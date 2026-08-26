# Spec: S094 — 战法分类与双 pipeline 统一底座重构

> 状态：**主体已实现**（S0-S5 功能核心 done；G4 backend pytest 2269 passed 0回归 + G5 frontend vitest 428 + tsc + vite build 双绿门）—— 2026-08-23 会话。Follow-up：T25 剩 4 polish bug（代码2次/P2判据/验证对齐/仓位摘要截断）/ T28 playwright e2e（需后端重启 + 可选写 s094 AC e2e spec）/ T19 前端 ContextTab 传 triplet.today。**判状态看 git log 不看本行。**
> 作者：Claude 会话  日期：2026-08-23
> 级别：**large**（跨层 + 双 pipeline 统一底座 + score_candidates 分流 + confidence 统一 + kline 扩容 + 5 根因修复 + UI 重设计）
> 流程门：spec.md + plan + task；feature 分支 `feature/S094-战法分类与双pipeline重构`；完整 grill；playwright 验收
> 依赖：S093 已合并（M4 归档）；**前置硬门：gene_scores 错位修复（S095）——✅ 已闭合（写路径守卫+交叉校验已实施 commit a6618df；08-13~08-21 七日重算 7/7 code 集合全等 commit ac22bac；2225 passed）**
> Oracle 第一轮：ora-6 完成，6 阻断 + 7 歧义，逐项吸收中

## 0. 起因

S093 验收后 grill 8 轮 + spec 审查 31 issue + 5 维度深度摸清，发现核心问题：**非涨停 pipeline 有两套互不相连的实现**（FLOW A score_candidates 涨停 pipeline 误跑非涨停战法 + FLOW B run_non_limitup_funnel 独立端点未接主 pipeline），spec 没摸清既有代码导致重复造轮子。

**5 维度精确根因**（基于代码证据）：

1. **两条非涨停数据流断裂**（FLOW A vs FLOW B）：FLOW A（score_candidates 跑全 12 战法含 dragon_head 无条件命中 → 涨停股 factors 无相对强度/均线多头 → 全 0）；FLOW B（run_non_limitup_funnel PatternScan 独立端点，未接 briefing）。两流数据契约断：A 用 gene 涨停因子 + compute_strategy_score；B 用 PatternScan 形态 + compute_non_limitup_score（硬编码权重）。
2. **6 根因（RC1-RC6）**：RC1 baostock cache 无 ma5/ma10/ma20（check_ma_bullish 恒 False）；RC2 scan_patterns 不传 sector_bars（relative_strength 退化为绝对涨幅）；RC3 两套权重源（NON_LIMITUP_WEIGHTS 硬编码 vs strategy_weights.json）；RC4 StrategyContext 无 market_scan_ctx 字段；RC5 score_candidates L511 丢弃 dispatch_match 产的 confidence/signal_strength；RC6 输出 schema 不一致（score vs strategy_score + 无 name）。
3. **score_candidates 跑全 12 战法**：不加 funnel_type 过滤 → dragon_head（非涨停）对涨停股跑 → 0 分；既有调用（workflow.py L222 / scheduled_tasks.py L1605）不传 funnel_type。
4. **zt_real 定位错**：不在 market._emotion（L272 len(zt) 东财 push2ex），在 _sentiment（L76 akshare legu "真实涨停"）；_sentiment 历史日返 {}（P0-1）。
5. **板块轮动修错对象**：前端 ContextTab 用 /api/strategy/funnel/sector-rotation（sector_cycle），非 /api/sector/rotation（sector_divergence 已弃用）；"未取得"根因**非 aggregate_sectors industry 缺**（ora-6 实测每个历史日 industry 满值），而是端点 date 必填无默认值 + 前端未传 date → 端点返空（ora-6 B5 修正）。
6. **kline cache 无非涨停股**：1121 只全涨停股 + FIELDS 无 ma5/ma10/ma20。
7. **🔴 gene_scores 历史行系统性错位一天**（Oracle 独立复现，08-13 起每一天）：写入时刻在 T 日晚，用盘中口径的东财池值算了 T+1 的基因标 T+1——每天偏移一个交易日。已用 code 集合相等验证（gs(08-18)=106 == zh(08-17)=106，全等；gs(08-19)=79 == zh(08-18)=79，全等；以此类推）。**FLOW A 候选输入（workflow.py L182 load_gene_scores）、R12 confidence 复用、R18 aggregate_sectors、backtest_lite/forward_test 全部坐在这份错位数据上。** 今天的 is_trading_day 守卫只防非交易日，防不住"交易日拿前一天池"这种错位。**前置硬门：S094 的 S2/S4 合并前必须完成 gene_scores 写路径修复（S095，spec 已立项实施）+ 历史行重算**。

用户要坚实工程底座（不修补，重构架构），避免返工。

## 1. 问题 / 目标

