"""LLM 预设表：多供应商配置，key 存 .env（VR_LLM_PRESET_<ID>__API_KEY），元数据硬编码。
前端通过 GET /api/llm/presets 拿清单（不含 key），选预设后 POST /api/chat 传 presetId，
后端按 id 从 env 查 key 补全。key 不进前端 bundle。"""

from __future__ import annotations
import os

# 静态元数据（不含 key）
_PRESETS_META: list[dict] = [
    {
        "id": "local-v1",
        "name": "Local 192.168.2.156",
        "baseURL": "http://192.168.2.156/v1",
        "models": ["glm-5.2", "deepseek-v4-pro", "kimi-k2.6"],
        "defaultModel": "glm-5.2",
    },
    {
        "id": "agnes",
        "name": "Agnes",
        "baseURL": "https://apihub.agnes-ai.com/v1",
        "models": ["agnes-2.0-flash"],
        "defaultModel": "agnes-2.0-flash",
    },
    {
        "id": "omniroute",
        "name": "OmniRoute",
        "baseURL": "http://192.168.2.225:20128/v1",
        "models": ["auto/best-coding", "auto/best-coding-fast", "auto/best-fast", "auto/best-reasoning", "auto/best-vision", "auto/cheap", "auto/coding", "auto/fast"],
        "defaultModel": "auto/best-coding",
    },
    {
        "id": "bailian",
        "name": "Bailian 100.89.194.96",
        "baseURL": "http://100.89.194.96/v1",
        "models": ["deepseek-chat", "deepseek-v4-flash-0731", "deepseek-v4-pro", "glm-5", "glm-5.2", "kimi-k2.6", "qwen3-coder-plus", "qwen3.7-max", "qwen3.8-max"],
        "defaultModel": "deepseek-v4-pro",
    },
    {
        "id": "sense-nova",
        "name": "Sense Nova",
        "baseURL": "https://token.sensenova.cn/v1",
        "models": ["sensenova-6.7-flash-lite", "deepseek-v4-flash"],
        "defaultModel": "sensenova-6.7-flash-lite",
    },
    {
        "id": "stepfun",
        "name": "StepFun",
        "baseURL": "https://api.stepfun.com/step_plan/v1",
        "models": ["step-3.7-flash", "step-3.5-flash"],
        "defaultModel": "step-3.7-flash",
    },
]


def _preset_env_key(preset_id: str) -> str:
    """id → env key：local-v1 → VR_LLM_PRESET_LOCAL_V1__API_KEY；sense-nova → VR_LLM_PRESET_SENSENOVA__API_KEY。"""
    return f"VR_LLM_PRESET_{preset_id.upper().replace('-', '_')}__API_KEY"


def list_presets() -> list[dict]:
    """返回预设清单（不含 apiKey，只报 hasKey 布尔）。"""
    result = []
    for p in _PRESETS_META:
        key = os.getenv(_preset_env_key(p["id"]), "")
        result.append({**p, "hasKey": bool(key)})
    return result


def resolve_preset(preset_id: str) -> dict | None:
    """按 id 查预设完整配置（含 apiKey）。无 key 或无预设返回 None。"""
    meta = next((p for p in _PRESETS_META if p["id"] == preset_id), None)
    if not meta:
        return None
    key = os.getenv(_preset_env_key(preset_id), "")
    if not key:
        return None
    return {**meta, "apiKey": key}
