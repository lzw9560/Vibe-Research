# -*- coding: utf-8 -*-
"""S132 R2 — profit_forecast empty-DataFrame 诚实化测试。

契约（spec §3 R2.4）：
- ① profit_forecast 返 []（akshare empty DataFrame soft-block）→ Valuation.forecast_status='empty_or_source_unavailable'
- ② 正常返 rows → forecast_status=None
- ③ DependencyMissing → forecast_note（原行为不破）

对齐 S131 R3 test_s131_valuation_hithink 范式（mock tencent + hithink + profit_forecast）。
"""
from __future__ import annotations

import pytest

import astock
from data import mappers
from data.sources.akshare_src import DependencyMissing


@pytest.fixture(autouse=True)
def _mock_tencent(monkeypatch):
    """mock 腾讯行情（东财口径 PE/PB），让 full_valuation 不真联网。"""
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: {
        c: {"name": "茅台" if c == "600519" else c, "price": 1500, "mcap_yi": 1.88e4,
            "pe_ttm": 19.92, "pb": 6.46} for c in codes
    })


def _mock_hithink_ok(monkeypatch):
    """mock hithink 正常返回空（不挡 PS/PCF 路径，让 forecast 路径独立测）。"""
    monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot", lambda codes: {})


def test_forecast_status_when_empty_dataframe(monkeypatch):
    """① profit_forecast 返 []（akshare soft-block/无覆盖）→ forecast_status='empty_or_source_unavailable'。"""
    _mock_hithink_ok(monkeypatch)
    monkeypatch.setattr(astock, "profit_forecast", lambda c: [])  # empty DataFrame path

    raw = astock.full_valuation("600519")
    assert raw["forecast_status"] == "empty_or_source_unavailable"

    val = mappers.valuation_from_full_valuation("600519", raw)
    assert val.forecast_status == "empty_or_source_unavailable"


def test_forecast_status_none_when_rows(monkeypatch):
    """② 正常返 rows → forecast_status 不设（None）。"""
    _mock_hithink_ok(monkeypatch)
    monkeypatch.setattr(astock, "profit_forecast", lambda c: [
        {"年度": "2026", "均值": "2.0", "预测机构数": "12"}])

    raw = astock.full_valuation("600519")
    assert raw.get("forecast_status") is None

    val = mappers.valuation_from_full_valuation("600519", raw)
    assert val.forecast_status is None


def test_dependency_missing_keeps_forecast_note(monkeypatch):
    """③ DependencyMissing（akshare 未装）→ forecast_note（原行为不破，early return 不设 forecast_status）。"""
    _mock_hithink_ok(monkeypatch)
    monkeypatch.setattr(astock, "profit_forecast",
                        lambda c: (_ for _ in ()).throw(DependencyMissing()))

    raw = astock.full_valuation("600519")
    assert raw["forecast_note"] == "一致预期需安装 akshare"
    assert "forecast_status" not in raw  # early return before forecast_status
