# -*- coding: utf-8 -*-
"""S203 T3: FirstBoardLimitupStrategy（首板涨停）test（TDD）。

验证 C1 龙头地位 sector_rank≤3 / C2 板块共振 zt_count_today≥2 / C3 封单精品 seal_to_float_ratio≥0.005
+ 无 msc data_unavailable 降级（涨停 pipeline 不构造 msc，诚实不臆造）。
"""
from __future__ import annotations

from types import SimpleNamespace

from strategies.impl.gene_based import FirstBoardLimitupStrategy


def _ctx(msc: dict | None = None):
    return SimpleNamespace(market_scan_ctx=msc)


def test_c1_sector_rank_3_hit():
    """C1 sector_rank≤3 命中。"""
    s = FirstBoardLimitupStrategy()
    msc = {"sector_rank": 2, "zt_count_today": 3, "seal_to_float_ratio": 0.006, "pattern": object()}
    r = s.match(_ctx(msc))
    c1 = [c for c in r.conditions if c.condition_id == "first_board_limitup.c1"][0]
    assert c1.state == "hit"


def test_c1_sector_rank_5_miss():
    """C1 sector_rank=5 > 3 不命中。"""
    s = FirstBoardLimitupStrategy()
    msc = {"sector_rank": 5, "zt_count_today": 3, "seal_to_float_ratio": 0.006, "pattern": object()}
    r = s.match(_ctx(msc))
    c1 = [c for c in r.conditions if c.condition_id == "first_board_limitup.c1"][0]
    assert c1.state == "miss"
    assert r.fired is False


def test_c2_zt_count_today_2_hit():
    """C2 zt_count_today≥2 命中（板块共振）。"""
    s = FirstBoardLimitupStrategy()
    msc = {"sector_rank": 2, "zt_count_today": 2, "seal_to_float_ratio": 0.006, "pattern": object()}
    r = s.match(_ctx(msc))
    c2 = [c for c in r.conditions if c.condition_id == "first_board_limitup.c2"][0]
    assert c2.state == "hit"


def test_c2_zt_count_today_1_miss():
    """C2 zt_count_today=1 < 2 不命中（无板块共振，秒板陷阱）。"""
    s = FirstBoardLimitupStrategy()
    msc = {"sector_rank": 2, "zt_count_today": 1, "seal_to_float_ratio": 0.006, "pattern": object()}
    r = s.match(_ctx(msc))
    c2 = [c for c in r.conditions if c.condition_id == "first_board_limitup.c2"][0]
    assert c2.state == "miss"
    assert r.fired is False


def test_c3_seal_0_005_hit():
    """C3 seal_to_float_ratio≥0.005 命中（精品封单门槛 0.5%）。"""
    s = FirstBoardLimitupStrategy()
    msc = {"sector_rank": 2, "zt_count_today": 3, "seal_to_float_ratio": 0.005, "pattern": object()}
    r = s.match(_ctx(msc))
    c3 = [c for c in r.conditions if c.condition_id == "first_board_limitup.c3"][0]
    assert c3.state == "hit"


def test_c3_seal_0_003_miss():
    """C3 seal_to_float_ratio=0.003 < 0.005 不命中（封单不够精品）。"""
    s = FirstBoardLimitupStrategy()
    msc = {"sector_rank": 2, "zt_count_today": 3, "seal_to_float_ratio": 0.003, "pattern": object()}
    r = s.match(_ctx(msc))
    c3 = [c for c in r.conditions if c.condition_id == "first_board_limitup.c3"][0]
    assert c3.state == "miss"
    assert r.fired is False


def test_all_hit_fired():
    """三条件全 hit → fired=True, confidence=0.6。"""
    s = FirstBoardLimitupStrategy()
    msc = {"sector_rank": 2, "zt_count_today": 3, "seal_to_float_ratio": 0.006, "pattern": object()}
    r = s.match(_ctx(msc))
    assert r.fired is True
    assert r.hit_count == 3
    assert r.confidence == 0.6


def test_no_msc_data_unavailable():
    """无 market_scan_ctx（涨停 pipeline 当前不构造）→ data_unavailable 整战法降级。"""
    s = FirstBoardLimitupStrategy()
    r = s.match(_ctx(None))
    assert r.fired is False
    # data_unavailable result：条件全 data_unavailable
    assert all(c.state == "data_unavailable" for c in r.conditions)


def test_partial_data_field_level():
    """部分字段缺失（seal None）→ 该字段 data_unavailable，其他正常评估（字段级降级非整战法）。"""
    s = FirstBoardLimitupStrategy()
    msc = {"sector_rank": 2, "zt_count_today": 3, "seal_to_float_ratio": None, "pattern": object()}
    r = s.match(_ctx(msc))
    c1 = [c for c in r.conditions if c.condition_id == "first_board_limitup.c1"][0]
    c2 = [c for c in r.conditions if c.condition_id == "first_board_limitup.c2"][0]
    c3 = [c for c in r.conditions if c.condition_id == "first_board_limitup.c3"][0]
    assert c1.state == "hit"
    assert c2.state == "hit"
    assert c3.state == "data_unavailable"  # seal None 字段级降级
    assert r.fired is False  # C3 data_unavailable → 不 fired
    assert r.data_ok is True  # 非整战法降级（有 pattern + 其他字段）


def test_strategy_code_name():
    """战法 code/name 正确。"""
    s = FirstBoardLimitupStrategy()
    assert s.code == "first_board_limitup"
    assert s.name == "首板涨停"
