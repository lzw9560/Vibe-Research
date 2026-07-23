# -*- coding: utf-8 -*-
"""情绪温度指数（STI）引擎 —— 兼容 facade（实际实现已拆分到 data/service/models）。"""

from __future__ import annotations

import threading
from limitup_sti.models import (
    STIPhase,
    STIDimension,
    STIResult,
    DISCLAIMER,
    STI_WEIGHTS,
    STI_DIRECTIONS,
    TOTAL_WEIGHT,
    PHASE_EXPLANATIONS,
    percentile_rank,
    _safe_float,
    _ema_3day,
)
from limitup_sti.service import STIEngine, get_sti_engine

# 兼容旧接口的模块级变量
_sti_lock = threading.Lock()
_sti_scores: list[float] = []

__all__ = [
    "STIEngine",
    "get_sti_engine",
    "STIPhase",
    "STIDimension",
    "STIResult",
    "DISCLAIMER",
    "STI_WEIGHTS",
    "STI_DIRECTIONS",
    "TOTAL_WEIGHT",
    "PHASE_EXPLANATIONS",
    "percentile_rank",
    "_safe_float",
    "_ema_3day",
    "_sti_lock",
    "_sti_scores",
]
