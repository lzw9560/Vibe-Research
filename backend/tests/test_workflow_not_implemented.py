"""S036: workflow 桩端点标灰单测——五个端点返回 not_implemented，不跑桩逻辑。

端点 early return 后不应触达 _workflow.run_intraday / run_post_market /
_workflow.intraday.signals / _bomb_alert_system.active_alerts。给这些装上"会爆炸"
的桩——若端点误调/误读立即 AssertionError 失败，从而把"标灰"钉死。
"""
from __future__ import annotations

import asyncio

import pytest

from routers import workflow as wf


def _guard_workflow(monkeypatch):
    """给桩逻辑装爆炸防护：端点标灰后任何误触达都立即失败。"""

    async def boom(*_a, **_kw):
        raise AssertionError("桩逻辑不应被触发（S036 标灰：端点应 early return）")

    monkeypatch.setattr(wf._workflow, "run_intraday", boom)
    monkeypatch.setattr(wf._workflow, "run_post_market", boom)
    monkeypatch.setattr(wf._bomb_alert_system, "active_alerts", boom)

    class _ExplodingIntraday:
        @property
        def signals(self):
            raise AssertionError("不应读 intraday.signals（S036 标灰）")

        @property
        def alerts(self):
            raise AssertionError("不应读 intraday.alerts（S036 标灰）")

    monkeypatch.setattr(wf._workflow, "intraday", _ExplodingIntraday())


def _assert_not_implemented(r: dict, *, message_contains: str = ""):
    assert r["not_implemented"] is True
    assert r["spec"] == "S036"
    if message_contains:
        assert message_contains in r["message"], r["message"]


def test_realtime_returns_not_implemented(monkeypatch):
    _guard_workflow(monkeypatch)
    r = asyncio.run(wf.get_realtime_workflow())
    _assert_not_implemented(r, message_contains="盘中监控")


def test_intraday_alias_returns_not_implemented(monkeypatch):
    """向后兼容别名 /intraday 与 /realtime 同走 early return。"""
    _guard_workflow(monkeypatch)
    r = asyncio.run(wf.get_intraday_workflow_alias())
    _assert_not_implemented(r, message_contains="盘中监控")


def test_post_market_returns_not_implemented(monkeypatch):
    _guard_workflow(monkeypatch)
    r = asyncio.run(wf.get_post_market_workflow())
    _assert_not_implemented(r, message_contains="盘后复盘")


def test_signals_returns_not_implemented(monkeypatch):
    _guard_workflow(monkeypatch)
    r = asyncio.run(wf.get_realtime_signals())
    _assert_not_implemented(r, message_contains="盘中信号")


def test_alerts_returns_not_implemented(monkeypatch):
    _guard_workflow(monkeypatch)
    r = asyncio.run(wf.get_bomb_alerts())
    _assert_not_implemented(r, message_contains="炸板预警")


def test_settle_returns_not_implemented(monkeypatch):
    _guard_workflow(monkeypatch)
    r = asyncio.run(wf.settle_position())
    _assert_not_implemented(r)
    # 指引用状态机流转结算（S034），不跑批量结算桩
    assert "状态机" in r["message"] or "S034" in r["message"], r["message"]


def test_refresh_unaffected(monkeypatch):
    """refresh 端点不涉及桩（S036 R6 保留），正常返回时间戳。"""
    _guard_workflow(monkeypatch)
    r = asyncio.run(wf.refresh_workflow())
    assert r["data"]["status"] == "success"
    assert "refreshed_at" in r["data"]