1. **统一双 pipeline 底座**：FLOW A + FLOW B 收敛为单一事实源——统一 K线契约 + 统一因子层 + 统一权重源 + 统一输出契约 + 统一候选输入
2. **战法分类分流**：12 战法按 funnel_type（7 limitup + 5 market_scan）分流，各对对应标的跑（涨停战法不对非涨停标的跑，反之亦然）
3. **score_candidates 分流 + confidence 统一**：加 funnel_type 参数 + 候选预分流契约 + 复用 dispatch_match 产的 compute_confidence（不派生）
4. **5 根因修复**：zt_real 显示层 / 板块轮动对对象 / kline cache 扩容 / MA 自算 / dragon_head 条件化
5. **UI 重设计**：双 pipeline 上下分区 + 折叠 + 卡片流转 + UI bug 修

## 2. 背景（现状挂载点，基于摸清）

- **FLOW A**（涨停 pipeline，briefing 消费）：workflow.py L177-227 load_gene_scores → cand_input → score_candidates L222 → dispatch_match（全 12 战法）→ scored_candidates → briefing 响应 → 前端 ForwardTabSection/StrategyMatchMatrix
- **FLOW B**（非涨停 pipeline，独立端点）：routers/strategy.py L245 /api/strategy/non-limitup-funnel → sector_rotation（TOP 板块）→ load_industry_map → get_sector_stocks → bars=cache.get(code)（len≥20）→ run_non_limitup_funnel L279 → scan_patterns（sector_bars=None 退化）→ compute_non_limitup_score（NON_LIMITUP_WEIGHTS 硬编码）→ 前端 NonLimitupLane（c.score/c.name 失配）
- **既有模块可复用**：strategies/non_limitup_funnel.py（run_non_limitup_funnel/compute_non_limitup_score）+ pattern_scan.py（compute_relative_strength/check_ma_bullish/compute_consolidation/compute_volume_breakout/compute_ma5_proximity/scan_patterns）+ sector_cycle.py（sector_strength_rank/aggregate_sectors/sector_rotation）+ strategy_base.py（dispatch_match L216 compute_confidence）+ compute_strategy_score（weight_set 机制）
- **zt_real**：market.py _sentiment L76（akshare legu "真实涨停"），历史日返 {}；_emotion L272 zt_count=len(zt) 东财 push2ex；下游 limitup_sti/service.py L164/L176 + workflow _market_emotion_from_ctx（ctx 路径读 sti_timeline）
- **板块轮动前端**：ContextTab.tsx L31-39 用 /api/strategy/funnel/sector-rotation（sector_cycle），sector_divergence 已弃用
- **kline cache**：baostock_kline_cache.json 1121 只全涨停股，FIELDS 无 ma5/ma10/ma20，refresh_kline_cache.py 增量不扩容

## 3. 需求清单（9 点坚实底座）

### A. 统一 K线契约（修 RC1/RC2）
- [ ] R1 pattern_scan 自算 MA（_compute_ma(bars,n) 由 close 序列算 ma5/ma10/ma20），不依赖 cache 字段
- [ ] R2 run_non_limitup_funnel L242 传 sector_bars（板块等权平均日K），compute_relative_strength 真为相对值

### B. 统一因子层 + 权重源（修 RC3）
- [ ] R3 删 non_limitup_funnel.py L48 NON_LIMITUP_WEIGHTS 硬编码
- [ ] R4 ~~compute_non_limitup_score 委托 compute_strategy_score(weight_set="non_limitup")~~ **（ora-6 B6 + ora-7 N3 拍板：不委托，下沉 match 层）**：per-strategy volume_signal 计算下沉到各战法 match() 内部——`compute_volume_signal_score`（non_limitup_funnel.py L86-120）按战法分支逻辑迁入对应 Strategy.match()，match 返回时把 volume_signal 填入 signals 的 confidence/signal_strength 字段（dispatch_match 已产这两个字段，strategy_base.py L252-253）。候选 factors 仍用**单一一份 PatternScan factors dict**（中文键 `{相对强度, 均线多头, 量能信号, 板块强度}`，0-100 值，复用既有 compute_relative_strength_score 等 4 个映射函数 non_limitup_funnel.py L60-137），per-strategy 差异在 match 层处理，不在候选层。**R14 候选 shape 不加 strategy_factors 字段**（单一 factors 够用，per-strategy 逻辑在 match 层）
- [ ] R5 PatternScan 升为 market_scan 唯一因子事实源，indicator_based PatternReversalStrategy 改读 PatternScan（不读 ctx.indicators）

