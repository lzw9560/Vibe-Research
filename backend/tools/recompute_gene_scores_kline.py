# -*- coding: utf-8 -*-
"""S187 · 历史因子 baostock 回溯 recompute 脚本。

对 07-09~08-14（或指定区间）逐日：
  1. 从 gene_scores DB 取该日已有 code 列表（em 破损回补写的真涨停股 code）
  2. DELETE 该日旧零因子行
  3. rebuild_date(date, codes) 走 baostock K 线重建 3 因子（非零）
  4. save_gene_scores(date, scores)

用法：
  python tools/recompute_gene_scores_kline.py --start 2026-07-09 --end 2026-08-14
  python tools/recompute_gene_scores_kline.py --start 2026-07-09 --end 2026-07-09 --dry-run  # 单日探测

为何不复用 backfill_history --source kline：后者 codes=None 扫全 DB 数百只/日（慢），
且无 DELETE 旧零行（INSERT OR REPLACE 不净表）。本脚本 per-date codes（快）+ DELETE（净）。
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from limitup_screener.data import save_gene_scores  # noqa: E402
from limitup_screener.kline_rebuild import rebuild_date  # noqa: E402
from vr_paths import resolve_data_dir  # noqa: E402


def _trading_days(start: str, end: str) -> list[str]:
    """枚举 [start, end] 区间交易日（跳周末；节假日由 DB 有无数据兜底）。"""
    from datetime import datetime, timedelta
    out: list[str] = []
    d = datetime.strptime(start, "%Y-%m-%d")
    end_d = datetime.strptime(end, "%Y-%m-%d")
    while d <= end_d:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


def _date_codes(date: str) -> list[str]:
    """从 gene_scores DB 取该日已有 code 列表（em 破损回补写的真涨停股 code）。"""
    gs = resolve_data_dir() / "gene_scores.db"
    if not gs.exists():
        return []
    conn = sqlite3.connect(str(gs), timeout=10)
    try:
        rows = conn.execute("SELECT code FROM gene_scores WHERE date=?", (date,)).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def _delete_date(date: str) -> int:
    """DELETE 该日旧零因子行，返删除数。"""
    gs = resolve_data_dir() / "gene_scores.db"
    conn = sqlite3.connect(str(gs), timeout=10)
    try:
        cur = conn.execute("DELETE FROM gene_scores WHERE date=?", (date,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


async def recompute_one(date: str, dry_run: bool = False) -> dict:
    """重算单日。返 {date, codes_in, deleted, rebuilt, nonzero}。"""
    codes = _date_codes(date)
    if not codes:
        return {"date": date, "codes_in": 0, "deleted": 0, "rebuilt": 0, "nonzero": 0,
                "note": "DB 无该日 code（跳过）"}

    deleted = _delete_date(date) if not dry_run else 0
    if dry_run:
        return {"date": date, "codes_in": len(codes), "deleted": 0, "rebuilt": 0, "nonzero": 0,
                "note": "dry-run 跳过写"}

    scores = await rebuild_date(date, codes=codes)
    if scores:
        save_gene_scores(date, scores)
    nonzero = sum(1 for s in scores if s.total_score > 0)
    return {"date": date, "codes_in": len(codes), "deleted": deleted,
            "rebuilt": len(scores), "nonzero": nonzero}


async def recompute_range(start: str, end: str, dry_run: bool = False) -> None:
    dates = _trading_days(start, end)
    print(f"recompute {start}~{end}：{len(dates)} 个交易日，dry_run={dry_run}")
    total_rebuilt = 0
    total_nonzero = 0
    for i, d in enumerate(dates):
        r = await recompute_one(d, dry_run=dry_run)
        print(f"[{i+1}/{len(dates)}] {d}: codes_in={r['codes_in']} deleted={r['deleted']} "
              f"rebuilt={r['rebuilt']} nonzero={r['nonzero']} {r.get('note','')}")
        total_rebuilt += r["rebuilt"]
        total_nonzero += r["nonzero"]
    print("=" * 50)
    print(f"完成：rebuilt={total_rebuilt} nonzero={total_nonzero}")


def main() -> None:
    p = argparse.ArgumentParser(description="S187 历史因子 baostock 回溯 recompute")
    p.add_argument("--start", required=True, help="起始日 YYYY-MM-DD")
    p.add_argument("--end", required=True, help="结束日 YYYY-MM-DD")
    p.add_argument("--dry-run", action="store_true", help="只探测不写")
    args = p.parse_args()
    asyncio.run(recompute_range(args.start, args.end, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
