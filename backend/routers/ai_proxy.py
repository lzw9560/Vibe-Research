"""AI 代理路由 —— 服务端持有 LLM API Key，前端无需自带 key。

将前端 LLM 请求转发到上游 OpenAI 兼容端点；API Key / Base URL / 默认 model
全部从后端环境变量读取（VR_LLM_BASE_URL / VR_LLM_API_KEY / VR_LLM_MODEL），
不进请求体、不落前端 localStorage。

鉴权：复用 app.py 的全局 `_require_api_key` 中间件——设了 VR_API_KEY 即要求
`Authorization: Bearer <key>`，覆盖所有 /api/*（含本路由 /api/ai/proxy），
故此处不再重复校验。

合规：本路由只做透传，不臆造数据、不给研判；研判由上游模型与用户 prompt 决定。
"""

from __future__ import annotations

import json

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import chat as chat_layer

router = APIRouter(prefix="/api/ai", tags=["ai"])

_UPSTREAM_TIMEOUT = 30  # 秒


class ProxyReq(BaseModel):
    # provider 当前为前向兼容字段：环境变量只配单一端点，故不做路由分支。
    provider: str = ""
    model: str = ""        # 留空则用 VR_LLM_MODEL 兜底
    messages: list[dict]
    stream: bool = False


def _resolve_base(base: str) -> str:
    """与 chat.py 一致：未带版本段则补 /v1。"""
    base = (base or "").rstrip("/")
    if not base.endswith(("/v1", "/v3", "/api/v3")):
        base = base + "/v1"
    return base


@router.post("/proxy")
def proxy(req: ProxyReq):
    """转发 LLM 请求到上游，key 服务端注入。

    - 非流式：返回上游 JSON。
    - 流式：原样转发上游 SSE（text/event-stream）字节流。
    连接级 / 非 200 错误 → HTTPException；请求体无 apiKey。
    """
    env_cfg = chat_layer._get_env_llm_config()
    base_url = env_cfg.get("baseURL", "")
    api_key = env_cfg.get("apiKey", "")
    default_model = env_cfg.get("model", "")

    if not base_url or not api_key:
        raise HTTPException(
            500,
            "后端未配置 LLM 环境变量（VR_LLM_BASE_URL / VR_LLM_API_KEY），无法代理。",
        )

    model = req.model or default_model
    if not model:
        raise HTTPException(400, "未指定 model，且后端未配置 VR_LLM_MODEL 兜底。")

    # SSRF 防护：复用 chat 层校验（挡云元数据 / 公网姿态禁内网）
    chat_layer._check_base_url(base_url)
    base = _resolve_base(base_url)
    url = f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": req.messages,
        "stream": req.stream,
    }

    if not req.stream:
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=_UPSTREAM_TIMEOUT)
        except requests.RequestException as e:
            raise HTTPException(502, f"上游请求失败：{e}")
        if r.status_code != 200:
            raise HTTPException(
                r.status_code,
                f"上游返回 HTTP {r.status_code}: {r.text[:500]}",
            )
        try:
            return JSONResponse(r.json())
        except ValueError:
            # 上游 200 但非 JSON：原样回吐文本，避免 500 误导
            return JSONResponse({"detail": "上游返回非 JSON", "text": r.text[:1000]}, status_code=502)

    # 流式：先建连接，连接级 / 非 200 错误可在返回前走 HTTPException
    try:
        upstream = requests.post(
            url, headers=headers, json=payload, timeout=_UPSTREAM_TIMEOUT, stream=True
        )
    except requests.RequestException as e:
        raise HTTPException(502, f"上游请求失败：{e}")
    if upstream.status_code != 200:
        body = upstream.text[:500]
        upstream.close()
        raise HTTPException(
            upstream.status_code,
            f"上游返回 HTTP {upstream.status_code}: {body}",
        )

    def gen():
        # 中途断流：iter_content 自然结束，连接在 finally 关闭
        try:
            for chunk in upstream.iter_content(chunk_size=None):
                if chunk:
                    yield chunk
        except requests.RequestException:
            # 中途网络异常：发一个错误 SSE 事件再结束
            yield b"data: " + json.dumps(
                {"error": "上游连接中断"}, ensure_ascii=False
            ).encode("utf-8") + b"\n\n"
        finally:
            upstream.close()

    return StreamingResponse(gen(), media_type="text/event-stream")


__all__ = ["router"]
