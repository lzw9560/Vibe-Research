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


def _ctx(gene=None, pool_item=None, indicators=None, derived=None) -> StrategyContext:
    return StrategyContext(
        code="000001", gene=gene or _gene(), pool_item=pool_item,
        indicators=indicators, derived=derived, weather_state=None,
    )


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
    def test_hit(self):
        s = LowAbsorptionStrategy()
        gene = _gene(total=70, factors={"次日溢价率": 55})
        m = s.match(_ctx(gene=gene))
        assert len(m) == 1 and m[0].condition == "龙头回调+资金关注"
        assert s.compute_confidence(m, _ctx(gene=gene)) == 0.5

    def test_miss_low_premium(self):
        s = LowAbsorptionStrategy()
        assert s.match(_ctx(gene=_gene(total=70, factors={"次日溢价率": 40}))) == []

    def test_miss_low_score(self):
        s = LowAbsorptionStrategy()
        assert s.match(_ctx(gene=_gene(total=60, factors={"次日溢价率": 55}))) == []


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
    def test_hit(self):
        s = PlatformBreakoutStrategy()
        gene = _gene(total=70, factors={"涨停频次": 45})
        m = s.match(_ctx(gene=gene))
        assert len(m) == 1 and m[0].condition == "平台整理+突破"
        assert s.compute_confidence(m, _ctx(gene=gene)) == 0.5

    def test_miss_low_freq(self):
        s = PlatformBreakoutStrategy()
        assert s.match(_ctx(gene=_gene(total=70, factors={"涨停频次": 30}))) == []


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
    def test_always_matches(self):
        """无条件放行——任意 gene 都命中，confidence=0.5。"""
        s = DragonHeadStrategy()
        for gene in [_gene(total=10, zt=0), _gene(total=90, zt=5)]:
            m = s.match(_ctx(gene=gene))
            assert len(m) == 1 and m[0].condition == "无条件放行"
            assert s.compute_confidence(m, _ctx(gene=gene)) == 0.5


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
    def _ind(self, max_high=8.0, shadow=5.0, ma5="Upward", amt=20.0, prev_amt=10.0):
        return SimpleNamespace(
            max_high_pct=max_high, shadow_length_pct=shadow, ma_5_status=ma5,
            amount_yi=amt, prev_amount_yi=prev_amt,
        )

    def test_5of5_high_confidence(self):
        """close_pct<9.5 + max_high≥7 + shadow≥4 + 放量≥1.2 + ma5 Upward → 5/5 → 1.0。"""
        s = PatternReversalStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"zdp": 5.0, "p": 10.0},
            indicators=self._ind(),
        )
        m = s.match(ctx)
        assert len(m) == 5
        assert s.compute_confidence(m, ctx) == 1.0

    def test_entry_price_override_p_plus_tick(self):
        """override compute_entry_price = tick(pool_item.p + 0.01)。"""
        s = PatternReversalStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"zdp": 5.0, "p": 10.0},
            indicators=self._ind(),
        )
        assert s.compute_entry_price(ctx) == 10.01  # 10.0 + 0.01

    def test_no_indicators_no_match(self):
        """无 indicators → K线因子 None → 不命中。"""
        s = PatternReversalStrategy()
        ctx = _ctx(
            gene=_gene(total=50, factors={"涨停频次": 0}),
            pool_item={"zdp": 5.0, "p": 10.0},
            indicators=None,
        )
        assert s.match(ctx) == []

    def test_no_pool_item_no_indicators_no_match(self):
        """无 pool_item 且无 indicators → close_pct None + K线因子 None → 0 命中 → 不输出。

        注：pattern_reversal 仅需 4/5 命中；有 indicators 时即便无 pool_item（close_pct=None，
        f1 不命中）仍可由 f2-f5 凑足 4 命中——此为既有行为（不改阈值）。本测验证
        pool_item + indicators 全无时确不命中。
        """
        s = PatternReversalStrategy()
        assert s.match(_ctx(gene=_gene(), pool_item=None, indicators=None)) == []


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
