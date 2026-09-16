# -*- coding: utf-8 -*-
"""S204 T11+T12: escalation_engine test（TDD）。

验证 maturity promote（candidate→watching）+ decay（WATCHING→FILTERED 非→CANDIDATE）+
R7 ensure_candidate 联动 + 决策#11 不 auto-fire holding。fake workflow_repo + tmp DB 隔离。
"""
from __future__ import annotations

import json

import pytest

import escalation_engine as ee
import tracking_pool_repo as tpr


class FakeWorkflowRepo:
    """fake workflow_state_repo（记录调用，隔离真实 DB）。"""

    def __init__(self, existing_states: dict | None = None):
        self.states = existing_states or {}  # {(code, date): status}
        self.calls: list[tuple] = []  # 记录 ensure_candidate/transition 调用

    def get_state(self, code, trade_date):
        return self.states.get((code, trade_date))

    def ensure_candidate(self, code, name, trade_date, reason=""):
        self.calls.append(("ensure_candidate", code, trade_date, reason))
        self.states[(code, trade_date)] = "candidate"
        return True

    def transition(self, code, trade_date, target, reason="", **kwargs):
        self.calls.append(("transition", code, trade_date, target, reason))
        self.states[(code, trade_date)] = target
        return (True, "ok")


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(tpr, "_DB_PATH", str(tmp_path / "test_escalation.db"))
    tpr._ensure_tables()
    return tpr


def _insert_track(code, admit_date, status="tracking", age=3, admit_gene=50, sector_rank=2):
    """插入 tracking 记录 + 几个 snapshots。"""
    tpr.insert_tracking_record(code, admit_date, admit_signal="early_admission", indicators={"gene_score": admit_gene, "sector_rank": sector_rank})
    tpr.update_tracking_status(code, admit_date, status, tracking_age_days=age)


def _add_snapshots(code, dates, gene_scores, sector_ranks):
    """插 snapshots（gene_score 改善 + sector_rank）。"""
    for d, gs, sr in zip(dates, gene_scores, sector_ranks):
        tpr.upsert_indicator_snapshot(code, d, {"gene_score": gs, "sector_rank": sr}, "escalation")


def test_maturity_promote(tmp_db):
    """tracking track（age≥3 + gene+25% + sector_rank≤5）→ promote candidate→watching。"""
    _insert_track("600000", "2026-01-01", status="tracking", age=3, admit_gene=50, sector_rank=5)
    _add_snapshots("600000", ["2026-01-02", "2026-01-03", "2026-01-04"], [60, 65, 62.5], [4, 3, 2])  # gene +25%
    fake = FakeWorkflowRepo()
    promoted = ee.escalate("2026-01-04", workflow_repo=fake)
    assert "600000" in promoted
    # transition 'watching' 调用
    assert ("transition", "600000", "2026-01-04", "watching", "maturity_promote") in fake.calls
    # tracking_pool → 'promoted'
    assert len(tpr.get_active_tracks("promoted")) == 1


def test_maturity_not_met_age(tmp_db):
    """age<3 → 不 promote（increment 后仍<3）。age=1 → escalate 增 1 → age=2 <3 不 promote。"""
    _insert_track("600000", "2026-01-01", age=1, admit_gene=50, sector_rank=2)
    _add_snapshots("600000", ["2026-01-02"], [65], [2])  # gene+30% 但 age 增后=2 仍<3
    fake = FakeWorkflowRepo()
    promoted = ee.escalate("2026-01-02", workflow_repo=fake)
    assert promoted == []
    # 不调 transition watching
    assert not any(c[3] == "watching" for c in fake.calls if c[0] == "transition")


def test_escalate_increments_tracking_age(tmp_db):
    """escalate() 每日增 tracking_age_days（CRITICAL bug fix 2026-09-16：默认 0 不增 → age_ok 永远 False）。

    age=0 → escalate 3 次（每日）→ age=3 → 满足 min_tracking_age → 若 gene/sector 也 met 则 promote。
    """
    _insert_track("600000", "2026-01-01", status="tracking", age=0, admit_gene=50, sector_rank=2)
    _add_snapshots("600000", ["2026-01-02"], [62.5], [2])  # gene +25% met, sector<=5 met
    fake = FakeWorkflowRepo()
    # day 1: age 0→1, <3, no promote
    ee.escalate("2026-01-02", workflow_repo=fake)
    assert not any(c[3] == "watching" for c in fake.calls if c[0] == "transition")
    assert tpr.get_active_tracks("tracking")[0].tracking_age_days == 1
    # day 2: age 1→2, <3, no promote
    ee.escalate("2026-01-03", workflow_repo=fake)
    assert tpr.get_active_tracks("tracking")[0].tracking_age_days == 2
    # day 3: age 2→3, >=3, gene+25% met, sector<=5 → promote
    ee.escalate("2026-01-04", workflow_repo=fake)
    assert any(c[1] == "600000" and c[3] == "watching" for c in fake.calls if c[0] == "transition")
    assert len(tpr.get_active_tracks("promoted")) == 1


