# Tasks: S011 — 调度收口

> 删 `scheduler.py` 是 T16 最后一步。

## 任务清单

| ID | 任务 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T1 | 扩展 `_should_run` 支持 `*/n`/范围/步进 | — | 单测覆盖边界 | ✅ 06229e1 |
| T2 | 🩹补 `scheduled_tasks.py` 的 `timedelta`/`asyncio` import | — | limitup_precompute/cleanup 不 NameError | ✅ 06229e1 |
| T3 | 🩹修 `TaskExecutor` 重复 `add_run`（开头 running，finally update 终态） | — | 一次执行一条 run 记录 | ✅ 06229e1 |
| T4 | SQLite WAL+busy_timeout+连接复用 | — | 无 database is locked | ⬜ |
| T5 | 任务去重（执行前查 running 同任务） | T3 | 重复触发跳过 | ✅ 06229e1 |
| T6 | ~~FastAPI lifespan + create_task 挂主循环~~ → **线程内长生命周期事件循环**（`_loop` 持 loop + `_ticker` 心跳） | — | 废线程内 asyncio.run；spawn 任务不被取消 | ✅ 06229e1 |
| T7 | `CronScheduler.stop` join+取消在途 | T6 | 优雅停止 | ⬜ |
| T8 | `portfolio.py` 删 `except: pass`+`while True` 加停止标志 | — | 错误有日志；可停止 | ⬜ |
| T9 | 三份预计算合并到 `daily_review.precompute_daily` | — | scheduler/scheduled_tasks 调它 | ⬜ |
| T10 | 状态机接线 `PreMarketWorkflow.run()` 调 `transition()` | — | 候选→watching 流转 | ⬜ |
| T11 | 状态落 `market_data.db` 新表 `workflow_state` | T10 | 可查状态 | ⬜ |
| T12 | 统一 `BEIJING_TZ`；修 `from backend.limitup_sti` 绝对路径 | — | 三处时区一致 | ⬜ |
| T13 | `pre_market_workflow` 删 `_build_strategy_match` 死代码 | — | run 不依赖它 | ⬜ |
| T14 | 单测：cron/TaskExecutor/状态机/lifespan | T1-T11 | 全过 | ✅ 06229e1（cron/TaskExecutor 47 例；状态机/lifespan 待 T10/T11） |
| T15 | 真实任务播种验证（建 enabled 任务跑一次） | T14 | 无并发重复 | ⬜ |
| T16 | **删 `scheduler.py`**，`app.py` 删旧钩子 | T15 | 收口单一 CronScheduler | ⬜ |
| T17 | `routers/scheduled_tasks.py` 不读 `st._manager` 私有 | T16 | 走公开 API | ⬜ |
| T18 | `routers/workflow.py` 删运行时 import+单例加锁 | — | 无循环依赖 | ⬜ |
| T19 | `pytest -m "not live"` + :8900 启停冒烟 | T16 | 全绿；启停优雅 | ⬜ |

## 依赖图
```
T1,T2,T3,T4,T5(并行) ─ T14
T6 ─ T7
T9,T10 ─ T11 ─ T14
T12,T13(并行)
T14 ─ T15 ─ T16 ─ T17 ─ T19
```

## 合规检查点
- T10 状态机流转是客观记录，不含买卖指令
- T9 预计算走 em_get
- T16 删 scheduler 前必须有 T15 播种验证（硬约束）
