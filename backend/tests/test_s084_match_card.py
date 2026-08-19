# -*- coding: utf-8 -*-
"""S084 阶段 B 单测：match_strategies 从 DiagnosisCard 读因子（AC6-AC7）。

覆盖：
- AC7：既有 9 战法传/不传 card 命中一致（card=None 走 fallback，card 非空 override，9 战法从 gene 读不变）
- AC6：PRD 2 战法 card 非空从 card.derived/pool_item/indicators 读
- AC6：card.derived 非空从 card.derived override
- AC6/R4：card.derived=None（card=None 或 card.derived=None）→ weak_turn_strong 走战法层 fallback 自补；
  今日有 snapshots → 正常匹配；今日无 snapshots → 仍 missing_s070_r7 跳过
- AC6：pattern_reversal f4 从 card.indicators.amount_yi/prev_amount_yi 补活
- R6：StrategyMatcher.match/match_batch 透传 card/cards_map

注：zt pool 无 hs 键（dossier cluster 5），weak_turn_strong f5（vol_ratio_1d）在 card 非空时 hs=None
不命中，最多 4/5（confidence 0.7）。spec §3.1 R5.2 "从 pool_item 读 hs" 与实际数据源矛盾，
本 spec 保守不改既有 hs 取数路径（避免破坏 pre_market_workflow），矛盾在验收报告标注。
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from candidate_funnel.models import (
    ActivityAssessment,
    ActivityTier,
    DiagnosisCard,
    IndicatorSet,
    StabilizationSignals,
)
from limitup_screener.models import GeneScore
from limitup_strategy import match_strategies
from strategies.strategy_matcher import StrategyMatcher


def _gene(code="000001", total=65.0, freq=25, zt_count=1, factors=None) -> GeneScore:
    """构造 GeneScore；默认 factors 含涨停频次 25（命中 first_plate）。"""
    return GeneScore(
        code=code, name=code, total_score=total,
        factors=factors or {"涨停频次": freq}, wilson_adjusted=total,
        qualify=True, high_gene=False, last_zt_dates=[], zt_count_250d=zt_count,
    )


def _card(code="000001", indicators=None, pool_item=None, derived=None) -> DiagnosisCard:
    ind = indicators or IndicatorSet(code=code, name=code)
    return DiagnosisCard(
        code=code, name=code, indicators=ind,
        activity=ActivityAssessment(tier=ActivityTier.COLD, rules_applied=[]),
        stabilization=StabilizationSignals(), as_of=datetime.now(),
        pool_item=pool_item, derived=derived,
    )


class TestNineStrategiesCardConsistency(unittest.TestCase):
    """AC7：既有 9 战法传/不传 card 命中一致（9 战法从 gene 读，card override 不影响）。"""

    def test_first_plate_card_none_vs_card_consistent(self):
        g = _gene(total=65.0, freq=25)  # 命中 first_plate（score>=60 + 频次>20）
        card = _card()  # 空子对象
        no_card = match_strategies(g.code, g)
        with_card = match_strategies(g.code, g, card=card)
        fp_nc = [s for s in no_card if s.strategy_code == "first_plate"]
        fp_c = [s for s in with_card if s.strategy_code == "first_plate"]
        self.assertEqual(len(fp_nc), len(fp_c), "first_plate 命中数量应一致")
        self.assertTrue(fp_nc, "first_plate 应命中")
        self.assertEqual(fp_nc[0].confidence, fp_c[0].confidence)


class TestWeakTurnStrongCard(unittest.TestCase):
    """AC6/R4：weak_turn_strong card.derived 非空 override；derived=None 走 fallback 自补；card=None 同路径。"""

    def test_card_derived_hits_4of5(self):
        # f1 lbc>=1, f2 broken>=20, f3 drop>=5, f4 lock>=14:40 全命中；f5 hs None（zt pool 无 hs）不命中
        g = _gene(total=50.0, freq=0, factors={"涨停频次": 0})
        pool = {"lbc": 1, "p": 10.0, "zdp": 5.0}
        derived = {"broken_duration_min": 25.0, "max_drop_pct": 6.0,
                   "last_lock_time": "2026-08-09T14:50", "data_status": "ok"}
        card = _card(pool_item=pool, derived=derived,
                     indicators=IndicatorSet(code="000001", name="X", prev_turnover_pct=10.0))
        sigs = match_strategies(g.code, g, card=card)
        wts = [s for s in sigs if s.strategy_code == "weak_turn_strong"]
        self.assertTrue(wts, "weak_turn_strong 应 4/5 命中")
        self.assertEqual(wts[0].confidence, 0.7)  # 4/5（f5 hs None 不命中）

    def test_card_derived_none_fallback_no_snapshots_skips(self):
        # R4：card 非空但 derived=None → 走 fallback 自补；今日无 snapshots → 仍 missing_s070_r7 跳过
        g = _gene(total=50.0, freq=0, factors={"涨停频次": 0})
        card = _card(pool_item={"lbc": 1, "p": 10.0}, derived=None)
        with mock.patch("risk.seal_intraday_collector.get_snapshots_by_code", return_value=[]):
            sigs = match_strategies(g.code, g, card=card)
        wts = [s for s in sigs if s.strategy_code == "weak_turn_strong"]
        self.assertEqual(wts, [], "derived=None + 今日无 snapshots → fallback 后仍 missing_s070_r7 跳过不输出")

    def test_card_derived_none_fallback_self_supplement_hits(self):
        # R4：card 非空但 derived=None → 走 fallback 自补；今日 snapshots 有值 → 正常 4/5 命中
        g = _gene(total=50.0, freq=0, factors={"涨停频次": 0})
        card = _card(pool_item={"lbc": 1, "p": 10.0}, derived=None)
        derived_fb = {"broken_duration_min": 25.0, "max_drop_pct": 6.0,
                      "last_lock_time": "2026-08-09T14:50", "data_status": "ok"}
        with mock.patch("risk.seal_intraday_collector.get_snapshots_by_code", return_value=[{}]), \
             mock.patch("strategies.intraday_features.compute_derived_features",
                        return_value=derived_fb):
            sigs = match_strategies(g.code, g, card=card)
        wts = [s for s in sigs if s.strategy_code == "weak_turn_strong"]
        self.assertTrue(wts, "derived=None + fallback snapshots 有值 → 应 fallback 自补后命中")
        self.assertEqual(wts[0].confidence, 0.7)  # 4/5（f5 hs None 不命中）

    def test_card_none_uses_s070_fallback(self):
        # card=None → 走既有 S070 fallback（取今日 snapshots）；测试环境无 snapshots → missing → 不输出
        g = _gene(total=50.0, freq=0, factors={"涨停频次": 0})
        # mock 今日 snapshots 为空（模拟盘前未采集）
        with mock.patch("risk.seal_intraday_collector.get_snapshots_by_code", return_value=[]):
            sigs = match_strategies(g.code, g, pool_item={"lbc": 1, "p": 10.0})  # card=None
        wts = [s for s in sigs if s.strategy_code == "weak_turn_strong"]
        self.assertEqual(wts, [], "card=None + 今日无 snapshots → missing_s070_r7 不输出（fallback 行为不变）")


class TestPatternReversalCard(unittest.TestCase):
    """AC6：pattern_reversal card 非空从 pool_item/indicators 读；f4 从 amount_yi/prev_amount_yi 补活。"""

    def test_card_volume_f4_hits_5of5(self):
        # f1 zdp<9.5, f2 max_high>=7, f3 shadow>=4, f4 volume_1d>volume_2d*1.2, f5 ma5=Upward 全命中
        g = _gene(total=50.0, freq=0, factors={"涨停频次": 0})
        ind = IndicatorSet(code="000001", name="X", max_high_pct=8.0, shadow_length_pct=5.0,
                           ma_5_status="Upward", amount_yi=20.0, prev_amount_yi=10.0)
        pool = {"zdp": 5.0, "p": 10.0}
        card = _card(indicators=ind, pool_item=pool)
        sigs = match_strategies(g.code, g, card=card)
        pr = [s for s in sigs if s.strategy_code == "pattern_reversal"]
        self.assertTrue(pr, "pattern_reversal 应 5/5 命中")
        self.assertEqual(pr[0].confidence, 1.0)  # f4 补活后全命中

    def test_card_none_no_pattern_reversal(self):
        # card=None + pool_item=None → close_pct=None → f1 不命中
        g = _gene(total=50.0, freq=0, factors={"涨停频次": 0})
        sigs = match_strategies(g.code, g)  # 无 pool_item/card
        pr = [s for s in sigs if s.strategy_code == "pattern_reversal"]
        self.assertEqual(pr, [], "无 pool_item → pattern_reversal 不命中")


class TestStrategyMatcherCard(unittest.TestCase):
    """R6：StrategyMatcher.match/match_batch 透传 card/cards_map。"""

    def test_match_passes_card(self):
        g = _gene(total=50.0, freq=0, factors={"涨停频次": 0})
        pool = {"lbc": 1, "p": 10.0, "zdp": 5.0}
        derived = {"broken_duration_min": 25.0, "max_drop_pct": 6.0,
                   "last_lock_time": "2026-08-09T14:50", "data_status": "ok"}
        card = _card(pool_item=pool, derived=derived,
                     indicators=IndicatorSet(code="000001", name="X", prev_turnover_pct=10.0))
        matcher = StrategyMatcher()
        sigs = matcher.match(g, card=card)
        self.assertTrue([s for s in sigs if s.strategy_code == "weak_turn_strong"])

    def test_match_batch_passes_cards_map(self):
        g = _gene(total=50.0, freq=0, factors={"涨停频次": 0})
        pool = {"lbc": 1, "p": 10.0, "zdp": 5.0}
        derived = {"broken_duration_min": 25.0, "max_drop_pct": 6.0,
                   "last_lock_time": "2026-08-09T14:50", "data_status": "ok"}
        card = _card(pool_item=pool, derived=derived,
                     indicators=IndicatorSet(code="000001", name="X", prev_turnover_pct=10.0))
        matcher = StrategyMatcher()
        results = matcher.match_batch([g], cards_map={"000001": card})
        self.assertIn("000001", results)
        self.assertTrue([s for s in results["000001"] if s.strategy_code == "weak_turn_strong"])

    def test_match_no_card_backward_compat(self):
        # 既有调用不传 card → 行为不变（既有 9 战法从 gene 读）
        g = _gene(total=65.0, freq=25)
        matcher = StrategyMatcher()
        sigs = matcher.match(g)  # 不传 card
        self.assertTrue([s for s in sigs if s.strategy_code == "first_plate"])


if __name__ == "__main__":
    unittest.main()
