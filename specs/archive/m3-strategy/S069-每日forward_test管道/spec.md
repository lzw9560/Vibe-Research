# Spec: S069 — 每日 forward_test 管道 + T+1 收益回填（流程框架打通）

> 状态：实现中（R1+R2 已落地 96f8778/9ff9ec1；待 prod baostock 验证 live 日积）
> 作者：lzw  日期：2026-08-16
> 关联：S066 §44 修订路径（114/115/116/123）、S041 回测定时任务、S055 盘中封单采集、S008 数据层
>
> **落地（2026-08-16）**：R1（每日 picks+universe 记录，executor forward_test_daily cron 15:45）+
> R2（T+1 收益回填，executor forward_test_t1_settle cron 15:50，baostock kline→return_open2close）。
> kline_returns.py 抽公共 helper（baostock 未装→{} 降级；prod requirements 有）。
> R1 record 改 INSERT OR IGNORE（重跑保 settled 不擦；08-14 NULL 实为 backtest_samples 缺最近日，
> 非 R1 wipe——prod 由 R2 baostock 回填 live 日）。41 测试过。
> **待 prod 验证**：baostock 装上后，R1+R2 日积 → forward_test_records/universe_returns 随 N 增长 →
> §44 verdict 覆盖 live N 日（非 stale 31）。dev 无 baostock，R2 降级 baostock_unavailable（不崩）。
>
> grill 决议（2026-08-16）：pre/post = 离线分析引擎、intraday = 执行层；盘后→盘前选股依据→盘中决策。
> 架构确认后，承重缺口 = §44 forward_test 数据**不日积**（仅 retroactive backfill 的 31 日）→ 116 复验无法用 live 累积数据。
> 本 spec 打通"每日回填新增"：forward_test picks + universe_returns 每日累积 → §44 verdict 覆盖 live N 日（非 stale 31）。

## 1. 问题 / 目标

当前每日定时（`limitup_precompute` 15:30）写 `gene_scores`（日积，31→60），但 **`run_daily_forward_test` + T+1 收益没接每日管道** → `forward_test_records`/`universe_returns` 不日积（仅 `tools/forward_test_backfill.py` retroactive 跑的 31 日）。结果：60 日时 `get_forward_test_summary` 仍只覆盖 31 settled（§44 verdict 部分）。

**目标**：forward_test picks + universe_returns 每日累积（live），使 §44 verdict 覆盖 live 累积的 N 日 → 116 复验无需等 backtest_samples、用 live 累积数据。

## 2. 背景

- `run_daily_forward_test(date, weather)`：记 picks（forward_test_records）+ universe codes（universe_returns，收益 NULL）。
- `record_actual_returns(date, returns)` / `record_universe_returns(date, returns)`：回填 picks / universe 的 T+1 收益（return_open2close/close2close/next_pctChg + is_win）。
- T+1 收益源：backtest_samples.json（Phase 0a 一次性，仅历史日）或 **BaoStock kline 次日 bar**（open/close → return_open2close = (next_close - next_open)/next_open*100）。live 日不在 backtest_samples → 需 kline。
- §44 gate（task 114）：`winrate>=60 AND lift>=2.0 AND random_settled>0`；116 诚实层（58c2bf4）：settled<80% total → "部分样本" caveat。
- 东财 zt_pool ~30 日滚动窗口（无深历史）→ 不能 backfill 历史，只能 live 日积（本 spec 使之）。

## 3. 需求清单

