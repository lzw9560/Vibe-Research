# -*- coding: utf-8 -*-
"""backfill 后核 bar 覆盖率——pre-2025-06-03 picks + train third（2024-06..2025-12）。

对比 backfill 前 28.4%（pre-2025-06-03）+ 38%（train third）。
不臆造——纯 cache 读取 + zt_history 查询。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
DB = ROOT / ".vibe-research" / "zt_history.db"


def _coverage(picks: list[tuple[str, str]], cache: dict) -> tuple[int, int, int]:
    """返 (has_d, has_d_and_d1, total)。has_d = pick D bar 在 cache；has_d_and_d1 = D+D+1 都在。"""
    has_d = 0
    has_d_and_d1 = 0
    for D, code in picks:
        bars = cache.get(code)
        if not bars:
            continue
        d_idx = next(
            (i for i, b in enumerate(bars) if str(b.get("date", ""))[:10] == D),
            None,
        )
        if d_idx is None:
            continue
        has_d += 1
        if d_idx + 1 < len(bars):
            has_d_and_d1 += 1
    return has_d, has_d_and_d1, len(picks)


def main() -> None:
    cache = json.loads(CACHE.read_bytes())
    print(f"cache codes={len(cache)}", flush=True)
    conn = sqlite3.connect(str(DB))

    # 1. pre-2025-06-03 picks（backfill 前基线 28.4%）
    pre = conn.execute(
        "SELECT date, code FROM zt_history WHERE date<'2025-06-03' "
        "AND lbc>=2 AND is_final=1 ORDER BY date"
    ).fetchall()
    hd, hd1, tot = _coverage([(r[0], r[1]) for r in pre], cache)
    print(
        f"\n1) pre-2025-06-03 picks: {hd}/{tot}={hd/tot*100:.1f}% have D bar "
        f"(D+D+1: {hd1}/{tot}={hd1/tot*100:.1f}%)  [baseline was 28.4%]",
        flush=True,
    )

    # 2. train third 范围（2024-06..2025-12）picks——backfill 前基线 ~38%
    train = conn.execute(
        "SELECT date, code FROM zt_history WHERE date>='2024-06-01' "
        "AND date<='2025-12-31' AND lbc>=2 AND is_final=1 ORDER BY date"
    ).fetchall()
    hd, hd1, tot = _coverage([(r[0], r[1]) for r in train], cache)
    print(
        f"2) train third (2024-06..2025-12) picks: {hd}/{tot}={hd/tot*100:.1f}% have D bar "
        f"(D+D+1: {hd1}/{tot}={hd1/tot*100:.1f}%)  [baseline was ~38%]",
        flush=True,
    )

    # 3. 全量 picks（总覆盖）
    allp = conn.execute(
        "SELECT date, code FROM zt_history WHERE lbc>=2 AND is_final=1 ORDER BY date"
    ).fetchall()
    hd, hd1, tot = _coverage([(r[0], r[1]) for r in allp], cache)
    print(
        f"3) all picks ({allp[0][0]}..{allp[-1][0]}): {hd}/{tot}={hd/tot*100:.1f}% have D bar "
        f"(D+D+1: {hd1}/{tot}={hd1/tot*100:.1f}%)",
        flush=True,
    )
    conn.close()


if __name__ == "__main__":
    main()
