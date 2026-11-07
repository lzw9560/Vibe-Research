# -*- coding: utf-8 -*-
"""anti_quant_engine —— 三战法因子计算 + 评分引擎（S235 T03，spec §5.2）。

三战法：反核（reversal）/ 尾盘突破（tail_breakout）/ 冰点反抽（ice_rebound）。

评分数学（修复 Oracle 阻断 3.4——原 sum(factors) 异纲量相加无效）：
1. 硬条件 veto（HARD_PRECONDITIONS）：任一硬条件归一化=0 → score=0，is_triggered=False
2. 软因子加权（FACTOR_WEIGHTS）：每因子 normalize_factor→0-1，按权重求和×100
3. is_triggered = score >= 60（探索性阈值，spec §2.3 标拍脑袋）

⚠️ 探索性：所有阈值未经统计验证，≤3% 资金跟踪，n≥60 才出 verdict。
"""

from __future__ import annotations

from tactics.factor_calculator import (
    calc_amount_ratio,
    calc_close_position,
    calc_prev_drop,
    calc_turnover_rate,
    calc_vol_ratio,
    calc_vwap,
    normalize_factor,
)

# ---------------------------------------------------------------------------
# 硬条件（gate）：任一不满足→veto（N1 修复：从权重表移出做 gate）
# ---------------------------------------------------------------------------

HARD_PRECONDITIONS: dict[str, list[str]] = {
    "reversal": ["prev_drop"],  # 前日必须跌>5%
    "tail_breakout": ["above_vwap"],  # 必须站稳 VWAP
    "ice_rebound": ["ice_point"],  # 必须冰点期
}

# ---------------------------------------------------------------------------
# 软因子权重（硬条件移出后重归一，三组和均=1.0）
# ---------------------------------------------------------------------------

FACTOR_WEIGHTS: dict[str, dict[str, float]] = {
    "reversal": {
        "gap_pct": 0.30,  # 2-5%→1.0
        "vol_ratio": 0.30,  # 4.5→1.0 线性
        "amount_ratio": 0.25,  # 10%→1.0 线性
        "bid_increasing": 0.15,  # bool→0/1
    },
    "tail_breakout": {
        "turnover_rate": 0.25,  # 12-22%→1.0
        "breakout_high": 0.25,
        "big_order_proxy": 0.10,  # 降级因子
        "sector_resonance": 0.25,
        "close_position": 0.15,
    },
    "ice_rebound": {
        "anti_drop": 0.35,
        "break_vwap": 0.20,
        "turnover_rate": 0.20,
        "bottom_divergence": 0.15,  # 降级因子
        "big_order_proxy": 0.10,  # 降级因子
    },
}

# 探索性评分阈值（spec §2.3 拍脑袋，标来源）
TRIGGER_SCORE = 60


def _veto_check(tactic_name: str, factors: dict) -> tuple[bool, str]:
    """硬条件 veto：任一硬条件归一化=0 → veto。返 (是否否决, 否决原因)。"""
    for h in HARD_PRECONDITIONS.get(tactic_name, []):
        if normalize_factor(h, factors.get(h)) == 0.0:
            return True, f"硬条件 {h} 不满足，veto"
    return False, ""


def _build_reason(normalized: dict, weights: dict) -> str:
    """人类可读的因子贡献串（降序排，便于飞书卡片展示）。"""
    items = sorted(
        ((k, normalized.get(k, 0.0), w) for k, w in weights.items()),
        key=lambda x: x[1] * x[2],
        reverse=True,
    )
    return "; ".join(f"{k}={n:.2f}×{w}" for k, n, w in items)


def _build_risk_warning(tactic_name: str) -> str:
    """战法特定风险提醒（统一加探索性 disclaimer）。"""
    base = "⚠️ 探索性策略，未经 Bootstrap 验证，≤3% 资金跟踪，单票≤1%"
    notes = {
        "reversal": "反核：竞价假抢筹风险（过 anti_quant_gateway），止损-10% gap-through",
        "tail_breakout": "尾盘突破：板块共振依赖前日数据，滑点 0.3%",
        "ice_rebound": "冰点反抽：冰点判定依赖连续 2 日跌停历史，首日不可用",
    }
    return f"{base} | {notes.get(tactic_name, '')}"


def score_tactic(name: str, factors: dict) -> dict:
    """评分核心：硬条件 veto + 软因子加权×100。返结果 dict。"""
    vetoed, reason = _veto_check(name, factors)
    if vetoed:
        return {
            "is_triggered": False,
            "tactic_name": "None",
            "score": 0,
            "reason": reason,
            "risk_warning": "不适用（硬条件未通过）",
            "factors": factors,
        }
    weights = FACTOR_WEIGHTS[name]
    normalized = {k: normalize_factor(k, factors.get(k)) for k in weights}
    score = sum(normalized[k] * w for k, w in weights.items()) * 100
    is_triggered = score >= TRIGGER_SCORE
    return {
        "is_triggered": is_triggered,
        "tactic_name": name if is_triggered else "None",
        "score": int(round(score)),
        "reason": _build_reason(normalized, weights),
        "risk_warning": _build_risk_warning(name),
        "factors": factors,
    }


