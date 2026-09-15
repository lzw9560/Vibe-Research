# S203 — 龙头战法数字化改造（首板/接力/反包 + Dragon Score + 风控）

> 状态：**草案**（2026-09-14）。基于 6 领域专家 deep-analysis workflow + 6-lens 对抗验证（全 REVISE）+ 实测核事实。待 plan.md/tasks.md。
> 关联：[[../S201b2-carry-logic-fix/spec.md]]（path_return carry fix，本 spec 的 §44 harness 依赖）、[[../S198-衰竭regime条件翻转/spec.md]]（regime-stratified 先例，本 spec 周期胜率复用）、[[../S199-S194方向感知重测/spec.md]]（gap edge 外推禁令先例）。
> 上游工作流：`w50pptu5i`（6 专家+6 验证器，1M tokens）、`wc8g37bbx`（30 策略 §44 map，跨战法 CRITICAL 喂入 S204）。

## 1. 问题 / 目标

用户 brief（上次关闭的讨论）对龙头战法数字化改造给出 3 sub 优化 + Dragon Score + 风控指标。实测 Vibe 4 张打板战法卡后发现**语义错配 + 缺失**：

### 1.1 三战法语义错配（已核实代码）

| 用户 brief | Vibe 现有卡 | 错配（已核实） |
|---|---|---|
| 首板：板块共振法+封单额/流通市值>0.5%+板块内前3封板 | 龙头战法 `dragon_head`（gene_based.py:392, sector_rank≤3） | sector_rank≤3 是"个股板块内排名"≠"板块涨停家数≥N 共振"；无封单额门槛 |
| 接力二三板：成交量1.5-2.5x首板+当下连板序列 | 连板接力 `consecutive_relay`（gene_based.py:82, zt_count_250d≥2） | zt_count_250d 是"**历史**250日涨停频次"≠"**当下**连板≥2"（gene_scores 表实测有 zt_count_250d 列，7466 行，但语义是历史频次） |
| 反包板：龙头大跌触发量化止损后筹码真空+5/10日均线爆量反包吞没阴线 | 反包战法 `reverse_package`（db_based.py:25, open_count≥2 炸板触发） | 触发根本不同：Vibe 是"炸板后反包"≠用户"龙头大跌后反包" |

### 1.2 缺失

- **Dragon Score**（龙头多因子评分体系）——Vibe 无。gene_scores 是历史后验因子（涨停频次/封板率等），缺实时维度（封单额/板块共振/情绪周期）。
- **风控指标**——动态封成比（封单金额/全天成交额<5% 或撤单>30% 警剔炸板）、Tick 级机器止损、吃大面强制休息——Vibe 仅有 drawdown_breaker（M4 因子相关性>0.85），无盘中风控 gate。
- **情绪周期自适应仓位**（启动/高潮/退潮动态调仓）——Vibe STI 5-phase 分类器存在（limitup_sti/models.py:63），但实测 sti_timeline 33 日期，phase 分布冰点15/分歧12/启动6/**退潮=0 天/高潮=0 天**，无法验证 regime conditioner。

### 1.3 目标

1. 三战法语义修正（不删现有验证过的卡，新建/补条件）。
2. Dragon Score 5 维 composite 融合分（非 ML 特征，对齐 [[weight-as-ml-feature-is-inert]]）。
3. 风控 gate 落地（Vibe 侧可做件 + QMT 侧参考模板标 BLOCKER）。
4. 周期胜率 regime-stratified §44 验证（回答用户问③）。

## 2. 需求

### 2.1 首板优化（dragon_head 补条件，不删 sector_rank≤3）

- **R1**：match 加 C2 板块共振——`sector_strength_rank.zt_count_today ≥ 2`（板块涨停家数，sector_cycle.py:165 已有）。门槛值 ≥2 or ≥3 先标"探索性"跑 lift 后校准，**不硬编码 production**。
- **R2**：match 加 C3 封单精品门槛——`seal_to_float_ratio ≥ 0.005`（0.5%）。⚠️ 对抗审修正：model field 在 `limitup_screener/models.py:50`（非 "GeneScore models.py"），但 **gene_scores DB 表实测无 seal_to_float_ratio 列**（columns: date/code/name/total_score/factor_*/wilson_adjusted/qualify/high_gene/zt_count_250d/...），load_gene_scores 路径下恒 0.0——须 (a) 给 gene_scores DB 加列回补，或 (b) 把涨停池 raw seal_amount/float_shares 合并到 gene-match ctx（market_scan_ctx）。且现有 `limitup_strategy.py:232` 已有 `seal_to_float_ratio>=0.05`（5%），R2 用 0.5% 是 **10x 差异**，须解释依据（社区精品门槛 vs 现有底线过滤）。**须做 sensitivity sweep [0.3%, 0.5%, 0.7%, 1.0%]**——若 edge 仅在 0.5% 不在邻近值 → overfit。⚠️ `grep 'sweep|sensitivity' tools/*_lift.py` 全空，sweep harness 不存在（S204 R13 新建）——**§4 验收须把 sweep pass 列为 gate**，否则社区参数直接进 production。
- **R3**：封单门槛按市值段分层校准（大盘 vs 小盘 0.5% 绝对含义不同），不全局一刀切。

