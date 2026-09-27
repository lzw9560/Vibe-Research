# -*- coding: utf-8 -*-
"""S061 R4：预测账本端点。

挂在 /api/prediction-ledger/* 前缀（区别于 S017 的 /api/prediction/* 级联预测）。

GET  /api/prediction-ledger          — 账本列表 + 命中率分桶
（POST /api/prediction-ledger/verify 已删 2026-09-27 v6 H6/H7 Phase 3 #20——verify_due_predictions 函数保留在 prediction_verify.py）
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

import prediction_ledger as pl

router = APIRouter(prefix="/api/prediction-ledger", tags=["prediction-ledger"])
_logger = logging.getLogger("vibe-research")


@router.get("")
async def get_ledger(
    days: int = Query(30, ge=1, le=180),
    source: str = Query("", description="按 source 过滤"),
) -> Dict[str, Any]:
    """预测账本：列表 + 命中率分桶。

    - 列表：最近 N 天预测（含未验证的 pending）
    - 统计：按 source 分桶，n<10 标注 sample_sufficient=false
    """
    try:
        preds = pl.list_predictions(days=days, source=source)
        stats = pl.compute_hit_rate(source=source, days=days)
        return {
            "data": [{
                "id": p.id,
                "stated_at": p.stated_at,
                "source": p.source,
                "signal_ref": p.signal_ref,
                "code": p.code,
                "name": p.name,
                "prediction_type": p.prediction_type,
                "expected": p.expected,
                "horizon": p.horizon,
                "due_date": p.due_date,
                "actual_return": p.actual_return,
                "status": p.status,
                "attribution": p.attribution,
                "verified_at": p.verified_at,
            } for p in preds],
            "stats": stats,
            "disclaimer": "历史统计特征，市场有风险，研究参考",
        }
    except Exception as e:  # noqa: BLE001
        _logger.exception("预测账本查询异常")
        raise HTTPException(502, f"预测账本异常：{e}") from e


__all__ = ["router"]
