# -*- coding: utf-8 -*-
"""Fetch dividend data from baostock for all long-range codes, cache to JSON.

Run in background; explore_event_dividend-exright.py reads the cache.
"""

from __future__ import annotations
import json
import sqlite3
import sys
import time
from pathlib import Path

import baostock as bs

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
DIV_CACHE = DATA / "dividend_events_cache.json"
YEARS = list(range(2018, 2026))


def get_long_range_codes() -> list[str]:
    """Codes with kline data from <= 2018-06 (full 8-year history)."""
    conn = sqlite3.connect(str(KLINE_DB))
    codes: list[str] = []
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if bars and min(b["date"] for b in bars) <= "2018-06-01":
            codes.append(code)
    conn.close()
    return sorted(codes)


def fetch_all() -> list[dict]:
    codes = get_long_range_codes()
    print(f"[fetch] {len(codes)} long-range codes × {len(YEARS)} years = {len(codes) * len(YEARS)} calls")
    events: list[dict] = []
    lg = bs.login()
    print(f"[fetch] login: {lg.error_code} {lg.error_msg}")
    t0 = time.time()
    done = 0
    for code in codes:
        bs_code = ("sh." if code.startswith("6") else "sz.") + code
        for yr in YEARS:
            try:
                rs = bs.query_dividend_data(code=bs_code, year=yr, yearType="operate")
                while rs.next():
                    row = rs.get_row_data()
                    oper_date = row[6]  # dividOperateDate
                    if not oper_date:
                        continue
                    events.append(
                        {
                            "code": code,
                            "ex_date": oper_date,
                            "year": yr,
                            "cash_before_tax": _to_float(row[9]),
                            "cash_after_tax": _to_float(row[10]),
                            "stocks_ps": _to_float(row[11]),
                            "reserve_to_stock": _to_float(row[13]),
                        }
                    )
            except Exception as e:
                print(f"[fetch] ERROR {bs_code} {yr}: {e}", file=sys.stderr)
            time.sleep(0.15)
        done += 1
        if done % 50 == 0:
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta = (len(codes) - done) / rate if rate > 0 else 0
            print(
                f"[fetch] {done}/{len(codes)} codes, {len(events)} events, {elapsed:.0f}s elapsed, ETA {eta:.0f}s",
                flush=True,
            )
    bs.logout()
    elapsed = time.time() - t0
    print(f"[fetch] DONE: {len(events)} events in {elapsed:.0f}s")
    return events


def _to_float(s: str) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def main() -> None:
    if DIV_CACHE.exists():
        with open(DIV_CACHE) as f:
            cached = json.load(f)
        print(f"[fetch] cache exists: {len(cached)} events. Use --refresh to re-fetch.")
        return
    events = fetch_all()
    with open(DIV_CACHE, "w") as f:
        json.dump(events, f, ensure_ascii=False)
    print(f"[fetch] saved {len(events)} events to {DIV_CACHE}")


if __name__ == "__main__":
    main()
