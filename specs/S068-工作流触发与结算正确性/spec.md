# Spec: S068 — 工作流触发与结算正确性

> 状态：已实现(2026-08-15)
> 作者：  日期：2026-08-15
> 关联：S026（盘前异步采集）/ S034（settled 流转即结算）/ S038（结算市价预填）/ S048（盘前快照）

## 1. 问题 / 目标

盘前采集触发端点在生产环境必 500、后台采集任务不保留引用可能被 GC 回收、settled 流转的 TOCTOU 竞态导致 winrate 双重记账。三者同属"采集触发与结算正确性"，合并修复。目标：点"采集"能真正触发盘前采集、采集任务不丢、同一次结算只写一条 winrate 记录。

## 2. 背景

- `routers/workflow.py` 的 `refresh_pre_market` 原为 sync `def` 端点，函数体调 `asyncio.create_task(_collect(...))`。Starlette 把 sync 端点丢进 anyio 线程池执行（线程内无 running event loop），`create_task` 抛 `RuntimeError: no running event loop` → 500。前端"采集"按钮（`frontend/src/lib/api/workflow.ts:33`）正调此端点；`_collect` 全仓唯一非测试调用方即此处（grep 确认，`scheduled_tasks` 的 `seal_intraday_collect` 同名不同物），故无任何调度绕过它直接采集。已用最小 TestClient 走真实 ASGI 路径复现 RuntimeError。
- 现有测试 `test_workflow_async.py` 用 `asyncio.run(wf.refresh_pre_market(...))` 调用——`asyncio.run` 提供了 running loop，恰好掩盖该 bug。
- `asyncio.create_task` 返回值未保留——`_collect` 内有 `await`/`to_thread` 挂起点，CPython 文档明确警告未保留引用的 task 可能被 GC 中途回收。同项目 `intraday_sentiment.py` 的 `self._task = create_task(...)` 是正确范式。
- `workflow_state_repo.py` 原 `transition()`：`get_state`（连接 A 读，连完即关）→ 状态机校验 → `UPDATE`+history（连接 B 写），读与写跨两个连接、无事务包裹、无锁。两个并发 `holding→settled`（带 exit_price）都对着陈旧 `holding` 通过校验、都写 history；回到 router `_settle_on_transition` 时 `settled_at` 仍 NULL（`mark_settled` 在 `record_settlement` 之后才落），两者都过幂等检查、都 `record_settlement` → 写两条 winrate 记录。`busy_timeout` 只防 DB 写锁，不防此应用层逻辑竞态。TestClient 串行调用测不出（旧代码串行下第二请求也会被状态机挡、只写 1 条——假信心）。
- `settlement_recorder.py` `if entry_price and exit_price is not None:` 运算符优先级实际为 `entry_price and (exit_price is not None)`，对正常非零价格结果恰好正确（非活跃 bug），但 `entry=0` 靠短路绕过除零纯属侥幸，属结算正确性路径上的隐患。

## 3. 需求清单

- [x] R1（采集触发）：`refresh_pre_market` 改为 `async def`，使其在 Starlette 事件循环线程内执行，`asyncio.create_task` 不再抛 RuntimeError；并发守卫（check→set 无 await）保持原子。
- [x] R2（任务不丢）：`create_task` 返回值保留强引用（模块级 set + `add_done_callback(discard)`），任务不被 GC 中途回收。
- [x] R3（流转原子性 · 承重修复）：`transition()` 的读-校验-写改为单连接单事务，`UPDATE ... WHERE code=? AND trade_date=? AND status=<期望当前态>` 按 rowcount 判定原子抢占；并发流转时后到者 rowcount=0 失败返回明确 detail。**此条才是防 settled 双写/双重记账的承重层**——第二个并发 `holding→settled` 在 UPDATE 处失败、返 400、到不了 `_settle_on_transition`。`_settle_on_transition` 维持原顺序（record → `mark_settled`），失败时 settled_at 未落、可重试恢复。
- [x] R4（条件修复）：`settlement_summary` 条件改为 `entry_price not in (None, 0) and exit_price is not None`，消除运算符优先级隐患（不改变正常非零价格行为）。
- [x] R5（真并发回归测试）：repo 层 `threading` 并发直测 `transition()`——N 线程并发 `holding→settled` 断言恰好 1 ok / 1 history / 1 winrate，且该测试在回退 R3 的旧实现（无 `WHERE status` 守卫）上会失败，证其区分力；另补 TestClient 路径触发 `refresh` 断言 200（锁 R1 不回退）；补 `settlement_summary` 条件用例。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/routers/workflow.py` | R1 `refresh_pre_market`→`async def`；R2 模块级 `_pending_collections` set 保留 task 引用 |
| `backend/workflow_state_repo.py` | R3 `transition()` 改单连接事务 + `WHERE status=?` 原子抢占 |
| `backend/settlement_recorder.py` | R4 `settlement_summary` 条件修正 |
| `backend/tests/test_s068_workflow_correctness.py` | R5 新增：threading 并发直测 + settlement_summary 条件 + refresh TestClient 200 |

## 5. 设计方案

### R1+R2 采集端点
```
_pending_collections: set[asyncio.Task] = set()   # R2：强引用，防 GC

