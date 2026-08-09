# Spec: S041 — 回测定时任务 + 趋势看板

> 状态：草案
> 作者：Codex  日期：2026-08-09
> 关联：`../S040-历史数据回填90天/spec.md`（90 天数据是前提）、`backend/scheduled_tasks.py`（`_execute_limitup_precompute` task_type 注册模式）、`backend/backtest_lite.py`（`run_backtest_async`）、`backend/strategies/strategy_backtest.py`（`run_strategy_backtest`）、`frontend/src/pages/Backtest.tsx`
>
> 级别：**medium**（跨层 + 新增 DB 表 + 前端组件）

## 1. 问题 / 目标

当前回测是手动触发——用户打开 Backtest 页面点刷新才跑一次，结果缓存在 JSON 文件（backtest_lite）或内存 dict（strategy_backtest）。无法看到 hit_rate / avg_return / win_rate 随时间变化的趋势，无法判断因子是否在衰减。

**目标**：
1. 注册一个定时任务 `daily_backtest_run`，每天收盘后自动跑 `backtest_lite` + `strategy_backtest`，结果存入 DB
2. 前端新增趋势看板：hit_rate / avg_return / 各战法 win_rate 随日期变化的时间序列折线图

## 2. 背景

- `scheduled_tasks` 系统已有 cron-like 调度，已注册的 task_type 包括 `daily_data_refresh` / `limitup_precompute` 等。新增 task_type 需要在 `TaskExecutor._execute_*` 方法里加对应逻辑。
- `backtest_lite` 结果缓存在 `data/backtest_cache.json`（按 start|end 键，无 TTL）。`strategy_backtest` 结果缓存在内存 `_CACHE` dict（12h TTL）。
- 前端 `Backtest.tsx` 已有散点图 + 指标卡 + 分位分析。`WinRateComparePanel.tsx` 已有战法胜率对比表。趋势看板是新的 Tab。
- S040 回填 90 天后，`backtest_lite` 可以跑 30 天窗口滚动比较（每天跑前 30 天的回测，看 hit_rate 是否在变）。

## 3. 需求清单

- [ ] R1 新增 task_type `daily_backtest_run` 在 `scheduled_tasks.TaskExecutor`：每天收盘后（17:00 cron）跑 `backtest_lite.run_backtest_async(前30天, 今天)` + `strategy_backtest.run_strategy_backtest(30)`，结果存入新 DB 表 `backtest_daily_snapshots`
- [ ] R2 新表 `backtest_daily_snapshots`（在 `market_data.db`）：字段 `id, snapshot_date, engine(lite/strategy), hit_rate, avg_return, max_drawdown, sharpe_ratio, total_signals, percentile_json, strategy_breakdown_json, created_at`。`snapshot_date + engine` 唯一约束（幂等，同天重跑覆盖）
- [ ] R3 新增 API `GET /api/backtest/trend?days=90`：返回时间序列 `[{date, engine, hit_rate, avg_return, ...}, ...]`
- [ ] R4 前端 `Backtest.tsx` 新增 Tab "趋势看板"：折线图展示 hit_rate / avg_return / 8 战法 win_rate 随日期变化。用 Recharts（已在依赖中）
- [ ] R5 定时任务支持 `--lookback_days` payload 参数（默认 30），控制回测窗口大小

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduled_tasks.py` | R1 新增 `_execute_daily_backtest_run` + task_type 注册 |
| `backend/scheduled_tasks.py` 或 `backend/routers/backtest.py` | R2 新表 DDL + 查询函数 |
| `backend/routers/backtest.py` | R3 `GET /api/backtest/trend` 端点 |
| `frontend/src/pages/Backtest.tsx` | R4 趋势看板 Tab + 折线图 |
| `frontend/src/lib/api.ts` | R3 新增 `backtestTrend` API 调用 |

## 5. 设计方案

### D1 快照表设计

不拆两张表（lite 一张、strategy 一张）——用 `engine` 字段区分。`percentile_json` 存 backtest_lite 的分位分析 JSON，`strategy_breakdown_json` 存 strategy_backtest 的 8 战法聚合结果 JSON。查询时按 engine 过滤，前端按 engine 分组渲染。

`snapshot_date + engine` 唯一约束——同天重跑覆盖（INSERT OR REPLACE），幂等。

### D2 回测窗口选择

默认 30 天滚动窗口——每天跑"前 30 天到今天"的回测。不是跑 90 天全量——全量跑一次够了，趋势看的是窗口移动时指标变化。如果数据不足 30 天则按实际可用天数截断（`strategy_backtest._get_available_dates` 已有此逻辑）。

### D3 前端趋势图

三个折线图：
1. hit_rate 趋势（backtest_lite 引擎，一条线）
2. avg_return 趋势（backtest_lite 引擎，一条线）
3. 8 战法 win_rate 趋势（strategy_backtest 引擎，8 条线）

用 Recharts `LineChart`，X 轴日期，Y 轴百分比。颜色用战法各自的固定色板。

### D4 不改现有缓存机制

backtest_lite 的 JSON 缓存和 strategy_backtest 的内存缓存保持不变。趋势快照是独立的 DB 存储，与运行时缓存不冲突——运行时缓存服务"打开页面秒出结果"，趋势快照服务"历史序列对比"。

## 6. 验收标准

- [ ] A1 定时任务注册成功，`GET /api/scheduled-tasks/types` 包含 `daily_backtest_run`
- [ ] A2 手动触发 `daily_backtest_run` 后 `backtest_daily_snapshots` 表新增 2 行（lite + strategy）
- [ ] A3 同天重复触发：行数不变（INSERT OR REPLACE 幂等）
- [ ] A4 `GET /api/backtest/trend?days=90` 返回时间序列数组，按日期升序
- [ ] A5 前端趋势看板渲染折线图，数据点数 = DB 中快照天数
- [ ] A6 `pytest -m "not live"` 全过

## 7. 合规与工程底线自查

- [ ] 回测结果属客观历史统计特征，前端挂"历史统计特征，市场有风险"
- [ ] 定时任务走现有调度系统，不额外拉东财（backtest 只读 DB + mootdx K 线）
- [ ] 无私有数据进 git

## 8. 测试计划

- pytest -m "not live"：确认新表 DDL + 查询函数 + API 端点
- 手动触发 `daily_backtest_run`：确认快照写入
- 前端打开趋势看板：确认折线图渲染

## 9. 风险与回滚

- **数据量小看趋势无意义**：S040 回填 90 天后才有足够快照。前 30 天的快照只有 30 个点，趋势线不够平滑——这是数据积累期的正常状态，不需要额外处理。
- **定时任务失败**：backtest 只读 DB + mootdx K 线，不碰东财，几乎不会失败。失败不阻断调度循环。
- **回滚**：删除 task_type + drop 表 + 删除前端 Tab。