### C. StrategyContext 扩展 + match 分流（修 RC4，R5/R6/R7）
- [ ] R6 StrategyContext L47 加可选 market_scan_ctx：{pattern: PatternScan, sector_rank: int, rel_strength_vs_sector: float}
- [ ] R7 score_candidates 加 funnel_type 参数：limitup 用 gene ctx 跑 7 涨停战法；market_scan 用 market_scan_ctx 跑 5 非涨停战法，二者不交叉
- [ ] R8 既有调用点传 funnel_type：workflow.py _collect（涨停候选 limitup + 非涨停候选 market_scan 两次调）+ scheduled_tasks.py L1605（limitup）——**ora-7 N8：删 pre_market_workflow（走 StrategyMatcher 不调 score_candidates）；补 forward_test.py L491（调 score_candidates，传 limitup）**
- [ ] R9 DragonHeadStrategy.match L180 删无条件放行，改读 market_scan_ctx.rel_strength_vs_sector + sector_rank（板块内排名≤3 才命中）——**ora-6 A3：dispatch_match 经共享，波及所有 match_strategies 消费方（pre_market_workflow L174、workflow.py L860、strategy_backtest L145/L236、prediction_ingest L99、position_advisor_v2 L196），这些上下文无 market_scan_ctx → dragon_head + 4 形态战法从"可能命中"变"永不命中"——涨停股场景本就不该命中这 5 个非涨停战法，方向大概率对，但 spec 须显式声明行为变化面而非默认**。另注意 **pre_market_workflow 不调 score_candidates**（走 StrategyMatcher），R8 里"pre_market_workflow 传 funnel_type"表述有误，删
- [ ] R10 3 K线形态战法（low_absorption/platform_breakout/pattern_reversal）match 改读 PatternScan（consolidation_days/ma5_proximity/volume_breakout）——**reverse_package 不在 R10**（ora-6 A6：reverse_package 注册在 market_scan 但 match 在 db_based.py 读炸板池，本质是涨停生态战法，保留 db-based 不改读 PatternScan；§4 受影响文件 db_based.py 补列）**

### D. 板块领涨子（R3 补）
- [ ] R11 新增 compute_sector_stock_rank(code, sector_stocks, bars_map)：板块内按 relative_strength 降序排名（个股内，非 sector_strength_rank 板块间）

### E. 统一输出契约（修 RC5/RC6，R8 confidence）
- [ ] R12 score_candidates 复用 dispatch_match 产的 compute_confidence（L511 不丢弃，从 signals 取 confidence/signal_strength 填 scored_candidates）
- [ ] R13 ~~run_non_limitup_funnel 输出对齐 scored_candidates schema~~ **（ora-6 A4：R27 把 run_non_limitup_funnel 拆成"只产候选不打分"后，独立端点 /api/strategy/non-limitup-funnel 的输出契约会断——前端 NonLimitupLane 消费它拿打分结果。R13 与 R27 互相矛盾。拍板：独立端点同步切换为"产候选 → score_candidates(market_scan)"，R13 改为对齐该新路径的输出 schema：加 name + confidence + signal_strength，字段名统一 strategy_score）**

### F. 候选输入统一（修 RC6）
- [ ] R14 FLOW B 候选扩为 {code,name,bars,sector,sector_rank,close}，与 FLOW A cand_input 对齐，score_candidates 单一入口服务两 funnel_type——**ora-7 N6：name 来源 = 从 `code_industry` 表反查（code→name 字段已存在，load_industry_map 已在产），kline cache FIELDS 无 name 字段故不从 bar 取**

### G. zt_real 显示层修（根因 4）
- [ ] R15 ~~前端读 briefing.market_emotion.zt_count 正确字段~~ **（ora-6 B2 阻断：market_emotion 无 zt_real 字段，zt_count 是东财池 len 非"真实涨停"，方案不可行——删）**
- [ ] R16 zt_real 持久化 + 显示层修（ora-6 A1 拍板：R16 变体）：
  - `market.py _emotion` 加 `zt_real` 字段（latest 日从 `_sentiment` 拉 akshare legu "真实涨停"；历史日返 None，不臆造）
  - `sti_timeline` schema 加 `zt_real` 列 + `_execute_sti_post_market`（scheduled_tasks L655-708）存 zt_real（latest 日算）
  - `_market_emotion_from_ctx` 读 `zt_real` 维度（历史日读 DB 持久化值，不依赖 akshare 历史源）
  - 前端 `briefing.market_emotion.zt_real` 显示真实涨停；`zt_count` 保留供内部（seal_rate/promotion/STI 内部一致性不动）
- [ ] R17 refresh 快照（pre-market/refresh 调 _collect 重算 market_emotion）

### H. 板块轮动修对对象（根因 5）
- [ ] R18 板块轮动根因=date=None 默认 localTodayStr（非交易日空，**非 industry 缺**——08-21 industry 54/54 有值端点返 10 板块），修：后端 /api/strategy/funnel/sector-rotation 端点 date=None 默认 last_trading_date_str（routers/strategy.py）+ 前端 ContextTab 传 triplet.today
- [ ] R19 ~~删 sector_divergence calculate_sector_rotation L207-209 prev_sectors.copy() TODO~~ **（ora-7 N5 拍板：砍掉——前端已弃用 sector_divergence（ContextTab L31 注释实锤），残留消费仅 api.ts L212 + test_s008_t13e + smoke_test_apis，无消费方值得保留；§4 表 sector_divergence.py 行删 R19、§10 S4 删 R19、§7 删 R19 引用）**

### I. kline cache 扩容（根因 6）
- [ ] R20 baostock 全 A ~5500 刷新任务（非增量 list(cache.keys())，扩容到非涨停股）——**ora-6 非阻断 #1：全 A 代码可直接复用 `load_industry_map()`（5540 条已在产），不必调 baostock `query_stock_basic`（已式微）；扩容后 cache ~150MB，routers/strategy.py:267 每请求 json.loads 全量需配套模块级 memo 或迁 sqlite/parquet；"1-2h"改"预估 2-3h 实测为准"**
- [ ] ~~R21 MA 在消费侧算（R1 自算），不依赖 cache 字段~~ **（ora-6 非阻断 #3：与 R1 完全重复，合并到 R1，删）**

