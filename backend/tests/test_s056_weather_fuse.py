# -*- coding: utf-8 -*-
"""S056：天气熔断三铁律补全测试。

R1 仓位熔断（暴风雨→triggered）+ R2 撤单熔断置桩（待S055）+ R3 次日强制离场信号。
软 gate：只提醒不锁死。
"""

import pytest
from fastapi.testclient import TestClient


class TestFuseEndpoint:
    """R1 仓位熔断 + fuse_state 汇总。"""

    def test_fuse_returns_three_rules(self, isolated_market_db):
        import app as appmod
        client = TestClient(appmod.app)
        r = client.get("/api/sentiment/weather/fuse")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        rule_ids = [rule["id"] for rule in data["rules"]]
        assert rule_ids == ["position_fuse", "cancel_fuse", "next_day_exit"]
        assert "fuse_state" in data
        assert "weather_state" in data

    def test_position_fuse_triggered_when_storm(self, isolated_market_db, monkeypatch):
        """暴风雨天气 → position_fuse.is_triggered=True, current_state=triggered。"""
        import app as appmod
        import routers.sentiment_weather as sw

        def _fake_latest():
            return {"data": {"weather_state": "暴风雨"}}
        monkeypatch.setattr(sw, "get_weather_latest", _fake_latest)

        client = TestClient(appmod.app)
        r = client.get("/api/sentiment/weather/fuse")
        assert r.status_code == 200
        data = r.json()["data"]
        pos = next(rule for rule in data["rules"] if rule["id"] == "position_fuse")
        assert pos["is_triggered"] is True
        assert pos["current_state"] == "triggered"
        assert data["fuse_state"] == "triggered"

    def test_position_fuse_normal_when_sunny(self, isolated_market_db, monkeypatch):
        import app as appmod
        import routers.sentiment_weather as sw

        def _fake_latest():
            return {"data": {"weather_state": "晴天"}}
        monkeypatch.setattr(sw, "get_weather_latest", _fake_latest)

        client = TestClient(appmod.app)
        r = client.get("/api/sentiment/weather/fuse")
        data = r.json()["data"]
        pos = next(rule for rule in data["rules"] if rule["id"] == "position_fuse")
        assert pos["is_triggered"] is False
        assert pos["current_state"] == "normal"
        assert data["fuse_state"] == "normal"

    def test_cancel_fuse_is_stub_pending_s055(self, isolated_market_db):
        """R2 撤单熔断置桩——data_status=待S055。"""
        import app as appmod
        client = TestClient(appmod.app)
        r = client.get("/api/sentiment/weather/fuse")
        data = r.json()["data"]
        cancel = next(rule for rule in data["rules"] if rule["id"] == "cancel_fuse")
        assert cancel["data_status"] == "待S055"
        assert cancel["is_triggered"] is False


class TestExitSignalsEndpoint:
    """R3 次日强制离场信号。"""

    def test_no_holdings_returns_empty(self, isolated_market_db, monkeypatch):
        import app as appmod
        import routers.sentiment_weather as sw

        # mock workflow_state_repo.list_states 返空
        class _FakeWsr:
            @staticmethod
            def list_states(date):
                return []
        monkeypatch.setattr(sw, "wsr", _FakeWsr, raising=False)
        # 注：sw 模块内 import workflow_state_repo as wsr 在函数内，需 patch 函数内 import
        # 用 sys.modules patch
        import sys
        original = sys.modules.get("workflow_state_repo")
        sys.modules["workflow_state_repo"] = _FakeWsr  # type: ignore
        try:
            client = TestClient(appmod.app)
            r = client.get(
                "/api/sentiment/weather/exit-signals",
                params={"date": "2026-08-11"},
            )
            assert r.status_code == 200, r.text
            data = r.json()["data"]
            assert data["signals"] == []
            assert data["summary"]["total"] == 0
        finally:
            if original:
                sys.modules["workflow_state_repo"] = original

    def test_missing_data_honest(self, isolated_market_db, monkeypatch):
        """行情数据不可得 → signal=None + data_status=missing，不臆造。"""
        import app as appmod
        import sys

        class _FakeWsr:
            @staticmethod
            def list_states(date):
                return [{"code": "000001", "name": "平安银行", "status": "holding"}]
        class _FakeAstock:
            @staticmethod
            def tencent_quote(codes):
                return {}
            @staticmethod
            def kline(code, *a, **k):
                return []
        original_wsr = sys.modules.get("workflow_state_repo")
        original_astock = sys.modules.get("astock")
        sys.modules["workflow_state_repo"] = _FakeWsr  # type: ignore
        sys.modules["astock"] = _FakeAstock  # type: ignore
        try:
            client = TestClient(appmod.app)
            r = client.get(
                "/api/sentiment/weather/exit-signals",
                params={"date": "2026-08-11"},
            )
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["summary"]["total"] == 1
            assert data["summary"]["missing"] == 1
            assert data["signals"][0]["signal"] is None
            assert data["signals"][0]["data_status"] == "missing"
        finally:
            if original_wsr:
                sys.modules["workflow_state_repo"] = original_wsr
            if original_astock:
                sys.modules["astock"] = original_astock

    def test_triggered_when_no_gap(self, isolated_market_db, monkeypatch):
        """竞价未高开（≤0%）→ 强制离场信号。"""
        import app as appmod
        import sys

        class _FakeWsr:
            @staticmethod
            def list_states(date):
                return [{"code": "000001", "name": "平安银行", "status": "holding"}]
        class _FakeAstock:
            @staticmethod
            def tencent_quote(codes):
                return {"000001": {"pct": -1.5, "open": 10.0, "price": 10.0}}
            @staticmethod
            def kline(code, *a, **k):
                # 5 日均价 11.0 → price 10 < 11 触发破均线
                return [{"close": 11.0}] * 6
        original_wsr = sys.modules.get("workflow_state_repo")
        original_astock = sys.modules.get("astock")
        sys.modules["workflow_state_repo"] = _FakeWsr  # type: ignore
        sys.modules["astock"] = _FakeAstock  # type: ignore
        try:
            client = TestClient(appmod.app)
            r = client.get(
                "/api/sentiment/weather/exit-signals",
                params={"date": "2026-08-11"},
            )
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["summary"]["triggered"] == 1
            sig = data["signals"][0]
            assert sig["signal"] == "强制离场"
            assert "竞价未高开" in sig["reason"]
        finally:
            if original_wsr:
                sys.modules["workflow_state_repo"] = original_wsr
            if original_astock:
                sys.modules["astock"] = original_astock
