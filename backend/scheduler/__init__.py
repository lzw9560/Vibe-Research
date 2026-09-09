# -*- coding: utf-8 -*-
"""scheduler 包入口——定时任务调度系统。

子模块：
- models: dataclass（ScheduledTask / TaskRun）
- db: SQLite 持久化（_DB_PATH / ScheduledTaskManager / _manager）
- snapshots: 回测快照存取
- notifications: 通知内容构建 + generate_daily_summary
- cron: cron 表达式匹配
- seed: 默认任务 seed（_ensure_seed_tasks）
- cron_runner: CronScheduler 调度器
- executors: TaskExecutor 薄分发 + 8 域 executor 函数
"""
from __future__ import annotations

from scheduler.models import ScheduledTask, TaskRun
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
from scheduler.snapshots import _save_snapshot, get_backtest_snapshots
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
from scheduler.cron import (
    _CRON_FIELD_BOUNDS,
    _cron_token_match,
    _cron_field_match,
    cron_match,
)
from scheduler.cron_runner import (
    _TICK_INTERVAL,
    CronScheduler,
    _scheduler,
    get_scheduler,
    start_scheduler,
    stop_scheduler,
)
from scheduler.seed import _ensure_seed_tasks
from scheduler.executors import TaskExecutor

__all__ = [
    # models
    "ScheduledTask", "TaskRun",
    # db
    "_DB_PATH", "_get_connection", "_ensure_tables", "ScheduledTaskManager", "_manager",
    "_TASK_TIMEOUTS", "_DEFAULT_TASK_TIMEOUT", "_REAPER_STALE_SECONDS",
    "_SEAL_COLLECT_SUBPROCESS_TIMEOUT", "_task_timeout",
    # snapshots
    "_save_snapshot", "get_backtest_snapshots",
    # notifications
    "_compute_dual_confirmation", "_compute_strategy_map",
    "_build_premarket_notification_content", "_S101_DISCLAIMER",
    "_load_final_cards", "_fetch_quotes", "_send_notify", "_fmt_pct",
    "_check_premarket_kill_switch", "_prepend_kill_switch_warning",
    "_build_auction_notify_content", "_build_open_notify_content",
    "_compute_t1_returns", "_bar_close", "_build_t1_review_content",
    "generate_daily_summary",
    # cron
    "_CRON_FIELD_BOUNDS", "_cron_token_match", "_cron_field_match", "cron_match",
    # cron_runner
    "_TICK_INTERVAL", "CronScheduler", "_scheduler", "get_scheduler",
    "start_scheduler", "stop_scheduler",
    # seed
    "_ensure_seed_tasks",
    # executors
    "TaskExecutor",
]
