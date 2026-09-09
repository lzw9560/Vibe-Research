# -*- coding: utf-8 -*-
"""scheduled_tasks.py —— re-export 兼容层（thin shim）。

原 3076 行 god-module 已拆为 ``backend/scheduler/`` 包（17 文件）。
本文件 re-export 全部公共名，保证 ``import scheduled_tasks`` /
``from scheduled_tasks import X`` 的调用方零改可用。

注：``_DB_PATH`` / ``_manager`` 等模块级名 re-export 的是引用——
``scheduled_tasks._DB_PATH`` 与 ``scheduler.db._DB_PATH`` 是同一个对象，
但 ``_get_connection`` 读的是 ``scheduler.db`` 模块自身的 global，故
conftest monkeypatch 须指 ``scheduler.db._DB_PATH``（而非本 shim）才生效。
"""
from __future__ import annotations

# 核心数据结构
from scheduler.models import ScheduledTask, TaskRun

# DB 层
from scheduler.db import (
    _DB_PATH,
    _get_connection,
    _ensure_tables,
    ScheduledTaskManager,
    _manager,
    _TASK_TIMEOUTS,
    _DEFAULT_TASK_TIMEOUT,
    _REAPER_STALE_SECONDS,
    _SEAL_COLLECT_SUBPROCESS_TIMEOUT,
    _task_timeout,
)

# 快照
from scheduler.snapshots import _save_snapshot, get_backtest_snapshots

# 通知内容构建 + generate_daily_summary
from scheduler.notifications import (
    _compute_dual_confirmation,
    _compute_strategy_map,
    _build_premarket_notification_content,
    _S101_DISCLAIMER,
    _load_final_cards,
    _fetch_quotes,
    _send_notify,
    _fmt_pct,
    _check_premarket_kill_switch,
    _prepend_kill_switch_warning,
    _build_auction_notify_content,
    _build_open_notify_content,
    _compute_t1_returns,
    _bar_close,
    _build_t1_review_content,
    generate_daily_summary,
)

# Cron 匹配
from scheduler.cron import (
    _CRON_FIELD_BOUNDS,
    _cron_token_match,
    _cron_field_match,
    cron_match,
)

# 调度器
from scheduler.cron_runner import (
    _TICK_INTERVAL,
    CronScheduler,
    _scheduler,
    get_scheduler,
    start_scheduler,
    stop_scheduler,
)

# 默认任务 seed
from scheduler.seed import _ensure_seed_tasks

# TaskExecutor
from scheduler.executors import TaskExecutor


# ============================================================================
# 模块级 executor 包装（向后兼容：旧测试/调用方按 st._execute_* 访问）
# ============================================================================
# S011-A R2 重构将 executor 方法从模块级函数迁入 TaskExecutor 类，部分旧测试与
# 调用方仍按 st._execute_xxx(ctx, payload) 访问（ctx 占位，executor 内部不用）。
# 此处提供向后兼容包装：转调默认 TaskExecutor 实例的对应方法。
# executor 方法不自持久状态（DB 操作走模块级 _manager），每次 new 实例无副作用。
def _execute_s066_validation_checkpoint(ctx, payload):
    """§44 60 天复验检查点（模块级兼容包装；ctx 占位忽略）。"""
    return TaskExecutor()._execute_s066_validation_checkpoint(payload)


def _execute_evaluation_backtest(ctx, payload):
    """S151 R3 评价层回溯检查点（模块级兼容包装；ctx 占位忽略）。"""
    return TaskExecutor()._execute_evaluation_backtest(payload)


def _execute_forward_test_daily(ctx, payload):
    """S069 R1 每日 forward_test picks 记录（模块级兼容包装；ctx 占位忽略）。"""
    return TaskExecutor()._execute_forward_test_daily(payload)


def _execute_forward_test_t1_settle(ctx, payload):
    """S069 R2 T+1 收益回填（模块级兼容包装；ctx 占位忽略）。"""
    return TaskExecutor()._execute_forward_test_t1_settle(payload)
