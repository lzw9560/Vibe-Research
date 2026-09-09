# -*- coding: utf-8 -*-
"""funnel 包入口——策略漏斗注册表 + 天气 + 评分 + 聚合 + 质量。

子模块：
- weather: 天气-策略推荐
- registry: STRATEGY_REGISTRY + 权重加载
- scoring: compute_strategy_score
- aggregation: _aggregate_strategy_funnels + score_candidates
- quality: check_quality_standards + passes_hard_standards
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

__all__ = [
    # weather
    "WEATHER_RECOMMENDATION", "WEATHER_STRATEGY_MAP", "FALLBACK_STRATEGIES",
    "get_weather_recommendation", "get_strategies_for_weather",
    # registry
    "STRATEGY_REGISTRY", "STRATEGY_FUNNEL_REGISTRY", "STRATEGIES_BY_FUNNEL_TYPE",
    "StrategyFunnelConfig", "get_strategy_config",
    "_DATA_DIR", "_WEIGHTS_PATH", "_WEIGHTS_CACHE",
    "_load_weights", "_get_weight_set",
    # scoring
    "compute_strategy_score", "_cand_to_gene", "_build_market_scan_factors",
    # aggregation
    "_aggregate_strategy_funnels", "score_candidates",
    # quality
    "check_quality_standards", "passes_hard_standards",
]
