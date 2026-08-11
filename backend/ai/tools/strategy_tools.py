"""S058：战法卡查询工具。

读 strategies/cards/<code>.md 返回文本；AI 三出口（chat/MCP/cli_runtime）透明复用。
code 不存在返 error dict（registry 惯例）；别名检索（aliases）。
"""
from __future__ import annotations

from pathlib import Path

from .registry import register_tool

_CARDS_DIR = Path(__file__).resolve().parent.parent.parent / "strategies" / "cards"


def _resolve_strategy_code(code_or_alias: str) -> str | None:
    """按 code 或别名解析出战法 code。"""
    from limitup_strategy import STRATEGY_REGISTRY

    s_lower = str(code_or_alias).strip().lower()
    for s in STRATEGY_REGISTRY:
        if s["code"].lower() == s_lower:
            return s["code"]
        for a in s.get("aliases", []):
            if a.lower() == s_lower:
                return s["code"]
    return None


@register_tool(
    "query_strategy_card",
    "查战法卡片：适用天气/核心逻辑/入场条件/退出参数/风险点。按战法 code 或别名检索。"
    "返回 Markdown 文本，供 AI 解读战法逻辑。",
    params={"code": {"description": "战法 code 或别名（如 first_plate / 首板 / consecutive_relay / 连板）"}},
)
def query_strategy_card(code: str) -> dict:
    resolved = _resolve_strategy_code(str(code))
    if not resolved:
        return {"error": f"未知战法 code 或别名：{code}"}
    card_path = _CARDS_DIR / f"{resolved}.md"
    if not card_path.exists():
        return {"error": f"战法卡片文件缺失：{resolved}.md"}
    return {
        "code": resolved,
        "card": card_path.read_text(encoding="utf-8"),
    }
