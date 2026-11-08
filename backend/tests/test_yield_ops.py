# -*- coding: utf-8 -*-
"""S243 运维 yield 测试——router + executor remind 逻辑。"""
from __future__ import annotations
from unittest.mock import patch
from fastapi.testclient import TestClient

import app  # noqa: E402

client = TestClient(app.app)


def test_repo_endpoint():
    """AC1: /api/yield/repo 返回 GC001 + 季末/月末标记。"""
    with patch("routers.yield_ops.get_gc001_rate") as mock:
        mock.return_value = {"symbol": "sh204001", "rate": 2.5, "quarter_end": False, "month_end": False, "threshold": 3.0}
        r = client.get("/api/yield/repo")
    assert r.status_code == 200
    body = r.json()
    assert "rate" in body
    assert "quarter_end" in body


def test_yield_snapshot():
    """AC5: /api/yield/snapshot 返回 repo + cb_today + ipo_today。"""
    with patch("routers.yield_ops.get_gc001_rate") as m1, \
         patch("routers.yield_ops.get_today_cb_subscriptions") as m2:
        m1.return_value = {"rate": 3.5, "quarter_end": True}
        m2.return_value = [{"code": "123456", "name": "测试CB"}]
        r = client.get("/api/yield/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert "repo" in body and "cb_today" in body and "ipo_today" in body
    assert body["cb_today"]["count"] == 1


def test_repo_remind_skip_below_threshold():
    """AC2/AC8: GC001<3% 非季末/月末 → skip 不打扰。"""
    with patch("scheduler.executors.yield_ops.get_gc001_rate") as mock:
        mock.return_value = {"rate": 1.2, "quarter_end": False, "month_end": False, "threshold": 3.0}
        from scheduler.executors.yield_ops import yield_repo_remind
        result = yield_repo_remind({"notify": True})
    assert result["status"] == "skip"
    assert "3.0" in result["reason"]


def test_repo_remind_trigger_quarter_end():
    """AC2: 季末 GC001 即使<3% 也触发（季末高息日）。"""
    with patch("scheduler.executors.yield_ops.get_gc001_rate") as mock_rate, \
         patch("scheduler.executors.yield_ops._send_text_notification") as mock_notify:
        mock_rate.return_value = {"rate": 2.0, "quarter_end": True, "month_end": False, "threshold": 3.0}
        from scheduler.executors.yield_ops import yield_repo_remind
        result = yield_repo_remind({"notify": True})
    assert result["status"] == "sent"
    assert result["quarter_end"] is True
    mock_notify.assert_called_once()


def test_repo_remind_trigger_high_rate():
    """AC2: GC001>3% 平日也触发。"""
    with patch("scheduler.executors.yield_ops.get_gc001_rate") as mock_rate, \
         patch("scheduler.executors.yield_ops._send_text_notification") as mock_notify:
        mock_rate.return_value = {"rate": 5.5, "quarter_end": False, "month_end": False, "threshold": 3.0}
        from scheduler.executors.yield_ops import yield_repo_remind
        result = yield_repo_remind({"notify": True})
    assert result["status"] == "sent"
    assert result["rate"] == 5.5


def test_cb_remind_skip_no_cb():
    """AC4/AC8: 今日无 CB 申购 → skip。"""
    with patch("scheduler.executors.yield_ops.get_today_cb_subscriptions") as mock:
        mock.return_value = []
        from scheduler.executors.yield_ops import yield_cb_remind
        result = yield_cb_remind({"notify": True})
    assert result["status"] == "skip"


def test_cb_remind_trigger():
    """AC4: 当日有 CB 申购 → 发飞书。"""
    with patch("scheduler.executors.yield_ops.get_today_cb_subscriptions") as mock_cbs, \
         patch("scheduler.executors.yield_ops._send_text_notification") as mock_notify:
        mock_cbs.return_value = [{"code": "123456", "name": "测试CB"}]
        from scheduler.executors.yield_ops import yield_cb_remind
        result = yield_cb_remind({"notify": True})
    assert result["status"] == "sent"
    assert result["n_cbs"] == 1
    mock_notify.assert_called_once()
