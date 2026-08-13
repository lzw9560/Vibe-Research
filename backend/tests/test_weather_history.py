# -*- coding: utf-8 -*-
"""S065 weather_history 持久化测试。

迁移幂等 + save/get round-trip + UPSERT 幂等 + compute_weather_snapshot
（有行/无行）+ 端点 + 盘后写入。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from weather_history import save_weather_snapshot, get_weather_by_date, get_weather_history


class TestSaveGetRoundTrip(unittest.TestCase):
    def setUp(self):
        # 用临时 DB
        import tempfile
        self._orig_db = sys.modules["weather_history"]._DB_PATH
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        import weather_history as wh
        wh._DB_PATH = self.tmp.name
        # 建表
        import sqlite3
        conn = sqlite3.connect(self.tmp.name)
        sql = (
            "CREATE TABLE weather_history ("
            "date TEXT PRIMARY KEY, weather_state TEXT, composite_score REAL, "
            "sti_score REAL, risk_score REAL, sector_continuity REAL, "
            "capital_momentum REAL, public_sentiment REAL, phase TEXT, "
            "confidence TEXT, computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(sql)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_save_and_get(self):
        row = {
            "date": "2026-08-13", "weather_state": "晴天",
            "composite_score": 87.8, "sti_score": 72.57,
            "risk_score": 70.0, "sector_continuity": 80.0,
            "capital_momentum": 60.0, "public_sentiment": 65.0,
            "phase": "启动", "confidence": "高",
        }
        save_weather_snapshot(row)
        got = get_weather_by_date("2026-08-13")
        self.assertIsNotNone(got)
        self.assertEqual(got["weather_state"], "晴天")
        self.assertEqual(got["sti_score"], 72.57)

    def test_upsert_idempotent(self):
        row = {
            "date": "2026-08-13", "weather_state": "晴天",
            "composite_score": 87.8, "sti_score": 72.57,
            "risk_score": 70.0, "sector_continuity": 80.0,
            "capital_momentum": 60.0, "public_sentiment": 65.0,
            "phase": "启动", "confidence": "高",
        }
        save_weather_snapshot(row)
        # 改字段再写同 date → UPSERT 更新不重复
        row["weather_state"] = "阴天"
        row["composite_score"] = 69.9
        save_weather_snapshot(row)
        got = get_weather_by_date("2026-08-13")
        self.assertEqual(got["weather_state"], "阴天")
        self.assertEqual(got["composite_score"], 69.9)
        # 只有一行
        hist = get_weather_history(10)
        dates = [h["date"] for h in hist]
        self.assertEqual(dates.count("2026-08-13"), 1)

    def test_get_missing_date_returns_none(self):
        self.assertIsNone(get_weather_by_date("2099-01-01"))

    def test_get_history_ordered_desc(self):
        for d in ["2026-08-11", "2026-08-12", "2026-08-13"]:
            save_weather_snapshot({
                "date": d, "weather_state": "晴天", "composite_score": 50.0,
                "sti_score": 60.0, "risk_score": 50.0, "sector_continuity": 50.0,
                "capital_momentum": 50.0, "public_sentiment": 50.0,
                "phase": "启动", "confidence": "中",
            })
        hist = get_weather_history(10)
        self.assertEqual(len(hist), 3)
        self.assertEqual(hist[0]["date"], "2026-08-13")  # 降序


class TestComputeWeatherSnapshot(unittest.TestCase):
    def test_missing_when_sti_no_row(self):
        """sti_timeline 无该日行 → data_status=missing，不臆造。"""
        from routers.sentiment_weather import compute_weather_snapshot
        with mock.patch(
            "routers.sentiment_weather._get_latest_sti_for_date",
            return_value={"score": None, "phase": None, "date": "2099-01-01"},
        ):
            snap = compute_weather_snapshot("2099-01-01")
        self.assertEqual(snap["data_status"], "missing")
        self.assertEqual(snap["weather_state"], "未知")
        self.assertIsNone(snap["sti_score"])

    def test_full_snapshot_when_sti_has_row(self):
        from routers.sentiment_weather import compute_weather_snapshot
        with mock.patch(
            "routers.sentiment_weather._get_latest_sti_for_date",
            return_value={"score": 72.57, "phase": "启动", "date": "2026-08-13"},
        ), mock.patch(
            "routers.sentiment_weather._calculate_risk_score_for_date",
            return_value=70.0,
        ), mock.patch(
            "routers.sentiment_weather._calculate_sector_continuity_for_date",
            return_value=80.0,
        ), mock.patch(
            "routers.sentiment_weather._calculate_capital_momentum_for_date",
            return_value=60.0,
        ), mock.patch(
            "routers.sentiment_weather._calculate_public_sentiment_for_date",
            return_value=65.0,
        ):
            snap = compute_weather_snapshot("2026-08-13")
        self.assertEqual(snap["data_status"], "ok")
        self.assertIn(snap["weather_state"], ["晴天", "阴天", "极端反弹", "暴风雨"])
        self.assertEqual(snap["sti_score"], 72.57)
        self.assertEqual(snap["phase"], "启动")
        self.assertIsNotNone(snap["composite_score"])
        # 五因子齐全
        for f in ("risk_score", "sector_continuity", "capital_momentum", "public_sentiment"):
            self.assertIn(f, snap)


class TestHistoryEndpoint(unittest.TestCase):
    def test_endpoint_returns_history(self):
        """端点可调 + 返回结构正确。"""
        from fastapi.testclient import TestClient
        import app as appmod
        with mock.patch(
            "weather_history.get_weather_history",
            return_value=[{"date": "2026-08-13", "weather_state": "晴天"}],
        ):
            client = TestClient(appmod.app)
            r = client.get("/api/sentiment/weather/history", params={"days": 30})
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["history"][0]["weather_state"], "晴天")


class TestStiPostMarketWriteback(unittest.TestCase):
    def test_sti_post_market_writes_snapshot_on_ok(self):
        """STI 计算成功 → weather_history 落行（验证调用链）。"""
        import scheduled_tasks as st
        executor = st.TaskExecutor()
        # mock STI 计算路径
        from limitup_sti.models import STIResult, STIPhase
        fake_result = STIResult(
            date="2026-08-13", score=72.57, phase=STIPhase.START,
            dimensions=None, source_ok=True, confidence="high",
            change_from_yesterday=None, data_updated="2026-08-13",
        )
        with mock.patch("market._emotion", return_value={"date": "2026-08-13", "zt_count": 50}), \
             mock.patch("market._sentiment", return_value={"up": 100, "down": 50, "active": "强"}), \
             mock.patch("limitup_sti.service.get_sti_engine") as mock_engine, \
             mock.patch("vr_paths.last_trading_date_str", return_value="2026-08-13"), \
             mock.patch("routers.sentiment_weather.compute_weather_snapshot") as mock_compute, \
             mock.patch("weather_history.save_weather_snapshot") as mock_save:
            mock_engine.return_value.compute.return_value = fake_result
            mock_compute.return_value = {"date": "2026-08-13", "weather_state": "晴天", "data_status": "ok"}
            result = executor._execute_sti_post_market({})
        self.assertEqual(result["status"], "ok")
        mock_compute.assert_called_once_with("2026-08-13")
        mock_save.assert_called_once()

    def test_sti_post_market_writeback_failure_does_not_block(self):
        """weather_history 落库失败不阻断 STI 主流程。"""
        import scheduled_tasks as st
        executor = st.TaskExecutor()
        from limitup_sti.models import STIResult, STIPhase
        fake_result = STIResult(
            date="2026-08-13", score=72.57, phase=STIPhase.START,
            dimensions=None, source_ok=True, confidence="high",
            change_from_yesterday=None, data_updated="2026-08-13",
        )
        with mock.patch("market._emotion", return_value={"date": "2026-08-13", "zt_count": 50}), \
             mock.patch("market._sentiment", return_value={"up": 100, "down": 50, "active": "强"}), \
             mock.patch("limitup_sti.service.get_sti_engine") as mock_engine, \
             mock.patch("vr_paths.last_trading_date_str", return_value="2026-08-13"), \
             mock.patch("routers.sentiment_weather.compute_weather_snapshot") as mock_compute, \
             mock.patch("weather_history.save_weather_snapshot", side_effect=RuntimeError("boom")):
            mock_engine.return_value.compute.return_value = fake_result
            mock_compute.return_value = {"date": "2026-08-13", "weather_state": "晴天", "data_status": "ok"}
            result = executor._execute_sti_post_market({})
        # STI 仍成功，weather 失败不阻断
        self.assertEqual(result["status"], "ok")


if __name__ == "__main__":
    unittest.main()
