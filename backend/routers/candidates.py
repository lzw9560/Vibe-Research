# -*- coding: utf-8 -*-
"""候选池漏斗 + 诊断卡路由（S002 阶段 E）。

挂 /api/workflow/candidates/* 与 /api/workflow/funnel/*。
合规：仅客观数据，无方向/参考价位（AC10）。VR_API_KEY 由 app 中间件统一鉴权。
"""

from __future__ import annotations

import asyncio
from datetime import date as _date
from typing import Any

from fastapi import APIRouter, Query

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
