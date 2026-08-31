# -*- coding: utf-8 -*-
"""S131 R3 — query_valuation hithink PS/PCF 源断诚实化测试。

契约（spec §3 R3.3）：
- ① hithink 失败 → full_valuation raw dict 标 ps_pcf_status='hithink_unavailable'
       → mapper 透传 Valuation.data_status → query_valuation response 含 data_status（LLM 见"源断"非"无估值"）
- ② hithink 成功 → 无 ps_pcf_status 标（原行为不破），Valuation.data_status=None

对齐 S125 sentiment_weather:1249 emit 范式（data_status on response）。
"""
from __future__ import annotations

import pytest

import astock
from data import mappers
from data.sources.akshare_src import DependencyMissing
from models.valuation import Valuation


@pytest.fixture(autouse=True)
def _mock_tencent(monkeypatch):
    """mock 腾讯行情（东财口径 PE/PB），让 full_valuation 不真联网。"""
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: {
        c: {"name": "茅台" if c == "600519" else c, "price": 1500, "mcap_yi": 1.88e4,
            "pe_ttm": 19.92, "pb": 6.46} for c in codes
    })


def _mock_hithink_failure(monkeypatch):
    """mock hithink valuation_snapshot 抛异常（源断）。"""
    monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot",
                        lambda codes: (_ for _ in ()).throw(DependencyMissing("断流")))
    monkeypatch.setattr(astock, "profit_forecast",
                        lambda c: (_ for _ in ()).throw(DependencyMissing()))


def _mock_hithink_success(monkeypatch):
    """mock hithink valuation_snapshot 正常返回。"""
    monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot", lambda codes: {
        "600519": {"ps_ttm": 9.36, "pcf_ttm": 13.62, "pe_ttm": 19.92, "pb_mrq": 6.46}
    })
    monkeypatch.setattr(astock, "profit_forecast",
                        lambda c: (_ for _ in ()).throw(DependencyMissing()))


# ── ① hithink 失败 → ps_pcf_status 透传 ──────────────────────────────────────


class TestHithinkFailure:
    def test_full_valuation_marks_ps_pcf_status(self, monkeypatch):
        """hithink 异常 → full_valuation raw dict 标 ps_pcf_status='hithink_unavailable'。"""
        _mock_hithink_failure(monkeypatch)
        fv = astock.full_valuation("600519")
        assert fv.get("ps_pcf_status") == "hithink_unavailable"
        # PS/PCF 仍 None（诚实缺失，不崩）
        assert fv["ps_ttm"] is None
        assert fv["pcf_ttm"] is None
        # PE/PB 走东财口径不变
        assert fv["pe_ttm"] == 19.92

    def test_mapper_propagates_data_status(self, monkeypatch):
        """mapper 透传 ps_pcf_status → Valuation.data_status。"""
        _mock_hithink_failure(monkeypatch)
        fv = astock.full_valuation("600519")
        v = mappers.valuation_from_full_valuation("600519", fv)
        assert isinstance(v, Valuation)
        assert v.data_status == "hithink_unavailable"

    def test_query_valuation_response_has_data_status(self, monkeypatch):
        """端到端：query_valuation → response dict 含 data_status（LLM 见"源断"）。"""
        _mock_hithink_failure(monkeypatch)
        from ai.tools.stock_tools import query_valuation
        r = query_valuation("600519")
        assert r.get("data_status") == "hithink_unavailable"
        # PS/PCF 仍 None（源断，非真无估值）
        assert r["ps_ttm"] is None
        assert r["pcf_ttm"] is None


# ── ② hithink 成功 → 无 status 标（原行为）────────────────────────────────────


class TestHithinkSuccess:
    def test_full_valuation_no_ps_pcf_status(self, monkeypatch):
        """hithink 正常 → raw dict 无 ps_pcf_status 键（原行为不破）。"""
        _mock_hithink_success(monkeypatch)
        fv = astock.full_valuation("600519")
        assert "ps_pcf_status" not in fv or fv.get("ps_pcf_status") is None
        # PS/PCF 有值（hithink 补成功）
        assert fv["ps_ttm"] == 9.36
        assert fv["pcf_ttm"] == 13.62

    def test_mapper_data_status_none(self, monkeypatch):
        """hithink 正常 → Valuation.data_status=None（无源断标）。"""
        _mock_hithink_success(monkeypatch)
        fv = astock.full_valuation("600519")
        v = mappers.valuation_from_full_valuation("600519", fv)
        assert v.data_status is None
        assert v.ps_ttm == 9.36
        assert v.pcf_ttm == 13.62

    def test_query_valuation_no_data_status(self, monkeypatch):
        """端到端：hithink 正常 → query_valuation response 无 data_status 标（原行为）。"""
        _mock_hithink_success(monkeypatch)
        from ai.tools.stock_tools import query_valuation
        r = query_valuation("600519")
        assert r.get("data_status") is None
        assert r["ps_ttm"] == 9.36
        assert r["pcf_ttm"] == 13.62
