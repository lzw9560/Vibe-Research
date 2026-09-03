# -*- coding: utf-8 -*-
"""sources/_filters 入口过滤测试（S002 B8，TDD RED）。

AC8：ST/*ST/退市整理/新股次新/停牌 在漏斗中剔除或标注，不与正常股混排。
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from candidate_funnel.sources._filters import (
    classify_exclusion,
    classify_board,
    classify_tradability,
)


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


class TestClassifyBoard(unittest.TestCase):
    """S148 R1：共享 board 分类，补 688/北交所空缺。"""

    def test_main_board(self):
        for code in ("600519", "000001", "002594", "603986"):
            self.assertEqual(classify_board(code), "主板", f"{code} 应为主板")

    def test_chinext(self):
        self.assertEqual(classify_board("300750"), "创业板")
        self.assertEqual(classify_board("301234"), "创业板")

    def test_star(self):
        self.assertEqual(classify_board("688981"), "科创板")
        self.assertEqual(classify_board("689009"), "科创板")

    def test_bse(self):
        self.assertEqual(classify_board("830799"), "北交所")
        self.assertEqual(classify_board("430047"), "北交所")

    def test_other(self):
        self.assertEqual(classify_board("999999"), "其他")


class TestClassifyTradability(unittest.TestCase):
    """S148 R2：共享可交易性过滤 = ST(radar carve-out) + board 排除。"""

    def test_st_excluded_without_radar(self):
        keep, reason, st_play = classify_tradability("ST贵人", "603555", {})
        self.assertFalse(keep)
        self.assertIn("ST", reason)
        self.assertIsNone(st_play)

    def test_st_reincluded_with_radar(self):
        keep, reason, st_play = classify_tradability("ST贵人", "603555", {"603555": "摘帽"})
        self.assertTrue(keep)
        self.assertIsNone(reason)
        self.assertEqual(st_play, "摘帽")

    def test_chinext_excluded(self):
        keep, reason, _ = classify_tradability("宁德时代", "300750", {})
        self.assertFalse(keep)
        self.assertIn("创业板", reason)

    def test_star_excluded(self):
        keep, reason, _ = classify_tradability("中芯国际", "688981", {})
        self.assertFalse(keep)
        self.assertIn("科创板", reason)

    def test_bse_excluded(self):
        keep, reason, _ = classify_tradability("某北交所股", "830799", {})
        self.assertFalse(keep)
        self.assertIn("北交所", reason)

    def test_board_takes_precedence_over_st_play(self):
        # 科创板 ST 且在 radar 白名单 → 仍按 board 排除（无权限是硬约束，摘帽也救不了）
        keep, reason, _ = classify_tradability("*ST科创", "688981", {"688981": "摘帽"})
        self.assertFalse(keep)
        self.assertIn("科创板", reason)

    def test_normal_stock_kept(self):
        keep, reason, st_play = classify_tradability("贵州茅台", "600519", {})
        self.assertTrue(keep)
        self.assertIsNone(reason)
        self.assertIsNone(st_play)

    def test_delisting_excluded(self):
        keep, reason, _ = classify_tradability("退市博元", "600656", {})
        self.assertFalse(keep)
        self.assertIsNotNone(reason)

    def test_radar_default_empty(self):
        # radar_set=None → 等价空白名单 → ST flat 排除（radar 未上线前的安全默认）
        keep, reason, _ = classify_tradability("ST贵人", "603555")
        self.assertFalse(keep)


if __name__ == "__main__":
    unittest.main()
