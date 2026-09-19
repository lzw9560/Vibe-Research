# -*- coding: utf-8 -*-
"""S066 §9 游资席位周更聚合 executor 通电 test（#13 follow-up，数据 prep 非 spec S220）。

验证三件事（team-lead 任务：mock update_hot_money_seats + assert executor 调它 + cron fire 接线）：
1. executor 调 strategies.hot_money_seats.update_hot_money_seats（mock 后断言调用 + days 透传）
2. 返回结构三态正确（ok / degraded / error）+ payload.days 默认与覆盖
3. cron fire 接线：seed.py 含 task_type + cron 周一 06:00 + dispatch dict 含 key + wrapper 委托

不联网：mock update_hot_money_seats（真实 em 取数 + 聚合逻辑已在 test_hot_money_seats.py 覆盖，
本测试只验通电接线，不重复测聚合）。AAA + 描述性命名。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from scheduler.executors import TaskExecutor  # noqa: E402
from scheduler.executors.hot_money_seats import hot_money_seats_update  # noqa: E402


# ── cron fire 接线：seed + dispatch + wrapper 委托 ────────────────────────

class TestHotMoneySeatsUpdateRegistration:
    """#13 通电接线：seed task + executor dispatch + wrapper delegation。"""

    @pytest.fixture(autouse=True)
    def _skip_selfcheck(self):
        """跳过 _startup_selfcheck DB 读（registration 测只验 dispatch dict，hermetic）。

        selfcheck 读 scheduled_tasks 表 seeded task_type 核 dispatch dict——本测只验 dispatch dict
        含 key + wrapper 委托，不验 selfcheck（selfcheck 在 test_startup_selfcheck.py 独立测）。
        设 class flag True 跳过，yield 后复位 False 防跨测污染。
        """
        TaskExecutor._selfcheck_done = True
        yield
        TaskExecutor._selfcheck_done = False

    def test_seed_has_hot_money_seats_update_task(self):
        """seed.py 源码含 task_type='hot_money_seats_update' + cron 周一 06:00 + payload days=60。"""
        seed_path = backend_dir / "scheduler" / "seed.py"
        src = seed_path.read_text(encoding="utf-8")
        assert 'task_type="hot_money_seats_update"' in src, \
            "seed.py 应含 task_type='hot_money_seats_update'"
        assert '"days": 60' in src, "payload 应含 days=60（60 日聚合窗口）"
        assert "0 6 * * 1" in src, "cron 应为 0 6 * * 1（每周一 06:00 周更）"

    def test_executor_hot_money_seats_update_registered(self):
        """TaskExecutor._executors dict 含 'hot_money_seats_update' key + callable（不落'未知任务类型'）。"""
        ex = TaskExecutor()
        assert "hot_money_seats_update" in ex._executors, \
            "_executors 应含 hot_money_seats_update（否则 cron fire 落 '未知任务类型'）"
        assert callable(ex._executors["hot_money_seats_update"])

    def test_execute_delegates_to_update_hot_money_seats(self, monkeypatch):
        """_execute_hot_money_seats_update 委托 strategies.hot_money_seats.update_hot_money_seats + 透传 days。"""
        captured: dict = {}

        def fake_update(days: int) -> int:
            captured["days"] = days
            return 7

        monkeypatch.setattr("strategies.hot_money_seats.update_hot_money_seats", fake_update)
        ex = TaskExecutor()
        result = ex._execute_hot_money_seats_update({"days": 60})

        assert result["status"] == "ok", f"mock 返 7 该 ok，得 {result['status']}"
        assert result["n_seats"] == 7
        assert captured["days"] == 60, "days 该透传给 update_hot_money_seats"


# ── executor 三态 + payload 透传 ──────────────────────────────────────────

def test_calls_update_hot_money_seats_and_returns_ok():
    """mock update_hot_money_seats 返 42 → status=ok + n_seats=42 + 调一次 + days 透传。"""
    with patch("strategies.hot_money_seats.update_hot_money_seats", return_value=42) as mock_fn:
        result = hot_money_seats_update({"days": 60})

    assert result["status"] == "ok"
    assert result["n_seats"] == 42
    assert result["days"] == 60
    mock_fn.assert_called_once_with(60)


def test_degraded_when_zero_seats():
    """update_hot_money_seats 返 0（fetch_billboard_dates 空返——em 端点空/熔断）→ status=degraded。"""
    with patch("strategies.hot_money_seats.update_hot_money_seats", return_value=0):
        result = hot_money_seats_update({})

    assert result["status"] == "degraded", "返 0 该 degraded（em 无可用数据，画像未变）"
    assert result["n_seats"] == 0
    assert result["days"] == 60  # payload 默认


def test_error_when_update_raises():
    """update_hot_money_seats raise → status=error（不 crash scheduled task，error 透传）。"""
    with patch("strategies.hot_money_seats.update_hot_money_seats",
               side_effect=RuntimeError("em 断连")):
        result = hot_money_seats_update({"days": 30})

    assert result["status"] == "error"
    assert result["n_seats"] == 0
    assert result["days"] == 30
    assert "em 断连" in result["error"]


def test_days_payload_override():
    """payload.days 透传（默认 60，传 90 → 调 update_hot_money_seats(90)）。"""
    with patch("strategies.hot_money_seats.update_hot_money_seats", return_value=10) as mock_fn:
        result = hot_money_seats_update({"days": 90})

    assert result["status"] == "ok"
    assert result["days"] == 90
    mock_fn.assert_called_once_with(90)
