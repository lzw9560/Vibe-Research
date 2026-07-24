# -*- coding: utf-8 -*-
"""通知分发结果数据结构 - 独立模块"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ChannelAttemptResult:
    """One static notification channel send attempt."""

    channel: str
    success: bool
    error_code: Optional[str] = None
    retryable: bool = False
    latency_ms: Optional[int] = None
    diagnostics: Optional[str] = None


@dataclass
class NotificationDispatchResult:
    """Structured result for notification dispatch diagnostics."""

    dispatched: bool
    success: bool
    status: str
    channel_results: List[ChannelAttemptResult] = field(default_factory=list)
    message: Optional[str] = None
