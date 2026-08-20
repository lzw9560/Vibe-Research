# -*- coding: utf-8 -*-
"""S089 A2：一次性脚本——对 8 个未启用 WAL 的 DB 执行 WAL + busy_timeout。

摸底（2026-08-20）：9 个 DB 中仅 ``market_data.db`` 已有 WAL，其余 8 个为
``delete`` journal。本脚本对这 8 个库统一 ``PRAGMA journal_mode=WAL`` +
``PRAGMA busy_timeout=5000``，并打印 before/after journal_mode 供核对。

用法::

    cd backend
    .venv/bin/python tools/enable_wal_all_dbs.py

不删除原库、不改 schema，仅切 journal 模式。可重复执行（WAL 库再跑
仍是 WAL，幂等）。
"""

from __future__ import annotations

import os
import sqlite3
import sys

# backend/ 在 sys.path，才能 import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import PRIVATE_DATA_DIR  # noqa: E402

# 8 个未启用 WAL 的 DB（market_data.db 已有 WAL，不在此列）
TARGET_DBS: list[str] = [
    "seal_intraday.db",
    "gene_scores.db",
    "funnel_cache.db",
    "winrate.db",
    "zt_history.db",
    "sti_timeline.db",
    "verification_card.db",
    "kline_history.db",
]


def enable_wal_for_db(db_filename: str) -> dict[str, str]:
    """对单个 DB 执行 WAL + busy_timeout，返回 before/after journal_mode。

    库不存在时跳过（返回 before="missing"），不臆造空库。
    """
    db_path = os.path.join(PRIVATE_DATA_DIR, db_filename)
    if not os.path.exists(db_path):
        return {"db": db_filename, "before": "missing", "after": "missing", "note": "文件不存在，跳过"}
    conn = sqlite3.connect(db_path)
    try:
        before = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        after = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        return {
            "db": db_filename,
            "before": before,
            "after": after,
            "busy_timeout": str(busy),
        }
    finally:
        conn.close()


def main() -> int:
    print(f"[enable_wal_all_dbs] PRIVATE_DATA_DIR={PRIVATE_DATA_DIR}")
    print(f"[enable_wal_all_dbs] 目标 {len(TARGET_DBS)} 个 DB\n")
    rc = 0
    for db in TARGET_DBS:
        result = enable_wal_for_db(db)
        before = result["before"]
        after = result["after"]
        if before == "missing":
            print(f"  - {db:24s}  SKIP（文件不存在）")
            continue
        busy = result.get("busy_timeout", "?")
        flag = "OK" if after == "wal" else "FAIL"
        if after != "wal":
            rc = 1
        print(f"  - {db:24s}  {flag}  journal_mode: {before} -> {after}  busy_timeout={busy}")
    print()
    print("[enable_wal_all_dbs] 完成。market_data.db 已有 WAL，未在此列表内。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
