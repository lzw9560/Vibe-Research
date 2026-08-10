"""S026: workflow pre-market 异步化单测（缓存 + 并发守卫 + GET 状态返回）。"""
from __future__ import annotations

import asyncio

import pytest

from routers import workflow as wf
from factors.base import FactorResult


def _fr(fid: str) -> FactorResult:
    return FactorResult(factor_id=fid, factor_name=fid, candidates=[], layers=[], config={})


def _reset_cache(monkeypatch, status="idle", run_id=None, factors=None):
    monkeypatch.setattr(
        wf,
        "_cache",
        {
            "run_id": run_id,
            "status": status,
            "factors": factors,
            "data_date": "2026-08-03",
            "as_of": None,
            "market_emotion": None,
            "error": None,
        },
    )


# ── B2: _collect 写缓存 ──────────────────────────────────────────────────


def test_collect_success_writes_done_cache(monkeypatch):
    async def fake_afetch(date, config=None):
        return [_fr("f1"), _fr("f2")]

    monkeypatch.setattr(wf.factor_registry, "afetch_all", fake_afetch)
    monkeypatch.setattr(wf.factor_registry, "register_default_factors", lambda: None)
    monkeypatch.setattr(wf, "_fetch_market_emotion", lambda d: {"sentiment": "neutral"})
    # S048：funnel_layers 构建（真跑会碰外部源）与快照落盘均隔离
    monkeypatch.setattr(wf, "_build_funnel_layers", lambda d: [])
    monkeypatch.setattr(wf, "_save_snapshot", lambda payload: None)
    _reset_cache(monkeypatch, status="running", run_id="rid1")

    asyncio.run(wf._collect("rid1", "2026-08-03"))

    assert wf._cache["status"] == "done"
    assert [f["factor_id"] for f in wf._cache["factors"]] == ["f1", "f2"]
    assert wf._cache["market_emotion"] == {"sentiment": "neutral"}
    assert wf._cache["as_of"] is not None
    assert wf._cache["run_id"] == "rid1"


def test_collect_failure_writes_error_cache(monkeypatch):
    async def boom(date, config=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(wf.factor_registry, "afetch_all", boom)
    monkeypatch.setattr(wf.factor_registry, "register_default_factors", lambda: None)
    monkeypatch.setattr(wf, "_fetch_market_emotion", lambda d: {})
    monkeypatch.setattr(wf, "_build_funnel_layers", lambda d: [])
    monkeypatch.setattr(wf, "_save_snapshot", lambda payload: None)
    _reset_cache(monkeypatch, status="running", run_id="rid1")

    asyncio.run(wf._collect("rid1", "2026-08-03"))

    assert wf._cache["status"] == "error"
    assert "boom" in wf._cache["error"]
    assert wf._cache["run_id"] == "rid1"


# ── B3: refresh 并发守卫 ────────────────────────────────────────────────


def test_refresh_idle_starts_collection(monkeypatch):
    _reset_cache(monkeypatch, status="idle")
    created: list = []

    async def noop_collect(rid, target):
        created.append(rid)

    monkeypatch.setattr(wf, "_collect", noop_collect)
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-03")

    r = asyncio.run(wf.refresh_pre_market(date="2026-08-03"))

    assert r["status"] == "running"
    assert r["run_id"]
    assert wf._cache["status"] == "running"
    assert wf._cache["run_id"] == r["run_id"]


def test_refresh_concurrent_returns_existing_run(monkeypatch):
    _reset_cache(monkeypatch, status="running", run_id="existing")
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-03")
    created: list = []

    async def noop_collect(rid, target):
        created.append(rid)

    monkeypatch.setattr(wf, "_collect", noop_collect)

    r = asyncio.run(wf.refresh_pre_market(date="2026-08-03"))

    assert r["status"] == "running"
    assert r["run_id"] == "existing"
    assert "已有采集在跑" in r["msg"]
    assert created == []  # 未重复创建采集任务


# ── C1: GET 各状态返回 ──────────────────────────────────────────────────


def test_get_idle_returns_prompt(monkeypatch):
    _reset_cache(monkeypatch, status="idle", factors=None)
    r = asyncio.run(wf.get_pre_market_workflow(date="2026-08-03"))
    assert r["status"] == "idle"
    assert "refresh" in r["msg"]


def test_get_done_returns_factors(monkeypatch):
    _reset_cache(
        monkeypatch,
        status="done",
        factors=[{"factor_id": "f1"}, {"factor_id": "f2"}],
    )
    r = asyncio.run(wf.get_pre_market_workflow(date="2026-08-03"))
    assert r["status"] == "done"
    assert [f["factor_id"] for f in r["factors"]] == ["f1", "f2"]


def test_get_error_returns_error(monkeypatch):
    _reset_cache(monkeypatch, status="error", factors=None)
    monkeypatch.setitem(wf._cache, "error", "boom")
    r = asyncio.run(wf.get_pre_market_workflow(date="2026-08-03"))
    assert r["status"] == "error"
    assert r["error"] == "boom"
