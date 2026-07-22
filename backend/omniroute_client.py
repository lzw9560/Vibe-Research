"""OmniRoute 托底模型通道。

可选模块：仅在用户启用且 OmniRoute 本地服务可达时工作。
不引入任何额外依赖——复用 chat.py 已有的 requests。

用法：
  - 设置环境变量 VR_OMNIRoute_ENABLED=true 启用
  - 设置 VR_OMNIRoute_MODEL=auto（或具体模型 ID）
  - 设置 VR_OMNIRoute_BASE_URL=http://localhost:20128（可选，默认 localhost:20128）
"""

from __future__ import annotations

import os
import socket
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

OMNIRoute_ENABLED = os.getenv("VR_OMNIRoute_ENABLED", "false").lower() == "true"
OMNIRoute_MODEL = os.getenv("VR_OMNIRoute_MODEL", "auto")
DEFAULT_OMNIRoute_URL = os.getenv("VR_OMNIRoute_BASE_URL", "http://localhost:20128")


def _is_omniroute_available(timeout: float = 1.0) -> bool:
    """检查 OmniRoute 本地服务是否可达。"""
    parsed = urlparse(DEFAULT_OMNIRoute_URL)
    host = parsed.hostname or "localhost"
    port = parsed.port or 20128
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def call_via_omniroute(
    messages: List[Dict[str, Any]],
    model: str = "auto",
    temperature: float = 0.3,
    use_tools: bool = False,
    stream: bool = False,
    tools: Optional[List[Dict]] = None,
) -> Optional[Dict[str, Any]]:
    """通过 OmniRoute 调用模型。

    返回格式与 chat.py 的 _call_llm 一致：
    {"choices": [{"message": {"content": "...", "tool_calls": [...]}}]}

    如果 OmniRoute 不可达，返回 None。
    """
    import requests

    if not OMNIRoute_ENABLED or not _is_omniroute_available():
        return None

    base = DEFAULT_OMNIRoute_URL.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if use_tools and tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    endpoint = f"{base}/chat/completions"
    try:
        r = requests.post(endpoint, json=payload, timeout=120, stream=stream)
        if r.status_code != 200:
            return None
        if stream:
            return r  # caller 负责解析 SSE
        return r.json()
    except (requests.RequestException, ValueError):
        return None
