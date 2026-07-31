# -*- coding: utf-8 -*-
"""S008 新浪日K线源单测：锁住 fetch_raw 返回 parsed raw bars（OHLCV，无 MA）。

新浪作为百度源的异构回退——多源链 ``baidu → sina → mootdx → akshare``
保证不同网络环境至少一源可达，不硬编码单源策略。
"""
from data.sources import sina


def _sample_raw() -> list[dict]:
    """新浪 CN_MarketData.getKLineData 返回（字符串字段）。"""
    return [
        {"day": "2026-07-30", "open": "1330.00", "high": "1345.00",
         "low": "1326.00", "close": "1336.46", "volume": "3398138"},
        {"day": "2026-07-31", "open": "1330.03", "high": "1345.00",
         "low": "1325.70", "close": "1338.93", "volume": "3665397"},
    ]


def test_fetch_raw_returns_parsed_bars(monkeypatch):
    monkeypatch.setattr(sina, "_fetch_json", lambda code, datalen=1023: _sample_raw())
    bars = sina.fetch_raw("600519")
    assert len(bars) == 2
    b = bars[-1]
    assert b["date"] == "2026-07-31"
    assert b["open"] == 1330.03
    assert b["close"] == 1338.93
    assert b["high"] == 1345.00
    assert b["low"] == 1325.70
    assert b["volume"] == 3665397
    assert b["amount"] is None        # 新浪日K不带成交额
    assert b["ma5"] is None           # 新浪不带 MA
    assert b["ma10"] is None
    assert b["ma20"] is None


def test_fetch_raw_missing_fields_none(monkeypatch):
    monkeypatch.setattr(sina, "_fetch_json",
                        lambda code, datalen=1023: [{"day": "2026-07-31", "close": "1338.93"}])
    bars = sina.fetch_raw("600519")
    b = bars[0]
    assert b["close"] == 1338.93
    assert b["open"] is None
    assert b["high"] is None
    assert b["volume"] is None


def test_fetch_raw_dash_volume_becomes_none(monkeypatch):
    monkeypatch.setattr(sina, "_fetch_json",
                        lambda code, datalen=1023: [{"day": "2026-07-31", "close": "1338.93", "volume": "-"}])
    bars = sina.fetch_raw("600519")
    assert bars[0]["volume"] is None


def test_fetch_raw_empty(monkeypatch):
    monkeypatch.setattr(sina, "_fetch_json", lambda code, datalen=1023: [])
    assert sina.fetch_raw("600519") == []
