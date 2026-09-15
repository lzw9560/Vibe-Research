# -*- coding: utf-8 -*-
"""S204 T9: tracking_pool_repo test（TDD）。

验证两表幂等建表 + insert-if-absent + upsert snapshot + get_active_tracks +
tracking label 词表分离 workflow_state enum（R5/R6 对抗审修正）。tmp DB 隔离。
"""
from __future__ import annotations

import pytest

import tracking_pool_repo as tpr
from tracking_pool_repo import (
    TRACKING_LABELS,
    TrackingRecord,
    IndicatorSnapshot,
)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """tmp DB 隔离（monkeypatch _DB_PATH + re-_ensure_tables）。"""
    db = str(tmp_path / "test_tracking.db")
    monkeypatch.setattr(tpr, "_DB_PATH", db)
    tpr._ensure_tables()
    return db


def test_table_created_idempotent(tmp_db):
    """_ensure_tables 幂等（跑两次不报错）。"""
    tpr._ensure_tables()  # 第二次
    tpr._ensure_tables()  # 第三次


def test_insert_tracking_record(tmp_db):
    """insert + 字段正确。"""
    assert tpr.insert_tracking_record("600000", "2026-01-01", "early_admission", {"sector_rank": 2}) is True
    tracks = tpr.get_active_tracks("admit")  # 默认 current_status='admit' (insert 时)
    assert len(tracks) == 1
    assert tracks[0].code == "600000"
    assert tracks[0].first_admit_date == "2026-01-01"
    assert tracks[0].admit_signal == "early_admission"
    assert tracks[0].current_status == "admit"


def test_insert_if_absent_idempotent(tmp_db):
    """重复 insert 同 (code, first_admit_date) → 忽略，1 行（ON CONFLICT DO NOTHING）。"""
    tpr.insert_tracking_record("600000", "2026-01-01")
    assert tpr.insert_tracking_record("600000", "2026-01-01") is False  # 已存在，不插入
    tracks = tpr.get_active_tracks("admit")
    assert len(tracks) == 1


def test_upsert_indicator_snapshot(tmp_db):
    """upsert（同 code,trade_date 插两次 → 1 行 INSERT OR REPLACE，后覆前）。"""
    tpr.upsert_indicator_snapshot("600000", "2026-01-01", {"sector_rank": 2}, "early_admit")
    tpr.upsert_indicator_snapshot("600000", "2026-01-01", {"sector_rank": 5}, "escalation")
    snaps = tpr.get_snapshots_for("600000")
    assert len(snaps) == 1  # UNIQUE → 1 行
    assert snaps[0].snapshot_source == "escalation"  # 后覆前


def test_get_active_tracks_filters_status(tmp_db):
    """get_active_tracks 按 current_status 过滤。"""
    tpr.insert_tracking_record("600000", "2026-01-01")
    tpr.insert_tracking_record("600001", "2026-01-01")
    tpr.update_tracking_status("600001", "2026-01-01", "tracking")
    active = tpr.get_active_tracks("tracking")  # 只 'tracking'
    assert len(active) == 1
    assert active[0].code == "600001"


def test_update_tracking_status(tmp_db):
    """update current_status + tracking_age_days。"""
    tpr.insert_tracking_record("600000", "2026-01-01")
    tpr.update_tracking_status("600000", "2026-01-01", "decayed", tracking_age_days=5)
    tracks = tpr.get_active_tracks("decayed")
    assert len(tracks) == 1
    assert tracks[0].current_status == "decayed"
    assert tracks[0].tracking_age_days == 5


def test_get_snapshots_ordered(tmp_db):
    """snapshots 按 date asc 返回。"""
    tpr.upsert_indicator_snapshot("600000", "2026-01-03", {"d": 3})
    tpr.upsert_indicator_snapshot("600000", "2026-01-01", {"d": 1})
    tpr.upsert_indicator_snapshot("600000", "2026-01-02", {"d": 2})
    snaps = tpr.get_snapshots_for("600000")
    assert [s.trade_date for s in snaps] == ["2026-01-01", "2026-01-02", "2026-01-03"]


def test_get_snapshots_up_to_date(tmp_db):
    """snapshots up_to_date 过滤。"""
    for d in ["2026-01-01", "2026-01-02", "2026-01-03"]:
        tpr.upsert_indicator_snapshot("600000", d, {"d": d})
    snaps = tpr.get_snapshots_for("600000", up_to_date="2026-01-02")
    assert [s.trade_date for s in snaps] == ["2026-01-01", "2026-01-02"]


def test_tracking_record_immutable(tmp_db):
    """TrackingRecord frozen dataclass。"""
    tpr.insert_tracking_record("600000", "2026-01-01")
    tracks = tpr.get_active_tracks("admit")
    with pytest.raises(Exception):
        tracks[0].code = "other"  # frozen


def test_tracking_labels_not_in_workflow_enum():
    """TRACKING_LABELS 词表分离 workflow_state.WorkflowStatus enum（R5/R6 修正）。"""
    from workflow_state_machine import WorkflowStatus
    workflow_enum_values = {s.value for s in WorkflowStatus}
    assert TRACKING_LABELS.isdisjoint(workflow_enum_values), (
        f"tracking labels {TRACKING_LABELS} 与 workflow_state enum {workflow_enum_values} 须分离"
    )


def test_tracking_labels_values():
    """TRACKING_LABELS 含 admit/tracking/decayed/promoted。"""
    assert TRACKING_LABELS == frozenset({"admit", "tracking", "decayed", "promoted"})
