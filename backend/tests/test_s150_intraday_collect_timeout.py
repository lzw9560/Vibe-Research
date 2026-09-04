# -*- coding: utf-8 -*-
"""S150 R4：盘中采集 stale-run 堵塞修复测试。

验证：
- R1 _task_timeout：per-task_type 返正确秒数（seal=120/precompute=700/默认=300）
- R2 reap_stale_running：stale running run 标 failed + 返 task_id；fresh running 不动
- R2 _reap_stale_runs：discard _running_task_ids（去堵 dedup，根因 B 真修）
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

import scheduled_tasks as st


def _make_file_db(tmp_path) -> str:
    """tmp_path 下建文件 DB + scheduled_task_runs 建表，返 db_path（close 不丢数据）。"""
    db_path = str(tmp_path / "test_scheduled_tasks.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduled_task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            status TEXT,
            started_at TEXT,
            finished_at TEXT,
            result TEXT,
            error TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _open_conn(db_path: str) -> sqlite3.Connection:
    """新开 conn（文件 DB 持久，reap close 后 test 重开查）。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


class _FakeTask:
    """最小 task stub（_task_timeout 只访问 task_type）。"""

    def __init__(self, task_type: str):
        self.task_type = task_type


# ─────────────────────────────────────────────────────────────────────────────
# R1：_task_timeout
# ─────────────────────────────────────────────────────────────────────────────

def test_task_timeout_per_type():
    """R1：_task_timeout 按 task_type 返秒数（seal=120/precompute=700/kline_refresh=1200/默认=300）。"""
    assert st._task_timeout(_FakeTask("seal_intraday_collect")) == 120
    assert st._task_timeout(_FakeTask("limitup_precompute")) == 700
    assert st._task_timeout(_FakeTask("kline_refresh")) == 1200  # 审查 HIGH2: 全A baostock 稳态>300s 防误杀
    assert st._task_timeout(_FakeTask("unknown_type")) == st._DEFAULT_TASK_TIMEOUT == 300


def test_reaper_stale_seconds_gt_max_task_timeout():
    """R2：reaper 阈值 > max task timeout（reaper 在 timeout 后才兜底，不抢前）。"""
    max_timeout = max(st._TASK_TIMEOUTS.values())
    assert st._REAPER_STALE_SECONDS > max_timeout


# ─────────────────────────────────────────────────────────────────────────────
# R2：reap_stale_running
# ─────────────────────────────────────────────────────────────────────────────

def test_reap_stale_running_marks_failed_and_returns_task_ids(tmp_path, monkeypatch):
    """R2：stale running run 标 failed + 返 task_id；fresh running 不动。"""
    db_path = _make_file_db(tmp_path)
    conn = _open_conn(db_path)
    # stale run（started_at 远早于 cutoff）
    conn.execute(
        "INSERT INTO scheduled_task_runs (id, task_id, status, started_at) "
        "VALUES (1, 5, 'running', '2020-01-01T00:00:00')"
    )
    # fresh run（started_at 现在，不应被 reap）
    conn.execute(
        "INSERT INTO scheduled_task_runs (id, task_id, status, started_at) "
        "VALUES (2, 6, 'running', ?)",
        (datetime.now().isoformat(),),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(st, "_get_connection", lambda: _open_conn(db_path))

    reaped = st._manager.reap_stale_running(st._REAPER_STALE_SECONDS)

    assert 5 in reaped, "stale task 5 应被 reap"
    assert 6 not in reaped, "fresh task 6 不应被 reap"

    # stale 标 failed + error 标 reap（重开 conn 查）
    conn = _open_conn(db_path)
    row = conn.execute("SELECT status, error FROM scheduled_task_runs WHERE id = 1").fetchone()
    assert row["status"] == "failed"
    assert "reaped stale" in (row["error"] or "")
    # fresh 仍 running
    row2 = conn.execute("SELECT status FROM scheduled_task_runs WHERE id = 2").fetchone()
    assert row2["status"] == "running"
    conn.close()


def test_reap_stale_running_empty_returns_empty(tmp_path, monkeypatch):
    """R2：无 stale run 时返空列表（不误动）。"""
    db_path = _make_file_db(tmp_path)
    monkeypatch.setattr(st, "_get_connection", lambda: _open_conn(db_path))
    assert st._manager.reap_stale_running(st._REAPER_STALE_SECONDS) == []


# ─────────────────────────────────────────────────────────────────────────────
# R2：_reap_stale_runs（CronScheduler 去堵 dedup）
# ─────────────────────────────────────────────────────────────────────────────

def test_reap_stale_runs_discards_running_task_ids(tmp_path, monkeypatch):
    """R2：_reap_stale_runs 清 DB stale + discard _running_task_ids（根因 B 真修）。"""
    db_path = _make_file_db(tmp_path)
    conn = _open_conn(db_path)
    conn.execute(
        "INSERT INTO scheduled_task_runs (id, task_id, status, started_at) "
        "VALUES (1, 5, 'running', '2020-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(st, "_get_connection", lambda: _open_conn(db_path))

    sched = st.CronScheduler()
    sched._running_task_ids.add(5)  # task 5 被 stale run 堵 dedup

    sched._reap_stale_runs()

    assert 5 not in sched._running_task_ids, "stale task 5 应从 _running_task_ids discard"
    # DB 也标 failed
    conn = _open_conn(db_path)
    row = conn.execute("SELECT status FROM scheduled_task_runs WHERE id = 1").fetchone()
    assert row["status"] == "failed"
    conn.close()


def test_reap_stale_runs_failure_does_not_crash_tick(monkeypatch):
    """R2：reap 异常不阻断（_tick 容错，noqa BLE001）。"""
    def boom(stale_seconds: int):
        raise RuntimeError("db down")
    monkeypatch.setattr(st._manager, "reap_stale_running", boom)
    sched = st.CronScheduler()
    sched._reap_stale_runs()  # 不抛


def test_thread_pool_isolated_from_default():
    """审查 HIGH1：TaskExecutor 独占 _thread_pool（max_workers=2），不共享 asyncio 默认池——
    调度器线程泄漏不影响路由器 asyncio.to_thread（71 调用方共享默认池，API 不冻）。"""
    te = st.TaskExecutor()
    assert hasattr(te, "_thread_pool")
    assert te._thread_pool._max_workers == 2
    # 独占池≠asyncio 默认池
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        default_exec = loop._default_executor
        assert te._thread_pool is not default_exec, "调度器池应独占，非默认池"
    finally:
        loop.close()
