# -*- coding: utf-8 -*-
"""S148 Phase 2 (a)：run_first_board_filter 接受注入 pool，跳过自取 fetch_zt_pool。

接入涨停叉时由调用方共享 zt_pool 源传入，dedup + 让涨停叉 R1 过滤覆盖 first-board。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRunFirstBoardFilterInjectedPool(unittest.TestCase):
    """注入 pool 时跳过 fetch_zt_pool；未注入时向后兼容自取。"""

    def test_injected_pool_skips_fetch_zt_pool(self):
        from strategies.first_board_filter import run_first_board_filter
        injected = [{"c": "600001", "name": "测试股"}]
        with mock.patch("strategies.first_board_filter.fetch_zt_pool") as mock_fetch, \
             mock.patch("strategies.first_board_filter.rank_candidates", return_value=[]) as _mock_rank, \
             mock.patch("strategies.first_board_filter.filter_first_board", return_value=[]) as _mock_ffb, \
             mock.patch("vr_paths.is_trading_day", return_value=True):
            result = run_first_board_filter("2026-09-03", pool=injected)
        mock_fetch.assert_not_called()  # 注入时不应再自取
        self.assertEqual(result["zt_pool_count"], 1)  # 用注入 pool 的长度

    def test_default_fetches_when_no_injection(self):
        from strategies.first_board_filter import run_first_board_filter
        with mock.patch("strategies.first_board_filter.fetch_zt_pool", return_value=[]) as mock_fetch, \
             mock.patch("strategies.first_board_filter.rank_candidates", return_value=[]) as _mock_rank, \
             mock.patch("strategies.first_board_filter.filter_first_board", return_value=[]) as _mock_ffb, \
             mock.patch("vr_paths.is_trading_day", return_value=True):
            run_first_board_filter("2026-09-03")
        mock_fetch.assert_called_once()  # 未注入 → 自取（向后兼容）


class TestAttachFirstBoardAnalysis(unittest.TestCase):
    """S148 Phase 2 (a)：首板 9 维评分接到 lane final_candidates（load_scores 缓存）。"""

    def test_merges_for_matching_codes(self):
        from strategies.first_board_filter import attach_first_board_analysis
        cards = [{"code": "600001"}, {"code": "000002"}]
        cached = {"scored_candidates": [
            {"code": "600001", "scores": {"seal_time": 80}, "total": 75.0, "market_phase": "普通"}
        ]}
        with mock.patch("strategies.first_board_filter.load_scores", return_value=cached):
            attach_first_board_analysis(cards, "2026-09-03")
        self.assertEqual(cards[0]["first_board_analysis"]["total"], 75.0)
        self.assertNotIn("first_board_analysis", cards[1])  # 非首板不加

    def test_no_cache_no_change(self):
        from strategies.first_board_filter import attach_first_board_analysis
        cards = [{"code": "600001"}]
        with mock.patch("strategies.first_board_filter.load_scores", return_value={}):
            attach_first_board_analysis(cards, "2026-09-03")
        self.assertNotIn("first_board_analysis", cards[0])

    def test_failure_does_not_crash(self):
        from strategies.first_board_filter import attach_first_board_analysis
        cards = [{"code": "600001"}]
        with mock.patch("strategies.first_board_filter.load_scores", side_effect=RuntimeError("db")):
            attach_first_board_analysis(cards, "2026-09-03")  # 不崩
        self.assertNotIn("first_board_analysis", cards[0])


if __name__ == "__main__":
    unittest.main()
