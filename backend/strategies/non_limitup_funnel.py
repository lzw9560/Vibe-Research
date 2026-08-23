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
    get_strategy_config,
    compute_strategy_score,
)


# ===========================================================================
# 板块等权平均日K聚合（S094 R2）
# ===========================================================================

def _aggregate_sector_bars(stock_bars_list: list[list[dict]]) -> list[dict]:
    """板块成分股等权平均日K（S094 R2）。

    spec §3.L ora-6 A5：成分股集合=板块全成分（有 bar 者参与），
    停牌/缺 bar 按日期对齐取交集。

    返回 list[dict]（{date, close, high, low, volume, amount} 简单平均），
    按日期升序。无数据返 []。
    """
    if not stock_bars_list:
        return []
    # 按日期聚合：{date: {field: [vals across stocks]}}
    by_date: dict[str, dict[str, list[float]]] = {}
    for bars in stock_bars_list:
        for b in bars:
            d = b.get("date")
            if not d:
                continue
            by_date.setdefault(d, {})
            for field in ("close", "high", "low", "volume", "amount"):
                v = b.get(field)
                if v is not None:
                    try:
                        by_date[d].setdefault(field, []).append(float(v))
                    except (ValueError, TypeError):
                        pass
    result: list[dict] = []
    for d in sorted(by_date.keys()):
        agg = by_date[d]
        row: dict[str, Any] = {"date": d}
        # 仅对至少 1 只成分股有值的字段取平均（等权，有 bar 者参与）
        for field in ("close", "high", "low", "volume", "amount"):
            vals = agg.get(field, [])
            if vals:
                row[field] = round(sum(vals) / len(vals), 4)
        result.append(row)
    return result


def _build_sector_bars_map(
    candidates: list[dict],
    sector_bars_map: dict[str, list[dict]] | None = None,
) -> dict[str, list[dict]]:
    """从 candidates 聚合每个 sector 的等权平均日K（S094 R2）。

    调用方可显式传 sector_bars_map 覆盖（S2 R14 候选扩字段后统一传）；
    不传则内部从 candidates 同 sector 的 bars 聚合兜底。
    """
    if sector_bars_map:
        return sector_bars_map
    sector_to_bars: dict[str, list[list[dict]]] = {}
    for cand in candidates:
        sector = cand.get("sector")
        if not sector:
            continue
        bars = cand.get("bars") or []
        if bars:
            sector_to_bars.setdefault(sector, []).append(bars)
    return {sector: _aggregate_sector_bars(bars_list) for sector, bars_list in sector_to_bars.items()}


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

    S094 R3：删硬编码 NON_LIMITUP_WEIGHTS，委托 compute_strategy_score
    读 strategy_weights.json 的 non_limitup 权重集（等权兜底，与旧硬编码值一致）。
    S094 R4：per-strategy volume_signal 下沉 match 层后，候选 factors 用单一一份
    PatternScan factors dict（中文键 {相对强度,均线多头,量能信号,板块强度} 0-100），
    此处仍用 compute_volume_signal_score 产 volume_signal 因子值（S2 R27 拆打分后删）。
    """
    cfg = get_strategy_config(strategy_code)
    if not cfg or cfg.funnel_type != "market_scan":
        return NonLimitupScore(
            code=code, strategy_code=strategy_code, strategy_name="",
            strategy_score=0.0, score_breakdown={}, pattern=pattern,
        )

    # S094 R4：单一 PatternScan factors dict（中文键，0-100 值，复用 4 个映射函数）
    rs_score = compute_relative_strength_score(pattern)
    ma_score = compute_ma_bullish_score(pattern)
    vol_score = compute_volume_signal_score(pattern, strategy_code)
    sec_score = compute_sector_strength_score(sector_rank)

    factors = {
        "相对强度": rs_score,
        "均线多头": ma_score,
        "量能信号": vol_score,
        "板块强度": sec_score,
    }

    # S094 R3：委托 compute_strategy_score（读 strategy_weights.json non_limitup 权重集）
    score, breakdown = compute_strategy_score(factors, "non_limitup")

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
    sector_bars_map: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """S094 R27/T9-full：只产非涨停候选（scan_patterns + 挂 pattern/sector_rank/close/name）。

    不自打分（删 compute_non_limitup_score 调用 + check_quality 过滤 + 排序）——打分 +
    硬剔除归 score_candidates(market_scan) 统一入口（T16 端点接线、check_quality 闸前移在 2b-i-c）。
    weather_state/sector_rank_map 保留签名兼容（现 unused：只产候选不做策略选择/打分）；
    板块内 sector_rank 在 candidate 上（build_non_limitup_candidates T8 算）。

    返回 [{code,name,bars,sector,sector_rank(板块内),close,pattern: PatternScan}, ...]。
    """
    sb_map = _build_sector_bars_map(candidates, sector_bars_map)
    produced: list[dict] = []
    for cand in candidates:
        code = cand.get("code", "")
        bars = cand.get("bars", [])
        sector = cand.get("sector", "")
        # 扫描形态（S094 R2：传 sector_bars，compute_relative_strength 真相对值）
        from strategies.pattern_scan import scan_patterns
        pattern = scan_patterns(code, bars, sb_map.get(sector))
        produced.append({
            **cand,
            "pattern": pattern,
            "name": cand.get("name", ""),
            "sector_rank": cand.get("sector_rank"),
            "close": cand.get("close") if cand.get("close") is not None else (bars[-1].get("close") if bars else None),
        })
    return produced


# S094 2b-i-c：_build_market_data 迁至 strategies/market_scan.py（因子层 home，§3.M；
# 供 score_candidates(market_scan) check_quality 闸前移用，避循环 import）。T9-full 后本模块不再调它。
