# S248 plan · depends_on 门控宽限重试

## 技术方案（_should_run 6 分支）

1. cron_match 通过 + 无 depends_on → True（不变）
2. cron_match 通过 + dep 满足 → True（不变，不进 _pending_retry）
3. cron_match 通过 + dep 未满足 → 加入 _pending_retry（retry_deadline = now + max_dep_timeout + 300）→ False
4. cron_match 不通过 + 在 _pending_retry 窗口内 + dep 满足 → True（补 fire）+ 清 _pending_retry
5. cron_match 不通过 + 在 _pending_retry 窗口内 + dep 未满足 → False（继续等）
6. cron_match 不通过 + _pending_retry 窗口过期（或无 _pending_retry）→ 清 _pending_retry → False

## 数据结构

`_pending_retry: Dict[int, Tuple[datetime, str]]`（task_id → (retry_deadline, depends_on_str)）。
- `_add_pending_retry(task, now)`：窗口 = max(_TASK_TIMEOUTS.get(dep, 300) for dep) + 300
- `_check_pending_retry(task, now)`：窗口内 dep 满足则 True + 清，过期则清 + False
- `_deps_satisfied(depends_on_str)`：复用 `_manager.dependency_satisfied`（今日 status IN success/degraded）
- `_run_task` 完成后 `_pending_retry.pop(task.id, None)`（防已 fire 残留）

## 取舍

- **窗口 = max_dep_timeout + 300**（自适应上游 timeout，kline_refresh 10800s → 窗口 11100s=185min）覆盖最坏 overrun + buffer
- **不改 cron_match**（保持精确分钟）——重试逻辑在 _should_run 层，blast radius 小
- **poll-based 宽限重试**（非事件驱动）——不改 executor 通知机制，最小改动

## 不选

- 事件驱动补触发（上游完成时通知下游）——需改 executor + 任务图，大重构
- 加大 cron 偏移（candidate_funnel 17:25 → 18:30？）——无法覆盖 70 分钟 overrun，且打乱盘后时序
- depends_on 改"running 也算满足"——破坏 R5 门控语义（防下游吃陈旧数据），治标不治本
