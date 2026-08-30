# -*- coding: utf-8 -*-
"""S106 cross_validate 接线 + Valuation 暴露 PS/PCF/discrepancy 测试。

契约（spec §6）：
- A1 query_valuation 返 ps_ttm/pcf_ttm 非空（S104 遗留修复）
- A2 /api/valuation raw dict 含 pe_ttm_hithink/pb_hithink/discrepancy
- A3 PE/PB 一致（CONSISTENT）无 discrepancy
- A4 PE/PB 差>5% discrepancy 透传 + 取主源东财
- A5 hithink 断流（SINGLE_SOURCE）PE/PB 走东财，无 discrepancy
- A6 cross_validate 不再孤儿（full_valuation 调用）
- A7 两出口一致
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import astock
from data import mappers
from data.validators import Verdict, cross_validate
from models.valuation import Valuation


@pytest.fixture(autouse=True)
def _mock_tencent(monkeypatch):
    """mock 腾讯行情（东财口径 PE/PB），让 full_valuation 不真联网。"""
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: {
        c: {"name": "茅台" if c == "600519" else c, "price": 1500, "mcap_yi": 1.88e4,
            "pe_ttm": 19.92, "pb": 6.46} for c in codes
    })


def _mock_hithink(monkeypatch, hs_return: dict | None):
    """mock hithink valuation_snapshot 返回（None = 断流）。"""
    from data.sources.akshare_src import DependencyMissing
    if hs_return is None:
        monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot",
                            lambda codes: (_ for _ in ()).throw(DependencyMissing("断流")))
    else:
        monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot", lambda codes: hs_return)
    # profit_forecast 走 DependencyMissing 跳过（测试不依赖一致预期）
    monkeypatch.setattr(astock, "profit_forecast",
                        lambda c: (_ for _ in ()).throw(DependencyMissing()))


# ── A1/A3：PS/PCF 暴露 + 一致时无 discrepancy ───────────────────────────────


class TestExposure:
    def test_ps_pcf_exposed_to_ai(self, monkeypatch):
        """A1：query_valuation 返 ps_ttm/pcf_ttm（S104 遗留修复）。"""
        _mock_hithink(monkeypatch, {"600519": {"ps_ttm": 9.36, "pcf_ttm": 13.62,
                                                "pe_ttm": 19.92, "pb_mrq": 6.46}})
        from ai.tools.stock_tools import query_valuation
        r = query_valuation("600519")
        assert r["ps_ttm"] == 9.36
        assert r["pcf_ttm"] == 13.62
        assert r["pe_ttm"] == 19.92  # 东财口径不变

    def test_consistent_no_discrepancy(self, monkeypatch):
        """A3：两源 PE/PB 一致（<1%）→ 无 discrepancy 键。"""
        _mock_hithink(monkeypatch, {"600519": {"ps_ttm": 9.36, "pcf_ttm": 13.62,
                                                "pe_ttm": 19.92, "pb_mrq": 6.46}})
        from ai.tools.stock_tools import query_valuation
        r = query_valuation("600519")
        assert "discrepancy" not in r or r.get("discrepancy") is None

    def test_endpoint_raw_dict_has_backup_sources(self, monkeypatch):
        """A2：/api/valuation raw dict 含 pe_ttm_hithink/pb_hithink。"""
        _mock_hithink(monkeypatch, {"600519": {"ps_ttm": 9.36, "pcf_ttm": 13.62,
                                                "pe_ttm": 19.92, "pb_mrq": 6.46}})
        fv = astock.full_valuation("600519")
        assert fv["pe_ttm_hithink"] == 19.92
        assert fv["pb_hithink"] == 6.46


# ── A4：MAJOR_DIFFERENCE discrepancy 透传 + 取主源 ─────────────────────────────


class TestMajorDifference:
    def test_major_difference_marks_discrepancy(self, monkeypatch):
        """A4：PE/PB 差>5% → discrepancy 透传 + 仍取主源东财。"""
        # 东财 PE=19.92，hithink PE=30.0（差>50% MAJOR_DIFFERENCE）
        _mock_hithink(monkeypatch, {"600519": {"ps_ttm": 9.36, "pcf_ttm": 13.62,
                                                "pe_ttm": 30.0, "pb_mrq": 6.46}})
        fv = astock.full_valuation("600519")
        assert "discrepancy" in fv and fv["discrepancy"] is not None
        disc = fv["discrepancy"]
        pe_disc = [d for d in disc if d["field"] == "pe_ttm"][0]
        assert pe_disc["verdict"] == "major_difference"
        assert pe_disc["deviation_pct"] > 5
        assert fv["pe_ttm"] == 19.92  # 取主源东财，不丢数据

    def test_major_difference_transmits_both_outlets(self, monkeypatch):
        """A7：discrepancy 两出口一致（AI model_dump == raw dict）。"""
        _mock_hithink(monkeypatch, {"600519": {"ps_ttm": 9.36, "pcf_ttm": 13.62,
                                                "pe_ttm": 30.0, "pb_mrq": 6.46}})
        fv = astock.full_valuation("600519")
        from ai.tools.stock_tools import query_valuation
        ai_r = query_valuation("600519")
        # AI 走 mapper→Valuation，discrepancy 透传
        assert ai_r.get("discrepancy") == fv.get("discrepancy")


# ── A5：hithink 断流 SINGLE_SOURCE ────────────────────────────────────────────


class TestSingleSource:
    def test_hithink_down_no_discrepancy(self, monkeypatch):
        """A5：hithink 断流 → PE/PB 走东财（SINGLE_SOURCE），无 discrepancy。"""
        _mock_hithink(monkeypatch, None)  # hithink 抛 DependencyMissing
        fv = astock.full_valuation("600519")
        assert fv["pe_ttm"] == 19.92  # 东财口径
        assert fv.get("pe_ttm_hithink") is None
        assert "discrepancy" not in fv or fv.get("discrepancy") is None


# ── A6：cross_validate 不再孤儿 ───────────────────────────────────────────────


class TestOrphanActivated:
    def test_full_valuation_calls_cross_validate(self, monkeypatch):
        """A6：full_valuation 调 cross_validate（孤儿上线）。"""
        _mock_hithink(monkeypatch, {"600519": {"ps_ttm": 9.36, "pcf_ttm": 13.62,
                                                "pe_ttm": 19.92, "pb_mrq": 6.46}})
        called = []
        orig = cross_validate
        def spy(field, values):
            r = orig(field, values)
            called.append(field)
            return r
        monkeypatch.setattr("data.validators.cross_validate", spy)
        astock.full_valuation("600519")
        assert "pe_ttm" in called  # cross_validate 被调
        assert "pb" in called


# ── mapper 透传 ──────────────────────────────────────────────────────────────


class TestMapper:
    def test_mapper_fills_ps_pcf_discrepancy(self):
        """mapper 填 ps_ttm/pcf_ttm/discrepancy。"""
        raw = {"name": "X", "price": 10, "mcap_yi": 100, "pe_ttm": 20, "pb": 3,
               "ps_ttm": 5.0, "pcf_ttm": 8.0, "dividend_yield": 2.0,
               "discrepancy": [{"field": "pe_ttm", "verdict": "major_difference", "deviation_pct": 10.0}]}
        v = mappers.valuation_from_full_valuation("600519", raw)
        assert v.ps_ttm == 5.0
        assert v.pcf_ttm == 8.0
        assert v.dividend_yield == 2.0
        assert v.discrepancy == raw["discrepancy"]


# ── cross_validate 纯函数回归（S017 P1-c）────────────────────────────────────


class TestCrossValidatePure:
    def test_consistent(self):
        r = cross_validate("pe", {"东财": 19.92, "hithink": 19.916204})
        assert r.verdict is Verdict.CONSISTENT
        assert r.adopted_value == 19.92

    def test_major_difference(self):
        r = cross_validate("pe", {"东财": 19.92, "hithink": 30.0})
        assert r.verdict is Verdict.MAJOR_DIFFERENCE

    def test_single_source(self):
        r = cross_validate("pe", {"东财": 19.92, "hithink": None})
        assert r.verdict is Verdict.SINGLE_SOURCE
        assert r.adopted_value == 19.92
