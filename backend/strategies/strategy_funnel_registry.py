# -*- coding: utf-8 -*-
"""strategy_funnel_registry.py —— re-export 兼容层（thin shim）。

原 940 行 god-module 已拆为 ``backend/strategies/funnel/`` 包（5 子模块）。
本文件 re-export 全部公共名，保证 ``import strategies.strategy_funnel_registry`` /
``from strategies.strategy_funnel_registry import X`` 的调用方零改可用。
"""
from __future__ import annotations

from strategies.funnel.weather import (
    WEATHER_RECOMMENDATION,
    WEATHER_STRATEGY_MAP,
    FALLBACK_STRATEGIES,
    get_weather_recommendation,
    get_strategies_for_weather,
)
from strategies.funnel.registry import (
    STRATEGY_REGISTRY,
    STRATEGY_FUNNEL_REGISTRY,
    STRATEGIES_BY_FUNNEL_TYPE,
    StrategyFunnelConfig,
    get_strategy_config,
    _DATA_DIR,
    _WEIGHTS_PATH,
    _WEIGHTS_CACHE,
    _load_weights,
    _get_weight_set,
)
from strategies.funnel.scoring import (
    compute_strategy_score,
    _cand_to_gene,
    _build_market_scan_factors,
)
from strategies.funnel.aggregation import (
    _aggregate_strategy_funnels,
    score_candidates,
)
from strategies.funnel.quality import (
    check_quality_standards,
    passes_hard_standards,
)
