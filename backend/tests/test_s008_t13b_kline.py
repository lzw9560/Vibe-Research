# -*- coding: utf-8 -*-
"""S008 T13b：kline mapper + risk_models/backtest_lite 迁 KLine 模型。

锁住：
- ``kline_from_mootdx`` 映射 raw bars（含部分 bar：仅 close+amount）→ KLine，
  ``vol``→``volume``、``amount``→``turnover``、缺字段=None（不臆造）；
- ``_bar_date`` 从 year/month/day 分量或 date/datetime 字符串归一 YYYY-MM-DD；
- risk_models 三函数经模型读 close/turnover（波动率/回撤/流动性），部分 bar 不崩；
- backtest_lite._calc_next_day_return 经模型读 date/close。
"""
import asyncio

import astock
import backtest_lite
import risk_models
from data.mappers import _bar_date, kline_from_mootdx


def _full_bars() -> list[dict]:
    """mootdx 全字段 bar（含 OHLC/date/vol/amount）。"""
    return [
        {"date": "2026-07-25", "open": 10.0, "close": 10.5, "high": 10.8,
         "low": 9.9, "vol": 1000, "amount": 60_000_000},
        {"date": "2026-07-26", "open": 10.5, "close": 10.4, "high": 10.7,
         "low": 10.2, "vol": 1200, "amount": 55_000_000},
    ]


def _partial_bars(n: int = 25, close: float = 10.0, amount: float = 60_000_000) -> list[dict]:
    """部分 bar（仅 close+amount，仿 test_s008_bugs 的 _fake_bars）。"""
    return [{"close": round(close * (1.005 ** i), 2), "amount": amount} for i in range(n)]


# ── mapper ───────────────────────────────────────────────────────────────

def test_kline_from_mootdx_full_bars():
    k = kline_from_mootdx("600519", _full_bars())
    assert k.code == "600519"
    assert len(k.bars) == 2
    b0 = k.bars[0]
    assert b0.date == "2026-07-25"
    assert b0.open == 10.0
    assert b0.close == 10.5
    assert b0.high == 10.8
    assert b0.low == 9.9
    assert b0.volume == 1000            # vol -> volume, int
    assert b0.turnover == 60_000_000.0   # amount -> turnover


def test_kline_from_mootdx_partial_bars_no_fabrication():
    """部分 bar（缺 OHLC/date）：缺字段=None，不臆造 0。"""
    k = kline_from_mootdx("600519", _partial_bars(3))
    assert len(k.bars) == 3
    b = k.bars[0]
    assert b.close is not None          # 有 close
    assert b.open is None                # 缺 open → None（不臆造 0）
    assert b.high is None
    assert b.low is None
    assert b.date is None
    assert b.turnover is not None        # amount -> turnover


def test_bar_date_from_components():
    assert _bar_date({"year": 2026, "month": 7, "day": 25}) == "2026-07-25"
    assert _bar_date({"date": "2026-07-25 15:00:00"}) == "2026-07-25"  # 截前 10
    assert _bar_date({"datetime": "2026-07-26"}) == "2026-07-26"
    assert _bar_date({"foo": 1}) is None


def test_kline_empty():
    k = kline_from_mootdx("600519", [])
    assert k.bars == ()


# ── risk_models 经模型读字段 ─────────────────────────────────────────────

def test_risk_volatility_via_model(monkeypatch):
    monkeypatch.setattr(astock, "kline", lambda code, offset=60: _partial_bars(30, 10.0))
    v = asyncio.run(risk_models._calculate_volatility("600519", window=20))
    assert v > 0


def test_risk_max_drawdown_via_model(monkeypatch):
    bars = [{"close": 10.0, "amount": 60_000_000}] + [
        {"close": round(10.0 * (1.01 ** i), 2), "amount": 60_000_000} for i in range(1, 40)
    ] + [{"close": round(10.0 * (1.01 ** 39) * 0.85, 2), "amount": 60_000_000}]
    monkeypatch.setattr(astock, "kline", lambda code, offset=60: bars)
    dd = asyncio.run(risk_models._calculate_max_drawdown("600519", window=60))
    assert dd > 0


def test_risk_liquidity_via_model(monkeypatch):
    monkeypatch.setattr(astock, "kline", lambda code, offset=20: _partial_bars(20, 10.0))
    assert asyncio.run(risk_models._calculate_liquidity_risk("600519")) == 0.0  # 60M > 50M
    low = [{"close": 10.0, "amount": 10_000_000} for _ in range(20)]
    monkeypatch.setattr(astock, "kline", lambda code, offset=20: low)
    assert asyncio.run(risk_models._calculate_liquidity_risk("600519")) > 0


# ── backtest_lite 经模型读 date/close ───────────────────────────────────

def test_backtest_next_day_return_via_model(monkeypatch):
    """date 命中 → 用 close 算次日收益；经模型读 date/close。"""
    bars = [
        {"date": "2026-07-25", "close": 10.0, "amount": 1},
        {"date": "2026-07-26", "close": 11.0, "amount": 1},
    ]
    monkeypatch.setattr(astock, "kline", lambda code, category=4, offset=5: bars)
    ret = backtest_lite._calc_next_day_return("600519", "2026-07-25")
    assert abs(ret - (11.0 - 10.0) / 10.0) < 1e-9


def test_backtest_next_day_return_no_date_match(monkeypatch):
    """date 不命中 → 返 0（经模型读 date，部分 bar 无 date 不崩）。"""
    monkeypatch.setattr(astock, "kline", lambda code, category=4, offset=5: _partial_bars(3))
    assert backtest_lite._calc_next_day_return("600519", "2026-07-25") == 0.0
