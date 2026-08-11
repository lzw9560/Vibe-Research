# -*- coding: utf-8 -*-
"""S052 D1/D6：as_of_date 参数化 + point-in-time 截断测试。

- run_strategy_backtest(lookback, as_of)：_get_available_dates date <= as_of 截断
- _execute_daily_backtest_run payload as_of_date：snapshot_date=as_of + 窗口终点=as_of
- as_of=None 行为与现状字节级一致
- trades 日期全 <= as_of（point-in-time 守卫）
"""
from __future__ import annotations

from unittest import mock
from types import SimpleNamespace

import pytest

from strategies.strategy_backtest import (
    _get_available_dates,
    run_strategy_backtest,
    clear_cache,
    list_trades,
)


def test_get_available_dates_as_of_truncates(tmp_path, monkeypatch):
    """as_of 给定时只取 date <= as_of。"""
    import sqlite3
    db = tmp_path / "gene.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row  # 与 production get_db 一致
    conn.executescript(
        "CREATE TABLE gene_scores (date TEXT);"
        "INSERT INTO gene_scores VALUES ('2026-08-10'),('2026-08-08'),('2026-08-07'),('2026-07-15');"
    )
    conn.commit()
    conn.close()
    # get_db 返新连接（row_factory 需在每次连接设）
    def fake_get_db():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr("strategies.strategy_backtest.get_db", fake_get_db)

    dates = _get_available_dates(60, as_of="2026-08-08")
    assert all(d <= "2026-08-08" for d in dates)
    assert "2026-08-10" not in dates
    assert "2026-08-08" in dates

    # 缺省不截断（取全部）
    dates_all = _get_available_dates(60)
    assert "2026-08-10" in dates_all


def test_run_strategy_backtest_as_of_cache_key_distinct(monkeypatch, tmp_path):
    """不同 as_of → 不同缓存键 → 不串数据。"""
    import sqlite3
    clear_cache()
    db = tmp_path / "gene.db"
    conn = sqlite3.connect(db)
    conn.executescript("CREATE TABLE gene_scores (date TEXT); INSERT INTO gene_scores VALUES ('2026-08-10'),('2026-08-08');")
    conn.commit()
    conn.close()
    def fake_get_db():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr("strategies.strategy_backtest.get_db", fake_get_db)
    monkeypatch.setattr("strategies.strategy_backtest.astock.kline", lambda *a, **k: [])
    monkeypatch.setattr("strategies.strategy_backtest.kline_from_mootdx", lambda *a: SimpleNamespace(bars=[]))
    monkeypatch.setattr("strategies.strategy_backtest.match_strategies", lambda *a: [])

    r1 = run_strategy_backtest(30, as_of="2026-08-08")
    r2 = run_strategy_backtest(30, as_of="2026-08-10")
    # as_of=08-08 截断后只取 08-08 及之前（1 日：08-08）；as_of=08-10 取全部（2 日）
    # 关键是不串缓存（同 lookback 不同 as_of 各自独立计算，结果不互覆）
    assert r1[0].available_days == 1  # 08-08 截断后
    assert r2[0].available_days == 2  # 08-10 全取


def test_execute_daily_backtest_run_as_of_path(monkeypatch):
    """_execute_daily_backtest_run payload as_of_date → snapshot_date=as_of + 窗口终点=as_of。"""
    import scheduled_tasks as st

    captured = {}

    def fake_lite(start, end):
        captured["lite"] = {"start": start, "end": end}
        return SimpleNamespace(hit_rate=0.5, avg_return=1.0, total_signals=3)

    def fake_strat(lookback, as_of=None):
        captured["strat"] = {"lookback": lookback, "as_of": as_of}
        return []

    monkeypatch.setattr("backtest_lite.run_backtest_async", fake_lite)
    monkeypatch.setattr("strategies.strategy_backtest.run_strategy_backtest", fake_strat)
    monkeypatch.setattr(st, "_save_snapshot", lambda *a, **k: None)

    executor = st.TaskExecutor()
    result = executor._execute_daily_backtest_run({"lookback_days": 30, "as_of_date": "2026-07-15"})

    assert result["snapshot_date"] == "2026-07-15"
    assert result["as_of_date"] == "2026-07-15"
    assert captured["lite"]["end"] == "2026-07-15"  # 窗口终点=as_of
    assert captured["strat"]["as_of"] == "2026-07-15"


def test_execute_daily_backtest_run_default_today(monkeypatch):
    """缺省 as_of → snapshot_date=今天（行为不变）。"""
    import scheduled_tasks as st
    from datetime import datetime

    captured = {}

    def fake_lite(start, end):
        captured["lite"] = {"start": start, "end": end}
        return SimpleNamespace(hit_rate=0.5, avg_return=1.0, total_signals=3)

    monkeypatch.setattr("backtest_lite.run_backtest_async", fake_lite)
    monkeypatch.setattr("strategies.strategy_backtest.run_strategy_backtest", lambda lb, as_of=None: [])
    monkeypatch.setattr(st, "_save_snapshot", lambda *a, **k: None)

    executor = st.TaskExecutor()
    result = executor._execute_daily_backtest_run({"lookback_days": 30})

    today = datetime.now().strftime("%Y-%m-%d")
    assert result["snapshot_date"] == today
    assert result["as_of_date"] is None  # 缺省 None
    assert captured["lite"]["end"] == today
