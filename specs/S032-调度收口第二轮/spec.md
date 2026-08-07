# Spec: S032 — 调度收口第二轮（S011b）：主循环收口 + portfolio 日志重试 + 状态机接线落库

> 状态：草案
> 作者：Claude  日期：2026-08-07
> 关联：`../S011-调度收口/spec.md`（第二轮，兑现 R6/R8/R10）、`../S031-调度收口盘前多层按战法回测/spec.md`（§0 切片表：本轮 = R6/R8/R10）、`../S012-工作流标灰/spec.md`（草案，盘中/盘后桩边界——本 spec 不碰）
>
> 级别：**medium**（跨层 >50 行；不碰新外部数据源 / 无新 AI 工具 / 无财务验算 → 不触发自动 large）。
> 流程门（AGENTS.md 分级工作流）：直接 develop 提交（无 feature 分支）+ issue 层单轮 review（`.scratch/`）+ 后端冒烟（:8900 启停 + 端点），免 playwright。
> 涉及交易工作流数据输出 → 过合规自查（§7，弱合规工程底线）。

---

## 1. 问题 / 目标

S031 完成调度收口第一轮（WAL/lifespan/BEIJING_TZ/预计算合并/seed/删 scheduler.py），但 S011 切片明确推后的三项仍在：

1. **R6 未做**：`CronScheduler.start()` 仍开 daemon 线程 + 线程内自建 `asyncio.new_event_loop()`（`scheduled_tasks.py:694,711`），与 FastAPI 主循环隔离——两套事件循环并存，是 S011 要废的「线程内 asyncio.run 桥接」残留。
2. **R8 未做**：`portfolio.start_scheduler` 的后台线程 `except Exception: pass` 静默吞错（`portfolio.py:195-196`，S031 已留注释「R8 第二轮改 logging」）。且该线程每次 tick `asyncio.run(_refresh_snapshot())` 新建循环——模块级 `_LOCK = asyncio.Lock()`（`portfolio.py:35`）被请求处理器（主循环）与后台线程（临时循环）**跨循环共用，互斥实际失效**（潜在并发洞）。
3. **R10 未做**：七态状态机（`workflow_state_machine.py`）从未接线——`PreMarketWorkflow.__init__` 建了个实例级状态机（`pre_market_workflow.py:96`）但 `run()` 全程不调 `transition()`，纯装饰；候选股盘前选出后无任何状态落库，打板工作流「候选→观察→监控→持仓→结算」中断在第一跳。

**目标**：
- 调度统一到 FastAPI 主事件循环（`asyncio.create_task`），删掉两个后台线程与跨循环桥接；portfolio 刷新异常改日志。
- 状态机接线落库：`workflow_state` 表（market_data.db）记录 (code, trade_date) 的七态状态；盘前 `run()` 自动落 candidate/filtered；其余流转走手动 API（盘中自动流转/盘后自动结算属 S012 未实现桩，本 spec 不碰）。

---

## 2. 背景

### 调度现状（R6/R8）

- `scheduled_tasks.CronScheduler.start()`（:680）：`threading.Thread(target=self._loop, daemon=True)`；`_loop`（:704）`asyncio.new_event_loop()` + `run_until_complete(self._ticker())`；`_tick`（:730）在自己循环里 `asyncio.create_task(self._run_task(task))`。
- `stop()`（:698）只置 `_running=False`，不 join（S031 R5 语义）。
- `app.py` lifespan（:53-61）：startup `_st.start_scheduler()` + `pf.start_scheduler(1800)`；shutdown `get_scheduler().stop()` + `pf._portfolio_stop.set()`。
- `portfolio.start_scheduler`（:185）：daemon 线程 `while not _portfolio_stop.wait(interval): try: asyncio.run(_refresh_snapshot()) except Exception: pass`。
- `_refresh_snapshot`（:177）只做 last_refresh 时间戳落盘（`async with _LOCK`）。
- 爆炸半径：`start_scheduler`/`_portfolio_stop` 的调用方仅 `app.py` lifespan + `tests/test_s031_scheduled_tasks.py`（rg 确认）；health `_check_scheduler`（`routers/health.py:87`）只读不启动。

### 状态机现状（R10）

