# -*- coding: utf-8 -*-
"""S214 zt_history 历史回补脚本——hithink backfill 历史涨停池。

fork 探测（2026-09-17）确认 hithink 可回溯 2024-06（em/ths 不可回补，stale docstring
说"无可用源"只算 em/ths）。snapshot_zt_pool(date) 已有 em→ths→hithink fallback 链，
本脚本循环历史日期调它（is_final=True 终盘）。

跑法：cd backend && .venv/bin/python tools/zt_history_backfill.py --start 2025-12-01 --end 2026-09-16
限流：sleep 0.5s/日期 + 熔断（连续 5 空日期跳过）。
工程底线：hithink 走 Key env 变量（fuyao.aicubes.cn，不裸调 requests，防封 OK）。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from data.zt_history_store import snapshot_zt_pool, _DB_PATH  # noqa: E402


def trading_days(start: str, end: str) -> list[str]:
    """生成 start 到 end 的交易日（跳过周末，不含节假日——空日期 snapshot 返 0 自动跳过）。"""
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    days: list[str] = []
    d = s
    while d <= e:
        if d.weekday() < 5:  # 周一-周五
            days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return days


def backfill(start: str, end: str, sleep_s: float = 0.5, melt_empty: int = 5) -> dict:
    """循环历史日期调 snapshot_zt_pool(date, is_final=True)，回补 zt_history。"""
    days = trading_days(start, end)
    print(f"[backfill] {start} → {end}: {len(days)} 交易日候选", flush=True)
    n_ok = 0
    n_empty = 0
    n_consecutive_empty = 0
    for d in days:
        try:
            written = snapshot_zt_pool(d, is_final=True)
            if written > 0:
                n_ok += 1
                n_consecutive_empty = 0
                print(f"  {d}: +{written} 行", flush=True)
            else:
                n_empty += 1
                n_consecutive_empty += 1
                print(f"  {d}: 空（非交易日/节假日/无数据）", flush=True)
            if n_consecutive_empty >= melt_empty:
                print(f"[backfill] 连续 {melt_empty} 空日期，熔断跳过剩余", flush=True)
                break
            time.sleep(sleep_s)
        except Exception as e:  # noqa: BLE001
            print(f"  {d}: 异常 {e}", flush=True)
            time.sleep(sleep_s)
    # 验证 zt_history 日期范围
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        row = conn.execute(
            "SELECT MIN(date), MAX(date), COUNT(DISTINCT date), COUNT(*) FROM zt_history"
        ).fetchone()
    finally:
        conn.close()
    print(f"\n[backfill] 完成: ok={n_ok} empty={n_empty}", flush=True)
    print(f"[zt_history] 日期范围 {row[0]} → {row[1]}, {row[2]} 交易日, {row[3]} 行", flush=True)
    return {"ok": n_ok, "empty": n_empty, "range": (row[0], row[1]), "days": row[2], "rows": row[3]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="zt_history 历史回补（hithink backfill）")
    ap.add_argument("--start", default="2025-12-01", help="开始日期 YYYY-MM-DD")
    ap.add_argument("--end", default="2026-09-16", help="结束日期 YYYY-MM-DD")
    ap.add_argument("--sleep", type=float, default=0.5, help="限流 sleep 秒/日期")
    ap.add_argument("--melt", type=int, default=5, help="连续空日期熔断阈值")
    args = ap.parse_args()
    result = backfill(args.start, args.end, args.sleep, args.melt)
    print(result)
