# -*- coding: utf-8 -*-
"""Backfill klines for relay codes (lbc>=2) via hithink, full historical range.

Prioritizes codes with more limit-up events. Stores into baostock_kline_cache.db
via kline_cache_store.upsert_bars so _factor_helpers.load_kline_db reads them.

防封: sleep 0.4s between calls, circuit breaker auto-trips on hithink 429/5xx.
Skips codes already cached. Writes progress to stdout.
"""
from __future__ import annotations
import sys, time, sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir
from engine.kline_cache_store import get_bars, upsert_bars, get_all_codes
from data.sources.hithink_src import fetch_kline

DATA = resolve_data_dir()
ZT_DB = DATA / "zt_history.db"

START = "2024-06-01"
END = "2026-10-01"

def _ms(d: str) -> int:
    dt = datetime.fromisoformat(d, tzinfo=timezone(timedelta(hours=8)))
    return int(dt.timestamp() * 1000)

def main(max_codes: int = 3000) -> None:
    conn = sqlite3.connect(str(ZT_DB))
    rows = conn.execute(
        "SELECT code, COUNT(*) c FROM zt_history WHERE COALESCE(lbc,0)>=2 "
        "GROUP BY code ORDER BY c DESC"
    ).fetchall()
    conn.close()
    print(f"relay codes by event count: {len(rows)} total", flush=True)

    cached = set(get_all_codes())
    print(f"already cached: {len(cached)}", flush=True)

    start_ms, end_ms = _ms(START), _ms(END)
    done = 0
    skipped = 0
    failed = 0
    t0 = time.time()
    for code, cnt in rows:
        if code in cached:
            skipped += 1
            continue
        if done >= max_codes:
            break
        try:
            bars = fetch_kline(code, start_ms, end_ms, adjust="forward")
        except Exception as e:
            print(f"  {code} ERR {repr(e)[:120]}", flush=True)
            failed += 1
            time.sleep(1.0)
            continue
        if not bars:
            failed += 1
            time.sleep(0.4)
            continue
        upsert_bars(code, bars)
        done += 1
        if done % 50 == 0:
            el = time.time() - t0
            print(f"  progress: {done} fetched, {skipped} skipped, {failed} failed, "
                  f"{el:.0f}s, {done/el*60:.1f}/min", flush=True)
        time.sleep(0.4)
    print(f"DONE: {done} fetched, {skipped} skipped, {failed} failed, "
          f"{time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    main(n)
