# -*- coding: utf-8 -*-
"""financial_rigor AC5 复算交叉核对（S002 G2，TDD RED）。

用 tools.financial_rigor.verify_activity_tier 独立重算活跃度分档，
对照 candidate_funnel.diagnosis.assess_activity 的输出，确认可复现。
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from candidate_funnel.diagnosis import assess_activity
from candidate_funnel.models import BaseThreshold, IndicatorSet
from tools.financial_rigor import verify_activity_tier

EFF = BaseThreshold()  # 8/20/2/10/8


class TestRigorMatchesAssessActivity(unittest.TestCase):
    """同输入：financial_rigor 重算的 tier 必须与 assess_activity 一致。"""

    CASES = [
        (25.0, 3.0, 50.0, 6.0, "热"),
        (10.0, 1.0, 5.0, 3.0, "活跃"),
        (3.0, 0.5, 2.0, 1.0, "冷"),
        (None, None, None, None, "冷"),
        (20.0, 2.0, 10.0, 8.0, "热"),
        (8.0, 2.0, 10.0, 8.0, "活跃"),
    ]

    def test_rigor_reproduces_system_tier(self):
        for turnover, vol, amt, amp, expected in self.CASES:
            with self.subTest(turnover=turnover):
                ind = IndicatorSet(
                    code="600519", name="样本",
                    turnover_pct=turnover, vol_ratio=vol,
                    amount_yi=amt, amplitude_pct=amp,
                )
                sys_assessment = assess_activity(ind, EFF)
                self.assertEqual(sys_assessment.tier.value, expected)

                r = verify_activity_tier(
                    turnover=turnover, vol_ratio=vol, amount_yi=amt, amplitude=amp,
                    turnover_cold=EFF.turnover_cold, turnover_hot=EFF.turnover_hot,
                    vol_ratio_active=EFF.vol_ratio_active,
                    amount_yi_min=EFF.amount_yi_min, amplitude_high=EFF.amplitude_high,
                    reported_tier=sys_assessment.tier.value,
                )
                self.assertEqual(r["recomputed_tier"], expected, f"{r}")
                self.assertTrue(r["consistent"], f"复算不一致: {r}")


if __name__ == "__main__":
    unittest.main()
