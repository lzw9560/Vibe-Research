# -*- coding: utf-8 -*-
"""S055 T2/T4：bomb-alerts / seal-snapshots 端点 + 去重冷却测试。"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_seal_db(tmp_path, monkeypatch):
    db_path = tmp_path / "seal_intraday.db"
    monkeypatch.setattr("risk.seal_intraday_collector._DB_PATH", str(db_path))
    monkeypatch.setattr("risk.seal_intraday_collector.SEAL_INTRADAY_DB_PATH", str(db_path))
    monkeypatch.setattr("risk.bomb_alert_dispatcher._DB_PATH", str(db_path))
    monkeypatch.setattr("risk.bomb_alert_dispatcher.SEAL_INTRADAY_DB_PATH", str(db_path))
    # 清空冷却 cache（跨测试隔离）
    import risk.bomb_alert_dispatcher as bad
    bad._cooldown_cache.clear()
    from risk.seal_intraday_collector import run_migrations
    run_migrations()
    yield str(db_path)
    bad._cooldown_cache.clear()


class TestBombAlertsEndpoint:
    def test_returns_empty_when_no_alerts(self, isolated_seal_db, monkeypatch):
        import app as appmod
        from vr_paths import last_trading_date_str
        target = last_trading_date_str()
        client = TestClient(appmod.app)
        r = client.get("/api/risk/bomb-alerts")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["alerts"] == []
        assert data["count"] == 0

    def test_returns_alerts_after_save(self, isolated_seal_db, monkeypatch):
        from risk.bomb_alert_dispatcher import save_alert
        from risk.bomb_alert_rules import RuleCheckResult
        from realtime_workflow import BombAlert
        from vr_paths import last_trading_date_str

        # save_alert 用 now.strftime 落 date 列，端点用 last_trading_date_str() 查——
        # 非交易日（周末/节假日）跑时 now(今日) != last_trading_date_str() 致存写/查询日期错位。
        # 对齐：now 取最近交易日，使 save 的 date == 端点查询 date（模拟交易日存写）。
        target = last_trading_date_str()
        now = datetime.fromisoformat(target)
        result = RuleCheckResult(
            rule_id="C1", triggered=True,
            alert=BombAlert(
                timestamp=now.isoformat(), code="000001", name="测试",
                alert_level="yellow", condition="封单减 40%",
                current_seal_amount=0.6e8, seal_amount_change_5min=0.4e8,
                recommendation="减仓或止盈",
            ),
            data_status="ok", reason="5 分钟降幅 40%",
        )
        save_alert("000001", "测试", result, now)

        import app as appmod
        client = TestClient(appmod.app)
        r = client.get("/api/risk/bomb-alerts")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 1
        assert data["alerts"][0]["code"] == "000001"
        assert data["alerts"][0]["rule_id"] == "C1"
        assert data["alerts"][0]["alert_level"] == "yellow"

    def test_save_on_non_trading_day_aligns_to_trading_date(self, isolated_seal_db, monkeypatch):
        """task 120：非交易日 save_alert → date 列按交易日历落（last_trading_date_str(now.date)），
        非 now.strftime 日历今日。原实现非交易日存周六、端点查 last_trading_date=周五 → 错位 count=0。"""
        from datetime import date
        from risk.bomb_alert_dispatcher import save_alert
        from risk.bomb_alert_rules import RuleCheckResult
        from realtime_workflow import BombAlert
        from vr_paths import last_trading_date_str

        sat = datetime(2026, 8, 15, 10, 0)  # 周六（非交易日，见 test_workflow_stage_tz）
        target = last_trading_date_str(sat.date())  # 周六 → 最近交易日
        assert target != sat.strftime("%Y-%m-%d")  # 确认周六非交易日（否则测试无意义）
        result = RuleCheckResult(
            rule_id="C1", triggered=True,
            alert=BombAlert(
                timestamp=sat.isoformat(), code="000001", name="测试",
                alert_level="yellow", condition="封单减 40%",
                current_seal_amount=0.6e8, seal_amount_change_5min=0.4e8,
                recommendation="减仓或止盈",
            ),
            data_status="ok", reason="5 分钟降幅 40%",
        )
        save_alert("000001", "测试", result, sat)

        import app as appmod
        client = TestClient(appmod.app)
        r = client.get("/api/risk/bomb-alerts", params={"date": target})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 1  # 非交易日存的 alert 按交易日历落 → 端点能查到
        assert data["alerts"][0]["code"] == "000001"


class TestSealSnapshotsEndpoint:
    def test_returns_snapshots_when_exists(self, isolated_seal_db, monkeypatch):
        from risk.seal_intraday_collector import save_snapshots
        from vr_paths import last_trading_date_str
        target = last_trading_date_str()
        rows = [{
            "ts": datetime.now().isoformat(), "date": target,
            "code": "000001", "name": "平安银行", "seal_amount": 1e8,
        }]
        save_snapshots(rows)

        import app as appmod
        client = TestClient(appmod.app)
        r = client.get("/api/risk/seal-snapshots", params={"code": "000001"})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["count"] == 1
        assert data["data_status"] == "ok"

    def test_returns_missing_when_empty(self, isolated_seal_db):
        import app as appmod
        client = TestClient(appmod.app)
        r = client.get("/api/risk/seal-snapshots", params={"code": "999999"})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 0
        assert data["data_status"] == "missing"


class TestCooldownDedup:
    def test_same_rule_not_retriggered_within_cooldown(self, isolated_seal_db, monkeypatch):
        """同股同规则 10 分钟内不重复触发。"""
        from risk.bomb_alert_dispatcher import is_in_cooldown, _mark_triggered
        now = datetime(2026, 8, 11, 10, 0)
        assert is_in_cooldown("000001", "C1", now) is False
        _mark_triggered("000001", "C1", now)
        # 5 分钟后仍在冷却期
        later = now + timedelta(minutes=5)
        assert is_in_cooldown("000001", "C1", later) is True
        # 11 分钟后冷却过期
        after = now + timedelta(minutes=11)
        assert is_in_cooldown("000001", "C1", after) is False

    def test_different_rule_independent(self, isolated_seal_db, monkeypatch):
        from risk.bomb_alert_dispatcher import is_in_cooldown, _mark_triggered
        now = datetime(2026, 8, 11, 10, 0)
        _mark_triggered("000001", "C1", now)
        # C2 不受 C1 冷却影响
        assert is_in_cooldown("000001", "C2", now) is False

    def test_different_code_independent(self, isolated_seal_db, monkeypatch):
        from risk.bomb_alert_dispatcher import is_in_cooldown, _mark_triggered
        now = datetime(2026, 8, 11, 10, 0)
        _mark_triggered("000001", "C1", now)
        # 600519 不受 000001 冷却影响
        assert is_in_cooldown("600519", "C1", now) is False
