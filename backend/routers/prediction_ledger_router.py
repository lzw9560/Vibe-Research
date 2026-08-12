# -*- coding: utf-8 -*-
"""S061 R4：预测账本端点。

挂在 /api/prediction-ledger/* 前缀（区别于 S017 的 /api/prediction/* 级联预测）。

GET  /api/prediction-ledger          — 账本列表 + 命中率分桶
POST /api/prediction-ledger           — 手动录入预测
POST /api/prediction-ledger/ingest    — 触发系统信号入账（盘后调度用）
POST /api/prediction-ledger/verify    — 触发到期对账
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import prediction_ledger as pl
from prediction_ingest import ingest_all
from prediction_verify import verify_due_predictions

router = APIRouter(prefix="/api/prediction-ledger", tags=["prediction-ledger"])
_logger = logging.getLogger("vibe-research")


class PredictionBody(BaseModel):
    """手动录入预测。"""
    stated_at: str = Field(..., description="预测发出日 YYYY-MM-DD")
    code: str = Field(..., description="股票代码 6 位")
    name: str = ""
    source: str = Field("manual", description="funnel_candidate | strategy_hit | manual")
    signal_ref: str = ""
    prediction_type: str = Field("next_day_premium", description="next_day_premium | strategy_outcome")
    baseline_price: float = 0.0
    expected: str = ">0"
    horizon: int = Field(1, ge=1, le=30, description="验证周期天数")


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


@router.post("")
async def add_prediction(body: PredictionBody) -> Dict[str, Any]:
    """手动录入预测。幂等：同日同源同股一条。"""
    try:
        p = pl.Prediction(
            stated_at=body.stated_at,
            source=body.source,
            code=body.code,
            name=body.name,
            signal_ref=body.signal_ref,
            prediction_type=body.prediction_type,
            baseline_price=body.baseline_price,
            expected=body.expected,
            horizon=body.horizon,
        )
        new_id = pl.add_prediction(p)
        if new_id is None:
            return {"status": "duplicate", "msg": "同日同源同股已存在"}
        return {"status": "ok", "id": new_id}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        _logger.exception("预测录入异常")
        raise HTTPException(502, f"预测录入异常：{e}") from e


@router.post("/ingest")
async def trigger_ingest(date: Optional[str] = Query(None, description="YYYY-MM-DD，默认今日")) -> Dict[str, Any]:
    """触发系统信号入账（漏斗 final + 战法命中）。盘后调度用。"""
    try:
        import asyncio
        result = await asyncio.to_thread(ingest_all, date)
        return {"status": "ok", "result": result}
    except Exception as e:  # noqa: BLE001
        _logger.exception("预测入账异常")
        raise HTTPException(502, f"预测入账异常：{e}") from e


@router.post("/verify")
async def trigger_verify(date: Optional[str] = Query(None, description="YYYY-MM-DD，默认今日")) -> Dict[str, Any]:
    """触发到期对账：扫 pending → hit/miss/voided。"""
    try:
        import asyncio
        result = await asyncio.to_thread(verify_due_predictions, date)
        return {"status": "ok", "result": result}
    except Exception as e:  # noqa: BLE001
        _logger.exception("预测对账异常")
        raise HTTPException(502, f"预测对账异常：{e}") from e


__all__ = ["router"]
