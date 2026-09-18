# S204 — 多日跟踪状态机架构 + §44v2 修正 + 承重数据 blocker

> 状态：**已实现（多日跟踪架构 R1-R7 + T9-T11 接线）**（2026-09-14 草案，c5e641e stage-1 + 0d411f2 T9-T11 接线 + 30e4d9b T11 fix 落地）。归档核于 2026-09-19。
> 落地证据：`backend/escalation_engine.py` + `backend/tracking_pool_repo.py` + `backend/early_admission.py` 均存在；`backend/routers/tracking.py:18` `import tracking_pool_repo as repo`；`backend/scheduler/executors/__init__.py:75,343` 注册 `_execute_early_admission_scan` + `from early_admission import scan_early_admission`；`backend/scheduler/seed.py:359` S204 T10 seed（grep 核实）。
> §44v2 三 CRITICAL（R8-R13 window-sanity/R3-enforce/Bonferroni）在 S159 v2 + S197 + S218 #1 af12ccf 跟进非本 spec，本 spec 仅多日跟踪架构部分落地。
> 归档至 `specs/_archive/`（reversible git mv）。
> 关联：[[../S203-龙头战法数字化改造/spec.md]]（战法内容 spec，依赖本 spec 的 §44v2 修正 + 多日跟踪架构）、[[../S159-§44应用规约v2/spec.md]]（§44v2 规约源）、[[../S197-r3-enforce-接线/spec.md]]（R3 enforce v2 草案，本 spec 推进落地）、[[../S201b2-carry-logic-fix/spec.md]]（path_return carry fix，§44 harness 依赖）。
> 上游工作流：`w50pptu5i`（6 专家+6 验证器）、`wc8g37bbx`（30 策略 §44 map，跨战法 CRITICAL 喂入本 spec）。

## 1. 问题 / 目标

S203 龙头战法数字化 + 用户架构洞察（"T日选股→T+1验证是单日单次，实战要连续观察多日指标、早早入池"）暴露**3 个承重系统级 gap**：

### 1.1 架构漏洞：七态状态机是薄转换验证器，非多日指标跟踪器

实测 `backend/workflow_state_machine.py`（88 行）：
- 7 态 pending→candidate→watching→monitoring→holding→settled（+filtered），`_ALLOWED_TRANSITIONS` 查表 + `transition(target, reason)` 追加 `_history`。**仅此**。
- **无**：跨日指标快照存储 / 按指标演化 aging 升级 / 早期入池跟踪池 / candidate→watching 自动晋级（指标成熟触发）。
- `workflow_state_repo.py`（420 行）：`ensure_candidate` 是盘前 run insert-if-absent 落 **T 日快照**，watching/monitoring/holding 流转走 `routers/workflow.py` **手动 API**（非指标驱动自动晋级）。

**结论**：用户洞察=真 gap。Vibe candidate 是 T 日单次快照，不是多日指标跟踪池。早期入池 + 多日指标演化跟踪 = 不存在。

### 1.2 §44v2 三个 CRITICAL（6+3 验证器识，须修）

1. **window-sanity 是诊断但不能行动**（两 workflow 都识）：plan 算 3 窗口（隔夜/D+1 日内/path）说"最高 lift 的窗口=edge 在哪"，但 verifier R5 gate（verifier.py:257-272）**只检查 edge_type 匹配窗口**（selection→path，event→overnight_gap），且在 harness 能据多窗口结果行动**之前就触发**。若 selection 策略 edge 实在隔夜（如均值回归 bollinger/zscore/反包），R5 查 path 见无优势→标 exploratory→跳过所有重方法论→**漏掉真 edge**，正是 §44v1 错窗口灾难。
2. **R3 enforce 部分落地，真实 gap 在两处**（对抗审 wjiq1hkmz CRITICAL 核实修正——原 §1.2 定性 FALSE）：lift_to_multiplier **已接线生产 sizing 路径**——`strategies/funnel/scoring.py:69`（gene-based 因子降权，:85 `multiplier=gene_multiplier if factor_name in _GENE_BASED_FACTORS else 1.0`）+ `routers/verifier.py:130`（API status+multiplier）+ `candidate_funnel/evaluation.py`（days_robust<60→×0.5 provisional cap；映射：探索性=1.0/未validated=0.5/劣于随机=0.1）。`engine/trade_journal.py:400`"脱节搁置"是 `query_winrate_trends` 周胜率趋势**显示标签**（原文"标签 robust 仅统计意义，不触发 sizing 调整"），非 sizing 路径。**真实 gap**：(a) S197 P0(c) scheduled_tasks R3 task reminder→enforce 未落地（`scheduler/seed.py` payload 无 enforce key，30/60 天跨阈自动但 enforce 触发无 API/CLI 路径）；(b) `candidate_funnel/evaluation.py` DIM_ARM_MAP arm/path sizing 空转——gene **因子级** sizing 已接，但 strategy **arm 级**（如 30 策略的 bollinger/zscore/macd arm）无 lift-based sizing。
3. **verifier 硬编码 Bonferroni for selection**：`verifier.py:299-303`（P4 slim）"selection uses Bonferroni only (status reads p_bonf)"。plan 称"小 n 用 BH 不 Bonferroni"**错**——BH 不参与 selection status。且 `stats.py:33` `_MAX_BONFERRONI_K=8` 硬上限，Phase>8 的 alpha_adj 计算错（声称 0.05/12 实际 cap 到 0.05/8）。

