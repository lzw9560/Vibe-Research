# -*- coding: utf-8 -*-
"""S245 打新 regime 监控测试——转弱/正常/边界触发逻辑。

TDD:先写测试验证 regime health 计算 + 2/3 触发逻辑。
"""
from __future__ import annotations

from unittest.mock import patch


def _mock_health(break_rate: float, median: float, ipo_pw: float) -> dict:
    """构造 regime health(绕过 akshare 拉数据)。"""
    from scheduler.executors import ipo_regime as mod
    t_break = break_rate > mod.BREAK_RATE_CUT
    t_median = median < mod.FIRST_DAY_MEDIAN_CUT
    t_ipo = ipo_pw > mod.IPO_PER_WEEK_CUT
    triggers = sum([t_break, t_median, t_ipo])
    return {
        "n_recent": 50,
        "break_rate": break_rate,
        "first_day_median_pct": median,
        "ipo_per_week": ipo_pw,
        "triggers": triggers,
        "trigger_flags": {"break": t_break, "median": t_median, "ipo": t_ipo},
        "regime": "weak" if triggers >= mod.TRIGGER_THRESHOLD else "normal",
    }


def test_ipo_regime_weak_2of3_break_median():
    """AC2: 破发>10% + median<50% (2/3 触发) → sent alert。"""
    with patch("scheduler.executors.ipo_regime.get_ipo_regime_health") as mock_h, \
         patch("scheduler.executors.ipo_regime._send_text_notification") as mock_notify:
        mock_h.return_value = _mock_health(break_rate=0.15, median=30.0, ipo_pw=3.0)
        from scheduler.executors.ipo_regime import ipo_regime_monitor
        result = ipo_regime_monitor({"notify": True})
    assert result["status"] == "sent"
    assert result["regime"] == "weak"
    assert result["triggers"] == 2
    mock_notify.assert_called_once()


def test_ipo_regime_weak_3of3():
    """AC2: 3/3 触发 → sent alert。"""
    with patch("scheduler.executors.ipo_regime.get_ipo_regime_health") as mock_h, \
         patch("scheduler.executors.ipo_regime._send_text_notification") as mock_notify:
        mock_h.return_value = _mock_health(break_rate=0.25, median=20.0, ipo_pw=7.0)
        from scheduler.executors.ipo_regime import ipo_regime_monitor
        result = ipo_regime_monitor({"notify": True})
    assert result["status"] == "sent"
    assert result["triggers"] == 3
    mock_notify.assert_called_once()


def test_ipo_regime_normal_0_trigger():
    """AC3: 0/3 触发(全正常) → skip 不打扰。"""
    with patch("scheduler.executors.ipo_regime.get_ipo_regime_health") as mock_h, \
         patch("scheduler.executors.ipo_regime._send_text_notification") as mock_notify:
        mock_h.return_value = _mock_health(break_rate=0.01, median=199.0, ipo_pw=2.0)
        from scheduler.executors.ipo_regime import ipo_regime_monitor
        result = ipo_regime_monitor({"notify": True})
    assert result["status"] == "skip"
    assert result["regime"] == "normal"
    assert result["triggers"] == 0
    mock_notify.assert_not_called()


def test_ipo_regime_normal_1_trigger():
    """AC3: 1/3 触发(边界) → skip(需 2/3 才 alert)。"""
    with patch("scheduler.executors.ipo_regime.get_ipo_regime_health") as mock_h, \
         patch("scheduler.executors.ipo_regime._send_text_notification") as mock_notify:
        # 只 IPO 加速触发(破发+median 正常)
        mock_h.return_value = _mock_health(break_rate=0.05, median=199.0, ipo_pw=7.0)
        from scheduler.executors.ipo_regime import ipo_regime_monitor
        result = ipo_regime_monitor({"notify": True})
    assert result["status"] == "skip"
    assert result["triggers"] == 1
    mock_notify.assert_not_called()


def test_ipo_regime_breaker_err_skip():
    """AC1: breaker open/fetch err → skip。"""
    with patch("scheduler.executors.ipo_regime.get_ipo_regime_health") as mock_h, \
         patch("scheduler.executors.ipo_regime._send_text_notification") as mock_notify:
        mock_h.return_value = {"error": "breaker open"}
        from scheduler.executors.ipo_regime import ipo_regime_monitor
        result = ipo_regime_monitor({"notify": True})
    assert result["status"] == "skip"
    assert "breaker" in result["reason"]
    mock_notify.assert_not_called()


def test_ipo_regime_health_thresholds():
    """AC2: 阈值边界——破发率 10% 整(不触发,需 >10%)。"""
    with patch("scheduler.executors.ipo_regime.get_ipo_regime_health") as mock_h:
        # break_rate=0.10 整(不 >0.10)= 不触发;median=50 整(不 <50)= 不触发
        mock_h.return_value = _mock_health(break_rate=0.10, median=50.0, ipo_pw=3.0)
        from scheduler.executors.ipo_regime import ipo_regime_monitor
        result = ipo_regime_monitor({"notify": True})
    # 0/3 触发(边界值不触发,需严格 >/<)
    assert result["triggers"] == 0
    assert result["regime"] == "normal"
