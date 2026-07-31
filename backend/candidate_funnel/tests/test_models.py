# -*- coding: utf-8 -*-
"""candidate_funnel 模型口径一致性测试（S002 阶段 A，TDD RED）。

对齐 specs/S002-plan.md §2 与 specs/S002-打板工作流重构.md §5.2。
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime

# backend 目录进 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from candidate_funnel.models import (
    ActivityAssessment,
    ActivityTier,
    Announcement,
    BaseThreshold,
    DiagnosisCard,
    FilterRecord,
    FunnelLayer,
    FunnelResult,
    IndicatorSet,
    StabilizationSignals,
    ThresholdConfig,
)


class TestBaseThreshold(unittest.TestCase):
    """A2: 基数阈值 8/20/2/10/8（spec §5.2 签字固化）。"""

    def test_defaults_match_spec(self):
        b = BaseThreshold()
        self.assertEqual(b.turnover_cold, 8.0)
        self.assertEqual(b.turnover_hot, 20.0)
        self.assertEqual(b.vol_ratio_active, 2.0)
        self.assertEqual(b.amount_yi_min, 10.0)
        self.assertEqual(b.amplitude_high, 8.0)


class TestThresholdConfig(unittest.TestCase):
    """A3: mode(auto/suggest/manual)/base/adjustment/sentiment_phase/effective。"""

    def test_default_mode_is_suggest(self):
        cfg = ThresholdConfig()
        self.assertEqual(cfg.mode, "suggest")

    def test_base_defaults_to_spec_thresholds(self):
        cfg = ThresholdConfig()
        self.assertIsInstance(cfg.base, BaseThreshold)
        self.assertEqual(cfg.base.turnover_cold, 8.0)

    def test_effective_none_until_resolved(self):
        cfg = ThresholdConfig()
        self.assertIsNone(cfg.effective)
        self.assertIsNone(cfg.sentiment_phase)
        self.assertIsNone(cfg.adjustment)


class TestIndicatorSet(unittest.TestCase):
    """A4: 六类字段全量 + missing 透明。"""

    def test_minimal_construction_with_none_fields(self):
        ind = IndicatorSet(code="600519", name="贵州茅台")
        self.assertEqual(ind.code, "600519")
        # 六类字段任一未取得为 None，不报错
        self.assertIsNone(ind.turnover_pct)
        self.assertIsNone(ind.vol_ratio)
        self.assertIsNone(ind.main_net_inflow)
        self.assertIsNone(ind.consec_boards)
        self.assertEqual(ind.announcements, [])
        self.assertEqual(ind.concepts, [])

    def test_missing_dict_default_empty_and_fillable(self):
        ind = IndicatorSet(code="000001", name="平安银行")
        self.assertEqual(ind.missing, {})
        ind.missing["northbound"] = "北向数据不可得"
        self.assertEqual(ind.missing["northbound"], "北向数据不可得")


class TestActivityModels(unittest.TestCase):
    """A5: ActivityTier 三枚举 + ActivityAssessment(含 rules_applied)。"""

    def test_activity_tier_three_values(self):
        self.assertEqual({t.value for t in ActivityTier}, {"冷", "活跃", "热"})

    def test_activity_assessment_carries_rules(self):
        a = ActivityAssessment(tier=ActivityTier.HOT, rules_applied=["换手>20%", "量比>2"])
        self.assertEqual(a.tier, ActivityTier.HOT)
        self.assertEqual(a.rules_applied, ["换手>20%", "量比>2"])


class TestStabilizationSignals(unittest.TestCase):
    """A5: 企稳四信号 + evidence。"""

    def test_four_signals_default_none_with_evidence(self):
        s = StabilizationSignals()
        self.assertIsNone(s.fewer_limit_downs)
        self.assertIsNone(s.volume_stop_falling)
        self.assertIsNone(s.main_flow_turning_positive)
        self.assertIsNone(s.board_height_rising)
        self.assertEqual(s.evidence, {})


class TestDiagnosisCard(unittest.TestCase):
    """A6: 聚合 + 无方向结论词（合规 AC10）。"""

    def test_construct_full_card(self):
        ind = IndicatorSet(code="600519", name="贵州茅台", turnover_pct=25.0)
        card = DiagnosisCard(
            code="600519",
            name="贵州茅台",
            indicators=ind,
            activity=ActivityAssessment(tier=ActivityTier.HOT, rules_applied=["换手>20%"]),
            stabilization=StabilizationSignals(),
            risk_flags=["极端估值"],
            as_of=datetime(2026, 7, 28, 9, 0, 0),
        )
        self.assertEqual(card.code, "600519")
        self.assertEqual(card.risk_flags, ["极端估值"])
        self.assertEqual(card.activity.tier, ActivityTier.HOT)

    def test_no_direction_conclusion_words_in_schema(self):
        """合规 AC10：DiagnosisCard 字段名不得含方向结论词。"""
        forbidden = {"回撤", "出货", "健康", "买入", "卖出", "止盈", "止损", "方向"}
        model_fields = set(DiagnosisCard.model_fields.keys())
        self.assertFalse(
            model_fields & forbidden,
            f"DiagnosisCard 字段命中方向词: {model_fields & forbidden}",
        )


class TestFunnelModels(unittest.TestCase):
    """A7: FilterRecord + FunnelLayer + FunnelResult。"""

    def test_filter_record(self):
        fr = FilterRecord(code="000002", name="万科A", reason="换手<8%")
        self.assertEqual(fr.reason, "换手<8%")

    def test_funnel_layer(self):
        layer = FunnelLayer(
            layer_id="R1",
            name="宽源",
            as_of=datetime(2026, 7, 28, 9, 0),
            input_count=100,
            output_count=40,
            filtered_out=[FilterRecord(code="000002", name="万科A", reason="ST")],
            output_codes=["600519"],
        )
        self.assertEqual(layer.input_count, 100)
        self.assertEqual(layer.output_count, 40)
        self.assertEqual(layer.output_codes, ["600519"])

    def test_funnel_result_has_layers_and_final_candidates(self):
        result = FunnelResult(
            run_id="run-1",
            date="2026-07-28",
            layers=[],
            final_candidates=[],
            threshold_config=ThresholdConfig(),
            as_of=datetime(2026, 7, 28, 9, 0),
        )
        self.assertEqual(result.run_id, "run-1")
        self.assertEqual(result.layers, [])
        self.assertEqual(result.final_candidates, [])


if __name__ == "__main__":
    unittest.main()
