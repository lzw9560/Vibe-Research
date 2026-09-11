# -*- coding: utf-8 -*-
"""S090 B kline_refresh task 单测——mock tools.refresh_kline_cache.main，验证 status/degraded/max_stocks 透传。"""
from __future__ import annotations


def test_kline_refresh_ok(monkeypatch):
    """main 返 0 → status ok + return_code 0。"""
    import scheduled_tasks

    monkeypatch.setattr("tools.refresh_kline_cache.main", lambda mx=None: 0)
    te = scheduled_tasks.TaskExecutor()
    r = te._execute_kline_refresh({})
    assert r["status"] == "ok"
    assert r["return_code"] == 0


def test_kline_refresh_degraded_on_main_fail(monkeypatch):
    """main 返 1（cache 不存在/baostock 未装/login 失败）→ status degraded。"""
    import scheduled_tasks

    monkeypatch.setattr("tools.refresh_kline_cache.main", lambda mx=None: 1)
    te = scheduled_tasks.TaskExecutor()
    r = te._execute_kline_refresh({})
    assert r["status"] == "degraded"
    assert r["return_code"] == 1


def test_kline_refresh_degraded_on_exception(monkeypatch):
    """main raise Exception → status degraded + reason 含错误信息。"""
    import scheduled_tasks

    def boom(mx=None):  # noqa: ANN001
        raise RuntimeError("baostock 挂")

    monkeypatch.setattr("tools.refresh_kline_cache.main", boom)
    te = scheduled_tasks.TaskExecutor()
    r = te._execute_kline_refresh({})
    assert r["status"] == "degraded"
    assert "baostock 挂" in r["reason"]


def test_kline_refresh_max_stocks_passed(monkeypatch):
    """max_stocks payload 透传给 main。"""
    import scheduled_tasks

    calls: list = []
    monkeypatch.setattr("tools.refresh_kline_cache.main",
                        lambda mx=None: calls.append(mx) or 0)
    te = scheduled_tasks.TaskExecutor()
    te._execute_kline_refresh({"max_stocks": 5})
    assert calls == [5]


def test_kline_refresh_registered_in_executors():
    """kline_refresh 注册在 _executors + 方法存在。"""
    import scheduled_tasks

    te = scheduled_tasks.TaskExecutor()
    assert "kline_refresh" in te._executors
    assert hasattr(te, "_execute_kline_refresh")
    assert te._executors["kline_refresh"] == te._execute_kline_refresh


def test_kline_refresh_reloads_bars_cache_on_success(monkeypatch):
    """main 返 0（刷盘成功）→ bars_provider 单例 cache 清掉重读。

    S175/S177：防 kline_refresh 16:30 写新 bar 但 _CACHE 仍读旧 → signal_date 不在
    bars → 全 unbuyable（推荐说买、执行说买不了）。
    """
    import scheduled_tasks
    from engine.bars_provider import KlineCacheBarsProvider

    reloaded: list = []
    monkeypatch.setattr("tools.refresh_kline_cache.main", lambda mx=None: 0)
    monkeypatch.setattr(KlineCacheBarsProvider, "reload",
                        lambda *a, **k: reloaded.append(True))
    te = scheduled_tasks.TaskExecutor()
    te._execute_kline_refresh({})
    assert reloaded == [True], "ret==0 成功后必须清 bars cache"


def test_kline_refresh_no_reload_on_degraded(monkeypatch):
    """main 返非 0（degraded）→ bars cache 不清（防刷新失败丢 cache）。S175/S177。"""
    import scheduled_tasks
    from engine.bars_provider import KlineCacheBarsProvider

    reloaded: list = []
    monkeypatch.setattr("tools.refresh_kline_cache.main", lambda mx=None: 1)
    monkeypatch.setattr(KlineCacheBarsProvider, "reload",
                        lambda *a, **k: reloaded.append(True))
    te = scheduled_tasks.TaskExecutor()
    te._execute_kline_refresh({})
    assert reloaded == [], "degraded 时不应清 cache（刷盘失败保留旧 bars）"
