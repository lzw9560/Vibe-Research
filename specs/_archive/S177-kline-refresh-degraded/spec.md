# S177 — kline_refresh executor 静默吞 degraded 修复

> 状态：已实现（T1-T7 done，32 tests green + 全量 3200 passed 0 failed deselect 7 pre-existing + tsc0；2026-09-10）
> 关联：core-invariant「绝不静默吞掉错误」· §1.2 工程底线「判断须可复现/不臆造」· backlog M1（limitup_sti/service.py:270 + data.py:131-132）
> 分级：medium（跨 backend+frontend，4 文件改 + 1 测试文件加用例；走 issue 层单轮 review）
> 编号依据：specs/ 目录最新为 S176，本 spec 递增 S177

---

## §1 问题 / 目标

### 问题

`scheduler/executors/__init__.py` 的 `execute()`（line 76-80）与 `execute_async()`（line 133-141）在拿到 executor 返回值后，**无条件标 `run.status = "success"`**，完全不读 `result["status"]` 字段。当 executor 返回 `{"status": "degraded", ...}`（如 kline_refresh 在 baostock 未装时），`run.status` 仍说 success，`run.result` 把 degraded 信号埋进 JSON 列，`scheduled_tasks.last_run_status` 也标 success。下游全链路（today_status 推算 → 前端徽章 → 通知）因此把 degraded 当成功：UI 显示绿色「已完成」，掩盖故障。

这是 codebase **已知 backlog M1**——`limitup_sti/service.py:270` 与 `limitup_sti/data.py:131-132` 两处原始注释早承认「execute() 不查 result["status"] payload，scheduled_task_runs.status 列仍记 success，run.status 改造见 backlog（M1）」。

### 目标

execute 读 `result["status"]` 反映 degraded/failed 到 `run.status` + `last_run_status` + 通知 + today_status 推算 + 前端徽章，全链路诚实。修复直接落实 core-invariant「绝不静默吞掉错误」。

---

## §2 背景（fresh Read 核实）

**精确代码路径**（2026-09-10 fresh Read 核实，行号真实）：

1. **kline_refresh**（`data_ops.py:63-84`）返回 `{"status": "ok"|"degraded", ...}`：line 78 `{"status": "ok" if ret == 0 else "degraded"}`、line 81 ImportError → `{"status": "degraded", "reason": ...}`、line 84 Exception → `{"status": "degraded", "reason": ...}`。它不 raise，只返 dict。**它是受害方非病源，无需改。**

2. **execute()**（`__init__.py:66-98`）：line 76 `result = executor(task.payload)` 拿到 degraded dict → line 77 `run.status = "success"` 无条件 → line 78 `run.result = result`（degraded 信号被埋进 result JSON）→ line 80 `_manager.update_task_status(task.id or 0, "success", started_at)`（last_run_status 也标 success）。

3. **execute_async()**（`__init__.py:103-164`）：同病。line 137 `run.status = "success"` 无条件 → line 141 `update_task_status(..., "success", ...)`。

4. **_send_notification()**（`__init__.py:166-185`）：line 172 `status_text = "成功" if status == "success" else "失败"`——二分无 degraded 语义。且 notify_on_failure 仅 except 分支触发（line 95/161），degraded 不 raise 故不发任何通知。

5. **TaskRun.status**（`models.py:33`）：自由 str `status: str = "running"`，无枚举约束——可直接加 `"degraded"` 值，无需改 model / 迁移。

6. **_compute_today_status()**（`routers/scheduled_tasks.py:19-45`）：line 40 success→done / line 42 failed→error / line 45 其余→pending。degraded 落 pending = 绿色 done 变灰色「待运行」，比 success 更误导（用户以为没跑）。

7. **execute() 同步版无生产调用方**：router（`scheduled_tasks.py:191`）与 CronScheduler 均走 `execute_async()`。但两处同病，为防未来误用 + 一致性，两处都修。

8. **reap_stale_running**（`db.py:239-270`）：标 stale running 为 `failed`——独立路径，不涉 degraded，不受影响。

9. **backlog M1 注释**（fresh grep 核实，非臆造）：
   - `limitup_sti/service.py:270`：「run.status 记 save 失败见 backlog（M1，需改 execute()）」
   - `limitup_sti/data.py:131-132`：「scheduled_task_runs.status 列仍记 success（execute() 不查 result["status"] payload），仅 result payload + 日志记 error——run.status 改造见 backlog（M1）」