### J. UI 重设计
- [ ] R22 前瞻 Tab 双 pipeline 上下分区 + 折叠收缩（涨停 pipeline 主展开 / 非涨停+辅助折叠）+ region 级 vs 卡片级折叠层级
- [ ] R23 卡片按 pipeline 流转顺序（①涨停池②涨停战法③breakout 弱信号④交叉验证 / ⑤板块领涨⑥K线形态⑦非涨停战法）
- [ ] R24 StrategyMatchMatrix 涨停/非涨停分区（单组件内分区或两实例，②⑦ 分置两 region）
- [ ] R25 UI bug 修：板块轮动"更多信息"股票代码 2 次（SectorCyclePanel）/ 仓位摘要截断（Workflow.tsx advisory 内联 L357-426）/ P2 仓位闸显示（P2RiskPanel，补现象判据）/ 验证对 spec（VerificationCard，指明对齐哪条）/ 定稿失配（SelectionPipeline 定稿节点对齐 final_candidates）

### K. 双 pipeline 收敛数据流（第 10 问 a 定）
- [ ] R26 workflow.py `_collect` 调 `gather_non_limitup_candidates(date)`（抽自 routers/strategy.py 端点：sector_rotation→load_industry_map→get_sector_stocks→bars）产非涨停候选 → 喂 `run_non_limitup_funnel(candidates, weather, sector_rank_map)` 产 PatternScan factors → `score_candidates(candidates, funnel_type="market_scan")`（run_non_limitup_funnel 签名是消费候选不产候选不接 date，故抽 gather 函数）
- [ ] R27 `run_non_limitup_funnel` 拆"产候选"+"打分"：只产候选（PatternScan factors + sector_rank + close），删自打分 `compute_non_limitup_score` 调用（打分归 score_candidates 统一入口）+ **score_candidates market_scan 分支调 check_quality_standards + passes_hard_standards（硬剔除闸前移，不丢 S075 硬剔除底线）**
- [ ] R28 briefing 响应分区透传：涨停 scored_candidates（limitup）+ 非涨停 scored_candidates（market_scan），前端双 pipeline 分区消费

### L. 各 R 细节定稿（grill 收敛）
- R1 `_compute_ma(bars, n)` = SMA（close[-n:]/n），n=5/10/20，bars<20 返 None（诚实降级）；放 pattern_scan.py，PatternScan 自持 TA
- R2 `sector_bars` = 板块成分股等权平均日K（close/high/low/volume 简单平均），compute_relative_strength 真为相对值（个股5日涨幅-板块5日涨幅）——**ora-6 A5：成分股集合=板块全成分（有 bar 者参与），停牌/缺 bar 按日期对齐取交集，写进定稿**
- R5 PatternReversal 沿用"长上影洗盘修复"形态——**ora-7 N2 完整定义**：
  - **新增 compute_\* 函数签名**：`compute_shadow_length_pct(bars) -> float` = `(high[-1] / close[-1] - 1) * 100`（复用既有先例 `candidate_funnel/sources/activity.py` L112-114 口径）；`compute_ma5_slope(bars) -> float` = `(ma5[-1] - ma5[-2]) / ma5[-2]`（ma5 用 R1 的 `_compute_ma(bars, 5)` 算，slope>0 即"向上"，阈值 0——零定义补齐）
  - **5 因子→3 字段删减显式声明**：原 5 因子（未封涨停 + 最高≥7% + 上影≥4% + 放量1.2x + 5日线向上）→ PatternScan 3 字段（shadow_length_pct≥4 + volume_breakout_ratio≥1.2 + ma5_slope>0），"未封涨停"和"最高≥7%"删减——理由：PatternScan 是 K线形态层不包含涨停判定（涨停判定在战法 match 层用 pool_item.lbc/zbc），"最高≥7%"与"上影≥4%"语义重叠（上影大则最高也大），保留上影更精确
  - **放量口径变更结论**：现 indicator_based 今量/昨量≥1.2 改为 PatternScan volume_breakout_ratio 今量/前5日均量≥1.2——阈值沿用 1.2（数据支撑优先：口径变但 1.2 是保守值，前5日均量比昨量更稳定，阈值不变是保守选择，实现后回测验证调参）
  - 改读 PatternScan 不读 ctx.indicators；spec §3"突破昨日最高"作废
