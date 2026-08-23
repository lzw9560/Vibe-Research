# -*- coding: utf-8 -*-
"""S086 各 Strategy 实现 match 单测（A15）。

按数据依赖维度分组：gene_based(8) / pool_based(1) / indicator_based(2) / db_based(1)。
每战法覆盖命中 + 不命中 + confidence；阈值/字符串与 limitup_strategy.py 既有分支对齐（不改阈值）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from limitup_screener.models import GeneScore
from strategies.strategy_base import ConditionMatch, StrategyContext
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


# ===========================================================================
# gene_based（8）
# ===========================================================================

class TestFirstPlate:
    def test_hit(self):
        s = FirstPlateStrategy()
        gene = _gene(total=70, factors={"涨停频次": 25})
        m = s.match(_ctx(gene=gene))
        assert len(m) == 1 and m[0].condition == "首次涨停+基因合格"
        assert s.compute_confidence(m, _ctx(gene=gene)) == pytest.approx(0.7)

    def test_miss_low_freq(self):
        s = FirstPlateStrategy()
        gene = _gene(total=70, factors={"涨停频次": 5})  # 频次≤20
        assert s.match(_ctx(gene=gene)) == []

    def test_miss_low_score(self):
        s = FirstPlateStrategy()
        gene = _gene(total=55, factors={"涨停频次": 25})  # score<60
        assert s.match(_ctx(gene=gene)) == []


class TestConsecutiveRelay:
    def test_hit(self):
        s = ConsecutiveRelayStrategy()
        gene = _gene(zt=3, factors={"封板率": 70})
        m = s.match(_ctx(gene=gene))
        assert len(m) == 1 and m[0].condition == "连板+封板强度"
        assert s.compute_confidence(m, _ctx(gene=gene)) == pytest.approx(0.7)

    def test_miss_low_zt(self):
        s = ConsecutiveRelayStrategy()
        assert s.match(_ctx(gene=_gene(zt=1, factors={"封板率": 70}))) == []

    def test_miss_low_seal(self):
        s = ConsecutiveRelayStrategy()
        assert s.match(_ctx(gene=_gene(zt=3, factors={"封板率": 50}))) == []


class TestBreakReseal:
    def test_hit_golden_zone(self):
        s = BreakResealStrategy()
        gene = _gene(zt=4, factors={"封板率": 85})
        m = s.match(_ctx(gene=gene))
        assert len(m) == 1 and "封板能力" in m[0].condition  # test_s053 对齐
        assert "黄金区" in m[0].description
        assert s.compute_confidence(m, _ctx(gene=gene)) == 0.7

    @pytest.mark.parametrize("zt", [3, 5])
    def test_boundary_zt_3_5_hit(self, zt):
        s = BreakResealStrategy()
        gene = _gene(zt=zt, factors={"封板率": 80})
        assert s.match(_ctx(gene=gene)) != []

    @pytest.mark.parametrize("zt", [2, 8])
    def test_miss_out_of_golden_zone(self, zt):
        s = BreakResealStrategy()
        assert s.match(_ctx(gene=_gene(zt=zt, factors={"封板率": 85}))) == []

    def test_miss_low_seal(self):
        s = BreakResealStrategy()
        assert s.match(_ctx(gene=_gene(zt=4, factors={"封板率": 70}))) == []


class TestLowAbsorption:
    """S094 R10/T14：改读 PatternScan（ma5_proximity≤3 + ma_bullish）。"""

    def test_hit_near_ma5_and_bullish(self):
        s = LowAbsorptionStrategy()
        m = s.match(_ctx(market_scan_ctx=_msc(ma5_proximity=2.0, ma_bullish=True)))
        assert len(m) == 1 and m[0].condition == "回调至MA5+均线多头"
        assert s.compute_confidence(m, _ctx(market_scan_ctx=_msc())) == 0.5

    def test_miss_far_from_ma5(self):
        s = LowAbsorptionStrategy()
        assert s.match(_ctx(market_scan_ctx=_msc(ma5_proximity=5.0))) == []

    def test_miss_not_bullish(self):
        s = LowAbsorptionStrategy()
        assert s.match(_ctx(market_scan_ctx=_msc(ma_bullish=False))) == []

    def test_miss_without_market_scan_ctx(self):
        s = LowAbsorptionStrategy()
        assert s.match(_ctx(gene=_gene())) == []


class TestNShapeCounterattack:
    @pytest.mark.parametrize("zt", [2, 5, 10])
    def test_hit(self, zt):
        s = NShapeCounterattackStrategy()
        m = s.match(_ctx(gene=_gene(zt=zt)))
        assert len(m) == 1 and m[0].condition == "N字形态+放量"
        assert s.compute_confidence(m, _ctx()) == 0.5

    @pytest.mark.parametrize("zt", [1, 11])
    def test_miss(self, zt):
        s = NShapeCounterattackStrategy()
        assert s.match(_ctx(gene=_gene(zt=zt))) == []


class TestPlatformBreakout:
    """S094 R10/T14：改读 PatternScan（consolidation_days≥5 + volume_breakout_ratio>2）。"""

    def test_hit_consolidation_and_volume_breakout(self):
        s = PlatformBreakoutStrategy()
        m = s.match(_ctx(market_scan_ctx=_msc(consolidation_days=6, volume_breakout_ratio=2.5)))
        assert len(m) == 1 and m[0].condition == "横盘+放量突破"
        assert s.compute_confidence(m, _ctx(market_scan_ctx=_msc())) == 0.5

    def test_miss_low_consolidation(self):
        s = PlatformBreakoutStrategy()
        assert s.match(_ctx(market_scan_ctx=_msc(consolidation_days=3, volume_breakout_ratio=2.5))) == []

    def test_miss_low_volume(self):
        s = PlatformBreakoutStrategy()
        assert s.match(_ctx(market_scan_ctx=_msc(consolidation_days=6, volume_breakout_ratio=1.5))) == []

    def test_miss_without_market_scan_ctx(self):
        s = PlatformBreakoutStrategy()
        assert s.match(_ctx(gene=_gene())) == []


class TestEndOfDaySneak:
    def test_hit(self):
        s = EndOfDaySneakStrategy()
        gene = _gene(factors={"封板率": 50, "次日溢价率": 45})
        m = s.match(_ctx(gene=gene))
        assert len(m) == 1 and m[0].condition == "尾盘封板"
        assert s.compute_confidence(m, _ctx(gene=gene)) == 0.4

    def test_miss_low_premium(self):
        s = EndOfDaySneakStrategy()
        assert s.match(_ctx(gene=_gene(factors={"封板率": 50, "次日溢价率": 30}))) == []


class TestDragonHead:
    """S094 R9：条件化——读 market_scan_ctx.sector_rank（板块内≤3）+ pattern 命中。

    旧 S086 无条件放行已删；无 market_scan_ctx（limitup/match_strategies 路径）→ 不命中。
    """

    def test_matches_when_sector_rank_le3(self):
        s = DragonHeadStrategy()
        m = s.match(_ctx(market_scan_ctx=_msc(2)))
        assert len(m) == 1 and m[0].condition == "板块内领涨"
        assert s.compute_confidence(m, _ctx(market_scan_ctx=_msc(2))) == 0.5

    def test_no_match_when_sector_rank_gt3(self):
        s = DragonHeadStrategy()
        assert s.match(_ctx(market_scan_ctx=_msc(5))) == []

    def test_no_match_without_market_scan_ctx(self):
        # R9 行为变化：无 market_scan_ctx（limitup/match_strategies 路径）→ 不命中
        s = DragonHeadStrategy()
        assert s.match(_ctx(gene=_gene(total=90, zt=5))) == []


# ===========================================================================
# pool_based（1）
# ===========================================================================

class TestStormReversal:
    def test_hit_early_fbt(self):
        s = StormReversalStrategy()
        m = s.match(_ctx(pool_item={"fbt": 93000}))
        assert len(m) == 1 and m[0].condition == "封板时间≤10:30"
        assert s.compute_confidence(m, _ctx()) == 0.7

    def test_miss_late_fbt(self):
        s = StormReversalStrategy()
        assert s.match(_ctx(pool_item={"fbt": 140000})) == []

    def test_miss_no_pool_item(self):
        s = StormReversalStrategy()
        assert s.match(_ctx(pool_item=None)) == []

    def test_miss_no_fbt_field(self):
        s = StormReversalStrategy()
        assert s.match(_ctx(pool_item={"p": 10.0})) == []


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
        """lbc/broken/drop/lock 命中；vol_ratio None（hs 取不到前日）→ 4/5 → 0.7。"""
        s = WeakTurnStrongStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"lbc": 2, "hs": 2.5, "p": 10.0},
            indicators=self._ind(prev_turnover_pct=None),  # prev_hs None → vol_ratio None
            derived=_DERIVED_OK,
        )
        m = s.match(ctx)
        assert len(m) == 4  # f1-f4
        assert s.compute_confidence(m, ctx) == 0.7

    def test_5of5_high_confidence(self):
        """全 5 因子命中 → 1.0。"""
        s = WeakTurnStrongStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"lbc": 2, "hs": 2.0, "p": 10.0},  # hs=2.0
            indicators=self._ind(prev_turnover_pct=1.0),  # prev_hs=1.0 → vol_ratio=2.0（区间 1.8-3.0）
            derived=_DERIVED_OK,
        )
        m = s.match(ctx)
        assert len(m) == 5
        assert s.compute_confidence(m, ctx) == 1.0

    def test_missing_derived_no_match(self):
        """derived=None → broken/drop/lock None → ≤3 命中 → 不输出。"""
        s = WeakTurnStrongStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"lbc": 2, "hs": 2.5, "p": 10.0},
            indicators=None, derived=None,
        )
        assert s.match(ctx) == []

    def test_lbc_in_match_value(self):
        """命中时 value 含 lbc（对齐 test_s081_strategy_matcher_pool_item AC）。"""
        s = WeakTurnStrongStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"lbc": 2, "hs": 2.5, "p": 10.0},
            indicators=self._ind(prev_turnover_pct=None),
            derived=_DERIVED_OK,
        )
        m = s.match(ctx)
        assert any("lbc=2" in c.value for c in m)


class TestPatternReversal:
    """S094 R5：PatternReversal 改读 PatternScan（不读 ctx.indicators）。

    5 因子→3 字段删减：删"未封涨停"（涨停判定在 match 层 pool_item.lbc/zbc）+
    删"最高≥7%"（与上影≥4% 重叠）。3 字段：shadow_length_pct>=4 +
    volume_breakout_ratio>=1.2 + ma5_slope>0。confidence=1.0(3命中)/0.7(2命中)。
    """

    def _pattern(self, shadow=5.0, vol_ratio=2.5, ma5_slope=0.01):
        """构造 PatternScan（含 S094 R5 新增 shadow_length_pct/ma5_slope 字段）。"""
        from strategies.pattern_scan import PatternScan
        return PatternScan(
            code="000001",
            relative_strength=5.0,
            ma_bullish=True,
            ma5_proximity=2.0,
            consolidation_days=0,
            consolidation_amplitude=None,
            volume_breakout_ratio=vol_ratio,
            amount_yi=20.0,
            shadow_length_pct=shadow,  # S094 R5 新增
            ma5_slope=ma5_slope,       # S094 R5 新增
        )

    def _ctx_with_pattern(self, pattern):
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"zdp": 5.0, "p": 10.0},
            indicators=None,  # S094 R5：不再读 indicators
        )
        ctx.market_scan_ctx = {"pattern": pattern, "sector_rank": 1, "rel_strength_vs_sector": 5.0}
        return ctx

    def test_3of3_high_confidence(self):
        """shadow>=4 + vol_ratio>=1.2 + ma5_slope>0 → 3/3 → 1.0。"""
        s = PatternReversalStrategy()
        ctx = self._ctx_with_pattern(self._pattern(shadow=5.0, vol_ratio=2.5, ma5_slope=0.01))
        m = s.match(ctx)
        assert len(m) == 3
        assert s.compute_confidence(m, ctx) == 1.0

    def test_entry_price_override_p_plus_tick(self):
        """override compute_entry_price = tick(pool_item.p + 0.01)。"""
        s = PatternReversalStrategy()
        ctx = self._ctx_with_pattern(self._pattern())
        assert s.compute_entry_price(ctx) == 10.01  # 10.0 + 0.01

    def test_no_pattern_no_match(self):
        """S094 R5：无 market_scan_ctx.pattern → 不命中（诚实降级，不臆造）。"""
        s = PatternReversalStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"zdp": 5.0, "p": 10.0},
            indicators=None,  # 旧路径 indicators 已不读
        )
        # market_scan_ctx 未设置 → None → 不命中
        assert s.match(ctx) == []

    def test_2of3_medium_confidence(self):
        """2 因子命中 → 0.7（medium）。shadow 命中 + vol_ratio 命中，ma5_slope<=0 不命中。"""
        s = PatternReversalStrategy()
        ctx = self._ctx_with_pattern(self._pattern(shadow=5.0, vol_ratio=2.5, ma5_slope=-0.01))
        m = s.match(ctx)
        assert len(m) == 2
        assert s.compute_confidence(m, ctx) == 0.7

    def test_lt_2_no_match(self):
        """<2 命中 → 不输出。"""
        s = PatternReversalStrategy()
        ctx = self._ctx_with_pattern(self._pattern(shadow=2.0, vol_ratio=1.0, ma5_slope=-0.01))
        assert s.match(ctx) == []


# ===========================================================================
# db_based（1）
# ===========================================================================

class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        # S089 C6：match() 调 SELECT MAX(date) → fetchone。返首行或 None。
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
        """seal_intraday.db open_count>=2 的票含 gene.code → 命中，confidence=0.4。

        S089 C6：路由层 get_latest_partition 返 (db_path, table)，sqlite3.connect
        mock 返 FakeConn，MAX(date)/DISTINCT code 两查询都返同一 FakeCursor。
        """
        s = ReversePackageStrategy()
        # get_latest_partition 在 match() 内 from db_partition_router 导入，
        # 走 db_partition_router 模块命名空间 → patch 该模块属性生效。
        import db_partition_router
        monkeypatch.setattr(
            db_partition_router, "get_latest_partition",
            lambda: ("fake.db", "seal_intraday_snapshots_202608"),
        )
        monkeypatch.setattr("sqlite3.connect", lambda *a, **kw: _FakeConn([("000001",)]))
        ctx = _ctx(gene=_gene())  # code=000001
        m = s.match(ctx)
        assert len(m) == 1 and "反包" in m[0].condition
        assert s.compute_confidence(m, ctx) == 0.4

    def test_miss_when_code_not_in_zb_pool(self, monkeypatch):
        s = ReversePackageStrategy()
        import db_partition_router
        monkeypatch.setattr(
            db_partition_router, "get_latest_partition",
            lambda: ("fake.db", "seal_intraday_snapshots_202608"),
        )
        monkeypatch.setattr("sqlite3.connect", lambda *a, **kw: _FakeConn([("999999",)]))
        assert s.match(_ctx(gene=_gene())) == []

    def test_miss_on_db_error(self, monkeypatch):
        """sqlite3.connect 异常 → zb_stocks 空集 → 不命中（诚实降级）。"""
        s = ReversePackageStrategy()
        import db_partition_router
        monkeypatch.setattr(
            db_partition_router, "get_latest_partition",
            lambda: ("fake.db", "seal_intraday_snapshots_202608"),
        )

        def _boom(*a, **kw):
            raise RuntimeError("db gone")
        monkeypatch.setattr("sqlite3.connect", _boom)
        assert s.match(_ctx(gene=_gene())) == []

    def test_miss_when_no_partition(self, monkeypatch):
        """S089 C6：当年库不存在（get_latest_partition 返 None）→ 空集不命中。"""
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
        assert s.match(_ctx(gene=_gene())) == []
