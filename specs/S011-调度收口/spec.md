# Spec: S011 — 调度收口（删 scheduler.py + 重写 scheduled_tasks + 状态机接线）

> 状态：已实现 2026-08-01
> 作者：Claude  日期：2026-07-29
> 关联：`../S006-系统重写纲领/spec.md`（§5 第 5 步）、`../S012`（工作流标灰，本 spec 接线状态机后其桩维持）、`../../ARCHITECTURE.md`、`../../CLAUDE.md` §2

---

## 1. 问题 / 目标

两套调度并行且重叠：`scheduler.py`(103,硬编码时间窗) 与 `scheduled_tasks.py`(587,CronScheduler 未播种) 功能重叠，盘后预计算逻辑抄三份（scheduler/scheduled_tasks/daily_review）；全栈守护线程+`asyncio.run` 桥接，与 FastAPI 事件循环隔离；SQLite 无 WAL/busy_timeout，并发写 `market_data.db` 风险；`TaskExecutor` 重复 `add_run` 产生两条 run 记录；`scheduled_tasks.py` 缺 `timedelta`/`asyncio` import（limitup_precompute/cleanup 触发即 NameError）；无优雅停止；`portfolio.py` `except Exception: pass` 静默吞错、`while True` 无出口；`workflow_state_machine.py` 七态定义了从未接线；时区三套策略并存。

**目标**：收口到单一 CronScheduler；不引入 APScheduler；lifespan 挂主循环；SQLite WAL+去重+优雅停止；修 import/add_run bug；状态机接入 `PreMarketWorkflow.run()` 落库；三份预计算合并；统一 `BEIJING_TZ`。**删 `scheduler.py` 是本 spec 最后一步**（先补测+修 bug+播种验证）。

## 2. 背景

- `app.py:71-72` 起 portfolio/limitup 调度器，`app.py:161-162` 起 CronScheduler；无 lifespan shutdown。
- `TaskExecutor` 6 内置任务：daily_data_refresh/daily_review_notify/limitup_precompute/portfolio_refresh/market_data_sync/cleanup_old_runs。
- `CronScheduler._should_run` 自实现 5 段式 cron，仅支持 `*`/数字/逗号，不支持 `*/n`/范围。
- 状态机七态：pending→candidate→watching→monitoring→holding→settled，旁路 filtered。

## 3. 需求清单

