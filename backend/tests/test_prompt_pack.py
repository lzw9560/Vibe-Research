"""prompt_pack 单测（P4-T2a：PromptPack dataclass + RESEARCH_PACK，砍 focus/deepdive/verdict）。"""
from __future__ import annotations

import dataclasses

import pytest

import prompt_pack
from prompt_pack import RESEARCH_PACK, PromptPack, load_pack


def test_research_pack_fields():
    assert RESEARCH_PACK.name == "research"
    for f in ("analyst_style", "analyst_len", "judge_requirements", "chat_guidance"):
        v = getattr(RESEARCH_PACK, f)
        assert isinstance(v, str) and v, f"{f} 应为非空 str"


def test_prompt_pack_frozen():
    with pytest.raises(Exception):
        RESEARCH_PACK.name = "other"  # type: ignore[misc]


def test_prompt_pack_chat_guidance_default():
    p = PromptPack(name="x", analyst_style="s", analyst_len="l", judge_requirements="j")
    # S010 放宽口径：可给方向性研判+操作建议，但不承诺确定性 + 挂风险提醒
    assert "方向性研判" in p.chat_guidance
    assert "操作建议" in p.chat_guidance
    assert "确定性" in p.chat_guidance  # 不承诺确定性
    assert "风险" in p.chat_guidance  # 挂风险提醒


def test_prompt_pack_custom_chat_guidance():
    p = PromptPack(name="c", analyst_style="a", analyst_len="b", judge_requirements="j", chat_guidance="g")
    assert p.chat_guidance == "g"


def test_prompt_pack_only_text_fields():
    """砍 focus_model/focus_skeleton/render_focus + deepdive/verdict 三件套。"""
    fields = {f.name for f in dataclasses.fields(PromptPack)}
    assert fields == {"name", "analyst_style", "analyst_len", "judge_requirements", "chat_guidance"}
    for dropped in ("focus_model", "focus_skeleton", "render_focus",
                    "deepdive_style", "deepdive_requirements",
                    "verdict_model", "verdict_skeleton", "render_verdict"):
        assert dropped not in fields


def test_research_pack_no_pydantic_deps():
    """PromptPack 不依赖 pydantic（砍了 focus_model/verdict_model: type[BaseModel]）。"""
    assert "pydantic" not in dir(prompt_pack), "不应 import pydantic"


# ===== P4-T4a/b：本地包加载（load_pack + 回落）=====


def test_load_pack_no_local(monkeypatch):
    monkeypatch.setattr(prompt_pack, "_local_pack_path", lambda: None)
    assert load_pack() is RESEARCH_PACK


def test_load_pack_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(prompt_pack, "_local_pack_path", lambda: tmp_path / "nope.py")
    assert load_pack() is RESEARCH_PACK


def test_load_pack_valid_local(monkeypatch, tmp_path):
    p = tmp_path / "prompts_local.py"
    p.write_text(
        "from prompt_pack import PromptPack\n"
        "PACK = PromptPack(name='custom', analyst_style='cs', analyst_len='cl', judge_requirements='cj')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prompt_pack, "_local_pack_path", lambda: p)
    pack = load_pack()
    assert pack.name == "custom"
    assert pack.analyst_style == "cs"


def test_load_pack_syntax_error(monkeypatch, tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("this is not valid python !!!", encoding="utf-8")
    monkeypatch.setattr(prompt_pack, "_local_pack_path", lambda: p)
    assert load_pack() is RESEARCH_PACK


def test_load_pack_not_promptpack(monkeypatch, tmp_path):
    p = tmp_path / "wrong.py"
    p.write_text("PACK = 'not a pack'", encoding="utf-8")
    monkeypatch.setattr(prompt_pack, "_local_pack_path", lambda: p)
    assert load_pack() is RESEARCH_PACK


def test_pack_module_var_is_research_by_default():
    """无本地包时，模块级 PACK 是 RESEARCH_PACK。"""
    assert isinstance(prompt_pack.PACK, PromptPack)
    assert prompt_pack.PACK.name == "research"
