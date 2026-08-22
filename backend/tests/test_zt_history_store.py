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


# ── S078 follow-up：每日唯一 + final 标记（2026-08-23 落地）──────────────────────


def test_snapshot_same_day_new_pool_overwrites_old_no_residue(monkeypatch, tmp_path):
    """同日二次写入不同 code 集合，旧池残行不应残留（修 INSERT OR REPLACE 只覆盖同 code 的 bug）。"""
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")

    # Act：16:00 写 2 只，后续写 1 只（不同 code 集合）
    zth.snapshot_zt_pool("2026-08-21", pool=_POOL)  # 600127, 001358
    zth.snapshot_zt_pool("2026-08-21", pool=[
        {"c": "300999", "n": "新妖", "lbc": 1}])  # 全新 code

    # Assert：只剩 1 行（300999），旧 2 行不应残留
    rows = zth.load_zt_history("2026-08-21", "2026-08-21")
    assert len(rows) == 1
    assert rows[0]["code"] == "300999"


def test_snapshot_final_overwrites_non_final(monkeypatch, tmp_path):
    """is_final=True 可覆盖非 final 旧行。"""
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")

    # Arrange：先写非 final
    zth.snapshot_zt_pool("2026-08-21", pool=_POOL, is_final=False)
    # Act：再写 final（不同 code 集合也行）
    zth.snapshot_zt_pool("2026-08-21", pool=[
        {"c": "300999", "n": "终盘版", "lbc": 1}], is_final=True)

    # Assert：终盘版覆盖成功，is_final=1
    rows = zth.load_zt_history("2026-08-21", "2026-08-21")
    assert len(rows) == 1
    assert rows[0]["code"] == "300999"
    assert rows[0]["is_final"] == 1


def test_snapshot_non_final_rejected_after_final_locked(monkeypatch, tmp_path):
    """旧行已 is_final=1，后续 is_final=False 写入应被拒绝（final 一旦落定不可被覆盖）。"""
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")

    # Arrange：先落定 final
    zth.snapshot_zt_pool("2026-08-21", pool=_POOL, is_final=True)
    assert len(zth.load_zt_history("2026-08-21", "2026-08-21")) == 2

    # Act：试图用非 final 覆盖（不同 code）
    written = zth.snapshot_zt_pool("2026-08-21", pool=[
        {"c": "300999", "n": "旧时点", "lbc": 1}], is_final=False)

    # Assert：拒绝，0 行写入，旧 final 数据保留
    assert written == 0
    rows = zth.load_zt_history("2026-08-21", "2026-08-21")
    assert len(rows) == 2  # 仍是原 final 的 2 行
    assert all(r["is_final"] == 1 for r in rows)


def test_snapshot_final_replaces_final_allowed(monkeypatch, tmp_path):
    """final 可被新 final 覆盖（同日重采终盘版允许，如人工补采）。"""
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")

    zth.snapshot_zt_pool("2026-08-21", pool=_POOL, is_final=True)
    zth.snapshot_zt_pool("2026-08-21", pool=[
        {"c": "300999", "n": "补采终盘", "lbc": 1}], is_final=True)

    rows = zth.load_zt_history("2026-08-21", "2026-08-21")
    assert len(rows) == 1
    assert rows[0]["code"] == "300999"
    assert rows[0]["is_final"] == 1


def test_ensure_final_column_idempotent_on_legacy_db(monkeypatch, tmp_path):
    """存量老表（无 is_final 列）首连自动 ALTER 加列，二次连不报错。"""
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")

    # Arrange：手动建老表（无 is_final 列），模拟 2026-08-23 迁移前的生产 DB
    import sqlite3
    conn = sqlite3.connect(tmp_path / "zt_history.db")
    conn.execute("""CREATE TABLE zt_history (
        date TEXT NOT NULL, code TEXT NOT NULL, name TEXT,
        lbc INTEGER, zbc REAL, fbt REAL, fund REAL, zje REAL, p REAL,
        ltsz REAL, fundamt REAL, hybk TEXT, snapshot_at TEXT,
        PRIMARY KEY (date, code))""")
    conn.execute("INSERT INTO zt_history (date, code, snapshot_at) VALUES ('2026-08-01', '000001', 'x')")
    conn.commit()
    conn.close()

    # Act：通过 _get_conn 触发 _ensure_final_column
    conn = zth._get_conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(zt_history)")}
    conn.close()

    # Assert：列已加
    assert "is_final" in cols
    # 二次连不报错（幂等）
    conn = zth._get_conn()
    conn.close()
