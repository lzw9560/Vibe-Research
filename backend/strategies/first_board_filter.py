# -*- coding: utf-8 -*-
"""first_board_filter.py —— re-export 兼容层（thin shim）。

原 1702 行 god-module 已拆为 ``backend/strategies/first_board/`` 包（6 子模块）。
本文件 re-export 全部公共名，保证 ``import strategies.first_board_filter`` /
``from strategies.first_board_filter import X`` 的调用方零改可用。

注：``em_zt_topic_pool`` / ``concept_blocks`` / ``_emotion`` 是 universe.py 顶部
import 的外部函数，测试 monkeypatch ``strategies.first_board_filter.em_zt_topic_pool``
经 shim 能 patch 到 shim 属性，但 scoring/exclusions 等子模块内部调用的是
``universe.em_zt_topic_pool``（universe 模块自身的 global）——shim 上的 patch
传不过去。故测试 monkeypatch 须指 ``strategies.first_board.universe.em_zt_topic_pool``
等新模块路径才生效（见 spec §4.5）。
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
    "MARKET_PHASE_WEIGHTS", "em_zt_topic_pool", "concept_blocks", "_emotion",
    "_logger",
    # data_extract
    "extract_chip_structure", "_get_kline_cache", "extract_sector",
    "_HS300_PCT_CACHE", "_KLINE_CACHE", "_KLINE_CACHE_MTIME",
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
    "_SCORES_DIR", "_SCORES_DIR_LEGACY", "ROOT",
]
