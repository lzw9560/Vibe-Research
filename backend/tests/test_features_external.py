"""Tests for backend/predict/features/external.py — S018 external feature specs.

TDD: (a)-(g) covering FeatureSpec construction, registration, look-ahead guard,
and the pure compute_overnight_returns function.

All tests are offline (no network calls).
"""

import pytest


# ── (a) 4 个 FeatureSpec 构造合法 ─────────────────────────────────


def _external_specs():
    """Return the EXTERNAL_SPECS tuple from the module under test."""
    from predict.features.external import EXTERNAL_SPECS
    return EXTERNAL_SPECS


def test_feature_specs_valid():
    """4 个 FeatureSpec 构造合法，offset/stage/compliance_flag 校验通过。"""
    from predict.features.external import EXTERNAL_SPECS

    assert len(EXTERNAL_SPECS) == 4
    names = {s.name for s in EXTERNAL_SPECS}
    assert names == {
        "overnight_spx_ret",
        "overnight_ndx_ret",
        "overnight_hstech_ret",
        "overnight_a50_ret",
    }
    for spec in EXTERNAL_SPECS:
        assert spec.source == "gstock"
        assert spec.category == "external"
        assert spec.availability_offset == 1
        assert spec.stage == "s2"
        assert spec.compliance_flag == "ok"
        assert spec.description  # non-empty


# ── (b) register_external 注册成功，get_by_name 能取回 ──────────────


def test_register_external_registers_all_four():
    """register_external 把 4 个 spec 注册进新 Registry 实例。"""
    from predict.features.external import register_external, EXTERNAL_SPECS
    from predict.features.registry import Registry

    registry = Registry()
    register_external(registry)

    for spec in EXTERNAL_SPECS:
        assert registry.get_by_name(spec.name) is spec


# ── (c) 重复注册同名 raise KeyError ─────────────────────────────────


def test_register_external_duplicate_raises():
    """重复注册同名 feature 时 Registry 抛 KeyError。"""
    from predict.features.external import register_external, EXTERNAL_SPECS
    from predict.features.registry import Registry

    registry = Registry()
    register_external(registry)
    with pytest.raises(KeyError, match="already registered"):
        register_external(registry)


# ── (d) list_for_stage look-ahead 防护 ────────────────────────────────


def test_list_for_stage_s2_includes_all_four():
    """list_for_stage('s2') 包含全部 4 个 external 特征。"""
    from predict.features.external import register_external
    from predict.features.registry import Registry

    registry = Registry()
    register_external(registry)
    s2_names = {s.name for s in registry.list_for_stage("s2")}
    assert s2_names == {
        "overnight_spx_ret",
        "overnight_ndx_ret",
        "overnight_hstech_ret",
        "overnight_a50_ret",
    }


def test_list_for_stage_s1_excludes_all_four():
    """list_for_stage('s1') **排除**全部 4 个（look-ahead 核心防护）。"""
    from predict.features.external import register_external
    from predict.features.registry import Registry

    registry = Registry()
    register_external(registry)
    s1_names = {s.name for s in registry.list_for_stage("s1")}
    assert s1_names == set()


# ── (e) compute_overnight_returns 纯函数：正常情况 ──────────────────


def test_compute_overnight_returns_all_present():
    """给定 mock indices（含 spx/ndx/hstech/a50），返回 4 个特征值。"""
    from predict.features.external import compute_overnight_returns

    mock_indices = [
        {"key": "spx", "name": "标普500", "region": "美股", "price": 4500.0, "change_pct": 0.75},
        {"key": "ndx", "name": "纳斯达克", "region": "美股", "price": 14000.0, "change_pct": 1.20},
        {"key": "hstech", "name": "恒生科技", "region": "港股", "price": 3800.0, "change_pct": -0.35},
        {"key": "a50", "name": "富时A50", "region": "外盘期货", "price": 14908.94, "change_pct": 0.38},
    ]
    result = compute_overnight_returns(mock_indices)
    assert result == {
        "overnight_spx_ret": 0.75,
        "overnight_ndx_ret": 1.20,
        "overnight_hstech_ret": -0.35,
        "overnight_a50_ret": 0.38,
    }


# ── (f) compute_overnight_returns 缺失 key / None change_pct ─────────


def test_compute_overnight_returns_missing_key_returns_none():
    """缺少某个 key 时，对应特征值返回 None。"""
    from predict.features.external import compute_overnight_returns

    mock_indices = [
        {"key": "spx", "name": "标普500", "region": "美股", "price": 4500.0, "change_pct": 0.75},
        {"key": "hstech", "name": "恒生科技", "region": "港股", "price": 3800.0, "change_pct": None},
    ]
    result = compute_overnight_returns(mock_indices)
    assert result["overnight_spx_ret"] == 0.75
    assert result["overnight_ndx_ret"] is None
    assert result["overnight_hstech_ret"] is None
    assert result["overnight_a50_ret"] is None


def test_compute_overnight_returns_none_change_pct_returns_none():
    """change_pct 为 None 时，对应特征值返回 None（不崩）。"""
    from predict.features.external import compute_overnight_returns

    mock_indices = [
        {"key": "spx", "name": "标普500", "region": "美股", "price": 4500.0, "change_pct": None},
    ]
    result = compute_overnight_returns(mock_indices)
    assert result["overnight_spx_ret"] is None
    assert result["overnight_ndx_ret"] is None
    assert result["overnight_hstech_ret"] is None
    assert result["overnight_a50_ret"] is None


# ── (g) compute_overnight_returns 空 list ──────────────────────────


def test_compute_overnight_returns_empty_list_returns_all_none():
    """空 list 输入返回全 None 的映射。"""
    from predict.features.external import compute_overnight_returns

    result = compute_overnight_returns([])
    assert result == {
        "overnight_spx_ret": None,
        "overnight_ndx_ret": None,
        "overnight_hstech_ret": None,
        "overnight_a50_ret": None,
    }
