# -*- coding: utf-8 -*-
"""astock.py 门面测试——覆盖纯函数 + kline + full_valuation 各降级路径。

不联网：tencent_quote / kline_multi / profit_forecast / hithink 全 monkeypatch 打桩。

对齐既有测试范式：
- test_s008_sources_facade.py（门面委派 + re-export 不变）
- test_s131_valuation_hithink.py（full_valuation hithink 源断）
- test_s132_profit_forecast.py（profit_forecast empty-DataFrame）
- test_s003_fixes.py（kline_multi 打桩 lambda）
"""
from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

import astock
from data.sources._common import DependencyMissing


# ════════════════════════════════════════════════════════════════════════════
# 纯数学函数：calc_peg / pe_digestion
# ════════════════════════════════════════════════════════════════════════════


class TestCalcPeg:
    """calc_peg(pe, cagr) = pe / (cagr * 100)；cagr<=0 → inf。"""

    def test_normal(self):
        # PE=30, CAGR=15% → 30 / 15 = 2.0
        assert astock.calc_peg(30, 0.15) == pytest.approx(2.0)

    def test_zero_cagr_returns_inf(self):
        """CAGR=0 → inf（分母为 0，避免除零）。"""
        assert astock.calc_peg(20, 0) == math.inf

    def test_negative_cagr_returns_inf(self):
        """负增长 → inf（不臆造负 PEG，无意义）。"""
        assert astock.calc_peg(20, -0.05) == math.inf


class TestPeDigestion:
    """pe_digestion(current_pe, cagr, target_pe=30)。

    - current_pe ≤ target_pe → 0（已低于目标，无需消化）
    - cagr <= 0 → inf（永不消化）
    - 否则 log(current/target) / log(1+cagr)
    """

    def test_already_below_target(self):
        """现 PE < 目标 → 0 年消化（已便宜）。"""
        assert astock.pe_digestion(20, 0.15) == 0.0

    def test_equal_to_target(self):
        """现 PE == 目标 → 0（边界）。"""
        assert astock.pe_digestion(30, 0.15) == 0.0

    def test_normal_digest(self):
        """PE=60, target=30, cagr=15% → log(2)/log(1.15) ≈ 4.96 年。"""
        val = astock.pe_digestion(60, 0.15, target_pe=30)
        assert val == pytest.approx(math.log(2) / math.log(1.15), rel=1e-6)
        assert val > 4.5 and val < 5.5  # 合理范围

    def test_custom_target(self):
        """传 target_pe=25。"""
        val = astock.pe_digestion(50, 0.20, target_pe=25)
        assert val == pytest.approx(math.log(2) / math.log(1.20), rel=1e-6)

    def test_negative_cagr_inf(self):
        """负增长 → inf（高估永不消化）。"""
        assert astock.pe_digestion(60, -0.1) == math.inf

    def test_zero_cagr_inf(self):
        """CAGR=0 → inf。"""
        assert astock.pe_digestion(60, 0) == math.inf


# ════════════════════════════════════════════════════════════════════════════
# _baostock_5min_to_timestamp：baostock time str → ms timestamp
# ════════════════════════════════════════════════════════════════════════════


