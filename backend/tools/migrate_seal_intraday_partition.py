# -*- coding: utf-8 -*-
"""S089 C5：seal_intraday_snapshots 历史数据迁移到分表分库。

读旧库 ``.vibe-research/seal_intraday.db`` 的 ``seal_intraday_snapshots`` 全量，
按 row.date 路由到 ``seal_intraday_YYYY.db`` 的 ``seal_intraday_snapshots_YYYYMM``
分表写入。行数对比验证 + 旧库保留 ``.bak``（不删数据）。

用法::

    cd backend
    .venv/bin/python tools/migrate_seal_intraday_partition.py --dry-run   # 只打印不写
    .venv/bin/python tools/migrate_seal_intraday_partition.py             # 实跑 + 旧库 .bak
    .venv/bin/python tools/migrate_seal_intraday_partition.py --no-keep-old  # 不保留 .bak（默认保留）

工程底线：
- 旧库保留 ``.bak`` 不删（spec §9 回滚预案）
- 行数前后对比（旧 COUNT(*) vs 新分表 SUM(COUNT(*))），不一致 abort
- 幂等：重复跑会重复写入（INSERT 非 UPSERT）——脚本检测旧库已 .bak 则跳过
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# backend/ 加 sys.path 才能 import config / db_partition_router
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import PRIVATE_DATA_DIR, SEAL_INTRADAY_DB_PATH  # noqa: E402
from db_partition_router import ensure_partition, resolve_partition  # noqa: E402

#: 旧库标准表名（迁移源）
OLD_TABLE = "seal_intraday_snapshots"
#: 旧库全路径
OLD_DB_PATH = SEAL_INTRADAY_DB_PATH


def _old_db_exists() -> bool:
    return os.path.exists(OLD_DB_PATH)


def _old_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (OLD_TABLE,),
    ).fetchone()
    return row is not None


def _read_old_rows(conn: sqlite3.Connection) -> list[dict]:
    """读旧库 seal_intraday_snapshots 全量（dict 列）。"""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT * FROM {OLD_TABLE}"
    ).fetchall()
    return [dict(r) for r in rows]


def _date_range(rows: list[dict]) -> tuple[str, str] | tuple[None, None]:
    """返回 (min_date, max_date)。空表返 (None, None)。"""
    dates = [r.get("date") for r in rows if r.get("date")]
    if not dates:
        return None, None
    return min(dates), max(dates)


def _bucket_rows(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """按 (db_path, table) 分桶。"""
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        date = r.get("date")
        if not date:
            continue
        db_path, table = resolve_partition(date)
        buckets[(db_path, table)].append(r)
    return buckets


def _insert_fields() -> list[str]:
    """分表 INSERT 字段（与 ensure_partition DDL 对齐，不含 id/created_at）。"""
    return ["ts", "date", "code", "name", "pool", "price", "seal_amount",
            "open_count", "first_seal_time", "consec_boards", "sector",
            "float_market_cap", "index_5min_change", "low_price", "limit_pct"]


def _write_bucket(db_path: str, table: str, rows: list[dict]) -> int:
    """写一个桶到对应分表，返回写入行数。"""
    if not rows:
        return 0
    # ensure 建表建索引（幂等）
    ensure_partition(rows[0]["date"])
    fields = _insert_fields()
    placeholders = ",".join(f":{f}" for f in fields)
    col_list = ",".join(fields)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.executemany(
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
            [{k: r.get(k) for k in fields} for r in rows],
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def _count_old(conn: sqlite3.Connection) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {OLD_TABLE}").fetchone()[0]


def _count_new(buckets: dict[tuple[str, str], list[dict]]) -> int:
    """统计新分表已写入行数（SUM(COUNT(*))）。"""
    total = 0
    # 按 db_path 聚合，每库开一次连接
    by_db: dict[str, list[str]] = defaultdict(list)
    for (db_path, table) in buckets:
        if table not in by_db[db_path]:
            by_db[db_path].append(table)
    for db_path, tables in by_db.items():
        if not os.path.exists(db_path):
            continue
        conn = sqlite3.connect(db_path)
        try:
            for table in tables:
                try:
                    total += conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except sqlite3.OperationalError:
                    pass  # 表不存在 → 0
        finally:
            conn.close()
    return total


def _preserve_aux_tables(bak_path: str, new_main_db: str) -> dict[str, int]:
    """从 .bak 旧库保留辅助表（非分区）到新主库 seal_intraday.db。

    辅助表（按 spec §4：seal_intraday_snapshots 走分区，其余留主库）：
    - bomb_alert_history（炸板预警历史，业务状态，需保留）
    - intraday_features / seal_derived_features（派生预采集，默认 0 行，幂等建）
    - migrations（迁移记录，run_migrations 重建）

    策略：新主库经 run_migrations() 建表（幂等），bomb_alert_history 从 .bak 拷行。
    其余表若 .bak 有行则一并拷（防御性）。
    """
    # 1. 新主库 run_migrations 重建辅助表 schema（intraday_features /
    #    seal_derived_features / bomb_alert_history / migrations）
    from risk.seal_intraday_collector import run_migrations
    run_migrations()  # 写入 new_main_db（_DB_PATH 已指向它）

    # 2. 从 .bak 拷 bomb_alert_history 行（+ 防御性拷其他有行的辅助表）
    aux_tables = ["bomb_alert_history", "intraday_features", "seal_derived_features"]
    copied: dict[str, int] = {}
    bak_conn = sqlite3.connect(bak_path)
    try:
        bak_conn.row_factory = sqlite3.Row
        for table in aux_tables:
            # 检查 .bak 有此表
            exists = bak_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                continue
            rows = [dict(r) for r in bak_conn.execute(f"SELECT * FROM {table}").fetchall()]
            if not rows:
                copied[table] = 0
                continue
            cols = list(rows[0].keys())
            col_list = ",".join(cols)
            placeholders = ",".join("?" for _ in cols)
            new_conn = sqlite3.connect(new_main_db)
            try:
                new_conn.executemany(
                    f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
                    [tuple(r[c] for c in cols) for r in rows],
                )
                new_conn.commit()
                copied[table] = len(rows)
            finally:
                new_conn.close()
    finally:
        bak_conn.close()
    return copied


def _rename_old_to_bak() -> str:
    """旧库重命名 .bak。返回 bak 路径。"""
    bak = OLD_DB_PATH + ".bak"
    if os.path.exists(bak):
        os.remove(bak)  # 覆盖旧 .bak
    os.rename(OLD_DB_PATH, bak)
    return bak


def _print_report(old_count: int, new_count: int | None, buckets: dict,
                  date_min: str | None, date_max: str | None,
                  dry_run: bool, bak_path: str | None) -> None:
    print("=" * 60)
    print("[migrate_seal_intraday_partition] 迁移报告")
    print("=" * 60)
    print(f"  旧库        : {OLD_DB_PATH}")
    print(f"  分库目录    : {PRIVATE_DATA_DIR}")
    print(f"  日期范围    : {date_min} ~ {date_max}")
    print(f"  分表数      : {len(buckets)}")
    print(f"  旧库行数    : {old_count}")
    if new_count is None:
        print(f"  新分表行数  : N/A（dry-run 未写）")
        print(f"  行数一致    : N/A")
    else:
        print(f"  新分表行数  : {new_count}")
        print(f"  行数一致    : {'OK' if old_count == new_count else 'FAIL'}")
    print(f"  模式        : {'dry-run（未写）' if dry_run else '实跑（已写）'}")
    if bak_path:
        print(f"  旧库备份    : {bak_path}")
    print()
    print("  分表明细（db_path / table / 行数）:")
    for (db_path, table), rows in sorted(buckets.items()):
        print(f"    {os.path.basename(db_path):28s} {table:36s} {len(rows):>8d} 行")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="S089 C5: seal_intraday 历史数据迁移到分表分库")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写")
    parser.add_argument("--no-keep-old", action="store_true",
                        help="不保留旧库 .bak（默认保留）")
    args = parser.parse_args()

    print(f"[migrate] PRIVATE_DATA_DIR={PRIVATE_DATA_DIR}")
    print(f"[migrate] 旧库={OLD_DB_PATH}")

    if not _old_db_exists():
        print("[migrate] 旧库不存在，无需迁移（可能已迁移过）。")
        return 0

    # 幂等检查：旧库已 .bak 说明已迁移过。
    # 实跑模式下跳过避免重复写入（新主库 seal_intraday_snapshots 为空，源数据在 .bak）。
    # dry-run 模式下若 .bak 存在，从 .bak 读源数据报告状态（不写）。
    source_db = OLD_DB_PATH
    if os.path.exists(OLD_DB_PATH + ".bak"):
        if args.dry_run:
            # dry-run：从 .bak 读源数据状态（已迁移过的查询）
            source_db = OLD_DB_PATH + ".bak"
            print(f"[migrate] 检测到 {source_db} —— 已迁移过，dry-run 从 .bak 读源状态。")
        else:
            print(f"[migrate] 检测到 {OLD_DB_PATH}.bak —— 旧库已迁移过，跳过。")
            return 0

    conn = sqlite3.connect(source_db)
    try:
        if not _old_table_exists(conn):
            print(f"[migrate] 源库 {source_db} 无 {OLD_TABLE} 表，跳过。")
            return 0
        old_count = _count_old(conn)
        rows = _read_old_rows(conn)
    finally:
        conn.close()

    date_min, date_max = _date_range(rows)
    buckets = _bucket_rows(rows)

    print(f"[migrate] 源库={source_db} 行数={old_count} 日期范围={date_min}~{date_max} 分表数={len(buckets)}")

    if args.dry_run:
        # dry-run 只统计、不写；行数一致标 N/A（未写 → new_count=0 不代表真失败）
        _print_report(old_count, None, buckets, date_min, date_max,
                      dry_run=True, bak_path=None)
        print("[migrate] dry-run 模式，未写入分表。")
        return 0

    # 实跑：写各桶
    written_total = 0
    for (db_path, table), bucket_rows in buckets.items():
        n = _write_bucket(db_path, table, bucket_rows)
        written_total += n
    print(f"[migrate] 写入完成，总行数={written_total}")

    # 行数验证
    new_count = _count_new(buckets)
    if new_count != old_count:
        print(f"[migrate] ERROR 行数不一致：旧={old_count} 新={new_count}，abort（不删旧库）")
        return 1

    # 旧库重命名 .bak（默认保留）——先重命名再在新主库重建辅助表 schema
    bak_path = None
    if not args.no_keep_old:
        bak_path = _rename_old_to_bak()
        print(f"[migrate] 旧库已备份为 {bak_path}")
        # S089 C5：从 .bak 保留辅助表（bomb_alert_history 等非分区表）到新主库。
        # 新主库 seal_intraday.db 经 run_migrations() 重建 schema，bomb_alert_history
        # 等业务状态表从 .bak 拷行（intraday_features/seal_derived_features 默认 0 行）。
        copied = _preserve_aux_tables(bak_path, OLD_DB_PATH)
        if any(copied.values()):
            print(f"[migrate] 辅助表行数保留：{copied}")
        else:
            print("[migrate] 辅助表无行需保留（新主库已重建空表）")

    _print_report(old_count, new_count, buckets, date_min, date_max,
                  dry_run=False, bak_path=bak_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
