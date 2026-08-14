# -*- coding: utf-8 -*-
"""S066 Phase 2 P2-3 非涨停类策略分 + 漏斗（低吸/反包/平台突破/龙头）。

spec §4.2/§4.3 非涨停类权重（等权起步，Phase 2 有数据后单独估参）：
    score = relative_strength × W1 + ma_bullish × W2 + volume_signal × W3 + sector_strength × W4
    W1 = W2 = W3 = W4 = 0.25

spec §3.1 非涨停类漏斗流程：
    热门板块 → 板块成分股 → 形态扫描 → 策略分排序 → 候选

与涨停类（strategy_funnel_registry）的关系：
- 涨停类用 gene_scores 五因子（已有数据）
- 非涨停类用 pattern_scan 形态指标（相对强度/均线多头/量比/板块强度）
- 两者共享天气硬开关 + 质量标准检查
- N字反击归入涨停类权重集（spec §4.4，已在 P1-1 处理）

spec §4.4 因子定义：
- relative_strength：个股 5 日涨幅 - 板块 5 日涨幅
- ma_bullish：MA5 > MA10 > MA20 = 1.0，否则按偏离度评分
- volume_signal：量比 > 2 = 1.0 / 资金净流入 = 1.0 / 成交额 > 15亿 = 1.0（按战法上下文选）
- sector_strength：板块涨幅排名分（top-5 = 1.0, top-20 = 0.5, 其他 = 0.2）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strategies.pattern_scan import (
    PatternScan,
    compute_relative_strength,
    check_ma_bullish,
    compute_ma5_proximity,
    compute_consolidation,
    compute_volume_breakout,
    compute_amount_yi,
)
from strategies.strategy_funnel_registry import (
    StrategyFunnelConfig,
    get_strategy_config,
    get_strategies_for_weather,
    compute_strategy_score,
    check_quality_standards,
    passes_hard_standards,
)


# 非涨停类因子权重（等权起步，spec §4.2）
NON_LIMITUP_WEIGHTS: dict[str, float] = {
    "relative_strength": 0.25,
    "ma_bullish": 0.25,
    "volume_signal": 0.25,
    "sector_strength": 0.25,
}


# ===========================================================================
# 非涨停类因子计算
# ===========================================================================

def compute_relative_strength_score(pattern: PatternScan) -> float:
    """相对强度因子（0-100 标准化）。

    relative_strength = 个股 5 日涨幅 - 板块 5 日涨幅
    正值越大越强 → 映射到 0-100
    """
    rs = pattern.relative_strength
    if rs is None:
        return 50.0  # 无数据 → 中性
    # 涨幅差 > 10% 满分，< -10% 零分
    score = 50 + rs * 5  # rs=0 → 50, rs=10 → 100, rs=-10 → 0
    return max(0.0, min(100.0, score))


def compute_ma_bullish_score(pattern: PatternScan) -> float:
    """均线多头因子。

    MA5 > MA10 > MA20 = 100 分
    否则按偏离度评分
    """
    if pattern.ma_bullish:
        return 100.0
    # 非多头排列 → 50 分起步（中性偏弱）
    return 50.0


def compute_volume_signal_score(pattern: PatternScan, strategy_code: str) -> float:
    """量能信号因子（按战法上下文选，spec §4.4）。

    低吸龙头：资金净流入 = 1.0（成交额作为代理）
    反包：成交额 > 15亿 = 1.0
    平台突破：量比 > 2 = 1.0
    龙头：换手 > 5% = 1.0（用成交额代理）
    """
    if strategy_code == "platform_breakout":
        # 量比突破
        if pattern.volume_breakout_ratio is not None and pattern.volume_breakout_ratio > 2:
            return 100.0
        elif pattern.volume_breakout_ratio is not None:
            return min(100.0, pattern.volume_breakout_ratio * 40)
        return 50.0
    elif strategy_code == "reverse_package":
        # 成交额 > 15亿
        if pattern.amount_yi is not None and pattern.amount_yi > 15:
            return 100.0
        elif pattern.amount_yi is not None:
            return min(100.0, pattern.amount_yi / 15 * 100)
        return 50.0
    elif strategy_code == "low_absorption":
        # 成交额作为资金流入代理
        if pattern.amount_yi is not None and pattern.amount_yi > 5:
            return 80.0
        return 50.0
    elif strategy_code == "dragon_head":
        # 换手 > 5%（用成交额代理）
        if pattern.amount_yi is not None and pattern.amount_yi > 10:
            return 100.0
        elif pattern.amount_yi is not None:
            return min(100.0, pattern.amount_yi / 10 * 100)
        return 50.0
    return 50.0


def compute_sector_strength_score(sector_rank: int | None) -> float:
    """板块强度因子（spec §4.4）。

    top-5 = 1.0 (100 分)
    top-20 = 0.5 (50 分)
    其他 = 0.2 (20 分)
    """
    if sector_rank is None:
        return 50.0  # 无排名 → 中性
    if sector_rank <= 5:
        return 100.0
    elif sector_rank <= 20:
        return 50.0
    else:
        return 20.0


# ===========================================================================
# 非涨停类策略分计算
# ===========================================================================

@dataclass(frozen=True)
class NonLimitupScore:
    """非涨停类策略分结果。"""
    code: str
    strategy_code: str
    strategy_name: str
    strategy_score: float
    score_breakdown: dict[str, float]
    pattern: PatternScan


def compute_non_limitup_score(
    code: str,
    pattern: PatternScan,
    strategy_code: str,
    sector_rank: int | None = None,
) -> NonLimitupScore:
    """非涨停类策略分计算（spec §4.2）。

    score = relative_strength × W1 + ma_bullish × W2 + volume_signal × W3 + sector_strength × W4
    W1 = W2 = W3 = W4 = 0.25（等权起步）
    """
    cfg = get_strategy_config(strategy_code)
    if not cfg or cfg.funnel_type != "market_scan":
        return NonLimitupScore(
            code=code, strategy_code=strategy_code, strategy_name="",
            strategy_score=0.0, score_breakdown={}, pattern=pattern,
        )

    rs_score = compute_relative_strength_score(pattern)
    ma_score = compute_ma_bullish_score(pattern)
    vol_score = compute_volume_signal_score(pattern, strategy_code)
    sec_score = compute_sector_strength_score(sector_rank)

    breakdown = {
        "relative_strength": round(rs_score * NON_LIMITUP_WEIGHTS["relative_strength"], 4),
        "ma_bullish": round(ma_score * NON_LIMITUP_WEIGHTS["ma_bullish"], 4),
        "volume_signal": round(vol_score * NON_LIMITUP_WEIGHTS["volume_signal"], 4),
        "sector_strength": round(sec_score * NON_LIMITUP_WEIGHTS["sector_strength"], 4),
    }
    score = sum(breakdown.values())

    return NonLimitupScore(
        code=code,
        strategy_code=cfg.code,
        strategy_name=cfg.name,
        strategy_score=round(score, 4),
        score_breakdown=breakdown,
        pattern=pattern,
    )


# ===========================================================================
# 非涨停类漏斗编排（spec §3.1）
# ===========================================================================

def run_non_limitup_funnel(
    candidates: list[dict],
    weather_state: str | None,
    sector_rank_map: dict[str, int] | None = None,
) -> list[dict]:
    """非涨停类漏斗：形态扫描 → 策略分排序 → 质量标准过滤。

    candidates: [{code, bars: [{...kline}], sector: industry_name}]
    weather_state: 天气状态（硬开关选策略组）
    sector_rank_map: {industry_name: rank} 板块排名（可选）

    流程（spec §3.1）：
    1. 天气硬开关 → 非涨停类策略组
    2. 对每个候选 × 每个适用策略：扫描形态 → 计算策略分 → 检查质量标准
    3. 过滤未通过硬标准的候选
    4. 按策略分降序排序
    """
    primary_codes, _ = get_strategies_for_weather(weather_state)

    # 过滤出非涨停类策略
    non_limitup_codes = [
        code for code in primary_codes
        if get_strategy_config(code) and get_strategy_config(code).funnel_type == "market_scan"
    ]

    if not non_limitup_codes:
        # 未知天气降级时可能无非涨停类，用 fallback
        _, fallback_codes = get_strategies_for_weather(weather_state)
        non_limitup_codes = [
            code for code in fallback_codes
            if get_strategy_config(code) and get_strategy_config(code).funnel_type == "market_scan"
        ]

    scored: list[dict] = []
    for cand in candidates:
        code = cand.get("code", "")
        bars = cand.get("bars", [])
        sector = cand.get("sector", "")
        sector_rank = sector_rank_map.get(sector) if sector_rank_map else None

        # 扫描形态
        from strategies.pattern_scan import scan_patterns
        pattern = scan_patterns(code, bars)

        for strat_code in non_limitup_codes:
            score_result = compute_non_limitup_score(code, pattern, strat_code, sector_rank)

            # 检查质量标准
            market_data = _build_market_data(pattern, cand)
            quality_results = check_quality_standards({"code": code}, strat_code, market_data)
            passes = passes_hard_standards(quality_results)

            scored.append({
                "code": code,
                "sector": sector,
                "strategy_code": score_result.strategy_code,
                "strategy_name": score_result.strategy_name,
                "strategy_score": score_result.strategy_score,
                "score_breakdown": score_result.score_breakdown,
                "quality_results": quality_results,
                "passes_hard_standards": passes,
                "relative_strength": pattern.relative_strength,
                "ma_bullish": pattern.ma_bullish,
                "volume_breakout_ratio": pattern.volume_breakout_ratio,
                "amount_yi": pattern.amount_yi,
                "ma5_proximity": pattern.ma5_proximity,
                "consolidation_days": pattern.consolidation_days,
            })

    # 过滤未通过硬标准的候选
    passed = [s for s in scored if s["passes_hard_standards"]]

    # 按策略分降序排序
    passed.sort(key=lambda x: x.get("strategy_score", 0), reverse=True)
    return passed


def _build_market_data(pattern: PatternScan, candidate: dict) -> dict:
    """从 PatternScan + candidate 构建 check_quality_standards 所需的 market_data。"""
    return {
        "close": candidate.get("close"),
        "ma5": pattern.ma5_proximity,  # 注意：这是接近度不是 MA5 值，需要从 bars 取
        "ma10": candidate.get("ma10"),
        "ma20": candidate.get("ma20"),
        "vol_ratio": pattern.volume_breakout_ratio,
        "amount_yi": pattern.amount_yi,
        "consecutive_boards": candidate.get("consecutive_boards"),
        "consolidation_days": pattern.consolidation_days,
        "vol_breakout_ratio": pattern.volume_breakout_ratio,
        "sector_rank": candidate.get("sector_rank"),
        "turnover_rate": candidate.get("turnover_rate"),
        "recent_zt_days": candidate.get("recent_zt_days"),
        "t1_limit_up": candidate.get("t1_limit_up"),
    }
