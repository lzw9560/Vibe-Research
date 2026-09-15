# -*- coding: utf-8 -*-
"""S203 T6: Relay23Strategy（接力二三板）test（TDD）。

验证 C1 当下连板 lbc≥2 / C2 量比 [1.5,2.5] / C3 Dragon Score 占位（data_unavailable 不阻塞 fire）
+ 无 lbc/bars data_unavailable 降级。
lbc 从涨停池 raw 取（区别 consecutive_relay 的 250 日历史频次）；量比 T/T-1 volume。
"""
from __future__ import annotations

from types import SimpleNamespace

from strategies.impl.gene_based import Relay23Strategy


def _ctx(msc: dict | None = None):
    return SimpleNamespace(market_scan_ctx=msc)


def _bar(open_, high, low, close, volume):
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume, "amount": 0}


def _bars(prev_vol: float, curr_vol: float):
    """[T-1, T]（date asc 尾部 2 bars），只关心 volume。"""
    return [
        _bar(10.0, 10.0, 9.5, 9.6, prev_vol),
        _bar(9.7, 10.5, 9.7, 10.2, curr_vol),
    ]


def test_c1_lbc_2_hit():
    """C1 lbc≥2 命中（当下连板接力）。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": 2, "bars": _bars(100, 200)}))
    c1 = [c for c in r.conditions if c.condition_id == "relay_23.c1"][0]
    assert c1.state == "hit"


def test_c1_lbc_3_hit():
    """C1 lbc=3（三板）命中。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": 3, "bars": _bars(100, 200)}))
    c1 = [c for c in r.conditions if c.condition_id == "relay_23.c1"][0]
    assert c1.state == "hit"


def test_c1_lbc_1_miss():
    """C1 lbc=1（首板非连板）不命中。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": 1, "bars": _bars(100, 200)}))
    c1 = [c for c in r.conditions if c.condition_id == "relay_23.c1"][0]
    assert c1.state == "miss"
    assert r.fired is False


def test_c1_lbc_none_data_unavailable():
    """C1 lbc 缺失 → data_unavailable（字段级降级，非整战法）。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": None, "bars": _bars(100, 200)}))
    c1 = [c for c in r.conditions if c.condition_id == "relay_23.c1"][0]
    assert c1.state == "data_unavailable"
    assert r.fired is False
    assert r.data_ok is True


def test_c2_vol_ratio_1_5_hit():
    """C2 量比 1.5（下界，闭区间）命中。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": 2, "bars": _bars(100, 150)}))  # 150/100=1.5
    c2 = [c for c in r.conditions if c.condition_id == "relay_23.c2"][0]
    assert c2.state == "hit"


def test_c2_vol_ratio_2_5_hit():
    """C2 量比 2.5（上界，闭区间）命中。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": 2, "bars": _bars(100, 250)}))  # 250/100=2.5
    c2 = [c for c in r.conditions if c.condition_id == "relay_23.c2"][0]
    assert c2.state == "hit"


def test_c2_vol_ratio_1_4_miss():
    """C2 量比 1.4（<1.5，缩量不足）不命中。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": 2, "bars": _bars(100, 140)}))
    c2 = [c for c in r.conditions if c.condition_id == "relay_23.c2"][0]
    assert c2.state == "miss"
    assert r.fired is False


def test_c2_vol_ratio_2_6_miss():
    """C2 量比 2.6（>2.5，爆量过度）不命中。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": 2, "bars": _bars(100, 260)}))
    c2 = [c for c in r.conditions if c.condition_id == "relay_23.c2"][0]
    assert c2.state == "miss"
    assert r.fired is False


def test_c2_vol_ratio_midpoint_hit():
    """C2 量比 2.0（区间中段）命中。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": 2, "bars": _bars(100, 200)}))
    c2 = [c for c in r.conditions if c.condition_id == "relay_23.c2"][0]
    assert c2.state == "hit"


def test_c3_dragon_score_placeholder():
    """C3 Dragon Score 占位 → data_unavailable（dimension_registry 接线待，不阻塞 fire）。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": 2, "bars": _bars(100, 200)}))
    c3 = [c for c in r.conditions if c.condition_id == "relay_23.c3"][0]
    assert c3.state == "data_unavailable"
    assert "占位" in c3.description or "接线待" in c3.description


def test_all_hit_fired():
    """C1+C2 hit（C3 占位 data_unavailable 不阻塞）→ fired=True, confidence=0.5。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": 2, "bars": _bars(100, 200)}))  # lbc=2 + 量比 2.0
    assert r.fired is True
    assert r.hit_count == 2  # C1+C2 hit，C3 占位 data_unavailable
    assert r.confidence == 0.5


def test_no_bars_no_lbc_full_data_unavailable():
    """无 lbc + 无 bars → 整战法 data_unavailable。"""
    s = Relay23Strategy()
    r = s.match(_ctx(None))
    assert r.fired is False
    assert r.data_ok is False
    assert all(c.state == "data_unavailable" for c in r.conditions)


def test_bars_only_no_lbc_field_level():
    """有 bars 无 lbc → C2 可评，C1 data_unavailable（字段级降级非整战法）。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"bars": _bars(100, 200)}))  # 无 lbc
    c1 = [c for c in r.conditions if c.condition_id == "relay_23.c1"][0]
    c2 = [c for c in r.conditions if c.condition_id == "relay_23.c2"][0]
    assert c1.state == "data_unavailable"
    assert c2.state == "hit"
    assert r.fired is False  # C1 data_unavailable → 不 fired
    assert r.data_ok is True


def test_bars_insufficient_vol_zero():
    """T-1 volume=0 → 量比无法算，C2 data_unavailable。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": 2, "bars": _bars(0, 200)}))  # T-1 vol=0
    c2 = [c for c in r.conditions if c.condition_id == "relay_23.c2"][0]
    assert c2.state == "data_unavailable"
    assert r.fired is False


def test_bars_single_bar_data_unavailable():
    """bars 仅 1 根 → 量比无法算，C2 data_unavailable。"""
    s = Relay23Strategy()
    r = s.match(_ctx({"lbc": 2, "bars": [_bar(10, 10, 9.5, 9.6, 100)]}))
    c2 = [c for c in r.conditions if c.condition_id == "relay_23.c2"][0]
    assert c2.state == "data_unavailable"
    assert r.fired is False


def test_strategy_code_name():
    """战法 code/name 正确。"""
    s = Relay23Strategy()
    assert s.code == "relay_23"
    assert s.name == "接力二三板"
