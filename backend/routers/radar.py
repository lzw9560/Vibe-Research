"""
Radar router.
"""
from fastapi import APIRouter, HTTPException
from typing import Any, Dict

import newsradar

router = APIRouter(tags=["radar"])


@router.get("/api/radar")
def radar() -> Dict[str, Any]:
    """资讯雷达：12 赛道公开 RSS 资讯（读缓存，无缓存返回赛道骨架）。"""
    try:
        return {"data": newsradar.get_radar(force=False)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资讯雷达异常：{e}") from e


@router.post("/api/radar/refresh")
def radar_refresh() -> Dict[str, Any]:
    """强制重抓全部 RSS 源（耗时约 20-40s），更新缓存。"""
    try:
        return {"data": newsradar.fetch_radar()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资讯雷达刷新失败：{e}") from e


__all__ = ["router"]
