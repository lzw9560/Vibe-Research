# -*- coding: utf-8 -*-
"""S172 fetch_etf_tracking 单测——mock akshare，验取数解析 + 跟踪误差计算口径。

离线：monkeypatch akshare 函数返固定 DataFrame，零网络。
"""
from __future__ import annotations

import math

import pandas as pd
import pytest


# ---- helpers ----

def _mock_etf_spot_df():
    """fund_etf_spot_em 返回的 mock DataFrame（含 512890 + 干扰行）。"""
    return pd.DataFrame({
        "代码": ["512890", "510300"],
        "名称": ["华泰柏瑞红利低波ETF", "沪深300ETF"],
        "最新价": ["1.234", "4.567"],
        "涨跌额": ["0.012", "-0.034"],
        "涨跌幅": ["0.98", "-0.74"],
        "成交量": ["100000", "200000"],
        "成交额": ["123400", "913400"],
    })


def _mock_hist_df(closes: list[float], start_date: str = "2026-01-05"):
    """fund_etf_hist_em / index_zh_a_hist 返回的 mock DataFrame（日期+收盘）。"""
    from datetime import date, timedelta
    base = date.fromisoformat(start_date)
    dates = [(base + timedelta(days=i)).isoformat() for i in range(len(closes))]
    return pd.DataFrame({"日期": dates, "收盘": closes})


def _mock_cons_weight_df():
    """index_stock_cons_weight_csindex 返回的 mock DataFrame。"""
    return pd.DataFrame({
        "日期": ["20260613"] * 3,
        "指数代码": ["930955"] * 3,
        "指数名称": ["中证红利低波动"] * 3,
        "成分券代码": ["601398", "600036", "601318"],
        "成分券名称": ["工商银行", "招商银行", "中国平安"],
        "权重": [0.05, 0.04, 0.03],
    })


# ============================ R1: fetch_etf_quote ============================

class TestFetchEtfQuote:
    def test_returns_dict_for_512890(self, monkeypatch):
        import akshare as ak
        monkeypatch.setattr(ak, "fund_etf_spot_em", lambda: _mock_etf_spot_df())
        from tools.fetch_etf_tracking import fetch_etf_quote
        q = fetch_etf_quote("512890")
        assert q["code"] == "512890"
        assert q["name"] == "华泰柏瑞红利低波ETF"
        assert q["price"] == 1.234
        assert q["change_pct"] == 0.98

    def test_missing_code_returns_empty(self, monkeypatch):
        import akshare as ak
        monkeypatch.setattr(ak, "fund_etf_spot_em", lambda: _mock_etf_spot_df())
        from tools.fetch_etf_tracking import fetch_etf_quote
        q = fetch_etf_quote("999999")
        assert q == {}

    def test_akshare_failure_returns_empty(self, monkeypatch):
        import akshare as ak
        def _boom():
            raise ConnectionError("network down")
        monkeypatch.setattr(ak, "fund_etf_spot_em", _boom)
        from tools.fetch_etf_tracking import fetch_etf_quote
        q = fetch_etf_quote("512890")
        assert q == {}


# ============================ R2: fetch_index_cons_weight ============================

class TestFetchIndexConsWeight:
    def test_returns_list_of_dicts(self, monkeypatch):
        import akshare as ak
        monkeypatch.setattr(ak, "index_stock_cons_weight_csindex",
                            lambda symbol: _mock_cons_weight_df())
        from tools.fetch_etf_tracking import fetch_index_cons_weight
        cons = fetch_index_cons_weight("930955")
        assert len(cons) == 3
        assert cons[0]["code"] == "601398"
        assert cons[0]["name"] == "工商银行"
        assert cons[0]["weight"] == 0.05


# ============================ R3: tracking_error_report ============================

class TestTrackingErrorReport:
    def test_parse_daily_returns(self):
        from tools.fetch_etf_tracking import _parse_daily_returns
        df = _mock_hist_df([1.0, 1.01, 1.02])
        rets = _parse_daily_returns(df)
        assert len(rets) == 3
        assert rets[0]["ret"] == 0.0  # 首条无前日
        assert abs(rets[1]["ret"] - 0.01) < 1e-9
        assert abs(rets[2]["ret"] - (1.02 - 1.01) / 1.01) < 1e-9

    def test_tracking_error_green(self, monkeypatch):
        """ETF 和指数收益几乎一致 → TE < 1% 绿灯。"""
        import akshare as ak
        etf_closes = [1.0 + i * 0.001 for i in range(30)]
        idx_closes = [1.0 + i * 0.001 + (i % 3 - 1) * 0.00005 for i in range(30)]
        monkeypatch.setattr(ak, "fund_etf_hist_em",
                            lambda **kw: _mock_hist_df(etf_closes))
        monkeypatch.setattr(ak, "index_zh_a_hist",
                            lambda **kw: _mock_hist_df(idx_closes))
        from tools.fetch_etf_tracking import tracking_error_report
        rpt = tracking_error_report("512890", "930955")
        assert "error" not in rpt
        assert "1m" in rpt["windows"]
        te_1m = rpt["windows"]["1m"]["te"]
        assert te_1m is not None
        assert te_1m < 1.0  # 绿灯
        assert rpt["windows"]["1m"]["light"] == "green"

    def test_tracking_error_calculation_matches_formula(self, monkeypatch):
        """手工算 TE 验证：std(diff)×sqrt(252)。"""
        import akshare as ak
        etf_closes = [1.0, 1.001, 1.002, 1.003]
        idx_closes = [1.0, 1.001, 1.00205, 1.00305]
        monkeypatch.setattr(ak, "fund_etf_hist_em",
                            lambda **kw: _mock_hist_df(etf_closes))
        monkeypatch.setattr(ak, "index_zh_a_hist",
                            lambda **kw: _mock_hist_df(idx_closes))
        from tools.fetch_etf_tracking import (
            tracking_error_report, _parse_daily_returns, _ANNUAL_FACTOR,
        )
        rpt = tracking_error_report("512890", "930955", windows={"all": 999})
        te_pct = rpt["windows"]["all"]["te"]

        # 用 _parse_daily_returns 得到实际收益序列，再手工算 TE
        etf_rets = [r["ret"] for r in _parse_daily_returns(_mock_hist_df(etf_closes))]
        idx_rets = [r["ret"] for r in _parse_daily_returns(_mock_hist_df(idx_closes))]
        diffs = [e - i for e, i in zip(etf_rets, idx_rets)]
        mean_d = sum(diffs) / len(diffs)
        var_d = sum((x - mean_d) ** 2 for x in diffs) / (len(diffs) - 1)
        expected_te = math.sqrt(var_d) * math.sqrt(_ANNUAL_FACTOR) * 100
        assert abs(te_pct - expected_te) < 0.01

    def test_empty_data_returns_error(self, monkeypatch):
        import akshare as ak
        monkeypatch.setattr(ak, "fund_etf_hist_em", lambda **kw: pd.DataFrame())
        monkeypatch.setattr(ak, "index_zh_a_hist", lambda **kw: pd.DataFrame())
        from tools.fetch_etf_tracking import tracking_error_report
        rpt = tracking_error_report("512890", "930955")
        assert "error" in rpt
        assert rpt["windows"] == {}
