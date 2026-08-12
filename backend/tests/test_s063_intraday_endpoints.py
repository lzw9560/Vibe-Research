# -*- coding: utf-8 -*-
"""S063 T31：盘中情绪端点集成测试 + T+1 预判测试。

AC5：盘中采样端点返回 4 维度+分数+趋势+色带区间
AC7：14:30 T+1 预判端点返回双场景，收盘后 actual_score 回填
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestIntradayEndpoints(unittest.TestCase):
    """AC5：5 GET + 1 POST 端点（mock 采样）。"""

    def setUp(self):
        """清理 sampler ring buffer + DB 当日行。"""
        from routers.intraday_sentiment import _sampler
        from limitup_sti.data import get_db
        _sampler.buffer.clear()
        _sampler._last_sample_time = None
        try:
            db = get_db()
            db.execute("DELETE FROM sti_intraday")
            db.commit()
        except Exception:
            pass

    def test_latest_returns_missing_when_empty(self):
        from routers.intraday_sentiment import get_intraday_latest
        import asyncio
        result = asyncio.run(get_intraday_latest())
        self.assertEqual(result["data"]["status"], "missing")

    def test_timeline_returns_empty_when_no_data(self):
        from routers.intraday_sentiment import get_intraday_timeline
        import asyncio
        result = asyncio.run(get_intraday_timeline())
        self.assertEqual(result["data"]["snapshots"], [])

    def test_latest_returns_data_after_sample(self):
        """mock _sample_once 注入一条数据 → latest 返回。"""
        from routers.intraday_sentiment import _sampler, get_intraday_latest
        import asyncio

        _sampler.buffer.append({
            "date": "2026-08-13", "time": "09:30",
            "zt_count": 90.0, "seal_rate": 0.85, "break_rate": 0.1,
            "ad_ratio": 2.5, "score": 100.0, "trend": "up",
            "t1_baseline": 70.0, "zone": "green",
        })
        result = asyncio.run(get_intraday_latest())
        self.assertEqual(result["data"]["score"], 100.0)
        self.assertEqual(result["data"]["trend"], "up")
        self.assertEqual(result["data"]["zone"], "green")

    def test_holdings_returns_empty_when_no_holdings(self):
        from routers.intraday_sentiment import get_intraday_holdings
        import asyncio
        with mock.patch("workflow_state_repo.list_states", return_value=[]), \
             mock.patch("vr_paths.last_trading_date_str", return_value="2026-08-13"):
            result = asyncio.run(get_intraday_holdings())
        self.assertEqual(result["data"]["holdings"], [])

    def test_scenarios_returns_empty_when_no_data(self):
        from routers.intraday_sentiment import get_intraday_scenarios
        import asyncio
        result = asyncio.run(get_intraday_scenarios())
        self.assertEqual(result["data"]["scenarios"], [])

    def test_snapshot_endpoint_triggers_sample(self):
        from routers.intraday_sentiment import trigger_snapshot
        import asyncio
        with mock.patch.object(
            # _sampler._sample_once 是方法，patch 实例方法
            type(__import__("routers.intraday_sentiment", fromlist=["_sampler"])._sampler),
            "_sample_once",
            return_value={"date": "2026-08-13", "time": "09:31", "score": 50.0, "trend": "flat", "zone": "yellow"},
        ):
            result = asyncio.run(trigger_snapshot())
        self.assertIn("data", result)


class TestT1Projection(unittest.TestCase):
    """AC7：T+1 预判端点。"""

    def test_not_ready_before_1430(self):
        from routers.intraday_sentiment import get_t1_projection
        import asyncio
        # mock datetime 返 10:00（14:30 前）
        with mock.patch("routers.intraday_sentiment.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 8, 13, 10, 0)
            mock_dt.strftime = datetime.strftime
            result = asyncio.run(get_t1_projection())
        self.assertEqual(result["data"]["status"], "not_ready")

    def test_ready_returns_two_scenarios_after_1430(self):
        from routers.intraday_sentiment import _sampler, get_t1_projection
        import asyncio
        # 注入有效 snapshot
        _sampler.buffer.clear()
        _sampler.buffer.append({
            "date": "2026-08-13", "time": "14:35",
            "zt_count": 80.0, "seal_rate": 0.75, "break_rate": 0.15,
            "ad_ratio": 2.0, "score": 75.0, "trend": "up",
            "t1_baseline": 70.0, "zone": "green",
        })
        with mock.patch("routers.intraday_sentiment.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 8, 13, 14, 35)
            mock_dt.strftime = datetime.strftime
            result = asyncio.run(get_t1_projection())
        self.assertEqual(result["data"]["status"], "ready")
        self.assertEqual(len(result["data"]["scenarios"]), 2)
        self.assertEqual(result["data"]["scenarios"][0]["name"], "维持")
        self.assertEqual(result["data"]["scenarios"][1]["name"], "反弹")
        self.assertIn("投影", result["data"]["disclaimer"])

    def test_insufficient_data_when_no_score(self):
        from routers.intraday_sentiment import _sampler, get_t1_projection
        import asyncio
        _sampler.buffer.clear()
        _sampler.buffer.append({
            "date": "2026-08-13", "time": "14:35",
            "zt_count": None, "seal_rate": None, "break_rate": None,
            "ad_ratio": None, "score": None, "trend": None,
            "t1_baseline": None, "zone": "yellow",
        })
        with mock.patch("routers.intraday_sentiment.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 8, 13, 14, 35)
            mock_dt.strftime = datetime.strftime
            result = asyncio.run(get_t1_projection())
        self.assertEqual(result["data"]["status"], "insufficient_data")


if __name__ == "__main__":
    unittest.main()
