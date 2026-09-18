# S177 plan.md — 技术方案

## 设计取舍

### D1: status 映射放模块级纯函数（非 inline / 非配置文件）

**选**：`scheduler/executors/__init__.py` 模块级 `_resolve_run_status(result) -> str` 纯函数。

**为何不选 inline**：execute() 和 execute_async() 两处都要同一逻辑，inline = DRY 违反 + 漂移风险（survey 明确两处同病）。
**为何不选配置文件/枚举类**：YAGNI——映射表 ~15 行、改动频率极低（新增 executor 才碰），拉一个 config/enum 类是过度工程。纯函数 + frozenset 常量足够，且可独立单测。

### D2: 三态 success/degraded/failed（非二态 success/failed）

**选**：`_resolve_run_status` 返回三值 `"success" | "degraded" | "failed"`。

**为何不选二态**（把 degraded 并入 failed）：degraded ≠ 全失败——kline_refresh baostock 未装时仍跑了、只是没拉到新 bar；monthly_vacuum 7 库 VACUUM 了 5 库（partial）。并进 failed = 红色「错误」，误导用户以为任务崩了。三态让「降级」有独立语义位（amber），诚实反映「跑了但有问题」。core-invariant「绝不静默吞错误」要求区分，不合并。

### D3: error 家族映射 failed（非 degraded）

**选**：`error`/`error: {e}` prefix + `timeout` → `failed`。

**权衡**：这些值是 executor 自己 catch 了异常、返 dict 而非 re-raise（executor 层吞错）。映射 degraded 还是 failed？
- 映射 degraded（amber）=「跑了但有异常」——但 `error: {e}` 语义是「核心功能失败」（limitup_precompute 没算出来），不是「部分成功」。
- 映射 failed（红）=「任务失败」——语义更准，且诚实揭示（当前这些被标 success 绿，是 bug 本身）。

**选 failed**：`error` 家族 = 核心功能失败 = failed。这会致当前标绿的任务变红（行为变更），但这是修 bug 的预期效果（停止说谎），非回归。spec §9 已记录此预期行为变更。

### D4: script_not_found 映射 degraded（非 failed）

**选**：`script_not_found` → degraded。

**权衡**：kg executor 找不到脚本（脚本路径配错/未部署）。这是配置问题非运行时崩溃。
- 映射 failed = 红色「错误」——但任务没崩，只是找不到目标。
- 映射 degraded = amber「降级」——提示「检查配置」，不惊吓。

**选 degraded**：配置缺失 ≠ 运行时失败，amber 更合适。此为可调点（plan 标注，若用户觉得该归 failed 一行改）。

### D5: degraded 触发 notify_on_failure（非 notify_on_success / 静默）

**选**：degraded → `if task.notify_on_failure: notify("degraded")`。

**为何不选 notify_on_success**：degraded 不是成功，notify_on_success 默认 False——走这条 = 默认不发通知 = 静默吞（正是修的 bug）。
**为何不选静默**：core-invariant「绝不静默吞掉错误」——degraded 是隐性故障，用户 opted into notify_on_failure（默认 True），应告知。
**为何不新增 notify_on_degraded 字段**：YAGNI——notify_on_failure 已覆盖「出问题就告警」语义，新增字段 = 过度工程 + 增加配置面。degraded 归 notify_on_failure 足够。

### D6: today_status 选 Option B 新增 amber degraded 态（非 A 复用 error 红）

**选 B**：_compute_today_status 加 `degraded → "degraded"` 分支 + 前端加 amber 样式槽。

**为何不选 A**（degraded → today_status="error" 复用红色）：A 零前端改但语义不准——degraded 任务今日「跑了但有问题」，标红色「错误」会让用户以为任务崩了（和 failed 混淆）。B 的 amber「降级」诚实区分「部分成功」与「全失败」。core-invariant 要求不静默吞，B 更诚实。前端改动机械（3 文件加 key/分支），非大工程。

**A 作为 fallback**：若用户求最小前端触碰，改 _compute_today_status 一行（degraded→"error"）即可降级为 A，前端零改。此 fork 不阻塞 backend 主体（execute 读 result status 这步无论 A/B 都做）。

