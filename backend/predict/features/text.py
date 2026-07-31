"""Text feature specs — S018 text feature slice.

LLM-based sentiment and event-type extraction from newsradar news.
All parsing is pure computation (no side effects, no network).
"""

from __future__ import annotations

import json
import re

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


def parse_llm_emotion(response: str) -> dict:
    """Parse LLM response JSON into structured emotion data.

    Tolerates markdown fences, clamps scores to [-1, 1],
    and maps unknown event types to "其他".
    """
    if not isinstance(response, str) or not response.strip():
        return {"emotion_score": None, "event_type": None}

    try:
        data = json.loads(_strip_markdown(response.strip()))
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


def fetch_news_emotion(news_text: str) -> dict:
    """Fetch news emotion via LLM (STUB — does not call LLM).

    TODO: 走 chat LLM 出口（VR_LLM_*），S008/S017 接 live；
    现仅 stub 返 parse_llm_emotion 的空结果。

    Args:
        news_text: The news text to analyze.

    Returns:
        dict with ``emotion_score`` and ``event_type`` both None.
    """
    return {"emotion_score": None, "event_type": None}
