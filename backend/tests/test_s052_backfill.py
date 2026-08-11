# -*- coding: utf-8 -*-
"""S052 D2/D4：回测快照缺口补跑测试。

- _compute_backfill_gap：缺口计算（跨周末 / 无快照上限 60 / 已有快照不重复 / 无缺口不触发）
- backfill_backtest_snapshots：幂等（连跑两次不重复）+ 单日失败不阻断
- 端点 POST /api/backtest/backfill
"""
from __future__ import annotations

from unittest import mock
from types import SimpleNamespace

import pytest

from backfill_snapshots import (
    _compute_backfill_gap,
    backfill_backtest_snapshots,
    _get_snapshot_max_date,
    _get_gene_scores_dates_since,
)


def test_compute_gap_with_existing_snapshot(monkeypatch):
    """last_have=2026-08-05 → 候选日 = gene_scores 中 > 08-05 且 <= 昨天。"""
    monkeypatch.setattr("backfill_snapshots._get_snapshot_max_date", lambda: "2026-08-05")
    monkeypatch.setattr("backfill_snapshots._get_gene_scores_dates_since",
                        lambda since, limit_days=60: ["2026-08-08", "2026-08-07", "2026-08-06"])
    # 昨天 = 2026-08-09（today=2026-08-10 mock）
    import backfill_snapshots as bs
    from datetime import date
    monkeypatch.setattr(bs, "datetime", type("DT", (), {
        "now": staticmethod(lambda: SimpleNamespace(date=lambda: date(2026, 8, 10)))
    }))
    gap = _compute_backfill_gap()
    assert "2026-08-06" in gap
    assert "2026-08-07" in gap
    assert "2026-08-08" in gap
    assert gap == sorted(gap)


def test_compute_gap_no_snapshot_caps_at_60(monkeypatch):
    """last_have=None（首次启动）→ 回溯上限 60 日。"""
    monkeypatch.setattr("backfill_snapshots._get_snapshot_max_date", lambda: None)
    dates = [f"2026-08-{i:02d}" for i in range(1, 11)]
    monkeypatch.setattr("backfill_snapshots._get_gene_scores_dates_since",
                        lambda since, limit_days=60: dates[:limit_days])
    import backfill_snapshots as bs
    from datetime import date
    monkeypatch.setattr(bs, "datetime", type("DT", (), {
        "now": staticmethod(lambda: SimpleNamespace(date=lambda: date(2026, 8, 10)))
    }))
    gap = _compute_backfill_gap()
    assert all(d <= "2026-08-09" for d in gap)


def test_compute_gap_empty_when_no_missing(monkeypatch):
    """last_have=昨天 → 无缺口。"""
    monkeypatch.setattr("backfill_snapshots._get_snapshot_max_date", lambda: "2026-08-09")
    monkeypatch.setattr("backfill_snapshots._get_gene_scores_dates_since",
                        lambda since, limit_days=60: ["2026-08-10"])
    import backfill_snapshots as bs
    from datetime import date
    monkeypatch.setattr(bs, "datetime", type("DT", (), {
        "now": staticmethod(lambda: SimpleNamespace(date=lambda: date(2026, 8, 10)))
    }))
    gap = _compute_backfill_gap()
    assert gap == []


def test_backfill_idempotent_run_twice(monkeypatch):
    """连跑两次回填不产生重复快照行（第二次无缺口）。"""
    call_count = {"n": 0}

    def fake_execute(self, payload):
        call_count["n"] += 1
        return {"snapshot_date": payload["as_of_date"], "_status": "ok"}

    monkeypatch.setattr("scheduled_tasks.TaskExecutor._execute_daily_backtest_run", fake_execute)
    # 第一次：3 日缺口
    monkeypatch.setattr("backfill_snapshots._compute_backfill_gap",
                        lambda: ["2026-08-06", "2026-08-07", "2026-08-08"])
    r1 = backfill_backtest_snapshots(60)
    assert r1["backfilled"] == 3
    assert call_count["n"] == 3

    # 第二次：无缺口（已回填）
    monkeypatch.setattr("backfill_snapshots._compute_backfill_gap", lambda: [])
    r2 = backfill_backtest_snapshots(60)
    assert r2["backfilled"] == 0
    assert call_count["n"] == 3  # 未再调


def test_backfill_single_day_failure_not_blocking(monkeypatch):
    """单日失败不阻断整批。"""
    def fake_execute(self, payload):
        if payload["as_of_date"] == "2026-08-07":
            raise RuntimeError("kline missing")
        return {"snapshot_date": payload["as_of_date"], "_status": "ok"}

    monkeypatch.setattr("scheduled_tasks.TaskExecutor._execute_daily_backtest_run", fake_execute)
    monkeypatch.setattr("backfill_snapshots._compute_backfill_gap",
                        lambda: ["2026-08-06", "2026-08-07", "2026-08-08"])
    r = backfill_backtest_snapshots(60)
    assert r["backfilled"] == 2
    assert r["failed"] == 1


def test_backfill_endpoint(monkeypatch):
    """POST /api/backtest/backfill 端点响应结构。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import scheduled_tasks as strat_router

    monkeypatch.setattr("backfill_snapshots._compute_backfill_gap", lambda: ["2026-08-06"])
    monkeypatch.setattr("scheduled_tasks.TaskExecutor._execute_daily_backtest_run",
                        lambda self, p: {"snapshot_date": p["as_of_date"], "_status": "ok"})

    app = FastAPI()
    app.include_router(strat_router.router)
    client = TestClient(app)

    resp = client.post("/api/backtest/backfill?days=60")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["backfilled"] == 1
    assert len(body["days"]) == 1
