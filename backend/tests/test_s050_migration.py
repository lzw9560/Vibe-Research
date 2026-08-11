# -*- coding: utf-8 -*-
"""S050 W0：winrate_records 迁移 003（信号归因 5 列）+ Record 扩字段测试。

迁移幂等（连跑两遍）+ 旧行 5 列 NULL + 新记录写入回读一致 + get_stats 不崩（NULL 兼容）。
所有写入经 tmp db——绝不碰用户真实 winrate.db。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from win_rate_tracker import WinRateRecord, WinRateTracker


@pytest.fixture
def tmp_winrate_db(tmp_path) -> str:
    """tmp winrate.db 路径（WinRateTracker 初始化跑迁移）。"""
    return str(tmp_path / "winrate.db")


def test_migration_003_idempotent(tmp_winrate_db):
    """迁移 003 幂等：连跑两遍不报错（MigrationManager 版本表保证）。"""
    t1 = WinRateTracker(db_path=tmp_winrate_db)
    # 第二次实例化（再跑迁移）——已应用版本跳过，不报错
    t2 = WinRateTracker(db_path=tmp_winrate_db)
    assert t1 is not t2
    cols = _columns(tmp_winrate_db)
    for col in ("signal_source", "signal_ref", "edge_family",
                "target_holding_period", "attention_mode"):
        assert col in cols, f"列 {col} 未创建"


def test_legacy_rows_have_null_attribution(tmp_winrate_db):
    """旧库升级后 legacy 行 5 列 NULL（向前兼容）。"""
    # 先建 001 表（无 003 列），插旧行
    conn = sqlite3.connect(tmp_winrate_db)
    sql = (Path(__file__).resolve().parent.parent
           / "migrations" / "win_rate_tracker"
           / "20250613-001_create_winrate_records.sql").read_text("utf-8")
    conn.executescript(sql)
    conn.execute(
        "INSERT INTO winrate_records (stock_code, stock_name, strategy_used, "
        "entry_date, entry_price, exit_date, exit_price, return_pct, is_win, "
        "gene_score, sti_label, sector, created_at) "
        "VALUES ('600519', '茅台', '首板', '2026-07-01', 10, '2026-07-02', 11, 10, 1, 80, '', '白酒', '2026-07-02')"
    )
    conn.commit()
    conn.close()
    # 现在实例化 tracker → 跑迁移 003 加列
    WinRateTracker(db_path=tmp_winrate_db)
    rows = _fetch(tmp_winrate_db)
    assert len(rows) == 1
    r = rows[0]
    assert r["signal_source"] is None
    assert r["signal_ref"] is None
    assert r["edge_family"] is None
    assert r["attention_mode"] is None  # legacy NULL


def test_new_record_writes_attribution(tmp_winrate_db):
    """新记录写入 5 列回读一致。"""
    tracker = WinRateTracker(db_path=tmp_winrate_db)
    rec = WinRateRecord(
        stock_code="600519", stock_name="茅台", strategy_used="首板",
        entry_date="2026-07-01", entry_price=10.0,
        exit_date="2026-07-02", exit_price=11.0,
        return_pct=10.0, is_win=True, gene_score=80.0, sti_label="启动", sector="白酒",
        signal_source="funnel_candidate", signal_ref="funnel:final",
        edge_family="momentum_premium", target_holding_period="T+1", attention_mode="A",
    )
    tracker.add_record(rec)
    rows = _fetch(tmp_winrate_db)
    assert len(rows) == 1
    r = rows[0]
    assert r["signal_source"] == "funnel_candidate"
    assert r["signal_ref"] == "funnel:final"
    assert r["edge_family"] == "momentum_premium"
    assert r["target_holding_period"] == "T+1"
    assert r["attention_mode"] == "A"


def test_new_record_default_attention_mode_A(tmp_winrate_db):
    """新记录 attention_mode 缺省 'A'。"""
    tracker = WinRateTracker(db_path=tmp_winrate_db)
    rec = WinRateRecord(
        stock_code="000001", stock_name="平安", strategy_used="连板",
        entry_date="2026-07-01", entry_price=10.0,
        exit_date="2026-07-02", exit_price=9.5,
        return_pct=-5.0, is_win=False, gene_score=60.0, sti_label="分歧", sector="银行",
        signal_source="feeling",
    )
    tracker.add_record(rec)
    rows = _fetch(tmp_winrate_db)
    assert rows[0]["attention_mode"] == "A"


def test_get_stats_does_not_crash_with_null_attribution(tmp_winrate_db):
    """get_stats 对 NULL 归因列不崩（legacy 行兼容）。"""
    tracker = WinRateTracker(db_path=tmp_winrate_db)
    rec = WinRateRecord(
        stock_code="600519", stock_name="茅台", strategy_used="首板",
        entry_date="2026-07-01", entry_price=10.0,
        exit_date="2026-07-02", exit_price=11.0,
        return_pct=10.0, is_win=True, gene_score=80.0, sti_label="启动", sector="白酒",
    )
    tracker.add_record(rec)
    stats = tracker.get_stats(window_size=20)
    assert stats.total_trades == 1
    assert stats.win_rate == 1.0


# ---- helpers ----

def _columns(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(winrate_records)").fetchall()}
    conn.close()
    return cols


def _fetch(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM winrate_records").fetchall()]
    conn.close()
    return rows
