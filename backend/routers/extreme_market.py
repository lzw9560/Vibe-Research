"""
Extreme market detector router.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict

import extreme_market_detector

router = APIRouter(tags=["market"])


@router.get("/api/market/extreme")
async def extreme_market_api(date: str = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日")) -> Dict[str, Any]:
    """获取极端行情信号（客观数据，非行动建议）。"""
    try:
        result = await extreme_market_detector.get_extreme_market_signal(date)
        if result is None:
            return {"data": {}}
        return {"data": result}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"极端行情检测异常：{e}") from e


__all__ = ["router"]
