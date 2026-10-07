# -*- coding: utf-8 -*-
"""龙虎榜历史 backfill 2018-2026 → SQLite（seat-level for 跟具名游资席位策略）。

数据源：东财 datacenter RPT_BILLBOARD_DAILYDETAILSBUY/SELL（走 astock.em_get 限流+熔断）
覆盖：2018-01-01 ~ 2026-10-07（~2000 交易日）
每日：buy + sell 两个端点 → seat-level rows

输出：.vibe-research/dragon_tiger_history.db
  table dragon_tiger_rows: (trade_date, security_code, dept_name, dept_code, side, buy, sell, net, explanation, change_rate, close_price, accum_amount)
  table fetch_log: (trade_date, buy_ok, sell_ok, n_rows, fetched_at)

增量：skip 已 fetch 的 trade_date（断点续跑）
"""
from __future__ import annotations
import json
import sys
import time
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategies.hot_money_seats import fetch_billboard_for_date_meta

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / ".vibe-research"
INDEX_CACHE = DATA / "index_ohlc_cache.json"
DB_PATH = DATA / "dragon_tiger_history.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dt_backfill")

SCHEMA = """
CREATE TABLE IF NOT EXISTS dragon_tiger_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    security_code TEXT,
    dept_name TEXT,
    dept_code TEXT,
    side TEXT,
    buy REAL,
    sell REAL,
    net REAL,
    explanation TEXT,
    change_rate REAL,
    close_price REAL,
    accum_amount REAL
);
CREATE INDEX IF NOT EXISTS idx_dt_date ON dragon_tiger_rows(trade_date);
CREATE INDEX IF NOT EXISTS idx_dt_seat ON dragon_tiger_rows(dept_name);
CREATE INDEX IF NOT EXISTS idx_dt_code ON dragon_tiger_rows(security_code);

CREATE TABLE IF NOT EXISTS fetch_log (
    trade_date TEXT PRIMARY KEY,
    buy_ok INTEGER,
    sell_ok INTEGER,
    n_rows INTEGER,
    fetched_at TEXT
);
"""


def load_trading_days(start: str = "2018-01-01", end: str = "2026-10-07") -> list[str]:
    with open(INDEX_CACHE) as f:
        raw = json.load(f)
    bars = raw.get("sh.000001", [])
    return sorted(b["date"] for b in bars if "date" in b and start <= b["date"] <= end)


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def is_fetched(conn, trade_date: str) -> bool:
    r = conn.execute("SELECT buy_ok, sell_ok FROM fetch_log WHERE trade_date=?", (trade_date,)).fetchone()
    return r is not None and r[0] == 1 and r[1] == 1


def save_day(conn, trade_date: str, meta: dict) -> int:
    rows = meta["rows"]
    # 先删该日旧行（重跑安全）
    conn.execute("DELETE FROM dragon_tiger_rows WHERE trade_date=?", (trade_date,))
    conn.execute("DELETE FROM fetch_log WHERE trade_date=?", (trade_date,))
    # 插入新行
    batch = []
    for r in rows:
        batch.append((
            trade_date,
            r.get("SECURITY_CODE", ""),
            r.get("OPERATEDEPT_NAME", ""),
            str(r.get("OPERATEDEPT_CODE", "")),
            r.get("side", ""),
            r.get("BUY"),
            r.get("SELL"),
            r.get("NET"),
            r.get("EXPLANATION", ""),
            r.get("CHANGE_RATE"),
            r.get("CLOSE_PRICE"),
            r.get("ACCUM_AMOUNT"),
        ))
    conn.executemany(
        "INSERT INTO dragon_tiger_rows (trade_date,security_code,dept_name,dept_code,side,buy,sell,net,explanation,change_rate,close_price,accum_amount) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        batch,
    )
    conn.execute(
        "INSERT INTO fetch_log (trade_date,buy_ok,sell_ok,n_rows,fetched_at) VALUES (?,?,?,?,?)",
        (trade_date, int(meta["buy_ok"]), int(meta["sell_ok"]), len(rows), datetime.now().isoformat()),
    )
    conn.commit()
    return len(rows)


def backfill(start: str = "2018-01-01", end: str = "2026-10-07") -> None:
    days = load_trading_days(start, end)
    conn = init_db()
    cached = conn.execute("SELECT COUNT(*) FROM fetch_log WHERE buy_ok=1 AND sell_ok=1").fetchone()[0]
    log.info(f"[backfill] {len(days)} trading days {days[0]}~{days[-1]}, cached={cached}")

    ok = fail = skip = 0
    t0 = time.time()
    for i, d in enumerate(days):
        if is_fetched(conn, d):
            skip += 1
            continue
        meta = fetch_billboard_for_date_meta(d)
        n = save_day(conn, d, meta)
        if meta["buy_ok"] and meta["sell_ok"]:
            ok += 1
        else:
            fail += 1
        if (i + 1) % 20 == 0:
            elapsed = time.time() - t0
            rate = (i + 1 - skip) / elapsed if elapsed > 0 and (i + 1 - skip) > 0 else 0
            eta = (len(days) - i - 1) / rate if rate > 0 else 0
            log.info(f"  [{i+1}/{len(days)}] {d} ok={ok} fail={fail} skip={skip} "
                     f"rows_day={n} elapsed={elapsed:.0f}s rate={rate:.2f}/d ETA={eta:.0f}s ({eta/60:.1f}min)")

    conn.close()
    elapsed = time.time() - t0
    log.info(f"\n[done] total={len(days)} ok={ok} fail={fail} skip={skip} "
             f"elapsed={elapsed:.0f}s ({elapsed/60:.1f}min)")
    log.info(f"[saved] {DB_PATH} ({DB_PATH.stat().st_size/1024:.0f}KB)")


if __name__ == "__main__":
    start = sys.argv[1] if len(sys.argv) > 1 else "2018-01-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2026-10-07"
    backfill(start, end)
