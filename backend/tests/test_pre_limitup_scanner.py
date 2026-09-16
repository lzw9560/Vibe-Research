# -*- coding: utf-8 -*-
"""S208 pre_limitup_scanner TDD test.

专家 reframe（2026-09-16）：drop high_gene（死阈值 + 证否），relay_seed (lbc==1) post-首板，
pit guard T-1 only，zero em_get。
"""
import sqlite3

import pre_limitup_scanner as pls

_ZT_SCHEMA = (
    "CREATE TABLE zt_history (date TEXT, code TEXT, name TEXT, lbc INTEGER, zbc REAL, "
    "fbt REAL, fund REAL, zje REAL, p REAL, ltsz REAL, fundamt REAL, hybk TEXT, "
    "snapshot_at TEXT, is_final INTEGER, source TEXT)"
)


def _make_zt_db(tmp_path, rows):
    """建 tmp zt_history.db + 插 rows [(date, code, lbc, hybk, is_final)]。"""
    zt_db = tmp_path / "zt_history.db"
    conn = sqlite3.connect(str(zt_db))
    conn.execute(_ZT_SCHEMA)
    conn.executemany(
        "INSERT INTO zt_history (date, code, lbc, hybk, is_final) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return zt_db


def test_scan_returns_lbc1_excludes_lbc2(tmp_path, monkeypatch):
    """scan_pre_limitup 返 lbc==1 首板，排除 lbc>=2 连板（非 pre-二板）。"""
    zt_db = _make_zt_db(tmp_path, [
        ("2026-01-01", "600000", 1, "化学制品", 1),  # 首板 → admit
        ("2026-01-01", "600001", 2, "化学制品", 1),  # 连板 → exclude
        ("2026-01-01", "600002", 3, "化学制品", 1),  # 连板 → exclude
    ])
    monkeypatch.setattr(pls, "ZT_DB", zt_db)
    monkeypatch.setattr(pls, "_sector_zt_count", lambda d, i: 3)
    cands = pls.scan_pre_limitup("2026-01-02", previous_trade_day="2026-01-01")
    codes = [c["code"] for c in cands]
    assert "600000" in codes
    assert "600001" not in codes
    assert "600002" not in codes
    assert all(c["lbc"] == 1 for c in cands)


def test_scan_high_gene_always_zero(tmp_path, monkeypatch):
    """high_gene 恒 0（dropped——死阈值 >=80 vs max 50.46 + 证否 0.942x，不扫 cutoff）。"""
    zt_db = _make_zt_db(tmp_path, [("2026-01-01", "600000", 1, "化学", 1)])
    monkeypatch.setattr(pls, "ZT_DB", zt_db)
    monkeypatch.setattr(pls, "_sector_zt_count", lambda d, i: 2)
    cands = pls.scan_pre_limitup("2026-01-02", previous_trade_day="2026-01-01")
    assert len(cands) == 1
    assert cands[0]["high_gene"] == 0


def test_scan_pit_guard_t1_only(tmp_path, monkeypatch):
    """pit guard：只取 T-1 数据，不取 T 日盘中。"""
    zt_db = _make_zt_db(tmp_path, [
        ("2026-01-01", "600000", 1, "化学", 1),  # T-1 → include
        ("2026-01-02", "600001", 1, "化学", 1),  # T → exclude (pit guard)
    ])
    monkeypatch.setattr(pls, "ZT_DB", zt_db)
    monkeypatch.setattr(pls, "_sector_zt_count", lambda d, i: 2)
    cands = pls.scan_pre_limitup("2026-01-02", previous_trade_day="2026-01-01")
    codes = [c["code"] for c in cands]
    assert "600000" in codes  # T-1 included
    assert "600001" not in codes  # T excluded


def test_scan_candidate_shape_5_keys(tmp_path, monkeypatch):
    """候选 dict 5 keys {code, sector_rank, zt_count_today, lbc, high_gene}（early_admission 契约）。"""
    zt_db = _make_zt_db(tmp_path, [("2026-01-01", "600000", 1, "化学制品", 1)])
    monkeypatch.setattr(pls, "ZT_DB", zt_db)
    monkeypatch.setattr(pls, "_sector_zt_count", lambda d, i: 5)
    cands = pls.scan_pre_limitup("2026-01-02", previous_trade_day="2026-01-01")
    assert len(cands) == 1
    c = cands[0]
    assert set(c.keys()) == {"code", "sector_rank", "zt_count_today", "lbc", "high_gene"}
    assert c["code"] == "600000"
    assert c["sector_rank"] is None  # MVP
    assert c["zt_count_today"] == 5
    assert c["lbc"] == 1
    assert c["high_gene"] == 0


def test_scan_empty_when_no_lbc1(tmp_path, monkeypatch):
    """T-1 无 lbc==1 首板 → 空列表（不臆造）。"""
    zt_db = _make_zt_db(tmp_path, [("2026-01-01", "600000", 2, "化学", 1)])  # only lbc=2
    monkeypatch.setattr(pls, "ZT_DB", zt_db)
    monkeypatch.setattr(pls, "_sector_zt_count", lambda d, i: 2)
    cands = pls.scan_pre_limitup("2026-01-02", previous_trade_day="2026-01-01")
    assert cands == []