- [ ] R1（每日 picks 记录）：post-market 定时（晚 limitup_precompute）调 `run_daily_forward_test(今日, build_context(今日).weather_state)` → 记当日 picks + universe codes（收益 NULL）。
- [ ] R2（T+1 收益回填）：每日 post-market 回填**昨日** forward_test picks + universe 的 T+1 收益（kline 次日 bar → return_open2close），调 `record_actual_returns` + `record_universe_returns`。
- [ ] R3（weather 接入）：R1 用 `build_context(date).weather_state`（非 None）——测完整架构非退化版（task 115 已证 weather-adapted 是完整版）。
- [ ] R4（幂等 + 不污染）：每日 task 幂等（INSERT OR REPLACE/IGNORE）；跨日不累积 dup（forward_test_backfill 已 auto-clear retroactive 跑，live 日不 clear）。
- [ ] R5（§44 verdict 覆盖验证）：N 日后 `get_forward_test_summary` 的 settled_count 随 N 增长（非固定 31）；universe_coverage 同。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduled_tasks.py` | 新 executor `_execute_forward_test_daily`（R1 记 picks+universe）+ `_execute_forward_test_t1_settle`（R2 回填昨日收益）；注册 _executors + seed 默认任务（post-market cron） |
| `backend/strategies/forward_test.py` | 可能抽 `record_day(date, weather)` 编排（fetch+record picks+universe）复用 R1 + backfill |
| `backend/tools/forward_test_backfill.py` | T+1 kline 收益计算函数抽公共（R2 + retroactive 共用） |
| kline 源（astock/baostock） | R2 取次日 bar（复用现有 kline fetch，走限流） |
| `backend/tests/test_task_executor.py` | +executor 测试 |

## 5. 设计方案

**两段式每日管道**（R1 当日 + R2 次日，因 T+1 收益需次日 kline 闭环）：
- **R1 post-market D**（cron ~15:40，晚 limitup_precompute 10min 避抢 DB）：`run_daily_forward_test(D, weather=build_context(D).weather_state)` → picks（forward_test_records UPSERT）+ universe codes（INSERT OR IGNORE）。weather 用 build_context（task 115 验证过 weather-adapted 是完整版；早期日无 STI→None 混入，诚实）。
- **R2 post-market D+1**（同 cron 窗口）：对 D 的 picks + universe，取 D+1 kline（BaoStock/astock 次日 bar，走限流熔断）→ return_open2close=(next_close-next_open)/next_open*100, close2close, next_pctChg → `record_actual_returns(D, ...)` + `record_universe_returns(D, ...)`。

**T+1 收益源取舍**：
- (a) BaoStock kline 次日 bar（需 fetch，新 code 也覆盖）——选此，live 日 backtest_samples 不含。
- (b) 扩 backtest_samples 每日——耦合 Phase 0a snapshot，不选。
- 复用 `forward_test_backfill.py` 的 returns 计算（抽公共函数），retroactive + live 共用。

**不接的（follow-on，单列 spec）**：
- §44 CLI 分析（0b factor_regression/grillQ1 screener_edge/sector_phase/IC）UI 化——需新 endpoints/panels，独立。
- 盘后→盘前选股依据流（winrate 反馈→权重 refine→pre 选股）——独立。

## 6. 验收标准

- [ ] A1 R1 executor 跑通：D 日后 forward_test_records 有 D 的 picks（≤20×策略数）+ universe_returns 有 D 的 codes（收益 NULL）。
- [ ] A2 R2 executor 跑通：D+1 后 D 的 picks + universe 有 return_open2close（非 NULL）。
- [ ] A3 幂等：同日重跑不 dup（INSERT OR REPLACE/IGNORE）。
- [ ] A4 N 日后 get_forward_test_summary 的 settled_count 随 N 增长（非固定 31）；universe_coverage 增长。
- [ ] A5 weather 接入：R1 用 build_context weather（非 None，早期日除外）。
- [ ] A6 §44 诚实层不变：settled<80% total 仍标"部分样本"（58c2bf4）。

## 7. 合规自查（弱合规，§1.2 工程底线）

- [x] 不臆造数据：R2 收益来自 kline 真实 bar（非编造）；缺 bar 标 NULL（不臆造）。
- [x] 私有数据隔离：写 VR_DATA_DIR 内 gene_scores.db（不入 git）。
- [x] 防封：kline fetch 走 astock/em_get 限流熔断（不裸调 requests）。
- [x] §13.0：本 spec 是**分析数据管道基建**（找 edge 的数据累积），非新 alpha 战法层——§44 no-edge 下建管道是地基（让 116 用 live 数据复验），非 build-on held。
