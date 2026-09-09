# -*- coding: utf-8 -*-
"""定时任务数据结构。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class ScheduledTask:
    """定时任务定义。"""
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    task_type: str = ""
    cron_expr: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    notify_on_success: bool = False
    notify_on_failure: bool = True
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class TaskRun:
    """单次任务执行记录。"""
    id: Optional[int] = None
    task_id: int = 0
    status: str = "running"
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None
    result: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
