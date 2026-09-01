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


# ── wrapper 真身直测（spec A4 兑现：patch astock.index_quote，不 mock wrapper）────
# 原 4 测 mock 了 _check_premarket_kill_switch 本身，wrapper 真身（import 接线 +
# MarketKillSwitch 属性访问 + except 降级）零覆盖。以下 3 测 patch 数据源让真函数跑。


def test_check_wrapper_real_triggered(monkeypatch):
    """真 wrapper + 真 check_market_kill_switch：暴跌 indices → triggered=True + 正确 pct。

    覆盖 import 接线 + MarketKillSwitch 属性访问（triggered/reason/sh_change_pct/gem_change_pct）。
    若 dataclass 改字段名或 import 路径断 → 此测报红（不会静默永远降级）。
    """
    import astock  # noqa: PLC0415
    crash = [
        {"name": "上证指数", "change_pct": -5.0},
        {"name": "创业板指", "change_pct": -1.20},
    ]
    monkeypatch.setattr(astock, "index_quote", lambda: crash)

    ks = st._check_premarket_kill_switch()

    assert ks["triggered"] is True
    assert "上证" in ks["reason"]
    assert ks["sh_change_pct"] == -5.0
    assert ks["gem_change_pct"] == -1.20


def test_check_wrapper_indices_empty_no_false_alarm(monkeypatch):
    """astock.index_quote 返 [] → 真 check_market_kill_switch 返 not_triggered（不臆造）。

    spec A4：indices 空 → 不触发熔断，wrapper 透传 None pct + reason 标 missing。
    """
    import astock  # noqa: PLC0415
    monkeypatch.setattr(astock, "index_quote", lambda: [])

    ks = st._check_premarket_kill_switch()

    assert ks["triggered"] is False
    assert "未取得" in ks["reason"] or "不触发" in ks["reason"]
    assert ks["sh_change_pct"] is None
    assert ks["gem_change_pct"] is None


def test_check_wrapper_exception_degrades_no_false_alarm(monkeypatch):
    """astock.index_quote 抛异常 → wrapper except 降级 not_triggered（不臆造，不阻断）。

    覆盖 wrapper 的 except 分支——9:25 网络挂/import 断时 kill_switch 永不误触发的诚实保证。
    若此分支坏（如返 triggered=True 或抛出）→ 此测报红。
    """
    import astock  # noqa: PLC0415

    def _boom():
        raise RuntimeError("tencent 不可达")

    monkeypatch.setattr(astock, "index_quote", _boom)

    ks = st._check_premarket_kill_switch()

    assert ks["triggered"] is False
    assert "降级" in ks["reason"]
    assert ks["sh_change_pct"] is None
    assert ks["gem_change_pct"] is None
