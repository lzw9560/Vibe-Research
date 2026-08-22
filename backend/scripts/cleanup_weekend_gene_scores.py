"""S098 Fix B：清理 gene_scores 表的非交易日（周末）污染行。

根因：东财涨停池对非交易日请求静默回退返回最近交易日池，
基因得分预计算没做交易日校验，把上一交易日池标成周末入库。

本脚本：
  1. 先备份 db 到 ``.vibe-research/gene_scores.db.bak-fix-weekend-<日期>``
  2. dry-run 打印将删的周末行（weekday>=5）按日期分组 + 总数
  3. --apply 执行删除
  4. 验证：近 8 日分组无周末

用法：
    cd backend && ../.venv/bin/python -m scripts.cleanup_weekend_gene_scores          # dry-run
    cd backend && ../.venv/bin/python -m scripts.cleanup_weekend_gene_scores --apply  # 实删
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import GENE_SCORES_DB_PATH  # noqa: E402


def _is_weekend(date_str: str) -> bool:
    """判定 YYYY-MM-DD 是否周末（weekday>=5）。"""
    try:
        return date.fromisoformat(date_str).weekday() >= 5
    except (ValueError, TypeError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="清理 gene_scores 表周末污染行（dry-run 默认）"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际执行删除（默认只 dry-run 打印）",
    )
    args = parser.parse_args()

    db_path = Path(GENE_SCORES_DB_PATH)
    if not db_path.exists():
        print(f"[ERROR] db 不存在: {db_path}", file=sys.stderr)
        sys.exit(1)

    print(f"db: {db_path}")
    print(f"模式: {'APPLY（实删）' if args.apply else 'DRY-RUN（只打印）'}")
    print()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 扫出所有周末行按日期分组
    weekend_rows = conn.execute(
        """
        SELECT date, COUNT(*) AS cnt
        FROM gene_scores
        GROUP BY date
        HAVING strftime('%w', date) IN ('0', '6')
        ORDER BY date DESC
        """
    ).fetchall()

    total = 0
    print("=== 将删的周末行（按日期分组）===")
    for r in weekend_rows:
        d = r["date"]
        try:
            wd = date.fromisoformat(d).weekday()
            wd_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][wd]
        except (ValueError, TypeError):
            wd_name = "?"
        print(f"  {d} ({wd_name}) cnt={r['cnt']}")
        total += r["cnt"]
    print(f"周末总行数: {total}")
    print()

    if total == 0:
        print("[OK] 无周末污染行，无需清理。")
        conn.close()
        return

    if not args.apply:
        print("[DRY-RUN] 如要实删，加 --apply")
        conn.close()
        return

    # 备份
    bak_path = db_path.with_name(
        f"{db_path.name}.bak-fix-weekend-{date.today().isoformat()}"
    )
    if bak_path.exists():
        # 同日重复跑，覆盖最新备份
        bak_path.unlink()
    shutil.copy2(db_path, bak_path)
    print(f"[BACKUP] 已备份到 {bak_path}")

    # 删除（用 weekday>=5 双保险，strftime %w 周日=0 周六=6）
    cur = conn.execute(
        """
        DELETE FROM gene_scores
        WHERE strftime('%w', date) IN ('0', '6')
        """
    )
    deleted = cur.rowcount
    conn.commit()
    print(f"[DELETED] 删除 {deleted} 行")

    # 验证
    print()
    print("=== 验证：近 8 日分组 ===")
    for r in conn.execute(
        "SELECT date, COUNT(*) AS cnt FROM gene_scores GROUP BY date ORDER BY date DESC LIMIT 8"
    ).fetchall():
        d = r["date"]
        try:
            wd = date.fromisoformat(d).weekday()
            wd_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][wd]
        except (ValueError, TypeError):
            wd_name = "?"
        flag = "  <-- 周末!" if _is_weekend(d) else ""
        print(f"  {d} ({wd_name}) cnt={r['cnt']}{flag}")

    # 残留周末行（应为 0）
    remain = conn.execute(
        "SELECT COUNT(*) FROM gene_scores WHERE strftime('%w', date) IN ('0', '6')"
    ).fetchone()[0]
    print()
    if remain == 0:
        print("[OK] 残留周末行 = 0，清理成功")
    else:
        print(f"[FAIL] 残留周末行 = {remain}（清理失败！）", file=sys.stderr)
        sys.exit(2)

    conn.close()


if __name__ == "__main__":
    main()
