# -*- coding: utf-8 -*-
"""S191 · datalake 统一目录管理 + 回放引擎（本地读回路径）。

用户原话"数据源湖共后期测试开发使用，分开设计"——datalake 是本地回放层
（供盘中策略调试回放），Turso 是云灾备层（write-only 备份），物理分离。

目录结构（resolve_data_dir()/datalake/）：
  datalake/
    stoke_YYYYMM.db      — stoke 研报/新闻/涨停归因/PE-PB（按月分库）
    ticks_YYYYMM.db      — mootdx 历史分笔（OFI proxy 用）
    seal_intraday_YYYYMM.db — 五档快照（现有，移或软链）
    baostock_kline.json  — 日 K cache（现有，移或软链）

回放引擎 replay.py 按 (date, code) 从各库拉数据按时间戳排序回放，供盘中策略调试。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from vr_paths import resolve_data_dir

DATALAKE_ROOT = resolve_data_dir() / "datalake"


def _ensure_datalake_dir() -> Path:
    """建 datalake 根目录。返路径。"""
    DATALAKE_ROOT.mkdir(parents=True, exist_ok=True)
    return DATALAKE_ROOT


def month_db(source: str, dt: datetime | None = None) -> Path:
    """返某源当月库路径。source: stoke/ticks/seal。dt 默认 now。"""
    _ensure_datalake_dir()
    dt = dt or datetime.now()
    ym = dt.strftime("%Y%m")
    return DATALAKE_ROOT / f"{source}_{ym}.db"


def _init_stoke_db(db: Path) -> None:
    """建 stoke 库表（幂等）。"""
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS research_reports (
                date TEXT, code TEXT, report_name TEXT, institution TEXT,
                rating TEXT, report_date TEXT,
                snapshot_at TEXT, raw_json TEXT,
                PRIMARY KEY (date, code, report_name, report_date)
            );
            CREATE TABLE IF NOT EXISTS news (
                date TEXT, code TEXT, title TEXT, content TEXT, time TEXT, source TEXT,
                snapshot_at TEXT,
                PRIMARY KEY (date, code, title, time)
            );
            CREATE TABLE IF NOT EXISTS strong_stocks (
                date TEXT, code TEXT, name TEXT, pct TEXT, reason TEXT, industry TEXT,
                snapshot_at TEXT,
                PRIMARY KEY (date, code)
            );
            CREATE TABLE IF NOT EXISTS pe_pb (
                date TEXT, name TEXT, pe REAL, pb REAL, snapshot_at TEXT,
                PRIMARY KEY (date, name)
            );
        """)
        conn.commit()
    finally:
        conn.close()


def save_stoke_data(date_str: str, items: dict[str, list[dict]]) -> dict:
    """沉淀 stoke 数据到 datalake/stoke_YYYYMM.db。items: {reports/news/strong/pe_pb: [...]}。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    db = month_db("stoke", dt)
    _init_stoke_db(db)
    conn = sqlite3.connect(str(db))
    saved = 0
    try:
        now = datetime.now().isoformat()
        for r in items.get("reports", []):
            conn.execute(
                "INSERT OR REPLACE INTO research_reports "
                "(date, code, report_name, institution, rating, report_date, snapshot_at, raw_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (date_str, r.get("code", ""), r.get("报告名称", r.get("report_name", "")),
                 r.get("机构", ""), r.get("东财评级", ""), r.get("日期", ""), now, ""),
            )
            saved += 1
        for n in items.get("news", []):
            conn.execute(
                "INSERT OR REPLACE INTO news (date, code, title, content, time, source, snapshot_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (date_str, n.get("code", ""), n.get("标题", n.get("title", "")),
                 n.get("内容", n.get("content", "")), n.get("时间", n.get("time", "")), "", now),
            )
            saved += 1
        for s in items.get("strong", []):
            conn.execute(
                "INSERT OR REPLACE INTO strong_stocks "
                "(date, code, name, pct, reason, industry, snapshot_at) VALUES (?,?,?,?,?,?,?)",
                (date_str, s.get("代码", s.get("code", "")), s.get("名称", s.get("name", "")),
                 str(s.get("涨跌幅", s.get("pct", ""))), s.get("入选理由", s.get("reason", "")),
                 s.get("所属行业", s.get("industry", "")), now),
            )
            saved += 1
        for p in items.get("pe_pb", []):
            conn.execute(
                "INSERT OR REPLACE INTO pe_pb (date, name, pe, pb, snapshot_at) VALUES (?,?,?,?,?)",
                (date_str, p.get("name", ""), p.get("pe"), p.get("pb"), now),
            )
            saved += 1
        conn.commit()
    finally:
        conn.close()
    return {"db": str(db), "saved": saved}


__all__ = ["DATALAKE_ROOT", "month_db", "_init_stoke_db", "save_stoke_data", "_init_ticks_db", "save_ticks"]


def _init_ticks_db(db: Path) -> None:
    """建 ticks 库表（mootdx 历史分笔，OFI proxy 用，幂等）。"""
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ticks (
                date TEXT NOT NULL,
                code TEXT NOT NULL,
                time TEXT,
                price REAL,
                vol INTEGER,
                buyorsell INTEGER,  -- 1=主动买 2=主动卖 0=中性 5/8=其他
                volume INTEGER,
                snapshot_at TEXT,
                PRIMARY KEY (date, code, time, vol)
            );
            CREATE INDEX IF NOT EXISTS idx_ticks_date_code ON ticks(date, code);
        """)
        conn.commit()
    finally:
        conn.close()


def save_ticks(date_str: str, code: str, ticks: list[dict]) -> dict:
    """沉淀 mootdx 分笔到 datalake/ticks_YYYYMM.db。ticks: [{time,price,vol,buyorsell,volume}]。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    db = month_db("ticks", dt)
    _init_ticks_db(db)
    conn = sqlite3.connect(str(db))
    try:
        now = datetime.now().isoformat()
        conn.executemany(
            "INSERT OR REPLACE INTO ticks (date, code, time, price, vol, buyorsell, volume, snapshot_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(date_str, code, t.get("time", ""), t.get("price", 0), int(t.get("vol", 0)),
              int(t.get("buyorsell", 0)), int(t.get("volume", 0)), now) for t in ticks],
        )
        conn.commit()
    finally:
        conn.close()
    return {"code": code, "date": date_str, "n_ticks": len(ticks)}
