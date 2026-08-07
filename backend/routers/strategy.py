"""
Strategy router.
"""
import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

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


@router.get("/api/strategy/backtest")
async def strategy_backtest(lookback_days: int = Query(60, ge=1, le=365)) -> Dict[str, Any]:
    """S031 R20/R22：按战法历史回测——8 战法各返 {win_rate, avg_return, sample_size, available_days}。

    只读 DB gene_scores + astock.kline（mootdx 本地），不触发 em_get；结果 12h 缓存。
    客观历史统计特征，市场有风险。
    """
    from strategies.strategy_backtest import run_strategy_backtest
    results = await asyncio.to_thread(run_strategy_backtest, lookback_days)
    return {
        "disclaimer": "历史统计特征，市场有风险，不构成投资建议。",
        "available_days": results[0].available_days if results else 0,
        "data": [
            {
                "strategy": r.strategy_name,
                "strategy_code": r.strategy_code,
                "win_rate": r.win_rate,
                "avg_return": r.avg_return,
                "sample_size": r.sample_size,
                "available_days": r.available_days,
            }
            for r in results
        ],
    }


__all__ = ["router"]
