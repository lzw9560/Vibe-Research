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
from limitup_sti.service import STIEngine, get_sti_engine, _BEIJING_TZ

# 公开别名：routers/sti.py 等以 ``limitup_sti.BEIJING_TZ`` 引用（service 内定义为私有 _BEIJING_TZ）
BEIJING_TZ = _BEIJING_TZ

import logging
_logger = logging.getLogger(__name__)

# 模块导入时自动运行迁移（幂等）——镜像 limitup_screener/__init__.py；
# 否则 fresh DB（测试/新部署）未实例化 STIEngine 时不建 sti_timeline → /api/health "no such table"。
try:
    from limitup_sti.data import run_initial_migrations
    run_initial_migrations()
except Exception as e:
    _logger.warning("[limitup_sti] 自动迁移失败（不影响主流程）: %s", e)

# 兼容旧接口的模块级变量
_sti_lock = threading.Lock()
_sti_scores: list[float] = []

__all__ = [
    "STIEngine",
    "get_sti_engine",
    "BEIJING_TZ",
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
