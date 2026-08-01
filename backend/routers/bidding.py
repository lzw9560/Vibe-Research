"""
Bidding monitor router.
"""
from fastapi import APIRouter, HTTPException
from typing import Any, Dict

from bidding_monitor import monitor_auction, build_auction_watchlist

router = APIRouter(tags=["bidding"])


@router.get("/api/auction/monitor")
async def auction_monitor() -> Dict[str, Any]:
    """候选池竞价监控（9:25 最终确认信号）。"""
    try:
        signals = await monitor_auction()
        if not signals:
            return {"data": []}
        return {
            "data": [
                {
                    "code": s.code,
                    "name": s.name,
                    "signal_type": s.signal_type,
                    "confidence": s.confidence,
                    "open_premium": s.open_premium,
                    "volume_ratio": s.volume_ratio,
                    "reasoning": s.reasoning,
                }
                for s in signals
            ]
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"竞价监控异常：{e}") from e


@router.get("/api/auction/watchlist")
async def auction_watchlist() -> Dict[str, Any]:
    """获取当前竞价监控候选池。"""
    try:
        codes = await build_auction_watchlist()
        return {"data": codes}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"候选池获取异常：{e}") from e


__all__ = ["router"]
