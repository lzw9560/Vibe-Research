"""Tests for backend/predict/features/macro.py — S019 Fred API slice.

All tests offline (no network). fetch_fred_series is a stub.
"""

import os

import pytest


# ── (a) 7 FeatureSpec 构造合法 ─────────────────────────────────────


def test_macro_specs_valid():
    from predict.features.macro import MACRO_SPECS

    assert len(MACRO_SPECS) == 7
    names = {s.name for s in MACRO_SPECS}
    assert names == {
        "us_10y_yield",
        "dxy",
        "us_fed_funds_eff",
        "us_10y2y_spread",
        "usd_cny",
        "wti_crude",
        "lme_copper",
    }
    for spec in MACRO_SPECS:
        assert spec.source == "fred_api"
        assert spec.category == "macro"
        assert spec.availability_offset == 1
        assert spec.stage == "s2"
        assert spec.compliance_flag == "ok"


# ── (b) register_macro 注册成功 ──────────────────────────────────────


def test_register_macro_registers_both():
    from predict.features.macro import MACRO_SPECS, register_macro
    from predict.features.registry import Registry

    reg = Registry()
    register_macro(reg)
    for spec in MACRO_SPECS:
        assert reg.get_by_name(spec.name) is spec


# ── (c) 重复注册 raise KeyError ─────────────────────────────────────


def test_register_macro_duplicate_raises():
    from predict.features.macro import register_macro
    from predict.features.registry import Registry

    reg = Registry()
    register_macro(reg)
    with pytest.raises(KeyError, match="already registered"):
        register_macro(reg)


# ── (d) list_for_stage look-ahead 防护 ───────────────────────────────


def test_list_for_stage_s2_includes_macro():
    from predict.features.macro import register_macro
    from predict.features.registry import Registry

    reg = Registry()
    register_macro(reg)
    names = {s.name for s in reg.list_for_stage("s2")}
    assert names == {
        "us_10y_yield",
        "dxy",
        "us_fed_funds_eff",
        "us_10y2y_spread",
        "usd_cny",
        "wti_crude",
        "lme_copper",
    }


def test_list_for_stage_s1_excludes_macro():
    """s1 不解锁 macro（s2 阶段），look-ahead 防护核心。"""
    from predict.features.macro import register_macro
    from predict.features.registry import Registry

    reg = Registry()
    register_macro(reg)
    assert reg.list_for_stage("s1") == []


# ── (e) parse_fred_observations 纯函数 ──────────────────────────────


def test_parse_fred_observations_normal():
    from predict.features.macro import parse_fred_observations

    resp = {
        "observations": [
            {"date": "2026-07-28", "value": "3.85"},
            {"date": "2026-07-29", "value": "3.90"},
        ]
    }
    out = parse_fred_observations(resp)
    assert out == [
        {"date": "2026-07-28", "value": 3.85},
        {"date": "2026-07-29", "value": 3.90},
    ]


def test_parse_fred_observations_missing_dot():
    """value == '.' 表示缺失 → None。"""
    from predict.features.macro import parse_fred_observations

    resp = {"observations": [{"date": "2026-07-28", "value": "."}]}
    out = parse_fred_observations(resp)
    assert out == [{"date": "2026-07-28", "value": None}]


def test_parse_fred_observations_empty_and_invalid():
    from predict.features.macro import parse_fred_observations

    assert parse_fred_observations(None) == []
    assert parse_fred_observations({}) == []
    assert parse_fred_observations({"observations": "not-a-list"}) == []
    # 非 dict 元素跳过；非 str date 跳过；非法 value → None
    resp = {"observations": [{"date": "2026-07-28", "value": "abc"}, {"value": "1"}, 42]}
    out = parse_fred_observations(resp)
    assert out == [{"date": "2026-07-28", "value": None}]


# ── (f) get_fred_api_key 读 VR_DATA_DIR ───────────────────────────────


def test_get_fred_api_key_missing_file(tmp_path, monkeypatch):
    from predict.features.macro import get_fred_api_key

    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    assert get_fred_api_key() is None