- `WorkflowStatus` 七态：pending/candidate/watching/monitoring/holding/settled + 旁路 filtered；`_ALLOWED_TRANSITIONS` 定义合法流转（`workflow_state_machine.py:25-33`）；`transition(target, reason)` 非法返 False。
- 全仓仅两处引用：`pre_market_workflow.py:31,96`（装饰性实例）、`trading_workflow.py:20`（仅 import 枚举，未用）。无任何持久化。
- `PreMarketWorkflow.run()`（:109）产出：`pool.candidates`（qualified GeneScore 列表）、`pool.filtered_out`（`[{code,name,reason}]`，reason="基因得分未达标"）——状态落库的现成数据源。
- 盘后 `PostMarketWorkflow._settle_recommendations`（:79）返 `[]` 桩；盘中 `RealtimeWorkflow.monitor_stock`（:85）返 None 桩——S012（草案）范围，本 spec 不补。
- `settlement.settlement_engine.SettlementEngine` 已存在（settle/batch_settle/win_rate）但仅在 `routers/workflow.py:97` 实例化、无调用方——接线属后续 spec。
- DB 落点：`market_data.db`（`scheduled_tasks.py:18` `backend/data/market_data.db`，gitignored `backend/data/*.db`）——与 scheduled_tasks/scheduled_task_runs 同库；连接模式照抄（busy_timeout=30000 + WAL）。

---

## 3. 需求清单

### R6 调度模型统一（S011 R6 兑现）

- [ ] R6.1 `CronScheduler` 删 `threading.Thread` + `_loop` 自建循环；`start()` 改 async：在**当前（FastAPI 主）循环** `create_task(self._ticker())`，保留启动时 DB 残留 running 恢复逻辑（现 start() 内的 count_running 重建）。
- [ ] R6.2 `stop()` 改 async：置 `_running=False` + cancel ticker task（`asyncio.wait_for` 限时，超时不阻塞 shutdown）；已 spawn 的 `_run_task` 子任务随主循环关闭终止（与 S031 daemon 不 join 政策一致，注释说明）。
- [ ] R6.3 `start_scheduler()`/`stop_scheduler()` 改 async 包装；`app.py` lifespan 改 `await`。
- [ ] R6.4 portfolio 刷新一并上主循环：`pf.start_scheduler` → async 版（主循环 `create_task(_refresh_loop())`，循环内 `await asyncio.sleep(interval)`）；删 `_portfolio_stop: threading.Event` 与 daemon 线程；lifespan shutdown cancel task。理由：消灭第二处「线程内 asyncio.run」桥接 + 修 `_LOCK` 跨循环失效。

### R8 portfolio 异常日志（S011 R8 兑现）

- [ ] R8.1 `_refresh_loop` 每 tick `try/except Exception → logger.warning("[portfolio] 后台刷新失败: %s", e, exc_info=True)`，循环不中断（下一 tick 即天然重试）；删 `except Exception: pass`。

### R10 状态机接线落库（S011 R10 兑现）

- [ ] R10.1 新模块 `backend/workflow_state_repo.py`：`market_data.db` 内建 `workflow_state`（code/name/trade_date/status/reason/created_at/updated_at，UNIQUE(code,trade_date)）+ `workflow_state_history`（from/to/reason/created_at）两表；连接带 busy_timeout=30000 + WAL（照 `scheduled_tasks._get_connection` 模式，独立 `_DB_PATH` 常量便于测试 monkeypatch）。
- [ ] R10.2 Repo API：`ensure_candidate(code,name,trade_date,reason)`（insert-if-absent，不回退已进阶状态）、`ensure_filtered(...)`、`transition(code,trade_date,target,reason)`（读当前态 → `WorkflowStateMachine(cur).transition(target)` 校验 → 落库 + history；非法返 False）、`list_states(trade_date)`、`get_state(code,trade_date)`、`get_history(code,trade_date)`。
- [ ] R10.3 `PreMarketWorkflow.run()` 接线：步骤 2 候选池构建后，qualified→`ensure_candidate`（reason 含基因达标）、filtered_out→`ensure_filtered`（沿用 report 的 reason 字段）。**整段 try/except 隔离**——落库失败 logger.warning，不阻塞盘前主流程。
- [ ] R10.4 `routers/workflow.py` 新端点：
  - `GET /api/workflow/state?date=` → 当日状态列表 + 按态计数；
  - `POST /api/workflow/state/transition`（body: code/date/target/reason）→ 状态机校验，非法 400 + 说明当前态与允许目标；
  - `GET /api/workflow/state/{code}/history?date=` → 流转历史。
- [ ] R10.5 **手动流转模型**：除 pending→candidate/filtered 由盘前自动落库外，candidate→watching→monitoring→holding→settled 全部走手动 API（用户按自己操作流转）。盘中自动推进/盘后自动结算 = S012 桩范围，不实现。
- [ ] R10.6 状态机规则单一事实源：repo 复用 `workflow_state_machine._ALLOWED_TRANSITIONS`（经 `WorkflowStateMachine.transition`），不复制规则表。

### 明确不做（记录）

