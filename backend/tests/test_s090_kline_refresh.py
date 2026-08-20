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
