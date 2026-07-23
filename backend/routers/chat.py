"""
Chat router.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json
from typing import Any, Dict

import chat as chat_layer
import cli_runtime

router = APIRouter(tags=["chat"])


class LLMConfig(BaseModel):
    provider: str = ""       # cli-* = 订阅接入（调本机 CLI）；其余 = API 接入
    baseURL: str = ""        # 订阅接入时留空
    apiKey: str = ""         # 订阅接入时留空
    model: str


class ChatReq(BaseModel):
    messages: list[dict]
    context: str = ""
    llm: LLMConfig


@router.post("/api/chat")
def chat(req: ChatReq) -> StreamingResponse:
    """系统 AI 对话，**流式** NDJSON（每行一个事件 {type: tool|delta|done|error}）。

    - API 接入：OpenAI 兼容 function-calling，边流答案边推工具调用事件。
    - 订阅接入（provider=cli-*）：调本机已登录的 CLI，stdout 边出边流（数据靠 context）。
    配置错误（缺 key / 未装 CLI）走 HTTP 400；运行时错误走流内 error 事件。用户配置随请求传入，后端不持久化。
    """
    if not req.messages:
        raise HTTPException(400, "messages 不能为空")

    # 允许空 LLM 配置走 OmniRoute 兜底
    is_omni_fallback = not req.llm.model
    if not is_omni_fallback:
        is_cli = req.llm.provider.startswith("cli-")
        if is_cli:
            kind = req.llm.provider[4:]
            if not cli_runtime.detect_cli(kind):
                raise HTTPException(400, f"未检测到「{kind}」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。")
        elif not req.llm.apiKey or not req.llm.baseURL:
            raise HTTPException(400, "缺少 Base URL 或 API Key，请先在「接入 AI」里填写")

    cfg = req.llm.model_dump() if not is_omni_fallback else {}
    cfg["use_omniroute"] = True  # 始终启用 OmniRoute 兜底

    def gen():
        try:
            events = (chat_layer.run_chat_cli_stream if is_cli else chat_layer.run_chat_stream)(cfg, req.messages, req.context)
            for ev in events:
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001 — 运行时错误以流内事件上报，不中断连接
            yield json.dumps({"type": "error", "message": f"对话失败：{e}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


__all__ = ["router"]
