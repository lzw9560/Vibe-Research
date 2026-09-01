# -*- coding: utf-8 -*-
"""S136：premarket 开盘后 kill_switch 实时核测（market_note 承诺落地）。

覆盖：
- 9:25/9:35 premarket 通知调 _check_premarket_kill_switch
- triggered=True → 通知 content 前置「⚠️ 市场熔断」「不开新仓」+ 返体 kill_switch.triggered
- triggered=False → 通知不变（无熔断警告）
- 检查降级（indices 空/检查失败）→ not_triggered，不臆造熔断，通知正常发
"""
from __future__ import annotations

import pytest

import scheduled_tasks as st


def _ks(triggered: bool, reason: str = "", sh=None, gem=None) -> dict:
    """构造 _check_premarket_kill_switch 返回 dict。"""
    return {"triggered": triggered, "reason": reason,
            "sh_change_pct": sh, "gem_change_pct": gem}


@pytest.fixture
def _final_cards():
    return [{"code": "600519", "name": "茅台"}]


def _patch_common(monkeypatch, _final_cards, ks, captured):
    """patch _load_final_cards/_fetch_quotes/_check_premarket_kill_switch/_send_notify。"""
    monkeypatch.setattr(st, "_load_final_cards", lambda d: _final_cards)
    monkeypatch.setattr(st, "_fetch_quotes", lambda codes: {})
    monkeypatch.setattr(st, "_check_premarket_kill_switch", lambda: ks)
    monkeypatch.setattr(st, "_send_notify",
                        lambda content: (captured.append(content), True)[1])


def test_open_notify_kill_switch_triggered_prepends_warning(monkeypatch, _final_cards):
    """9:35 open_notify + kill_switch triggered → content 前置熔断块 + 返体 triggered=True。"""
    captured = []
    _patch_common(monkeypatch, _final_cards,
                  _ks(True, "上证跌幅 -3.50% > 3%，不开新仓", sh=-3.50), captured)

    executor = st.TaskExecutor()
    result = executor._execute_premarket_open_notify({"date": "2026-08-31"})

    assert result["status"] == "ok"
    assert result["kill_switch"]["triggered"] is True
    assert captured  # 通知发了（不屏蔽）
    content = captured[0]
    assert content.startswith("⚠️ 市场熔断")  # 前置（在 9:35 开盘表现 之前）
    assert "不开新仓" in content
    assert "上证 -3.50%" in content
    assert "9:35 开盘表现" in content  # 原 content 仍列（标注非屏蔽）


def test_auction_notify_kill_switch_triggered_prepends_warning(monkeypatch, _final_cards):
    """9:25 auction_notify + triggered → content 前置熔断块（创业板暴跌）。"""
    captured = []
    _patch_common(monkeypatch, _final_cards,
                  _ks(True, "创业板跌幅 -4.20% > 4%，不开新仓", gem=-4.20), captured)

    executor = st.TaskExecutor()
    result = executor._execute_premarket_auction_notify({"date": "2026-08-31"})

    assert result["kill_switch"]["triggered"] is True
    content = captured[0]
    assert "⚠️ 市场熔断" in content
    assert "不开新仓" in content
    assert "创业板 -4.20%" in content
    assert "9:25 竞价确认" in content


def test_open_notify_market_normal_no_warning(monkeypatch, _final_cards):
    """triggered=False（市场正常）→ 通知无熔断警告（不变）。"""
    captured = []
    _patch_common(monkeypatch, _final_cards,
                  _ks(False, "市场正常（上证 0.50% / 创业板 0.30%）", sh=0.50, gem=0.30), captured)

    executor = st.TaskExecutor()
    result = executor._execute_premarket_open_notify({"date": "2026-08-31"})

    assert result["kill_switch"]["triggered"] is False
    content = captured[0]
    assert "⚠️ 市场熔断" not in content
    assert "不开新仓" not in content
    assert content.startswith("📈 9:35")  # 原 content 头不变


def test_open_notify_kill_switch_check_degrades_no_false_alarm(monkeypatch, _final_cards):
    """检查降级（indices 空/检查失败）→ not_triggered，不臆造熔断，通知正常发。"""
    captured = []
    _patch_common(monkeypatch, _final_cards,
                  _ks(False, "检查失败（降级不触发）: boom"), captured)

    executor = st.TaskExecutor()
    result = executor._execute_premarket_open_notify({"date": "2026-08-31"})

    assert result["kill_switch"]["triggered"] is False
    assert "降级" in result["kill_switch"]["reason"]
    content = captured[0]
    assert "⚠️ 市场熔断" not in content  # 不臆造熔断
    assert captured  # 通知正常发（检查失败不阻断）
