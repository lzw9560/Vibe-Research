# -*- coding: utf-8 -*-
"""cap=0 guard 测试——3 cron 推送 cap=0 时 skip 飞书（v6.5 P1 #7）。

v6/v6.5 加 cap=0 guard（daily_report bc265d2 + keypoint_notify 96e750c + weekly_review 9f939b6 +
regime_flip_notify cb9abab）但 0 测试覆盖。本 test monkeypatch get_consecutive_relay_signals 返
cap=0 signals + mock _send_text_notification，断言 3 cron cap=0 时 _send_text_notification 未调用。

catch 未来 guard 被 refactor 破坏（fixture 全用 0.75 无 cap=0 断言——v6.5 戳破）。
"""
import pytest
from unittest.mock import patch

# fake cap=0 signals（consecutive_relay falsified 后 evaluation.py cap=0.0）
_FAKE_CAP0_SIGNALS = {
    "cap": {"effective": 0.0, "base": 0.0, "decay": 0.0, "regime_factor": 0.0, "zuoT_factor": 1.0, "note": "archive"},
    "filters": {"total_scanned": 0, "tradable": 0, "exploratory": 0, "avoid": 0},
    "signals": [],
    "regime": {"current": "bull", "edge_status": "ARCHIVED", "freshness": {}},
    "hardstop": {"active": True, "reason": "archive"},
    "date": "2026-09-27",
    "verified_numbers": {},
}


@pytest.fixture
def mock_cap0(monkeypatch):
    """monkeypatch get_consecutive_relay_signals 返 cap=0 signals。"""
    monkeypatch.setattr(
        "tools.signal_report.get_consecutive_relay_signals",
        lambda date: _FAKE_CAP0_SIGNALS,
    )
    # weekly_review 调 TradeJournal + _actual_pnl——mock 避免 DB 依赖
    monkeypatch.setattr(
        "scheduler.executors.signals._actual_pnl_for_weekly_review",
        lambda: {},
    )
    monkeypatch.setattr(
        "tools.signal_report._compute_consecutive_relay_decay",
        lambda: {"bear_days": 0, "decay_stable": False, "lbc3_days": 0, "decay_pct": 0.0},
    )
    return _FAKE_CAP0_SIGNALS


def test_daily_report_cap0_skip_notify(mock_cap0):
    """daily_report cap=0 → skip 飞书（v6 H1 guard bc265d2）。"""
    from scheduler.executors.signals import daily_report
    with patch("scheduler.executors.signals._send_text_notification") as mock_send:
        result = daily_report({"notify": True})
        assert result["status"] == "ok"
        mock_send.assert_not_called()  # cap=0 archive → skip 飞书


def test_keypoint_notify_cap0_skip_notify(mock_cap0):
    """keypoint_notify cap=0 → skip 飞书（v6 H1 guard 96e750c）。"""
    from scheduler.executors.signals import keypoint_notify
    with patch("scheduler.executors.signals._send_text_notification") as mock_send:
        result = keypoint_notify({"notify": True})
        assert result["status"] == "ok"
        mock_send.assert_not_called()


def test_weekly_review_cap0_skip_notify(mock_cap0):
    """weekly_review cap=0 → skip 飞书（v6 M1 guard 9f939b6）。"""
    from scheduler.executors.signals import weekly_review
    with patch("scheduler.executors.signals._send_text_notification") as mock_send:
        result = weekly_review({"notify": True})
        assert result["status"] == "ok"
        mock_send.assert_not_called()