class TestBaostockTimestamp:
    """_baostock_5min_to_timestamp('YYYYMMDDHHMMSSmmm') → ms（北京 +08:00）。"""

    def test_known_timestamp(self):
        """20260915093500000 → 2026-09-15 09:35:00 +08:00 的 ms timestamp。"""
        from datetime import datetime, timezone, timedelta

        expected = int(
            datetime(2026, 9, 15, 9, 35, tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000
        )
        assert astock._baostock_5min_to_timestamp("20260915093500000") == expected

    def test_different_time(self):
        """20260101000000000 → 2026-01-01 00:00 +08:00（午夜，毫秒部分 000 被截断）。"""
        from datetime import datetime, timezone, timedelta

        expected = int(
            datetime(2026, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000
        )
        # 输入 14 位 + 3 位毫秒（共 17），但函数只取前 12 位（YYYYMMDDHHMM）
        assert astock._baostock_5min_to_timestamp("20260101000000000") == expected


# ════════════════════════════════════════════════════════════════════════════
# _resample_daily_to_period：日K → 周/月K 聚合
# ════════════════════════════════════════════════════════════════════════════


def _bar(date: str, o=10.0, h=11.0, lo=9.0, c=10.5, v=1000, a=10000.0) -> dict:
    """构造单根日 K bar。"""
    return {"date": date, "open": o, "high": h, "low": lo, "close": c, "volume": v, "amount": a}


class TestResampleDaily:
    """_resample_daily_to_period(daily, category)。category=5 周 / 6 月。"""

    def test_empty_input(self):
        """空输入 → 空输出（不臆造）。"""
        assert astock._resample_daily_to_period([], 5) == []
        assert astock._resample_daily_to_period([], 6) == []

    def test_weekly_aggregation(self):
        """周 K：同 ISO 周合并。3 根日 K → 1 周 K（open=首 close=末 high=max low=min vol=sum）。"""
        # 2026-01-05(周一) / 01-06(周二) / 01-07(周三) 同 ISO 周
        daily = [
            _bar("2026-01-05", o=10.0, h=11.0, lo=9.0, c=10.5, v=1000, a=10000),
            _bar("2026-01-06", o=10.5, h=12.0, lo=10.0, c=11.5, v=2000, a=20000),
            _bar("2026-01-07", o=11.5, h=13.0, lo=11.0, c=12.5, v=3000, a=30000),
        ]
        out = astock._resample_daily_to_period(daily, 5)
        assert len(out) == 1
        bar = out[0]
        assert bar["date"] == "2026-01-07"  # 末根日期
        assert bar["open"] == 10.0  # 首根 open
        assert bar["close"] == 12.5  # 末根 close
        assert bar["high"] == 13.0  # max
        assert bar["low"] == 9.0  # min
        assert bar["volume"] == 6000  # sum
        assert bar["amount"] == 60000.0

    def test_monthly_aggregation(self):
        """月 K：同年月合并。"""
        daily = [
            _bar("2026-01-05", o=10.0, c=11.0, v=1000),
            _bar("2026-01-20", o=11.0, c=12.0, v=2000),
            _bar("2026-02-03", o=12.0, c=13.0, v=3000),  # 新月
        ]
        out = astock._resample_daily_to_period(daily, 6)
        assert len(out) == 2  # 1月 + 2月
        # 1月：open=10 close=12 vol=3000
        assert out[0]["open"] == 10.0
        assert out[0]["close"] == 12.0
        assert out[0]["volume"] == 3000
        # 2月：单根
        assert out[1]["open"] == 12.0
        assert out[1]["close"] == 13.0

    def test_missing_fields_none(self):
        """缺字段（None）跳过聚合，不臆造 0。"""
        daily = [
            {"date": "2026-01-05", "open": 10.0, "high": None, "low": 9.0, "close": 10.5, "volume": 1000, "amount": None},
            {"date": "2026-01-06", "open": 10.5, "high": 12.0, "low": None, "close": 11.5, "volume": None, "amount": 20000},
        ]
        out = astock._resample_daily_to_period(daily, 5)
        assert len(out) == 1
        bar = out[0]
        # high 只有 1 个有效值（12.0）
        assert bar["high"] == 12.0
        # low 只有 1 个有效值（9.0）
        assert bar["low"] == 9.0
        # volume 只有 1 个有效值
        assert bar["volume"] == 1000
        # amount 只有 1 个有效值
        assert bar["amount"] == 20000.0

    def test_all_none_high_low(self):
        """所有 high/low 都 None → max([]) / min([]) → None（不崩）。"""
        daily = [
            {"date": "2026-01-05", "open": 10.0, "high": None, "low": None, "close": 10.5, "volume": 1000, "amount": 10000},
        ]
        out = astock._resample_daily_to_period(daily, 5)
        assert len(out) == 1
        assert out[0]["high"] is None
        assert out[0]["low"] is None

    def test_malformed_date_passthrough(self):
        """date 不是 YYYY-MM-DD 格式 → 原样返回作 key（不崩）。"""
        daily = [{"date": "bad", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1, "amount": 1}]
        out = astock._resample_daily_to_period(daily, 5)
        assert len(out) == 1
        assert out[0]["date"] == "bad"

    def test_unknown_category_monthly_default(self):
        """category 非 5 → 走月 K 分支（else 分支）。"""
        daily = [
            _bar("2026-01-05"),
            _bar("2026-02-05"),
        ]
        out = astock._resample_daily_to_period(daily, 99)
        assert len(out) == 2  # 两个月


# ════════════════════════════════════════════════════════════════════════════
# _aggregate_5min_to_period：5min bars → period_min 分钟 bars
# ════════════════════════════════════════════════════════════════════════════


class TestAggregate5min:
    """_aggregate_5min_to_period(bars_5min, period_min)。"""

    def test_empty(self):
        """空输入 → 空输出。"""
        assert astock._aggregate_5min_to_period([], 5) == []
        assert astock._aggregate_5min_to_period([], 15) == []

    def test_period_5_passthrough(self):
        """period_min=5 → 直接返（加 timestamp，不聚合）。"""
        bars = [
            {"date": "2026-01-05", "time": "20260105093500000", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        ]
        out = astock._aggregate_5min_to_period(bars, 5)
        assert len(out) == 1
        assert "timestamp" in out[0]
        assert out[0]["timestamp"] is not None

    def test_period_15_aggregation(self):
        """15min：3 根 5min bars 聚合成 1 根 15min bar（同一 15min 窗口内）。"""
        # 9:35, 9:40, 9:44 → 同 15min 窗口（9:30-9:45，9:45 是下一窗口起点）
        bars = [
            {"date": "2026-01-05", "time": "20260105093500000", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100},
            {"date": "2026-01-05", "time": "20260105094000000", "open": 10.5, "high": 12.0, "low": 10.0, "close": 11.5, "volume": 200},
            {"date": "2026-01-05", "time": "20260105094400000", "open": 11.5, "high": 13.0, "low": 11.0, "close": 12.5, "volume": 300},
        ]
        out = astock._aggregate_5min_to_period(bars, 15)
        assert len(out) == 1
        bar = out[0]
        assert bar["open"] == 10.0  # 首根 open
        assert bar["close"] == 12.5  # 末根 close
        assert bar["high"] == 13.0  # max
        assert bar["low"] == 9.0  # min
        assert bar["volume"] == 600  # sum

    def test_bar_without_timestamp_or_time_skipped(self):
        """无 timestamp 且无 time → 跳过（continue，不崩）。"""
        bars = [
            {"date": "2026-01-05", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},  # 无 time
            {"date": "2026-01-05", "time": "20260105093500000", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
        ]
        out = astock._aggregate_5min_to_period(bars, 15)
        assert len(out) == 1  # 只有 1 根有效

    def test_bar_with_explicit_timestamp(self):
        """已有 timestamp 字段 → 直接用，不需 time 转换。"""
        bars = [
            {"date": "2026-01-05", "timestamp": 1000000, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
            {"date": "2026-01-05", "timestamp": 1003000, "open": 10.5, "high": 12, "low": 10, "close": 11, "volume": 200},
        ]
        # period_ms = 15 * 60 * 1000 = 900000
        # 1000000 // 900000 = 1 → key = 900000
        # 1003000 // 900000 = 1 → key = 900000（同窗口）
        out = astock._aggregate_5min_to_period(bars, 15)
        assert len(out) == 1

    def test_missing_high_low_volume(self):
        """high/low/volume 为 None → 跳过聚合（不臆造 0）。"""
        bars = [
            {"date": "2026-01-05", "timestamp": 900000, "open": 10, "high": None, "low": 9, "close": 10, "volume": 100},
            {"date": "2026-01-05", "timestamp": 1000000, "open": 10, "high": 11, "low": None, "close": 10, "volume": None},
        ]
        out = astock._aggregate_5min_to_period(bars, 15)
        # 两根同 15min 窗口
        assert len(out) == 1
        # high 只有 1 个有效
        assert out[0]["high"] == 11
        # low 只有 1 个有效
        assert out[0]["low"] == 9
        # volume 只有 1 个有效
        assert out[0]["volume"] == 100


# ════════════════════════════════════════════════════════════════════════════
# kline()：日K / 周K / 月K / 分钟K 各分支 + 降级
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _no_network_kline(monkeypatch):
    """防真网络：kline_multi（日K 多源）+ baostock 5min 全打桩。"""
    monkeypatch.setattr(astock, "kline_multi", lambda *a, **k: ([], "stub"))


class TestKlineDaily:
    """kline(category=4) 日K分支。"""

    def test_daily_normal(self, monkeypatch):
        """日 K：kline_multi 返数据 → 截取 offset 条。"""
        bars = [_bar(f"2026-01-{i:02d}") for i in range(1, 11)]  # 10 根
        monkeypatch.setattr(astock, "kline_multi", lambda *a, **k: (bars, "baostock"))
        out = astock.kline("600519", category=4, offset=5)
        assert len(out) == 5
        assert out[-1]["date"] == "2026-01-10"

    def test_daily_offset_exceeds_len(self, monkeypatch):
        """offset > 数据量 → 返全量（不截断）。"""
        bars = [_bar(f"2026-01-{i:02d}") for i in range(1, 4)]  # 3 根
        monkeypatch.setattr(astock, "kline_multi", lambda *a, **k: (bars, "baostock"))
        out = astock.kline("600519", category=4, offset=60)
        assert len(out) == 3  # 全量返

    def test_daily_empty_returns_empty(self, monkeypatch):
        """kline_multi 返空 → 诚实返 []（不臆造）。"""
        monkeypatch.setattr(astock, "kline_multi", lambda *a, **k: ([], None))
        assert astock.kline("600519", category=4) == []

    def test_daily_kline_multi_exception(self, monkeypatch):
        """kline_multi 抛异常 → 吞 + 返 []（不崩）。"""
        def _raise(*a, **k):
            raise OSError("network down")
        monkeypatch.setattr(astock, "kline_multi", _raise)
        assert astock.kline("600519", category=4) == []


class TestKlineWeeklyMonthly:
    """kline(category=5 周 / 6 月）。"""

    def test_weekly_resample(self, monkeypatch):
        """周 K：日K → _resample_daily_to_period(category=5)。"""
        daily = [
            _bar("2026-01-05"),  # ISO 周
            _bar("2026-01-06"),
            _bar("2026-01-12"),  # 下一 ISO 周
        ]
        monkeypatch.setattr(astock, "kline_multi", lambda *a, **k: (daily, "baostock"))
        out = astock.kline("600519", category=5, offset=60)
        assert len(out) == 2  # 2 周

    def test_monthly_resample(self, monkeypatch):
        """月 K：日K → _resample_daily_to_period(category=6)。"""
        daily = [
            _bar("2026-01-05"),
            _bar("2026-02-05"),
        ]
        monkeypatch.setattr(astock, "kline_multi", lambda *a, **k: (daily, "baostock"))
        out = astock.kline("600519", category=6, offset=60)
        assert len(out) == 2  # 2 月

    def test_weekly_empty(self, monkeypatch):
        """周 K：kline_multi 空 → []。"""
        monkeypatch.setattr(astock, "kline_multi", lambda *a, **k: ([], None))
        assert astock.kline("600519", category=5) == []


class TestKlineMinute:
    """kline(category=1/15/30/11) 分钟K分支——baostock 5min 聚合。"""

    def test_5min_normal(self, monkeypatch):
        """category=1（5min）：baostock fetch_5min_bars 返数据 → 直接返（加 timestamp）。"""
        bars = [
            {"date": "2026-01-05", "time": "20260105093500000", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        ]
        monkeypatch.setattr("data.sources.baostock_src.fetch_5min_bars", lambda code, start, end: bars)
        out = astock.kline("600519", category=1, offset=10)
        assert len(out) == 1
        assert "timestamp" in out[0]

    def test_15min_aggregation(self, monkeypatch):
        """category=15：3 根 5min → 1 根 15min（同一 15min 窗口内）。"""
        # 9:35, 9:40, 9:44 → 同 15min 窗口（9:30-9:45）
        bars = [
            {"date": "2026-01-05", "time": "20260105093500000", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
            {"date": "2026-01-05", "time": "20260105094000000", "open": 10.5, "high": 12, "low": 10, "close": 11, "volume": 200},
            {"date": "2026-01-05", "time": "20260105094400000", "open": 11, "high": 13, "low": 11, "close": 12, "volume": 300},
        ]
        monkeypatch.setattr("data.sources.baostock_src.fetch_5min_bars", lambda code, start, end: bars)
        out = astock.kline("600519", category=15, offset=10)
        assert len(out) == 1
        assert out[0]["open"] == 10
        assert out[0]["close"] == 12

    def test_60min_category_11(self, monkeypatch):
        """category=11（60min）。"""
        # 造 12 根 5min（1 小时）→ 1 根 60min
        bars = [
            {"date": "2026-01-05", "time": f"2026010509{i:02d}00000", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100}
            for i in range(30, 45)  # 9:30 - 9:45（3 根 5min）
        ]
        monkeypatch.setattr("data.sources.baostock_src.fetch_5min_bars", lambda code, start, end: bars)
        out = astock.kline("600519", category=11, offset=10)
        assert len(out) == 1  # 都在同一 60min 窗口

    def test_minute_empty_baostock(self, monkeypatch):
        """分钟 K：baostock 返空 → []（诚实降级）。"""
        monkeypatch.setattr("data.sources.baostock_src.fetch_5min_bars", lambda code, start, end: [])
        assert astock.kline("600519", category=1) == []

    def test_minute_baostock_exception(self, monkeypatch):
        """分钟 K：baostock 抛异常 → 吞 + []（不崩）。"""
        def _raise(code, start, end):
            raise OSError("baostock down")
        monkeypatch.setattr("data.sources.baostock_src.fetch_5min_bars", _raise)
        assert astock.kline("600519", category=15) == []

    def test_minute_import_error(self, monkeypatch):
        """分钟 K：baostock fetch_5min_bars 抛 ImportError → 吞 + []（kline except 捕获所有 Exception）。"""
        def _raise(code, start, end):
            raise ImportError("baostock not installed")
        monkeypatch.setattr("data.sources.baostock_src.fetch_5min_bars", _raise)
        assert astock.kline("600519", category=1) == []


class TestKlineUnknownCategory:
    """category 非 1/4/5/6/11/15/30 → kline_multi 分支返 []（category!=4/5/6 的 else）。"""

    def test_unknown_category_intraday_fallback_empty(self, monkeypatch):
        """日K kline_multi 返数据但 category=99（非 4/5/6）→ 返 []（else 分支）。"""
        daily = [_bar("2026-01-05")]
        monkeypatch.setattr(astock, "kline_multi", lambda *a, **k: (daily, "baostock"))
        # category=99 不在 _MIN_CATEGORY（分钟分支），也不在 4/5/6（日K分支的 if）
        # → 走日K kline_multi 分支，但 category 不匹配 → 返 []
        out = astock.kline("600519", category=99)
        assert out == []


# ════════════════════════════════════════════════════════════════════════════
# full_valuation()：腾讯行情 + hithink + cross_validate + profit_forecast
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_tencent_quote(monkeypatch):
    """mock 腾讯行情——返茅台全字段。"""
    def _quote(codes):
        return {
            c: {
                "name": "贵州茅台" if c == "600519" else c,
                "price": 1500.0,
                "mcap_yi": 18800.0,
                "pe_ttm": 25.0,
                "pb": 8.0,
            }
            for c in codes
        }
    monkeypatch.setattr(astock, "tencent_quote", _quote)


@pytest.fixture
def mock_hithink_none(monkeypatch):
    """mock hithink valuation_snapshot 返空（PS/PCF 无值）。"""
    monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot", lambda codes: {})


@pytest.fixture
def mock_profit_forecast_none(monkeypatch):
    """mock profit_forecast 抛 DependencyMissing（akshare 未装）。"""
    def _raise(code):
        raise DependencyMissing("akshare 未安装")
    monkeypatch.setattr(astock, "profit_forecast", _raise)


class TestFullValuationBasics:
    """full_valuation 基础路径：行情 + hithink + forecast 全 mock。"""

    def test_quote_missing_raises_valueerror(self, monkeypatch):
        """腾讯行情返空（code 不在 dict）→ raise ValueError（不臆造估值）。"""
        monkeypatch.setattr(astock, "tencent_quote", lambda codes: {})
        with pytest.raises(ValueError, match="未取到"):
            astock.full_valuation("600519")

    def test_base_fields_from_tencent(self, mock_tencent_quote, mock_hithink_none, mock_profit_forecast_none):
        """full_valuation 基础字段（name/price/pe_ttm/pb）来自腾讯行情。"""
        fv = astock.full_valuation("600519")
        assert fv["name"] == "贵州茅台"
        assert fv["code"] == "600519"
        assert fv["price"] == 1500.0
        assert fv["pe_ttm"] == 25.0
        assert fv["pb"] == 8.0
        assert fv["mcap_yi"] == 18800.0

    def test_ps_pcf_default_none(self, mock_tencent_quote, mock_hithink_none, mock_profit_forecast_none):
        """PS/PCF 默认 None（东财结构性缺，hithink 补）。"""
        fv = astock.full_valuation("600519")
        assert fv["ps_ttm"] is None
        assert fv["pcf_ttm"] is None

    def test_forecast_note_when_dependency_missing(self, mock_tencent_quote, mock_hithink_none, mock_profit_forecast_none):
        """profit_forecast DependencyMissing → forecast_note（early return）。"""
        fv = astock.full_valuation("600519")
        assert fv["forecast_note"] == "一致预期需安装 akshare"
        # early return，不设 forecast_status
        assert "forecast_status" not in fv


class TestFullValuationHithink:
    """hithink 补 PS/PCF 路径。"""

    def test_hithink_success(self, mock_tencent_quote, mock_profit_forecast_none, monkeypatch):
        """hithink 正常 → PS/PCF 有值。"""
        monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot", lambda codes: {
            "600519": {"ps_ttm": 9.5, "pcf_ttm": 13.0, "pe_ttm": 25.0, "pb_mrq": 8.0}
        })
        fv = astock.full_valuation("600519")
        assert fv["ps_ttm"] == 9.5
        assert fv["pcf_ttm"] == 13.0
        # 备源字段也填
        assert fv["pe_ttm_hithink"] == 25.0
        assert fv["pb_hithink"] == 8.0

    def test_hithink_failure_marks_status(self, mock_tencent_quote, mock_profit_forecast_none, monkeypatch):
        """hithink 抛异常 → ps_pcf_status='hithink_unavailable'（PS/PCF 仍 None）。"""
        def _raise(codes):
            raise RuntimeError("hithink down")
        monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot", _raise)
        fv = astock.full_valuation("600519")
        assert fv.get("ps_pcf_status") == "hithink_unavailable"
        assert fv["ps_ttm"] is None
        assert fv["pcf_ttm"] is None

    def test_hithink_code_not_in_result(self, mock_tencent_quote, mock_profit_forecast_none, monkeypatch):
        """hithink 返 dict 但不含本 code → PS/PCF 仍 None（不崩）。"""
        monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot", lambda codes: {"000001": {}})
        fv = astock.full_valuation("600519")
        assert fv["ps_ttm"] is None
        # 不算 hithink_unavailable（调用成功，只是无该 code 数据）
        assert "ps_pcf_status" not in fv


class TestFullValuationForecast:
    """profit_forecast 路径——EPS/CAGR/PEG/消化年数。"""

    def test_forecast_empty_marks_status(self, mock_tencent_quote, mock_hithink_none, monkeypatch):
        """profit_forecast 返 [] → forecast_status='empty_or_source_unavailable'。"""
        monkeypatch.setattr(astock, "profit_forecast", lambda code: [])
        fv = astock.full_valuation("600519")
        assert fv["forecast_status"] == "empty_or_source_unavailable"
        # eps/pe_26e/cagr 仍 None
        assert fv["eps_26e"] is None
        assert fv["pe_26e"] is None

    def test_forecast_with_2026_eps(self, mock_tencent_quote, mock_hithink_none, monkeypatch):
        """profit_forecast 返 2026 EPS → pe_26e = price / eps。"""
        monkeypatch.setattr(astock, "profit_forecast", lambda code: [
            {"年度": "2026", "均值": "50.0", "预测机构数": "12"}
        ])
        fv = astock.full_valuation("600519")
        # price=1500, eps_26=50 → pe_26e = 30.0
        assert fv["eps_26e"] == 50.0
        assert fv["pe_26e"] == 30.0
        assert fv["analyst_count"] == 12

    def test_forecast_with_cagr(self, mock_tencent_quote, mock_hithink_none, monkeypatch):
        """profit_forecast 返 2026 + 2027 EPS → CAGR + PEG + digest_years。"""
        monkeypatch.setattr(astock, "profit_forecast", lambda code: [
            {"年度": "2026", "均值": "50.0", "预测机构数": "10"},
            {"年度": "2027", "均值": "60.0", "预测机构数": "10"},
        ])
        fv = astock.full_valuation("600519")
        # pe_26e = 1500/50 = 30
        # cagr = 60/50 - 1 = 0.2 (20%)
        # peg = calc_peg(30, 0.2) = 30 / (0.2 * 100) = 1.5
        assert fv["eps_26e"] == 50.0
        assert fv["eps_27e"] == 60.0
        assert fv["pe_26e"] == 30.0
        assert fv["cagr_pct"] == 20.0
        assert fv["peg"] == 1.5

    def test_forecast_eps_with_comma(self, mock_tencent_quote, mock_hithink_none, monkeypatch):
        """EPS 含逗号（千分位）→ 解析成功。"""
        monkeypatch.setattr(astock, "profit_forecast", lambda code: [
            {"年度": "2026", "均值": "1,234.56", "预测机构数": "5"}
        ])
        fv = astock.full_valuation("600519")
        assert fv["eps_26e"] == 1234.56

    def test_forecast_eps_invalid(self, mock_tencent_quote, mock_hithink_none, monkeypatch):
        """EPS 是 '-' 占位 → _eps 返 None，pe_26e 不计算。"""
        monkeypatch.setattr(astock, "profit_forecast", lambda code: [
            {"年度": "2026", "均值": "-", "预测机构数": "5"}
        ])
        fv = astock.full_valuation("600519")
        assert fv["eps_26e"] is None
        assert fv["pe_26e"] is None

    def test_forecast_zero_eps_skipped(self, mock_tencent_quote, mock_hithink_none, monkeypatch):
        """eps_26=0 → 不计算 pe_26e（if eps_26 and eps_26 > 0）。"""
        monkeypatch.setattr(astock, "profit_forecast", lambda code: [
            {"年度": "2026", "均值": "0", "预测机构数": "3"}
        ])
        fv = astock.full_valuation("600519")
        assert fv["eps_26e"] == 0.0
        assert fv["pe_26e"] is None  # 0 不 > 0，跳过

    def test_forecast_analyst_count_invalid(self, mock_tencent_quote, mock_hithink_none, monkeypatch):
        """预测机构数非数字 → analyst_count=0（降级不崩）。"""
        monkeypatch.setattr(astock, "profit_forecast", lambda code: [
            {"年度": "2026", "均值": "50.0", "预测机构数": "abc"}
        ])
        fv = astock.full_valuation("600519")
        assert fv["eps_26e"] == 50.0
        assert fv["analyst_count"] == 0  # 解析失败降级 0

    def test_forecast_2027_only(self, mock_tencent_quote, mock_hithink_none, monkeypatch):
        """只有 2027 EPS（无 2026）→ eps_27e 填，pe_26e/cagr 不计算。"""
        monkeypatch.setattr(astock, "profit_forecast", lambda code: [
            {"年度": "2027", "均值": "60.0", "预测机构数": "5"}
        ])
        fv = astock.full_valuation("600519")
        assert fv["eps_26e"] is None
        assert fv["eps_27e"] == 60.0
        assert fv["pe_26e"] is None
        assert fv["cagr_pct"] is None


class TestFullValuationCrossValidate:
    """cross_validate 路径——PE/PB 东财 vs hithink 仲裁。"""

    def test_discrepancy_when_major_diff(self, mock_tencent_quote, mock_profit_forecast_none, monkeypatch):
        """东财 PE=25, hithink PE=30 → 偏差 20%（>5%）→ 标 discrepancy。"""
        monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot", lambda codes: {
            "600519": {"ps_ttm": None, "pcf_ttm": None, "pe_ttm": 30.0, "pb_mrq": 8.0}
        })
        fv = astock.full_valuation("600519")
        # pe_ttm 东财 25 vs hithink 30 → 偏差 20% > 5% → MAJOR_DIFFERENCE
        assert "discrepancy" in fv
        disc = fv["discrepancy"]
        fields = [d["field"] for d in disc]
        assert "pe_ttm" in fields

    def test_no_discrepancy_when_consistent(self, mock_tencent_quote, mock_profit_forecast_none, monkeypatch):
        """东财 PE=25, hithink PE=25.1 → 偏差 0.4%（≤1%）→ 无 discrepancy 标。"""
        monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot", lambda codes: {
            "600519": {"ps_ttm": None, "pcf_ttm": None, "pe_ttm": 25.1, "pb_mrq": 8.0}
        })
        fv = astock.full_valuation("600519")
        # CONSISTENT 不标
        assert "discrepancy" not in fv or fv.get("discrepancy") is None

    def test_no_discrepancy_when_hithink_missing(self, mock_tencent_quote, mock_profit_forecast_none, monkeypatch):
        """hithink 无 PE/PB（None）→ 两源缺一 → SINGLE_SOURCE，不标 discrepancy。"""
        monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot", lambda codes: {
            "600519": {"ps_ttm": None, "pcf_ttm": None, "pe_ttm": None, "pb_mrq": None}
        })
        fv = astock.full_valuation("600519")
        assert "discrepancy" not in fv

    def test_cross_validate_exception_no_crash(self, mock_tencent_quote, mock_profit_forecast_none, monkeypatch):
        """cross_validate 模块 import 失败/异常 → 吞，不崩估值。"""
        monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot", lambda codes: {
            "600519": {"ps_ttm": None, "pcf_ttm": None, "pe_ttm": 25.0, "pb_mrq": 8.0}
        })
        # 让 cross_validate 抛异常
        import data.validators as vv
        original = vv.cross_validate
        def _raise(field, values):
            raise RuntimeError("validator crash")
        monkeypatch.setattr(vv, "cross_validate", _raise)
        try:
            fv = astock.full_valuation("600519")
            # 不崩，估值正常返
            assert fv["pe_ttm"] == 25.0
        finally:
            monkeypatch.setattr(vv, "cross_validate", original)