class AntiQuantEngine:
    """三战法评分引擎。无状态（ice_point / market 数据由调用方传入，便于测试）。"""

    def evaluate_reversal(
        self,
        code: str,
        prev_klines: list[dict],
        auction_live_1: dict,
        auction_live_2: dict,
        auction_final: dict,
        prev_day_turnover: float = 0.0,
    ) -> dict:
        """战法一反核：前日跌>5% + 09:25 高开 2-5% + 量比>4.5 + 额占比>10%。"""
        prev_close = float(prev_klines[-1].get("close_price", 0) or 0) if prev_klines else 0.0
        open_price = float(auction_final.get("open_price", 0) or 0)
        gap_pct_calc = ((open_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
        # 5 日开盘量从 prev_klines 取（open_volume 优先，fallback volume）
        prev_5d_open_vols = [float(k.get("open_volume", k.get("volume", 0)) or 0) for k in prev_klines[-5:]]
        # hithink auction-snapshot 直接值优先（真实数据口径正确），
        # 回退 calc（inline 测试）。2026-10-08 实测发现：calc 口径错
        # （竞价量/前5日开盘量单位不匹配返0），hithink 直接值才对。
        gap_pct = float(auction_final.get("auction_pct") or gap_pct_calc or 0)
        vol_ratio = float(
            auction_final.get("auction_volume_ratio") or calc_vol_ratio(auction_final, prev_5d_open_vols) or 0
        )
        # auction_yesterday_ratio_pct 是百分点（2.66=2.66%），amount_ratio 需比率（0.0266）→ /100
        amt_hithink = float(auction_final.get("auction_yesterday_ratio_pct", 0) or 0) / 100
        amount_ratio = amt_hithink if amt_hithink > 0 else calc_amount_ratio(auction_final, prev_day_turnover)
        factors = {
            "prev_drop": calc_prev_drop(prev_klines),
            "gap_pct": gap_pct,
            "vol_ratio": vol_ratio,
            "amount_ratio": amount_ratio,
            "bid_increasing": bool(
                float(auction_live_2.get("volume", 0) or 0) >= float(auction_live_1.get("volume", 0) or 0)
            ),
        }
        result = score_tactic("reversal", factors)
        result["code"] = code
        result["raw"] = {
            "prev_klines": prev_klines,
            "auction_live_1": auction_live_1,
            "auction_live_2": auction_live_2,
            "auction_final": auction_final,
            "prev_day_turnover": prev_day_turnover,
        }
        return result

    def evaluate_tail_breakout(
        self,
        code: str,
        snapshot: dict,
        limit_up_pool: dict | list | None = None,
    ) -> dict:
        """战法二尾盘突破：站稳 VWAP + 换手 12-22% + 突破日内高点 + 板块≥2 涨停。"""
        vwap = calc_vwap(snapshot)
        close = float(snapshot.get("close_price", 0) or 0)
        high = float(snapshot.get("high_price", 0) or 0)
        # 板块涨停数：limit_up_pool 为 dict 时取 total，为 list 时取 len
        if isinstance(limit_up_pool, dict):
            sector_count = int(limit_up_pool.get("total", 0) or 0)
        elif isinstance(limit_up_pool, list):
            sector_count = len(limit_up_pool)
        else:
            sector_count = 0
        factors = {
            "above_vwap": bool(close > 0 and close >= vwap),
            "turnover_rate": calc_turnover_rate(snapshot),
            "breakout_high": (close / high) if high > 0 else 0.0,
            "big_order_proxy": float(snapshot.get("big_order_proxy", 0) or 0),
            "sector_resonance": sector_count,
            "close_position": calc_close_position(snapshot),
        }
        result = score_tactic("tail_breakout", factors)
        result["code"] = code
        result["raw"] = {"snapshot": snapshot, "limit_up_pool": limit_up_pool}
        return result

    def evaluate_ice_rebound(
        self,
        code: str,
        snapshot: dict,
        market_stats: dict,
        ice_point: bool = False,
    ) -> dict:
        """战法三冰点反抽：冰点期 + 盘中抗跌 + 换手 8-15%。

        ice_point 由调用方从 IcePointDetector 传入（保持引擎无状态、可测）。
        anti_drop = 个股跌幅 - 市场跌幅（正值=抗跌，跌得比市场少）。
        """
        stock_drop = float(snapshot.get("price_change_ratio_pct", 0) or 0)
        market_drop = float(market_stats.get("market_drop_pct", 0) or 0)
        anti_drop = stock_drop - market_drop  # 个股跌得比市场少 → 正
        vwap = calc_vwap(snapshot)
        close = float(snapshot.get("close_price", 0) or 0)
        factors = {
            "ice_point": bool(ice_point),
            "anti_drop": anti_drop,
            "break_vwap": bool(close > 0 and close >= vwap),
            "turnover_rate": calc_turnover_rate(snapshot),
            "bottom_divergence": float(snapshot.get("bottom_divergence", 0) or 0),
            "big_order_proxy": float(snapshot.get("big_order_proxy", 0) or 0),
        }
        result = score_tactic("ice_rebound", factors)
        result["code"] = code
        result["raw"] = {"snapshot": snapshot, "market_stats": market_stats, "ice_point": ice_point}
        return result
