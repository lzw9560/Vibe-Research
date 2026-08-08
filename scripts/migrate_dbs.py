#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S037: 三库 + winrate 统一迁移到 .vibe-research/

用法:
    python scripts/migrate_dbs.py          # 执行迁移
    python scripts/migrate_dbs.py --dry    # 只打印计划不执行

幂等: 新库已存在且行数匹配则跳过, 可重复运行.
旧库改名 .bak (不删除), 留同目录.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

# 把 backend/ 加入 sys.path 以 import vr_paths——与 config 使用同一路径解析逻辑
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "backend"))
from vr_paths import resolve_data_dir  # noqa: E402


def _repo_relative(path: str) -> Path:
    """把相对路径解析为仓库根下绝对路径."""
    p = Path(path)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return p


MIGRATIONS: list[dict] = [
    {
        "name": "gene_scores",
        "old": "backend/limitup_screener/vibe_research.db",
        "new": "gene_scores.db",
        "tables": ["gene_scores", "fuse_pardon_records", "migrations"],
    },
    {
        "name": "sti_timeline",
        "old": "backend/limitup_sti/vibe_research.db",
        "new": "sti_timeline.db",
        "tables": ["sti_timeline", "migrations"],
    },
    {
        "name": "winrate",
        "old": "backend/data/winrate.db",
        "new": "winrate.db",
        "tables": ["winrate_records", "migrations"],
    },
]


def _wal_checkpoint(conn: sqlite3.Connection) -> None:
    """WAL 模式下强制全量落盘, 防 cp 到不一致快照."""
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.DatabaseError:
        pass


def _table_row_count(conn: sqlite3.Connection, table: str) -> int:
    """返回指定表行数, 表不存在返回 -1."""
    try:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError:
        return -1


def _get_row_counts(db_path: Path, tables: list[str]) -> dict[str, int]:
    """获取库中各表行数."""
    conn = sqlite3.connect(str(db_path))
    counts = {}
    for t in tables:
        counts[t] = _table_row_count(conn, t)
    conn.close()
    return counts


def _counts_match(old_counts: dict[str, int], new_counts: dict[str, int]) -> bool:
    """比较新旧库行数是否一致."""
    return old_counts == new_counts


def migrate_db(spec: dict, dry: bool = False, data_dir: Path | None = None) -> dict:
    """迁移单个库. 返回状态报告.

    ``data_dir`` 默认走 ``vr_paths.resolve_data_dir()``，与 ``config`` 保持
    一致（兼容 ``VR_DATA_DIR`` 环境变量）。测试可注入临时目录隔离。
    """
    name = spec["name"]
    old_path = _repo_relative(spec["old"])
    if data_dir is None:
        data_dir = resolve_data_dir()
    new_path = Path(data_dir) / spec["new"]
    tables = spec["tables"]

    report = {
        "name": name,
        "old": str(old_path),
        "new": str(new_path),
        "status": "",
        "old_counts": {},
        "new_counts": {},
    }

    # 源库不存在
    if not old_path.exists():
        report["status"] = "skip: old db not found"
        return report

    # 读旧行数 (先 wal_checkpoint 确保全量落盘)
    conn_old = sqlite3.connect(str(old_path))
    _wal_checkpoint(conn_old)
    for t in tables:
        report["old_counts"][t] = _table_row_count(conn_old, t)
    conn_old.close()

    # 幂等检查: 新库已存在且行数匹配则跳过
    if new_path.exists():
        new_counts = _get_row_counts(new_path, tables)
        report["new_counts"] = new_counts
        if _counts_match(report["old_counts"], new_counts):
            report["status"] = "skip: already migrated (row counts match)"
            return report
        # 新库存在但行数不匹配——如果新库全空 (0 rows) 说明 app 启动时
        # 已创建 schema 但未迁移数据, 可以安全覆盖
        # 只看数据表 (排除 migrations 表: schema 已建则 migrations 有记录)
        data_tables = [t for t in tables if t != "migrations"]
        new_data_empty = all(new_counts.get(t, -1) <= 0 for t in data_tables)
        old_has_data = any(report["old_counts"].get(t, -1) > 0 for t in data_tables)
        if not (new_data_empty and old_has_data):
            report["status"] = "ERROR: new db exists with data but row counts mismatch"
            return report
        # 新库全空旧库有数据——继续迁移 (覆盖空库)

    if dry:
        report["status"] = "dry-run: would migrate"
        report["new_counts"] = {t: "?" for t in tables}
        return report

    # 确保 .vibe-research/ 目录存在
    new_path.parent.mkdir(parents=True, exist_ok=True)

    # cp 旧库到新路径
    shutil.copy2(str(old_path), str(new_path))

    # 验证新库行数
    report["new_counts"] = _get_row_counts(new_path, tables)
    if not _counts_match(report["old_counts"], report["new_counts"]):
        report["status"] = "ERROR: row count mismatch after copy"
        return report

    # 旧库改名 .bak
    bak_path = old_path.with_suffix(old_path.suffix + ".bak")
    if bak_path.exists():
        bak_path.unlink()
    old_path.rename(bak_path)

    report["status"] = "migrated"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="S037: 迁移三库 + winrate 到 .vibe-research/"
    )
    parser.add_argument(
        "--dry", action="store_true", help="只打印计划不执行"
    )
    args = parser.parse_args()

    print(f"仓库根: {_REPO_ROOT}")
    print(f"目标目录: {resolve_data_dir()}")
    print()

    reports = []
    for spec in MIGRATIONS:
        report = migrate_db(spec, dry=args.dry)
        reports.append(report)
        print(f"[{report['name']}] {report['status']}")
        if report["old_counts"]:
            for t, c in report["old_counts"].items():
                nc = report["new_counts"].get(t, "?")
                print(f"  {t}: old={c} new={nc}")
        print()

    errors = [r for r in reports if r["status"].startswith("ERROR")]
    if errors:
        print(f"!! {len(errors)} 个库迁移失败")
        return 1
    print("迁移完成。" if not args.dry else "Dry-run 完成.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
