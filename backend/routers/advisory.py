# -*- coding: utf-8 -*-
"""S042 统一持仓建议引擎 API（R5）。

GET /api/advisory/summary → 三场景建议汇总（推荐/自选/持仓）。
教育研究式口吻，非交易指令（CLAUDE.md §1.1 弱合规）。
"""
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from strategies.position_advisor_v2 import advisory_summary

router = APIRouter(tags=["advisory"])


@router.get("/api/advisory/summary")
async def advisory_summary_endpoint(
    limit: int = Query(20, ge=1, le=50, description="推荐标的取 top N"),
) -> Dict[str, Any]:
    """三场景建议汇总（recommendations + watchlist + holdings）。

    每条建议含 win_rate / win_rate_source（backtest_90d / synthetic / none）/
    matched_strategy / reasons / risk_notes + 免责声明。
    """
    try:
        return await advisory_summary(limit)
    except Exception as e:  # noqa: BLE001 — 建议引擎异常返 502，不泄露栈
        raise HTTPException(502, f"建议引擎异常：{e}") from e


__all__ = ["router"]
