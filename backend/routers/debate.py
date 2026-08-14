# -*- coding: utf-8 -*-
"""S020/main：多空辩论 + 反思审计路由（/api/debate + /api/reflect）。

main 分支的内联端点，develop 合并后拆为模块化路由（保 chat.py 的 LLM 校验口径）。
- /api/debate：后端拉客观事实底稿 → 多方/空方/中立主持依次发言，流式 NDJSON。
  不产出买卖结论，终点是分歧点 + 验证清单。
- /api/reflect：对一段已写好的分析做推理审计（数据支撑/最脆弱一环/验证清单），流式 NDJSON。

LLM 配置校验口径与 routers/chat.py 一致（API 接入需 baseURL+apiKey+model，
CLI 接入需检测本机命令；预设接入走 presetId 补全）。
"""
from __future__ import annotations

import json
from typing import Any, Dict

import cli_runtime
import debate as debate_layer
import reflection as reflect_layer
import llm_presets
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(tags=["debate"])


class LLMConfig(BaseModel):
    provider: str = ""
    baseURL: str = ""
    apiKey: str = ""
    model: str
    presetId: str = ""


class DebateReq(BaseModel):
    code: str
    rounds: int = 1
    llm: LLMConfig


class ReflectReq(BaseModel):
    source: str
    title: str = ""
    llm: LLMConfig


def _resolve_llm(cfg: dict) -> None:
    """LLM 配置校验（口径同 main 的 ``_check_llm``，**严格校验不 env fallback**）。

    与 routers/chat.py 的 /api/chat 不同：chat 用 env 兜底（develop 特性），
    debate/reflect 用 main 的严格校验——model/apiKey/baseURL 必填，
    缺则 400（main 测试兼容）。
    """
    if not cfg.get("model"):
        raise HTTPException(400, "缺少模型配置，请先在「接入 AI」里选择")
    preset_id = cfg.get("presetId", "")
    if preset_id:
        resolved = llm_presets.resolve_preset(preset_id)
        if not resolved:
            raise HTTPException(400, f"预设「{preset_id}」未配置或缺少 API key")
        cfg["baseURL"] = resolved["baseURL"]
        cfg["apiKey"] = resolved["apiKey"]
        if not cfg.get("model"):
            cfg["model"] = resolved["defaultModel"]
        return
    is_cli = cfg.get("provider", "").startswith("cli-")
    if is_cli:
        kind = cfg["provider"][4:]
        if not cli_runtime.detect_cli(kind):
            raise HTTPException(400, f"未检测到「{kind}」对应的本机命令。请先安装并登录该 CLI。")
    elif not cfg.get("apiKey") or not cfg.get("baseURL"):
        raise HTTPException(400, "缺少 Base URL 或 API Key，请先在「接入 AI」里填写")


def _ndjson(events_fn) -> StreamingResponse:
    """流式 NDJSON 包装：事件序列化为一行一 JSON，异常转 error 事件。"""
    def gen():
        try:
            for ev in events_fn():
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001 — 运行时错误以流内事件上报
            yield json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson")


@router.post("/api/debate")
def debate(req: DebateReq) -> StreamingResponse:
    """多空辩论：后端先拉客观事实底稿，多方/空方/中立主持依次发言，流式 NDJSON。

    刻意不产出买卖结论——终点是分歧点 + 验证清单，判断留给用户。
    """
    code = (req.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    cfg = req.llm.model_dump()
    _resolve_llm(cfg)
    rounds = 2 if req.rounds >= 2 else 1
    return _ndjson(lambda: debate_layer.run_debate_stream(cfg, code, rounds))


@router.post("/api/reflect")
def reflect(req: ReflectReq) -> StreamingResponse:
    """反思：对一段已写好的分析做推理审计（数据支撑/最脆弱一环/验证清单），流式 NDJSON。"""
    if not (req.source or "").strip():
        raise HTTPException(400, "source 不能为空")
    cfg = req.llm.model_dump()
    _resolve_llm(cfg)
    return _ndjson(lambda: reflect_layer.run_reflection_stream(cfg, req.source, req.title))
