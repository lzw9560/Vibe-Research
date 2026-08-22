# 技术方案 · S041 回测定时任务 + 趋势看板

> 对应：`spec.md`（需求/验收）、`tasks.md`（原子任务）
> 依赖：S040 回填 90 天数据。

## 1. 文件结构与职责

### 新增
| 文件 | 职责 |
|---|---|
| `backend/routers/backtest.py`（扩展） | 新增 `GET /api/backtest/trend` 端点 + 快照查询函数 |
| 前端 `frontend/src/components/charts/TrendChart.tsx` | 趋势折线图组件 |

### 改动
| 文件 | 改动 |
|---|---|
| `backend/scheduled_tasks.py` | 新增 `_execute_daily_backtest_run` + task_type 注册 |
| `backend/routers/backtest.py` | 新增 trend 端点 |
| `frontend/src/pages/Backtest.tsx` | 新增"趋势看板" Tab |
| `frontend/src/lib/api.ts` | 新增 `backtestTrend` 调用 |

## 2. 快照表 DDL

```sql
CREATE TABLE IF NOT EXISTS backtest_daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    engine TEXT NOT NULL,           -- 'lite' | 'strategy'
    hit_rate REAL,
    avg_return REAL,
    max_drawdown REAL,
    sharpe_ratio REAL,
    total_signals INTEGER,
    percentile_json TEXT,            -- lite 分位分析 JSON
    strategy_breakdown_json TEXT,    -- strategy 8 战法 JSON
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_date, engine)   -- 幂等：同天重跑覆盖
);
```

表放 `market_data.db`（与 scheduled_tasks 同库）。

## 3. 定时任务

### 3.1 task_type 注册
在 `TaskExecutor` 加 `_execute_daily_backtest_run(self, payload)`：
```python
def _execute_daily_backtest_run(self, payload):
    import asyncio
    lookback = int(payload.get("lookback_days", 30))
    today = datetime.now().strftime("%Y-%m-%d")
    start = (today - timedelta(days=lookback)).strftime("%Y-%m-%d")

    # lite
    lite_result = asyncio.run(run_backtest_async(start, today))
    _save_snapshot(today, "lite", lite_result)

    # strategy
    strat_results = run_strategy_backtest(lookback)
    _save_snapshot(today, "strategy", strat_results)
```

在 `list_task_types` 端点加 `"daily_backtest_run"`。

### 3.2 cron
默认 `0 17 * * 1-5`（周一到周五 17:00 收盘后）。用户可在 scheduled_tasks UI 修改。

## 4. 趋势 API

```python
@router.get("/api/backtest/trend")
async def backtest_trend(days: int = Query(90, ge=1, le=365)):
    # 查 backtest_daily_snapshots 最近 N 天
    rows = db.execute("SELECT * FROM backtest_daily_snapshots ORDER BY snapshot_date ASC LIMIT ?", (days,))
    return {"data": [_row_to_dict(r) for r in rows]}
```

## 5. 前端趋势看板

三个 LineChart（Recharts）：
1. hit_rate 趋势（engine=lite，一条线）
2. avg_return 趋势（engine=lite，一条线）
3. 8 战法 win_rate 趋势（engine=strategy，八条线）

X 轴 snapshot_date，Y 轴百分比。strategy_breakdown_json 解析成 8 条数据系列。
