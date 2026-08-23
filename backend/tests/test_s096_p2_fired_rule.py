# -*- coding: utf-8 -*-
"""S096：_format_p2_fired_rule fired_rule 字符串单测。

3 case：红期 override 显覆盖 / normal 四档 / floor 缺数据降级标注。
big_loss 恒 None（_emotion 无大面股字段）→ big_loss≥8 永不 fired，不测该路径。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pre_market_workflow import PreMarketWorkflow


def _rule(factors: dict, phase: str, would_be_phase: str) -> str:
    """_format_p2_fired_rule 不用 self（仅 factors/phase/would_be_phase），传 None 免实例化。"""
    return PreMarketWorkflow._format_p2_fired_rule(None, factors, phase, would_be_phase)  # type: ignore[arg-type]


class TestFormatP2FiredRule(unittest.TestCase):
    def test_red_period_floor_override(self):
        """floor≥20 → 红期硬熔断 fired，显触发因子 + 覆盖了什么四档。"""
        factors = {"zt_count": 120, "big_loss": None, "floor": 25,
                   "ladder_success": 0.3, "ladder_height": 3}
        rule = _rule(factors, "红期", "亢奋")  # would_be_phase=四档 zt=120→亢奋
        self.assertIn("红期硬熔断", rule)
        self.assertIn("floor=25≥20", rule)
        self.assertIn("覆盖", rule)
        self.assertIn("zt=120", rule)
        self.assertIn("亢奋", rule)

    def test_normal_four_tier(self):
        """floor present <20, zt<100 → 活跃（四档，硬熔断 checked 未 fired）。"""
        factors = {"zt_count": 85, "big_loss": None, "floor": 1,
                   "ladder_success": 0.3, "ladder_height": 3}
        rule = _rule(factors, "活跃", "活跃")
        self.assertIn("四档", rule)
        self.assertIn("zt=85", rule)
        self.assertIn("活跃", rule)
        self.assertNotIn("红期硬熔断", rule)

    def test_floor_missing_degradation(self):
        """floor None（big_loss 恒 None）→ 红期硬熔断未检，仅四档。"""
        factors = {"zt_count": 85, "big_loss": None, "floor": None,
                   "ladder_success": None, "ladder_height": None}
        rule = _rule(factors, "活跃", "活跃")
        self.assertIn("红期硬熔断未检", rule)
        self.assertIn("floor 数据缺", rule)
        self.assertIn("仅四档", rule)
        self.assertIn("zt=85", rule)


if __name__ == "__main__":
    unittest.main()
