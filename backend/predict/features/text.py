"""Text feature specs — S018 text feature slice.

LLM-based sentiment and event-type extraction from newsradar news.
All parsing is pure computation (no side effects, no network).
"""

from __future__ import annotations

import json
import os
import re

import requests

from predict.features.registry import FeatureSpec, Registry

# ── Module-level constants ────────────────────────────────────────

# 版本升级时须重算全量文本特征
LLM_MODEL_VERSION = "gpt-4o-mini-2024-07-18"

# 固定提示词模板（合规：只做客观情绪与事件标注，不做投资建议、不预测收益、不荐股）
NEWS_EMOTION_PROMPT = """你是一个财经新闻情绪与事件分析助手。你的任务是对给定新闻文本进行客观情绪与事件标注。

要求：
1. 分析新闻文本的情绪倾向，给出一个介于 -1 到 1 之间的情绪分数。
   - 1 表示极度正面/利好
   - -1 表示极度负面/利空
   - 0 表示中性/无情绪倾向
2. 判断新闻涉及的事件类型，从以下类别中选择：
   - 监管
   - 并购
   - 回购
   - 减持
   - 业绩预告
   - 其他

只做客观情绪与事件标注，不做投资建议、不预测收益、不荐股。

请严格以 JSON 格式输出，不要包含任何额外解释：
{"emotion_score": <float>, "event_type": "<事件类型>"}

新闻文本：
{news_text}
"""

# ── Module-level immutable spec declarations ────────────────────────

TEXT_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="news_emotion",
        source="newsradar",
        category="text",
        availability_offset=0,
        stage="s1",
        compliance_flag="ok",
        description="newsradar新闻LLM情绪分+事件类型，固定模型版本+提示词可复算",
    ),
)

# ── Event type whitelist ──────────────────────────────────────────

_EVENT_TYPES = {"监管", "并购", "回购", "减持", "业绩预告", "其他"}

# ── Registration ───────────────────────────────────────────────────


def register_text(registry: Registry) -> None:
    """Register all text FeatureSpecs into the given Registry.

    Raises:
        KeyError: If any feature name is already registered.
    """
    for spec in TEXT_SPECS:
        registry.register(spec)


# ── Pure computation (no side effects, no network) ──────────────


def _strip_markdown(text: str) -> str:
    """Strip markdown ```json fences from LLM response."""
    for pattern in (r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            return m.group(1)
    return text


def _extract_json_block(text: str) -> str | None:
    """Extract the first balanced {...} JSON object block from text.

    Handles nested braces and braces inside strings. Returns None if no
    balanced block is found. Used to tolerate LLM responses that embed the
    JSON object in surrounding prose.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_llm_emotion(response: str) -> dict:
    """Parse LLM response JSON into structured emotion data.

    Tolerates markdown fences and prose-embedded JSON blocks, clamps
    scores to [-1, 1], and maps unknown event types to "其他".
    """
    if not isinstance(response, str) or not response.strip():
        return {"emotion_score": None, "event_type": None}

    cleaned = _strip_markdown(response.strip())
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        block = _extract_json_block(cleaned)
        if block is None:
            return {"emotion_score": None, "event_type": None}
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            return {"emotion_score": None, "event_type": None}

    if not isinstance(data, dict):
        return {"emotion_score": None, "event_type": None}

    raw_score = data.get("emotion_score")
    if raw_score is None:
        return {"emotion_score": None, "event_type": None}
    try:
        score = max(-1.0, min(1.0, float(raw_score)))
    except (TypeError, ValueError):
        return {"emotion_score": None, "event_type": None}

    raw_event = data.get("event_type")
    event_type = raw_event if isinstance(raw_event, str) and raw_event in _EVENT_TYPES else "其他"

    return {"emotion_score": score, "event_type": event_type}


def validate_prompt_compliance(prompt: str) -> bool:
    """Check if a prompt contains prohibited compliance keywords.

    Returns True if the prompt is clean (no prohibited words found),
    False otherwise.

    Prohibited keywords: "建议买入", "建议卖出", "推荐", "保证收益", "代客决策"
    """
    if not isinstance(prompt, str):
        return False
    prohibited = {"建议买入", "建议卖出", "推荐", "保证收益", "代客决策"}
    for word in prohibited:
        if word in prompt:
            return False
    return True


# ── LLM wiring (env-configured, no chat.py import to avoid cycles) ──


def _env_llm_config() -> dict:
    """Read LLM config from env (same keys as chat.py's VR_LLM_*).

    Returns:
        dict with ``baseURL`` / ``apiKey`` / ``model``; missing keys
        default to empty strings.
    """
    return {
        "baseURL": os.environ.get("VR_LLM_BASE_URL", ""),
        "apiKey": os.environ.get("VR_LLM_API_KEY", ""),
        "model": os.environ.get("VR_LLM_MODEL", ""),
    }


def _llm_chat(cfg: dict, messages: list) -> dict:
    """Call an OpenAI-compatible /chat/completions endpoint.

    Mirrors chat.py's _call_llm (without function calling), so text.py
    does not import chat.py (avoids circular dependency).

    Raises:
        RuntimeError: If the endpoint returns a non-200 status.
    """
    base = cfg["baseURL"].rstrip("/")
    if not base.endswith(("/v1", "/v3", "/api/v3")):
        # 多数 OpenAI 兼容端点需要 /v1；已带版本段则不动。
        base = base + "/v1"
    payload = {"model": cfg["model"], "messages": messages, "temperature": 0.3}
    r = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['apiKey']}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    if r.status_code != 200:
        raise RuntimeError(f"模型接口 HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def fetch_news_emotion(news_text: str) -> dict:
    """Fetch news emotion via LLM.

    Calls an OpenAI-compatible endpoint configured through the VR_LLM_*
    environment variables. When any of VR_LLM_BASE_URL / VR_LLM_API_KEY /
    VR_LLM_MODEL is unset, degrades gracefully to an all-None result
    without making any network call.

    Args:
        news_text: The news text to analyze.

    Returns:
        dict with ``emotion_score`` (float in [-1, 1] or None) and
        ``event_type`` (whitelisted string, default "其他").

    Raises:
        RuntimeError: If the LLM endpoint returns a non-200 status.
    """
    if not isinstance(news_text, str) or not news_text.strip():
        return {"emotion_score": None, "event_type": None}

    cfg = _env_llm_config()
    if not (cfg["baseURL"] and cfg["apiKey"] and cfg["model"]):
        return {"emotion_score": None, "event_type": None}

    messages = [
        {"role": "system", "content": "你是财经新闻情绪与事件标注助手，只做客观标注。"},
        {"role": "user", "content": NEWS_EMOTION_PROMPT.replace("{news_text}", news_text)},
    ]
    data = _llm_chat(cfg, messages)
    content = data["choices"][0]["message"].get("content") or ""
    return parse_llm_emotion(content)