### 2.2 接力二三板优化（consecutive_relay 语义修正）

- **R4**：C1 从 `zt_count_250d ≥ 2` 改为 `lbc ≥ 2`（**当下**连板数≥2=二板以上）。lbc 字段在涨停池 raw data 有（models.py:236 h.boards=lbc）。zt_count_250d 降为 C2 辅助（历史频次加分不做门槛）。
- **R5**：**爆炸半径**——grep 所有引用 zt_count_250d 的代码（gene_scores 表列 + gene_based.py match + 可能的 lift harness），确认改 C1 不破坏其他依赖。
- **R6**：lianban_lift **已用 baostock**（实测 `lianban_lift.py` KLINE=baostock_kline_cache.json），非"改用 baostock 派生"——但 baostock bars 无 pctChg → is_unbuyable_next_bar 一字板误判可买 → lianban_lift returns **已被污染**，须**先等 S204 R14 pctChg 注入修复**后才可靠。⚠️ "172 天 2495 连板"数字无来源（baostock cache 实测 5231 codes/2111 dates 非 172；ths_lb_cache 43 dates/788 boards≥2 非 2495），删掉不可复现数字，"adequate n>200"结论待 R14 修复后重测。

### 2.3 反包板优化（新建，不改 reverse_package）

- **R7**：**不删 reverse_package**（有 629 笔 50.9%+1.07%/笔回测 + 实盘 357 笔 47.62% 验证）。
- **R8**：新建 `leader_drop_reversal` 战法卡——触发=核心龙头（sector_rank≤3 或 high_gene）T-N 日大跌（跌幅≥7%）+ T 日在 5/10 日均线处放量（close≥前日 open 且 open≤前日 close=吞没）+ volume_breakout_ratio≥1.2。
- **R9**：edge_type=`event`。**须跑 window sanity** 定位 edge 在哪个窗口（反包日→D+1/D+2/D+3 path），不能写死 path 窗口（§44v2 rule①，见 S204）。

### 2.4 Dragon Score（5 维 composite）

- **R10**：5 维 + 先验权重（非回测拟合，但 25/25/20/15/15 是 round numbers，标 overfit 风险）：

