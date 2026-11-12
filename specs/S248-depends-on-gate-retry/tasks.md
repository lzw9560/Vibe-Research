# S248 tasks

## TDD RED（先写测试）
- [ ] 写 `backend/tests/test_cron_dep_retry.py`
  - [ ] test_dep_running_no_fire_but_pending（cron 命中 + dep 未满足 → False + 加入 _pending_retry）
  - [ ] test_dep_satisfied_retries_fire_within_window（cron 不命中 + 窗口内 dep 满足 → True + 清 _pending_retry）
  - [ ] test_retry_window_expire_no_fire（cron 不命中 + 窗口过期 → False + 清 _pending_retry）
  - [ ] test_no_dep_unaffected（无 depends_on → 现有 cron_match 行为不变）
  - [ ] test_dep_satisfied_no_pending（cron 命中 + dep 满足 → True + 不进 _pending_retry）
  - [ ] test_run_task_clears_pending（_run_task 完成后清 _pending_retry）

## GREEN（实现）
- [ ] `backend/scheduler/cron_runner.py`
  - [ ] import `timedelta` + `Dict, Tuple`
  - [ ] `__init__` 加 `self._pending_retry: Dict[int, Tuple[datetime, str]] = {}`
  - [ ] `_should_run` 改造（6 分支）
  - [ ] `_check_pending_retry` + `_add_pending_retry` + `_deps_satisfied` helper
  - [ ] `_run_task` 完成后 `_pending_retry.pop(task.id, None)`

## 验证
- [ ] `pytest -k "scheduler or cron or depends" -m "not live"` 全绿
- [ ] 现有 test_cron_should_run 绿（无回归）
- [ ] commit `feat(S248): depends_on 门控宽限重试（覆盖上游 overrun 致当日静默断链）`