def test_maturity_not_met_gene(tmp_db):
    """gene 改善<20% → 不 promote。"""
    _insert_track("600000", "2026-01-01", age=3, admit_gene=50, sector_rank=2)
    _add_snapshots("600000", ["2026-01-02", "2026-01-03", "2026-01-04"], [55, 57, 58], [2, 2, 2])  # gene+16% <20%
    fake = FakeWorkflowRepo()
    assert ee.escalate("2026-01-04", workflow_repo=fake) == []


def test_maturity_not_met_sector_rank(tmp_db):
    """sector_rank>5 → 不 promote。"""
    _insert_track("600000", "2026-01-01", age=3, admit_gene=50, sector_rank=10)
    _add_snapshots("600000", ["2026-01-02", "2026-01-03", "2026-01-04"], [65, 70, 75], [8, 7, 6])  # gene+50% 但 rank>5
    fake = FakeWorkflowRepo()
    assert ee.escalate("2026-01-04", workflow_repo=fake) == []


def test_ensure_candidate_linkage(tmp_db):
    """pre-涨停 track 不在 workflow_state → ensure_candidate 先调再 transition（R7）。"""
    _insert_track("600000", "2026-01-01", age=3, admit_gene=50, sector_rank=2)
    _add_snapshots("600000", ["2026-01-04"], [65], [2])
    fake = FakeWorkflowRepo(existing_states={})  # 无 (code, date)
    ee.escalate("2026-01-04", workflow_repo=fake)
    # ensure_candidate 先于 transition
    ensure_calls = [c for c in fake.calls if c[0] == "ensure_candidate"]
    trans_calls = [c for c in fake.calls if c[0] == "transition"]
    assert ensure_calls  # 调了 ensure_candidate
    assert trans_calls  # 调了 transition
    # ensure_candidate 在 transition 前（calls 顺序）
    assert fake.calls.index(ensure_calls[0]) < fake.calls.index(trans_calls[0])


def test_ensure_skipped_if_state_exists(tmp_db):
    """workflow_state 已有 (code, date) → 不调 ensure_candidate。"""
    _insert_track("600000", "2026-01-01", age=3, admit_gene=50, sector_rank=2)
    _add_snapshots("600000", ["2026-01-04"], [65], [2])
    fake = FakeWorkflowRepo(existing_states={("600000", "2026-01-04"): "candidate"})  # 已存在
    ee.escalate("2026-01-04", workflow_repo=fake)
    assert not any(c[0] == "ensure_candidate" for c in fake.calls)  # 不调 ensure


def test_decay_promoted_5_days_no_improvement(tmp_db):
    """promoted track（watching）5 日 gene 下降 → decay WATCHING→FILTERED（T12）。"""
    _insert_track("600000", "2026-01-01", status="promoted", age=6, admit_gene=50, sector_rank=2)
    _add_snapshots("600000", ["2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"], [45, 40, 38, 35, 30], [2, 2, 2, 2, 2])  # gene 下降
    fake = FakeWorkflowRepo(existing_states={("600000", "2026-01-06"): "watching"})
    ee.escalate("2026-01-06", workflow_repo=fake)
    # transition 'filtered' reason='decayed'
    assert ("transition", "600000", "2026-01-06", "filtered", "decayed") in fake.calls
    # tracking_pool → 'decayed'
    assert len(tpr.get_active_tracks("decayed")) == 1


def test_decay_uses_filtered_not_candidate(tmp_db):
    """decay → WATCHING→FILTERED（非→CANDIDATE，防振荡 loop）。"""
    _insert_track("600000", "2026-01-01", status="promoted", age=6, admit_gene=50, sector_rank=2)
    _add_snapshots("600000", ["2026-01-06"], [30], [2])  # gene 下降
    fake = FakeWorkflowRepo(existing_states={("600000", "2026-01-06"): "watching"})
    ee.escalate("2026-01-06", workflow_repo=fake)
    # 不调 transition 'candidate'（防振荡）
    assert not any(c[3] == "candidate" for c in fake.calls if c[0] == "transition")


def test_no_auto_holding(tmp_db):
    """escalate 不调 transition('monitoring'/'holding')（决策#11 watching 以上人工）。"""
    _insert_track("600000", "2026-01-01", status="tracking", age=3, admit_gene=50, sector_rank=2)
    _add_snapshots("600000", ["2026-01-04"], [65], [2])
    fake = FakeWorkflowRepo()
    ee.escalate("2026-01-04", workflow_repo=fake)
    assert not any(c[3] in ("monitoring", "holding") for c in fake.calls if c[0] == "transition")


def test_maturity_criteria_immutable():
    """MaturityCriteria frozen dataclass。"""
    mc = ee.MaturityCriteria()
    with pytest.raises(Exception):
        mc.min_tracking_age = 99  # frozen
