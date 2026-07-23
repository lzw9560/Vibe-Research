"""
LimitUp analysis router.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict

import limitup_strategy as lstrat
from routers.common import _validate
from risk import update_one_day_risk_realtime

router = APIRouter(tags=["limitup"])


@router.get("/api/limitup/analysis/{code}")
async def limitup_analysis(code: str, date: str = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日")) -> Dict[str, Any]:
    """获取个股的基因得分 + 策略逻辑匹配 + 风控规则知识（教育性展示，非行动建议）。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        # 动态获取一日游风险评分（V2.0.2 动态化）
        risk = await update_one_day_risk_realtime(code)
        result = await lstrat.get_analysis(code, date, risk=risk)
        return {"data": result}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"个股策略分析异常：{e}") from e


__all__ = ["router"]
