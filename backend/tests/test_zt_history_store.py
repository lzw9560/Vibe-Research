# -*- coding: utf-8 -*-
"""S078 zt_history_store 离线单测（spec §8）。

monkeypatch _DB_PATH 到 tmp（避免写真 .vibe-research/zt_history.db）。
不联网：snapshot_zt_pool(date, pool=预填) 跳过 em 调用。
AAA + 描述性命名。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # backend/
sys.path.insert(0, str(ROOT))

import data.zt_history_store as zth  # noqa: E402


_POOL = [
    {"c": "600127", "n": "金健米业", "lbc": 1, "zbc": 0, "fbt": 93500, "fund": 1e8,
     "zje": 5.30, "p": 5.30, "ltsz": 1e9, "fundamt": 2e8, "hybk": "AI"},
    {"c": "001358", "n": "兴欣新材", "lbc": 1, "zbc": 1, "fbt": 101500, "fund": 5e5,
     "zje": 10.21, "p": 10.21, "ltsz": 5e8, "fundamt": 3e7, "hybk": "芯片"},
]


# ── 归一辅助 ────────────────────────────────────────────────────────────────

def test_to_float_to_int_to_iso():
    assert zth._to_float(None) is None
    assert zth._to_float("-") is None
    assert zth._to_float("1,234.5") == 1234.5
    assert zth._to_int("3") == 3
    assert zth._to_int(None) is None
    assert zth._to_iso("20260814") == "2026-08-14"
    assert zth._to_iso("2026-08-14") == "2026-08-14"
    assert zth._to_iso("") == ""


# ── snapshot + load round-trip ─────────────────────────────────────────────

def test_snapshot_and_load_round_trip(monkeypatch, tmp_path):
    # Arrange：DB 指向 tmp
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")

    # Act
    written = zth.snapshot_zt_pool("2026-08-14", pool=_POOL)

    # Assert：写入 2 行 + round-trip
    assert written == 2
    rows = zth.load_zt_history("2026-08-14", "2026-08-14")
    assert len(rows) == 2
    r = next(r for r in rows if r["code"] == "600127")
    assert r["date"] == "2026-08-14"
    assert r["name"] == "金健米业"
    assert r["lbc"] == 1
    assert r["zbc"] == 0.0
    assert r["fund"] == 1e8
    assert r["hybk"] == "AI"
    assert r["snapshot_at"]  # 非空


def test_snapshot_idempotent_no_duplicate(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")

    # Act：同日同 pool snapshot 两次
    zth.snapshot_zt_pool("2026-08-14", pool=_POOL)
    zth.snapshot_zt_pool("2026-08-14", pool=_POOL)

    # Assert：仍 2 行（INSERT OR REPLACE 幂等，不翻倍）
    rows = zth.load_zt_history("2026-08-14", "2026-08-14")
    assert len(rows) == 2


def test_snapshot_multiple_dates_and_list(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")

    # Act：两日 snapshot
    zth.snapshot_zt_pool("2026-08-14", pool=_POOL)
    zth.snapshot_zt_pool("2026-08-15", pool=[_POOL[0]])  # 只 1 只

    # Assert：load 跨日 3 行；list_history_dates 2 日
    rows = zth.load_zt_history("2026-08-14", "2026-08-15")
    assert len(rows) == 3
    dates = zth.list_history_dates()
    assert dates == ["2026-08-14", "2026-08-15"]


def test_snapshot_empty_pool_returns_zero(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")

    # Act：空池
    written = zth.snapshot_zt_pool("2026-08-14", pool=[])

    # Assert：0 行，DB 无数据
    assert written == 0
    assert zth.load_zt_history("2026-08-14", "2026-08-14") == []


def test_snapshot_date_format_compact_and_iso(monkeypatch, tmp_path):
    # Arrange
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")

    # Act：YYYYMMDD 入参
    zth.snapshot_zt_pool("20260814", pool=[_POOL[0]])

    # Assert：DB 存 ISO 格式
    rows = zth.load_zt_history("20260814", "20260814")
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-08-14"
