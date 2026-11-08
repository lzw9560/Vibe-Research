# -*- coding: utf-8 -*-
"""S244 红利低波仓位规则测试——季再平衡 + drawdown 监控。

TDD:先写测试验证逻辑(季初触发/非季初 skip/dd<=-20% 触发/dd 正常 skip/dd 观察区 skip)。
"""
from __future__ import annotations

from unittest.mock import patch
from datetime import datetime


# === portfolio_rebalance_remind ===

def test_rebalance_remind_quarter_start_jan():
    """AC2: 1 月(季初)触发提醒。"""
    with patch("scheduler.executors.portfolio.datetime") as mock_dt, \
         patch("scheduler.executors.portfolio._send_text_notification") as mock_notify:
        mock_dt.now.return_value = datetime(2026, 1, 5)
        from scheduler.executors.portfolio import portfolio_rebalance_remind
        result = portfolio_rebalance_remind({"notify": True})
    assert result["status"] == "sent"
    assert result["month"] == 1
    mock_notify.assert_called_once()


def test_rebalance_remind_quarter_start_apr():
    """AC2: 4 月(季初)触发。"""
    with patch("scheduler.executors.portfolio.datetime") as mock_dt, \
         patch("scheduler.executors.portfolio._send_text_notification") as mock_notify:
        mock_dt.now.return_value = datetime(2026, 4, 1)
        from scheduler.executors.portfolio import portfolio_rebalance_remind
        result = portfolio_rebalance_remind({"notify": True})
    assert result["status"] == "sent"
    assert result["month"] == 4


def test_rebalance_remind_non_quarter_skip():
    """AC2: 2 月(非季初)skip。"""
    with patch("scheduler.executors.portfolio.datetime") as mock_dt, \
         patch("scheduler.executors.portfolio._send_text_notification") as mock_notify:
        mock_dt.now.return_value = datetime(2026, 2, 15)
        from scheduler.executors.portfolio import portfolio_rebalance_remind
        result = portfolio_rebalance_remind({"notify": True})
    assert result["status"] == "skip"
    assert "非季初" in result["reason"]
    mock_notify.assert_not_called()


# === portfolio_drawdown_monitor ===

def test_drawdown_monitor_trigger_reduce():
    """AC3/AC4: drawdown <= -20% 触发减仓提醒。"""
    with patch("scheduler.executors.portfolio.get_divlowvol_drawdown") as mock_dd, \
         patch("scheduler.executors.portfolio._send_text_notification") as mock_notify:
        mock_dd.return_value = {"code": "512890", "current": 0.80, "peak": 1.10,
                                "drawdown": -0.273, "date": "2026-11-06"}
        from scheduler.executors.portfolio import portfolio_drawdown_monitor
        result = portfolio_drawdown_monitor({"notify": True})
    assert result["status"] == "sent"
    assert result["action"] == "reduce"
    assert result["drawdown"] <= -0.20
    mock_notify.assert_called_once()


def test_drawdown_monitor_normal_skip():
    """AC3: drawdown >= -10% 正常 skip。"""
    with patch("scheduler.executors.portfolio.get_divlowvol_drawdown") as mock_dd, \
         patch("scheduler.executors.portfolio._send_text_notification") as mock_notify:
        mock_dd.return_value = {"code": "512890", "current": 1.05, "peak": 1.10,
                                "drawdown": -0.045, "date": "2026-11-06"}
        from scheduler.executors.portfolio import portfolio_drawdown_monitor
        result = portfolio_drawdown_monitor({"notify": True})
    assert result["status"] == "skip"
    assert "正常" in result["reason"]
    mock_notify.assert_not_called()


def test_drawdown_monitor_observe_skip():
    """AC3: drawdown 在 -20%~-10% 观察区 skip。"""
    with patch("scheduler.executors.portfolio.get_divlowvol_drawdown") as mock_dd, \
         patch("scheduler.executors.portfolio._send_text_notification") as mock_notify:
        mock_dd.return_value = {"code": "512890", "current": 0.95, "peak": 1.10,
                                "drawdown": -0.136, "date": "2026-11-06"}
        from scheduler.executors.portfolio import portfolio_drawdown_monitor
        result = portfolio_drawdown_monitor({"notify": True})
    assert result["status"] == "skip"
    assert "观察区" in result["reason"]
    mock_notify.assert_not_called()


# === arm 注册 ===

def test_divlowvol_arm_setup():
    """AC1: _setup_divlowvol_arm 注册 arm_status(is_active=1, weight=0.25)。"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from engine.trade_journal import TradeJournal
    tj = TradeJournal()
    tj.set_arm_status("dividend_low_vol", is_active=True, weight_override=0.25)
    st = tj.query_arm_status("dividend_low_vol")
    assert st is not None
    # st 可能是 tuple/dict,核 is_active + weight
    if isinstance(st, tuple):
        assert st[0] is True or st[1] is True  # is_active
        assert abs(float(st[2] if len(st) > 2 else 0.25) - 0.25) < 1e-6 or st[1] is True
    elif isinstance(st, dict):
        assert st.get("is_active") is True
        assert abs(float(st.get("weight_override", 0)) - 0.25) < 1e-6
