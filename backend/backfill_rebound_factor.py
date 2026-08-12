# -*- coding: utf-8 -*-
"""S053 R4 回填脚本——逐日重算 gene_scores 的 factor_rebound_rate。

修完 R1-R3 后，历史 gene_scores 的 factor_rebound_rate 仍恒 0（旧公式算的）。
本脚本逐日调 precompute_daily_async 重算，让因子值不再恒 0。

用法：
    python backfill_rebound_factor.py --days 30           # 重算近 30 日
    python backfill_rebound_factor.py --days 30 --dry-run # 只列日期不执行
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import GENE_SCORES_DB_PATH  # noqa: E402


def _gene_dates(days: int) -> list[str]:
    """gene_scores 最近 days 个有数据的日期，升序。"""
    conn = sqlite3.connect(GENE_SCORES_DB_PATH)
    rows = conn.execute(
        "SELECT DISTINCT date FROM gene_scores ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    conn.close()
    return sorted(r[0] for r in rows)


async def _backfill_async(days: int, dry_run: bool) -> dict:
    from limitup_screener.service import precompute_daily_async

    dates = _gene_dates(days)
    if not dates:
        return {"backfilled": 0, "msg": "无 gene_scores 日期"}

    print(f"[backfill_rebound] 目标 {len(dates)} 日: {dates[0]}~{dates[-1]}", flush=True)

    if dry_run:
        return {"dry_run": True, "dates": dates}

    success = 0
    failed = 0
    for i, d in enumerate(dates, 1):
        try:
            await precompute_daily_async(d)
            success += 1
            if i % 5 == 0:
                print(f"[backfill_rebound] {i}/{len(dates)} 完成", flush=True)
            await asyncio.sleep(0.5)  # em_get 轻限流
        except Exception as exc:
            failed += 1
            print(f"[backfill_rebound] {d} 失败: {exc}", flush=True)

    return {"backfilled": success, "failed": failed, "total": len(dates)}


def backfill(days: int = 30, dry_run: bool = False) -> dict:
    return asyncio.run(_backfill_async(days, dry_run))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    print(backfill(a.days, a.dry_run))
