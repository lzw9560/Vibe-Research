# -*- coding: utf-8 -*-
"""诊断卡聚合测试（S002 C1-C5，TDD RED）。

assess_activity 可复现分档（C1）；detect_stabilization 四信号+依据（C2）；
build_diagnosis_card 聚合（C3）；missing 透明（C4）。
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from candidate_funnel.diagnosis import (
    assess_activity,
    build_diagnosis_card,
    build_indicator_set,
    detect_stabilization,
)
from candidate_funnel.models import (
    ActivityTier,
    BaseThreshold,
    IndicatorSet,
    StabilizationSignals,
)

EFF = BaseThreshold()


class TestAssessActivity(unittest.TestCase):
    """C1: 规则可复现分档。"""

    def test_hot_tier(self):
        ind = IndicatorSet(code="600519", name="贵州茅台", turnover_pct=25.0, vol_ratio=3.0, amount_yi=50.0)
        a = assess_activity(ind, EFF)
        self.assertEqual(a.tier, ActivityTier.HOT)
        self.assertTrue(len(a.rules_applied) > 0)

    def test_active_tier(self):
        ind = IndicatorSet(code="000001", name="平安银行", turnover_pct=10.0)
        self.assertEqual(assess_activity(ind, EFF).tier, ActivityTier.ACTIVE)

    def test_cold_tier(self):
        ind = IndicatorSet(code="000002", name="万科A", turnover_pct=3.0)
        self.assertEqual(assess_activity(ind, EFF).tier, ActivityTier.COLD)

    def test_missing_turnover_defaults_cold(self):
        ind = IndicatorSet(code="000003", name="样本", turnover_pct=None)
        a = assess_activity(ind, EFF)
        self.assertEqual(a.tier, ActivityTier.COLD)
        self.assertIn("换手未取得", a.rules_applied)

    def test_reproducible(self):
        ind = IndicatorSet(code="600519", name="贵州茅台", turnover_pct=25.0, vol_ratio=3.0)
        a1 = assess_activity(ind, EFF)
        a2 = assess_activity(ind, EFF)
        self.assertEqual(a1.model_dump(), a2.model_dump())


class TestDetectStabilization(unittest.TestCase):
    """C2: 企稳四信号 + evidence，每信号 bool 或 None。"""

    _RECOVERY = {
        "dt_count": 5, "prev_dt_count": 12,        # 跌停减少
        "volume": 1.2e9, "prev_volume": 1.0e9,      # 量能不再下降
        "main_flow": 5e8, "prev_main_flow": -3e8,   # 主力转正
        "max_boards": 6, "prev_max_boards": 4,      # 连板高度上升
    }

    def test_recovery_signals_all_true(self):
        s = detect_stabilization(IndicatorSet(code="M", name="市场"), self._RECOVERY)
        self.assertIsInstance(s, StabilizationSignals)
        self.assertTrue(s.fewer_limit_downs)
        self.assertTrue(s.volume_stop_falling)
        self.assertTrue(s.main_flow_turning_positive)
        self.assertTrue(s.board_height_rising)
        self.assertTrue(len(s.evidence) > 0)

    def test_no_recovery_signals_false(self):
        ctx = {
            "dt_count": 15, "prev_dt_count": 10,
            "volume": 1.0e9, "prev_volume": 1.2e9,
            "main_flow": -5e8, "prev_main_flow": 3e8,
            "max_boards": 3, "prev_max_boards": 5,
        }
        s = detect_stabilization(IndicatorSet(code="M", name="市场"), ctx)
        self.assertFalse(s.fewer_limit_downs)
        self.assertFalse(s.volume_stop_falling)
        self.assertFalse(s.main_flow_turning_positive)
        self.assertFalse(s.board_height_rising)

    def test_missing_context_yields_none(self):
        s = detect_stabilization(IndicatorSet(code="M", name="市场"), {})
        self.assertIsNone(s.fewer_limit_downs)
        self.assertIsNone(s.volume_stop_falling)
        self.assertIsNone(s.main_flow_turning_positive)
        self.assertIsNone(s.board_height_rising)

    def test_reproducible(self):
        s1 = detect_stabilization(IndicatorSet(code="M", name="市场"), self._RECOVERY)
        s2 = detect_stabilization(IndicatorSet(code="M", name="市场"), self._RECOVERY)
        self.assertEqual(s1.model_dump(), s2.model_dump())


class TestBuildDiagnosisCardAndMissing(unittest.TestCase):
    """C3/C4: 聚合 + missing 透明。"""

    def test_missing_folded_into_indicators(self):
        genes = {}
        activity = {"600519": {"name": "贵州茅台", "turnover_pct": 25.0,
                               "missing": {"vol_ratio": "行情字段未取得"}}}
        fund = {"600519": {"main_net_inflow": 1.0, "missing": {"northbound": "北向数据不可得"}}}
        ind = build_indicator_set("600519", "贵州茅台", genes, activity, fund, {}, {}, {})
        self.assertEqual(ind.missing.get("vol_ratio"), "行情字段未取得")
        self.assertEqual(ind.missing.get("northbound"), "北向数据不可得")

    def test_build_card(self):
        ind = IndicatorSet(code="600519", name="贵州茅台", turnover_pct=25.0)
        card = build_diagnosis_card("600519", "贵州茅台", ind, EFF, market_ctx=None,
                                    as_of=datetime(2026, 7, 28, 9, 0))
        self.assertEqual(card.code, "600519")
        self.assertEqual(card.activity.tier, ActivityTier.HOT)
        self.assertIsInstance(card.stabilization, StabilizationSignals)


if __name__ == "__main__":
    unittest.main()
