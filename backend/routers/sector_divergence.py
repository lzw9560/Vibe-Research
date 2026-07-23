"""
Sector divergence router.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict

import sector_divergence

router = APIRouter(tags=["sector"])


@router.get("/api/sector/divergence")
async def sector_divergence_api(date: str = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日")) -> Dict[str, Any]:
    """获取板块情绪分化度（客观数据，非行动建议）。"""
    try:
        result = await sector_divergence.get_sector_divergence(date)
        if result is None:
            return {"data": []}
        return {"data": result}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"板块分化度计算异常：{e}") from e


@router.get("/api/sector/divergence/history")
async def sector_divergence_history(days: int = Query(30, ge=7, le=252, description="历史天数")) -> Dict[str, Any]:
    """获取板块情绪分化度历史趋势（客观数据，非行动建议）。"""
    try:
        history = await sector_divergence.get_sector_divergence_history(days=days)
        return {"data": history}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"板块分化度历史查询异常：{e}") from e


@router.get("/api/sector/rotation")
async def sector_rotation_api(date: str = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日")) -> Dict[str, Any]:
    """获取板块轮动速度（客观数据，非行动建议）。"""
    try:
        result = await sector_divergence.get_sector_rotation(date)
        if result is None:
            return {"data": {}}
        return {"data": result}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"板块轮动计算异常：{e}") from e


__all__ = ["router"]