@router.post("/api/workflow/pre-market/refresh")
async def refresh_pre_market(...) -> Dict[str, Any]:
    ...（守卫与历史不可变检查不变）...
    t = asyncio.create_task(_collect(run_id, target_date))
    _pending_collections.add(t)
    t.add_done_callback(_pending_collections.discard)
    return {"run_id": run_id, "status": "running"}
```
async 端点在事件循环线程执行 → `create_task` 有 running loop；check→set 之间无 await，单事件循环下原子（多 worker 才需外部协调，属既有 TODO，不属本 spec 范围）。

### R3 流转原子化（承重）
读+校验+写收敛到单连接单事务，`WHERE status=<期望当前态>` 让并发流转的"后到者"rowcount=0：
```
def transition(code, trade_date, target, reason="", ...):
    target_status = WorkflowStatus(target)          # ValueError → 未知状态
    conn = _get_connection()
    try:
        row = conn.execute("SELECT status FROM workflow_state WHERE code=? AND trade_date=?", ...).fetchone()
        if row is None: return False, "该日无此股的工作流状态记录: ..."
        current_status = WorkflowStatus(row["status"])
        machine = WorkflowStateMachine(current_status)
        if not machine.transition(target_status, reason):
            return False, f"当前状态 {current_status.value} 不允许流转到 {target_status.value}（允许: ...）"
        now = _now_iso()
        cur = conn.execute(
            "UPDATE workflow_state SET status=?, reason=?, updated_at=?, "
            "entry_price=COALESCE(?,entry_price), exit_price=COALESCE(?,exit_price), "
            "strategy=COALESCE(?,strategy), attention_mode=COALESCE(?,attention_mode) "
            "WHERE code=? AND trade_date=? AND status=?",
            (target_status.value, reason, now, entry_price, exit_price, strategy, attention_mode,
             code, trade_date, current_status.value))
        if cur.rowcount == 0:
            return False, "状态已被并发流转改变，请重试"   # 原子抢占失败
        conn.execute("INSERT INTO workflow_state_history (...) VALUES (...)", (...))
        if target_status == WorkflowStatus.CANDIDATE:
            conn.execute("UPDATE workflow_state SET settled_at=NULL WHERE code=? AND trade_date=?", ...)
        conn.commit()
    finally:
        conn.close()
    return True, "ok"