### 1.3 承重数据 blocker（跨战法，须修/标）

- **baostock bars 全无 pctChg**（实测 2018+2025 都无，keys=[date,open,high,low,close,volume,amount]）→ `is_unbuyable_next_bar`（bar_utils.py:47-90，line 23 `_bar_get(nb,"pctChg",0.0)`）一字涨停误判可买 → **污染 ALL backtest returns**，不只龙头/limitup。影响 S203 全部 + 30 策略全 24 可接。
- **gene_scores 表 7466 行**（2026-07-13 起 eastmoney_live，~60 天）<60 R6 gate → underpowered（非空，验证器 V2"0 字节"错已核）。
- **forward_test_records 表 337 行**（~20 交易日，2026-08-17~09-11）<60 → underpowered（§44 写回依赖）。
- **seal_intraday 仅 10 交易日**（8 月 3 天+9 月 7 天）→ 封成比/炸板 intraday 回测不够。
- **STI sti_timeline 33 日期**（实测核，对抗审修正原"32/分歧11"），phase 分布冰点15/分歧12/启动6/**退潮=0 天/高潮=0 天**→ regime_adaptation 退潮×0.5/高潮×1.0 无数据可验。
- **mootdx 0.11.7 已装** .venv（验证器 V5"未装"错已核），Quotes.transactions() 可拉历史分笔（t0_simulator.py:57 验证），但实时当日分笔流未接线+未测。
- **撤单率全栈无数据源**：bidding_monitor.py:103/133 硬编码 `cancel_rate=0.0`，sentiment_weather.py:501 原文"撤单比依赖盘口分笔数据，mootdx 不可得"。须 L2 付费（用户决策）。
- **sensitivity sweep harness 不存在**：`grep 'sweep|sensitivity' tools/*_lift.py` 全空。S203 社区参数校准依赖 sweep，须先建。
- **walk_forward_oos 不做 train-refit**：docstring 明确"Train window NOT optimized (frozen/pre-registered)"。专家 plan"train 期 refit→test 期验"作 overfit 检测**在 verifier 不存在**。

### 1.4 目标

1. 多日跟踪状态机（不重写七态，加驱动层，不破 _ALLOWED_TRANSITIONS invariants）。
2. §44v2 三 CRITICAL 修（window-sanity 可行动化 + R3 enforce 接线 + Bonferroni K/family 修）。
3. 承重数据 blocker（pctChg 注入修一字板误判 + underpowered 标注 + sweep harness 新建）。

## 2. 需求

### 2.1 多日跟踪架构（不破 invariants）

- **R1**：新建 `candidate_tracking_pool` 表——`(code, first_admit_date, admit_signal, admit_indicators_json, current_status, tracking_age_days, UNIQUE(code, first_admit_date))`。每股每次入池一条 track，记早期入池信号 + 当前跟踪态 + 跟踪天数。⚠️ 对抗审修正：tracking_pool key=(code,first_admit_date) 与 workflow_state key=(code,trade_date) 不同，**须设计两池同步协议**——escalation run date T 时：查 tracking_pool 活跃 track（current_status='tracking'）→ 对每 track 用 (code,T) 查 workflow_state；若 (code,T) 无行 → ensure_candidate(code,T,reason='escalation from first_admit T-N') 再 transition；若盘前 run 已 insert (code,T) 为 filtered，escalation 跳过该 track。
- **R2**：新建 `indicator_snapshots` 表——`(code, trade_date, indicators_json, snapshot_source, UNIQUE(code, trade_date))`。每股每日一条，存封单额/流通市值比、量比 relay_vol_ratio、sector_rank、gene_score、STI phase、MA5 斜率等。供 escalation 看指标演化序列。
- **R3**：新建 `escalation_engine.py`——复用 `workflow_state_repo.transition()` CAS（不改 `_ALLOWED_TRANSITIONS`）。指标成熟→candidate→watching 自动晋级。**watching 以上留人工**（半自动化助手定位）。
- **R4**：新建 `early_admission.py`——识别 pre-涨停候选（板块启动初期/连板苗子），**T-1 及更早数据 only**（盘前 run 时 T 日未开盘，T-1 收盘是最新可得，天然 guard）。
- **R5 防振荡**：⚠️ S049 D7 已允许 WATCHING→CANDIDATE（取消观察回池）。escalation 每日自动 candidate→watching 会**形成 candidate↔watching 振荡 loop**。**resolution**（对抗审修正 R5/R6 矛盾）：tracking_pool.current_status 是 **tracking 级 label**（admit/tracking/decayed/promoted），SEPARATE from workflow_state.WorkflowStatus enum——实际 state transition 走 WATCHING→FILTERED 用 reason='decayed'，**不加新 DECAYED 态**（保 _ALLOWED_TRANSITIONS 不破）。anti-flapping：watching 后 N=5 日无指标改善 → tracking_pool.current_status='decayed' + workflow_state transition WATCHING→FILTERED（非→CANDIDATE 回池）。
- **R6 词表对齐**（对抗审修正，与 R5 resolution 一致）：tracking_pool.current_status 是 **tracking 级 label**（admit/tracking/decayed/promoted，tracking 池内部决策用），**不进 workflow_state enum**。workflow_state 仍用 WorkflowStatus 7 态（pending/candidate/watching/monitoring/holding/settled/filtered）做实际 transition。escalation_engine 调 transition 传 WorkflowStatus 态名（如 WATCHING/FILTERED），tracking_pool label 是 escalation 决策输入非 state machine 态。
- **R7 escalation promote pre-涨停候选**：⚠️ early_admission 入 pre-涨停候选到 tracking_pool，但 escalation_check 调 `transition(code, 'watching')` 要求该股已在 workflow_state candidate——pre-涨停候选**不在** workflow_state → transition 失败。须 escalation 先 `ensure_candidate` 入池再 transition，或 tracking_pool 与 workflow_state 联动同步。

### 2.2 §44v2 修正

- **R8 window-sanity 可行动化**（对抗审 CRITICAL 修正，原"两者都做"中 harness-side 是 data-snooping）：**去掉 harness-side edge_type adjustment**（按胜出窗口调 edge_type = 选择偏差，让结果最好看的 edge_type inflate Type I error，Bonferroni 不覆盖）。改 **verifier-side fix**：R5 改查 ALL 计算窗口（任一窗口有优势→进重方法论，全无才 exploratory）+ verifier 对任何 edge_type **同时计算 selection_lift AND event_metrics**（当前 verifier.py:343 event_metrics 只在 edge_type in _EVENT_EDGE_TYPES 时算，须扩展为任何 edge_type 都算两者，verdict 同时报）。这样 selection 策略的 overnight_gap edge 也被测试（当前不被测）。若不改 verifier 双算，则 harness 须对同一策略跑两次 verify（selection + overnight_gap），但须在 K 冻结 pre-registration 声明双重测试计入多重比较。
- **R9 R3 enforce 真实 gap 接线**（对抗审 CRITICAL 修正，原 R9 目标文件错）：**不重写 trade_journal.py**（它不做 sizing，:400 是显示标签）。改：(a) 推进 S197 P0(c)——`scheduler/seed.py` R3 task 加 enforce key + API/CLI 触发路径（30/60 天跨阈不仅 reminder 还 enforce）；(b) `candidate_funnel/evaluation.py` DIM_ARM_MAP arm-sizing 接线——非 gene 策略 arm（30 策略 bollinger/zscore/macd 等）用 lift-based sizing 替代空转。days_robust<60 → provisional cap ×0.5（gene 因子级已 DONE，扩展到 arm 级）。
- **R10 Bonferroni K/family 修**（修 CRITICAL 3，§6 #9 决策不用 BH）：①`stats.py:33` `_MAX_BONFERRONI_K=8` cap——Phase>8 须**拆≤8 子 phase**（不用 BH，保 Bonferroni 严格；verifier.py:299-303 硬编码 selection 只 Bonferroni，BH 不参与 selection status，若要引入须改 verifier 给 selection 也算 p_bh=方法论变更须 grill）；②family grouping **未实现**（bonferroni_bh 只 p×n 无 family 逻辑）——bollinger==zscore 数学等价、triple_ma≈ema_ribbon、macd≈rsi_momentum 须按 effective families 数（~9-15 非 raw 30）设 n_comparisons，或去重等价策略；③K 冻结 pre-registration——harness 首次入库时冻结 K 防后调。K=12（3 regime×4 战法）按 regime 拆 3 family 各 K=4，跨 regime 用 Bonferroni-Holm 层级校正或标"每 regime family 独立 FWER，跨 regime 探索性"。
- **R11 event edge base_rate=0 drift fix**：event null 是"mean>0"非"beat market"→牛市 drift 假阳性（影响 dragon_tiger/limitup_quality 当 event 测）。修：event edge 也算 universe（同日全市场）+ 两样本测试（event_mean vs universe_mean），或减市场均值再 t-test。或 selection edge day_paired_lift 替代（survivors vs universe 隔日对冲 drift）。
- **R12 n<200 harness guard**：verifier R6 只查 days_robust<60，**不查 n<200**。harness 须加 pre-check：total survivors<200 → 跳 wire_verdict 标 underpowered。
- **R13 sensitivity sweep harness 新建**：S203 社区参数（封单>0.5%/量能 1.5-2.5x/板块 top3）校准依赖 sweep，新建 `tools/sensitivity_sweep.py`（或 per-harness sweep 函数）。

### 2.3 承重数据 blocker

- **R14 baostock bars 注入 pctChg + isST**（修一字板误判 CRITICAL，对抗审修正 cache vs fallback）：**cache 路径**（`baostock_kline_cache.json`，7 字段无 pctChg）需注入；**fallback 路径**（`baostock_src.py:27` KLINE_FIELDS 含 pctChg+isST，`_baostock_a_share_hist→fetch_daily_bars`）不需注入。优先方案：用 `refresh_kline_cache.py` 全量刷新 cache 补 pctChg。回测 loop 前给 cache bar 注入 `pctChg = (close[d] - close[d-1]) / close[d-1] * 100`。⚠️ **isST 不能默认 '0'**——须从 baostock query_stock_basic 或 ST 股列表派生，否则 ST 股一字板用 10% 阈值（非 5%）会漏判。**blocker #1**，不修则 S203 全部 + 30 策略 returns 污染。
- **R15 underpowered 标注**：gene_scores（~60 天）/forward_test_records（~20 天）/seal_intraday（10 天）/STI 退潮高潮（0 天）—— harness 须标 underpowered 不外推（§44v2 rule②），不判 robust/falsified。institutional 季度披露 cadence（~4 独立事件/年）须 structural underpowered override（verifier 无此机制，harness post-process）。
- **R16 forward_test_records 回补**：§44 战法写回依赖 forward_test_records，当前 ~20 天。须 scheduled 回补至 ≥60 天（或等积累）。
- **R17 数据源标注诚实**：撤单率标降级口径"仅 seal_amount 阈值，撤单比不可得"（不臆造）；mootdx tick 实时未接线标 BLOCKER（回测用 5min kline 近似，不用 daily OHLCV 做 VWAP 代理=look-ahead）。

## 3. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/workflow_state_repo.py` | 加 `candidate_tracking_pool` + `indicator_snapshots` 两表（幂等 CREATE IF NOT EXISTS）+ 索引；`_ensure_columns` 幂等 ALTER 加 first_admit_date/admit_signal/tracking_age_days 到 workflow_state |
| `backend/escalation_engine.py`（新建）| 指标成熟→candidate→watching 自动晋级（复用 transition CAS，防 S049 D7 振荡，词表对齐，ensure_candidate 联动）|
| `backend/early_admission.py`（新建）| pre-涨停候选识别，T-1 数据 only，pit guard |
| `backend/s44_verifier/verifier.py` | R5 window-sanity 查 ALL 窗口（R8 选项 b）；event edge 两样本/减市场均值（R11）|
| `backend/s44_verifier/stats.py` | Bonferroni K=8 cap 文档化+拆 phase；family grouping 实现（R10）|
| `backend/engine/bar_utils.py` 或 harness | baostock bars 注入 pctChg + isST（R14）|
| `backend/engine/trade_journal.py` | lift_to_multiplier 接线替代直读 weight_multiplier（R9 R3 enforce）|
| `backend/tools/sensitivity_sweep.py`（新建）| sweep harness（R13）|
| `backend/scheduled_tasks.py` | 新任务：early_admit_scan / daily_indicator_update / escalation_check / entry_trigger_scan / s44_strategy_writeback（S203 §2.7）|

## 4. 验收

- **多日跟踪**：两表 + escalation_engine 落地，不破 _ALLOWED_TRANSITIONS（现有 settled/filtered 重入不变），防振荡（watching→decayed 非→candidate），词表对齐 workflow_state，escalation 能 promote pre-涨停候选（ensure_candidate 联动）。
- **§44v2 修**：window-sanity 可行动（harness 调 edge_type 匹配胜出窗口 OR verifier R5 查 ALL 窗口）；R3 enforce 接线（trade_journal 用 lift_to_multiplier，days<60 cap×0.5）；Bonferroni K 处理（Phase>8 拆≤8 或 BH）+ family grouping（等价策略去重）+ K 冻结；event edge drift fix。
- **数据 blocker**：baostock bars 注入 pctChg + isST（回归 test：一字涨停不再误判可买）；underpowered 标注（gene_scores/forward_test_records/seal_intraday/STI/institutional）；sensitivity sweep harness 可跑。
- 全 `pytest -m "not live"` 绿（含新 test + S201b2 carry fix 不回退）。
- 承重：不臆造（pctChg 计算注入非臆造；撤单率标降级）；私有数据隔离；防封。

## 5. 合规自查

- 工程底线：不臆造（pctChg=(close[d]-close[d-1])/close[d-1]*100 可复算；撤单率标降级不臆造；underpowered 标 underpowered 不外推）；私有数据隔离（candidate_tracking_pool 在 .vibe-research/ 不进 git）；防封（em_get 走限流）。✓
- §44v2：本 spec **就是** §44v2 修正（window-sanity/R3 enforce/Bonferroni），属"重大方法论变更"，6-lens grill 已起（w50pptu5i + wc8g37bbx 全 REVISE，已核事实修正）。✓
- §44 不每阶段参与：本 spec 是承重架构+方法论修，grill 已起，后续 plan/tasks 阶段不再每步过 §44（除非方法论再变）。✓

## 6. 决策分叉（用户须定）

| 分叉 | 决策（2026-09-14 定） | 依据 |
|---|---|---|
| window-sanity 修法 | **verifier-side only**（R5 查 ALL 窗口 + verifier 对任何 edge_type 同时算 selection_lift AND event_metrics） | 对抗审 wjiq1hkmz CRITICAL 修正：harness-side 调 edge_type 是 data-snooping（选最好看的 edge_type=选择偏差，Bonferroni 不覆盖），去掉。verifier-side R5 查 ALL + 双算 metrics 让 selection 策略的隔夜 edge 也被测（当前 event_metrics 只在 edge_type∈event 时算）。**supersede 原"两者都做"**（用户同意修正） |
| R3 enforce 接线程度 | trade_journal 用 lift_to_multiplier（S197 v2 草案推进）| S197 标 P0(a)(b) DONE 在 evaluation.py，trade_journal:400 脱节须接线 |
| Bonferroni K>8 处理 | 拆≤8 子 phase（不用 BH 保 Bonferroni 严格）| BH 不 cap K 但 selection status 硬编码 Bonferroni；拆 phase 保严格+alpha_adj 正确 |
| family grouping | 去重等价策略（bollinger==zscore 去其一）+ effective families 数设 n_comparisons | bonferroni_bh 无 family 逻辑，去重最简单 |
| escalation 自动晋级程度 | 只 candidate→watching 自动（观察级非交易级），watching 以上人工 | A 股 T+1 容错率低，auto-fire holding=自动买入不可当日卖；社区阈值未验证 |
| baostock pctChg 注入位置 | **cache 刷新为主 + harness 注入 fallback**（`refresh_kline_cache.py` 全量刷新 cache 补 pctChg + isST 从 ST 列表派生；stale cache 时 harness enrich bar dict 副本）| R14 优先 refresh cache 一劳永逸（baostock_src:27 fallback 路径含 pctChg，刷新即有）；#12 harness fallback 保 bar_utils 源码干净；须备份 cache（5231 股×2111 日）+ 幂等 |
| 数据回补优先级 | forward_test_records 回补至≥60 天（§44 写回依赖）| 当前~20 天阻塞 §44 战法写回 |

## 7. 关键约束（来自 6+3 验证器，已实测核事实）

> 跨 w50pptu5i（龙头）+ wc8g37bbx（30 策略）9 验证器全 REVISE。以下已核事实 + 已识 §44v2 违规/架构问题，作为本 spec 约束：

- ✅ **baostock bars 全无 pctChg**（2018+2025 都无）→ is_unbuyable_next_bar 一字板误判可买 → 污染 ALL backtest returns（R14 修）。
- ✅ **gene_scores 表 7466 行非空**（2026-07-13 起，~60 天）——验证器 V2"0 字节"**错**已核；但 <60 → underpowered。
- ✅ **forward_test_records 337 行**（~20 交易日）<60 → underpowered（§44 写回依赖，R16 回补）。
- ✅ **zt_history.db 2288 行/32 日期/564 zbc≥2**（reverse_package 触发条件有数据）——验证器 V4"空"**错**已核；但 32<60 → underpowered。
- ✅ **mootdx 0.11.7 已装** .venv，Quotes.transactions() 可拉历史分笔——验证器 V5"未装"**错**已核；但实时分笔流未接线+未测。
- ⚠️ **seal_intraday 仅 10 天**，封成比/炸板 intraday 回测不够。
- ⚠️ **STI 退潮/高潮零天数据**，regime_adaptation 无数据可验。
- ⚠️ **撤单率全栈无数据源**（cancel_rate=0 硬编码），须 L2 付费（用户决策）。
- ⚠️ **§44v2 三 CRITICAL**：window-sanity 不可行动（R8）/ R3 enforce 未落地（R9）/ Bonferroni K=8 cap+family 未实现（R10）。
- ⚠️ **walk_forward_oos 不 train-refit**（frozen），"train-refit overfit 检测"在 verifier 不存在（R13 sweep harness 新建替代）。
- ⚠️ **架构**：S049 D7 WATCHING→CANDIDATE 振荡 loop（R5 防）；tracking_pool 词表须对齐 workflow_state（R6）；escalation 无法 promote pre-涨停候选（R7 ensure_candidate 联动）。
- ⚠️ **verifier V3 "5231 股×2067 bars"是假**——实际只 974 股≥1000 bars，786 股早于 2018-06；"320 优先"无文件无 grep 痕迹（未文档化）。harness 须预筛 len≥123 + first_bar<2018-06。

## 8. 对抗审剩余 HIGH（plan.md 处理）

> wjiq1hkmz 对抗审 6 lens 全 REVISE，3 CRITICAL + 关键 HIGH 已在 §1.2/R8/R9/R10/R14/R1/R5/R6 修。以下 HIGH 是 plan-implementation 细节，plan.md 须定：

- **R3 maturity 量化（architecture HIGH）**：R3"指标成熟→candidate→watching 自动晋级"未量化。plan 须定 maturity 标准（如 tracking_age_days≥3 AND gene_score improvement≥20% over admit-day AND sector_rank≤5 → promote），标探索性（社区阈值未验证），+ decay 标准（watching 后 N=5 日无改善→decayed）。
- **R8 verifier 双算爆炸半径（§44v2 HIGH）**：R8 须 verifier 对任何 edge_type 同时计算 selection_lift AND event_metrics——这是方法论变更，plan 须 grill + 评估爆炸半径（破坏 `test_s44_verifier.py` 5 个现有 R5 test 如 :807 test_r5_window_sanity_no_advantage_forces_exploratory 等，须同步更新）。
- **§3 test files（testability HIGH）**：plan 须列 `test_s44_verifier.py`（5 个 R5 test + 1 bonferroni test 须更新）+ `test_s144_unbuyable_t1.py`（no-pctChg 场景）+ `test_s034_settlement.py`（重入 regression）+ `test_s44_wire.py` + 新建 `test_escalation_engine.py`/`test_early_admission.py`/`test_sensitivity_sweep.py`/`test_tracking_pool.py`。
- **§3 scheduled_tasks files（testability HIGH）**：plan 须加 `scheduler/executors/__init__.py`（注册 5 task_type→_execute_*，:55 _executors dict）+ `scheduler/seed.py`（seed 5 task 含 cron_expr + payload），非 `scheduled_tasks.py`（任务注册不在那）。
- **R8 harness 双跑备选**：若不改 verifier 双算，harness 对同一策略跑两次 verify（selection + overnight_gap）——plan 须在 K 冻结 pre-registration 声明双重测试计入多重比较。
