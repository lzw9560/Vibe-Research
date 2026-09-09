# S177 tasks.md — 可执行 checklist

> 实现：TDD 先写测试（RED）→ 实现（GREEN）→ 回归。依赖序见每条标注。
> 命令中 `.venv/bin/python` = macOS venv 解释器（见 CLAUDE.md §2 / memory env-macos-primary）。

---

## T1 · 新增 `_resolve_run_status()` 纯函数 + 单测

- **依赖序**：1（无依赖，最先做）
- **可并行**：是（独立纯函数，不碰其他文件）
- **验收点**：7 个 status 值映射正确（degraded→degraded / error→failed / timeout→failed / skipped→success / ok→success / 无字段→success / due→success）
- **步骤**：
  1. `backend/scheduler/executors/__init__.py` 顶部（logger 定义后）加 `_DEGRADED_STATUSES` frozenset + `_resolve_run_status(result)` 函数（代码见 plan §5.1）
  2. `backend/tests/test_task_executor.py` 新增 `class TestResolveRunStatus`，7 用例：
     - `degraded` → `"degraded"`；`partial` → `"degraded"`；`source_fail` → `"degraded"`
     - `"error"` / `"error: boom"` / `"timeout"` → `"failed"`
     - `"ok"` / `"due"` / `"skipped"` / `"not_due"` / `"nothing_to_settle"` / `"no_dir"` → `"success"`
     - `{}`（无 status）→ `"success"`；`{"sync": True}` → `"success"`；非 dict → `"success"`
- **测试命令**：
  ```bash
  cd backend && .venv/bin/python -m pytest tests/test_task_executor.py::TestResolveRunStatus -q
  ```
- **预期**：全绿（先写测试会 RED——函数还没加；加函数后 GREEN）

---

## T2 · execute() / execute_async() 接线 `_resolve_run_status`

- **依赖序**：2（依赖 T1 的函数已存在）
- **可并行**：否（与 T3 同文件 `__init__.py`，须串行）
- **验收点**：A1（degraded→run.status degraded）+ A2（无字段→success）+ A3（skipped→success）+ A4（error→failed）
- **步骤**：
  1. `execute()`（line 76-84）：`run.status = "success"` → `run.status = _resolve_run_status(result)`；`update_task_status(..., "success", ...)` → `update_task_status(..., run.status, ...)`
  2. `execute()` 通知逻辑（line 82-84）重构：success→notify_on_success；degraded/failed→notify_on_failure（代码见 plan §5.2）
  3. `execute_async()`（line 133-145）同构改动
  4. except 块不动（异常 = failed + notify_on_failure，已有）
- **测试命令**：
  ```bash
  cd backend && .venv/bin/python -m pytest tests/test_task_executor.py::TestAddRunNoDuplicate -q
  ```
- **预期**：现有 success/failure 用例全绿（backward-compat：无 status 字段 → success）

---

## T3 · `_send_notification()` 三分支文案

- **依赖序**：3（依赖 T1 定义 status 值；与 T2 同文件须 T2 后）
- **可并行**：否（同 `__init__.py`）
- **验收点**：A6（degraded 通知文案「降级」非「失败」）
- **步骤**：
  1. `__init__.py:172` `status_text = "成功" if status == "success" else "失败"` → `status_text = {"success": "成功", "degraded": "降级", "failed": "失败"}.get(status, "未知")`
- **测试命令**：
  ```bash
  cd backend && .venv/bin/python -m pytest tests/test_task_executor.py -k "notify or degraded" -q
  ```
- **预期**：degraded run + notify_on_failure=True → 通知被调且文案含「降级」

---

## T4 · `_compute_today_status()` 加 degraded 分支

- **依赖序**：4（依赖 T1 定义 "degraded" 值；不同文件可与 T2/T3 并行）
- **可并行**：是（`scheduled_tasks.py` ≠ `__init__.py`）
- **验收点**：A5（degraded last_run_status + 今日 → today_status="degraded"）
- **步骤**：
  1. `routers/scheduled_tasks.py:42-43` 之间插入 `if last_run_date == today_bj and status == "degraded": return "degraded"`
  2. docstring line 21 返回值补 `degraded`
- **测试命令**：
  ```bash
  cd backend && .venv/bin/python -m pytest tests/test_task_executor.py -k "today_status" -q
  ```
- **预期**：degraded + 今日 → "degraded"（非 done/pending/error）

---

## T5 · 新增 degraded / backward-compat / skipped / error-from-dict 集成测试

- **依赖序**：5（依赖 T1-T4 实现完成）
- **可并行**：否（测的是 T2-T4 的行为）
- **验收点**：A1-A6 全覆盖
- **步骤**：`test_task_executor.py` 新增用例（代码见 spec §8）：
  1. `test_degraded_result_marks_run_degraded`（A1）
  2. `test_no_status_field_stays_success`（A2 backward-compat）
  3. `test_skipped_not_misclassified`（A3 不误杀）
  4. `test_error_from_dict_maps_failed` + `test_timeout_maps_failed`（A4）
  5. `test_degraded_triggers_notify_on_failure`（A6）
  6. `test_today_status_degraded`（A5，测 `_compute_today_status`）
- **测试命令**：
  ```bash
  cd backend && .venv/bin/python -m pytest tests/test_task_executor.py -q
  ```
- **预期**：全绿（新增 + 现有用例不回归）

---

## T6 · 前端 today_status 联合类型 + STATUS_STYLES + ETA 三元（Option B）

- **依赖序**：6（依赖 T4 定义 "degraded" today_status 值；与后端可并行）
- **可并行**：是（前端 2 文件 ≠ 后端文件）
- **验收点**：A8（tsc --noEmit 零错误）
- **步骤**：
  1. `frontend/src/lib/query/scheduledTasks.ts:13` 联合类型加 `"degraded"`：`today_status: "done" | "error" | "running" | "pending" | "degraded"`
  2. `frontend/src/components/workflow/TaskStatusCard.tsx:25-44` STATUS_STYLES 加 degraded entry（amber hsl(38 92% 50%)，label "降级"）
  3. `TaskStatusCard.tsx:199-205` ETA 三元补 degraded 分支：`... : t.today_status === "degraded" ? "降级" : "错误"`
- **测试命令**：
  ```bash
  cd frontend && npx tsc --noEmit
  ```
- **预期**：零错误（Record key 全覆盖联合类型）

---

## T7 · 全量回归 + tsc 终验

- **依赖序**：7（依赖 T1-T6 全完成）
- **可并行**：否
- **验收点**：A7（不回归）+ A8（tsc 零错误）
- **步骤**：
  1. 后端全量（deselect 3 flaky）：
     ```bash
     cd backend && .venv/bin/python -m pytest -m "not live" -q \
       --deselect tests/test_newsradar.py::test_fetch_global_intel_wm_import_fails \
       --deselect tests/test_s032_refresh_loop.py \
       --deselect tests/test_s040_backfill.py
     ```
  2. 前端 tsc：`cd frontend && npx tsc --noEmit`
  3. 逐条核对 spec §6 验收标准 A1-A8
- **预期**：后端全绿（0 failed）+ tsc 零错误 + A1-A8 全过

---

## 完成后（spec 归档）

- spec 顶部状态行改「已实现」+ 日期
- commit message：`fix(S177): execute()/execute_async() 读 result status——degraded 不再静默吞 success（backlog M1）`
- commit 前 `git branch --show-current` 确认分支（并发会话防误 commit）