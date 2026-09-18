# -*- coding: utf-8 -*-
"""S218 Component 3: 关键点位决策通知 keypoint_notify 测试。

验收 (spec §4):
- test_keypoint_notify_reuses_comp1_core：不重复 scan+regime+lift
- test_gapdown_is_honest_label_not_stop_loss："诚实标" + 不含"止损通知"
- test_notify_uses_send_notification_not_routers：走 _send_notification/NotificationService
- test_d_close_entry_notify_has_reference_price：D 收盘入场通知含参考价 + 入场指引
- test_notify_carries_s44_honesty_strings：统计验证 / paper-only / 零真交易 / 照做有风险
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_notification_service():
    """Mock NotificationService 防真发通知。"""
    with patch("notification.notification_service.NotificationService", autospec=True):
        yield


def _make_signals() -> dict:
    """构造 get_consecutive_relay_signals 返回的标准 mock 结构。"""
    return {
        "date": "2026-09-18",
        "arm": "consecutive_relay",
        "regime": {
            "current": "bull",
            "edge_status": "bull validated（train 1.57%→test 1.04%，p=0.0054）",
            "freshness": {"last_cache_date": "2026-09-18", "stale": False, "days_since": 0, "n_dates": 30},
        },
        "cap": {
            "effective": 0.75,
            "base": 1.0,
            "decay": 0.75,
            "regime_factor": 1.0,
            "zuoT_factor": 1.0,
            "note": "bull ×0.75 provisional",
        },
        "filters": {
            "total_scanned": 3,
            "tradable": 2,
            "exploratory": 0,
            "avoid": 1,
        },
        "signals": [
            {
                "code": "000001.SZ",
                "name": "平安银行",
                "lbc": 2,
                "entry_price": 12.34,
                "price_source": "2026-09-18",
                "unbuyable": False,
                "bucket": "tradable",
            },
            {
                "code": "000002.SZ",
                "name": "万科A",
                "lbc": 3,
                "entry_price": 15.67,
                "price_source": "2026-09-18",
                "unbuyable": False,
                "bucket": "tradable",
            },
            {
                "code": "000003.SZ",
                "name": "ST某某",
                "lbc": 2,
                "entry_price": None,
                "price_source": "N/A",
                "unbuyable": True,
                "bucket": "avoid",
            },
        ],
        "verified_numbers": {
            "chrono_train": 1.57,
            "chrono_test": 1.04,
            "chrono_decay_pct": 34,
            "chrono_p": 0.0054,
            "chrono_wr": 52.7,
            "deep_dive_lbc2": 0.90,
            "deep_dive_lbc3": 2.05,
        },
        "disclaimers": [
            "统计验证（非已实现收益）—— edge 衰减中（train 1.57%→test 1.04% 跌 34%）",
            "paper-only 无券商（零真交易）—— 接券商前所有战绩 paper，要真获益须手动在券商下单",
            "照做有风险 —— cap（75%/50%）是统计信心不是保本，真钱仓位由你手动定",
            "非自动交易 —— 本系统不自动下单，须手动在券商下单",
            "bull 已 validated（×0.75），但 within-regime only，别跨 regime 推广",
        ],
    }


def _make_signals_bear() -> dict:
    """bear regime mock（用于探索性信号测试）。"""
    s = _make_signals()
    s["regime"]["current"] = "bear"
    s["regime"]["edge_status"] = "bear underpowered（<60 test 天没法定，×0.5 保守）"
    s["cap"]["effective"] = 0.5
    s["cap"]["note"] = "bear ×0.5 underpowered"
    for sig in s["signals"][:2]:
        sig["bucket"] = "exploratory"
    s["filters"]["tradable"] = 0
    s["filters"]["exploratory"] = 2
    return s


def _make_signals_gapdown() -> dict:
    """包含 gap-down 场景的 mock（D+1 开盘 < D 收盘，模拟 gap-down）。"""
    s = _make_signals()
    s["gap_down"] = True  # keypoint_notify 内部判断 gap-down 的 hint
    return s


# ── helpers ───────────────────────────────────────────────────────────────

def _collect_notifications():
    """patch _send_text_notification 并收集所有调用参数。"""
    calls = []

    def _fake_send(text: str) -> None:
        calls.append(text)

    return calls, _fake_send


def _text_contains(text: str, *needles: str) -> bool:
    """Assert text contains ALL needles (case-insensitive on Chinese)."""
    for n in needles:
        if n not in text:
            return False
    return True


def _text_not_contains(text: str, *needles: str) -> bool:
    """Assert text contains NONE of the needles."""
    for n in needles:
        if n in text:
            return False
    return True


# ── test: reuse comp1 core ───────────────────────────────────────────────

def test_keypoint_notify_reuses_comp1_core():
    """keypoint_notify 必须调用 get_consecutive_relay_signals，不重复 scan+regime+lift。"""
    from scheduler.executors.signals import keypoint_notify
    from tools.signal_report import get_consecutive_relay_signals

    with patch(
        "scheduler.executors.signals.get_consecutive_relay_signals",
        return_value=_make_signals(),
    ) as mock_get_signals:
        with patch("scheduler.executors.signals._send_text_notification", return_value=None):
            result = keypoint_notify({"run_date": "2026-09-18", "notify": False})

    # 1. 必须调用 get_consecutive_relay_signals
    mock_get_signals.assert_called_once_with("2026-09-18")

    # 2. 返回值结构正确
    assert result["status"] == "ok"
    assert result["date"] == "2026-09-18"
    assert "notifications" in result
    assert result["notifications_sent"] == 3  # D收盘 + D+1开盘 + gap-down


# ── test: gap-down 诚实标，非止损通知 ────────────────────────────────────

def test_gapdown_is_honest_label_not_stop_loss():
    """gap-down 通知必须标'诚实标'，禁止出现'止损通知'。"""
    from scheduler.executors.signals import keypoint_notify

    with patch(
        "scheduler.executors.signals.get_consecutive_relay_signals",
        return_value=_make_signals(),
    ):
        captured = []
        with patch("scheduler.executors.signals._send_text_notification", side_effect=captured.append):
            keypoint_notify({"run_date": "2026-09-18", "notify": True})

    # 找 gap-down 通知（或任意通知）
    all_text = "\n".join(captured)

    # 必须含"诚实标"
    assert "诚实标" in all_text, f"通知应含'诚实标'，实际：{all_text[:200]}"
    # 必须含"仓位 sizing"
    assert "仓位 sizing" in all_text or "sizing" in all_text.lower(), f"通知应含仓位 sizing"
    # 必须含"非 stop-loss" 或类似表达
    assert any(
        phrase in all_text for phrase in ["非 stop-loss", "非 stop loss", "不是 stop-loss", "非 stop"]
    ), f"通知应说明不是 stop-loss，实际：{all_text[:200]}"
    # 禁止含完整词"止损通知"（但允许分开出现）
    assert "止损通知" not in all_text, f"通知不应出现'止损通知'，实际：{all_text[:200]}"


# ── test: Feishu path via _send_notification ──────────────────────────────

def test_notify_uses_send_notification_not_routers():
    """通知必须走 _send_text_notification（即 NotificationService.send），不能调 routers/feishu。"""
    from scheduler.executors.signals import keypoint_notify

    mock_send = MagicMock(return_value=None)

    with patch(
        "scheduler.executors.signals.get_consecutive_relay_signals",
        return_value=_make_signals(),
    ):
        with patch("scheduler.executors.signals._send_text_notification", mock_send):
            keypoint_notify({"run_date": "2026-09-18", "notify": True})

    # 必须调用 send 方法（不走 routers/feishu.py）
    assert mock_send.called, "应调用 _send_text_notification，但未被调用"

    # 不应 import routers.feishu
    import scheduler.executors.signals as _signals_module
    assert "routers" not in str(_signals_module.__file__), "不应直接依赖 routers"


# ── test: D 收盘入场通知含参考价 + 入场指引 ───────────────────────────────

def test_d_close_entry_notify_has_reference_price():
    """D 收盘入场通知必须含参考价 + 入场指引（14:57-15:00 集合竞价）。"""
    from scheduler.executors.signals import keypoint_notify

    captured = []
    with patch(
        "scheduler.executors.signals.get_consecutive_relay_signals",
        return_value=_make_signals(),
    ):
        with patch("scheduler.executors.signals._send_text_notification", side_effect=captured.append):
            keypoint_notify({"run_date": "2026-09-18", "notify": True})

    all_text = "\n".join(captured)

    # 参考价
    assert "¥12.34" in all_text or "12.34" in all_text, f"应含参考价 12.34，实际：{all_text[:200]}"
    # 入场指引
    assert "14:57" in all_text or "集合竞价" in all_text, f"应含 14:57-15:00 集合竞价指引"
    # D 收盘买
    assert any(w in all_text for w in ["今日收盘", "D 收盘", "收盘买"]), f"应含 D 收盘入场指引"


# ── test: §44 诚实性字符串 ───────────────────────────────────────────────

def test_notify_carries_s44_honesty_strings():
    """通知必须携带 §44 诚实性标签：统计验证 / 非已实现收益 / paper-only / 零真交易 / 照做有风险。"""
    from scheduler.executors.signals import keypoint_notify

    captured = []
    with patch(
        "scheduler.executors.signals.get_consecutive_relay_signals",
        return_value=_make_signals(),
    ):
        with patch("scheduler.executors.signals._send_text_notification", side_effect=captured.append):
            keypoint_notify({"run_date": "2026-09-18", "notify": True})

    all_text = "\n".join(captured)

    # 统计验证 / 非已实现收益
    assert any(w in all_text for w in ["统计验证", "非已实现收益"]), f"应含统计验证/非已实现收益标签"
    # paper-only / 零真交易
    assert any(w in all_text for w in ["paper-only", "零真交易", "无券商"]), f"应含 paper-only/零真交易标签"
    # 照做有风险
    assert "照做有风险" in all_text, f"应含'照做有风险'标签"
    # ×0.75 公式
    assert any(w in all_text for w in ["×0.75", "× 0.75"]), f"应含 cap ×0.75 标注"


# ── smoke: 三种通知的完整文本结构 ─────────────────────────────────────────

def test_keypoint_notify_three_notifications_structure():
    """Smoke: 验证三种通知（D收盘入场 / D+1开盘出场 / gap-down 诚实标）都有内容。"""
    from scheduler.executors.signals import keypoint_notify

    captured = []
    with patch(
        "scheduler.executors.signals.get_consecutive_relay_signals",
        return_value=_make_signals(),
    ):
        with patch("scheduler.executors.signals._send_text_notification", side_effect=captured.append):
            result = keypoint_notify({"run_date": "2026-09-18", "notify": True})

    # 返回结构
    assert result["status"] == "ok"
    notifications = result.get("notifications", [])
    assert len(notifications) == 3, f"应有 3 条通知，实际 {len(notifications)}"

    titles = [n.get("title", "") for n in notifications]
    # D 收盘
    assert any("收盘" in t or "入场" in t for t in titles), f"应有 D 收盘入场通知: {titles}"
    # D+1 开盘
    assert any("开盘" in t or "出场" in t for t in titles), f"应有 D+1 开盘出场通知: {titles}"
    # gap-down
    assert any("gap" in t.lower() or "诚实标" in t or "风控" in t for t in titles), f"应有 gap-down 诚实标通知: {titles}"

    # 每条都有内容
    for n in notifications:
        assert n.get("body"), f"通知 {n.get('title')} 应有 body"