10. **executor 返回值全谱**（fresh grep `scheduler/executors/` 核实，8 域文件）：
    - success/正常：`ok`、`due`（s066 写了 checkpoint = 干了活）、`skipped`（intraday 非交易时段 = 正常跳过）、`not_due`（s066 没到期）、`nothing_to_settle`（t1 无 NULL 待结算）、`no_dir`（monthly_vacuum 目录不存在 = 无事可做）
    - degraded：`degraded`（kline_refresh）、`partial`（monthly_vacuum 部分库失败）、`source_fail`（limitup 数据源失败）、`no_emotion_data`（limitup 无情绪数据）、`script_not_found`（kg 脚本不存在）、`baostock_unavailable`（baostock 不可用，impl 时 grep 实测发现补全）
    - failed：`error`、`error: {e}`（f-string 前缀，limitup/first_board/ai_portfolio/premarket/intraday 多处）、`timeout`（kg 超时）
    - 无 status 字段：`{"ok": True}`、`{"sync": True}` 等（测试 + 部分 executor）

---

## §3 需求清单

**R1** `execute()` / `execute_async()` 拿到 result 后，若 result 是 dict 且含 `"status"` 字段，按映射规则标 `run.status`（非 ok → degraded/failed），而非无脑 success。无 status 字段或 status==ok/due/skipped/not_due/nothing_to_settle/no_dir → 保持 success（backward-compat，不破坏现有 30+ executor 与测试）。

**R2** 定义统一 status 映射规则（须覆盖 §2.10 全谱），集中为一个纯函数 `_resolve_run_status(result) -> str`，返回 `"success" | "degraded" | "failed"`：
- `error` / `error: *`（startswith） / `timeout` → `failed`（核心功能失败）
- `degraded` / `partial` / `source_fail` / `no_emotion_data` / `script_not_found` → `degraded`（部分失败/可恢复）
- 其余（ok/due/skipped/not_due/nothing_to_settle/no_dir/未知值/None/无字段） → `success`

**R3** `_send_notification()` 加 degraded 文案分支（「降级」，非「成功」非「失败」）。

**R4** degraded 触发 `notify_on_failure`（if flag set）——degraded 是隐性故障，用户 opted into notify_on_failure（默认 True），应告知。不新增 notify_on_degraded 字段（YAGNI，notify_on_failure 已覆盖「出问题就告警」语义）。

**R5** `_compute_today_status()` 认 degraded last_run_status → 映射 today_status。**选 Option B**：新增 amber「降级」态（`today_status="degraded"`），诚实区分「部分成功」与「全失败」。Option A（复用 error 红色）作为最小改动 fallback 记录，不采用。

**R6**（Option B）前端 today_status 联合类型 + STATUS_STYLES Record + ETA 三元补 degraded 槽。

---

## §4 受影响文件

| 文件 | 改动 | 说明 |
|---|---|---|
| `backend/scheduler/executors/__init__.py` | 改 | 新增 `_resolve_run_status()` 纯函数 + execute()/execute_async() 读 result status + _send_notification 三分支文案 + 通知触发逻辑重构 |
| `backend/routers/scheduled_tasks.py` | 改 | `_compute_today_status()` 加 degraded 分支（Option B） |
| `frontend/src/lib/query/scheduledTasks.ts` | 改 | today_status 联合类型加 `"degraded"`（line 13） |
| `frontend/src/components/workflow/TaskStatusCard.tsx` | 改 | STATUS_STYLES Record 加 degraded entry（amber）+ ETA 三元补分支（lines 199-205） |
| `backend/tests/test_task_executor.py` | 改 | 新增 degraded / backward-compat / skipped 不误杀 / error-from-dict 用例 |
| `backend/scheduler/executors/data_ops.py` | **不改** | kline_refresh 已正确返 degraded dict（受害方非病源） |
| `backend/scheduler/models.py` | **不改** | TaskRun.status 自由 str 无枚举约束，可直接加 "degraded" 值 |
| `backend/scheduler/db.py` | **不改** | reap_stale_running 标 stale 为 failed，独立路径不涉 degraded |

---

## §5 设计方案

### 5.1 status 映射纯函数

新增模块级 `_resolve_run_status(result: Any) -> str`（`__init__.py`），集中映射逻辑，DRY（execute + execute_async 共用），可独立单测：

```python
_DEGRADED_STATUSES = frozenset({
    "degraded", "partial", "source_fail", "no_emotion_data",
    "script_not_found", "baostock_unavailable",
})

def _resolve_run_status(result: Any) -> str:
    """executor 返回值 → run.status 映射。

    - dict 无 status 字段 / status 未匹配任何类 → success（backward-compat）
    - error / error: * / timeout → failed（核心功能失败，executor 吞了异常返 dict）
    - degraded / partial / source_fail / no_emotion_data / script_not_found → degraded
    - ok / due / skipped / not_due / nothing_to_settle / no_dir → success（正常完成或正常跳过）
    """
    if not isinstance(result, dict):
        return "success"
    status = result.get("status")
    if status is None:
        return "success"
    if isinstance(status, str) and (status == "error" or status.startswith("error:") or status == "timeout"):
        return "failed"
    if isinstance(status, str) and status in _DEGRADED_STATUSES:
        return "degraded"
    return "success"
```

