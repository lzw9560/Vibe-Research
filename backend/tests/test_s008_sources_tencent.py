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
