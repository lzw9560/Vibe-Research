# -*- coding: utf-8 -*-
"""龙虎榜席位智能引擎 —— 兼容 facade（实际实现已拆分到 data/service/models）。"""

from __future__ import annotations

from seat_engine.models import (
    SeatProfile,
    ConsensusSignal,
    SEAT_DISCLAIMER,
    SEAT_LOOKBACK_DAYS,
    SEAT_QUANT_THRESHOLD,
    SEAT_ACTIVE_MIN,
    SEAT_LARGE_POS,
    SEAT_SMALL_POS,
)
from seat_engine.service import SeatEngine, get_engine, BEIJING_TZ

__all__ = [
    "SeatEngine",
    "get_engine",
    "BEIJING_TZ",
    "SeatProfile",
    "ConsensusSignal",
    "SEAT_DISCLAIMER",
    "SEAT_LOOKBACK_DAYS",
    "SEAT_QUANT_THRESHOLD",
    "SEAT_ACTIVE_MIN",
    "SEAT_LARGE_POS",
    "SEAT_SMALL_POS",
]
