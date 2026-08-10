# -*- coding: utf-8 -*-
"""S047 阶段 B：gene_scores 历史复算（新 full 权重，一次性迁移）。

grill 锁定边界：
- 仅 ``data_source='eastmoney_live'`` 行（rebuild 行无替代权重证据，逐行不碰）
- 从存储因子列纯算术重算 total_score + qualify + high_gene；**因子列不变**
- 复算前备份 ``gene_scores.db.bak-s047-<ts>``；复算后校验因子列逐行相等 + 行数不变
- winrate_records / workflow_state 不改写（结算快照语义=结算时刻所见）

用法::

    cd backend && .venv/bin/python -m limitup_screener.recalc_gene_weights [--dry-run]
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import time
from pathlib import Path

import vr_paths

from limitup_screener.models import GENE_HIGH_THRESHOLD, GENE_QUALIFY_THRESHOLD, calc_total_score

FACTOR_COLS = (
    "factor_premium_rate", "factor_red_rate", "factor_seal_rate",
    "factor_rebound_rate", "factor_freq_score",
)
_COL_TO_NAME = {
    "factor_premium_rate": "次日溢价率",
    "factor_red_rate": "红盘率",
    "factor_seal_rate": "封板率",
    "factor_rebound_rate": "炸板后溢价",
    "factor_freq_score": "涨停频次",
}


def recalc_live_rows(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """复算 eastmoney_live 行。返回统计 dict。dry_run 只算不写。"""
    rows = conn.execute(
        "SELECT rowid, total_score, qualify, high_gene, " + ", ".join(FACTOR_COLS)
        + " FROM gene_scores WHERE data_source = 'eastmoney_live'"
    ).fetchall()
    stats = {"n": len(rows), "changed": 0, "qualify_now": 0, "high_now": 0, "zero_factor_rows": 0}
    updates: list[tuple] = []
    for r in rows:
        rowid, old_total, old_q, old_h = r[0], r[1], r[2], r[3]
        vals = [r[4 + i] if r[4 + i] is not None else 0.0 for i in range(len(FACTOR_COLS))]
        if all(v == 0.0 for v in vals):
            stats["zero_factor_rows"] += 1
        factors = {_COL_TO_NAME[c]: v for c, v in zip(FACTOR_COLS, vals)}
        new_total = calc_total_score(factors, weights="full")
        new_q = 1 if new_total >= GENE_QUALIFY_THRESHOLD else 0
        new_h = 1 if new_total >= GENE_HIGH_THRESHOLD else 0
        if new_total != old_total or new_q != int(bool(old_q)) or new_h != int(bool(old_h)):
            stats["changed"] += 1
        stats["qualify_now"] += new_q
        stats["high_now"] += new_h
        updates.append((new_total, new_q, new_h, rowid))
    if not dry_run:
        conn.executemany(
            "UPDATE gene_scores SET total_score = ?, qualify = ?, high_gene = ? WHERE rowid = ?",
            updates,
        )
        conn.commit()
    return stats


def _factor_snapshot(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT rowid, code, date, " + ", ".join(FACTOR_COLS) + " FROM gene_scores ORDER BY rowid"
    ).fetchall()


def main() -> None:
    ap = argparse.ArgumentParser(description="S047 阶段 B 历史复算（新 full 权重）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = ap.parse_args()

    db = Path(vr_paths.resolve_data_dir()) / "gene_scores.db"
    conn = sqlite3.connect(db)
    n_before = conn.execute("SELECT COUNT(*) FROM gene_scores").fetchone()[0]
    snapshot = _factor_snapshot(conn)

    backup_path = None
    if not args.dry_run:
        backup_path = db.parent / f"{db.name}.bak-s047-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(db, backup_path)

    stats = recalc_live_rows(conn, dry_run=args.dry_run)

    n_after = conn.execute("SELECT COUNT(*) FROM gene_scores").fetchone()[0]
    factors_ok = _factor_snapshot(conn) == snapshot

    print(f"模式: {'dry-run' if args.dry_run else 'WRITE'}")
    print(f"live 行 n={stats['n']} 变更={stats['changed']} 新 qualify={stats['qualify_now']} "
          f"新 high_gene={stats['high_now']} 全零因子行={stats['zero_factor_rows']}")
    if backup_path:
        print(f"备份: {backup_path}")
    print(f"校验: 行数 {n_before}→{n_after} {'OK' if n_before == n_after else 'FAIL'}; "
          f"因子列逐行不变 {'OK' if factors_ok else 'FAIL'}")
    if n_before != n_after or not factors_ok:
        raise SystemExit("校验失败——请从备份恢复")


if __name__ == "__main__":
    main()
