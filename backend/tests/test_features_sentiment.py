"""Tests for backend/predict/features/sentiment.py — S018 sentiment feature specs.

TDD: (a)-(g) covering FeatureSpec construction, registration, look-ahead guard,
and the pure computation functions (aggregate_emotion, sector_divergence_score).

All tests are offline (no network calls).
"""

import pytest


# ── (a) 2 个 FeatureSpec 构造合法 ───────────────────────────────────


def test_sentiment_specs_valid():
    """2 个 FeatureSpec 构造合法，compliance_flag 校验通过。"""
    from predict.features.sentiment import SENTIMENT_SPECS

    assert len(SENTIMENT_SPECS) == 2
    names = {s.name for s in SENTIMENT_SPECS}
    assert names == {"limitup_emotion", "sector_divergence"}

    spec_by_name = {s.name: s for s in SENTIMENT_SPECS}

    limitup = spec_by_name["limitup_emotion"]
    assert limitup.source == "limitup_sti"
    assert limitup.category == "sentiment"
    assert limitup.availability_offset == 0
    assert limitup.stage == "s1"
    assert limitup.compliance_flag == "aggregate_only"
    assert limitup.description  # non-empty

    sector = spec_by_name["sector_divergence"]
    assert sector.source == "astock.em_get"
    assert sector.category == "sentiment"
    assert sector.availability_offset == 0
    assert sector.stage == "s1"
    assert sector.compliance_flag == "ok"
    assert sector.description  # non-empty


# ── (b) register_sentiment 注册全 2 个；get_by_name 取回 ─────────────


def test_register_sentiment_registers_all_two():
    """register_sentiment 把 2 个 spec 注册进新 Registry 实例。"""
    from predict.features.sentiment import register_sentiment, SENTIMENT_SPECS
    from predict.features.registry import Registry

    registry = Registry()
    register_sentiment(registry)

    for spec in SENTIMENT_SPECS:
        assert registry.get_by_name(spec.name) is spec


# ── (c) 重复注册同名 raise KeyError ─────────────────────────────────


def test_register_sentiment_duplicate_raises():
    """重复注册同名 feature 时 Registry 抛 KeyError。"""
    from predict.features.sentiment import register_sentiment
    from predict.features.registry import Registry

    registry = Registry()
    register_sentiment(registry)
    with pytest.raises(KeyError, match="already registered"):
        register_sentiment(registry)


# ── (d) list_for_stage look-ahead 防护 ──────────────────────────────


def test_list_for_stage_s1_includes_both():
    """list_for_stage('s1') 包含全部 2 个 sentiment 特征。"""
    from predict.features.sentiment import register_sentiment
    from predict.features.registry import Registry

    registry = Registry()
    register_sentiment(registry)
    s1_names = {s.name for s in registry.list_for_stage("s1")}
    assert s1_names == {"limitup_emotion", "sector_divergence"}


def test_list_for_stage_s0_invalid_raises():
    """list_for_stage('s0') 抛出 ValueError（无效 stage）。"""
    from predict.features.sentiment import register_sentiment
    from predict.features.registry import Registry

    registry = Registry()
    register_sentiment(registry)
    with pytest.raises(ValueError, match="stage must be one of"):
        registry.list_for_stage("s0")


# ── (e) aggregate_emotion 正常：只取聚合数值，不含个股字段 ──────────


def test_aggregate_emotion_normal():
    """给定含聚合字段 + 假个股字段的 emotion dict，输出只保留聚合数值 key。"""
    from predict.features.sentiment import aggregate_emotion

    mock_emotion = {
        "date": "2026-07-29",
        "zt_count": 45,
        "dt_count": 3,
        "zb_count": 8,
        "max_boards": 7,
        "lianban_count": 12,
        "ladder": [{"boards": 2, "count": 5}, {"boards": 3, "count": 3}],
        "lianban_stocks": [{"code": "000001", "name": "平安银行"}],
        "seal_rate": 0.85,
        "break_rate": 0.15,
        "promotion_rate": 0.42,
        "yzt_count": 38,
        "stock_name": "should_be_removed",
        "code": "should_be_removed",
        "name": "should_be_removed",
    }
    result = aggregate_emotion(mock_emotion)

    # Should contain only flat numeric aggregate keys
    expected_keys = {
        "max_boards",
        "limit_up_count",
        "limit_down_count",
        "seal_rate",
        "broken_rate",
        "advance_rate",
    }
    assert set(result.keys()) == expected_keys
    assert result["max_boards"] == 7
    assert result["limit_up_count"] == 45
    assert result["limit_down_count"] == 3
    assert result["seal_rate"] == 0.85
    assert result["broken_rate"] == 0.15
    assert result["advance_rate"] == 0.42

    # Compliance: no individual stock fields leaked
    for forbidden in ("stock_name", "code", "name", "lianban_stocks", "ladder"):
        assert forbidden not in result


def test_aggregate_emotion_none_returns_empty():
    """输入 None 返回空 dict。"""
    from predict.features.sentiment import aggregate_emotion

    assert aggregate_emotion(None) == {}


# ── (f) aggregate_emotion 含 ladder 嵌套 list：不暴露个股字段 ────────


def test_aggregate_emotion_ladder_no_leak():
    """即使 ladder 嵌套 list 含个股 dict，输出也不暴露任何个股字段。"""
    from predict.features.sentiment import aggregate_emotion

    mock_emotion = {
        "max_boards": 5,
        "zt_count": 30,
        "dt_count": 2,
        "seal_rate": 0.80,
        "break_rate": 0.20,
        "promotion_rate": 0.35,
        "ladder": [
            {"boards": 2, "count": 4, "stocks": [{"code": "000001", "name": "A"}]},
            {"boards": 3, "count": 2, "stocks": [{"code": "000002", "name": "B"}]},
        ],
    }
    result = aggregate_emotion(mock_emotion)

    # Only flat numeric keys
    assert "ladder" not in result
    assert "stocks" not in result
    assert "code" not in result
    assert "name" not in result
    assert result["max_boards"] == 5
    assert result["limit_up_count"] == 30


# ── (g) sector_divergence_score：正常 / None pct 跳过 / <2 有效 / None 输入 ─


def test_sector_divergence_score_normal():
    """正常板块 list，用极差计算分歧度。"""
    from predict.features.sentiment import sector_divergence_score

    sectors = [
        {"name": "半导体", "pct": 3.5},
        {"name": "白酒", "pct": -1.2},
        {"name": "银行", "pct": 0.5},
    ]
    result = sector_divergence_score(sectors)
    assert result == pytest.approx(4.7)  # 3.5 - (-1.2)


def test_sector_divergence_score_with_none_pct():
    """pct 含 None 时跳过，用有效值计算。"""
    from predict.features.sentiment import sector_divergence_score

    sectors = [
        {"name": "A", "pct": 2.0},
        {"name": "B", "pct": None},
        {"name": "C", "pct": -1.0},
    ]
    result = sector_divergence_score(sectors)
    assert result == pytest.approx(3.0)  # 2.0 - (-1.0)


def test_sector_divergence_score_less_than_two_valid():
    """有效 pct 少于 2 个返回 None。"""
    from predict.features.sentiment import sector_divergence_score

    assert sector_divergence_score([{"name": "A", "pct": 1.0}]) is None
    assert sector_divergence_score([{"name": "A", "pct": None}]) is None
    assert sector_divergence_score([]) is None


def test_sector_divergence_score_none_input():
    """输入 None 返回 None。"""
    from predict.features.sentiment import sector_divergence_score

    assert sector_divergence_score(None) is None
