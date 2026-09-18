# -*- coding: utf-8 -*-
"""S218 #4: startup task-registration drift self-check 测试。

守卫语义：TaskExecutor.__init__ 启动时读 scheduled_tasks 表所有 task_type，
对每个 seeded task_type 核在 dispatch dict。不在 → log error（不 raise，防 startup
crash）；DB 不可用 → log warning 跳过。让 stale dispatch dict（worktree merge +
uvicorn --reload 未抓改动 → DB 新 task_type + 旧内存 dict）立即日志可见，不等
cron fire 才报「未知任务类型」。

纯离线：monkeypatch _manager.list_tasks 返定制 task_type 列表（含 dispatch 没有
的）→ assert log error 不 raise。class flag 隔离（每 test 重置保证 _startup_selfcheck 重跑）。
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from scheduler.executors import TaskExecutor, _manager


def _fake_task(task_type: str) -> SimpleNamespace:
    """轻量替身——_startup_selfcheck 只读 .task_type 字段。"""
    return SimpleNamespace(task_type=task_type)


@pytest.fixture(autouse=True)
def _reset_selfcheck_flag():
    """每个 test 重置 class flag（保证 _startup_selfcheck 重跑，不受前序 test 影响）。"""
    TaskExecutor._selfcheck_done = False
    yield
    TaskExecutor._selfcheck_done = False


class TestStartupSelfcheck:
    """S218 #4：startup drift self-check——stale dispatch dict 立即日志可见。"""

    def test_missing_task_type_logs_error_no_raise(self, monkeypatch, caplog):
        # seeded 含 dispatch 没有的 'ghost_task_type' → log error，不 raise
        monkeypatch.setattr(
            _manager,
            "list_tasks",
            lambda: [_fake_task("daily_report"), _fake_task("ghost_task_type")],
        )
        with caplog.at_level(logging.ERROR, logger="vibe-research"):
            TaskExecutor()  # 不 raise——stale dict 不应崩 startup

        assert any(
            "ghost_task_type" in m and "seeded but not in dispatch" in m
            for m in caplog.messages
        ), f"应 log error 标 ghost_task_type missing，got: {caplog.messages}"

    def test_all_present_logs_info_zero_missing(self, monkeypatch, caplog):
        monkeypatch.setattr(
            _manager,
            "list_tasks",
            lambda: [_fake_task("daily_report"), _fake_task("keypoint_notify")],
        )
        with caplog.at_level(logging.INFO, logger="vibe-research"):
            TaskExecutor()

        assert any("0 missing" in m for m in caplog.messages), (
            f"应 log info 汇总 0 missing，got: {caplog.messages}"
        )
        assert not any(
            "seeded but not in dispatch" in m for m in caplog.messages
        ), "全在 dispatch 不应 log error"

    def test_db_unavailable_logs_warning_no_raise(self, monkeypatch, caplog):
        """DB 锁/未初始化 → log warning 跳过，不 raise（防 startup crash）。"""

        def _boom():
            raise RuntimeError("db locked")

        monkeypatch.setattr(_manager, "list_tasks", _boom)
        with caplog.at_level(logging.WARNING, logger="vibe-research"):
            TaskExecutor()  # 不 raise

        assert any(
            "读取失败" in m or "跳过" in m for m in caplog.messages
        ), f"应 log warning 标 DB 不可用跳过，got: {caplog.messages}"

    def test_selfcheck_runs_once_per_process(self, monkeypatch):
        """class flag：同一 process 第二次 instantiate 不再查 DB（防 API GET 噪声 + DB hammer）。"""
        calls = {"n": 0}

        def _stub():
            calls["n"] += 1
            return []

        monkeypatch.setattr(_manager, "list_tasks", _stub)
        TaskExecutor()
        TaskExecutor()
        assert calls["n"] == 1, "self-check 应只跑一次 per process（class flag）"
