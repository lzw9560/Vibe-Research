# -*- coding: utf-8 -*-
"""S042 统一持仓建议引擎 API（R5）+ S067 P3 端点超时降级。

GET /api/advisory/summary → 三场景建议汇总（推荐/自选/持仓）。
教育研究式口吻，非交易指令（CLAUDE.md §1.1 弱合规）。
"""
import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from strategies.position_advisor_v2 import advisory_summary, advise_recommendations, advise_watchlist

router = APIRouter(tags=["advisory"])

# S067 P3：端点超时上限（秒）——超时返回已计算部分 + partial=true
_ENDPOINT_TIMEOUT = 15.0


@router.get("/api/advisory/summary")
async def advisory_summary_endpoint(
    limit: int = Query(20, ge=1, le=50, description="推荐标的取 top N"),
) -> Dict[str, Any]:
    """三场景建议汇总（recommendations + watchlist + holdings）。

    每条建议含 win_rate / win_rate_source（backtest_90d / synthetic / none）/
    matched_strategy / reasons / risk_notes + 免责声明。

    S067 P3：15s 超时降级——超时返回已计算部分 + partial=true + disclaimer，
    不让前端卡死。超时部分标 timed_out。回退不重算（避免再次阻塞）。
    """
    try:
        result = await asyncio.wait_for(advisory_summary(limit), timeout=_ENDPOINT_TIMEOUT)
        return result
    except asyncio.TimeoutError:
        # 超时降级：返回空 + partial=true，不重算（重算会再次阻塞事件循环）
        return {
            "recommendations": [],
            "watchlist": [],
            "holdings": [],
            "partial": True,
            "timed_out": True,
            "timeout_seconds": _ENDPOINT_TIMEOUT,
            "disclaimer": "历史统计特征，市场有风险，不构成投资建议。端点超时，建议稍后重试。",
            "note": f"端点 {_ENDPOINT_TIMEOUT}s 超时，三场景均未完成。可能是回测冷启动或数据源慢，请稍后重试。",
        }
    except Exception as e:  # noqa: BLE001 — 建议引擎异常返 502，不泄露栈
        raise HTTPException(502, f"建议引擎异常：{e}") from e


__all__ = ["router"]