## 模块拆分

### 新增：`_resolve_run_status(result: Any) -> str`（__init__.py 模块级）

```python
_DEGRADED_STATUSES = frozenset({
    "degraded", "partial", "source_fail", "no_emotion_data", "script_not_found",
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

**不改动 data_ops.py / limitup.py / intraday.py 等 executor**——它们已正确返 status dict，是受害方非病源。只改消费方（execute）。

### 改 execute()（__init__.py:66-98）

try 块 line 77 `run.status = "success"` → `run.status = _resolve_run_status(result)`；line 80 `update_task_status(..., "success", ...)` → 用 `run.status`。通知逻辑重构：
```python
# 原：if task.notify_on_success: self._send_notification(task, run, "success")
# 新：
if run.status == "success":
    if task.notify_on_success:
        self._send_notification(task, run, "success")
else:  # degraded 或 failed（来自 result dict，非异常）
    if task.notify_on_failure:
        self._send_notification(task, run, run.status)
```
except 块不变（异常 = failed + notify_on_failure）。

### 改 execute_async()（__init__.py:103-164）

同 execute()：line 137 → `_resolve_run_status(result)`；line 141 → `run.status`；通知同上重构。

### 改 _send_notification()（__init__.py:166-185）

line 172 `status_text = "成功" if status == "success" else "失败"` → 三分支：
```python
status_text = {"success": "成功", "degraded": "降级", "failed": "失败"}.get(status, "未知")
```

### 改 _compute_today_status()（scheduled_tasks.py:40-45）

line 42-43 之间插入：
```python
if last_run_date == today_bj and status == "degraded":
    return "degraded"
```

### 前端（Option B）

scheduledTasks.ts:13：联合类型加 `"degraded"`。
TaskStatusCard.tsx:25-44：STATUS_STYLES 加 degraded entry（amber hsl(38 92% 50%)）。lines 199-205 ETA 三元加 degraded 分支（`"降级"`）。

## 依赖序

```
T1 _resolve_run_status 纯函数（无依赖，可独立单测）
  ↓
T2 execute/execute_async 接线（依赖 T1）
T3 _send_notification 三分支（依赖 T1 定义的 status 值，可与 T2 同文件连续改）
T4 _compute_today_status degraded 分支（依赖 T1，不同文件可并行）
  ↓
T5 前端 today_status + STATUS_STYLES（依赖 T4 定义的 "degraded" 值，可与 T2-T4 并行）
  ↓
T6 新增测试（依赖 T1-T4 实现）
  ↓
T7 全量回归 + tsc
```

## 数据流

```
executor(payload)  →  result dict {"status": "degraded", ...}
       ↓
_resolve_run_status(result)  →  "degraded"
       ↓
execute(): run.status = "degraded"
           run.result = result（原 dict 保留，degraded 信号不再被埋）
           update_task_status(task.id, "degraded", started_at)  →  scheduled_tasks.last_run_status = "degraded"
           notify_on_failure=True → _send_notification(task, run, "degraded") → 文案「降级」
       ↓
GET /api/scheduled-tasks → _compute_today_status(task)
  last_run_status=="degraded" + last_run_at==今日 → today_status="degraded"
       ↓
前端 today_status="degraded" → STATUS_STYLES["degraded"] → amber 节点 + 「降级」徽章
```

## 备选不选记录

- **让 executor re-raise 而非返 dict**：范围太大（8 域文件 30+ executor 改返回契约），且 kline_refresh 的降级返回是设计意图（baostock 未装不崩）。不在本 spec 范围——本 spec 只修消费方（execute 读 status），不改生产方。未来若要统一 executor 返回契约另起 spec。
- **notify_on_degraded 新字段**：YAGNI，notify_on_failure 已覆盖告警语义。
- **TaskRun.status 加 Enum 约束**：models.py 改 dataclass 字段为 Enum 会破坏现有 `status="running"` 字面量赋值 + DB schema（status 列是 TEXT）。自由 str 直接加 "degraded" 值，零迁移成本。Enum 约束是未来 spec 的事。