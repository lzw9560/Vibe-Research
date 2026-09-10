# -*- coding: utf-8 -*-
"""S175 T4 — scheduler trade_journal_daily executor 接线测试（BREAK-0 fix）。

验证：① TaskExecutor._executors 含 trade_journal_daily dispatch；
② trade_journal_daily(payload) 调 JournalRecorder.settle_pending_breakout +
run_daily(arms=['floor','breakout']) + update_floor_mtm 三步 + 返 {settled_pending,
arms, floor_mtm}。
mock orchestrator，不读真 cache/不联网。
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def test_trade_journal_daily_in_dispatch_dict():
    """TaskExecutor._executors 含 trade_journal_daily → _execute_trade_journal_daily。"""
    from scheduler.executors import TaskExecutor
    executor = TaskExecutor()
    assert "trade_journal_daily" in executor._executors
    assert callable(executor._executors["trade_journal_daily"])


def test_trade_journal_daily_calls_orchestrator_three_steps(tmp_path, monkeypatch):
    """trade_journal_daily 调 settle_pending_breakout + run_daily + update_floor_mtm。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))

    mock_recorder = MagicMock()
    mock_recorder.settle_pending_breakout.return_value = {"n_pending": 0, "n_settled": 0}
    mock_recorder.run_daily.return_value = {
        "floor": {"n_candidates": 1, "n_realized": 0},
        "breakout": {"n_candidates": 5, "n_realized": 2},
    }
    mock_recorder.update_floor_mtm.return_value = 1

    with patch("strategies.journal_recorder.JournalRecorder", return_value=mock_recorder):
        from scheduler.executors.journal import trade_journal_daily
        result = trade_journal_daily({})

    # 三步全调
    mock_recorder.settle_pending_breakout.assert_called_once()
    mock_recorder.run_daily.assert_called_once()
    mock_recorder.update_floor_mtm.assert_called_once()
    # run_daily 用 arms=['floor','breakout','trend']（S181 trend 臂进 cron paper_track，2026-09-11 用户决策）
    _, kwargs = mock_recorder.run_daily.call_args
    assert kwargs.get("arms") == ["floor", "breakout", "trend"]
    # 返结构
    assert "settled_pending" in result
    assert "arms" in result
    assert "floor_mtm" in result
    assert result["arms"]["breakout"]["n_realized"] == 2


def test_trade_journal_daily_target_date_passthrough(tmp_path, monkeypatch):
    """payload.target_date 透传 run_daily（None→run_daily default prev_trading_date_str）。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    mock_recorder = MagicMock()
    mock_recorder.settle_pending_breakout.return_value = {"n_pending": 0, "n_settled": 0}
    mock_recorder.run_daily.return_value = {}
    mock_recorder.update_floor_mtm.return_value = 0

    with patch("strategies.journal_recorder.JournalRecorder", return_value=mock_recorder):
        from scheduler.executors.journal import trade_journal_daily
        trade_journal_daily({"target_date": "2026-09-01"})

    _, kwargs = mock_recorder.run_daily.call_args
    assert kwargs.get("target_date") == "2026-09-01"  # 透传


def test_execute_trade_journal_daily_wrapper_delegates(tmp_path, monkeypatch):
    """TaskExecutor._execute_trade_journal_daily thin wrapper 委托 domain 函数。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    mock_recorder = MagicMock()
    mock_recorder.settle_pending_breakout.return_value = {"n_pending": 0, "n_settled": 0}
    mock_recorder.run_daily.return_value = {}
    mock_recorder.update_floor_mtm.return_value = 0

    with patch("strategies.journal_recorder.JournalRecorder", return_value=mock_recorder):
        from scheduler.executors import TaskExecutor
        result = TaskExecutor()._execute_trade_journal_daily({})

    assert "settled_pending" in result
    mock_recorder.run_daily.assert_called_once()
