# -*- coding: utf-8 -*-
"""涨停基因选股器 —— 兼容 facade（实际实现已拆分到 data/service/models）。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime

from limitup_screener.models import (
    GeneScore,
    ScreenerResult,
    BacktestPoint,
    DISCLAIMER,
    compute_gene_score,
    wilson_lower_bound,
    LOOKBACK_DAYS,
    GENE_QUALIFY_THRESHOLD,
    GENE_HIGH_THRESHOLD,
)
from limitup_screener.service import (
    get_screener_result,
    precompute_daily_async,
    precompute_daily,
    backfill_async,
    backfill,
    _resolve_date,
    _fetch_zt_pool,
    _collect_zt_history_batch,
    _compute_and_cache_async,
    _compute_and_cache,
)
from limitup_screener.models import compute_factors as _compute_factors
from limitup_screener.models import calc_total_score as _calc_total_score

_BEIJING_TZ = datetime.now().astimezone().tzinfo
BEIJING_TZ = _BEIJING_TZ
_logger = logging.getLogger(__name__)

# 模块导入时自动运行迁移（幂等）
try:
    from limitup_screener.data import run_migrations
    run_migrations()
except Exception as e:
    _logger.warning("[limitup_screener] 自动迁移失败（不影响主流程）: %s", e)

# 兼容旧接口
__all__ = [
    "get_screener_result",
    "precompute_daily_async",
    "precompute_daily",
    "backfill_async",
    "backfill",
    "compute_gene_score",
    "wilson_lower_bound",
    "GeneScore",
    "ScreenerResult",
    "BacktestPoint",
    "DISCLAIMER",
    "LOOKBACK_DAYS",
    "GENE_QUALIFY_THRESHOLD",
    "GENE_HIGH_THRESHOLD",
    "_resolve_date",
    "_fetch_zt_pool",
    "_collect_zt_history_batch",
    "_compute_factors",
    "_calc_total_score",
    "_compute_and_cache_async",
    "_compute_and_cache",
    "BEIJING_TZ",
]
