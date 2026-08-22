# -*- coding: utf-8 -*-
"""一次性迁移：zt_history 同日多 snapshot 去重 + is_final 标记（2026-08-23 落地）。

背景：旧写入路径用 INSERT OR REPLACE（PK=date,code），新旧快照 code 集合不同时
残行混入。实证 2026-08-21 同日存 16:00 68 条 + 08-23 00:08 54 条两时点混合 122 行。
新机制改为单事务 DELETE+INSERT（每日唯一）+ is_final 标记（采集时间>=17:15 视终盘）。

迁移逻辑（幂等，可重复跑）：
1. ALTER TABLE 加 is_final 列（若不存在）——实际由 zt_history_store._get_conn 自动完成
2. 对每个 date，按 snapshot_at 取时间最晚的一条为新数据
3. 删除该 date 下所有行，仅重新插入最晚时点对应的行集合
4. is_final 判定：最晚时点 snapshot_at >= 17:15（北京时间）→ 1；否则 0
   （历史采集点早于 17:15 规则上线，保守标 0，后续可由回填任务升级）
5. 报告：处理 date 数、删行数、标 final 数

手动触发：
    cd backend && .venv/bin/python -m scripts.migrate_zt_history_final
    cd backend && .venv/bin/python -m scripts.migrate_zt_history_final --dry-run
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# backend/ 入 sys.path 以复用 zt_history_store（确保 _ensure_final_column 跑过）
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import data.zt_history_store as zth  # noqa: E402


def _parse_snapshot_time(snapshot_at: str) -> tuple[int, int] | None:
    """从 snapshot_at（ISO 字符串如 '2026-08-21T16:00:38'）取 (hour, minute)。

    返回 None 表示无法解析（保守视为非 final）。时区按北京时间（东财源为国内时点）。
    """
    if not snapshot_at or "T" not in snapshot_at:
        return None
    try:
        time_part = snapshot_at.split("T", 1)[1][:5]  # HH:MM
        hh, mm = time_part.split(":")
        return int(hh), int(mm)
    except (ValueError, IndexError):
        return None


def _is_final_by_time(snapshot_at: str) -> bool:
    """采集时间 >= 17:15 → True（终盘稳定版）。"""
    hm = _parse_snapshot_time(snapshot_at)
    if hm is None:
        return False
    hh, mm = hm
    return hh > 17 or (hh == 17 and mm >= 15)


def migrate(dry_run: bool = False) -> dict:
    """执行迁移。返回统计 dict。"""
    db_path = zth._DB_PATH
    # 先确保 is_final 列存在（建表/ALTER 幂等）
    conn = zth._get_conn()
    conn.close()

    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        # 取所有 date
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM zt_history ORDER BY date")]
        total_dates = len(dates)
        total_deleted = 0
        total_kept_rows = 0
        final_count = 0
        detail = []

        for d in dates:
            # 该 date 下所有 snapshot_at，取最晚一条时点
            snap_rows = conn.execute(
                "SELECT snapshot_at, COUNT(*) c FROM zt_history WHERE date = ? "
                "GROUP BY snapshot_at ORDER BY snapshot_at", (d,)).fetchall()
            if len(snap_rows) <= 1:
                # 单时点：无需删行，只需判 is_final 并 UPDATE
                if not snap_rows:
                    continue
                latest_snap = snap_rows[-1]["snapshot_at"]
                is_final = _is_final_by_time(latest_snap)
                rowcount = conn.execute(
                    "UPDATE zt_history SET is_final = ? WHERE date = ?",
                    (1 if is_final else 0, d)).rowcount
                total_kept_rows += rowcount
                if is_final:
                    final_count += 1
                detail.append((d, rowcount, 0, is_final))
                continue

            # 多时点：取最晚 snapshot_at，保留该时点全部行，删其余
            latest_snap = snap_rows[-1]["snapshot_at"]
            is_final = _is_final_by_time(latest_snap)

            # 数删除行
            del_count = conn.execute(
                "SELECT COUNT(*) FROM zt_history WHERE date = ? AND snapshot_at != ?",
                (d, latest_snap)).fetchone()[0]
            # 取保留行
            keep_rows = conn.execute(
                "SELECT * FROM zt_history WHERE date = ? AND snapshot_at = ?",
                (d, latest_snap)).fetchall()

            if not dry_run:
                conn.execute("DELETE FROM zt_history WHERE date = ?", (d,))
                conn.executemany(
                    """INSERT INTO zt_history
                    (date, code, name, lbc, zbc, fbt, fund, zje, p, ltsz, fundamt, hybk,
                     snapshot_at, is_final)
                    VALUES (:date, :code, :name, :lbc, :zbc, :fbt, :fund, :zje, :p,
                            :ltsz, :fundamt, :hybk, :snapshot_at, :is_final)""",
                    [{**dict(r), "is_final": 1 if is_final else 0} for r in keep_rows])

            total_deleted += del_count
            total_kept_rows += len(keep_rows)
            if is_final:
                final_count += 1
            detail.append((d, len(keep_rows), del_count, is_final))

        if not dry_run:
            conn.commit()

        return {
            "dry_run": dry_run,
            "total_dates": total_dates,
            "total_deleted": total_deleted,
            "total_kept_rows": total_kept_rows,
            "final_dates": final_count,
            "detail": detail,
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只预览不写盘")
    args = parser.parse_args()

    print(f"[migrate_zt_history_final] dry_run={args.dry_run}")
    print(f"[migrate_zt_history_final] DB={zth._DB_PATH}")
    stats = migrate(dry_run=args.dry_run)

    print("\n=== 迁移结果 ===")
    print(f"处理 date 数: {stats['total_dates']}")
    print(f"删行数: {stats['total_deleted']}")
    print(f"保留行数: {stats['total_kept_rows']}")
    print(f"标 final 的 date 数: {stats['final_dates']}")
    print("\n=== 逐日明细 (date, 保留行, 删行, is_final) ===")
    for d, kept, deleted, is_final in stats["detail"]:
        flag = "FINAL" if is_final else "non-final"
        marker = "" if deleted == 0 and kept > 0 and len(stats["detail"]) > 0 else ""
        print(f"  {d}: 保留 {kept} 行, 删 {deleted} 行, {flag}")

    # 验证：每日唯一
    conn = sqlite3.connect(zth._DB_PATH)
    try:
        dups = conn.execute(
            "SELECT date, COUNT(DISTINCT snapshot_at) c FROM zt_history "
            "GROUP BY date HAVING c > 1").fetchall()
        print("\n=== 验证：每日唯一（多时点日应为空）===")
        if dups:
            for r in dups:
                print(f"  仍多时点: {r[0]} ({r[1]} 时点)")
        else:
            print("  ✅ 所有 date 均唯一时点")
        print("\n=== 验证：最近 5 日 final 标记 ===")
        for r in conn.execute(
                "SELECT date, is_final FROM zt_history GROUP BY date "
                "ORDER BY date DESC LIMIT 5"):
            print(f"  {r[0]}: is_final={r[1]}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
