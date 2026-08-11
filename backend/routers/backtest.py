"""
Backtest router.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict

from backtest_lite import (
    run_backtest_async,
    generate_scatter_data,
    _calc_factor_percentile_analysis,
    _calc_factor_ic,
    _PREMIUM_BUCKETS,
)
import scheduled_tasks as _st  # S041：复用 market_data.db 连接 + get_backtest_snapshots

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


@router.get("/api/backtest/trend")
async def backtest_trend(
    days: int = Query(90, ge=1, le=365, description="最近 N 天快照"),
) -> Dict[str, Any]:
    """S041：回测指标趋势时间序列（hit_rate/avg_return/各战法 win_rate 随日期变化）。

    返回 {data: [{snapshot_date, engine, hit_rate, avg_return, max_drawdown,
    sharpe_ratio, total_signals, percentile_json, strategy_breakdown_json, created_at}, ...]}。
    按 snapshot_date 升序，engine 升序（同日 lite 在 strategy 前）。
    JSON 字段已反序列化成 dict/list，缺失为 None。
    """
    try:
        rows = _st.get_backtest_snapshots(days)
        return {"data": rows}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"回测趋势数据异常：{e}") from e


@router.get("/api/backtest/factor-analysis")
async def backtest_factor_analysis(
    start: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end: str = Query(..., description="结束日期 YYYY-MM-DD"),
    factor: str = Query("premium_rate", description="因子名，当前仅支持 premium_rate（次日溢价率）"),
) -> Dict[str, Any]:
    """S043 R4：单因子分位分析——按因子值分桶，输出各桶 count / avg_return / hit_rate。

    样本取该区间全部基因候选（不按 qualify 阈值过滤），避免幸存者偏差。
    """
    _FACTOR_MAP = {"premium_rate": ("factor_premium_rate", _PREMIUM_BUCKETS)}
    if factor not in _FACTOR_MAP:
        raise HTTPException(400, f"不支持的因子：{factor}，可选：{', '.join(_FACTOR_MAP)}")
    factor_key, buckets = _FACTOR_MAP[factor]
    try:
        scatter = await generate_scatter_data((start, end))
        analysis = _calc_factor_percentile_analysis(scatter, factor_key, buckets)
        ic_analysis = _calc_factor_ic(scatter, factor_key)
        return {
            "data": {
                "factor": factor,
                "period": f"{start} ~ {end}",
                "sample_size": len(scatter),
                "buckets": analysis,
                "ic_analysis": ic_analysis,
            }
        }
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"因子分位分析异常：{e}") from e


__all__ = ["router"]
