"""S071 盘前选股 router（breakout 弱信号 + 风控 + 诚实标签）。

§44 60日复验窗口：breakout day-cluster lift=1.72x <2x，未 validated 但不阻断——honest_label 标弱信号，
edge 主来自风控非对称（(b) ethos）。前向测试期间不投真金。
"""
from typing import Any, Dict

from fastapi import APIRouter, Query

router = APIRouter(tags=["strategy"])


@router.get("/api/strategy/premarket-selection")
async def premarket_selection(
    date: str = Query(..., description="目标交易日 T (YYYY-MM-DD)，用 T-1 kline 算 breakout"),
    top_n: int = Query(20, ge=1, le=50, description="返回候选数上限"),
    min_score: float = Query(0.90, ge=0.0, le=1.0, description="breakout 分数下限（0-1）"),
) -> Dict[str, Any]:
    """S071 盘前选股：breakout_20d 排序 → top-N + 风控具体价。

    返回候选（code/breakout 分数/止损/止盈/仓位×日历）+ honest_label + 风控参数。
    弱信号（§44 60日复验窗口：<2x 未 validated 但不阻断，honest_label 标弱信号跑通），edge 主来自风控非对称。前向测试期间不投真金。
    """
    from strategies.premarket_selection import select_premarket_with_risk

    sel = select_premarket_with_risk(date, top_n=top_n, min_score=min_score)
    return {
        "disclaimer": (
            "弱信号（§44 day-cluster lift=1.72x<2x 非 validated edge）。"
            "前向测试期间不投真金。历史统计特征，市场有风险。"
        ),
        "data": {
            "target_date": sel.target_date,
            "honest_label": sel.honest_label,
            "risk_params": {
                "position_pct": sel.risk_params.position_pct,
                "max_positions": sel.risk_params.max_positions,
                "stop_loss_pct": sel.risk_params.stop_loss_pct,
                "take_profit_pct": sel.risk_params.take_profit_pct,
                "max_hold_days": sel.risk_params.max_hold_days,
            },
            "calendar_multiplier": sel.calendar_multiplier,
            "calendar_reason": sel.calendar_reason,
            "market_note": sel.market_note,
            "candidates": [
                {
                    "code": c.code,
                    "name": c.name,
                    "breakout_score": c.breakout_score,
                    "breakout_binary": c.breakout_binary,
                    "t1_close": c.t1_close,
                    "t1_date": c.t1_date,
                    "entry_ref": c.entry_ref,
                    "stop_loss": c.stop_loss,
                    "take_profit": c.take_profit,
                    "position_pct": c.position_pct,
                }
                for c in sel.candidates
            ],
            "count": len(sel.candidates),
        },
    }


__all__ = ["router"]
