"""Tests for backend/predict/features/text.py — S018 text feature specs.

TDD: (a)-(h) covering FeatureSpec construction, registration, look-ahead guard,
LLM constants, prompt compliance, LLM response parsing, and the stub fetch.

All tests are offline (no network calls).
"""

import pytest


# ── (a) FeatureSpec 构造合法 ──────────────────────────────────────


def test_text_specs_valid():
    """TEXT_SPECS 构造合法，source/category/stage/compliance_flag 正确。"""
    from predict.features.text import TEXT_SPECS

    assert len(TEXT_SPECS) == 1
    spec = TEXT_SPECS[0]
    assert spec.name == "news_emotion"
    assert spec.source == "newsradar"
    assert spec.category == "text"
    assert spec.availability_offset == 0
    assert spec.stage == "s1"
    assert spec.compliance_flag == "ok"
    assert "newsradar" in spec.description
    assert "LLM" in spec.description


# ── (b) register_text 注册成功，get_by_name 能取回 ──────────────


def test_register_text_registers_one():
    """register_text 把 1 个 spec 注册进新 Registry 实例。"""
    from predict.features.text import register_text, TEXT_SPECS
    from predict.features.registry import Registry

    registry = Registry()
    register_text(registry)

    for spec in TEXT_SPECS:
        assert registry.get_by_name(spec.name) is spec


# ── (c) 重复注册同名 raise KeyError ─────────────────────────────


def test_register_text_duplicate_raises():
    """重复注册同名 feature 时 Registry 抛 KeyError。"""
    from predict.features.text import register_text
    from predict.features.registry import Registry

    registry = Registry()
    register_text(registry)
    with pytest.raises(KeyError, match="already registered"):
        register_text(registry)


# ── (d) list_for_stage("s1") 含 news_emotion ──────────────────────


def test_list_for_stage_s1_includes_news_emotion():
    """list_for_stage('s1') 包含 news_emotion 特征。"""
    from predict.features.text import register_text
    from predict.features.registry import Registry

    registry = Registry()
    register_text(registry)
    s1_names = {s.name for s in registry.list_for_stage("s1")}
    assert "news_emotion" in s1_names


def test_list_for_stage_s1_excludes_when_stage_later():
    """如果 stage 晚于 s1，list_for_stage('s1') 应排除（本模块 stage='s1' 所以应包含）。"""
    from predict.features.text import register_text
    from predict.features.registry import Registry

    registry = Registry()
    register_text(registry)
    s1_names = {s.name for s in registry.list_for_stage("s1")}
    assert "news_emotion" in s1_names


# ── (e) LLM_MODEL_VERSION / NEWS_EMOTION_PROMPT 是模块常量 ──────


def test_llm_model_version_is_non_empty_string():
    """LLM_MODEL_VERSION 是非空字符串常量。"""
    from predict.features.text import LLM_MODEL_VERSION

    assert isinstance(LLM_MODEL_VERSION, str)
    assert LLM_MODEL_VERSION
    assert "2024" in LLM_MODEL_VERSION


def test_news_emotion_prompt_is_non_empty_string():
    """NEWS_EMOTION_PROMPT 是非空字符串常量。"""
    from predict.features.text import NEWS_EMOTION_PROMPT

    assert isinstance(NEWS_EMOTION_PROMPT, str)
    assert NEWS_EMOTION_PROMPT
    assert "emotion_score" in NEWS_EMOTION_PROMPT


# ── (f) 合规核心：validate_prompt_compliance ───────────────────


def test_validate_prompt_compliance_true_for_valid_prompt():
    """NEWS_EMOTION_PROMPT 通过合规检查（无违禁词）。"""
    from predict.features.text import validate_prompt_compliance, NEWS_EMOTION_PROMPT

    assert validate_prompt_compliance(NEWS_EMOTION_PROMPT) is True


def test_validate_prompt_compliance_false_for_suggest_buy():
    """含'建议买入'的假提示词返 False。"""
    from predict.features.text import validate_prompt_compliance

    fake_prompt = "你是一个投资顾问，建议买入这只股票。"
    assert validate_prompt_compliance(fake_prompt) is False


