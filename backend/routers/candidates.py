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

# cache_response 定义在 app.py，但 candidates.py 模块级 import 会触发 circular import
# （app.py 加载时 include_router(candidates.router) ← candidates 还没加载完）。
# 生产环境 app.py 先加载无循环；测试环境直接 import routers.workflow 触发循环。
# 方案 B：try/except 回退，测试环境用 noop decorator（参照 topology.py:24-31 同款做法）。
try:
    from app import cache_response
except (ImportError, AttributeError):  # noqa: PLC0415 — 测试环境 app 未加载时回退
    def cache_response(ttl: int = 300):  # type: ignore[misc]
        """noop fallback：测试环境无缓存中间件，直接透传。"""
        def deco(func):
            return func
        return deco
from candidate_funnel import funnel as funnel_mod
from candidate_funnel.funnel_cache import (  # S087 R10：run_funnel 结果落库缓存
    list_cached_dates,
    load_funnel_result,
    save_funnel_result,
)
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
    """POST → 实跑 FunnelResult + 落缓存（S087 R10）。

    实跑 run_funnel（慢，全市场）+ save_funnel_result（落库供前端读缓存秒开）。
    前端 tab 默认读 GET /candidates/funnel/cache，"重新跑"按钮才调本端点。

    S149 修复：默认 date 从 _today() 改 last_trading_date_str()——周末/节假日/盘前
    （precompute 17:15 才写当日）"今日"无 zt 池→run 出 0 候选→前端空。改最近交易日
    后"重跑漏斗"默认重算最近交易日（有 zt 池→有候选）。显式传 date 不受影响。
    """
    from vr_paths import last_trading_date_str  # noqa: PLC0415

    d = date or last_trading_date_str()
    result = await asyncio.to_thread(funnel_mod.run_funnel, stage, d, _store["config"])
    await asyncio.to_thread(save_funnel_result, d, stage, result)
    return result


@router.get("/candidates/funnel/cache")
async def get_funnel_cache(date: str | None = None):
    """GET → 读缓存的 FunnelResult（秒开，S087 R10）。

    前端 tab 默认调此端点；缓存缺返 404，前端 fallback POST 实跑或显示空态。
    """
    from vr_paths import last_trading_date_str  # noqa: PLC0415

    d = date or last_trading_date_str()
    cached = load_funnel_result(d, "all")
    if cached is None:
        raise HTTPException(404, detail=f"无缓存 run_funnel 结果 date={d}，请点'重新跑'触发实跑")
    return cached


@router.get("/candidates/funnel/dates")
async def list_funnel_cache_dates():
    """GET → 有缓存的日期列表（前端日期选择器标注，S087 R10）。"""
    return {"dates": list_cached_dates()}


@router.get("/candidates")
@cache_response(ttl=60)
async def list_candidates(date: str | None = None):
    """GET → 最终候选 DiagnosisCard 列表（AC1）。
    H8 修复：优先读 SQLite 持久化缓存（POST /candidates/funnel 落库），
    缓存缺失时 fallback 实跑 run_funnel。"""
    from vr_paths import last_trading_date_str  # noqa: PLC0415
    d = date or last_trading_date_str()
    cached = load_funnel_result(d, "all")
    if cached is not None:
        return cached.final_candidates
    result = await asyncio.to_thread(funnel_mod.run_funnel, "all", d, _store["config"])
    return result.final_candidates


@router.get("/candidates/{code}/diagnosis")
@cache_response(ttl=60)
async def get_diagnosis(code: str, date: str | None = None):
    """GET → 单股 DiagnosisCard（AC3/AC4/AC6）。"""
    from vr_paths import last_trading_date_str  # noqa: PLC0415
    return await asyncio.to_thread(funnel_mod.diagnose, code, date or last_trading_date_str(), _store["config"])


@router.get("/funnel/layers")
@cache_response(ttl=60)
async def get_layers(run_id: str | None = None, date: str | None = None):
    """GET → 各层 FunnelLayer（AC1 每层可检视）。
    H8 修复：优先读 SQLite 持久化缓存，缓存缺失时 fallback 实跑。"""
    from vr_paths import last_trading_date_str  # noqa: PLC0415
    d = date or last_trading_date_str()
    cached = load_funnel_result(d, "all")
    if cached is not None:
        return cached.layers
    result = await asyncio.to_thread(funnel_mod.run_funnel, "all", d, _store["config"])
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
    from vr_paths import last_trading_date_str  # noqa: PLC0415
    result = await asyncio.to_thread(funnel_mod.run_funnel, "all", date or last_trading_date_str(), _store["config"])
    layer = next((l for l in result.layers if l.layer_id == layer_id), None)
    if layer is None:
        raise HTTPException(404, f"未知漏斗层: {layer_id}")
    return {"layer": layer.model_dump(mode="json"), "final_candidates_count": len(result.final_candidates)}


@router.post("/funnel/layers/{layer_id}/rerun-downstream")
async def rerun_downstream(layer_id: str, date: str | None = None):
    """下游全跑（S023 F4）：用户确认后往下重跑，返回全部层。"""
    from vr_paths import last_trading_date_str  # noqa: PLC0415
    result = await asyncio.to_thread(funnel_mod.run_funnel, "all", date or last_trading_date_str(), _store["config"])
    idx = next((i for i, l in enumerate(result.layers) if l.layer_id == layer_id), None)
    if idx is None:
        raise HTTPException(404, f"未知漏斗层: {layer_id}")
    return {"layers": [l.model_dump(mode="json") for l in result.layers[idx:]], "final_candidates": [c.model_dump(mode="json") for c in result.final_candidates]}
