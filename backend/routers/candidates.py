# -*- coding: utf-8 -*-
"""候选池漏斗 + 诊断卡路由（S002 阶段 E）。

挂 /api/workflow/candidates/* 与 /api/workflow/funnel/*。
合规：仅客观数据，无方向/参考价位（AC10）。VR_API_KEY 由 app 中间件统一鉴权。
"""

from __future__ import annotations

import asyncio
from datetime import date as _date
from typing import Any

from fastapi import APIRouter, Query, HTTPException

from app import cache_response
from candidate_funnel import funnel as funnel_mod
from candidate_funnel.models import BaseThreshold, ThresholdConfig
from config import AssistantDefaultConfig

router = APIRouter(prefix="/api/workflow", tags=["candidates"])


def _default_config() -> ThresholdConfig:
    """从 AssistantDefaultConfig 构造默认候选池配置（A10）。"""
    d = AssistantDefaultConfig()
    return ThresholdConfig(
        mode=d.CANDIDATE_FUNNEL_MODE,
        base=BaseThreshold(**d.CANDIDATE_FUNNEL_BASE),
    )


# P1 内存配置（不动状态机持久化），初值取自 AssistantDefaultConfig 默认（A10）
_defaults = AssistantDefaultConfig()
_store: dict[str, Any] = {
    "config": _default_config(),
    "sources": dict(_defaults.CANDIDATE_FUNNEL_SOURCES),
}


def _today() -> str:
    return _date.today().isoformat()


@router.post("/candidates/funnel")
async def post_funnel(stage: str = "all", date: str | None = None):
    """POST → FunnelResult（AC1/AC7/AC9）。"""
    return await asyncio.to_thread(funnel_mod.run_funnel, stage, date or _today(), _store["config"])


@router.get("/candidates")
@cache_response(ttl=60)
async def list_candidates(date: str | None = None):
    """GET → 最终候选 DiagnosisCard 列表（AC1）。"""
    result = await asyncio.to_thread(funnel_mod.run_funnel, "all", date or _today(), _store["config"])
    return result.final_candidates


@router.get("/candidates/{code}/diagnosis")
@cache_response(ttl=60)
async def get_diagnosis(code: str, date: str | None = None):
    """GET → 单股 DiagnosisCard（AC3/AC4/AC6）。"""
    return await asyncio.to_thread(funnel_mod.diagnose, code, date or _today(), _store["config"])


@router.get("/funnel/layers")
@cache_response(ttl=60)
async def get_layers(run_id: str | None = None, date: str | None = None):
    """GET → 各层 FunnelLayer（AC1 每层可检视）。"""
    result = await asyncio.to_thread(funnel_mod.run_funnel, "all", date or _today(), _store["config"])
    return result.layers


@router.get("/funnel/config")
async def get_config():
    """GET → ThresholdConfig + 来源开关（AC2）。"""
    return {"config": _store["config"].model_dump(), "sources": _store["sources"]}


@router.put("/funnel/config")
async def put_config(body: dict):
    """PUT → 更新配置（AC2）。body 可含 ThresholdConfig 字段 + sources 开关。"""
    cfg_data = {k: v for k, v in body.items() if k != "sources"}
    if cfg_data:
        _store["config"] = ThresholdConfig(**cfg_data)
    if isinstance(body.get("sources"), dict):
        _store["sources"].update(body["sources"])
    return {"config": _store["config"].model_dump(), "sources": _store["sources"]}


@router.put("/funnel/layers/{layer_id}/rerun")
async def rerun_layer(layer_id: str, date: str | None = None, body: dict | None = None):
    """重跑单层（S023 F3）：更新 cfg 后重跑，只返回该层结果。

    交互：调参→重跑该层→展示新结果→用户决定是否下游全跑。
    实现：run_funnel 整体重跑（分层调用成本高），前端只展示目标层。
    """
    if body:
        cfg_data = {k: v for k, v in body.items() if k != "sources"}
        if cfg_data:
            _store["config"] = ThresholdConfig(**cfg_data)
    result = await asyncio.to_thread(funnel_mod.run_funnel, "all", date or _today(), _store["config"])
    layer = next((l for l in result.layers if l.layer_id == layer_id), None)
    if layer is None:
        raise HTTPException(404, f"未知漏斗层: {layer_id}")
    return {"layer": layer.model_dump(mode="json"), "final_candidates_count": len(result.final_candidates)}


@router.post("/funnel/layers/{layer_id}/rerun-downstream")
async def rerun_downstream(layer_id: str, date: str | None = None):
    """下游全跑（S023 F4）：用户确认后往下重跑，返回全部层。"""
    result = await asyncio.to_thread(funnel_mod.run_funnel, "all", date or _today(), _store["config"])
    idx = next((i for i, l in enumerate(result.layers) if l.layer_id == layer_id), None)
    if idx is None:
        raise HTTPException(404, f"未知漏斗层: {layer_id}")
    return {"layers": [l.model_dump(mode="json") for l in result.layers[idx:]], "final_candidates": [c.model_dump(mode="json") for c in result.final_candidates]}
