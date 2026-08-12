# -*- coding: utf-8 -*-
"""S061 预测账本历史回填——从 gene_scores 涨停候选回填次日溢价预测 + 真实对账。

口径（诚实、零臆造）：
- 读 gene_scores 中 qualify=1 的历史候选，每条生成一个 next_day_premium 预测
  （source='manual', signal_ref='backfill:gene_scores'）——source 用 manual 与
  未来 live 入册的 funnel_candidate 区分，不撞 UNIQUE(stated_at,source,code)。
- 对账：信号日 close → 次日 close 算 actual_return。K 线窗口未覆盖 / 无次日 bar
  → status='voided'，attribution 标原因，不臆造收益。最近一日（无次日 close）→ pending。
- 幂等：signal_ref='backfill:gene_scores' 标记，重跑前先删旧回填行。
- 按股缓存 K 线（一个 code 一次 mootdx 拉取覆盖整个窗口），避免逐日重复请求。

用法：
    python backfill_prediction_ledger.py --days 30 --dry-run   # 只探测，不写 DB
    python backfill_prediction_ledger.py --days 30
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from data.mappers import kline_from_mootdx  # noqa: E402
from config import WINRATE_DB_PATH  # noqa: E402

_SYNTH_REF = "backfill:gene_scores"
KLINE_OFFSET = 220  # 覆盖 ~150 交易日窗口（全量 gene_scores 范围）留余量
QUALIFY_THRESHOLD = 50.0  # = GENE_QUALIFY_THRESHOLD；qualify 标志历史欠填，用分数阈值为准


def _gene_dates(days: int) -> list[str]:
    """gene_scores 最近 days 个有合格候选（total_score≥阈值）的日期，升序。"""
    from limitup_screener.data import get_db
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT date FROM gene_scores WHERE total_score >= ? "
        "ORDER BY date DESC LIMIT ?",
        (QUALIFY_THRESHOLD, days),
    ).fetchall()
    conn.close()
    return sorted(r["date"] for r in rows)


def _candidates_for_dates(dates: list[str]) -> list[dict]:
    """取这些日期的合格候选（date/code/name/total_score）。"""
    if not dates:
        return []
    ph = ",".join("?" * len(dates))
    from limitup_screener.data import get_db
    conn = get_db()
    rows = conn.execute(
        f"SELECT date, code, name, total_score FROM gene_scores "
        f"WHERE total_score >= ? AND date IN ({ph}) ORDER BY date, total_score DESC",
        [QUALIFY_THRESHOLD, *dates],
    ).fetchall()
    conn.close()
    return [{"date": r["date"], "code": r["code"], "name": r["name"] or r["code"],
             "score": r["total_score"] or 0.0} for r in rows]


def _fetch_bars(code: str) -> list:
    """拉取个股 K 线（mootdx），返回 Kline bar 列表；失败返空。"""
    try:
        raw = astock.kline(code, category=4, offset=KLINE_OFFSET)
        return kline_from_mootdx(code, raw).bars or []
    except Exception:
        return []


def backfill(days: int = 30, dry_run: bool = False) -> dict:
    dates = _gene_dates(days)
    if not dates:
        return {"written": 0, "msg": "无 qualify=1 的 gene_scores 日期"}
    cands = _candidates_for_dates(dates)

    # 按 code 聚合，便于一次拉取覆盖该股全部窗口日
    by_code: dict[str, list[dict]] = {}
    for c in cands:
        by_code.setdefault(c["code"], []).append(c)

    rows_out: list[dict] = []
    kline_cache: dict[str, list] = {}
    codes = list(by_code.keys())
    for idx, code in enumerate(codes, 1):
        bars = kline_cache.get(code)
        if bars is None:
            bars = _fetch_bars(code)
            kline_cache[code] = bars
            time.sleep(0.08)  # mootdx 轻限流
        idx_by_date = {}
        for i, b in enumerate(bars):
            idx_by_date.setdefault((b.date or "")[:10], i)
        for c in by_code[code]:
            d = c["date"]
            i = idx_by_date.get(d)
            if i is None:
                rows_out.append({**c, "status": "voided",
                                 "attribution": "K线窗口未覆盖该日", "baseline": None,
                                 "actual": None, "due": None})
                continue
            target_close = bars[i].close
            if i + 1 < len(bars):
                next_bar = bars[i + 1]
                next_close = next_bar.close
                due = (next_bar.date or "")[:10]
                actual = round((next_close - target_close) / target_close, 6) if target_close else None
                status = "hit" if (actual is not None and actual > 0) else "miss"
                rows_out.append({**c, "status": status, "attribution": None,
                                 "baseline": target_close, "actual": actual, "due": due})
            else:
                rows_out.append({**c, "status": "pending", "attribution": "次日未收盘",
                                 "baseline": target_close, "actual": None, "due": None})
        if idx % 50 == 0:
            print(f"[backfill_prediction_ledger] {idx}/{len(codes)} 股处理完", flush=True)

    if dry_run:
        return {"dry_run": True, "candidates": len(cands), "codes": len(codes),
                "rows": len(rows_out),
                "hit": sum(1 for r in rows_out if r["status"] == "hit"),
                "miss": sum(1 for r in rows_out if r["status"] == "miss"),
                "voided": sum(1 for r in rows_out if r["status"] == "voided"),
                "pending": sum(1 for r in rows_out if r["status"] == "pending")}

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    conn = sqlite3.connect(WINRATE_DB_PATH)
    try:
        conn.execute("DELETE FROM prediction_ledger WHERE signal_ref = ?", (_SYNTH_REF,))
        batch = [(
            r["date"], "manual", _SYNTH_REF, r["code"], r["name"],
            "next_day_premium", r["baseline"], ">0", 1,
            r["due"] or r["date"], r["actual"], r["status"], r["attribution"],
            now if r["status"] in ("hit", "miss") else None,
        ) for r in rows_out]
        cols = ("stated_at,source,signal_ref,code,name,prediction_type,"
                "baseline_price,expected,horizon,due_date,actual_return,"
                "status,attribution,verified_at")
        ph = ",".join(["?"] * len(cols.split(",")))
        conn.executemany(
            f"INSERT INTO prediction_ledger ({cols}) VALUES ({ph})",
            batch,
        )
        conn.commit()
    finally:
        conn.close()

    return {"written": len(rows_out), "candidates": len(cands), "codes": len(codes),
            "hit": sum(1 for r in rows_out if r["status"] == "hit"),
            "miss": sum(1 for r in rows_out if r["status"] == "miss"),
            "voided": sum(1 for r in rows_out if r["status"] == "voided"),
            "pending": sum(1 for r in rows_out if r["status"] == "pending")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    print(backfill(a.days, a.dry_run))
