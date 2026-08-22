# -*- coding: utf-8 -*-
"""seat_engine 数据层 —— SQLite 持久化（S094：JSON → seat_profiles 宽表）。

合并 A 链路（seat_engine）与 B 链路（hot_money_seats）到同一张宽表。
A 字段（total_*/avg_*/net_amt/stock_cooldown/last_seen/seat_type）由本模块读写；
B 字段（next_day_sell_rate/appearance_count/confidence/source/note）由
strategies.hot_money_seats 读写。两边通过 seat_name 主键关联。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from config import SEAT_PROFILES_DB_PATH
from migrations import MigrationManager
from seat_engine.models import SeatProfile

_DB_PATH = SEAT_PROFILES_DB_PATH
_LOCK = threading.Lock()


def _migrate_schema() -> None:
    """建表（幂等，模块 import 时自动跑）。"""
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    sql = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "seat_engine" / "20260823-001_create_seat_profiles.sql"
    ).read_text(encoding="utf-8")
    MigrationManager(db_path=_DB_PATH).upgrade([{
        "version": "20260823-001",
        "name": "create_seat_profiles",
        "sql": sql,
    }])


# 模块 import 时自动建表（幂等），镜像 limitup_sti/__init__.py 模式
try:
    _migrate_schema()
except Exception:
    pass


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


_A_FIELDS = (
    "total_appearances",
    "total_buy_amt",
    "total_sell_amt",
    "net_amt",
    "avg_buy_amt",
    "avg_sell_amt",
    "stock_cooldown",
    "last_seen",
    "seat_type",
)


def load_profiles_from_db() -> dict:
    """Load persisted seat profiles from SQLite (链路 A 字段)。

    返回 {seat_name: {字段...}} dict，与旧 JSON 版返回类型一致（调用方无感）。
    表不存在或空库返 {}。
    """
    try:
        conn = _get_conn()
    except Exception:
        return {}
    try:
        cursor = conn.execute(
            "SELECT seat_name, total_appearances, total_buy_amt, total_sell_amt, "
            "net_amt, avg_buy_amt, avg_sell_amt, stock_cooldown, last_seen, seat_type "
            "FROM seat_profiles"
        )
        result: dict = {}
        for row in cursor.fetchall():
            result[row["seat_name"]] = {
                "seat_name": row["seat_name"],
                "total_appearances": row["total_appearances"] or 0,
                "total_buy_amt": row["total_buy_amt"] or 0.0,
                "total_sell_amt": row["total_sell_amt"] or 0.0,
                "net_amt": row["net_amt"] or 0.0,
                "avg_buy_amt": row["avg_buy_amt"] or 0.0,
                "avg_sell_amt": row["avg_sell_amt"] or 0.0,
                "stock_cooldown": row["stock_cooldown"] or 0,
                "last_seen": row["last_seen"] or "",
                "seat_type": row["seat_type"] or "inactive",
            }
        return result
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def save_profiles_to_db(profiles: dict) -> None:
    """Persist seat profiles to SQLite (UPSERT，链路 A 字段)。

    INSERT OR REPLACE 保留 B 字段（next_day_sell_rate 等）不覆盖——
    用 COALESCE 从旧行取 B 字段，避免 REPLACE 清空 B 列。
    profiles: {seat_name: {字段...}}，与旧 JSON 版入参一致。
    """
    if not profiles:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _LOCK:
        conn = _get_conn()
        try:
            for name, data in profiles.items():
                # COALESCE 保留旧行的 B 字段（hot_money_seats 写入），避免被 REPLACE 清空
                conn.execute(
                    """
                    INSERT INTO seat_profiles (
                        seat_name, total_appearances, total_buy_amt, total_sell_amt,
                        net_amt, avg_buy_amt, avg_sell_amt, stock_cooldown, last_seen,
                        seat_type, next_day_sell_rate, appearance_count, confidence,
                        source, note, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        COALESCE((SELECT next_day_sell_rate FROM seat_profiles WHERE seat_name=?), NULL),
                        COALESCE((SELECT appearance_count FROM seat_profiles WHERE seat_name=?), NULL),
                        COALESCE((SELECT confidence FROM seat_profiles WHERE seat_name=?), NULL),
                        COALESCE((SELECT source FROM seat_profiles WHERE seat_name=?), NULL),
                        COALESCE((SELECT note FROM seat_profiles WHERE seat_name=?), NULL),
                        ?
                    )
                    ON CONFLICT(seat_name) DO UPDATE SET
                        total_appearances=excluded.total_appearances,
                        total_buy_amt=excluded.total_buy_amt,
                        total_sell_amt=excluded.total_sell_amt,
                        net_amt=excluded.net_amt,
                        avg_buy_amt=excluded.avg_buy_amt,
                        avg_sell_amt=excluded.avg_sell_amt,
                        stock_cooldown=excluded.stock_cooldown,
                        last_seen=excluded.last_seen,
                        seat_type=excluded.seat_type,
                        updated_at=excluded.updated_at
                    """,
                    (
                        name,
                        data.get("total_appearances", 0),
                        data.get("total_buy_amt", 0.0),
                        data.get("total_sell_amt", 0.0),
                        data.get("net_amt", 0.0),
                        data.get("avg_buy_amt", 0.0),
                        data.get("avg_sell_amt", 0.0),
                        data.get("stock_cooldown", 0),
                        data.get("last_seen", ""),
                        data.get("seat_type", "inactive"),
                        name, name, name, name, name,  # COALESCE 子查询的 seat_name 参数
                        now,
                    ),
                )
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
        finally:
            conn.close()
