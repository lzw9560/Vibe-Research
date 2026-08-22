# 任务拆分 · S041 回测定时任务 + 趋势看板

> 对应：`spec.md`（需求）、`plan.md`（技术方案）
> 依赖：S040 先合并。

---

## 阶段 A · 快照表 + 定时任务（R1/R2）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| A1 | `backtest_daily_snapshots` 表 DDL + 幂等写入函数 `_save_snapshot` | — | `backend/scheduled_tasks.py` 或 `backend/routers/backtest.py` | 手动调 _save_snapshot 两次 -> 行数不变 | A2,A3 |
| A2 | `TaskExecutor._execute_daily_backtest_run`：跑 backtest_lite + strategy_backtest，调 _save_snapshot 存两行 | A1 | `backend/scheduled_tasks.py` | 手动触发 -> 表新增 2 行 | A2 |
| A3 | `list_task_types` 加 `"daily_backtest_run"` | A2 | `backend/routers/scheduled_tasks.py` | `GET /api/scheduled-tasks/types` 包含 daily_backtest_run | A1 |

## 阶段 B · 趋势 API（R3）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| B1 | `GET /api/backtest/trend?days=90` 端点：查表返回时间序列 | A1 | `backend/routers/backtest.py` | curl -> 返回数组按日期升序 | A4 |
| B2 | 单测：trend 端点 mock DB 返回正确序列 | B1 | `backend/tests/test_backtest_trend.py` | pytest 过 | A4 |

## 阶段 C · 前端趋势看板（R4）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| C1 | `frontend/src/lib/api.ts` 新增 `backtestTrend(days)` | B1 | `frontend/src/lib/api.ts` | tsc 过 | A4 |
| C2 | `TrendChart.tsx` 折线图组件：hit_rate + avg_return 两条线 | C1 | `frontend/src/components/charts/TrendChart.tsx` | tsc 过；mock 数据渲染折线 | A5 |
| C3 | 8 战法 win_rate 趋势图：解析 strategy_breakdown_json -> 8 条线 | C1 | `frontend/src/components/charts/TrendChart.tsx` | tsc 过；mock 渲染 8 条线 | A5 |
| C4 | `Backtest.tsx` 新增 Tab "趋势看板"，渲染三个折线图 | C2,C3 | `frontend/src/pages/Backtest.tsx` | 页面切到趋势 Tab 看到图 | A5 |

## 阶段 D · 集成验收

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| D1 | pytest -m "not live" 全绿 | B2 | — | 全过 | A6 |
| D2 | 手动触发 daily_backtest_run -> 表新增 2 行 | A2 | — | SELECT 确认 | A2 |
| D3 | 同天重复触发：行数不变 | D2 | — | SELECT 确认 | A3 |
| D4 | 前端趋势看板渲染：数据点数 = DB 快照天数 | C4,D2 | — | 肉眼确认 | A5 |
