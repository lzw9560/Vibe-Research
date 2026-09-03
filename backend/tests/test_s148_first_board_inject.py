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


if __name__ == "__main__":
    unittest.main()