```
保留既有 `(ok, detail)` 返回签名与 400 detail shape，router 无需改。`_settle_on_transition` 维持 S034 原顺序（`record_settlement` → `mark_settled`）：R3 已保证同一 (code,date,round) 仅 1 个请求能走到结算，原顺序下若 `record_settlement` 抛异常则 settled_at 未落、用户可重试恢复——**可恢复**优于"先抢占后 record"的不可恢复漏记。

### R4 条件修正
`if entry_price not in (None, 0) and exit_price is not None:` —— 对正常非零价格行为不变（既有测试 `test_settlement_summary_math` 的 entry=0→0.0、entry=None→hold_days 0 断言仍成立），消除运算符优先级隐患。

### 取舍（grill 后修订）
- **删去原 R4「claim_settlement 抢占式结算幂等」**：grill trace 证明 R3 的 `WHERE status=current` 已在 UPDATE 处挡住第二个并发 `holding→settled`（rowcount=0、返 400、到不了 `_settle_on_transition`），claim_settlement 对"防双写"冗余。且其"先抢占 settled_at 再 record"顺序把可恢复失败（record 抛异常→settled_at 未落→可重试）改成了不可恢复漏记（settled_at 已落→重试被 R3 挡→永久缺记），纯属为防一个 R3 已防住的竞态而引入更糟的失败模式，违反 YAGNI。故删 `claim_settlement`、`_settle_on_transition` 回原顺序。
- 不引入 `threading.Lock`：SQLite 单连接事务 + `WHERE status=?` 的 rowcount 原子判定天然跨进程安全（依赖 DB 串行化）。锁只护单进程，反不如 DB 原子。
- **验收换 repo 层线程并发直测**：TestClient（同步）串行处理请求，两个"并发"POST 实际串行化——第二个在 R3 下因 status 已变而失败、写 1 条，但旧代码串行下第二请求也会被状态机挡、同样写 1 条，**即旧代码上 A3 也绿**，假信心。R3 的原子性是 DB 层属性，故用 `threading` 在 repo 层直测 `transition()`：N 线程并发 `holding→settled` → 恰好 1 ok/1 history/1 winrate；该测试在回退 R3 的旧实现上写 N 条、会失败，证其区分力。

## 6. 验收标准

- [x] A1 受影响测试子集全绿：S068 新增 4 + 回归（test_s034/test_s032/test_s033/test_workflow_async/test_workflow_snapshot）36，共 40 全过，不回退（全量 `pytest -m "not live"` 未跑——newsradar 联网慢测试按 memory 单独 deselect）。
- [x] A2 TestClient 路径：`POST /api/workflow/pre-market/refresh`（mock `_collect`）返回 200、`status==running`、`run_id` 非空（锁 R1/R2：原 sync `def`+`create_task` 经 TestClient 必 500）。
- [x] A3（承重）repo 层 `threading` 并发直测：8 线程并发 `transition(holding→settled)` → 恰好 1 个 `ok=True`、`to_status='settled'` history 恰好 1 行、winrate 恰好 1 条。
- [x] A4 区分力佐证（手动核验）：临时去掉 R3 的 `AND status=?` 守卫后跑 A3，8 线程写出 **5 个 ok=True**（竞态实发）→ 断言失败；还原守卫后 1 个 → 通过。证 A3 在脆弱实现上失败、非假信心。已还原，不入常驻 CI。
- [x] A5 `settlement_summary(0.0, 11.0, ...)` 仍返 `return_pct=0.0`（不除零、不抛异常）；`(10.0, 11.0)` 仍 10.0；`exit=None` → 0.0；`entry=None` → hold_days 0。
- [ ] A6（数据正确性）`return_pct` 公式经 `~/tools/financial_rigor.py cross-validate` 一致——本 macOS 无 `~/tools/`（CLAUDE.md §5 Windows 工具），formula 已由测试断言 `return_pct==10.0`（entry=10/exit=11）算术锁定，留待 Windows 环境手动 `financial_rigor.py` 复核。

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机：本 spec 纯正确性修复，不新增研判/推荐输出，无新增用户可见措辞。不触发合规仪式。
- [x] 判断可复现：R3 修复的是"胜率记账不重记/可复现"——正是 §1.2 工程底线"让胜率数字为真"的前提；A6 跑 `financial_rigor.py` 验算 return_pct 公式。禁臆造/心算。
- [x] 涨停四池/连板股榜：不涉及。
- [x] 用户私有数据：winrate.db 仍只在 `.vibe-research/`（`config.WINRATE_DB_PATH`），测试经 `tmp_winrate` 注入 tmp db，绝不碰用户真实库（沿用 S034 测试隔离）。未进 git、未上传。
- [x] 新增东财端点：不涉及，无新 `em_get`。

## 8. 测试计划

- 离线快测：`cd backend && .venv/bin/python -m pytest tests/test_s068_workflow_correctness.py tests/test_workflow_async.py tests/test_s034_settlement.py tests/test_workflow_snapshot.py -m "not live" -p no:cacheprovider`（newsradar 联网慢测试不在本批，按 memory 单独 deselect）。
- `tests/test_s068_workflow_correctness.py`：A2（TestClient refresh 200）、A3（threading 并发 transition）、A5（settlement_summary 条件）。
- A4 手动核验：临时去掉 R3 `AND status=?` 跑 A3 观察失败。
- A6 手动验算：`python ~/tools/financial_rigor.py cross-validate --field return_pct --values '{"程序":10.0,"手算":10.0}'`。

## 9. 风险与回滚

- 风险：R3 改 `transition` 事务模型——既有调用方（`routers/workflow.py` 端点、`test_s034` 链式流转）依赖 `(ok, detail)` 签名与 400 detail shape，须保持不变；改完跑全量 workflow 测试防回退。
- 回滚：三文件改动独立、可 `git revert` 单 commit；无 schema 变更（删 `claim_settlement`、保留 `mark_settled`）。
- 后续（不在本 spec 范围）：`is_terminal` 命名与转移表语义矛盾；`trading_workflow`/`realtime_workflow`/`pre_market_workflow` 的时区 naive 阶段判定与 `_resolve_date` 死循环；盘前双采集路径（`_collect` vs `PreMarketWorkflow.run`）的架构收敛。以上另行立项。