- 交易日历精确节假日（S031 seed 注释「推 S011b」）：本轮仍不做——无可靠离线节假日数据源（臆造日期 = 违反工程底线）；现状 cron 跳周末 + 非交易日 screener 返空池自然 no-op 已足够（YAGNI）。需要时另立 spec 接数据源。
- S012 标灰（桩→NotImplementedError + UI 徽标）：独立 spec，不并入。
- SettlementEngine 接线 / 盘后自动结算：依赖 K 线结算语义，另立 spec（可复用 S031 回测引擎的次日价格逻辑）。
- 前端呈现（候选抽屉显示状态 + 流转按钮）：本 spec 纯后端；前端面另立 spec（数据先积累）。
- `routers/scheduled_tasks.py` 读 `st._manager` 私有：S011 遗留，非本轮重点，不动（R6 不改 _manager，无破坏）。

---

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduled_tasks.py` | R6：`CronScheduler.start/stop` async 化、删 `_loop`/`self._thread`/threading；`start_scheduler`/`stop_scheduler` async |
| `backend/portfolio.py` | R6.4+R8：`start_scheduler` async（主循环 task）、删线程/`_portfolio_stop`、`_refresh_loop` 异常日志 |
| `backend/app.py` | lifespan 改 await（startup 两个 async start；shutdown await stop + cancel portfolio task） |
| `backend/workflow_state_repo.py`（新） | R10.1/R10.2 两表 + repo API |
| `backend/pre_market_workflow.py` | R10.3 run() 落库接线（try/except 隔离）；装饰性 `self.state_machine` 删除 |
| `backend/routers/workflow.py` | R10.4 三端点 |
| `backend/conftest.py` | `isolated_market_db` fixture 同时 patch `workflow_state_repo._DB_PATH` |
| `backend/tests/test_s031_scheduled_tasks.py` | `test_lifespan_shutdown` 适配 async start/stop（去 `_portfolio_stop` 断言） |
| `backend/tests/test_s032_workflow_state.py`（新） | repo/接线/端点单测 |
| `backend/tests/test_s032_scheduler_mainloop.py`（新） | R6/R8：主循环 ticker、stop cancel、portfolio 日志 |
| `specs/README.md` | 归档时补 S025–S032 索引行 + 修「下一个新 spec」编号 |

---

## 5. 设计方案

### D1 主循环收口方式

`CronScheduler` 保留 `start`/`stop` 名称但改 async 语义：

```python
async def start(self):      # 必须在运行中的事件循环内调用（lifespan）
    ...DB 残留 running 恢复（不变）...
    self._running = True
    self._task = asyncio.get_running_loop().create_task(self._ticker())

async def stop(self):
    self._running = False
    if self._task:
        self._task.cancel()
        with suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(asyncio.shield(self._task), timeout=2.0)
```

- `_ticker`/`_tick`/`_run_task` 逻辑不变——它们本就是协程，换到主循环即正确；handler 经 `execute_async` 的 `to_thread` 跑，不阻塞主循环。
- 备选「保留线程仅桥接主循环」否决：正是 S011 R6 要废的模式。

### D2 portfolio 一并上主循环（不只加日志）

`_LOCK` 跨循环互斥失效是真实并发洞（请求侧 add/remove/save 与后台刷新共用模块级 Lock，但后台在线程临时循环里 acquire）。统一后：

```python
async def _refresh_loop(interval: int):
    while True:
        await asyncio.sleep(interval)
        try:
            await _refresh_snapshot()
        except Exception as e:            # R8：日志，不吞
            logger.warning("[portfolio] 后台刷新失败: %s", e, exc_info=True)

async def start_scheduler(interval: int = 1800) -> asyncio.Task:
    return asyncio.get_running_loop().create_task(_refresh_loop(interval))
