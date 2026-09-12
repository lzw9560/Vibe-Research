"""S193/S196 技术分析信号工具——缺口 / MACD 背离 / RSI 超买超卖 regime（喂 AI 研判）。

FE-2（backlog）：classify_gap + ta_signals(MACD/RSI) 进 chat.TOOLS（声明式 registry，
自动同步 chat.run_chat TOOLS + mcp_server）。AI 问股时可查个股某日缺口/MACD/RSI regime。

合规（CLAUDE.md §1 弱合规）：工具返客观 regime + 置信度 payload（研究性判断原料），
方向性研判由 LLM 在 SYSTEM_PROMPT 约束下给出，工具不越权。三信号作 regime 判断不直接买卖
（spec S193/S196：缺口/MACD/RSI 是 regime 信号，喂 AI 综合研判 + 融合消融验）。
"""
from __future__ import annotations

from engine.gap_classifier import classify_gap
from engine.ta_signals import classify_macd_divergence, classify_rsi

from .registry import register_tool


@register_tool(
    "query_gap_regime",
    "查个股某日缺口 regime（普通/突破/持续/衰竭 + 方向 + 趋势启动/中继/反转/噪声 + 置信度 + 量比/回补/压力位）。"
    "S193：缺口作 regime 信号不直接买卖，喂 AI 综合研判。",
    params={
        "code": {"description": "6 位股票代码，如 '600519'"},
        "date": {"description": "YYYY-MM-DD 目标日"},
    },
)
def query_gap_regime(code: str, date: str) -> dict:
    return classify_gap(str(code), str(date))


@register_tool(
    "query_macd_divergence",
    "查个股 MACD 背离 regime（顶背离/底背离/无背离 + 方向 + 置信度）。"
    "S196：作 regime 信号不买卖，与缺口互补（趋势启动/反转确认）。",
    params={
        "code": {"description": "6 位股票代码"},
        "date": {"description": "YYYY-MM-DD 目标日"},
    },
)
def query_macd_divergence(code: str, date: str) -> dict:
    return classify_macd_divergence(str(code), str(date))


@register_tool(
    "query_rsi",
    "查个股 RSI 超买超卖 regime（超买/超卖/中性 + RSI 值 + 置信度）。"
    "S196：作 regime 信号不买卖，超买警惕回调/超卖警惕反弹。",
    params={
        "code": {"description": "6 位股票代码"},
        "date": {"description": "YYYY-MM-DD 目标日"},
    },
)
def query_rsi(code: str, date: str) -> dict:
    return classify_rsi(str(code), str(date))