def test_get_fred_api_key_reads_file(tmp_path, monkeypatch):
    from predict.features.macro import get_fred_api_key

    (tmp_path / "fred_api_key").write_text("secret-key-123\n", encoding="utf-8")
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    assert get_fred_api_key() == "secret-key-123"


def test_get_fred_api_key_empty_file(tmp_path, monkeypatch):
    from predict.features.macro import get_fred_api_key

    (tmp_path / "fred_api_key").write_text("   \n", encoding="utf-8")
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    assert get_fred_api_key() is None


# ── (g) fetch_fred_series: 无 key 返 None（不触网） ────────────────


def test_fetch_fred_series_no_key_returns_none():
    from predict.features.macro import fetch_fred_series

    assert fetch_fred_series("DGS10", None) is None


@pytest.mark.live
def test_fetch_fred_series_dgs10_live():
    """live: 有 key 时 DGS10 返非空 + parse 有数值（key 在 VR_DATA_DIR）。"""
    from predict.features.macro import fetch_fred_series, get_fred_api_key, parse_fred_observations

    key = get_fred_api_key()
    if not key:
        pytest.skip("无 Fred API key")
    resp = fetch_fred_series("DGS10", key)
    assert resp is not None
    obs = parse_fred_observations(resp)
    assert len(obs) > 0
    vals = [o["value"] for o in obs if o["value"] is not None]
    assert vals, "DGS10 应有非缺失观测值"


@pytest.mark.live
def test_fetch_fred_series_dxy_live():
    """live: DTWEXBGS (dxy) 返非空 + 最新在 2020 后（验证未用废止的 DTWEXB）。"""
    from predict.features.macro import FRED_SERIES, fetch_fred_series, get_fred_api_key, parse_fred_observations

    key = get_fred_api_key()
    if not key:
        pytest.skip("无 Fred API key")
    resp = fetch_fred_series(FRED_SERIES["dxy"], key)
    assert resp is not None
    obs = parse_fred_observations(resp)
    vals = [o for o in obs if o["value"] is not None]
    assert vals, "DTWEXBGS 应有非缺失观测值"
    # DTWEXB 废止于 2019-12-31；后继 DTWEXBGS 最新应在 2024 之后
    assert vals[-1]["date"] >= "2024-01-01"


# ── (h) T15 batch2 live：DFF/T10Y2Y/DEXCHUS/PCOPPUSDM ──────────────


@pytest.mark.live
@pytest.mark.parametrize("name", ["us_fed_funds_eff", "us_10y2y_spread", "usd_cny", "lme_copper"])
def test_fetch_fred_series_batch2_live(name):
    """live: DFF/T10Y2Y/DEXCHUS/PCOPPUSDM 返非空 + 最新在 2024 后。"""
    from predict.features.macro import FRED_SERIES, fetch_fred_series, get_fred_api_key, parse_fred_observations

    key = get_fred_api_key()
    if not key:
        pytest.skip("无 Fred API key")
    resp = fetch_fred_series(FRED_SERIES[name], key)
    assert resp is not None
    obs = parse_fred_observations(resp)
    vals = [o for o in obs if o["value"] is not None]
    assert vals, f"{name} 应有非缺失观测值"
    assert vals[-1]["date"] >= "2024-01-01", f"{name} 最新应非陈旧数据"


@pytest.mark.live
def test_fetch_fred_series_wti_live():
    """live: DCOILWTICO 返非空（不硬断言最新年份——系列可用性需现场确认）。"""
    from predict.features.macro import FRED_SERIES, fetch_fred_series, get_fred_api_key, parse_fred_observations

    key = get_fred_api_key()
    if not key:
        pytest.skip("无 Fred API key")
    resp = fetch_fred_series(FRED_SERIES["wti_crude"], key)
    assert resp is not None
    obs = parse_fred_observations(resp)
    vals = [o for o in obs if o["value"] is not None]
    assert vals, "DCOILWTICO 应有非缺失观测值"