| 维度 | 权重 | 数据源（已核实存在） | overfit 风险 |
|---|---|---|---|
| 板块强度 | 25% | sector_strength_rank.zt_count_today（sector_cycle.py:165）+ 板块涨幅排名（sector_divergence.py:130 calculate_sector_divergence） | 中——门槛 N=2/3 须 walk-forward 校准 |
| 封单强度 | 25% | seal_to_float_ratio（limitup_screener/models.py:50，⚠️ gene_scores DB 无此列须 wiring）+ seal_slope（intraday_features.py 分钟级） | 高——0.5% 阈值社区来源，须市值段分层 + sensitivity sweep |
| 量能确认 | 20% | volume_breakout_ratio（pattern_scan.py:49）+ relay_vol_ratio（**待新增**，baostock K线派生）+ 换手率（涨停池 raw 有） | 高——1.5-2.5 倍区间社区来源，gap_window_lift 已证 gene_score 含换手率因子对 gap 无 selection edge |
| 情绪周期 | 15% | STI score（limitup_sti/models.py:63 5-phase+8维加权）+ 连板梯队（market.py:166） | 极高——退潮/高潮实测零天数据，MVP 用连续 score 不硬分三态，标"探索性 regime 标注"不进交易决策 |
| 技术形态 | 15% | MA5/MA10（baostock 可算）+ K线形态吞没/上影（OHLCV 可算）+ shadow_length_pct（pattern_scan.py 已有）+ ma5_slope（已有） | 中——形态判定参数（实体涨幅 X%）+ 位置 N日高点 lookback 须 walk-forward |

- **R11**：composite_formula = Σ(dimension_i_normalized × weight_i) → 0-100。归一化：板块强度=zt_count_today/全市场涨停均值封顶1.0；封单=seal_to_float_ratio/0.005 封顶1.0+seal_slope 正则加分；量能=relay_vol_ratio/2.0 封顶1.0；情绪=STI score/100；技术=MA 排列+形态命中数/3。
- **R12**：**非喂 ML 特征**（对齐 [[weight-as-ml-feature-is-inert]]）——分数本身是选股排序依据，不是喂模型的特征。
- **R13**：regime_adaptation——退潮期 Dragon Score 权重×0.5（对齐 §44v2 R3 enforce，但 R3 enforce 未落地见 S204），高潮×1.0，启动×1.2。⚠️ 实测退潮/高潮零天数据，**MVP 先用连续 STI score 不硬分三态，标探索性**，积累 60+ 天后验证三态是否真有预测力（须先验证 STI phase 作 regime conditioner 有 population edge——三态间 path return 均值差异须显著 ANOVA/Kruskal-Wallis，无 edge 则不加分）。

### 2.5 风控指标

- **R14**：动态封成比——`seal_amount / turnover < 5%` 黄色预警（Vibe 侧可做，em_get 涨停池有 seal_amount + amount）。
- **R15**：撤单率——⚠️ 实测 bidding_monitor.py:103/133 硬编码 `cancel_rate=0.0`（腾讯行情不含撤单率），sentiment_weather.py:501 原文"撤单比依赖盘口分笔数据，mootdx 不可得→仅用封单额阈值"。mootdx transactions() 返回成交分笔非委托队列，无法算撤单率。**用户"撤单>30%警剔"是硬约束，只有 L2 付费行情能拿**——标降级口径"仅 seal_amount 阈值，撤单比不可得"，诚实标注不臆造。接 L2 需用户付费决策（core-invariant：花钱须用户定）。
- **R16**：Tick 级机器止损——⚠️ Vibe 无 mootdx tick 实时管道（mootdx 0.11.7 已装于 .venv，Quotes.transactions() 可拉历史分笔 t0_simulator.py:57 已验证，但实时当日分笔流未接线+未测）。**回测用 baostock 5min kline 做可回测近似**（不用 daily OHLCV 做 VWAP 代理=look-ahead，验证器 HIGH）。
- **R17**：吃大面强制休息——单笔浮亏>5%→该 code 当日禁加仓，合计>8%→全账户禁开新仓+冷却。零件齐（risk_rules.py + at_risk.py + drawdown_breaker.py），**须从诊断升级为 enforce**。

