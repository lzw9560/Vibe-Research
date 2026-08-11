# -*- coding: utf-8 -*-
"""S054 样本回填测试。"""
from __future__ import annotations

from unittest import mock
from pathlib import Path

import pytest

from backfill_winrate_samples import backfill_winrate_samples


def _is_bought_via_hash(code: str, date: str) -> bool:
    h = hash(f"{code}|{date}") % 100
    return h < 70


def test_backfill_idempotent_run_twice(tmp_path, monkeypatch):
    """连跑两次，第二次不产生新行（先删旧合成行）。"""
    calls = {"n": 0}

    class FakeTracker:
        db_path = str(tmp_path / "winrate.db")
        def add_record(self, r):
            calls["n"] += 1

    monkeypatch.setattr("backfill_winrate_samples._list_gene_score_dates", lambda d: ["2026-08-11"])
    monkeypatch.setattr("backfill_winrate_samples._load_gene_scores_for_date",
                        lambda d: [{"code": "600519", "name": "茅台", "gene_score": 70}])
    monkeypatch.setattr("backfill_winrate_samples._calc_next_day_return", lambda c, d: 0.05)
    monkeypatch.setattr("win_rate_tracker.WinRateTracker", lambda: FakeTracker())

    r1 = backfill_winrate_samples(30)
    n1 = calls["n"]
    r2 = backfill_winrate_samples(30)
    assert r1["backfilled"] == r2["backfilled"]


def test_backfill_missed_reserved(tmp_path, monkeypatch):
    """30% 标的留作 missed 桶，不写 winrate_records。"""
    calls = {"written": 0}

    class FakeTracker:
        db_path = str(tmp_path / "winrate.db")
        def add_record(self, r):
            calls["written"] += 1

    monkeypatch.setattr("backfill_winrate_samples._list_gene_score_dates", lambda d: ["2026-08-11"])
    monkeypatch.setattr("backfill_winrate_samples._load_gene_scores_for_date",
                        lambda d: [
                            {"code": "600519", "name": "茅台", "gene_score": 70},
                            {"code": "000001", "name": "平安", "gene_score": 65},
                            {"code": "300750", "name": "宁德", "gene_score": 60},
                            {"code": "002594", "name": "比亚迪", "gene_score": 55},
                        ])
    monkeypatch.setattr("backfill_winrate_samples._calc_next_day_return", lambda c, d: 0.03)
    monkeypatch.setattr("win_rate_tracker.WinRateTracker", lambda: FakeTracker())

    r = backfill_winrate_samples(30)
    assert r["backfilled"] + r["missed_reserved"] == 4


def test_backfill_kline_missing_skipped(tmp_path, monkeypatch):
    """K 线缺失标的跳过（failed 计数）。"""
    class FakeTracker:
        db_path = str(tmp_path / "winrate.db")
        def add_record(self, r): pass

    monkeypatch.setattr("backfill_winrate_samples._list_gene_score_dates", lambda d: ["2026-08-11"])
    monkeypatch.setattr("backfill_winrate_samples._load_gene_scores_for_date",
                        lambda d: [{"code": "600519", "name": "茅台", "gene_score": 70}])
    monkeypatch.setattr("backfill_winrate_samples._calc_next_day_return", lambda c, d: None)
    monkeypatch.setattr("win_rate_tracker.WinRateTracker", lambda: FakeTracker())

    r = backfill_winrate_samples(30)
    assert r["backfilled"] == 0
    assert r["failed"] == 1


def test_backfill_no_snapshots(tmp_path, monkeypatch):
    """无 gene_scores 日期 → backfilled=0。"""
    monkeypatch.setattr("backfill_winrate_samples._list_gene_score_dates", lambda d: [])
    r = backfill_winrate_samples(30)
    assert r["backfilled"] == 0
