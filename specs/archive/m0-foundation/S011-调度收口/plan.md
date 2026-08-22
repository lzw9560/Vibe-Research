# Plan: S011 — 调度收口技术方案

> 对应 `spec.md`。细化 cron 扩展、lifespan、SQLite WAL、状态机接线、删 scheduler 顺序。

## 1. cron 扩展（不引 APScheduler）

`_should_run(expr, now)` 扩展支持：
- `*/n`：步进（`*/5` 每 5 分钟）
- `n-m`：范围（`9-15` 时段）
- `,` 逗号、`*` 通配（已有）
实现：解析表达式为 `(minute, hour, dom, month, dow)` 五段，每段支持 `*/n`/`n-m`/列表。

## 2. lifespan 接入

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = start_scheduler()  # asyncio.create_task 挂主循环
    yield
    await scheduler.stop()  # join 线程、取消在途任务
app = FastAPI(lifespan=lifespan)
```
- 废线程内 `asyncio.run` 桥接；调度循环用 `asyncio.create_task` 挂主事件循环
- 同步阻塞取数仍用 `asyncio.to_thread`
- `CronScheduler.stop`：`_running=False` + join + 取消在途 task
- `portfolio`/`scheduler` 的 `while True` 加 `_stop` 事件标志

## 3. SQLite WAL

```python
def _get_connection():
    conn = sqlite3.connect(_DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn
```
- 连接复用（`check_same_thread=False` + lock，或 threadlocal）
- 任务去重：执行前查 `scheduled_task_runs` 是否有 `running` 同任务

## 4. 状态机接线

- `PreMarketWorkflow.run()` 在候选产出/进入 watching 时调 `transition("watching", reason=...)`
- 状态落 `market_data.db` 新表 `workflow_state(code, state, history, updated_at)`
- `realtime`/`post` 桩维持（S012 标灰），状态机不推进到 holding/settled

## 5. 修 bug + 删 scheduler 顺序（硬约束）

1. 补 `timedelta`/`asyncio` import
2. 修 `TaskExecutor` 重复 `add_run`（开头插 running，finally 改 update 终态，不二次插）
3. 补 cron/TaskExecutor 单测
4. 真实任务播种验证
5. **最后**：删 `scheduler.py`，`app.py` 删 `start_portfolio_scheduler`/`start_limitup_scheduler` 旧钩子

## 6. 三份预计算合并

- `scheduler._precompute_limitup_async` + `scheduled_tasks._execute_limitup_precompute` + `daily_review.precompute_daily` → 合并到 `daily_review.precompute_daily` 一处
- 调度器只调 `daily_review.precompute_daily(back_days=3)`

## 7. 实现步骤
1. cron 扩展 + 单测
2. 补 import + 修 add_run + 单测
3. SQLite WAL + 去重
4. lifespan + 优雅停止
5. 三份预计算合并
6. 状态机接线 + 落库 + 单测
7. portfolio 删 except pass + 停止标志
8. 统一 BEIJING_TZ + 修绝对路径
9. 播种验证 → 删 scheduler.py
10. `pytest -m "not live"` + :8900 启停冒烟

## 8. 风险点
- 删 scheduler 前 scheduled_tasks 0 测试 → 顺序硬约束
- asyncio.create_task 挂主循环与线程消费者兼容 → to_thread 包阻塞
- 状态机接线改变 PreMarketWorkflow 行为 → 落库可查可回退
