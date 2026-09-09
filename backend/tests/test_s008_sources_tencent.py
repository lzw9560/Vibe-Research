# -*- coding: utf-8 -*-
"""S008 腾讯源单测：锁住 fetch_raw 返回**全字段** raw（无字段丢失）。

数据总线设计的核心不变量：raw 是单一事实源，含 last_close/open/vol_ratio/pe_static
等被 bidding_monitor / candidate_funnel 活跃消费的字段——任何投影不得丢这些。
"""
from data.sources import tencent


def _gtimg_full() -> str:
    """构造一条含全部关键字段的腾讯行情返回行（≥53 字段）。"""
    parts = ["0"] * 55
    parts[1] = "贵州茅台"
    parts[3] = "1194.45"   # price
    parts[4] = "1180.0"    # last_close
    parts[5] = "1190.0"    # open
    parts[32] = "1.2"      # change_pct
    parts[33] = "1200.0"  # high
    parts[34] = "1185.0"  # low
    parts[37] = "123456"  # amount_wan
    parts[39] = "18.05"   # pe_ttm
    parts[44] = "15000"   # mcap_yi
    parts[46] = "6.41"    # pb
    parts[49] = "2.3"      # vol_ratio
    parts[52] = "17.9"    # pe_static
    return 'v_sh600519="' + "~".join(parts) + '";'


def test_fetch_raw_returns_full_fields(monkeypatch):
    monkeypatch.setattr(tencent, "_TENCENT_CACHE", {})  # S067 缓存隔离：清缓存防先前测试的实盘值短路 _fetch_gtimg mock
    monkeypatch.setattr(tencent, "_fetch_gtimg", lambda codes: _gtimg_full())
    out = tencent.fetch_raw(["600519"])
    q = out["600519"]
    # 核心字段齐全
    assert q["name"] == "贵州茅台"
    assert q["price"] == 1194.45
    assert q["last_close"] == 1180.0
    assert q["open"] == 1190.0
    assert q["high"] == 1200.0
    assert q["low"] == 1185.0
    assert q["vol_ratio"] == 2.3
    assert q["pe_static"] == 17.9
    assert q["pe_ttm"] == 18.05
    assert q["mcap_yi"] == 15000
    assert q["change_pct"] == 1.2


def test_index_raw_returns_four_indices(monkeypatch):
    # 构造 4 条指数行
    def fake_fetch(codes):
        lines = []
        for c in codes:
            parts = ["0"] * 55
            parts[1] = c
            parts[3] = "100"
            parts[32] = "0.5"
            parts[31] = "0.5"
            lines.append(f'v_{c}="' + "~".join(parts) + '";')
        return ";".join(lines)

    monkeypatch.setattr(tencent, "_fetch_gtimg", fake_fetch)
    out = tencent.index_raw()
    assert len(out) == 4
    assert all("name" in x and "price" in x for x in out)


def test_parse_gtimg_bad_lines_ignored():
    assert tencent._parse_gtimg("garbage;no_quotes_here;") == {}
    assert tencent._parse_gtimg("") == {}


def test_parse_gtimg_five_level_bid_ask(monkeypatch):
    """五档买卖盘提取（fields 9-28）：buy/sell 各 5 档 {level, price, vol}。

    vol=手×100→股，与 eastmoney bids() 同口径——可替代/并行。
    """
    monkeypatch.setattr(tencent, "_TENCENT_CACHE", {})
    parts = ["0"] * 55
    parts[1] = "测试股"
    parts[3] = "10.50"  # price
    # 买1-5 (price, vol) — vol 单位=手
    parts[9] = "10.49";  parts[10] = "120"   # 买1: 10.49元, 120手→12000股
    parts[11] = "10.48"; parts[12] = "80"    # 买2
    parts[13] = "10.47"; parts[14] = "60"    # 买3
    parts[15] = "10.46"; parts[16] = "40"    # 买4
    parts[17] = "10.45"; parts[18] = "20"    # 买5
    # 卖1-5 (price, vol)
    parts[19] = "10.51"; parts[20] = "100"   # 卖1
    parts[21] = "10.52"; parts[22] = "90"    # 卖2
    parts[23] = "10.53"; parts[24] = "70"    # 卖3
    parts[25] = "10.54"; parts[26] = "50"    # 卖4
    parts[27] = "10.55"; parts[28] = "30"   # 卖5
    raw = 'v_sz002980="' + "~".join(parts) + '";'

    monkeypatch.setattr(tencent, "_fetch_gtimg", lambda codes: raw)
    out = tencent.fetch_raw(["002980"])
    q = out["002980"]

    assert len(q["buy"]) == 5
    assert len(q["sell"]) == 5

    # 买1-5：价格递减，vol=手×100→股
    assert q["buy"][0] == {"level": 1, "price": 10.49, "vol": 12000.0}
    assert q["buy"][1] == {"level": 2, "price": 10.48, "vol": 8000.0}
    assert q["buy"][2] == {"level": 3, "price": 10.47, "vol": 6000.0}
    assert q["buy"][3] == {"level": 4, "price": 10.46, "vol": 4000.0}
    assert q["buy"][4] == {"level": 5, "price": 10.45, "vol": 2000.0}

    # 卖1-5：价格递增
    assert q["sell"][0] == {"level": 1, "price": 10.51, "vol": 10000.0}
    assert q["sell"][1] == {"level": 2, "price": 10.52, "vol": 9000.0}
    assert q["sell"][2] == {"level": 3, "price": 10.53, "vol": 7000.0}
    assert q["sell"][3] == {"level": 4, "price": 10.54, "vol": 5000.0}
    assert q["sell"][4] == {"level": 5, "price": 10.55, "vol": 3000.0}
