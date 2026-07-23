"""
Strategy router.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict

import limitup_strategy as lstrat

router = APIRouter(tags=["strategy"])


@router.get("/api/strategy/signals/{code}")
async def strategy_signals(code: str, date: str = Query(None, description="日期，格式 YYYY-MM-DD")) -> Dict[str, Any]:
    """获取个股战法匹配信号。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        signals = await lstrat.get_strategy_signals(code, date)
        return {
            "data": [
                {
                    "code": s.code,
                    "name": s.name,
                    "strategy_name": s.strategy_name,
                    "strategy_code": s.strategy_code,
                    "score": s.score,
                    "signal_strength": s.signal_strength,
                    "confidence": s.confidence,
                    "entry_price": s.entry_price,
                    "entry_condition": s.entry_condition,
                    "entry_type": s.entry_type,
                    "stop_loss": s.stop_loss,
                    "stop_loss_condition": s.stop_loss_condition,
                    "take_profit": s.take_profit,
                    "take_profit_condition": s.take_profit_condition,
                    "max_hold_days": s.max_hold_days,
                    "exit_condition": s.exit_condition,
                    "historical_win_rate": s.historical_win_rate,
                    "historical_avg_return": s.historical_avg_return,
                    "sample_size": s.sample_size,
                    "risk_reward_ratio": s.risk_reward_ratio,
                    "reasoning": s.reasoning,
                    "risk_notes": s.risk_notes,
                }
                for s in signals
            ]
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"战法信号异常：{e}") from e


@router.get("/api/strategy/registry")
async def strategy_registry() -> Dict[str, Any]:
    """获取战法库定义。"""
    try:
        registry = lstrat.get_strategy_registry()
        return {"data": registry}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"战法库获取异常：{e}") from e


__all__ = ["router"]
