# -*- coding: utf-8 -*-
"""portfolio.py 纯函数与集成单测。"""

import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import portfolio


class TestPortfolioCore(unittest.TestCase):
    """持仓核心逻辑测试。"""

    def setUp(self):
        """每个测试使用独立的临时 JSON 文件。"""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.pf_file = os.path.join(self.tmpdir.name, "portfolio.json")
        portfolio.PF_FILE = self.pf_file
        portfolio.CACHE_DIR = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run(self, coro):
        return asyncio.run(coro)

    def test_add_holding_creates_new(self):
        result = self._run(portfolio.add_holding("600519", 100, 1800.0))
        self.assertEqual(len(result["holdings"]), 1)
        h = result["holdings"][0]
        self.assertEqual(h["code"], "600519")
        self.assertEqual(h["shares"], 100)
        self.assertEqual(h["cost"], 1800.0)

    def test_add_holding_merges_same_code(self):
        self._run(portfolio.add_holding("600519", 100, 1800.0))
        result = self._run(portfolio.add_holding("600519", 200, 1900.0))
        self.assertEqual(len(result["holdings"]), 1)
        h = result["holdings"][0]
        # 加权平均成本：(100*1800 + 200*1900) / 300 = 1866.67
        self.assertAlmostEqual(h["shares"], 300.0)
        self.assertAlmostEqual(h["cost"], 1866.67, places=2)

    def test_remove_holding(self):
        self._run(portfolio.add_holding("600519", 100, 1800.0))
        result = self._run(portfolio.remove_holding("600519"))
        self.assertEqual(len(result["holdings"]), 0)

    def test_remove_holding_not_found(self):
        result = self._run(portfolio.remove_holding("000001"))
        self.assertEqual(len(result["holdings"]), 0)

    def test_close_position_adds_to_closed(self):
        self._run(portfolio.add_holding("600519", 100, 1800.0))
        result = self._run(portfolio.close_position("600519", "2025-07-23", 2000.0, 100, 1800.0))
        self.assertEqual(len(result["holdings"]), 0)
        self.assertEqual(len(result["closed"]), 1)
        closed = result["closed"][0]
        self.assertEqual(closed["code"], "600519")
        self.assertEqual(closed["shares"], 100)
        # P&L = (2000 - 1800) * 100 = 20000
        self.assertAlmostEqual(closed["pnl"], 20000.0)
        self.assertAlmostEqual(closed["pnl_pct"], 11.11, places=2)

    def test_close_position_zero_cost(self):
        self._run(portfolio.add_holding("600519", 100, 0.0))
        result = self._run(portfolio.close_position("600519", "2025-07-23", 2000.0, 100, 0.0))
        closed = result["closed"][0]
        self.assertEqual(closed["pnl_pct"], 0.0)

    def test_get_portfolio_empty(self):
        result = self._run(portfolio.get_portfolio())
        self.assertEqual(result["holdings"], [])
        self.assertEqual(result["totals"]["market_value"], 0.0)

    def test_get_portfolio_with_mock_quotes(self):
        self._run(portfolio.add_holding("600519", 100, 1800.0))
        mock_quotes = {
            "600519": {"name": "贵州茅台", "price": 2000.0}
        }
        with patch.object(portfolio.astock, "tencent_quote", return_value=mock_quotes):
            result = self._run(portfolio.get_portfolio())
        self.assertEqual(len(result["holdings"]), 1)
        h = result["holdings"][0]
        self.assertEqual(h["name"], "贵州茅台")
        self.assertEqual(h["price"], 2000.0)
        self.assertAlmostEqual(h["market_value"], 200000.0)
        self.assertAlmostEqual(h["pnl"], 20000.0)
        self.assertAlmostEqual(h["pnl_pct"], 11.11, places=2)

    def test_get_portfolio_totals(self):
        self._run(portfolio.add_holding("600519", 100, 1800.0))
        self._run(portfolio.add_holding("000001", 200, 10.0))
        mock_quotes = {
            "600519": {"name": "贵州茅台", "price": 2000.0},
            "000001": {"name": "平安银行", "price": 12.0}
        }
        with patch.object(portfolio.astock, "tencent_quote", return_value=mock_quotes):
            result = self._run(portfolio.get_portfolio())
        totals = result["totals"]
        # 600519: 100*2000 = 200000, cost = 100*1800 = 180000
        # 000001: 200*12 = 2400, cost = 200*10 = 2000
        self.assertAlmostEqual(totals["market_value"], 202400.0)
        self.assertAlmostEqual(totals["cost"], 182000.0)
        self.assertAlmostEqual(totals["pnl"], 20400.0)
        self.assertAlmostEqual(totals["pnl_pct"], 11.21, places=2)

    def test_get_portfolio_handles_quote_failure(self):
        self._run(portfolio.add_holding("600519", 100, 1800.0))
        with patch.object(portfolio.astock, "tencent_quote", side_effect=Exception("API error")):
            result = self._run(portfolio.get_portfolio())
        # 行情失败时，价格应为 0.0
        h = result["holdings"][0]
        self.assertEqual(h["price"], 0.0)
        self.assertEqual(h["market_value"], 0.0)

    def test_realized_pnl_calculation(self):
        self._run(portfolio.add_holding("600519", 100, 1800.0))
        self._run(portfolio.close_position("600519", "2025-07-23", 2000.0, 100, 1800.0))
        result = self._run(portfolio.get_portfolio())
        self.assertAlmostEqual(result["realized_pnl"], 20000.0)

    def test_remove_closed(self):
        self._run(portfolio.add_holding("600519", 100, 1800.0))
        self._run(portfolio.close_position("600519", "2025-07-23", 2000.0, 100, 1800.0))
        result = self._run(portfolio.remove_closed(0))
        self.assertEqual(len(result["closed"]), 0)

    def test_remove_closed_invalid_index(self):
        self._run(portfolio.add_holding("600519", 100, 1800.0))
        result = self._run(portfolio.remove_closed(999))
        self.assertEqual(len(result["closed"]), 0)


class TestPortfolioScheduler(unittest.TestCase):
    """后台定时任务测试。"""

    def test_start_scheduler_creates_thread(self):
        with patch("threading.Thread.start"):
            portfolio.start_scheduler(interval=60)
            # 线程已创建（start 被 mock，不会真正运行）

    def test_refresh_snapshot_updates_timestamp(self):
        tmpdir = tempfile.TemporaryDirectory()
        pf_file = os.path.join(tmpdir.name, "portfolio.json")
        portfolio.PF_FILE = pf_file
        portfolio.CACHE_DIR = tmpdir.name
        try:
            asyncio.run(portfolio._refresh_snapshot())
            d = portfolio._load()
            self.assertIsNotNone(d.get("last_refresh"))
            self.assertRegex(d["last_refresh"], r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
