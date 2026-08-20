# -*- coding: utf-8 -*-
"""S087 R10：run_funnel 结果持久化缓存（落本地 sqlite 表）。

进程级 `_FUNNEL_CACHE`（funnel.py）重启即丢；本模块把 FunnelResult 落库，前端 tab
读缓存秒开，"重新跑"按钮走 POST 实跑 + 写缓存。表存 `VR_DATA_DIR/funnel_cache.db`
（私有数据，不进 git）。缓存拿不到 → 调用方 fallback 实跑（R10 兜底）。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from threading import Lock
from typing import TYPE_CHECKING

from vr_paths import resolve_data_dir

if TYPE_CHECKING:
    from candidate_funnel.models import FunnelResult

_logger = logging.getLogger("vibe-research")

# 动态算 DB path（跟随 VR_DATA_DIR，测试 conftest 设临时目录时隔离，不污染生产 .vibe-research）
_DB_NAME = "funnel_cache.db"
_LOCK = Lock()


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(resolve_data_dir() / _DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS funnel_results (
            date TEXT NOT NULL,
            stage TEXT NOT NULL,
            result_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (date, stage)
        )
        """
    )
    return conn


def save_funnel_result(date: str, stage: str, result: "FunnelResult") -> None:
    """落库 FunnelResult（date+stage 唯一键，OR REPLACE）。

    失败只 warning 不抛（缓存写失败不影响主流程——内存缓存仍可用）。
    """
    try:
        js = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with _LOCK:
            conn = _get_db()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO funnel_results "
                    "(date, stage, result_json, updated_at) VALUES (?, ?, ?, ?)",
                    (date, stage, js, now),
                )
                conn.commit()
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("funnel_cache 落库失败 date=%s stage=%s: %s", date, stage, exc)


def load_funnel_result(date: str, stage: str = "all") -> "FunnelResult | None":
    """读缓存 FunnelResult；缺/损坏返 None（调用方 fallback 实跑）。"""
    from candidate_funnel.models import FunnelResult  # noqa: PLC0415

    with _LOCK:
        conn = _get_db()
        try:
            row = conn.execute(
                "SELECT result_json, updated_at FROM funnel_results WHERE date=? AND stage=?",
                (date, stage),
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    try:
        return FunnelResult.model_validate_json(row["result_json"])
    except Exception as exc:  # noqa: BLE001 — 损坏缓存降级，调 fallback 实跑
        _logger.warning("funnel_cache 损坏 date=%s stage=%s: %s", date, stage, exc)
        return None


def list_cached_dates() -> list[str]:
    """有缓存的日期列表（降序，近 60 日）。"""
    with _LOCK:
        conn = _get_db()
        try:
            rows = conn.execute(
                "SELECT DISTINCT date FROM funnel_results ORDER BY date DESC LIMIT 60"
            ).fetchall()
        finally:
            conn.close()
    return [r["date"] for r in rows]
