# -*- coding: utf-8 -*-
"""S055 T1：盘中封单时序采集层单测。

覆盖：
- 表 + 迁移（迁移幂等）
- 交易时段门控（非交易时段不落库、不请求东财）
- 采集写库（mock em_zt_topic_pool）
- prune 删除旧数据
- 查询接口（get_snapshots_by_code / get_latest_snapshots / get_recent_window）
"""

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_seal_db(tmp_path, monkeypatch):
    """临时 SEAL_INTRADAY_DB_PATH + 触发迁移。"""
    db_path = tmp_path / "seal_intraday.db"
    monkeypatch.setattr("risk.seal_intraday_collector._DB_PATH", str(db_path))
    monkeypatch.setattr("risk.seal_intraday_collector.SEAL_INTRADAY_DB_PATH", str(db_path))
    # 重新导入以触发迁移（_DB_PATH 已 patch）
    from risk.seal_intraday_collector import run_migrations
    run_migrations()
    return str(db_path)


class TestMigrations:
    def test_table_created(self, isolated_seal_db):
        conn = sqlite3.connect(isolated_seal_db)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            assert "seal_intraday_snapshots" in tables
            assert "bomb_alert_history" in tables
        finally:
            conn.close()

    def test_migration_idempotent(self, isolated_seal_db):
        from risk.seal_intraday_collector import run_migrations
        run_migrations()  # 二次调用不报错
        conn = sqlite3.connect(isolated_seal_db)
        try:
            cnt = conn.execute("SELECT COUNT(*) FROM seal_intraday_snapshots").fetchone()[0]
            assert cnt == 0
        finally:
            conn.close()


class TestTradingTimeGate:
    def test_non_trading_day_skipped(self, monkeypatch):
        from risk.seal_intraday_collector import is_intraday_trading_time
        # 周六
        saturday = datetime(2026, 8, 8, 10, 30)  # 2026-08-08 周六
        assert is_intraday_trading_time(saturday) is False

    def test_before_open_skipped(self, monkeypatch):
        from risk.seal_intraday_collector import is_intraday_trading_time
        weekday_morning = datetime(2026, 8, 11, 9, 0)  # 周二 09:00（盘前）
        assert is_intraday_trading_time(weekday_morning) is False

    def test_midday_closed(self, monkeypatch):
        from risk.seal_intraday_collector import is_intraday_trading_time
        midday = datetime(2026, 8, 11, 12, 30)  # 周二 12:30（午间休市）
        assert is_intraday_trading_time(midday) is False

    def test_after_close_skipped(self, monkeypatch):
        from risk.seal_intraday_collector import is_intraday_trading_time
        after = datetime(2026, 8, 11, 16, 0)  # 周二 16:00
        assert is_intraday_trading_time(after) is False

    def test_morning_session_ok(self, monkeypatch):
        from risk.seal_intraday_collector import is_intraday_trading_time
        morning = datetime(2026, 8, 11, 10, 0)  # 周二 10:00
        assert is_intraday_trading_time(morning) is True

    def test_afternoon_session_ok(self, monkeypatch):
        from risk.seal_intraday_collector import is_intraday_trading_time
        afternoon = datetime(2026, 8, 11, 14, 30)  # 周二 14:30
        assert is_intraday_trading_time(afternoon) is True


class TestCollectOnce:
    def test_non_trading_time_skips_em_get(self, isolated_seal_db, monkeypatch):
        """非交易时段不请求东财。"""
        from risk.seal_intraday_collector import collect_once
        import risk.seal_intraday_collector as sic

        # 强制非交易时段
        monkeypatch.setattr(sic, "is_intraday_trading_time", lambda now=None: False)

        call_count = [0]
        def _fake_em(*a, **k):
            call_count[0] += 1
            return []
        monkeypatch.setattr("astock.em_zt_topic_pool", _fake_em)

        result = collect_once()
        assert result["written"] == 0
        assert result["skipped"] == 1
        assert call_count[0] == 0  # 没调东财

    def test_trading_time_writes_snapshots(self, isolated_seal_db, monkeypatch):
        """交易时段写快照。"""
        from risk.seal_intraday_collector import collect_once
        import risk.seal_intraday_collector as sic

        monkeypatch.setattr(sic, "is_intraday_trading_time", lambda now=None: True)

        fake_pool = [
            {"c": "000001", "n": "平安银行", "fbt": 93500, "zbc": 0, "zje": 12.5,
             "open": 12.0, "seal_amount": 1e8, "float_shares": 1e9, "lbc": 1, "hybk": "银行"},
            {"c": "600519", "n": "贵州茅台", "fbt": 100000, "zbc": 1, "zje": 1800,
             "open": 1790, "seal_amount": 5e8, "float_shares": 1e9, "lbc": 2, "hybk": "白酒"},
        ]
        monkeypatch.setattr("astock.em_zt_topic_pool", lambda *a, **k: fake_pool)
        monkeypatch.setattr("astock.tencent_quote", lambda codes: {"sh000001": {"pct": 0.5}})

        result = collect_once()
        assert result["written"] == 2
        assert result["data_status"] == "ok"

        # 验证落库
        from risk.seal_intraday_collector import get_snapshots_by_code
        rows = get_snapshots_by_code("000001")
        assert len(rows) == 1
        assert rows[0]["name"] == "平安银行"
        assert rows[0]["sector"] == "银行"

    def test_em_failure_degraded(self, isolated_seal_db, monkeypatch):
        """东财请求失败 → data_status=degraded，不臆造。"""
        from risk.seal_intraday_collector import collect_once
        import risk.seal_intraday_collector as sic

        monkeypatch.setattr(sic, "is_intraday_trading_time", lambda now=None: True)

        def _fail(*a, **k):
            raise RuntimeError("circuit breaker open")
        monkeypatch.setattr("astock.em_zt_topic_pool", _fail)

        result = collect_once()
        assert result["written"] == 0
        assert result["data_status"] == "degraded"


class TestPrune:
    def test_prune_deletes_old(self, isolated_seal_db):
        from risk.seal_intraday_collector import save_snapshots, prune_old_snapshots
        old_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        rows = [{"ts": "old", "date": old_date, "code": "000001"}]
        save_snapshots(rows)
        deleted = prune_old_snapshots(30)
        assert deleted >= 1


class TestQueries:
    def test_get_latest_snapshots(self, isolated_seal_db, monkeypatch):
        from risk.seal_intraday_collector import collect_once, get_latest_snapshots
        import risk.seal_intraday_collector as sic

        monkeypatch.setattr(sic, "is_intraday_trading_time", lambda now=None: True)
        monkeypatch.setattr("astock.em_zt_topic_pool", lambda *a, **k: [
            {"c": "000001", "n": "平安银行", "zje": 12.5, "seal_amount": 1e8, "float_shares": 1e9, "lbc": 1, "hybk": "银行"},
        ])
        monkeypatch.setattr("astock.tencent_quote", lambda codes: {})

        collect_once()
        latest = get_latest_snapshots()
        assert len(latest) == 1
        assert latest[0]["code"] == "000001"