- R16 zt_real 持久化：sti_timeline schema 加 zt_real 列 + `_execute_sti_post_market`（scheduled_tasks L672-690）存 zt_real（latest 日算）+ `_market_emotion_from_ctx` 读 zt_real 维度（历史日读 DB，不依赖 akshare 历史源）
- R18 板块轮动根因修正（ora-6 B5 收敛三处矛盾）：根因**非 aggregate_sectors industry 缺**（ora-6 实测每个历史日 industry 都是满值，save_gene_scores L112 code_industry 兜底），真正根因是端点 `/api/strategy/funnel/sector-rotation` date 参数必填无默认值 + 前端未传 date → 端点返空。修法：后端端点 date 默认 `last_trading_date_str()`（routers/strategy.py 改），前端 ContextTab 传 `triplet.today`（非交易日=F=最近交易日）。叠加 B1 错位影响：历史日聚合的是前一天的池（错位修复后自动消解）
- R4 per-strategy volume_signal 下沉 match 层（ora-7 N3 拍板，与 §3.R4 一致）：`compute_volume_signal_score`（non_limitup_funnel.py L86-120）按战法分支逻辑（platform_breakout volume_breakout_ratio>2 / reverse_package 成交额>15亿 / low_absorption >5亿 / dragon_head >10亿）迁入对应 Strategy.match()，match 返回时填入 signals 的 confidence/signal_strength 字段。候选 factors 仍用单一一份 PatternScan factors dict（中文键 `{相对强度, 均线多头, 量能信号, 板块强度}`，0-100 值，复用既有 compute_relative_strength_score 等 4 个映射函数 non_limitup_funnel.py L60-137）。R14 候选 shape 不加 strategy_factors 字段
- R20 kline cache 扩容：**ora-6 非阻断 #1 已吸收——复用 `load_industry_map()`（5540 条已在产）取全 A 代码（非 baostock `query_stock_basic` 已式微）+ 一次性扩容（周末/盘后跑，预估 2-3h 实测为准）+ 后续增量维护；扩容后 cache ~150MB 需配套模块级 memo 或迁 sqlite/parquet** + 后续增量维护（5500 append 新 bar）

### M. 实施细节定稿（grill 第 2 轮收敛）
- **12 战法归组表**（STRATEGIES_BY_FUNNEL_TYPE）：
  - limitup（7）：first_plate 首板挖掘 / consecutive_relay 连板接力 / break_reseal 炸板回封 / n_shape_counterattack N字反击 / end_of_day_sneak 尾盘偷袭 / weak_turn_strong 弱转强接力 / storm_reversal 暴风雨逆势涨停
  - market_scan（5）：dragon_head 龙头 / low_absorption 低吸 / reverse_package 反包 / platform_breakout 平台突破 / pattern_reversal 形态反包
- **funnel_type 默认**：必填（无默认 None=全跑）——None=全跑与 R7"不交叉"矛盾 + market_scan_ctx 缺失 crash。既有调用（workflow/scheduled_tasks L1605）传 limitup；market_scan 调用传 market_scan
- **模块归属**：新建 `market_scan.py`（因子层+形态子+领涨子 compute_sector_stock_rank）；`non_limitup_funnel.py` 保留 `run_non_limitup_funnel` 瘦身为"调 market_scan 产候选"入口（R27 拆分后只产候选不打分）。删 §4"或"字样
- **PatternScan 字段清单**（R10 + R5 对齐）：
  - pattern_reversal = shadow_length_pct / volume_breakout_ratio / ma5_slope（长上影洗盘修复）——**ora-7 N2：统一用 ma5_slope（非 ma_bullish），与 R5 一致**
  - low_absorption = ma5_proximity（均线回调）/ ma_bullish
  - reverse_package = 保留炸板池 db-based（open_count>=2，非 K线形态子——口径修正，单列 db 子）
  - platform_breakout = consolidation_days / volume_breakout（突破平台）
- **性能预算**（market_scan pipeline）：top N 板块上限（如 10）+ 每板块成分股上限 ≤50 + scan_patterns 超时熔断 + 候选 cap ≤30 喂 score_candidates（5500 股全扫分钟级超时，故限定 top 板块成分股）

## 4. 受影响文件

### 后端
| 文件 | 改动 |
|---|---|
| `strategies/pattern_scan.py` | R1 自算 MA + R2 传 sector_bars + R5 因子事实源 |
| `strategies/non_limitup_funnel.py` | R3 删硬编码权重 + R4 ~~委托~~**不委托**（volume_signal 下沉 match 层）+ R14 候选扩字段 |
| `strategies/strategy_base.py` | R6 StrategyContext 加 market_scan_ctx |
| `strategies/strategy_funnel_registry.py` | R7 score_candidates 加 funnel_type + R12 复用 confidence + R13 输出对齐 |
| `strategies/impl/gene_based.py` | R9 DragonHead 条件化 + ~~R10 4 战法 match 改读 PatternScan~~（R10 改 3 战法，reverse_package 不在，ora-6 A6） |
| `strategies/impl/db_based.py` | R10 reverse_package 保留 db-based 不改读 PatternScan（ora-6 A6 补列，§4 漏列修复） |
| `strategies/impl/indicator_based.py` | R5 PatternReversal 改读 PatternScan |
| `strategies/sector_cycle.py` | R11 compute_sector_stock_rank |
| `routers/strategy.py` | R18 端点 date 默认 `last_trading_date_str()` + R13 /api/strategy/non-limitup-funnel 对齐新 schema（ora-7 N7 归属修正，合并为一行） |
| `strategies/market_scan.py`（新建） | R11 板块领涨子 compute_sector_stock_rank（复用既有函数，非重写） |
| `routers/workflow.py` | R8 传 funnel_type + 双 pipeline 响应 |
| `scheduled_tasks.py` | R8 L1605 传 funnel_type |
| `market.py` | R16 _emotion 加 zt_real 字段（可选） |
| ~~`sector_divergence.py`~~ | ~~R19 删 prev_sectors TODO~~ **（ora-7 N5 砍掉，前端已弃用，§4 行删）** |
| `tools/refresh_kline_cache.py` | R20 扩容全 A |