# ════════════════════════════════════════════════════════════════════════════
# 门面 re-export + 辅助函数（补 test_s008_sources_facade 未覆盖）
# ════════════════════════════════════════════════════════════════════════════


class TestReExports:
    """re-export 完整性 + get_prefix 边界。"""

    def test_get_prefix_sh(self):
        """6/9/5 开头 → sh（沪市主板/科创板/基金）。"""
        assert astock.get_prefix("600519") == "sh"
        assert astock.get_prefix("688981") == "sh"
        assert astock.get_prefix("900001") == "sh"  # B 股
        assert astock.get_prefix("510300") == "sh"  # ETF

    def test_get_prefix_sz(self):
        """0/3 开头 → sz（深市主板/创业板）。"""
        assert astock.get_prefix("000001") == "sz"
        assert astock.get_prefix("300750") == "sz"

    def test_get_prefix_bj(self):
        """8 开头 → bj（北交所）。"""
        assert astock.get_prefix("830799") == "bj"

    def test_dependency_missing_class(self):
        """DependencyMissing 可实例化 + 是 RuntimeError 子类。"""
        exc = astock.DependencyMissing("test")
        assert isinstance(exc, RuntimeError)
        assert "test" in str(exc)

    def test_ua_non_empty(self):
        """UA 是非空字符串（HTTP 头）。"""
        assert isinstance(astock.UA, str)
        assert len(astock.UA) > 0


