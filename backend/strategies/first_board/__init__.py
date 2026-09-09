# -*- coding: utf-8 -*-
"""first_board 包入口——首板过滤 + 三层剔除 + 9 维度评分。

子模块：
- universe: 涨停池/首板过滤/市场档位判定
- data_extract: 筹码结构/板块/历史K线缓存
- exclusions: 三层剔除（封板质量/筹码/市场环境）
- scoring: 15 个 score_dim* + score_candidate + rank_candidates
- pipeline: run_first_board_filter / attach_first_board_analysis 主入口
- persistence: 评分落盘/读盘/日期列表
"""
from __future__ import annotations

from strategies.first_board.universe import (
    fetch_zt_pool,
    filter_first_board,
    _market_phase,
    _to_float,
    _fbt_to_hhmm,
    PHASE_TO_CAP_TIER,
    EXCLUDE_THRESHOLDS,
    MARKET_PHASE_WEIGHTS,
    em_zt_topic_pool,
    concept_blocks,
    _emotion,
    _logger,
)
from strategies.first_board.data_extract import (
    extract_chip_structure,
    _get_kline_cache,
    extract_sector,
    _HS300_PCT_CACHE,
    _KLINE_CACHE,
    _KLINE_CACHE_MTIME,
)
from strategies.first_board.persistence import (
    save_scores,
    load_scores,
    list_score_dates,
    _SCORES_DIR,
    _SCORES_DIR_LEGACY,
    ROOT,
)
from strategies.first_board.exclusions import (
    exclude_layer1_seal_quality,
    exclude_layer2_chip_structure,
    exclude_layer3_market_env,
    _sector_zt_count,
    _market_drop_pct,
)
from strategies.first_board.scoring import (
    score_dim1_sector,
    score_dim2_hot_money,
    score_dim3_seal_strength,
    score_dim4_chip,
    score_dim5_auction,
    score_dim6_northbound,
    score_dim7_institution,
    score_dim8_theme,
    score_dim9_event,
    score_dim_seal_time,
    score_dim_sector_link,
    score_dim_market_cap,
    score_dim_seal_ratio,
    score_dim_turnover,
)
from strategies.first_board.pipeline import (
    _SCORE_DIMS,
    score_candidate,
    rank_candidates,
    run_first_board_filter,
    attach_first_board_analysis,
)
from strategies.first_board.persistence import (
    save_scores,
    load_scores,
    list_score_dates,
    _SCORES_DIR,
    _SCORES_DIR_LEGACY,
    ROOT,
)

__all__ = [
    # universe
    "fetch_zt_pool", "filter_first_board", "_market_phase", "_to_float",
    "_fbt_to_hhmm", "PHASE_TO_CAP_TIER", "EXCLUDE_THRESHOLDS",
    "MARKET_PHASE_WEIGHTS", "_HS300_PCT_CACHE", "_KLINE_CACHE",
    "_KLINE_CACHE_MTIME", "em_zt_topic_pool", "concept_blocks", "_emotion",
    "ROOT", "_logger",
    # data_extract
    "extract_chip_structure", "_get_kline_cache", "extract_sector",
    # exclusions
    "exclude_layer1_seal_quality", "exclude_layer2_chip_structure",
    "exclude_layer3_market_env", "_sector_zt_count", "_market_drop_pct",
    # scoring
    "score_dim1_sector", "score_dim2_hot_money", "score_dim3_seal_strength",
    "score_dim4_chip", "score_dim5_auction", "score_dim6_northbound",
    "score_dim7_institution", "score_dim8_theme", "score_dim9_event",
    "score_dim_seal_time", "score_dim_sector_link", "score_dim_market_cap",
    "score_dim_seal_ratio", "score_dim_turnover", "_SCORE_DIMS",
    "score_candidate", "rank_candidates",
    # pipeline
    "run_first_board_filter", "attach_first_board_analysis",
    # persistence
    "save_scores", "load_scores", "list_score_dates",
    "_SCORES_DIR", "_SCORES_DIR_LEGACY",
]
