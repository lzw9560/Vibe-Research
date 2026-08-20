# -*- coding: utf-8 -*-
"""S089 B1-B3：seal_intraday_snapshots 分表分库路由层。

设计见 ``specs/S089-SQLite并发性能加固与分表分库/spec.md`` §5.1。

分库命名：``seal_intraday_YYYY.db``（按年分库）
分表命名：``seal_intraday_snapshots_YYYYMM``（按月分表）

路由三件套：
- ``resolve_partition(date_str)`` —— date → (db_path, table_name) 纯映射，不开 DB
- ``ensure_partition(date_str)`` —— resolve + 幂等建表建索引
- ``get_latest_partition()`` —— 当年最新月表（SELECT MAX(date) 路由用）

查询模式经摸底 100% 带 date 或 code+date，无跨月范围扫描，分表后每查询
先 ``resolve_partition(date)`` 再查分表，路由对消费方透明。

兼容 S070 R6：分表 DDL 含 ``low_price`` + ``limit_pct`` 字段（S070 R6.1
已 ALTER 加列，新分表直接带，省迁移）。S070 R7 派生查询实现时调本路由。
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import sqlite3

from config import PRIVATE_DATA_DIR, SEAL_INTRADAY_DIR, seal_intraday_db_path
from db_health import get_healthy_conn

_logger = logging.getLogger(__name__)


def resolve_partition(date_str: str) -> tuple[str, str]:
    """date → (db_path, table_name)。

    Args:
        date_str: ``'YYYY-MM-DD'`` 格式日期。

    Returns:
        ``(db_path, table_name)``。例：
        ``'2026-08-20'`` → ``('.vibe-research/seal_intraday_2026.db',
        'seal_intraday_snapshots_202608')``。

    纯映射，不打开 DB、不建表。调用方需写数据时应先调 ``ensure_partition``。
    """
    year = date_str[:4]
    # '2026-08' → '202608'
    month = date_str[:7].replace("-", "")
    db_path = seal_intraday_db_path(year)
    table_name = f"seal_intraday_snapshots_{month}"
    return db_path, table_name


def ensure_partition(date_str: str) -> tuple[str, str]:
    """resolve + 幂等建表建索引。

    幂等（``CREATE IF NOT EXISTS``）：重复调用同一 date 不报错、不重建。
    DDL 与原 ``seal_intraday_snapshots`` 表一致，含 ``low_price`` +
    ``limit_pct`` 字段（兼容 S070 R6.1 已落地的列）。
    3 个索引对齐原表：``(date, code)`` / ``(code, ts)`` / ``(ts)``。

    Args:
        date_str: ``'YYYY-MM-DD'`` 格式日期。

    Returns:
        ``(db_path, table_name)``，表+索引已就绪可直接 INSERT/SELECT。
    """
    db_path, table = resolve_partition(date_str)
    conn = get_healthy_conn(db_path)
    try:
        # YYYYMM 段取 table_name 后缀（seal_intraday_snapshots_YYYYMM → YYYYMM）
        yyyymm = table.rsplit("_", 1)[-1]
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                date TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                pool TEXT,
                price REAL,
                seal_amount REAL,
                open_count REAL,
                first_seal_time REAL,
                consec_boards REAL,
                sector TEXT,
                float_market_cap REAL,
                index_5min_change REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                low_price REAL,
                limit_pct REAL
            );
            CREATE INDEX IF NOT EXISTS idx_{yyyymm}_date_code
                ON {table}(date, code);
            CREATE INDEX IF NOT EXISTS idx_{yyyymm}_code_ts
                ON {table}(code, ts);
            CREATE INDEX IF NOT EXISTS idx_{yyyymm}_ts
                ON {table}(ts);
            """
        )
        conn.commit()
    finally:
        conn.close()
    return db_path, table


def get_latest_partition() -> tuple[str, str] | None:
    """路由到当年最新月表（SELECT MAX(date) 路由用）。

    遍历当年库的所有 ``seal_intraday_snapshots_YYYYMM`` 表，取最大的 YYYYMM。
    无表时返回 None（调用方自降级，不臆造）。

    Returns:
        ``(db_path, table_name)`` 指向当年最大月份的分表；当年库不存在或
        无分表时返回 ``None``。
    """
    year = str(_dt.date.today().year)
    db_path = seal_intraday_db_path(year)
    if not os.path.exists(db_path):
        return None
    conn = get_healthy_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name LIKE 'seal_intraday_snapshots_%'"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None
    # 取 YYYYMM 后缀，取最大（字典序 = 时间序，YYYYMM 定长 6）
    months = [r["name"].rsplit("_", 1)[-1] for r in rows]
    latest = max(months)
    return db_path, f"seal_intraday_snapshots_{latest}"