class TestParseGtimg:
    """_parse_gtimg 解析腾讯 gtimg 响应。"""

    def test_empty_string(self):
        """空字符串 → {}。"""
        assert astock._parse_gtimg("") == {}

    def test_malformed_line_skipped(self):
        """坏行（无 = 或无 "）跳过。"""
        assert astock._parse_gtimg("garbage;another_bad") == {}

    def test_normal_parse(self):
        """正常解析 1 行 → 含全字段 raw dict。"""
        parts = ["0"] * 55
        parts[1] = "贵州茅台"
        parts[3] = "1500.0"  # price
        parts[4] = "1480.0"  # last_close
        parts[44] = "18800.0"  # mcap_yi
        parts[46] = "8.0"  # pb
        line = f'v_sh600519="' + "~".join(parts) + '";'
        result = astock._parse_gtimg(line)
        assert "600519" in result
        q = result["600519"]
        assert q["name"] == "贵州茅台"
        assert q["price"] == 1500.0
        assert q["last_close"] == 1480.0
        assert q["mcap_yi"] == 18800.0
        assert q["pb"] == 8.0
        # 五档买卖盘
        assert len(q["buy"]) == 5
        assert len(q["sell"]) == 5

    def test_short_vals_skipped(self):
        """vals 长度 < 53 → 该行跳过（不崩）。"""
        line = 'v_sh600519="a~b~c";'
        assert astock._parse_gtimg(line) == {}