- [ ] R1 扩展 `_should_run` 支持 `*/n`/范围/步进（不引入 APScheduler）
- [ ] R2 🩹补 `scheduled_tasks.py` 的 `timedelta`/`asyncio` import；🩹修 `TaskExecutor` 重复 `add_run` bug
- [ ] R3 SQLite：`PRAGMA journal_mode=WAL` + `busy_timeout` + 连接复用/池
- [ ] R4 任务去重：同任务执行中不重复触发
- [ ] R5 lifespan：`app.py` 用 FastAPI lifespan 注册启动/优雅停止；`CronScheduler.stop` join 线程；`portfolio`/`scheduler` 的 `while True` 加停止标志
- [ ] R6 调度模型统一：用 `asyncio.create_task` 挂 FastAPI 主循环，废线程内 `asyncio.run` 桥接
- [ ] R7 三份预计算逻辑合并到 `daily_review.precompute_daily` 一处，调度器只调它
- [ ] R8 🩹删 `portfolio.py:186` `except Exception: pass`，改日志+重试
- [ ] R9 统一 `BEIJING_TZ`（trading_workflow/realtime/post_market 改用，daily_review 修 `from backend.limitup_sti` 绝对路径）
- [ ] R10 状态机接入 `PreMarketWorkflow.run()`：候选→watching→... 流转调 `transition()`，状态落 `market_data.db`
- [ ] R11 `pre_market_workflow.py` 删 `_build_strategy_match` 死代码
- [ ] R12 **最后一步**：补 cron 匹配+TaskExecutor 单测+修 bug+真实任务播种验证后，删 `scheduler.py`，收口到 CronScheduler

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduled_tasks.py` | 🔥重写（cron扩展/import/add_run/WAL/去重/lifespan） |
| `backend/scheduler.py` | 🗑️删（最后一步） |
| `backend/portfolio.py` | ✏️🩹删 except pass+停止标志+lock 移 lifespan |
| `backend/trading_workflow.py` | ✏️时段配置化+BEIJING_TZ |
| `backend/workflow_state_machine.py` | 🔥接线+落库 |
| `backend/pre_market_workflow.py` | ✏️驱动状态机+删死代码 |
| `backend/daily_review.py` | ✏️合并三份预计算之一+修绝对路径+BEIJING_TZ |
| `backend/app.py` | ✏️lifespan+删旧调度钩子 |
| `backend/routers/scheduled_tasks.py` | ✏️不读 `st._manager` 私有 |
| `backend/routers/workflow.py` | ✏️🩹删运行时 import（循环依赖）+单例加锁 |

## 5. 设计方案

- **不换框架**：扩展现有 `_should_run`（几十行支持 `*/n`/范围），不引 APScheduler，避免 async 调度模型切换的新负担。
- **调度模型**：FastAPI lifespan 启动时 `asyncio.create_task` 挂调度循环到主事件循环；废"线程内 asyncio.run 起临时循环"。保留 `asyncio.to_thread` 包同步阻塞取数。
- **删 scheduler 顺序**：补测→修 bug→播种验证→删。先立测试网再动唯一在跑的调度。
- **状态机接线**：`PreMarketWorkflow.run()` 在候选产出/进入 watching 时调 `transition()`，状态写 `market_data.db` 新表 `workflow_state`；realtime/post 桩维持（S012 标灰）。

## 6. 验收标准

- [ ] A1 `_should_run` 支持 `*/n`/范围，单测覆盖边界值
- [ ] A2 `TaskExecutor` 各 `_execute_*` 有单测；无 import/add_run bug
- [ ] A3 SQLite WAL+busy_timeout 启用；并发写无 `database is locked`
- [ ] A4 任务去重：同任务执行中重复触发被跳过
- [ ] A5 lifespan 优雅停止：进程退出时 join 线程、在途任务完成或取消
- [ ] A6 `scheduler.py` 已删；CronScheduler 单一收口
- [ ] A7 状态机 `transition()` 在 `PreMarketWorkflow.run()` 被调；状态可从 `market_data.db` 查
- [ ] A8 `portfolio` 无 `except: pass`；`while True` 有停止标志
- [ ] A9 统一 `BEIJING_TZ`；无 `from backend.limitup_sti` 绝对路径
- [ ] A10 `pytest -m "not live"` 全过（含 cron/TaskExecutor/状态机新测）
- [ ] A11 :8900 启动/停止优雅；盘后预计算无并发重复

## 7. 合规自查（按新 CLAUDE.md §1）

- [ ] 调度逻辑不引入方向性判断
- [ ] 状态机流转是客观状态记录，不含买卖指令
- [ ] 预计算仍走 em_get，不裸调
- [ ] 私有数据仍只存 VR_DATA_DIR

## 8. 测试计划

- 单测：test_cron_should_run（*/n/范围/边界）、test_task_executor（各任务+去重+add_run 无重复）、test_state_machine（流转/非法转换/reset/落库）、test_lifespan_shutdown
- 集成：`pytest -m "not live"`；market_data.db 隔离 fixture（conftest 补）
- live：:8900 启停；盘后预计算触发一次验证无并发

## 9. 风险与回滚

- 🟠 删 scheduler 前 scheduled_tasks 0 测试：先补测+播种验证再删（顺序硬约束）
- 🟡 asyncio.create_task 挂主循环与现有线程消费者兼容：保留 to_thread 包阻塞取数
- 🟡 状态机接线改变 PreMarketWorkflow 行为：基线测+落库可查可回退
- 🟢 回滚：恢复 scheduler.py（git）；状态机接线可移除