### 前端
| 文件 | 改动 |
|---|---|
| `Workflow.tsx` | R22 双 pipeline 分区+折叠 + R23 卡片流转 + 仓位摘要内联修 |
| `StrategyMatchMatrix.tsx` | R24 涨停/非涨停分区 |
| `SectorCyclePanel.tsx` | R25 代码 2 次修 |
| `P2RiskPanel.tsx` | R25 P2 显示 |
| `VerificationCardBlock.tsx` | R25 验证对 spec |
| `NonLimitupPlaceholder.tsx` | R13 对齐新 schema（c.score→c.strategy_score） |
| `components/pipeline/SelectionPipeline.tsx` | R25 定稿失配 |

## 5. 验收标准

- [x] AC1 战法分类分流正确（7 limitup + 5 market_scan，各对对应标的跑，dragon_head 不对涨停股跑——条件化 match）
- [x] AC2 双 pipeline 统一底座（**ora-6 A7：= AC3+AC6+AC7+AC8 合称，无独立可测判据，降级为合称标注**）
- [x] AC3 score_candidates funnel_type 分流 + confidence 复用（不再全 None/0，从 dispatch_match 取）
- [x] AC4 zt_real 显示层修（market_emotion 加 zt_real 字段 + sti_timeline 持久化 + 历史日读 DB 值，不破坏 _emotion 内部 zt_count）
- [x] AC5 板块轮动不再"未取得"（sector_cycle 端点 date 默认 last_trading_date_str + 前端传 triplet.today；非 aggregate_sectors industry 缺——ora-6 B5 实测 industry 54/54 满值）
- [x] AC6 kline cache 扩容非涨停股 + MA 消费侧算
- [x] AC7 pattern_scan MA 自算（check_ma_bullish 不恒 False）+ relative_strength 相对值（传 sector_bars）
- [x] AC8 UI 双 pipeline 分区+折叠+卡片流转
- [x] AC9 UI bug 修（代码2次/摘要/P2/验证/定稿失配）——T25 5/5 done（P2 判据→S096 落地）
- [x] AC10 离线全测绿（pytest 2269 + vitest 428 + tsc + vite build 双绿门）
- [x] AC11 playwright e2e——T28 done（`s094-dual-pipeline.spec.ts` 4 测全绿：涨停叉②/非涨停叉⑦切换/结构不崩/S097 漏斗空态 R15 降级）

## 6. 设计取舍

1. **统一底座非接入修补**——FLOW A+B 收敛单一事实源（用户要求坚实底座，不返工修补）
2. **复用既有函数**（pattern_scan compute_* / sector_cycle / compute_strategy_score），不重写算法
3. **PatternScan 升 market_scan 唯一因子源**——消灭 indicator_based 第三条算路
4. **confidence 复用 dispatch_match**（不派生 strategy_score/100，保留 per-strategy 语义）
5. **zt_real 持久化+显示层修**（R16 变体：_emotion 加 zt_real 字段 + sti_timeline 持久化 + 历史日读 DB，ora-7 A1 拍板；不改 _emotion 内部 zt_count）
6. **kline cache 扩容 + MA 消费侧算**（不依赖 cache 字段）
7. **UI 上下分区+折叠**（涨停主/非涨停次）

## 7. 合规自查

- [x] 不臆造：score_candidates 分流 + match 条件化，数据缺标 None 不命中；板块轮动 rotation_speed 不造假值（R19 已砍，ora-7 N5）
- [x] 私有数据 .vibe-research/ 不进 git
- [x] em_get 防封：kline 用 baostock（非东财不被限流）；板块用 sector/industry（既有防封）
- [x] 历史统计特征标注

## 8. 已知盲点（基于摸清已收敛大部分）

1. ~~market_scan 新建工作量~~→复用既有 non_limitup_funnel/pattern_scan/sector_cycle（不重写）
2. K线形态 3 战法 match 改读 PatternScan——R10 给 consolidation_days/ma5_proximity/volume_breakout_ratio 阈值（复用既有 compute_*，阈值沿用既有默认值，实现后回测验证调参，按数据支撑优先规则）
3. 板块领涨 compute_sector_stock_rank——个股内排名（R11，复用 relative_strength）
4. confidence 口径——复用 compute_confidence（R12，不派生，收敛）
5. zt_real akshare legu "真实涨停"口径——R16 持久化+显示层（R15 已删，ora-6 B2；不改 _emotion 内部 zt_count）
6. 板块轮动端点 date 默认值缺失——R18 修端点 date 默认 `last_trading_date_str()` + 前端传 triplet.today（非 aggregate_sectors industry 缺，ora-6 B5 修正）
7. kline cache 扩容——R20 baostock 全 A 刷新任务

