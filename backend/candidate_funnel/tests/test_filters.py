# -*- coding: utf-8 -*-
"""sources/_filters 入口过滤测试（S002 B8，TDD RED）。

AC8：ST/*ST/退市整理/新股次新/停牌 在漏斗中剔除或标注，不与正常股混排。
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from candidate_funnel.sources._filters import classify_exclusion


class TestClassifyExclusion(unittest.TestCase):
    def test_st_stock_excluded(self):
        excluded, reason = classify_exclusion("ST贵人", "603555")
        self.assertTrue(excluded)
        self.assertIn("ST", reason)

    def test_star_st_excluded(self):
        excluded, reason = classify_exclusion("*ST海伦", "300700")
        self.assertTrue(excluded)
        self.assertIn("ST", reason)

    def test_delisting_excluded(self):
        excluded, reason = classify_exclusion("退市博元", "600656")
        self.assertTrue(excluded)
        self.assertIsNotNone(reason)

    def test_new_share_flagged(self):
        excluded, reason = classify_exclusion("N新股", "001234")
        self.assertTrue(excluded)
        self.assertIsNotNone(reason)

    def test_normal_stock_not_excluded(self):
        excluded, reason = classify_exclusion("贵州茅台", "600519")
        self.assertFalse(excluded)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
