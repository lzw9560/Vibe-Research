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
import llm_presets

router = APIRouter(tags=["chat"])


class LLMConfig(BaseModel):
    provider: str = ""       # cli-* = 订阅接入（调本机 CLI）；其余 = API 接入
    baseURL: str = ""        # 订阅接入时留空
    apiKey: str = ""         # 订阅接入时留空
    model: str
    presetId: str = ""       # 选了预设时非空，后端按 id 从 env 查 key 补全


class ChatReq(BaseModel):
    messages: list[dict]
    context: str = ""
    llm: LLMConfig


@router.get("/api/settings/llm-env-status")
def get_llm_env_status() -> Dict[str, Any]:
    """返回后端 LLM 环境变量配置状态（不暴露敏感值）。"""
    env_cfg = chat_layer._get_env_llm_config()
    return {
        "has_env_base_url": bool(env_cfg.get("baseURL")),
        "has_env_api_key": bool(env_cfg.get("apiKey")),
        "has_env_model": bool(env_cfg.get("model")),
    }


@router.get("/api/llm/presets")
def get_llm_presets() -> Dict[str, Any]:
    """返回后端已配置的 LLM 预设清单（不含 apiKey，只报 hasKey）。
    前端 Settings 页用它渲染预设下拉，用户选预设后 chat 传 presetId，
    后端按 id 从 .env 查 key 补全，key 不进前端。"""
    return {"presets": llm_presets.list_presets()}


@router.post("/api/chat")
def chat(req: ChatReq) -> StreamingResponse:
    """系统 AI 对话，**流式** NDJSON（每行一个事件 {type: tool|delta|done|error}）。

    - API 接入：OpenAI 兼容 function-calling，边流答案边推工具调用事件。
    - 订阅接入（provider=cli-*）：调本机已登录的 CLI，stdout 边出边流（数据靠 context）。
    配置错误（缺 key / 未装 CLI）走 HTTP 400；运行时错误走流内 error 事件。用户配置随请求传入，后端不持久化。
    """
    if not req.messages:
        raise HTTPException(400, "messages 不能为空")

    cfg = req.llm.model_dump()
    # 预设接入：前端传 presetId，后端从 .env 查 key 补全（key 不进前端 bundle）
    preset_id = cfg.get("presetId", "")
    if preset_id:
        resolved = llm_presets.resolve_preset(preset_id)
        if not resolved:
            raise HTTPException(400, f"预设「{preset_id}」未配置或缺少 API key，请检查后端 .env 的 VR_LLM_PRESET_{preset_id.upper().replace('-', '_')}__API_KEY")
        # 预设补全：baseURL/apiKey 用预设的，model 允许前端覆盖（默认用预设 defaultModel）
        cfg["baseURL"] = resolved["baseURL"]
        cfg["apiKey"] = resolved["apiKey"]
        if not cfg.get("model"):
            cfg["model"] = resolved["defaultModel"]
    is_cli = cfg.get("provider", "").startswith("cli-")
    if is_cli:
        kind = cfg["provider"][4:]
        if not cli_runtime.detect_cli(kind):
            raise HTTPException(400, f"未检测到「{kind}」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。")
    else:
        if not cfg.get("apiKey") or not cfg.get("baseURL"):
            env_cfg = chat_layer._get_env_llm_config()
            if not env_cfg.get("apiKey") or not env_cfg.get("baseURL"):
                raise HTTPException(400, "缺少 Base URL 或 API Key，请先在「接入 AI」里填写，或配置后端环境变量 VR_LLM_BASE_URL / VR_LLM_API_KEY")

    # 后端环境变量兜底：前端未传的字段用环境变量补全
    env_cfg = chat_layer._get_env_llm_config()
    for k in ("baseURL", "apiKey", "model"):
        if not cfg.get(k) and env_cfg.get(k):
            cfg[k] = env_cfg[k]

    def gen():
        try:
            events = (chat_layer.run_chat_cli_stream if is_cli else chat_layer.run_chat_stream)(cfg, req.messages, req.context)
            for ev in events:
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001 — 运行时错误以流内事件上报，不中断连接
            yield json.dumps({"type": "error", "message": f"对话失败：{e}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


__all__ = ["router"]
