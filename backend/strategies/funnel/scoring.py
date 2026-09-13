# -*- coding: utf-8 -*-
"""策略分计算——compute_strategy_score / _cand_to_gene / _build_market_scan_factors。"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

from strategies.funnel.registry import _get_weight_set

logger = logging.getLogger(__name__)


def compute_strategy_score(
    factors: dict[str, float],
    weight_set: str,
) -> tuple[float, dict[str, float]]:
    """按指定权重集计算策略分。

    factors: {factor_name: value}（来自 gene_scores，中文键名）
    weight_set: "limitup" / "non_limitup" / "storm_reversal"
    返回 (score, breakdown)。

    spec §4.1 涨停类：
        score = Σ(factor_value [× reverse ? (100-x) : x] × weight)
    反向因子（premium/freq）用 (100-value) 反转。

    权重加载失败 → 等权兜底（标注 fallback）。

    因子名映射：权重文件用英文键名（factor_seal_rate 等），
    gene_scores 用中文键名（封板率 等），需映射查值。
    """
    # 英文权重键 → 中文 gene_scores 键
    _FACTOR_NAME_MAP = {
        "factor_seal_rate": "封板率",
        "factor_red_rate": "红盘率",
        "factor_rebound_rate": "炸板后溢价",
        "factor_freq_score": "涨停频次",
        "factor_premium": "次日溢价率",
        "relative_strength": "相对强度",
        "ma_bullish": "均线多头",
        "volume_signal": "量能信号",
        "sector_strength": "板块强度",
    }
    ws = _get_weight_set(weight_set)
    weights = ws.get("weights", {})
    if not weights:
        # 等权兜底：所有因子等权 1/N
        if factors:
            n = len(factors)
            score = sum(factors.values()) / n
            breakdown = {k: v / n for k, v in factors.items()}
        else:
            score = 0.0
            breakdown = {}
        return round(score, 4), breakdown

    # S151 R2 + S161 R8：评价层降权注入——gene-based 因子（封板率/红盘率/炸板后溢价/涨停频次/次日溢价率）
    # proxy 映射 gene composite rho≈0 → 推断无方向性 → lift_to_multiplier 得降权（days<60 → provisional ×0.5）
    # 非 gene 因子（相对强度/均线多头/量能信号/板块强度）×1.0
    _GENE_BASED_FACTORS = {
        "factor_seal_rate", "factor_red_rate", "factor_rebound_rate",
        "factor_freq_score", "factor_premium",
    }
    try:
        from candidate_funnel.evaluation import lift_to_multiplier
        from candidate_funnel.lift_override import get_effective_dimension
        _gene_dim = get_effective_dimension("gene_score")
        gene_multiplier = lift_to_multiplier(
            _gene_dim.lift, _gene_dim.n, days_robust=_gene_dim.days_robust,
        )[1]  # §44v2 P0：override 优先（revalidation 写回生效），fallback frozen days=38<60 → ×0.5
    except Exception:  # noqa: BLE001 — import 失败降级默认（gene rho≈0, days<60 → ×0.5 provisional）
        gene_multiplier = 0.5
    total = 0.0
    breakdown = {}
    for factor_name, w_info in weights.items():
        w = w_info.get("weight", 0)
        reverse = w_info.get("reverse", False)
        # 英文权重键 → 中文 gene_scores 键映射
        cn_name = _FACTOR_NAME_MAP.get(factor_name, factor_name)
        val = factors.get(cn_name, 0)
        if reverse:
            val = 100 - val
        # S151 R2 + S161 R8：gene-based 因子经 lift_to_multiplier 降权，非 gene 因子 ×1.0
        multiplier = gene_multiplier if factor_name in _GENE_BASED_FACTORS else 1.0
        contribution = val * w * multiplier
        total += contribution
        breakdown[factor_name] = round(contribution, 4)

    return round(total, 4), breakdown


def _cand_to_gene(cand: dict):
    """dict 候选 → GeneScore 适配（grill Q6：dispatch_match 需要 GeneScore）。

    字段映射经 limitup_screener/models.py GeneScore 定义核实。
    factors 优先取 cand["factors"]；total_score/zt_count_250d 同时回退到 factors 内同名键。
    wilson_adjusted/qualify/high_gene/last_zt_dates 用安全默认值——
    dispatch_match 只读 total_score/factors/zt_count_250d/code，不读这几项。
    """
    from limitup_screener.models import GeneScore

    factors = cand.get("factors", {}) or {}
    total = cand.get("total_score", factors.get("total_score", 0)) or 0
    zt_count = cand.get("zt_count_250d", factors.get("zt_count_250d", 0)) or 0
    return GeneScore(
        code=cand.get("code", ""),
        name=cand.get("name", ""),
        total_score=float(total),
        factors=factors,
        wilson_adjusted=float(total),
        qualify=total >= 50,
        high_gene=total >= 60,
        last_zt_dates=[],
        zt_count_250d=int(zt_count),
        data_source=cand.get("data_source", "eastmoney_live"),
        date=cand.get("date", ""),
    )


def _build_market_scan_factors(pattern, cand: dict, strat_code: str) -> dict:
    """S094 audit fix: market_scan 候选从 PatternScan + strat_code 建 factors dict（4 因子 0-100）。

    run_non_limitup_funnel（R27/T9-full）产 pattern（PatternScan）不产 factors dict →
    score_candidates 拿 cand["factors"]={} 空 → compute_strategy_score 全 0（非涨停侧 scoring 废）。
    此处补建：相对强度/均线多头/板块强度（candidate-level，compute_*_score）+
    量能信号（per-strategy，compute_volume_signal_score(pattern, strat_code)，R4 下沉 match 层算）。
    pattern None → 各因子降级 50（不臆造 0）。
    """
    from strategies.non_limitup_funnel import (  # 懒 import 防 circular
        compute_relative_strength_score, compute_ma_bullish_score,
        compute_volume_signal_score, compute_sector_strength_score,
    )
    sector_rank = cand.get("sector_rank")
    return {
        "相对强度": compute_relative_strength_score(pattern) if pattern is not None else 50.0,
        "均线多头": compute_ma_bullish_score(pattern) if pattern is not None else 50.0,
        "量能信号": compute_volume_signal_score(pattern, strat_code) if pattern is not None else 50.0,
        "板块强度": compute_sector_strength_score(sector_rank),
    }
