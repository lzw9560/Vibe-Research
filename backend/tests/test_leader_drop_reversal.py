# -*- coding: utf-8 -*-
"""S203 T5: LeaderDropReversalStrategy（龙头大跌反包）test（TDD）。

验证 C1 龙头确认 / C2 T-1 大跌≥7% / C3 T 吞没 / C4 放量≥1.2x + 无 bars data_unavailable 降级。
大跌从 close/open 复算（不依赖 pctChg，R14 注入前可用）。
"""
from __future__ import annotations

from types import SimpleNamespace

from strategies.impl.gene_based import LeaderDropReversalStrategy


def _ctx(gene=None, msc=None):
    return SimpleNamespace(gene=gene, market_scan_ctx=msc)


def _gene(high_gene=None):
    return SimpleNamespace(high_gene=high_gene, total_score=50)


def _bar(open_, high, low, close, volume):
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume, "amount": 0}


def test_c2_drop_7pct_hit():
    """C2 T-1 日内大跌≥7%（close 相对 open 跌≥7%）命中。"""
    s = LeaderDropReversalStrategy()
    # T-1: open=10, close=9.3 → 跌 7% (≤-7%)
    bars = [_bar(10.0, 10.0, 9.2, 9.3, 100), _bar(9.5, 10.5, 9.5, 10.2, 150)]
    msc = {"bars": bars}
    r = s.match(_ctx(gene=_gene(high_gene=1), msc=msc))
    c2 = [c for c in r.conditions if c.condition_id == "leader_drop_reversal.c2"][0]
    assert c2.state == "hit"


def test_c2_drop_below_7pct_miss():
    """C2 T-1 跌<7% 不命中。"""
    s = LeaderDropReversalStrategy()
    bars = [_bar(10.0, 10.0, 9.5, 9.6, 100), _bar(9.7, 10.5, 9.7, 10.2, 150)]  # 跌 4%
    r = s.match(_ctx(gene=_gene(high_gene=1), msc={"bars": bars}))
    c2 = [c for c in r.conditions if c.condition_id == "leader_drop_reversal.c2"][0]
    assert c2.state == "miss"
    assert r.fired is False


def test_c3_engulf_hit():
    """C3 T 吞没（curr.close≥prev.open & curr.open≤prev.close）命中。"""
    s = LeaderDropReversalStrategy()
    # T-1: open=10 close=9.3; T: open=9.2(≤9.3) close=10.1(≥10)
    bars = [_bar(10.0, 10.0, 9.2, 9.3, 100), _bar(9.2, 10.5, 9.2, 10.1, 150)]
    r = s.match(_ctx(gene=_gene(high_gene=1), msc={"bars": bars}))
    c3 = [c for c in r.conditions if c.condition_id == "leader_drop_reversal.c3"][0]
    assert c3.state == "hit"


def test_c4_volume_1_2x_hit():
    """C4 放量≥1.2x 命中。"""
    s = LeaderDropReversalStrategy()
    bars = [_bar(10.0, 10.0, 9.2, 9.3, 100), _bar(9.2, 10.5, 9.2, 10.1, 150)]  # 150/100=1.5≥1.2
    r = s.match(_ctx(gene=_gene(high_gene=1), msc={"bars": bars}))
    c4 = [c for c in r.conditions if c.condition_id == "leader_drop_reversal.c4"][0]
    assert c4.state == "hit"


def test_all_hit_fired():
    """四条件全 hit → fired, confidence=0.55。"""
    s = LeaderDropReversalStrategy()
    # T-1: open=10 close=9.3(跌7%); T: open=9.2(≤9.3) close=10.1(≥10) vol=150(1.5x)
    bars = [_bar(10.0, 10.0, 9.2, 9.3, 100), _bar(9.2, 10.5, 9.2, 10.1, 150)]
    r = s.match(_ctx(gene=_gene(high_gene=1), msc={"bars": bars}))
    assert r.fired is True
    assert r.hit_count == 4
    assert r.confidence == 0.55


def test_no_bars_data_unavailable():
    """无 bars（涨停 pipeline 不构造 msc.bars）→ C2/C3/C4 data_unavailable，C1 可评。"""
    s = LeaderDropReversalStrategy()
    r = s.match(_ctx(gene=_gene(high_gene=1), msc={}))  # 无 bars
    c2 = [c for c in r.conditions if c.condition_id == "leader_drop_reversal.c2"][0]
    c3 = [c for c in r.conditions if c.condition_id == "leader_drop_reversal.c3"][0]
    c4 = [c for c in r.conditions if c.condition_id == "leader_drop_reversal.c4"][0]
    c1 = [c for c in r.conditions if c.condition_id == "leader_drop_reversal.c1"][0]
    assert c1.state == "hit"  # high_gene=1 可评
    assert c2.state == "data_unavailable"  # 无 bars
    assert c3.state == "data_unavailable"
    assert c4.state == "data_unavailable"
    assert r.fired is False  # C2/C3/C4 data_unavailable → 不 fired


def test_no_bars_no_gene_full_data_unavailable():
    """无 bars + 无龙头确认 → 整战法 data_unavailable。"""
    s = LeaderDropReversalStrategy()
    r = s.match(_ctx(gene=_gene(high_gene=None), msc=None))
    assert r.fired is False
    assert all(c.state == "data_unavailable" for c in r.conditions)


def test_c1_sector_rank_3_hit():
    """C1 sector_rank≤3 也算龙头确认（high_gene None 时）。"""
    s = LeaderDropReversalStrategy()
    bars = [_bar(10.0, 10.0, 9.2, 9.3, 100), _bar(9.2, 10.5, 9.2, 10.1, 150)]
    r = s.match(_ctx(gene=_gene(high_gene=None), msc={"bars": bars, "sector_rank": 2}))
    c1 = [c for c in r.conditions if c.condition_id == "leader_drop_reversal.c1"][0]
    assert c1.state == "hit"  # sector_rank=2≤3


def test_c1_non_leader_miss():
    """C1 非龙头（high_gene=0 + sector_rank=5）不命中。"""
    s = LeaderDropReversalStrategy()
    bars = [_bar(10.0, 10.0, 9.2, 9.3, 100), _bar(9.2, 10.5, 9.2, 10.1, 150)]
    r = s.match(_ctx(gene=_gene(high_gene=0), msc={"bars": bars, "sector_rank": 5}))
    c1 = [c for c in r.conditions if c.condition_id == "leader_drop_reversal.c1"][0]
    assert c1.state == "miss"
    assert r.fired is False


def test_drop_from_close_not_pctchg():
    """大跌从 close/open 复算（不依赖 pctChg 字段，R14 注入前可用）。"""
    s = LeaderDropReversalStrategy()
    # bars 无 pctChg 字段，从 close/open 算
    bars = [{"open": 10.0, "high": 10.0, "low": 9.2, "close": 9.3, "volume": 100},
            {"open": 9.2, "high": 10.5, "low": 9.2, "close": 10.1, "volume": 150}]
    r = s.match(_ctx(gene=_gene(high_gene=1), msc={"bars": bars}))
    c2 = [c for c in r.conditions if c.condition_id == "leader_drop_reversal.c2"][0]
    assert c2.state == "hit"  # 跌 7%，无 pctChg 也能算
