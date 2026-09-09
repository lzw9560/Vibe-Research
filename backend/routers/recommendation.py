"""
Recommendation router.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict

from recommendation_engine import get_recommendation, get_today_recommendations, get_multi_arm_recommendations

router = APIRouter(tags=["recommendation"])


@router.get("/api/recommendation/today")
async def today_recommendations(limit: int = Query(20, ge=1, le=50)) -> Dict[str, Any]:
    """获取今日推荐清单（HIGH/MEDIUM 优先）。"""
    try:
        recs = await get_today_recommendations(limit=limit)
        return {
            "data": [
                {
                    "code": r.code,
                    "name": r.name,
                    "gene_score": r.gene_score,
                    "level": r.level.value,
                    "position_suggestion": r.position_suggestion,
                    "reasoning": r.reasoning,
                    "risk_notes": r.risk_notes,
                }
                for r in recs
            ]
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"推荐引擎异常：{e}") from e


@router.get("/api/recommendation/multi-arm")
def multi_arm_recommendations() -> Dict[str, Any]:
    """S175 R9 — 多臂推荐（各臂 honest_label + floor 读 equity sizing，R9↔R10 接线）。

    floor=externally_validated actionable（ETF 512890 批次）；breakout=§44_falsified paper-only；
    limitup/trend=mock_not_ready；gap=dead_arm 不推荐。
    """
    try:
        recs = get_multi_arm_recommendations()
        return {"data": [
            {
                "arm": r.arm,
                "honest_label": r.honest_label.value,
                "action_type": r.action_type,
                "code": r.code,
                "name": r.name,
                "sizing_suggestion": r.sizing_suggestion,
                "coverage_rate": r.coverage_rate,
                "days_tracked": r.days_tracked,
                "validated": r.validated,
                "note": r.note,
            }
            for r in recs
        ]}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"多臂推荐异常：{e}") from e


@router.get("/api/recommendation/{code}")
async def stock_recommendation(code: str, date: str = Query(None, description="日期，格式 YYYY-MM-DD")) -> Dict[str, Any]:
    """获取个股推荐详情。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        rec = await get_recommendation(code, date)
        if not rec:
            # 数据可得性：该股当日无推荐 → 返回 200+null，避免前端把"无数据"误判为接口故障（404）
            return {"data": None}
        return {"data": rec}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"个股推荐异常：{e}") from e


__all__ = ["router"]
