# -*- coding: utf-8 -*-
"""S167 盘中微结构数据累积地基（"等 live" 路径）。

§44 reframe（S159）：edge 在盘中盘口博弈，不在 T-1 选股。S152/S156 已证否封板时间/
秒板（prior LOW），但用户选"等 live"——每日累积实时无历史的盘中微结构源，30-60 天
后用 §44v2 框架复测。本模块只**累积**，不出 edge 结论。

累积三源（date-keyed，不 prune）：
- **hithink 实时排名**（skyrocket 飙升榜 / hot_stock 热股榜 / anomaly 异动榜）——
  实时**无历史**，不快照即永久丢失。每 10min 周期快照 → `intraday_ranking_snapshots`。
- **tencent 量比 vol_ratio**（资金活跃度代理，实时点）——同周期附 hithink 快照 →
  `intraday_quote_snapshots`。
- **baostock 5min 次日冻结**（秒板/封板时间派生，多年可回补但当日 bar T+1 lag）——
  次日 09:00 冻结 prev_trading_date 涨停股 5min bars → `baostock_5min_freeze`。

**已有源不重建**：seal_intraday（S055）已每 60s 累积封单额 trajectory，独立 partitioned
SQLite，本模块不复刻（§44v2 复测时联读 seal_intraday_snapshots + 本库）。

工程底线：
- 私有 DB 在 `.vibe-research/intraday_accumulation/intraday_microstructure.db`
  （`config.INTRADAY_ACCUMULATION_DIR`，gitignored，不入 home）
- 缺数据填 None / data_status=degraded（不臆造、不伪装空榜为数据）
- hithink 走 `circuit_breaker`；涨停池 codes 走 hithink limit_up_pool（非 em_get 防封）
- schema inline `CREATE TABLE IF NOT EXISTS`（fresh DB 首连建表，避开 migration 框架接线坑）

范式复刻：`data/zt_history_store`（S078）。

spec: `specs/S167-盘中微结构数据累积/spec.md`
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any

from config import INTRADAY_ACCUMULATION_DIR

_logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(INTRADAY_ACCUMULATION_DIR, "intraday_microstructure.db")
_DB_LOCK = threading.Lock()

_SCHEMA_RANKINGS = """CREATE TABLE IF NOT EXISTS intraday_ranking_snapshots (
    date TEXT NOT NULL,             -- YYYY-MM-DD（交易日）
    ts TEXT NOT NULL,               -- 快照时间戳 ISO（分钟级）
    source TEXT NOT NULL,           -- skyrocket / hot_stock / anomaly
    code TEXT NOT NULL,             -- 6 位裸 code
    name TEXT,
    rank INTEGER,
    heat REAL,
    rank_change REAL,
    rank_trend TEXT,
    extra_json TEXT,                -- 原样保留未归一字段（异动 schema 未实测全字段）
    snapshot_at TEXT,               -- 落库时间戳
    PRIMARY KEY (date, ts, source, code)
)"""
_INDEX_RANKINGS = (
    "CREATE INDEX IF NOT EXISTS idx_rank_date_ts ON intraday_ranking_snapshots(date, ts)"
)

_SCHEMA_QUOTES = """CREATE TABLE IF NOT EXISTS intraday_quote_snapshots (
    date TEXT NOT NULL,
    ts TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    price REAL,
    change_pct REAL,
    vol_ratio REAL,                 -- 量比（资金活跃度代理）
    turnover_pct REAL,              -- 换手
    limit_up REAL,
    limit_down REAL,
    amount_wan REAL,                -- 成交额（万元）
    snapshot_at TEXT,
    PRIMARY KEY (date, ts, code)
)"""
_INDEX_QUOTES = (
    "CREATE INDEX IF NOT EXISTS idx_quote_date_ts ON intraday_quote_snapshots(date, ts)"
)

_SCHEMA_BAOSTOCK = """CREATE TABLE IF NOT EXISTS baostock_5min_freeze (
    date TEXT NOT NULL,             -- 涨停日（prev_trading_date）
    code TEXT NOT NULL,
    name TEXT,
    bars_json TEXT,                 -- 当日 5min bars（[{date,time,open,high,low,close,volume}]）
    bar_count INTEGER,
    captured_at TEXT,
    PRIMARY KEY (date, code)
)"""
_INDEX_BAOSTOCK = (
    "CREATE INDEX IF NOT EXISTS idx_bs5_date ON baostock_5min_freeze(date)"
)


def _get_conn() -> sqlite3.Connection:
    """建库 + 建三表（幂等）+ 返连接。row_factory=Row。"""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA_RANKINGS)
    conn.execute(_INDEX_RANKINGS)
    conn.execute(_SCHEMA_QUOTES)
    conn.execute(_INDEX_QUOTES)
    conn.execute(_SCHEMA_BAOSTOCK)
    conn.execute(_INDEX_BAOSTOCK)
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# 归一辅助
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    s = str(v).strip().replace(",", "")
    if not s or s in ("-", "--", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(v) -> int | None:
    f = _to_float(v)
    return int(f) if f is not None else None


# ─────────────────────────────────────────────────────────────────────────────
# 写入
# ─────────────────────────────────────────────────────────────────────────────

def save_ranking_snapshots(
    date: str, ts: str, source: str, items: list[dict[str, Any]]
) -> int:
    """批量写 hithink 排名快照（skyrocket/hot_stock/anomaly 归一后）。返回写入行数。

    幂等：PK(date, ts, source, code) INSERT OR REPLACE，同周期重跑覆盖不翻倍。
    缺字段填 None（不臆造）。空 items 返 0。
    """
    if not items:
        return 0
    snap_at = datetime.now().isoformat(timespec="seconds")
    rows = []
    for it in items:
        code = str(it.get("code", "") or "").strip()
        if not code:
            continue
        # extra_json：保留未归一字段（异动榜原样字段除 thscode/code/name 外）
        extra = {k: v for k, v in it.items()
                 if k not in ("code", "name", "rank", "heat", "rank_change", "rank_trend")}
        rows.append({
            "date": date, "ts": ts, "source": source, "code": code,
            "name": it.get("name"), "rank": _to_int(it.get("rank")),
            "heat": _to_float(it.get("heat")),
            "rank_change": _to_float(it.get("rank_change")),
            "rank_trend": it.get("rank_trend"),
            "extra_json": json.dumps(extra, ensure_ascii=False) if extra else None,
            "snapshot_at": snap_at,
        })
    if not rows:
        return 0
    conn = _get_conn()
    try:
        with _DB_LOCK:
            cur = conn.executemany(
                """INSERT OR REPLACE INTO intraday_ranking_snapshots
                (date, ts, source, code, name, rank, heat, rank_change, rank_trend,
                 extra_json, snapshot_at)
                VALUES (:date, :ts, :source, :code, :name, :rank, :heat, :rank_change,
                 :rank_trend, :extra_json, :snapshot_at)""",
                rows,
            )
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()


def save_quote_snapshots(
    date: str, ts: str, quotes: dict[str, dict[str, Any]]
) -> int:
    """批量写 tencent 量比快照。quotes: {裸code: {price, vol_ratio, ...}}。返回写入行数。

    幂等：PK(date, ts, code) INSERT OR REPLACE。缺字段 None。
    """
    if not quotes:
        return 0
    snap_at = datetime.now().isoformat(timespec="seconds")
    rows = []
    for code, q in quotes.items():
        code = str(code).strip()
        if not code or not isinstance(q, dict):
            continue
        rows.append({
            "date": date, "ts": ts, "code": code,
            "name": q.get("name"), "price": _to_float(q.get("price")),
            "change_pct": _to_float(q.get("change_pct")),
            "vol_ratio": _to_float(q.get("vol_ratio")),
            "turnover_pct": _to_float(q.get("turnover_pct")),
            "limit_up": _to_float(q.get("limit_up")),
            "limit_down": _to_float(q.get("limit_down")),
            "amount_wan": _to_float(q.get("amount_wan")),
            "snapshot_at": snap_at,
        })
    if not rows:
        return 0
    conn = _get_conn()
    try:
        with _DB_LOCK:
            cur = conn.executemany(
                """INSERT OR REPLACE INTO intraday_quote_snapshots
                (date, ts, code, name, price, change_pct, vol_ratio, turnover_pct,
                 limit_up, limit_down, amount_wan, snapshot_at)
                VALUES (:date, :ts, :code, :name, :price, :change_pct, :vol_ratio,
                 :turnover_pct, :limit_up, :limit_down, :amount_wan, :snapshot_at)""",
                rows,
            )
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()


def freeze_baostock_5min(
    date: str, code: str, name: str | None, bars: list[dict[str, Any]]
) -> int:
    """写单股 baostock 5min 次日冻结。bars: [{date,time,open,high,low,close,volume}]。

    幂等：PK(date, code) INSERT OR REPLACE。空 bars 仍写（bar_count=0，诚实记录缺数据）。
    """
    snap_at = datetime.now().isoformat(timespec="seconds")
    bars_json = json.dumps(bars, ensure_ascii=False) if bars else "[]"
    conn = _get_conn()
    try:
        with _DB_LOCK:
            conn.execute(
                """INSERT OR REPLACE INTO baostock_5min_freeze
                (date, code, name, bars_json, bar_count, captured_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (date, code, name, bars_json, len(bars), snap_at),
            )
            conn.commit()
            return 1
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 读取（供未来 §44v2 复测）
# ─────────────────────────────────────────────────────────────────────────────

