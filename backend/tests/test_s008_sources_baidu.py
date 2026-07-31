# -*- coding: utf-8 -*-
"""S008 百度股市通源单测：锁住 fetch_raw 返回 parsed raw bars（OHLCV + MA5/10/20）。

百度股市通是当前公司网下**唯一不限流**的个股日K线源（东财 push2his 被封），
直接解 S017 panel OOS 的 kline 阻塞；且自带 ma5/ma10/ma20，免本地重算。

实测百度 schema（2026-07-31 live 验证）：keys 含 ``timestamp``（unix 秒 CST）与
``time``（YYYY-MM-DD 日期串），无 ``date`` key；早期 bar 的 MA 字段为 "--"。
marketData 为 ';'-分隔、每行 ','-联接的值串（与 keys 顺序对齐）。

不变量：
- ``fetch_raw(code)`` 返 ``list[dict]``（与 mootdx kline 一致的 raw bars 形状），
  每 bar 含 date/open/close/high/low/volume/amount/ma5/ma10/ma20，缺字段=None（不臆造）；
- keys 顺序无关——按 key 名索引，对百度字段顺序变动鲁棒；
- date 优先取 ``time``（日期串），否则从 ``timestamp``（unix 秒）转 CST(UTC+8)。
"""
from data.sources import baidu


def _sample_response() -> dict:
    """百度股市通真实返回形状（Result.newMarketData.{keys,marketData}）。"""
    keys = ["timestamp", "time", "open", "close", "volume", "high", "low",
            "amount", "range", "ratio", "turnoverratio", "preClose",
            "ma5avgprice", "ma5volume", "ma10avgprice", "ma10volume",
            "ma20avgprice", "ma20volume"]
    # 两根 bar：2018-05-07 / 2018-05-08（茅台除权前早期数据，MA 已有）
    rows = ";".join([
        "1525622400,2018-05-07,375.15,413.37,8559143,417.08,372.97,5858519223.00,+35.30,+9.34,0.68,378.07,--,--,--,--,--,--",
        "1525708800,2018-05-08,413.37,440.00,9000000,445.00,410.00,6200000000.00,+26.63,+6.43,0.72,413.37,425.0,--,430.0,--,435.0,--",
    ])
    return {"Result": {"newMarketData": {"keys": keys, "marketData": rows}}}


def test_fetch_raw_returns_parsed_bars(monkeypatch):
    monkeypatch.setattr(baidu, "_fetch_json", lambda code, start_time="": _sample_response())
    bars = baidu.fetch_raw("600519")
    assert len(bars) == 2
    b = bars[-1]
    assert b["date"] == "2018-05-08"          # time 字段（日期串）
    assert b["open"] == 413.37
    assert b["close"] == 440.00
    assert b["high"] == 445.00
    assert b["low"] == 410.00
    assert b["volume"] == 9000000
    assert b["amount"] == 6_200_000_000.0
    assert b["ma5"] == 425.0
    assert b["ma10"] == 430.0
    assert b["ma20"] == 435.0


def test_fetch_raw_ma_dashes_become_none(monkeypatch):
    """早期 bar MA 字段为 '--' → None，不臆造 0。"""
    monkeypatch.setattr(baidu, "_fetch_json", lambda code, start_time="": _sample_response())
    bars = baidu.fetch_raw("600519")
    b0 = bars[0]  # 第一根 MA 全 '--'
    assert b0["close"] == 413.37
    assert b0["ma5"] is None
    assert b0["ma10"] is None
    assert b0["ma20"] is None


def test_fetch_raw_key_order_independent(monkeypatch):
    """keys 顺序变动不影响解析（按 key 名索引）。"""
    keys = ["close", "time", "open", "ma5avgprice", "high", "low",
            "ma10avgprice", "volume", "timestamp", "amount", "ma20avgprice"]
    # values 按 keys 顺序：close=440, time=2018-05-08, open=413.37, ma5=425.0,
    # high=445.0, low=410.0, ma10=430.0, volume=9000000, timestamp=1525708800,
    # amount=6.2e9, ma20=435.0
    rows = ("440.00,2018-05-08,413.37,425.0,445.00,410.00,"
            "430.0,9000000,1525708800,6200000000.00,435.0")
    monkeypatch.setattr(
        baidu, "_fetch_json",
        lambda code, start_time="": {"Result": {"newMarketData": {"keys": keys, "marketData": rows}}},
    )
    bars = baidu.fetch_raw("600519")
    assert len(bars) == 1
    b = bars[0]
    assert b["date"] == "2018-05-08"
    assert b["close"] == 440.00
    assert b["open"] == 413.37
    assert b["ma5"] == 425.0
    assert b["ma10"] == 430.0
    assert b["ma20"] == 435.0


