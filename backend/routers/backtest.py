"""
Backtest router.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict

from backtest_lite import run_backtest_async, generate_scatter_data

router = APIRouter(tags=["backtest"])


@router.get("/api/backtest/scatter")
async def backtest_scatter(
    start: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end: str = Query(..., description="结束日期 YYYY-MM-DD"),
) -> Dict[str, Any]:
    """获取回测散点数据。"""
    try:
        data = await generate_scatter_data((start, end))
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"回测散点数据异常：{e}") from e


@router.get("/api/backtest/result")
async def backtest_result(
    start: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end: str = Query(..., description="结束日期 YYYY-MM-DD"),
) -> Dict[str, Any]:
    """获取回测结果。"""
    try:
        result = await run_backtest_async(start, end)
        return {
            "data": {
                "period": result.period,
                "total_signals": result.total_signals,
                "hit_count": result.hit_count,
                "hit_rate": result.hit_rate,
                "avg_return": result.avg_return,
                "max_drawdown": result.max_drawdown,
                "sharpe_ratio": result.sharpe_ratio,
                "percentile_analysis": result.percentile_analysis,
            }
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"回测结果异常：{e}") from e


__all__ = ["router"]