**关键安全**：`skipped`/`not_due`/`nothing_to_settle`/`no_dir` 不在任何 degraded/failed 集合 → fall through 到 success。intraday 非交易时段返 skipped 是正常跳过不算故障，**不误杀**（risk #7 最大设计风险已防）。

### 5.2 execute() / execute_async() 接线

```python
# execute() try 块（原 line 76-84）
result = executor(task.payload)
run.status = _resolve_run_status(result)   # 原: run.status = "success"
run.result = result
run.finished_at = datetime.now().isoformat()
_manager.update_task_status(task.id or 0, run.status, started_at)  # 原: "success"

# 通知（重构：success→notify_on_success；degraded/failed→notify_on_failure）
if run.status == "success":
    if task.notify_on_success:
        self._send_notification(task, run, "success")
else:  # degraded 或 failed（来自 result dict，非异常）
    if task.notify_on_failure:
        self._send_notification(task, run, run.status)
```

execute_async() 同构（line 133-145）。

except 块不变（异常 = failed + notify_on_failure，已有）。

### 5.3 _send_notification() 三分支

```python
status_text = {"success": "成功", "degraded": "降级", "failed": "失败"}.get(status, "未知")
```

### 5.4 _compute_today_status() 加 degraded 分支（Option B）

```python
if last_run_date == today_bj and status == "degraded":
    return "degraded"
```

### 5.5 前端（Option B）

- `scheduledTasks.ts:13`：`today_status: "done" | "error" | "running" | "pending" | "degraded"`
- `TaskStatusCard.tsx` STATUS_STYLES 加：
  ```ts
  degraded: {
    node: "border-[hsl(38_92%_50%)] bg-[hsl(38_92%_50%/0.3)]",
    pill: "bg-[hsl(38_92%_50%/0.12)] text-[hsl(38_92%_50%)]",
    label: "降级",
  },
  ```
- ETA 三元（lines 199-205）补：`... : t.today_status === "degraded" ? "降级" : "错误"`

**doneCount 逻辑不变**（line 89 只 filter `=== "done"`）：degraded 不计已完成——正确，degraded 不是全完成。载入按钮（line 217 `=== "done"`）也不对 degraded 显示——正确，degraded 产出可能不完整。

---

## §6 验收标准

**A1** mock executor 返 `{"status": "degraded", "reason": "X"}` → `run.status == "degraded"`，`run.result == 原 dict`（reason 保留），`refreshed.last_run_status == "degraded"`。

**A2** mock executor 返 `{"status": "ok"}` 或 `{}`（无 status 字段）或 `{"sync": True}` → `run.status == "success"`（backward-compat，不破坏 test_task_executor.py 现有用例）。

**A3** mock executor 返 `{"status": "skipped", "reason": "非交易时段"}` → `run.status == "success"`（intraday 正常跳过不算故障，**不误杀**）。

**A4** mock executor 返 `{"status": "error: boom"}` → `run.status == "failed"`（从 result dict 映射，非异常路径）；`{"status": "timeout"}` → `run.status == "failed"`。

**A5** today_status 推算：`last_run_status == "degraded"` + `last_run_at == 今日` → `_compute_today_status` 返 `"degraded"`（非 done 非 pending 非 error）。

**A6** 通知：degraded run + `notify_on_failure=True` → `_send_notification` 被调且 status_text == "降级"（非「失败」非「成功」）；`notify_on_failure=False` → 不调。

**A7** 现有 `test_task_executor.py` 全绿（不回归——lines 114/153/168/279/335 返无 status 字段 dict 保持 success）。

**A8** `cd frontend && npx tsc --noEmit` 零错误（STATUS_STYLES Record key 全覆盖 today_status 联合类型）。

---

## §7 合规与工程底线自查

| 底线 | 自查 |
|---|---|
| 不臆造数据 | ✅ 本修复让 degraded/failed 状态如实反映到 run.status——当前说谎 success 才是「臆造状态」。修复后状态可复现（executor 返回值 → run.status 映射规则透明可审计） |
| 私有数据隔离 | ✅ 无涉——不改数据存储路径，run.status 是任务执行状态非用户私有数据 |
| em_get 防封 | ✅ 无涉——不改东财端点调用路径。kline_refresh 走 baostock 非 em_get |
| core-invariant「绝不静默吞掉错误」 | ✅ **本修复直接落实此条**——当前 execute 静默把 degraded 吞成 success，修复后 degraded/failed 如实冒泡到 run.status + last_run_status + 通知 + UI |
| 弱合规（风险提醒级） | 无涉——非数据输出/AI 提示词/交易信号改动 |

**工程底线全过。** 弱合规无关（不涉投资判断/免责/个股呈现）。