```

- lifespan 持 task 引用，shutdown `task.cancel()`。`_portfolio_stop` Event 删除（测试同步改）。
- 备选「保留线程只改日志」否决：桥接与跨循环 Lock 仍在，R6 只做一半。

### D3 状态落库模型

- **粒度**：(code, trade_date) 唯一——同一股不同交易日独立流转（打板按日换候选）。
- **自动 vs 手动**：盘前自动只落两态（candidate/filtered，来自 report 实际字段，禁臆造）；其余手动 API——因为 watching/monitoring/holding 的语义是「用户在盯/在持有」，只有用户知道，系统无数据源自动推进（盘中桩未实现）。settled 亦手动（自动结算属 SettlementEngine 接线 spec）。
- **insert-if-absent**：同日多次 refresh 盘前简报不重复写、不把用户已推进的 watching/holding 回退成 candidate。
- **隔离**：落库失败只 warning——状态记录是增强，不是盘前主流程的正确性依赖。

### D4 DB 落点与连接

与 scheduled_tasks 同 `market_data.db`（S011 R10 原话「状态落 market_data.db」）。`workflow_state_repo.py` 自带 `_DB_PATH` 常量 + `_get_connection()`（busy_timeout=30000 + WAL）——与 scheduled_tasks 平行而非 import 其私有；测试 fixture 两处一起 patch。备选「抽共享 db 模块」否决（8 行重复 < 跨模块重构面，YAGNI）。

### D5 端点设计

挂既有 `routers/workflow.py`（`tags=["workflow"]`，复用 `_serialize`）。transition 非法时 400 返回 `{current, allowed_targets}` 供前端后续做交互。鉴权沿用 app 级 `VR_API_KEY` 中间件，无新增。

---

## 6. 验收标准

- [ ] A1 `scheduled_tasks.py` 无 `threading`；`CronScheduler` 无 `_thread`/`_loop`；ticker 经主循环 `create_task` 启动。
- [ ] A2 `portfolio.py` 无 `threading`、无 `_portfolio_stop`、无 `except Exception: pass`；刷新异常有 warning 日志且循环存活。
- [ ] A3 :8900 启动→`scheduled_tasks` seed 存在、ticker/task 运行；Ctrl-C 退出优雅（无 hang、无 traceback 泄漏）。
- [ ] A4 `workflow_state`/`workflow_state_history` 建表（WAL）；盘前 run() 后：qualified 股行 status=candidate、filtered 股行 status=filtered；重复 run() 无重复行、无状态回退。
- [ ] A5 手动流转 API：合法流转 200 + history 增行；非法流转 400 + 当前态/允许目标；未知 code/date 404/400 明确。
- [ ] A6 `workflow_state_machine._ALLOWED_TRANSITIONS` 未被复制（rg 验证规则表只一处）。
- [ ] A7 落库异常注入时 `run()` 仍正常返回 report（隔离测试）。
- [ ] A8 `pytest -m "not live"` 全过（新增测试 + 既有适配；newsradar 联网 flaky 测试 --deselect 为 pre-existing，不算失败）。
- [ ] A9 状态输出仅客观流转记录，无方向性研判措辞。

---

## 7. 合规与工程底线自查（弱合规，CLAUDE.md §1.2）

- [ ] 不臆造：candidate/filtered 状态全部来自 `run()` 实际 report 字段；流转合法性由既有状态机规则校验；无合成数据。
- [ ] 私有数据隔离：`workflow_state` 含用户手动流转记录（反映个人交易意图）→ 存 `backend/data/market_data.db`（`backend/data/*.db` 已 gitignored，同 scheduled_tasks 先例）；不上传、不进 git。
- [ ] 防封：本 spec 零新增外部数据调用（纯内部 SQLite + 既有管道）。
- [ ] 状态/流转属客观流程记录，非方向性判断；端点无买卖时机输出。
- [ ] 手动流转由用户发起（半自动助手定位，用户即决策者）。

---

## 8. 测试计划

- **新增单测**（`test_s032_workflow_state.py`）：repo 建表/upsert 幂等/不回退进阶态；transition 合法+非法；pre_market 接线（mock screener → 断言 DB 行）；落库异常注入 run() 不挂；端点三枚（TestClient）。
- **新增单测**（`test_s032_scheduler_mainloop.py`）：`async def start` 在主循环建 task 且 tick 可触发；`stop` cancel 生效；portfolio `_refresh_loop` 异常后存活 + 日志（caplog）。
- **适配**：`test_lifespan_shutdown` 改 async start/stop 断言。
- **离线全量**：`cd backend && .venv/bin/python -m pytest -m "not live" --deselect tests/test_newsradar_global_intel.py::test_fetch_global_intel_wm_import_fails`。
- **冒烟**：:8900 启停 + `curl /api/workflow/state?date=<最近 qualified 日>` + 手动 transition 一条验证 DB。

---

## 9. 风险与回滚

- **主循环 ticker 与请求争抢**：handler 全经 to_thread，tick 本体 O(任务数) 轻量；风险低。回滚：git revert（恢复线程版）。
- **lifespan async 化破坏启动**：test_lifespan_shutdown + :8900 冒烟双保险。
- **状态表写放大**：每日盘前 ≤ 数百行 insert-if-absert，忽略不计。
- **回滚**：develop 直提交，按 commit 粒度 revert；新表留存无害（不读即无影响）。

---

## 10. 决策记录（2026-08-07）

- **级别 medium**：不碰新外部源/AI/财务验算 → 不自动 large；跨层 >50 行 → medium。流程门按 AGENTS.md（无 feature 分支，issue 层 review）。
- **portfolio 一并上主循环**（D2）：超出 R8 字面（仅日志），但修 `_LOCK` 跨循环失效 + 消灭第二处线程桥接，属 R6「废线程内 asyncio.run 桥接」原文范围。
- **手动流转模型**（D3/D5）：watching/monitoring/holding 无自动数据源（盘中桩未实现），诚实地让用户 API 流转；自动结算留 SettlementEngine spec。
- **交易日历不做**：无可靠离线节假日数据，臆造违规；现状周末跳过 + 空池 no-op 足够。
- **前端不做**：后端先行积累数据，呈现另立 spec。