def test_fetch_raw_date_from_timestamp_when_no_time(monkeypatch):
    """无 time(日期串) key 时，从 timestamp(unix 秒) 按 CST(UTC+8) 转 YYYY-MM-DD。"""
    keys = ["timestamp", "open", "close", "high", "low", "volume"]
    # 1525622400 = 2018-05-06 16:00 UTC = 2018-05-07 00:00 CST
    rows = "1525622400,375.15,413.37,417.08,372.97,8559143"
    monkeypatch.setattr(
        baidu, "_fetch_json",
        lambda code, start_time="": {"Result": {"newMarketData": {"keys": keys, "marketData": rows}}},
    )
    bars = baidu.fetch_raw("600519")
    assert bars[0]["date"] == "2018-05-07"


def test_fetch_raw_missing_fields_are_none_no_fabrication(monkeypatch):
    """缺 ma/open 等字段 → None，不臆造 0。"""
    keys = ["timestamp", "time", "close", "volume"]
    rows = "1525622400,2018-05-07,413.37,8559143"
    monkeypatch.setattr(
        baidu, "_fetch_json",
        lambda code, start_time="": {"Result": {"newMarketData": {"keys": keys, "marketData": rows}}},
    )
    bars = baidu.fetch_raw("600519")
    b = bars[0]
    assert b["close"] == 413.37
    assert b["open"] is None
    assert b["high"] is None
    assert b["low"] is None
    assert b["ma5"] is None
    assert b["ma10"] is None
    assert b["ma20"] is None


def test_fetch_raw_empty_marketdata(monkeypatch):
    monkeypatch.setattr(
        baidu, "_fetch_json",
        lambda code, start_time="": {"Result": {"newMarketData": {"keys": ["timestamp"], "marketData": ""}}},
    )
    assert baidu.fetch_raw("600519") == []


def test_fetch_raw_bad_rows_ignored(monkeypatch):
    keys = ["time", "close"]
    rows = "2018-05-07,413.37;garbage;line;2018-05-08,440.00"
    monkeypatch.setattr(
        baidu, "_fetch_json",
        lambda code, start_time="": {"Result": {"newMarketData": {"keys": keys, "marketData": rows}}},
    )
    bars = baidu.fetch_raw("600519")
    assert len(bars) == 2  # garbage/line 字段不足跳过


# ── mapper ──────────────────────────────────────────────────────────────

def test_baidu_kline_from_dict_maps_to_klinebar():
    from data.mappers import baidu_kline_from_dict
    bars = [
        {"date": "2018-05-07", "open": 375.15, "close": 413.37, "high": 417.08,
         "low": 372.97, "volume": 8559143, "amount": 5.858e9, "ma5": None},
        {"date": "2018-05-08", "open": 413.37, "close": 440.00, "high": 445.00,
         "low": 410.00, "volume": 9000000, "amount": 6.2e9, "ma5": 425.0},
    ]
    k = baidu_kline_from_dict("600519", bars)
    assert k.code == "600519"
    assert len(k.bars) == 2
    b = k.bars[-1]
    assert b.date == "2018-05-08"
    assert b.close == 440.00
    assert b.volume == 9000000
    assert b.turnover == 6.2e9      # amount -> turnover
    assert b.ma5 == 425.0
    b0 = k.bars[0]
    assert b0.ma5 is None            # None 透传


def test_baidu_kline_from_dict_partial_bar_no_fabrication():
    from data.mappers import baidu_kline_from_dict
    bars = [{"date": "2018-05-08", "close": 440.00}]  # 仅 close+date
    k = baidu_kline_from_dict("600519", bars)
    b = k.bars[0]
    assert b.close == 440.00
    assert b.open is None
    assert b.high is None
    assert b.ma5 is None


def test_baidu_kline_from_dict_empty():
    from data.mappers import baidu_kline_from_dict
    k = baidu_kline_from_dict("600519", [])
    assert k.bars == ()