---

## §8 测试计划

**新增用例**（test_task_executor.py，TDD 先写后跑）：

1. `test_degraded_result_marks_run_degraded`：monkeypatch executor 返 `{"status": "degraded", "reason": "cannot import fetch_daily_bars"}` → `run.status == "degraded"` + `run.result == 原 dict` + `refreshed.last_run_status == "degraded"`。
2. `test_no_status_field_stays_success`（backward-compat）：executor 返 `{}` / `{"ok": True}` / `{"sync": True}` → `run.status == "success"`。
3. `test_skipped_not_misclassified`：executor 返 `{"status": "skipped", "reason": "非交易时段"}` → `run.status == "success"`。
4. `test_error_from_dict_maps_failed`：executor 返 `{"status": "error: boom"}` → `run.status == "failed"`（非异常路径）。
5. `test_timeout_maps_failed`：executor 返 `{"status": "timeout"}` → `run.status == "failed"`。
6. `test_degraded_triggers_notify_on_failure`：degraded + `notify_on_failure=True` → `_send_notification` 被调，status_text 含「降级」。
7. `test_today_status_degraded`：`last_run_status == "degraded"` + `last_run_at == 今日` → `_compute_today_status` 返 `"degraded"`。

**回归命令**：
```bash
cd backend && .venv/bin/python -m pytest tests/test_task_executor.py -q
cd backend && .venv/bin/python -m pytest -m "not live" -q \
  --deselect tests/test_newsradar.py::test_fetch_global_intel_wm_import_fails \
  --deselect tests/test_s032_refresh_loop.py \
  --deselect tests/test_s040_backfill.py
cd frontend && npx tsc --noEmit
```

---

## §9 风险与回滚

**R-1 行为变更（非回归）**：当前返 `error: {e}`/`timeout` 的 executor 被标 success（绿 done），修复后标 failed（红 error）。用户会看到「新」失败——这是停止说谎的预期效果，非回归。**缓解**：spec §1 明确标注此行为变更；若用户不愿一次性揭示，可分阶段（先只映射 degraded→degraded，error 家族暂留 success 下个 spec 处理）。但推荐一次性修干净。

**R-2 映射误杀**：最大设计风险。`skipped`/`not_due`/`nothing_to_settle`/`no_dir` 是正常跳过，若误归 degraded/failed 会把 intraday 非交易时段正常跳过标红。**已防**：映射规则 §5.1 明确这些值 fall through 到 success，且 A3 验收点专测 skipped 不误杀。

**R-3 script_not_found 归类**：kg 脚本不存在归 degraded 还是 failed 是判断题。spec 归 degraded（配置缺失非运行时崩溃）。若用户觉得该归 failed，改 `_DEGRADED_STATUSES` 一行即可。此为可调点。

**R-4 前端 Record 缺 key**：STATUS_STYLES 是 `Record<TodayStatus, ...>`，加 today_status 值不补 entry → tsc 编译报错。**已防**：A8 验收 tsc --noEmit；tasks T5 显式补 entry。

**R-5 未知 status 值**：未来新增 executor 可能返新 status 值不在任何集合。`_resolve_run_status` 对未知值 fall through 到 success（保守，不误杀）。新增值时须同步更新 `_DEGRADED_STATUSES` 或加 failed 前缀判断。**缓解**：函数 docstring 列全谱 + 注释「新增 executor status 值须审视映射」。

**R-6 pre-existing failure（非 S177 引入，已核实因果链断）**：全量回归 9 failed 经核实——
- test_regression_bugs + test_registry：task_type / tool_names 集合缺 S175/S176/S150/S167 新增项（trade_journal_daily / ofi_collect / kg_audit / query_kg_entities / query_kg_relations），S177 顺手补齐（同 test_task_executor 同类 test debt）。
- s070 seal_intraday 4 个：`seal_intraday_collect` 走 subprocess（intraday.py:39-48 超时/失败返 `{"error":...}` 无 data_status/written），测试 mock in-process 函数（em_zt_topic_pool）被 subprocess 隔离不生效——pre-existing subprocess/mock 范式问题。S177 改 execute 读 result status 不影响 `_execute_seal_intraday_collect`（测试直接调 executor 函数不走 execute），**无因果**。
- s144 unbuyable 3 个：is_unbuyable 检测返 False，S177 没碰 unbuyable 检测，**无因果**。
7 个 s070/s144 pre-existing 单独 spec 处理（非 S177 范围）。§8 回归命令加 `--deselect tests/test_s070_seal_intraday_executor.py --deselect tests/test_s144_unbuyable_t1.py`。

**回滚**：全部改动集中在 4 文件 + 1 测试文件。`git revert <commit>` 即可回退。无 DB 迁移（TaskRun.status 自由 str，加 "degraded" 值不需 schema 变更）。无配置变更。