def load_rankings(start: str, end: str) -> list[dict[str, Any]]:
    """读 [start, end] 排名快照（date, ts, source, rank 升序）。start/end: YYYY-MM-DD。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT date, ts, source, code, name, rank, heat, rank_change,
               rank_trend, extra_json
               FROM intraday_ranking_snapshots
               WHERE date >= ? AND date <= ? ORDER BY date, ts, source, rank""",
            (start, end),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_quotes(start: str, end: str) -> list[dict[str, Any]]:
    """读 [start, end] 量比快照（date, ts, code 升序）。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT date, ts, code, name, price, change_pct, vol_ratio,
               turnover_pct, limit_up, limit_down, amount_wan
               FROM intraday_quote_snapshots
               WHERE date >= ? AND date <= ? ORDER BY date, ts, code""",
            (start, end),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_5min_freeze(start: str, end: str) -> list[dict[str, Any]]:
    """读 [start, end] baostock 5min 冻结（date, code 升序）。bars_json 不解析（原样）。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT date, code, name, bars_json, bar_count, captured_at
               FROM baostock_5min_freeze
               WHERE date >= ? AND date <= ? ORDER BY date, code""",
            (start, end),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_accumulation_dates() -> list[str]:
    """列出有累积快照的日期（YYYY-MM-DD，升序；三表并集）。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT DISTINCT date FROM (
               SELECT date FROM intraday_ranking_snapshots
               UNION SELECT date FROM intraday_quote_snapshots
               UNION SELECT date FROM baostock_5min_freeze
               ) ORDER BY date"""
        ).fetchall()
        return [r["date"] for r in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    # 手动触发当日快照（调试用；生产由 scheduled_tasks 触发）
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "dates":
        print(list_accumulation_dates())