### 2.6 代码模板（用户问②）

- **R18**：Vibe 侧信号+风控 gate 可落地（零件齐）——`generate_board_signal(code, limit_price, seal_ratio, dragon_score) → {code, trigger_price, seal_ratio, vwap, stop_price, max_size}` + `check_eligibility(code, intraday_breaker, drawdown_breaker) → bool`（IntradayLossBreaker+DrawdownBreaker 四层乘积 final_size=arm_size×portfolio_mult×lift_mult×intraday_mult）。
- **R19**：QMT 侧参考模板——`board_hit_trigger`/`vwap_stop`/`seal_ratio_monitor`/`big_loss_breaker`，**标 BLOCKER 放 `specs/S203/templates/` 不进 backend 生产代码**（Vibe 是研究看板无 xtquant/QMT 集成无下单路由，打板秒级竞争 Vibe 60s 轮询→QMT 执行信号延迟=不可用，须独立搭执行层）。

### 2.7 周期胜率（用户问③）

- **R20**：复用 gap_regime_stratified.py MA20 3-way（bull/bear/range，sh.000001 MA20+slope，index_ma20_regime.json 已有 cache），为 4 战法卡各写 `regime_stratified_*_lift.py`。
- **R21**：picks 按 D 日 regime 标签分层，算 per-regime net_mean/win_rate/day_clustered_t + §44v2 wire_verdict。**§44v2 rule①：前置 window sanity 定位 edge 在哪个 regime——不能跳过**（见 S204）。
- **R22**：regime-stratified per S198 precedent——但**不外推**（验证器 HIGH：S198 只证 gap 极性 regime-dependent，非"所有策略须 regime-stratified"；gap_window_lift 已证 gene_score 对 gap 无 selection edge lift 0.942x）。
- **R23**：STI 5-phase 待积累 60+ 天数据后做交叉验证（高潮/退潮零天数据 now）。

## 3. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/strategies/cards/龙头战法.yaml` 或 gene_based.py:392 | match 加 C2 板块共振 + C3 封单>0.5% |
| `backend/strategies/cards/连板接力.yaml` 或 gene_based.py:82 | C1 改 lbc≥2 替代 zt_count_250d（爆炸半径 grep 先确认） |
| `backend/strategies/cards/`（新建） | `leader_drop_reversal.yaml` 战法卡 |
| `backend/strategies/gene_score.py` 或新模块 | Dragon Score 5 维 composite（归一化+权重） |
| `backend/tools/lianban_lift.py` | 实测已用 baostock，须先等 S204 R14 pctChg 注入修复污染；删掉"172天"不可复现数字 |
| `backend/tools/regime_stratified_*_lift.py`（新建×4） | 4 战法 regime-stratified §44 harness |
| `backend/risk/`（risk_rules/at_risk/drawdown_breaker） | 吃大面从诊断升级 enforce |
| `backend/routers/bidding.py` | 封成比预警（seal_amount/turnover<5%）|
| `specs/S203/templates/`（新建） | QMT 侧参考模板（不进 backend 生产）|

## 4. 验收

- 三战法卡语义修正落地（首板加 C2/C3、接力 C1 改 lbc≥2、反包新建 leader_drop_reversal），每改一卡跑现有 §44 lift harness 对比改前改后。
- Dragon Score 5 维 composite 产出 0-100 分，各维度可单独跑 IC 定位 edge 在哪个窗口（§44v2 前置 sanity），无 edge 的维度不进融合。
- 风控 gate：封成比预警 + 吃大面 enforce（Vibe 侧），QMT 模板标 BLOCKER。
- 4 战法 regime-stratified §44 verdict（MA20 3-way），小 n regime 标 underpowered 不外推；Bonferroni K>8 拆≤8 子 phase 保严格（**不用 BH**，对齐 S204 §6 #9 决策；verifier.py:299-303 硬编码 selection 只 Bonferroni，BH 不参与 selection status）。
- 全 `pytest -m "not live"` 绿（含新 test）。
- 承重：不臆造（社区参数标探索性+sensitivity sweep）、私有数据隔离、防封（em_get 走限流）。

