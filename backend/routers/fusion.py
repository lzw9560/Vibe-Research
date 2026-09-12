"""S194 fusion router——融合研判查询（FE-6 前端展示用）。

GET /api/fusion/{code} → compute_fusion_for_query(code)（最新交易日）→ fusion_output dict +
build_fusion_context 文本块。前端 FusionPage 展示 regime/方向/置信度/信号权重/top 相似 case。
"""
from fastapi import APIRouter, HTTPException
from typing import Any, Dict

from engine.fusion_pipeline import compute_fusion_for_query
from engine.fusion_layer import build_fusion_context

router = APIRouter(tags=["fusion"])


@router.get("/api/fusion/{code}")
def fusion_for_stock(code: str) -> Dict[str, Any]:
    """查个股最新交易日的融合研判。返 {data: {fusion: {...}, context_text: str}}。"""
    try:
        out = compute_fusion_for_query(str(code))
        return {"data": {"fusion": out, "context_text": build_fusion_context(out)}}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"融合研判异常：{e}") from e
