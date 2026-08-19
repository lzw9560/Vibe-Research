# -*- coding: utf-8 -*-
"""candidate_funnel 阈值解析测试（S002 阶段 A8 + D1-D5，TDD RED）。

对齐 specs/S002-plan.md §3.2 resolve_thresholds 与 spec §5.2 情绪自适应。
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from candidate_funnel.models import BaseThreshold, ThresholdConfig
from candidate_funnel.thresholds import resolve_thresholds


class TestResolveThresholdsManual(unittest.TestCase):
    """A8: manual 模式直用 base。"""

    def test_manual_uses_base_unchanged(self):
        cfg = ThresholdConfig(mode="manual")
        eff = resolve_thresholds(cfg, sti_phase=None)
        self.assertEqual(eff.turnover_cold, 8.0)
        self.assertEqual(eff.turnover_hot, 20.0)
        self.assertEqual(eff.vol_ratio_active, 2.0)
        # manual 不引入情绪调整
        self.assertTrue(cfg.adjustment is None or cfg.adjustment == {})


class TestResolveThresholdsDegraded(unittest.TestCase):
    """A8/D4: 缺 phase 降级为基数 + 标注。"""

    def test_suggest_missing_phase_degrades_to_base(self):
        cfg = ThresholdConfig(mode="suggest")
        eff = resolve_thresholds(cfg, sti_phase=None)
        self.assertEqual(eff.turnover_cold, 8.0)
        # 降级标记可复现
        self.assertIsNotNone(cfg.adjustment)
        self.assertIn("STI 去噪", str(cfg.adjustment))  # §44 grill：note 改为"STI 去噪固定基数"

    def test_auto_missing_phase_degrades_to_base(self):
        cfg = ThresholdConfig(mode="auto")
        eff = resolve_thresholds(cfg, sti_phase=None)
        self.assertEqual(eff.turnover_cold, 8.0)


class TestResolveThresholdsPhaseAdjusted(unittest.TestCase):
    """A8/D2: 有 phase 时按情绪调整档位边界（如暴风雨换手下限→12）。"""

    def test_storm_phase_raises_turnover_floor(self):
        cfg = ThresholdConfig(mode="auto")
        eff = resolve_thresholds(cfg, sti_phase="暴风雨")
        # §44 grill 2026-08-17（S072 STI 去噪）：sentiment_phase 不再调阈值，暴风雨固定基数 8.0
        self.assertEqual(eff.turnover_cold, 8.0)
        # 调整项写入 adjustment 以便可复现（AC5）
        self.assertIsNotNone(cfg.adjustment)
        self.assertTrue(len(cfg.adjustment) > 0)

    def test_clear_phase_keeps_base(self):
        cfg = ThresholdConfig(mode="auto")
        eff = resolve_thresholds(cfg, sti_phase="晴天")
        self.assertEqual(eff.turnover_cold, 8.0)

    def test_effective_is_base_threshold_instance(self):
        cfg = ThresholdConfig(mode="suggest")
        eff = resolve_thresholds(cfg, sti_phase="晴天")
        self.assertIsInstance(eff, BaseThreshold)


class TestResolveSuggestBasis(unittest.TestCase):
    """D3: suggest 模式给出建议阈值 + 依据（可复现）。"""

    def test_suggest_storm_includes_basis(self):
        cfg = ThresholdConfig(mode="suggest")
        eff = resolve_thresholds(cfg, sti_phase="暴风雨")
        # §44 grill 2026-08-17：暴风雨不再 raise turnover floor，固定基数
        self.assertEqual(eff.turnover_cold, 8.0)
        self.assertIsNotNone(cfg.adjustment)
        self.assertIn("依据", str(cfg.adjustment))


class TestResolveReproducible(unittest.TestCase):
    """AC5: 同输入两次解析结果一致。"""

    def test_same_input_same_output(self):
        cfg1 = ThresholdConfig(mode="auto")
        cfg2 = ThresholdConfig(mode="auto")
        eff1 = resolve_thresholds(cfg1, sti_phase="暴风雨")
        eff2 = resolve_thresholds(cfg2, sti_phase="暴风雨")
        self.assertEqual(eff1.model_dump(), eff2.model_dump())
        self.assertEqual(cfg1.adjustment, cfg2.adjustment)


if __name__ == "__main__":
    unittest.main()
