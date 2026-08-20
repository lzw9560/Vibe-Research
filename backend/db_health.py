# -*- coding: utf-8 -*-
"""S089 A1：SQLite 连接健康加固统一工具。

所有 DB 访问点逐步替换为 ``get_healthy_conn``，保证：

- ``PRAGMA journal_mode=WAL`` —— 写入不阻塞读（单进程软并发下避免 ``database is locked``）
- ``PRAGMA busy_timeout=5000`` —— 锁竞争时等待 5s 而非立即报错
- ``PRAGMA foreign_keys=ON`` —— 外键约束生效
- ``row_factory = sqlite3.Row`` —— 统一 dict 风格访问

新建 DB 也会自动启用 WAL，无需额外迁移脚本。既有 DB（8 个未启用）由
``backend/tools/enable_wal_all_dbs.py`` 一次性补齐。
"""

from __future__ import annotations

import logging
import sqlite3

_logger = logging.getLogger(__name__)

#: gene_scores 覆盖索引触发阈值（spec E1：行数 > 50,000 才建）
_GENE_SCORES_COVER_INDEX_THRESHOLD = 50_000


def get_healthy_conn(db_path: str, check_same_thread: bool = True) -> sqlite3.Connection:
    """统一连接初始化：WAL + busy_timeout=5000 + 外键 + Row。

    Args:
        db_path: SQLite 数据库文件路径。
        check_same_thread: 传 False 允许跨线程复用单连接（高频写入 DB 配合
            模块级 ``_DB_LOCK`` 串行化写入用，见 ``seal_intraday_collector`` /
            ``limitup_screener.data``）。默认 True（常规 per-call 连接）。

    Returns:
        配置好 PRAGMA 的 ``sqlite3.Connection``（调用方负责 close，或复用
        模块级单连接时不 close）。
    """
    conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_gene_scores_cover_index(db_path: str) -> bool:
    """S089 E1：gene_scores 覆盖索引兜底预案（条件触发）。

    离线分析脚本 6 处全表扫描 gene_scores（spec §2.3 摸底）。当前 6,943 行不急，
    行数 > 50,000 时建覆盖索引 ``idx_gene_scores_cover(date, code, data_source,
    total_score)`` 兜底，避免 3 年 ~33,000 行仍不触发（阈值保守留余量）。

    Args:
        db_path: gene_scores.db 全路径（``config.GENE_SCORES_DB_PATH``）。

    Returns:
        True 表示已创建（或已存在）；False 表示跳过（行数不足或表不存在）。
    """
    import os

    if not os.path.exists(db_path):
        _logger.info("[gene_scores_cover] %s 不存在，跳过", db_path)
        return False

    conn = sqlite3.connect(db_path)
    try:
        # 表不存在 → 跳过（fresh env 未跑迁移）
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='gene_scores'"
        ).fetchone()
        if not row:
            _logger.info("[gene_scores_cover] gene_scores 表不存在，跳过")
            return False
        count = conn.execute("SELECT COUNT(*) FROM gene_scores").fetchone()[0]
        if count <= _GENE_SCORES_COVER_INDEX_THRESHOLD:
            _logger.info(
                "[gene_scores_cover] 行数 %d <= %d，跳过覆盖索引",
                count, _GENE_SCORES_COVER_INDEX_THRESHOLD,
            )
            return False
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gene_scores_cover "
            "ON gene_scores(date, code, data_source, total_score)"
        )
        conn.commit()
        _logger.info(
            "[gene_scores_cover] 行数 %d > %d，已建覆盖索引 idx_gene_scores_cover",
            count, _GENE_SCORES_COVER_INDEX_THRESHOLD,
        )
        return True
    finally:
        conn.close()
