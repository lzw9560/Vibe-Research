# -*- coding: utf-8 -*-
"""S086/S097 各 Strategy 实现 match 单测。

S097：12 战法 match() 返 StrategyMatchResult（全量条件三态 hit/miss/data_unavailable
+ fired 按 fire_rule + confidence）。每战法覆盖 hit + miss + data_unavailable
（数据前置缺失整战法降级 / 字段级数据缺）+ fired 判定 + confidence。
阈值/字符串与 limitup_strategy.py 既有分支对齐（不改阈值）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from limitup_screener.models import GeneScore
from strategies.strategy_base import StrategyContext, StrategyMatchResult
from strategies.impl import (
    BreakResealStrategy,
    ConsecutiveRelayStrategy,
    DragonHeadStrategy,
    EndOfDaySneakStrategy,
    FirstPlateStrategy,
    LowAbsorptionStrategy,
    NShapeCounterattackStrategy,
    PatternReversalStrategy,
    PlatformBreakoutStrategy,
    ReversePackageStrategy,
    StormReversalStrategy,
    WeakTurnStrongStrategy,
)


def _gene(total=70.0, zt=1, factors=None) -> GeneScore:
    return GeneScore(
        code="000001", name="X", total_score=total,
        factors=factors or {"涨停频次": 25, "封板率": 30, "次日溢价率": 40, "红盘率": 50, "炸板后溢价": 0},
        wilson_adjusted=total, qualify=True, high_gene=False,
        last_zt_dates=[], zt_count_250d=zt,
    )


def _ctx(gene=None, pool_item=None, indicators=None, derived=None, market_scan_ctx=None) -> StrategyContext:
    return StrategyContext(
        code="000001", gene=gene or _gene(), pool_item=pool_item,
        indicators=indicators, derived=derived, weather_state=None,
        market_scan_ctx=market_scan_ctx,
    )


def _pat(**kw):
    """S094：构造 PatternScan（默认值满足多数 market_scan 战法命中条件，kw 覆盖）。"""
    from strategies.pattern_scan import PatternScan
    defaults = dict(
        code="000001", relative_strength=5.0, ma_bullish=True, ma5_proximity=2.0,
        consolidation_days=6, consolidation_amplitude=None,
        volume_breakout_ratio=2.5, amount_yi=20.0,
        shadow_length_pct=5.0, ma5_slope=0.01,
    )
    defaults.update(kw)
    return PatternScan(**defaults)


def _msc(sector_rank: int = 1, pattern=None, **kw) -> dict:
    """S094：构造 market_scan_ctx（pattern 默认 _pat，kw 透传 _pat）。"""
    return {"pattern": pattern if pattern is not None else _pat(**kw),
            "sector_rank": sector_rank, "rel_strength_vs_sector": 5.0}


def _state_of(r: StrategyMatchResult, cid: str) -> str:
    """按 condition_id 取 state（测试辅助）。"""
    for c in r.conditions:
        if c.condition_id == cid:
            return c.state
    raise AssertionError(f"condition {cid} not found in {r.conditions}")


# ===========================================================================
# gene_based（8）
# ===========================================================================

class TestFirstPlate:
    def test_hit(self):
        s = FirstPlateStrategy()
        gene = _gene(total=70, factors={"涨停频次": 25})
        r = s.match(_ctx(gene=gene))
        assert isinstance(r, StrategyMatchResult)
        assert r.fired and r.hit_count == 2 and len(r.conditions) == 2
        assert r.conditions[0].condition_id == "first_plate.c1"
        assert _state_of(r, "first_plate.c1") == "hit"
        assert _state_of(r, "first_plate.c2") == "hit"
        assert r.confidence == pytest.approx(0.7)
        assert r.data_ok

    def test_miss_low_freq(self):
        s = FirstPlateStrategy()
        gene = _gene(total=70, factors={"涨停频次": 5})  # C2 频次≤20
        r = s.match(_ctx(gene=gene))
        assert not r.fired
        assert _state_of(r, "first_plate.c1") == "hit"
        assert _state_of(r, "first_plate.c2") == "miss"
        assert r.confidence is None

    def test_miss_low_score(self):
        s = FirstPlateStrategy()
        gene = _gene(total=35, factors={"涨停频次": 25})  # C1 score<40（fa4514e 60→40）
        r = s.match(_ctx(gene=gene))
        assert not r.fired
        assert _state_of(r, "first_plate.c1") == "miss"
        assert _state_of(r, "first_plate.c2") == "hit"


class TestConsecutiveRelay:
    def test_hit(self):
        s = ConsecutiveRelayStrategy()
        gene = _gene(zt=3, factors={"封板率": 70})
        r = s.match(_ctx(gene=gene))
        assert r.fired and r.hit_count == 2
        assert _state_of(r, "consecutive_relay.c1") == "hit"
        assert _state_of(r, "consecutive_relay.c2") == "hit"
        assert r.confidence == pytest.approx(0.7)

    def test_miss_low_zt(self):
        s = ConsecutiveRelayStrategy()
        r = s.match(_ctx(gene=_gene(zt=1, factors={"封板率": 70})))
        assert not r.fired
        assert _state_of(r, "consecutive_relay.c1") == "miss"
        assert _state_of(r, "consecutive_relay.c2") == "hit"

    def test_miss_low_seal(self):
        s = ConsecutiveRelayStrategy()
        r = s.match(_ctx(gene=_gene(zt=3, factors={"封板率": 50})))
        assert not r.fired
        assert _state_of(r, "consecutive_relay.c1") == "hit"
        assert _state_of(r, "consecutive_relay.c2") == "miss"


class TestBreakReseal:
    def test_hit_golden_zone(self):
        s = BreakResealStrategy()
        gene = _gene(zt=4, factors={"封板率": 85})
        r = s.match(_ctx(gene=gene))
        assert r.fired and r.hit_count == 2
        assert r.conditions[1].condition_name == "强封板"
        assert "黄金区" in r.conditions[0].description  # test_s053 对齐
        assert r.confidence == 0.7

    @pytest.mark.parametrize("zt", [3, 5])
    def test_boundary_zt_3_5_hit(self, zt):
        s = BreakResealStrategy()
        r = s.match(_ctx(gene=_gene(zt=zt, factors={"封板率": 80})))
        assert r.fired

    @pytest.mark.parametrize("zt", [2, 8])
    def test_miss_out_of_golden_zone(self, zt):
        s = BreakResealStrategy()
        r = s.match(_ctx(gene=_gene(zt=zt, factors={"封板率": 85})))
        assert not r.fired
        assert _state_of(r, "break_reseal.c1") == "miss"

    def test_miss_low_seal(self):
        s = BreakResealStrategy()
        r = s.match(_ctx(gene=_gene(zt=4, factors={"封板率": 70})))
        assert not r.fired
        assert _state_of(r, "break_reseal.c2") == "miss"


class TestLowAbsorption:
    """S094 R10/T14：改读 PatternScan（ma5_proximity≤3 + ma_bullish）。
    S097：无 market_scan_ctx → data_ok=False 整战法降级（全 data_unavailable）。"""

    def test_hit_near_ma5_and_bullish(self):
        s = LowAbsorptionStrategy()
        r = s.match(_ctx(market_scan_ctx=_msc(ma5_proximity=2.0, ma_bullish=True, volume_breakout_ratio=0.8)))  # S153 R5 C3 vol_brk<1.0 hit
        assert r.fired and r.hit_count == 3
        assert r.confidence == 0.5

    def test_miss_far_from_ma5(self):
        s = LowAbsorptionStrategy()
        r = s.match(_ctx(market_scan_ctx=_msc(ma5_proximity=5.0)))
        assert not r.fired
        assert _state_of(r, "low_absorption.c1") == "miss"

    def test_miss_not_bullish(self):
        s = LowAbsorptionStrategy()
        r = s.match(_ctx(market_scan_ctx=_msc(ma_bullish=False)))
        assert not r.fired
        assert _state_of(r, "low_absorption.c2") == "miss"

    def test_data_unavailable_without_market_scan_ctx(self):
        """无 market_scan_ctx → data_ok=False，全 data_unavailable（非逻辑 miss）。"""
        s = LowAbsorptionStrategy()
        r = s.match(_ctx(gene=_gene()))
        assert not r.fired
        assert not r.data_ok
        assert all(c.state == "data_unavailable" for c in r.conditions)
        assert r.confidence is None


class TestNShapeCounterattack:
    @pytest.mark.parametrize("zt", [2, 5, 10])
    def test_hit(self, zt):
        s = NShapeCounterattackStrategy()
        r = s.match(_ctx(gene=_gene(zt=zt)))
        assert r.fired and r.hit_count == 1
        assert r.conditions[0].condition_name == "N字区间"  # R14：去"放量"
        assert r.confidence == 0.5

    @pytest.mark.parametrize("zt", [1, 11])
    def test_miss(self, zt):
        s = NShapeCounterattackStrategy()
        r = s.match(_ctx(gene=_gene(zt=zt)))
        assert not r.fired
        assert _state_of(r, "n_shape_counterattack.c1") == "miss"


class TestPlatformBreakout:
    """S094 R10/T14：改读 PatternScan（consolidation_days≥5 + volume_breakout_ratio>2）。"""

    def test_hit_consolidation_and_volume_breakout(self):
        s = PlatformBreakoutStrategy()
        r = s.match(_ctx(market_scan_ctx=_msc(consolidation_days=6, volume_breakout_ratio=2.5, consolidation_amplitude=5.0)))  # S153 R4 C3 amplitude≤6.0 hit
        assert r.fired and r.hit_count == 3
        assert r.confidence == 0.5

    def test_miss_low_consolidation(self):
        s = PlatformBreakoutStrategy()
        r = s.match(_ctx(market_scan_ctx=_msc(consolidation_days=3, volume_breakout_ratio=2.5)))
        assert not r.fired
        assert _state_of(r, "platform_breakout.c1") == "miss"

    def test_miss_low_volume(self):
        s = PlatformBreakoutStrategy()
        r = s.match(_ctx(market_scan_ctx=_msc(consolidation_days=6, volume_breakout_ratio=1.5)))
        assert not r.fired
        assert _state_of(r, "platform_breakout.c2") == "miss"

    def test_data_unavailable_without_market_scan_ctx(self):
        s = PlatformBreakoutStrategy()
        r = s.match(_ctx(gene=_gene()))
        assert not r.fired
        assert not r.data_ok
        assert all(c.state == "data_unavailable" for c in r.conditions)


class TestEndOfDaySneak:
    def test_hit(self):
        s = EndOfDaySneakStrategy()
        gene = _gene(factors={"封板率": 50, "次日溢价率": 45})
        r = s.match(_ctx(gene=gene))
        assert r.fired and r.hit_count == 2
        assert r.confidence == 0.4

    def test_miss_low_premium(self):
        s = EndOfDaySneakStrategy()
        r = s.match(_ctx(gene=_gene(factors={"封板率": 50, "次日溢价率": 10})))  # 次日溢价率<15 miss（fa4514e 40→15）
        assert not r.fired
        assert _state_of(r, "end_of_day_sneak.c2") == "miss"


class TestDragonHead:
    """S094 R9：条件化——读 market_scan_ctx.sector_rank（板块内≤3）+ pattern 命中。
    S097：无 market_scan_ctx → data_ok=False 整战法降级（非旧"空list硬过滤"）。"""

    def test_matches_when_sector_rank_le3(self):
        s = DragonHeadStrategy()
        r = s.match(_ctx(market_scan_ctx=_msc(2)))
        assert r.fired and r.hit_count == 1
        assert r.confidence == 0.5

    def test_no_match_when_sector_rank_gt3(self):
        s = DragonHeadStrategy()
        r = s.match(_ctx(market_scan_ctx=_msc(5)))
        assert not r.fired
        assert _state_of(r, "dragon_head.c1") == "miss"

    def test_data_unavailable_without_market_scan_ctx(self):
        """无 market_scan_ctx → data_ok=False，全 data_unavailable（非逻辑 miss）。"""
        s = DragonHeadStrategy()
        r = s.match(_ctx(gene=_gene(total=90, zt=5)))
        assert not r.fired
        assert not r.data_ok
        assert all(c.state == "data_unavailable" for c in r.conditions)

    def test_field_data_unavailable_no_sector_rank(self):
        """pattern 存在但 sector_rank None → 字段级 data_unavailable（data_ok=True，非整战法降级）。"""
        s = DragonHeadStrategy()
        msc = {"pattern": _pat(), "sector_rank": None, "rel_strength_vs_sector": 5.0}
        r = s.match(_ctx(market_scan_ctx=msc))
        assert not r.fired
        assert r.data_ok  # pattern 在，仅 sector_rank 缺 → 字段级降级
        assert _state_of(r, "dragon_head.c1") == "data_unavailable"


# ===========================================================================
# pool_based（1）
# ===========================================================================

class TestStormReversal:
    def test_hit_early_fbt(self):
        s = StormReversalStrategy()
        r = s.match(_ctx(pool_item={"fbt": 93000}))
        assert r.fired and r.hit_count == 1
        assert r.confidence == 0.7

    def test_miss_late_fbt(self):
        s = StormReversalStrategy()
        r = s.match(_ctx(pool_item={"fbt": 140000}))
        assert not r.fired
        assert _state_of(r, "storm_reversal.c1") == "miss"

    def test_data_unavailable_no_pool_item(self):
        """无 pool_item → data_ok=False 整战法降级。"""
        s = StormReversalStrategy()
        r = s.match(_ctx(pool_item=None))
        assert not r.fired
        assert not r.data_ok
        assert all(c.state == "data_unavailable" for c in r.conditions)

    def test_field_data_unavailable_no_fbt(self):
        """pool_item 有但缺 fbt → 字段级 data_unavailable（战法 data_ok=True）。"""
        s = StormReversalStrategy()
        r = s.match(_ctx(pool_item={"p": 10.0}))
        assert not r.fired
        assert r.data_ok  # 战法前置在，仅字段缺
        assert _state_of(r, "storm_reversal.c1") == "data_unavailable"


# ===========================================================================
# indicator_based（2）
# ===========================================================================

_DERIVED_OK = {
    "broken_duration_min": 25.0, "max_drop_pct": 6.0,
    "last_lock_time": "2026-08-11T14:50", "data_status": "ok",
}


class TestWeakTurnStrong:
    def _ind(self, prev_turnover_pct=1.0):
        return SimpleNamespace(prev_turnover_pct=prev_turnover_pct)

    def test_4of5_medium_confidence(self):
        """lbc/broken/drop/lock 命中；vol_ratio None（prev_hs None）→ C5 data_unavailable → 4/5 → 0.7。"""
        s = WeakTurnStrongStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"lbc": 2, "hs": 2.5, "p": 10.0},
            indicators=self._ind(prev_turnover_pct=None),  # prev_hs None → vol_ratio None
            derived=_DERIVED_OK,
        )
        r = s.match(ctx)
        assert r.fired and r.hit_count == 4
        assert _state_of(r, "weak_turn_strong.c5") == "data_unavailable"  # 字段级数据缺
        assert r.confidence == 0.7

    def test_5of5_high_confidence(self):
        """全 5 因子命中 → 1.0。"""
        s = WeakTurnStrongStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"lbc": 2, "hs": 2.0, "p": 10.0},
            indicators=self._ind(prev_turnover_pct=1.0),  # vol_ratio=2.0（区间 1.8-3.0）
            derived=_DERIVED_OK,
        )
        r = s.match(ctx)
        assert r.fired and r.hit_count == 5
        assert r.confidence == 1.0

    def test_missing_derived_not_fired(self):
        """derived=None → C2/C3/C4 data_unavailable；C5 data_unavailable → hit_count=1 → 不 fired。"""
        s = WeakTurnStrongStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"lbc": 2, "hs": 2.5, "p": 10.0},
            indicators=None, derived=None,
        )
        r = s.match(ctx)
        assert not r.fired
        assert r.hit_count == 1  # 仅 C1 hit
        assert _state_of(r, "weak_turn_strong.c1") == "hit"
        assert _state_of(r, "weak_turn_strong.c2") == "data_unavailable"

    def test_c4_r18_before_threshold_miss(self):
        """R18：last_lock_time[11:16] >= "14:40"（修旧 ISO 整串比较恒命中 bug）。

        last_lock_time="2026-08-11T13:00"（日期 2026 但时间 13:00<14:40）：
        旧 `>= "2026-01-01T14:40"` 字典序 True（2026-08>2026-01，日期段压倒→恒命中 bug）；
        新 [11:16]="13:00" < "14:40" → miss。
        """
        s = WeakTurnStrongStrategy()
        derived = dict(_DERIVED_OK, last_lock_time="2026-08-11T13:00")
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"lbc": 2, "hs": 2.0, "p": 10.0},
            indicators=self._ind(prev_turnover_pct=1.0),
            derived=derived,
        )
        r = s.match(ctx)
        assert _state_of(r, "weak_turn_strong.c4") == "miss"  # R18 修复：13:00 < 14:40
        # C1/C2/C3/C5 hit（4 命中）→ 仍 fired，但 C4 正确 miss（旧 bug 会 hit → 5 命中）
        assert r.hit_count == 4
        assert r.confidence == 0.7

    def test_lbc_in_actual_value(self):
        """命中时 C1.actual_value 含 lbc（对齐 test_s081_strategy_matcher_pool_item AC）。"""
        s = WeakTurnStrongStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"lbc": 2, "hs": 2.5, "p": 10.0},
            indicators=self._ind(prev_turnover_pct=None),
            derived=_DERIVED_OK,
        )
        r = s.match(ctx)
        c1 = next(c for c in r.conditions if c.condition_id == "weak_turn_strong.c1")
        assert "lbc=2" in (c1.actual_value or "")

    def test_c1_data_unavailable_no_pool_item(self):
        """pool_item=None → C1 lbc data_unavailable（非臆造 lbc=0 miss；spec §7 不臆造工程底线）。"""
        s = WeakTurnStrongStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item=None,  # 无 pool_item → lbc 缺
            indicators=None, derived=None,
        )
        r = s.match(ctx)
        assert _state_of(r, "weak_turn_strong.c1") == "data_unavailable"
        assert r.data_ok  # 字段级降级，非整战法


class TestPatternReversal:
    """S094 R5：PatternReversal 改读 PatternScan（不读 ctx.indicators）。
    S097：无 pattern → data_ok=False 整战法降级。3 字段 ≥2/3 命中 fired。"""

    def _pattern(self, shadow=5.0, vol_ratio=2.5, ma5_slope=0.01):
        from strategies.pattern_scan import PatternScan
        return PatternScan(
            code="000001", relative_strength=5.0, ma_bullish=True, ma5_proximity=2.0,
            consolidation_days=0, consolidation_amplitude=None,
            volume_breakout_ratio=vol_ratio, amount_yi=20.0,
            shadow_length_pct=shadow, ma5_slope=ma5_slope,
        )

    def _ctx_with_pattern(self, pattern):
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"zdp": 5.0, "p": 10.0},
            indicators=None,
        )
        ctx.market_scan_ctx = {"pattern": pattern, "sector_rank": 1, "rel_strength_vs_sector": 5.0}
        return ctx

    def test_3of3_high_confidence(self):
        """shadow>=4 + vol_ratio>=1.2 + ma5_slope>0 → 3/3 → 1.0。"""
        s = PatternReversalStrategy()
        ctx = self._ctx_with_pattern(self._pattern(shadow=5.0, vol_ratio=2.5, ma5_slope=0.01))
        r = s.match(ctx)
        assert r.fired and r.hit_count == 3
        assert r.confidence == 1.0

    def test_entry_price_override_p_plus_tick(self):
        """override compute_entry_price = tick(pool_item.p + 0.01)。"""
        s = PatternReversalStrategy()
        ctx = self._ctx_with_pattern(self._pattern())
        assert s.compute_entry_price(ctx) == 10.01  # 10.0 + 0.01

    def test_data_unavailable_no_pattern(self):
        """无 market_scan_ctx.pattern → data_ok=False 整战法降级（不臆造）。"""
        s = PatternReversalStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"zdp": 5.0, "p": 10.0},
            indicators=None,
        )
        r = s.match(ctx)
        assert not r.fired
        assert not r.data_ok
        assert all(c.state == "data_unavailable" for c in r.conditions)

    def test_2of3_medium_confidence(self):
        """2 因子命中 → 0.7。shadow + vol_ratio 命中，ma5_slope<=0 miss。"""
        s = PatternReversalStrategy()
        ctx = self._ctx_with_pattern(self._pattern(shadow=5.0, vol_ratio=2.5, ma5_slope=-0.01))
        r = s.match(ctx)
        assert r.fired and r.hit_count == 2
        assert _state_of(r, "pattern_reversal.c3") == "miss"
        assert r.confidence == 0.7

    def test_lt_2_not_fired(self):
        """<2 命中 → 不 fired。"""
        s = PatternReversalStrategy()
        ctx = self._ctx_with_pattern(self._pattern(shadow=2.0, vol_ratio=1.0, ma5_slope=-0.01))
        r = s.match(ctx)
        assert not r.fired
        assert r.hit_count == 0


# ===========================================================================
# db_based（1）
# ===========================================================================

class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **kw):
        return _FakeCursor(self._rows)

    def close(self):
        pass


class TestReversePackage:
    def test_hit_when_code_in_zb_pool(self, monkeypatch):
        """open_count>=2 的票含 gene.code → 命中，confidence=0.4。"""
        s = ReversePackageStrategy()
        import db_partition_router
        monkeypatch.setattr(
            db_partition_router, "get_latest_partition",
            lambda: ("fake.db", "seal_intraday_snapshots_202608"),
        )
        monkeypatch.setattr("sqlite3.connect", lambda *a, **kw: _FakeConn([("000001",)]))
        r = s.match(_ctx(gene=_gene()))  # code=000001
        assert r.fired and r.hit_count == 1
        assert r.conditions[0].condition_name == "前日真炸板"
        assert r.confidence == 0.4

    def test_miss_when_code_not_in_zb_pool(self, monkeypatch):
        s = ReversePackageStrategy()
        import db_partition_router
        monkeypatch.setattr(
            db_partition_router, "get_latest_partition",
            lambda: ("fake.db", "seal_intraday_snapshots_202608"),
        )
        monkeypatch.setattr("sqlite3.connect", lambda *a, **kw: _FakeConn([("999999",)]))
        r = s.match(_ctx(gene=_gene()))
        assert not r.fired
        assert r.data_ok  # DB 正常，只是 code 不在池 → 逻辑 miss 非 data 缺
        assert _state_of(r, "reverse_package.c1") == "miss"

    def test_data_unavailable_on_db_error(self, monkeypatch):
        """sqlite3.connect 异常 → data_ok=False 整战法降级（非逻辑 miss）。"""
        s = ReversePackageStrategy()
        import db_partition_router
        monkeypatch.setattr(
            db_partition_router, "get_latest_partition",
            lambda: ("fake.db", "seal_intraday_snapshots_202608"),
        )

        def _boom(*a, **kw):
            raise RuntimeError("db gone")
        monkeypatch.setattr("sqlite3.connect", _boom)
        r = s.match(_ctx(gene=_gene()))
        assert not r.fired
        assert not r.data_ok
        assert all(c.state == "data_unavailable" for c in r.conditions)

    def test_data_unavailable_when_no_partition(self, monkeypatch):
        """当年库不存在（get_latest_partition 返 None）→ data_ok=False 整战法降级。"""
        s = ReversePackageStrategy()
        import db_partition_router
        monkeypatch.setattr(
            db_partition_router, "get_latest_partition",
            lambda: None,
        )
        # sqlite3.connect 不应被调（无分区时不连库）
        def _boom(*a, **kw):
            raise AssertionError("不应连库")
        monkeypatch.setattr("sqlite3.connect", _boom)
        r = s.match(_ctx(gene=_gene()))
        assert not r.fired
        assert not r.data_ok
        assert all(c.state == "data_unavailable" for c in r.conditions)
