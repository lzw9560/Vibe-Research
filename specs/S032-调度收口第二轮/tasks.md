# Tasks: S032 — 调度收口第二轮（S011b）

> 对应 `spec.md`。medium 级：直接 develop 提交，每任务一 commit（`feat(S032):` / `refactor(S032):` / `test(S032):`）。

## 任务清单

| ID | 任务 | 需求 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|---|
| T1 | `backend/workflow_state_repo.py` 新建：`_DB_PATH`（market_data.db）+ `_get_connection`（busy_timeout+WAL）+ `_ensure_tables`（workflow_state / workflow_state_history）+ repo API（ensure_candidate/ensure_filtered/transition/list_states/get_state/get_history） | R10.1,R10.2,R10.6 | — | repo 单测过；规则复用 `WorkflowStateMachine.transition` | ⬜ |
| T2 | `conftest.py` `isolated_market_db` 同时 patch `workflow_state_repo._DB_PATH`；`test_s032_workflow_state.py` repo 层测试（幂等/不回退/合法非法流转/history） | R10.1 | T1 | repo 测试全过 | ⬜ |
| T3 | `pre_market_workflow.py` run() 接线：pool 构建后 qualified→ensure_candidate、filtered_out→ensure_filtered；整段 try/except + logger.warning；删装饰性 `self.state_machine` | R10.3 | T1 | 接线测试：mock screener→DB 行正确；异常注入 run() 不挂 | ⬜ |
| T4 | `routers/workflow.py` 三端点：`GET /api/workflow/state?date=` / `POST /api/workflow/state/transition` / `GET /api/workflow/state/{code}/history`；非法流转 400 带 current+allowed_targets | R10.4,R10.5 | T1 | TestClient 端点测试过 | ⬜ |
| T5 | `scheduled_tasks.py` R6：`start/stop` async 化（主循环 create_task / cancel+限时等待）、删 `_loop`/`_thread`/`threading`；`start_scheduler`/`stop_scheduler` async | R6.1-R6.3 | — | 主循环 ticker 测试：tick 可触发、stop cancel 生效 | ⬜ |
| T6 | `portfolio.py` R6.4+R8：`start_scheduler` async（主循环 `_refresh_loop`）、删线程/`_portfolio_stop`、异常 `logger.warning(..., exc_info=True)` 循环存活 | R6.4,R8.1 | — | _refresh_loop 异常存活+日志测试（caplog） | ⬜ |
| T7 | `app.py` lifespan：startup `await _st.start_scheduler()` + `await pf.start_scheduler(1800)`（持 task 引用）；shutdown `await _st.get_scheduler().stop()` + cancel portfolio task；`test_lifespan_shutdown` 适配 | R6.3 | T5,T6 | lifespan 测试过；:8900 启停优雅 | ⬜ |
| T8 | 冒烟 + 归档：:8900 启停 + seed 验证 + curl state/transition 一条验 DB；tasks 全 ✅ 后 spec 头部状态→已实现+日期；`specs/README.md` 补 S025–S032 索引行、修「下一个新 spec」编号；commit 归档 | A3-A9 | T1-T7 | 冒烟过；README 索引齐 | ⬜ |

## 依赖图

```
T1(repo) ─ T2(repo 测试) ─ T3(盘前接线) ─ T4(端点)
T5(scheduler R6) ─┐
                  ├─ T7(lifespan 适配) ─ T8(冒烟+归档)
T6(portfolio R6+R8) ┘
```

- T1-T4（R10 线）与 T5/T6（R6/R8 线）可并行；T7 是汇合点。
- T8 收尾：全量 `pytest -m "not live"`（--deselect newsradar 联网 flaky）+ 冒烟 + 归档。

## 合规检查点

- T1/T3：状态数据全部来自 report 实际字段（禁臆造）；规则单一事实源（不复制 `_ALLOWED_TRANSITIONS`）
- T3：落库失败不阻塞盘前主流程（try/except 隔离）
- T5/T6：主循环任务不阻塞请求（handler 经 to_thread）
- 全程零新增外部数据调用（无 em_get 新端点）
