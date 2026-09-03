# -*- coding: utf-8 -*-
"""S086 调度器 + 上下文准备单测（A15）。

覆盖：
- dispatch_match：空注册表→[]；mock ctx + Strategy→预期 Signal；confidence=0 不输出；
  pool_item 缺失→入场价 gene.total_score 代理 + "价格代理" 标注；pool_item.p→tick 对齐。
- _prepare_derived：card_derived 非空直返；None→fallback snapshots；data_status=missing→None；异常→None。
- _prepare_pool_item：map 有 code→dict；无→None；None map→None。
- match_strategies 兼容包装：旧签名（code, gene, pool_item, indicators, card）可用。
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
from strategies.strategy_base import (
    BaseStrategy,
    ConditionMatch,
    StrategyConfig,
    StrategyContext,
    _prepare_derived,
    _prepare_pool_item,
    dispatch_match,
    match_strategies,
)


def _gene(total=70.0, zt=1, factors=None) -> GeneScore:
    return GeneScore(
        code="000001", name="X", total_score=total,
        factors=factors or {"涨停频次": 25, "封板率": 30, "次日溢价率": 40},
        wilson_adjusted=total, qualify=True, high_gene=False,
        last_zt_dates=[], zt_count_250d=zt,
    )


def _ctx(gene=None, pool_item=None, indicators=None, derived=None) -> StrategyContext:
    return StrategyContext(
        code="000001", gene=gene or _gene(), pool_item=pool_item,
        indicators=indicators, derived=derived, weather_state=None,
    )


# ===========================================================================
# A15-1：dispatch_match 调度器
# ===========================================================================

class TestDispatchMatch:
    def test_empty_registry_returns_empty(self):
        assert dispatch_match(_ctx(), []) == []

    def test_no_match_strategy_produces_no_signal(self):
        """Strategy.match 返回 [] → 不输出信号。"""
        from strategies.impl import FirstPlateStrategy
        # gene 不满足 first_plate（涨停频次=5 ≤ 20）
        cfg = StrategyConfig(
            code="first_plate", name="首板挖掘", strategy_impl=FirstPlateStrategy(),
            stop_loss_pct=-3.0, take_profit_pct=8.0, max_hold_days=3,
        )
        gene = _gene(factors={"涨停频次": 5, "封板率": 30})
        sigs = dispatch_match(_ctx(gene=gene), [cfg])
        assert sigs == []

    def test_match_assembles_signal_with_proxy_entry_price(self):
        """命中 → 组装 StrategySignal；pool_item 缺失→入场价 gene.total_score + "价格代理" 标注。"""
        from strategies.impl import FirstPlateStrategy
        cfg = StrategyConfig(
            code="first_plate", name="首板挖掘", strategy_impl=FirstPlateStrategy(),
            stop_loss_pct=-3.0, take_profit_pct=8.0, max_hold_days=3,
            entry_condition="首次涨停+基因≥60",
        )
        gene = _gene(total=70.0, factors={"涨停频次": 25, "封板率": 30})  # 命中 first_plate
        sigs = dispatch_match(_ctx(gene=gene, pool_item=None), [cfg])
        assert len(sigs) == 1
        s = sigs[0]
        assert s.strategy_code == "first_plate"
        assert s.confidence == pytest.approx(0.7)  # min(70/100, 1.0)
        assert s.entry_price == 70.0  # gene.total_score 代理（无 pool_item.p）
        assert s.stop_loss == round(70.0 * (1 - 3.0 / 100), 2)  # 67.9
        assert s.take_profit == round(70.0 * (1 + 8.0 / 100), 2)  # 75.6
        assert any("价格代理" in n for n in s.risk_notes)  # A7 标注

    def test_match_uses_pool_item_p_as_entry_price(self):
        """pool_item.p 有值 → 入场价 tick 对齐（非 gene.total_score 代理），无"价格代理"标注。"""
        from strategies.impl import FirstPlateStrategy
        cfg = StrategyConfig(
            code="first_plate", name="首板挖掘", strategy_impl=FirstPlateStrategy(),
            stop_loss_pct=-3.0, take_profit_pct=8.0, max_hold_days=3,
        )
        gene = _gene(total=70.0, factors={"涨停频次": 25, "封板率": 30})
        sigs = dispatch_match(_ctx(gene=gene, pool_item={"p": 10.0, "fbt": 93000}), [cfg])
        s = sigs[0]
        assert s.entry_price == 10.0  # tick 对齐 pool_item.p
        assert not any("价格代理" in n for n in s.risk_notes)

    def test_confidence_zero_produces_no_signal(self):
        """compute_confidence 返回 0.0 → 不输出（即便 match 非空）。"""

        class _ZeroConf(BaseStrategy):
            code = "zero"
            name = "Zero"
            def match(self, ctx):
                return [ConditionMatch(condition="c", value="v", description="d")]
            def compute_confidence(self, matches, ctx):
                return 0.0

        cfg = StrategyConfig(
            code="zero", name="Zero", strategy_impl=_ZeroConf(),
            stop_loss_pct=-3.0, take_profit_pct=8.0, max_hold_days=3,
        )
        assert dispatch_match(_ctx(), [cfg]) == []

    def test_strategy_exception_does_not_block_others(self):
        """单战法 match 异常 → 跳过该战法，不阻断其余。"""

        class _Boom(BaseStrategy):
            code = "boom"
            name = "Boom"
            def match(self, ctx):
                raise RuntimeError("boom")
            def compute_confidence(self, matches, ctx):
                return 0.5

        from strategies.impl import FirstPlateStrategy
        boom = StrategyConfig(
            code="boom", name="Boom", strategy_impl=_Boom(),
            stop_loss_pct=-3.0, take_profit_pct=8.0, max_hold_days=3,
        )
        fp = StrategyConfig(
            code="first_plate", name="首板挖掘", strategy_impl=FirstPlateStrategy(),
            stop_loss_pct=-3.0, take_profit_pct=8.0, max_hold_days=3,
        )
        gene = _gene(total=70.0, factors={"涨停频次": 25, "封板率": 30})
        sigs = dispatch_match(_ctx(gene=gene), [boom, fp])
        assert [s.strategy_code for s in sigs] == ["first_plate"]  # boom 跳过

    def test_signals_sorted_by_risk_reward_times_winrate(self):
        """输出按 risk_reward_ratio × confidence_mapped_winrate 降序（合成 heuristic）。"""
        from strategies.impl import BreakResealStrategy, FirstPlateStrategy
        # first_plate: stop=-3/tp=8 → rr=2.67; break_reseal: stop=-3/tp=6 → rr=2.0
        # first_plate confidence=0.7→winrate=0.76; break_reseal confidence=0.7→winrate=0.76
        # 两战法都命中：gene zt=4,seal=85,score=70,freq=25
        gene = _gene(total=70.0, zt=4, factors={"涨停频次": 25, "封板率": 85})
        fp = StrategyConfig(
            code="first_plate", name="首板", strategy_impl=FirstPlateStrategy(),
            stop_loss_pct=-3.0, take_profit_pct=8.0, max_hold_days=3,
        )
        br = StrategyConfig(
            code="break_reseal", name="炸板回封", strategy_impl=BreakResealStrategy(),
            stop_loss_pct=-3.0, take_profit_pct=6.0, max_hold_days=1,
        )
        sigs = dispatch_match(_ctx(gene=gene), [fp, br])
        # first_plate rr(2.67)*win > break_reseal rr(2.0)*win → first_plate 排前
        assert sigs[0].strategy_code == "first_plate"


# ===========================================================================
# A15-2：_prepare_derived（R8 derived fallback 上提）
# ===========================================================================

class TestPrepareDerived:
    def test_card_derived_nonempty_returned_directly(self):
        """card_derived 非空 → 直接返回（调用方传 T-1 值）。"""
        d = {"broken_duration_min": 25.0, "max_drop_pct": 6.0, "data_status": "ok"}
        assert _prepare_derived(d, "001") is d

    def test_none_fallback_no_snapshots_returns_none(self, monkeypatch):
        """card_derived=None + snapshots 空 → None。"""
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code", lambda code, date: [])
        assert _prepare_derived(None, "001") is None

    def test_none_fallback_snapshots_ok(self, monkeypatch):
        """card_derived=None + snapshots 有值 + data_status=ok → 返回 derived。"""
        derived = {"broken_duration_min": 25.0, "max_drop_pct": 6.0, "data_status": "ok"}
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code", lambda code, date: [{"ts": "x"}])
        monkeypatch.setattr("strategies.intraday_features.compute_derived_features", lambda snaps: derived)
        assert _prepare_derived(None, "001") == derived

    def test_none_fallback_data_status_missing_returns_none(self, monkeypatch):
        """card_derived=None + compute_derived 返 data_status=missing → None。"""
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code", lambda code, date: [{"ts": "x"}])
        monkeypatch.setattr(
            "strategies.intraday_features.compute_derived_features",
            lambda snaps: {"data_status": "missing"},
        )
        assert _prepare_derived(None, "001") is None

    def test_exception_returns_none(self, monkeypatch):
        """get_snapshots 抛异常 → None（不阻断）。"""
        def _boom(code, date):
            raise RuntimeError("db gone")
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code", _boom)
        assert _prepare_derived(None, "001") is None


# ===========================================================================
# A15-3：_prepare_pool_item（R7）
# ===========================================================================

class TestPreparePoolItem:
    def test_none_map_returns_none(self):
        assert _prepare_pool_item(None, "001") is None

    def test_empty_map_returns_none(self):
        assert _prepare_pool_item({}, "001") is None

    def test_map_has_code_returns_dict(self):
        pi = {"c": "001", "fbt": 93000, "p": 10.0}
        assert _prepare_pool_item({"001": pi}, "001") is pi

    def test_map_missing_code_returns_none(self):
        assert _prepare_pool_item({"002": {"fbt": 93000}}, "001") is None


# ===========================================================================
# A15-4：match_strategies 兼容包装（旧签名）
# ===========================================================================

class TestMatchStrategiesCompat:
    def test_old_signature_2_args(self):
        """match_strategies(code, gene) 旧签名可用。"""
        gene = _gene(total=70.0, factors={"涨停频次": 25, "封板率": 30})
        sigs = match_strategies("000001", gene)
        assert isinstance(sigs, list)
        assert any(s.strategy_code == "first_plate" for s in sigs)

    def test_pool_item_keyword(self):
        """pool_item 关键字传参 → storm_reversal 命中 fbt。"""
        gene = _gene(total=50.0, zt=1, factors={"涨停频次": 5, "封板率": 80})
        sigs = match_strategies("000001", gene, pool_item={"fbt": 93000, "p": 10.0})
        assert any(s.strategy_code == "storm_reversal" for s in sigs)

    def test_card_override_reads_subobjects(self):
        """card 非空 → 从 card.pool_item/indicators/derived override 读（S084 R5）。"""
        from candidate_funnel.models import DiagnosisCard, IndicatorSet, ActivityAssessment, ActivityTier, StabilizationSignals
        from datetime import datetime
        gene = _gene(total=50.0, factors={"涨停频次": 0})
        ind = IndicatorSet(code="000001", name="X", prev_turnover_pct=10.0)
        card = DiagnosisCard(
            code="000001", name="X", indicators=ind,
            activity=ActivityAssessment(tier=ActivityTier.COLD, rules_applied=[]),
            stabilization=StabilizationSignals(), as_of=datetime.now(),
            pool_item={"lbc": 1, "p": 10.0, "zdp": 5.0},
            derived={"broken_duration_min": 25.0, "max_drop_pct": 6.0,
                     "last_lock_time": "2026-08-09T14:50", "data_status": "ok"},
        )
        sigs = match_strategies("000001", gene, card=card)
        # weak_turn_strong 4/5 命中（derived override + pool_item.lbc）
        assert any(s.strategy_code == "weak_turn_strong" for s in sigs)