## 9. 冲突审查

| 旧 spec/代码 | 旧决策 | S094 决策 | 处置 | 迁移路径 |
|---|---|---|---|---|
| S093 R4 前瞻 pipeline | 涨停单 pipeline | 双 pipeline 统一底座 | 替换 | Workflow.tsx 双分区 + FLOW A+B 收敛 |
| S086 score_candidates | 跑全 12 战法 | funnel_type 分流 | 替换 | strategy_funnel_registry.py 加 funnel_type |
| S066 non_limitup_funnel | 独立端点 FLOW B | 接入主 pipeline + 统一底座 | 共存+重构 | non_limitup_funnel.py volume_signal 下沉 match 层 + 输出对齐 |
| NON_LIMITUP_WEIGHTS 硬编码 | L48 硬编码 | 删，委托 strategy_weights.json | 替换 | non_limitup_funnel.py L48 删 |
| market zt_count | len(zt) 东财 | 显示层 zt_real / _emotion 加字段 | 共存 | market.py 加 zt_real + 前端读 |
| sector_divergence 板块轮动 | 前端用 | 前端弃用，改 sector_cycle | 替换 | ContextTab 已改，R18 修 sector_cycle |
| baostock cache 1121 | 增量不扩容 | 全 A 扩容 | 替换 | refresh_kline_cache.py 全 A |

## 10. 阶段划分（ora-6 B4 重排：消除 S2 依赖 S3 倒置 + R26-R28 归属）

### S0 前置硬门：gene_scores 错位修复（S095）——✅ 已闭合，见 `specs/S095-gene_scores写路径修复与日期守卫/`

### S1 统一 K线契约 + 因子层 + 权重源（R1-R5）
- pattern_scan 自算 MA + 扩 compute_shadow_length_pct/compute_ma5_slope（B3）+ 传 sector_bars + 删 NON_LIMITUP_WEIGHTS + **不委托**（volume_signal 下沉 match 层，B6）+ PatternScan 升唯一源

### S2 候选生产拆分 + sector_rank（R11/R14/R27）← ora-6 重排：sector_rank 前置
- compute_sector_stock_rank（R11）+ FLOW B 候选扩字段（R14）+ run_non_limitup_funnel 拆"只产候选"（R27）+ market_scan.py 新建（因子层+形态子+领涨子）

### S3 StrategyContext 扩展 + match 分流 + confidence（R6-R13/R26/R28）
- StrategyContext market_scan_ctx + score_candidates funnel_type + 既有调用传（含 forward_test L491，ora-6 A2）+ dragon_head 条件化 + 4 战法 match 改 PatternScan + confidence 复用 + R26 workflow._collect 调 gather_non_limitup_candidates + R28 briefing 分区透传

### S4 5 根因修复（R16-R20）← ora-8 A5：R15/R19/R21 已删，区间收拢
- zt_real 持久化 + 板块轮动端点 date 默认 + kline cache 扩容（R20 全 A 代码复用 load_industry_map 5540 条，ora-6 非阻断 #1）

### S5 前端 UI（R22-R25）
- 双 pipeline 分区+折叠 + 卡片流转 + StrategyMatchMatrix 分区 + UI bug

### S6 全量回归 + playwright
- pytest + vitest + tsc + vite build + playwright e2e AC1-AC11

---

## 11. 前瞻 Tab 重构附录（2026-08-24，grill 决议）

> 本附录为 S094 UI 部分的演进决议，与 §5.J（R22-R25）并存——R22 被下方 A1 显式推翻，R23 流转顺序被 A2 扩展。按 AGENTS.md「spec 逻辑冲突审查」规则显式记录处置，不留暗债。

### A1. R22 推翻：上下分区+折叠 → 同页互斥切换

**旧决策**（R22）：涨停叉主展开 + 非涨停叉 `CollapsibleFold` 折叠，上下分区同屏。
**问题**：上下分区是「前瞻页太长」的根因——涨停叉 6 节点 + 非涨停折叠 + ②③④⑤ 堆叠下方，纵向滚动负担大、决策链割裂。
**新决策**：`SelectionPipeline` 内部 `activeLane` state + segmented control，**涨停叉 | 非涨停叉 互斥切换，默认涨停**，一次只显一叉；无"全部"选项（保留即没解决根因）。
**迁移路径**：`SelectionPipeline.tsx` fork prop 降级为初始值；`CandidateFunnelEmbed` 不改（不传 fork）；R22"涨停主/非涨停次"精神从折叠程度改为默认显示项。
**处置**：替换。

### A2. 共享区结构扩展（R23 增补）

R23 原为两叉纯线性序列，无共享区概念。本次增补：

- **前置共享区**（两叉共用，只显一次，辅助角色）：
  - 板块轮动（涨停叉看语境 / 非涨停叉定选股宇宙（⑤）——同一数据链两端，禁止两处重复渲染）
  - 语境 `ContextTab`（可展开）
  - 情绪天气 `WeatherDecisionBar`（T-1）
