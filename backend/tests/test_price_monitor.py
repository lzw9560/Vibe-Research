# -*- coding: utf-8 -*-
"""S206 price_monitor executor 测试。

mock tencent_quote + NotificationService，测 scan_price_alerts：
表建+seed 5 标的 / 无触及 / 触及压力1/突破压力2/跌破支撑2 / 推送失败不阻断。
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock


def test_ensure_table_seeds_5_default_alerts(tmp_path):
    """建表 + seed 5 默认标的。"""
    with patch("scheduler.executors.price_monitor._get_alerts_db", return_value=str(tmp_path / "vr.db")):
        from scheduler.executors.price_monitor import _get_alerts
        alerts = _get_alerts()
    codes = [a["code"] for a in alerts]
    assert "002156" in codes and "600584" in codes
    assert len(alerts) >= 5


def test_check_alerts_resistance1_triggered():
    """触及压力1（price >= resistance1 但 < resistance2）。"""
    from scheduler.executors.price_monitor import _check_alerts
    alerts = [{"code": "002156", "name": "通富微电", "support1": 58.5, "support2": 57.97,
               "resistance1": 60.0, "resistance2": 61.5}]
    prices = {"002156": {"price": 60.1}}
    triggered = _check_alerts(prices, alerts)
    assert len(triggered) == 1
    assert "触及压力1" in triggered[0]["direction"]


def test_check_alerts_resistance2_breakout():
    """突破压力2（price >= resistance2）。"""
    from scheduler.executors.price_monitor import _check_alerts
    alerts = [{"code": "600584", "name": "长电科技", "support1": 68.0, "support2": 67.5,
               "resistance1": 70.0, "resistance2": 71.5}]
    prices = {"600584": {"price": 72.0}}
    triggered = _check_alerts(prices, alerts)
    assert len(triggered) == 1
    assert "突破压力2" in triggered[0]["direction"]


def test_check_alerts_support2_broken():
    """跌破支撑2（price <= support2）。"""
    from scheduler.executors.price_monitor import _check_alerts
    alerts = [{"code": "002185", "name": "华天科技", "support1": 15.8, "support2": 15.5,
               "resistance1": 16.5, "resistance2": 17.0}]
    prices = {"002185": {"price": 15.3}}
    triggered = _check_alerts(prices, alerts)
    assert len(triggered) == 1
    assert "跌破支撑2" in triggered[0]["direction"]


def test_check_alerts_no_trigger_in_range():
    """价格在支撑1~压力1 之间无触及。"""
    from scheduler.executors.price_monitor import _check_alerts
    alerts = [{"code": "002281", "name": "光迅科技", "support1": 180.0, "support2": 178.0,
               "resistance1": 185.0, "resistance2": 190.0}]
    prices = {"002281": {"price": 182.0}}
    triggered = _check_alerts(prices, alerts)
    assert len(triggered) == 0


def test_scan_no_push_when_no_trigger(tmp_path):
    """无触及 → 不推送。"""
    with patch("scheduler.executors.price_monitor._get_alerts_db", return_value=str(tmp_path / "vr.db")), \
         patch("astock.tencent_quote", return_value={}), \
         patch("notification.notification_service.NotificationService") as MockNS:
        MockNS.return_value.is_available.return_value = False
        from scheduler.executors.price_monitor import scan_price_alerts
        r = scan_price_alerts({})
    # tencent_quote 返空 → prices 空 → 无触及
    assert r["status"] == "ok"
    MockNS.return_value.send.assert_not_called()


def test_scan_push_failure_does_not_crash(tmp_path):
    """推送抛异常 → 不阻断，返 alerts 仍有。"""
    fake_prices = {"002156": {"price": 61.0}}  # 触及压力1
    with patch("scheduler.executors.price_monitor._get_alerts_db", return_value=str(tmp_path / "vr.db")), \
         patch("astock.tencent_quote", return_value={"002156": {"raw": 1}}), \
         patch("data.mappers.quote_from_tencent") as MockMap, \
         patch("notification.notification_service.NotificationService") as MockNS:
        MockMap.return_value.model_dump.return_value = {"price": 61.0}
        ns = MockNS.return_value
        ns.is_available.return_value = True
        ns.send.side_effect = RuntimeError("飞书挂了")
        from scheduler.executors.price_monitor import scan_price_alerts
        r = scan_price_alerts({})
    assert r["status"] == "ok"
    assert r["alerts"] >= 1  # triggered 仍记录
