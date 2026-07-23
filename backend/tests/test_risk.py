# -*- coding: utf-8 -*-
"""risk.py 纯函数单测。"""

import unittest
from risk import get_dynamic_thresholds, calculate_capital_flow_trend, calculate_flow_adjustment


class TestDynamicThresholds(unittest.TestCase):
    """动态阈值测试。"""

    def test_known_phase_returns_thresholds(self):
        thresholds = get_dynamic_thresholds("HIGH潮")
        self.assertEqual(thresholds["high"], 75)
        self.assertEqual(thresholds["medium"], 50)
        self.assertEqual(thresholds["low"], 25)

    def test_unknown_phase_returns_default(self):
        thresholds = get_dynamic_thresholds("UNKNOWN")
        self.assertEqual(thresholds["high"], 65)
        self.assertEqual(thresholds["medium"], 40)
        self.assertEqual(thresholds["low"], 15)

    def test_none_phase_returns_default(self):
        thresholds = get_dynamic_thresholds(None)
        self.assertEqual(thresholds["high"], 65)


class TestCapitalFlowTrend(unittest.TestCase):
    """资金流趋势判断测试。"""

    def test_empty_history_returns_oscillating(self):
        self.assertEqual(calculate_capital_flow_trend([]), "震荡")

    def test_single_entry_returns_oscillating(self):
        self.assertEqual(calculate_capital_flow_trend([{"capital_flow_signal": 0.5}]), "震荡")

    def test_two_entries_returns_oscillating(self):
        self.assertEqual(
            calculate_capital_flow_trend([{"capital_flow_signal": 0.5}, {"capital_flow_signal": -0.5}]),
            "震荡"
        )

    def test_upward_trend(self):
        history = [{"capital_flow_signal": 0.1}, {"capital_flow_signal": 0.2}, {"capital_flow_signal": 0.5}]
        self.assertEqual(calculate_capital_flow_trend(history), "流入")

    def test_downward_trend(self):
        history = [{"capital_flow_signal": 0.8}, {"capital_flow_signal": 0.2}, {"capital_flow_signal": 0.1}]
        self.assertEqual(calculate_capital_flow_trend(history), "流出")

    def test_oscillating_trend(self):
        history = [{"capital_flow_signal": 0.1}, {"capital_flow_signal": 0.2}, {"capital_flow_signal": 0.15}]
        self.assertEqual(calculate_capital_flow_trend(history), "震荡")


class TestFlowAdjustment(unittest.TestCase):
    """资金流调整值测试。"""

    def test_positive_signal_decreases_risk(self):
        adjustment = calculate_flow_adjustment({"capital_flow_signal": 0.5})
        self.assertEqual(adjustment, -10.0)

    def test_negative_signal_increases_risk(self):
        adjustment = calculate_flow_adjustment({"capital_flow_signal": -0.5})
        self.assertEqual(adjustment, 10.0)

    def test_zero_signal_no_adjustment(self):
        adjustment = calculate_flow_adjustment({"capital_flow_signal": 0.0})
        self.assertEqual(adjustment, 0.0)

    def test_missing_signal_returns_zero(self):
        adjustment = calculate_flow_adjustment({})
        self.assertEqual(adjustment, 0.0)

    def test_non_numeric_signal_returns_zero(self):
        adjustment = calculate_flow_adjustment({"capital_flow_signal": "invalid"})
        self.assertEqual(adjustment, 0.0)


if __name__ == "__main__":
    unittest.main()