- **后置共享区**（两叉共用，只显一次）：
  - 风控非对称 + P2 仓位（advisory 摘要并入此区，不重复展示；独立页 `/advisory` 保留为详情入口）

**最终布局**（替换 §5.J R22/R23 的前端呈现）：

```
前瞻 Tab
├─ 前置共享区：板块轮动 · 语境 · 情绪天气（T-1）
├─ [涨停叉 | 非涨停叉] 切换（默认涨停）
├─ 涨停叉：① 涨停股池 → R1 过滤 → ② 战法匹配（7 战法分组视图）
│          → ③ breakout 弱信号 → ④ 交叉验证
├─ 非涨停叉：⑤ 选股宇宙（板块 TOP-N 成分股）→ ⑥ K线形态
│            → ⑦ 战法匹配（5 战法分组视图）→ ⑧ 候选终选
└─ 后置共享区：风控 + P2 仓位
```

### A3. 因子下沉边界（基因打分拆解决议）

**背景**：grill 中曾提议「基因打分作为过滤环插入选股漏斗」。经查 `funnel.py` 现状（R1 仅名称剔除、R2/R3 已直通下放战法）+ S084 TASK A 决议，该提议违反「选股池 = 全体战法标的 superset」——全局基因过滤会预筛掉弱转强等低基因特征标的，重演 R2/R3 预筛错误。**撤销该提议。**

**采纳形态**：因子评分**下沉拆解为各战法 sub-pipeline 内部的判断条件**——每个战法子管线按自己的因子条件过滤，**禁止**在战法之前设置全局因子过滤节点：

| 战法 | 因子条件归属 |
|---|---|
| first_plate 首板挖掘 | 基因分≥60 + 涨停频次>20（现有隐式门槛显式化） |
| consecutive_relay / break_reseal / n_shape / end_of_day_sneak / storm_reversal | 各战法自定义因子条件 |
| weak_turn_strong 弱转强 | **不用基因分**（低基因是特征，不能被筛掉） |

因子过滤环的渲染与实现见后续 **S097 逐条件因子过滤**（本附录 A2 的②⑦分组视图为其第一阶段载体）。

### A4. 删除/融入清单（去噪）

| 卡片 | 处置 | 理由 |
|---|---|---|
| 因子漏斗 `FactorSection` | 融入②⑦战法分组视图 | 数据链 = limitup_screener = 选股漏斗上游评分，前瞻页重复展示 |
| advisory 摘要 + 仓位详情入口 | 并入后置共享区 | 独立页 `/advisory` 已有，前瞻只留最终推荐 |
| T1Tab | 删除 | 工程核查页（数据新鲜度），非决策信息 |
| "辅助决策" `CollapsibleFold` | 拆开，拆入前置共享区后删除 | 折叠深藏降低使用率 |

### A5. 冲突审查表（追加，按 §9 格式）

| 旧决策 | 新决策 | 处置 | 迁移路径 |
|---|---|---|---|
| R22 上下分区+折叠 | 同页互斥切换（默认涨停） | 替换 | SelectionPipeline activeLane state + segmented control |
| R23 纯线性①-⑦ | 增补前置/后置共享区结构 | 扩展 | Workflow.tsx ForwardTabSection 重组 |
| 基因打分独立漏斗卡片 | 因子下沉战法子管线条件 | 替换 | 因子漏斗删，因子过滤进②⑦分组视图（S097 载体） |
| advisory 前瞻摘要 | 并入后置共享区 | 替换 | /advisory 独立页保留 |

### A6. Follow-up

- **S097 — 逐条件因子过滤**：12 战法 `match()` 重构返回条件级过滤明细（每条件 输入数/过滤后数/条件描述），前端每战法子管线渲染「因子条件 → 过滤数」明细漏斗。**待开独立 spec**（预计 medium，跨层）。

### A7. 待办：孤立组件处置

审计发现两个更早 spec 的遗留组件（与 S094 重构无关），处置如下：

| 组件 | 来源 spec | 处置 | 状态 |
|---|---|---|---|
| **WinRateCompareSection** | S093 T11 | 接入后置共享区（战法 60 日胜率对比） | ✅ 已接入（`Workflow.tsx` PostSharedRegion） |
| **CandidateProgressiveCard** | S066 §11.1 | 保留不删，待后续接入——三层渐进式候选卡（L0决策/L1摘要/L2详情/L3因子子页），UX 优于表格形态，但当前后端 `scored_candidates` 字段不匹配 `CandidateCardData`（缺 one_line_reason/position_pct/risk_label/score_breakdown 等），需后端补字段后接入 | ⏳ 待办：后端补 `CandidateCardData` 格式数据 + 前端接入 |

### A7. 合规自查

- [x] 因子下沉边界显式写入，不设全局因子预过滤闸（不违反 S084 superset 决议）
- [x] 不臆造：切换/共享区缺数据时显"—"或降级节点
- [x] 历史统计特征标注：战法命中矩阵/分组视图沿用既有 §44 未验证标注