## 5. 合规自查

- 工程底线：不臆造（Dragon Score 维度+权重标 overfit 风险+sensitivity sweep；撤单率标降级口径不臆造）；私有数据隔离（无涉）；防封（em_get 走限流）。✓
- §44v2：本 spec 涉及 §44 验证，须过 §44v2 rule①（前置 window sanity，不能跳过）+ rule②（n-adequacy，小 n 标 underpowered 不外推）+ rule③（Bonferroni 按 n 调，K 冻结 pre-registration）+ rule④（R3 enforce，但未落地见 S204）。✓
- §44 不每阶段参与：本 spec 是战法数字化+方法论（regime-stratified §44），属"重大方法论变更"，6-lens grill 已起（w50pptu5i 全 REVISE，已核事实修正）。✓

## 6. 决策分叉（用户须定）

| 分叉 | 决策（2026-09-14 定） | 依据 |
|---|---|---|
| Dragon Score vs gene_score 关系 | 叠加（gene_score 作历史维度+Dragon Score 作实时维度，融合规则=Dragon Score 排序 gene_score 合格池内） | gene_scores 表实测 7466 行非空（有 zt_count_250d/factor_seal_rate/high_gene 列），叠加有基础；但 ~60 天 underpowered，先叠加后按 §44 结果决定是否替换 |
| sensitivity sweep 范围 | 封单[0.3/0.5/0.7/1.0%] + 量能[1.0/1.5/2.0/2.5/3.0x] + 板块[top1/top3/top5/top10] | 验证器实测无 sweep harness，须先建（移 S204） |
| 接力 C1 改 lbc≥2 爆炸半径 | grep zt_count_250d 全引用，确认 gene_scores 列+gene_based.py+lift harness 依赖后改 | 避免破坏其他依赖 |
| leader_drop_reversal 大跌阈值 | 跌幅≥7%（探索性，sensitivity sweep） | 社区参数标探索性 |
| QMT 模板范围 | Vibe 侧落地 + QMT 侧参考模板（不进生产） | Vibe 无券商 API，改架构=大型重构偏离定位 |
| 情绪周期定义 | **两者都做**（MA20 3-way 先出第一批 verdict + STI 5-phase 待高潮/退潮积累） | 用户定两者都做；实测 sti_timeline 33 天但 phase 分布冰点15/分歧12/启动6/**高潮=0/退潮=0**，STI 5-phase 高潮/退潮 verdict 会 underpowered（0 picks）直到积累；MA20 3-way 全 regime 有数据先出回答用户问③ |

## 7. 关键约束（来自 6-lens 对抗验证，已实测核事实）

> 6 验证器全 REVISE。以下已核事实 + 已识 §44v2 违规，作为本 spec 约束（非 raw 专家错误）：

- ✅ **gene_scores.db 非空**：3.37MB，6 表（gene_scores 7466 行，2026-07-13 起 eastmoney_live，**46 trading days** 实测非"~60 天"）。验证器 V2"0 字节空"**错**。但 46 天 <60 R6 gate → underpowered。
- ✅ **zt_history.db 非空**：2288 行/32 日期/564 行 zbc≥2（reverse_package 触发条件有数据），但 32<60 → underpowered。
- ✅ **mootdx 0.11.7 已装** .venv，Quotes.transactions() 可拉历史分笔（t0_simulator.py:57 已验证），但实时分笔流未接线+未测。验证器 V5"未装"**错**。
- ⚠️ **seal_intraday 仅 10 交易日**（8月3天+9月7天），封成比/炸板 intraday 回测不够。
- ⚠️ **STI 退潮/高潮零天数据**，dragon_score regime_adaptation 退潮×0.5/高潮×1.0 无数据可验，MVP 用连续 score。
- ⚠️ **撤单率全栈无数据源**（cancel_rate=0 硬编码），须 L2 付费（用户决策）。
- ⚠️ **§44v2 违规**（须 S204 修，对抗审修正）：①前置 window sanity 不能跳过；②R3 enforce **部分落地**（lift_to_multiplier 已接 scoring.py:69/verifier.py:130/evaluation.py，真实 gap 是 S197 P0(c) R3 task enforce + DIM_ARM_MAP arm-sizing 空转，非 trade_journal:400 那是显示标签）；③verifier 硬编码 selection 只用 Bonferroni（**verifier.py:299-303** 非 stats.py:299-303），BH 不参与 selection status；④walk_forward_oos 不做 train-refit（frozen/pre-registered），"train-refit overfit 检测"在 verifier 不存在；⑤sensitivity sweep harness 不存在；⑥event edge base_rate=0 null 牛市 drift 假阳性。
- ⚠️ **baostock bars 全无 pctChg**（2018+2025 都无）→ is_unbuyable_next_bar 一字板误判可买 → 污染 ALL backtest returns（S204 修）。
- ⚠️ **架构**（S204 R5/R6 已 resolution）：S049 D7 振荡 loop 防 → tracking_pool tracking 级 label（decayed）分离 workflow_state enum（实际 transition WATCHING→FILTERED 非→CANDIDATE，不加新 DECAYED 态保 invariants）；escalation promote pre-涨停候选须 ensure_candidate 联动（R7）。

## 8. 对抗审剩余 HIGH（plan.md 处理）

> wjiq1hkmz 对抗审 6 lens 全 REVISE，3 CRITICAL + 关键 HIGH 已在 §1.2/§4/§7 修。以下 HIGH 是 plan-implementation 细节，plan.md 须定：

- **DRY（overfit lens HIGH）**：Dragon Score 5 维 vs 现有 `first_board/scoring.py` 9 维系统（score_dim1_sector/score_dim_seal_ratio/score_dim_market_cap/score_dim_seal_time/score_dim_turnover 等）大量重叠。R10 未提及已有系统，权重 25/25/20/15/15 flat round-number vs 已有"按市场档位分层"更精细。plan 须定 Dragon Score 与 scoring.py 关系——复用/扩展/替代？若替代须说明为何弃档位分层改 flat。R2 seal 0.5% vs 现有 `limitup_strategy.py:232` 5%（10x）须解释依据。
- **R9 event drift（§44v2 lens HIGH）**：leader_drop_reversal edge_type=event 受 base_rate=0 drift（牛市假阳性）。plan 须引用 S204 R11 fix（event 也用 universe_by_day 两样本/减市场均值）或改 edge_type=selection（day_paired_lift 天然对冲 drift）+ 跑 window sanity 确认 edge 窗口。
- **§4 metric/verdict/sweep gate（testability HIGH）**：plan 须定义 (a) 对比 metric（如 day-paired lift net_mean），(b) pass 阈值（post-change lift ≥ pre-change OR net_mean>0），(c) regression 阈值（lift 掉>10%=block），(d) verdict pass enum（robust_edge/exploratory=pass？underpowered=provisional ship ×0.5？falsified=block），(e) sweep gate（edge 在≥2/4 邻近值=pass，单点=overfit→block production）。
- **§3 test files（testability HIGH）**：plan 须列 test_*.py（TDD），含 lianban_lift/first_board_layer_lift/gap_window_lift 等其他 lift harness 是否同步改（pctChg 依赖）。
- **R20 K-split（§44v2 HIGH）**：K=12（3 regime×4 战法）按 regime 拆 3 family 各 K=4，跨 regime Bonferroni-Holm 层级校正或标"每 regime family 独立 FWER，跨 regime 探索性"（详见 S204 R10）。
