# -*- coding: utf-8 -*-
"""S044 阶段7 单测：历史取数——activity kline 复算（R7）+ sector_flow 历史 missing。"""
from unittest import mock

from candidate_funnel.sources import activity
from predict.features import fund_flow as ff


_KLINE_BARS = [
    {"datetime": "2026-08-05 15:00", "open": 11.0, "close": 11.1, "high": 11.2, "low": 10.9, "vol": 800000.0, "amount": 8.8e8},
    {"datetime": "2026-08-06 15:00", "open": 11.1, "close": 11.0, "high": 11.3, "low": 10.8, "vol": 900000.0, "amount": 9.9e8},
    {"datetime": "2026-08-07 15:00", "open": 11.2, "close": 11.19, "high": 11.26, "low": 11.1, "vol": 882977.0, "amount": 986373760.0},
]
# tencent 当日（供流通股本近似 + name）；float_mcap_yi=2000亿
_TODAY_QUOTE = {"000001": {"name": "平安银行", "price": 11.19, "float_mcap_yi": 2000.0}}


class TestHistoricalActivity:
    def test_历史日走kline复算(self):
        with mock.patch.object(activity.astock, "tencent_quote", return_value=_TODAY_QUOTE), \
             mock.patch.object(activity.astock, "kline", return_value=_KLINE_BARS):
            out = activity.fetch_activity(["000001"], "2026-08-07")  # 历史（< 今日）
        e = out["000001"]
        assert e["price"] == 11.19
        assert e["amount_yi"] == round(986373760 / 1e8, 4)
        assert e["change_pct"] == round((11.19 - 11.0) / 11.0 * 100, 2)  # 前日 close=11.0
        assert e["amplitude_pct"] == round((11.26 - 11.1) / 11.0 * 100, 2)
        # turnover_pct = vol×10000/float_shares; float_shares=2000e8/11.19
        float_shares = 2000.0e8 / 11.19
        assert e["turnover_pct"] == round(882977.0 * 10000 / float_shares, 2)
        assert "turnover_pct" not in e["missing"]

    def test_历史日无对应bar_标missing(self):
        with mock.patch.object(activity.astock, "tencent_quote", return_value=_TODAY_QUOTE), \
             mock.patch.object(activity.astock, "kline", return_value=_KLINE_BARS):
            out = activity.fetch_activity(["000001"], "2025-01-01")  # 不在 bars
        assert out["000001"]["price"] is None
        assert "turnover_pct" in out["000001"]["missing"]

    def test_无流通股本近似_turnover标missing_其他仍复算(self):
        tq = {"000001": {"name": "x", "price": None, "float_mcap_yi": None}}
        with mock.patch.object(activity.astock, "tencent_quote", return_value=tq), \
             mock.patch.object(activity.astock, "kline", return_value=_KLINE_BARS):
            out = activity.fetch_activity(["000001"], "2026-08-07")
        assert out["000001"]["turnover_pct"] is None
        assert "turnover_pct" in out["000001"]["missing"]
        assert out["000001"]["amount_yi"] is not None  # 不依赖流通股本

    def test_当日走tencent不走kline(self):
        # as_of=今日 → 走 tencent 路径（不调 kline）
        with mock.patch.object(activity.astock, "tencent_quote", return_value=_TODAY_QUOTE) as tq, \
             mock.patch.object(activity.astock, "kline", side_effect=AssertionError("当日不应调kline")):
            activity.fetch_activity(["000001"], "2099-01-01")  # 未来日 ≥ 今日 → 非历史
        assert tq.called


class TestHistoricalSectorFlow:
    def test_历史日sector_flow仍None(self):
        # fetch_sector_flow 防御式（历史也 None）——7d
        assert ff.fetch_sector_flow("000001", "2026-07-01") is None
