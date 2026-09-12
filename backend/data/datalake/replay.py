# -*- coding: utf-8 -*-
"""S191 · datalake 回放引擎（本地读回路径，供盘中策略调试回放）。

按 (date, code) 从 datalake 各库拉数据按时间戳排序回放，模拟实时。
用户"模拟实时交易"意图——Turso 是云灾备，datalake 是本地回放层。

用法：
  from data.datalake.replay import replay_day
  events = replay_day("2026-09-11", ["000001","600000"])  # 按时间戳排序的盘中事件流
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from data.datalake.store import DATALAKE_ROOT, month_db


def load_ticks(date_str: str, code: str) -> list[dict]:
    """从 datalake/ticks_YYYYMM.db 拉某 code 某 date 分笔（mootdx tick）。

    返 [{time, price, vol, buyorsell, ...}] 按时间排序。
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    db = month_db("ticks", dt)
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM ticks WHERE date=? AND code=? ORDER BY time",
            (date_str, code),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_stoke(date_str: str, kind: str = "strong") -> list[dict]:
    """从 datalake/stoke_YYYYMM.db 拉研报/新闻/强势涨停/PE-PB。kind: reports/news/strong/pe_pb。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    db = month_db("stoke", dt)
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    table = {"reports": "research_reports", "news": "news", "strong": "strong_stocks", "pe_pb": "pe_pb"}.get(kind, "strong_stocks")
    try:
        rows = conn.execute(f"SELECT * FROM {table} WHERE date=?", (date_str,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def replay_day(date_str: str, codes: list[str]) -> dict:
    """回放某日某些股的盘中事件流（模拟实时）。

    返 {date, codes, ticks_by_code: {code: [tick...]}, stoke: {strong/reports/news}}。
    供盘中策略调试——从 datalake 读回历史数据按时间戳回放，不依赖 live。
    """
    ticks_by_code = {c: load_ticks(date_str, c) for c in codes}
    stoke_strong = load_stoke(date_str, "strong")
    return {
        "date": date_str,
        "codes": codes,
        "ticks_by_code": ticks_by_code,
        "stoke_strong": stoke_strong,
        "note": "datalake 本地回放（Turso 是云灾备，datalake 是本地回放层，物理分离）",
    }


__all__ = ["load_ticks", "load_stoke", "replay_day"]