def test_validate_prompt_compliance_false_for_suggest_sell():
    """含'建议卖出'的假提示词返 False。"""
    from predict.features.text import validate_prompt_compliance

    fake_prompt = "建议卖出，避免亏损。"
    assert validate_prompt_compliance(fake_prompt) is False


def test_validate_prompt_compliance_false_for_recommend():
    """含'推荐'的假提示词返 False。"""
    from predict.features.text import validate_prompt_compliance

    fake_prompt = "我推荐你关注这只股票。"
    assert validate_prompt_compliance(fake_prompt) is False


def test_validate_prompt_compliance_false_for_guarantee():
    """含'保证收益'的假提示词返 False。"""
    from predict.features.text import validate_prompt_compliance

    fake_prompt = "保证收益，稳赚不赔。"
    assert validate_prompt_compliance(fake_prompt) is False


def test_validate_prompt_compliance_false_for_delegate():
    """含'代客决策'的假提示词返 False。"""
    from predict.features.text import validate_prompt_compliance

    fake_prompt = "我可以代客决策，帮你买卖。"
    assert validate_prompt_compliance(fake_prompt) is False


# ── (g) parse_llm_emotion 纯函数 ────────────────────────────────


def test_parse_llm_emotion_normal_json():
    """正常 JSON 返回正确 emotion_score 和 event_type。"""
    from predict.features.text import parse_llm_emotion

    response = '{"emotion_score": 0.5, "event_type": "并购"}'
    result = parse_llm_emotion(response)
    assert result == {"emotion_score": 0.5, "event_type": "并购"}


def test_parse_llm_emotion_markdown_fenced():
    """Markdown ```json 围栏 JSON → 正确解析。"""
    from predict.features.text import parse_llm_emotion

    response = '```json\n{"emotion_score": -0.8, "event_type": "监管"}\n```'
    result = parse_llm_emotion(response)
    assert result == {"emotion_score": -0.8, "event_type": "监管"}


def test_parse_llm_emotion_score_clamp_high():
    """emotion_score 越界 >1 → clamp 到 1。"""
    from predict.features.text import parse_llm_emotion

    response = '{"emotion_score": 2.5, "event_type": "回购"}'
    result = parse_llm_emotion(response)
    assert result["emotion_score"] == 1.0
    assert result["event_type"] == "回购"


def test_parse_llm_emotion_score_clamp_low():
    """emotion_score 越界 <-1 → clamp 到 -1。"""
    from predict.features.text import parse_llm_emotion

    response = '{"emotion_score": -3.0, "event_type": "减持"}'
    result = parse_llm_emotion(response)
    assert result["emotion_score"] == -1.0
    assert result["event_type"] == "减持"


def test_parse_llm_emotion_invalid_event_type():
    """event_type 不在取值集 → '其他'。"""
    from predict.features.text import parse_llm_emotion

    response = '{"emotion_score": 0.0, "event_type": "不明事件"}'
    result = parse_llm_emotion(response)
    assert result["emotion_score"] == 0.0
    assert result["event_type"] == "其他"


def test_parse_llm_emotion_parse_failure_returns_none():
    """解析失败 → 全 None。"""
    from predict.features.text import parse_llm_emotion

    response = "这不是 JSON"
    result = parse_llm_emotion(response)
    assert result == {"emotion_score": None, "event_type": None}


def test_parse_llm_emotion_missing_keys_returns_none():
    """JSON 缺少必要字段 → 全 None。"""
    from predict.features.text import parse_llm_emotion

    response = '{"other": "value"}'
    result = parse_llm_emotion(response)
    assert result == {"emotion_score": None, "event_type": None}


def test_parse_llm_emotion_empty_string():
    """空字符串 → 全 None。"""
    from predict.features.text import parse_llm_emotion

    result = parse_llm_emotion("")
    assert result == {"emotion_score": None, "event_type": None}


# ── (h) fetch_news_emotion stub 不触网，返全 None ──────────────


def test_fetch_news_emotion_stub_returns_none():
    """fetch_news_emotion stub 不触网，返回全 None。"""
    from predict.features.text import fetch_news_emotion

    result = fetch_news_emotion("某公司业绩大幅增长")
    assert result == {"emotion_score": None, "event_type": None}
