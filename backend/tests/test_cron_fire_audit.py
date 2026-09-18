# -*- coding: utf-8 -*-
"""S218 #10 cron-fire audit 测试（TDD - RED → GREEN）。

验收（spec: 把 "wired" 变 "observable wired"）：
- log_fire_receipt 写 jsonl（每行 {ts, task_name, status, output_path, n_rows, duration_ms}）
- log_fire_receipt append 多行（不覆盖），返的 receipt == 落盘行
- log_fire_receipt 接受非 dict result（status/output/n_rows=None，不抛）
- log_fire_receipt 3-arg 调用（spec signature）→ duration_ms=None
- cron_audit：last_run_at=null 且无 receipt → missed（reality-check 核心场景）
- cron_audit：今日有 receipt → 不 missed（executor 真跑了），即使 last_run_at=null
- cron_audit：last_run_at recent → 不 missed（scheduler 触发了），即使无 receipt
- cron_audit：last_run_at stale（> stale_hours）→ missed
- cron_audit：payload.task_types 限定范围；enabled=False 不算 expected
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from scheduler.cron_fire_audit import log_fire_receipt
from vr_paths import BEIJING_TZ


# ── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_fire_log(tmp_path, monkeypatch):
    """隔离 cron_fire.log 到 tmp_path（防跨测试 receipt 污染）。

    resolve_data_dir() 读 VR_DATA_DIR env——setenv 到 tmp_path 后 log_fire_receipt
    + _read_receipts + cron_audit 全走 tmp_path/cron_fire.log（与 conftest 全局
    _TEST_DATA_DIR 隔离，s218 系列测写的 receipt 不污染本测）。
    """
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def isolated_scheduler_db(tmp_path, monkeypatch):
    """隔离 scheduled_tasks DB 到 tmp_path（cron_audit 读 last_run_at 不污染真实库）。

    镜像 conftest.isolated_market_db：patch scheduler.db._DB_PATH + 建表。_manager 单例
    的方法读模块级 _DB_PATH global（patch 生效），故 create_task/update_task_status 落 tmp。
    """
    from scheduler.db import _ensure_tables, _manager

    db_path = tmp_path / "market_data.db"
    monkeypatch.setattr("scheduler.db._DB_PATH", str(db_path))
    _ensure_tables()
    yield _manager


def _create_task(manager, name, task_type, last_run_at=None, enabled=True):
    """建一个 scheduled_task，可选设 last_run_at（经 update_task_status）。"""
    from scheduler.models import ScheduledTask

    t = manager.create_task(ScheduledTask(
        name=name,
        task_type=task_type,
        cron_expr="0 0 * * *",
        enabled=enabled,
    ))
    if last_run_at is not None:
        manager.update_task_status(t.id, "success", last_run_at)
    return t


# ── test: log_fire_receipt 写 jsonl ───────────────────────────────────────

def test_log_fire_receipt_writes_jsonl_line(isolated_fire_log, tmp_path):
    """log_fire_receipt 写 1 行 jsonl，字段齐全；返回的 receipt == 落盘行。"""
    result = {"status": "ok", "report_path": "/tmp/x.json", "signals": 3}
    receipt = log_fire_receipt("daily_report", {"notify": True}, result, duration_ms=12.3)

    log_file = tmp_path / "cron_fire.log"
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    line = json.loads(lines[0])
    assert line["task_name"] == "daily_report"
    assert line["status"] == "ok"
    assert line["output_path"] == "/tmp/x.json"
    assert line["n_rows"] == 3
    assert line["duration_ms"] == 12.3
    assert "ts" in line and line["ts"]

    # 返回的 receipt 与落盘内容一致
    assert receipt == line


def test_log_fire_receipt_appends_multiple(isolated_fire_log, tmp_path):
    """多次 fire → 多行 append（不覆盖）。"""
    log_fire_receipt("daily_report", {}, {"status": "ok", "signals": 1})
    log_fire_receipt("weekly_review", {}, {"status": "ok", "record_path": "/w.json"})

    lines = (tmp_path / "cron_fire.log").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["task_name"] == "daily_report"
    assert json.loads(lines[1])["task_name"] == "weekly_review"
    assert json.loads(lines[1])["output_path"] == "/w.json"


def test_log_fire_receipt_handles_non_dict_result(isolated_fire_log, tmp_path):
    """executor 异常返非 dict（如 None）→ receipt 仍写（status/output/n_rows=None）。"""
    receipt = log_fire_receipt("x", {}, None)

    line = json.loads((tmp_path / "cron_fire.log").read_text(encoding="utf-8").strip())
    assert line["status"] is None
    assert line["output_path"] is None
    assert line["n_rows"] is None
    assert receipt["status"] is None


def test_log_fire_receipt_no_duration(isolated_fire_log, tmp_path):
    """3-arg 调用（spec signature）→ duration_ms=None（未测耗时）。"""
    log_fire_receipt("daily_report", {}, {"status": "ok"})

    line = json.loads((tmp_path / "cron_fire.log").read_text(encoding="utf-8").strip())
    assert line["duration_ms"] is None


# ── test: cron_audit 数 missed ─────────────────────────────────────────────

def test_cron_audit_misses_null_last_run_at(isolated_fire_log, isolated_scheduler_db):
    """last_run_at=null 且无 receipt → missed（reality-check 核心场景：cron 从未触发）。"""
    _create_task(isolated_scheduler_db, "daily_report", "daily_report", last_run_at=None)
    _create_task(isolated_scheduler_db, "keypoint_notify_entry", "keypoint_notify", last_run_at=None)

    from scheduler.executors.audit import cron_audit

    out = cron_audit({})

    assert out["status"] == "ok"
    assert out["n_expected"] == 2
    assert out["n_missed"] == 2
    assert out["n_fired"] == 0
    assert set(out["missed"]) == {"daily_report", "keypoint_notify_entry"}


def test_cron_audit_receipt_today_not_missed(isolated_fire_log, isolated_scheduler_db):
    """今日有 receipt → 不 missed（executor 真跑了），即使 last_run_at=null。"""
    _create_task(isolated_scheduler_db, "daily_report", "daily_report", last_run_at=None)
    log_fire_receipt("daily_report", {}, {"status": "ok", "signals": 2})

    from scheduler.executors.audit import cron_audit

    out = cron_audit({})

    assert out["n_expected"] == 1
    assert out["n_missed"] == 0
    assert out["n_fired"] == 1
    assert "daily_report" in out["fired_today"]
    assert out["missed"] == []


def test_cron_audit_recent_last_run_at_not_missed(isolated_fire_log, isolated_scheduler_db):
    """last_run_at recent（≤ stale_hours）→ 不 missed（scheduler 触发了），即使无 receipt。"""
    recent = datetime.now(BEIJING_TZ).isoformat()
    _create_task(isolated_scheduler_db, "daily_report", "daily_report", last_run_at=recent)

    from scheduler.executors.audit import cron_audit

    out = cron_audit({"stale_hours": 36})

    assert out["n_missed"] == 0
    assert out["n_fired"] == 1


def test_cron_audit_stale_last_run_at_missed(isolated_fire_log, isolated_scheduler_db):
    """last_run_at > stale_hours → missed（太久没跑）。"""
    stale = (datetime.now(BEIJING_TZ) - timedelta(hours=48)).isoformat()
    _create_task(isolated_scheduler_db, "daily_report", "daily_report", last_run_at=stale)

    from scheduler.executors.audit import cron_audit

    out = cron_audit({"stale_hours": 36})

    assert out["n_missed"] == 1
    assert out["missed"] == ["daily_report"]


def test_cron_audit_respects_audited_task_types(isolated_fire_log, isolated_scheduler_db):
    """payload.task_types 限定 audit 范围（只看指定 task_type）。"""
    _create_task(isolated_scheduler_db, "daily_report", "daily_report", last_run_at=None)
    _create_task(isolated_scheduler_db, "fund_accumulation", "fund_accumulation", last_run_at=None)

    from scheduler.executors.audit import cron_audit

    out = cron_audit({"task_types": ["daily_report"]})

    assert out["n_expected"] == 1  # 只看 daily_report
    assert out["n_missed"] == 1
    assert out["missed"] == ["daily_report"]


def test_cron_audit_disabled_tasks_not_expected(isolated_fire_log, isolated_scheduler_db):
    """enabled=False 的 task 不算 expected（disabled 不该 fire）。"""
    _create_task(isolated_scheduler_db, "disabled_cron", "daily_report",
                 last_run_at=None, enabled=False)

    from scheduler.executors.audit import cron_audit

    out = cron_audit({})

    assert out["n_expected"] == 0  # disabled 不算
    assert out["n_missed"] == 0
