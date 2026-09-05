"""chat PromptPack 接线单测（P4-T3c：PACK 字段注入 + S010 放宽不回归）。"""
from __future__ import annotations

import chat
from prompt_pack import PACK, RESEARCH_PACK


def test_system_prompt_contains_pack_fields():
    s = chat.SYSTEM_PROMPT.format(context="测试")
    assert "【分析风格" in s
    assert PACK.analyst_style in s
    assert PACK.analyst_len in s
    assert PACK.chat_guidance in s


def test_system_prompt_no_tools_contains_pack_fields():
    s = chat.SYSTEM_PROMPT_NO_TOOLS.format(context="测试")
    assert "【分析风格" in s
    assert PACK.analyst_style in s
    assert PACK.chat_guidance in s


def test_system_prompt_keeps_s010_relaxed():
    """S010 放宽口径保留（不回退）：可给方向性研判 + 操作建议。"""
    s = chat.SYSTEM_PROMPT.format(context="x")
    assert "方向性研判" in s
    assert "操作建议" in s
    # 工程底线保留：不承诺确定性 + 风险提醒
    assert "确定性" in s
    assert "风险" in s


def test_system_prompt_keeps_analysis_framework():
    """ANALYSIS_FRAMEWORK 五维框架保留（不被 PACK 替换）。"""
    s = chat.SYSTEM_PROMPT.format(context="x")
    assert "【投研分析框架】" in s
    assert "估值" in s and "资金面" in s  # 五维


def test_pack_is_research_by_default():
    """默认 PACK 是 RESEARCH_PACK（无本地包）。"""
    assert PACK is RESEARCH_PACK


def test_research_pack_aligned_s010():
    """RESEARCH_PACK.analyst_style/chat_guidance 对齐 S010 放宽（不含保守口径）。"""
    assert "方向性研判" in RESEARCH_PACK.analyst_style
    assert "操作建议" in RESEARCH_PACK.chat_guidance
    # 不含保守口径（不给买卖点位/不给参与倾向）——对齐 S010 放宽
    assert "不给买卖点位" not in RESEARCH_PACK.analyst_style
    assert "不给参与倾向" not in RESEARCH_PACK.chat_guidance
