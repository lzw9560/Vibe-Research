# -*- coding: utf-8 -*-
"""S193 R4 gap_scan executor 测试。

mock NotificationService + KlineCacheBarsProvider + watchlist + _classify_gap_from_bars，
测 scan_watchlist_gaps 逻辑：空 watchlist / 无变盘 / 有变盘推送 / 推送失败不阻断。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_bars(dates: list[str], lows: list[float], highs: list[float]) -> list[dict]:
    """造 bars（date/low/high/close/volume）。"""
    return [
        {"date": d, "open": lows[i], "high": highs[i], "low": lows[i],
         "close": highs[i], "volume": 1000}
        for i, d in enumerate(dates)
    ]


def test_empty_watchlist_skips():
    """watchlist 空 → 跳过，返 alerts=0。"""
    with patch("candidate_funnel.sources.watchlist_in.get_watchlist_codes", return_value=[]):
        from scheduler.executors.gap_scan import scan_watchlist_gaps
        r = scan_watchlist_gaps({})
    assert r["status"] == "ok"
    assert r["alerts"] == 0
    assert r["scanned"] == 0


def test_no_alerts_when_all_normal_gaps():
    """所有缺口都是普通 → 无 alert（普通不推）。"""
    bars = _make_bars(["2026-09-10", "2026-09-11"], [10, 10.5], [10.5, 11])  # 无缺口（overlap）
    with patch("candidate_funnel.sources.watchlist_in.get_watchlist_codes", return_value=["000001"]), \
         patch("engine.bars_provider.KlineCacheBarsProvider") as MockBP, \
         patch("engine.gap_classifier._classify_gap_from_bars") as MockClassify, \
         patch("notification.notification_service.NotificationService") as MockNS:
        MockBP.return_value.return_value = bars
        MockClassify.return_value = {"type": "普通", "direction": "向上", "regime": "噪声", "confidence": 0.4}
        MockNS.return_value.is_available.return_value = False
        from scheduler.executors.gap_scan import scan_watchlist_gaps
        r = scan_watchlist_gaps({})
    assert r["alerts"] == 0
    assert r["scanned"] == 1
    MockNS.return_value.send.assert_not_called()


def test_breakout_alert_pushed():
    """突破缺口 → 推送（route_type=alert, dedup_key=gap_scan_date）。"""
    bars = _make_bars(["2026-09-10", "2026-09-11"], [10, 11.5], [10.5, 12])
    with patch("candidate_funnel.sources.watchlist_in.get_watchlist_codes", return_value=["000001"]), \
         patch("engine.bars_provider.KlineCacheBarsProvider") as MockBP, \
         patch("engine.gap_classifier._classify_gap_from_bars") as MockClassify, \
         patch("notification.notification_service.NotificationService") as MockNS:
        MockBP.return_value.return_value = bars
        MockClassify.return_value = {"type": "突破", "direction": "向上", "regime": "趋势启动", "confidence": 0.7}
        ns_instance = MockNS.return_value
        ns_instance.is_available.return_value = True
        from scheduler.executors.gap_scan import scan_watchlist_gaps
        r = scan_watchlist_gaps({})
    assert r["alerts"] == 1
    assert r["alert_codes"] == ["000001"]
    ns_instance.send.assert_called_once()
    _, kwargs = ns_instance.send.call_args
    assert kwargs["route_type"] == "alert"
    assert kwargs["dedup_key"].startswith("gap_scan_")


def test_exhaustion_alert_pushed():
    """衰竭缺口 → 推送（continuation 正信号，非剔除）。"""
    bars = _make_bars(["2026-09-10", "2026-09-11"], [10, 11.5], [10.5, 12])
    with patch("candidate_funnel.sources.watchlist_in.get_watchlist_codes", return_value=["000002"]), \
         patch("engine.bars_provider.KlineCacheBarsProvider") as MockBP, \
         patch("engine.gap_classifier._classify_gap_from_bars") as MockClassify, \
         patch("notification.notification_service.NotificationService") as MockNS:
        MockBP.return_value.return_value = bars
        MockClassify.return_value = {"type": "衰竭", "direction": "向下", "regime": "反转", "confidence": 0.65}
        ns_instance = MockNS.return_value
        ns_instance.is_available.return_value = True
        from scheduler.executors.gap_scan import scan_watchlist_gaps
        r = scan_watchlist_gaps({})
    assert r["alerts"] == 1
    assert "continuation" in _content_of(ns_instance.send)


def _content_of(mock_send):
    """提取 send 调用的 content（第一个位置参数）。"""
    args, _ = mock_send.call_args
    return args[0] if args else ""


def test_continuation_not_pushed():
    """持续缺口 → 不推送（中继避免噪声）。"""
    bars = _make_bars(["2026-09-10", "2026-09-11"], [10, 11.5], [10.5, 12])
    with patch("candidate_funnel.sources.watchlist_in.get_watchlist_codes", return_value=["000003"]), \
         patch("engine.bars_provider.KlineCacheBarsProvider") as MockBP, \
         patch("engine.gap_classifier._classify_gap_from_bars") as MockClassify, \
         patch("notification.notification_service.NotificationService") as MockNS:
        MockBP.return_value.return_value = bars
        MockClassify.return_value = {"type": "持续", "direction": "向上", "regime": "趋势中继", "confidence": 0.6}
        MockNS.return_value.is_available.return_value = False
        from scheduler.executors.gap_scan import scan_watchlist_gaps
        r = scan_watchlist_gaps({})
    assert r["alerts"] == 0


def test_push_failure_does_not_crash():
    """NotificationService.send 抛异常 → 不阻断，log warning，返 alerts 仍有。"""
    bars = _make_bars(["2026-09-10", "2026-09-11"], [10, 11.5], [10.5, 12])
    with patch("candidate_funnel.sources.watchlist_in.get_watchlist_codes", return_value=["000001"]), \
         patch("engine.bars_provider.KlineCacheBarsProvider") as MockBP, \
         patch("engine.gap_classifier._classify_gap_from_bars") as MockClassify, \
         patch("notification.notification_service.NotificationService") as MockNS:
        MockBP.return_value.return_value = bars
        MockClassify.return_value = {"type": "突破", "direction": "向上", "regime": "趋势启动", "confidence": 0.7}
        ns_instance = MockNS.return_value
        ns_instance.is_available.return_value = True
        ns_instance.send.side_effect = RuntimeError("飞书挂了")
        from scheduler.executors.gap_scan import scan_watchlist_gaps
        r = scan_watchlist_gaps({})  # 不抛
    assert r["status"] == "ok"
    assert r["alerts"] == 1  # alert 仍记录（推送失败不丢 alert）
