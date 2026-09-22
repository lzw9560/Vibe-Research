# -*- coding: utf-8 -*-
"""baostock kline cache SQLite 存取层（per-code 按需查，替代全量 JSON load）。

**背景（内存泄漏根因，2026-09-22 排查）**：``baostock_kline_cache.json`` 482MB，
全量 ``json.loads`` → 2.19GB Python dict 常驻（实测 peak RSS 2190MB，
3.14M bar dicts × ~700B）。``bars_provider._CACHE`` + ``kline_resolver._CACHE``
各一份模块级全量 load，生产热路径（``journal`` daily_report / ``quant`` API /
``signal_report``）只需 per-code 查（~18 picks），全量 load 纯浪费 2.19GB 常驻内存。

**方案（Repository Pattern + SQLite WAL）**：482MB JSON → SQLite DB
（``baostock_kline_cache.db``，``code TEXT PRIMARY KEY`` + ``bars_json TEXT``）。
per-code 查 O(log n) ~2ms（PoC 验证 5248×600 bars avg 2.13ms），~0 常驻
（~300KB 临时 per 查）。WAL 模式并发读不阻塞写。refresh upsert 增量更新
（per-code，替代全量 read+dump 482MB→2.19GB 峰值）。

**迁移**：首次 ``get_bars`` 检测 SQLite 空表 → 从 JSON 自动迁移（一次性
2.19GB 峰值 ~30s）。或手动跑 ``tools/migrate_kline_cache_to_sqlite.py``。

**并发**：单 connection + ``threading.Lock`` 串行所有操作（sqlite3 connection
跨线程需同步）。per-code 2ms 串行 18 picks 36ms 可接受。WAL 允许读不阻塞写
（但单 connection 仍串行——后续如并发瓶颈可改 thread-local connection pool）。

**设计模式**：Repository Pattern——封装数据访问，消费方（bars_provider /
kline_resolver / refresh）不依赖存储细节（SQLite/JSON/mmap 可换）。

工程底线：不臆造——code 不存在/查询失败返 []，不补默认值。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from vr_paths import resolve_data_dir

_logger = logging.getLogger(__name__)

_DB_NAME = "baostock_kline_cache.db"
_JSON_NAME = "baostock_kline_cache.json"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_migrated = False


def _db_path() -> Path:
    return resolve_data_dir() / _DB_NAME


def _json_path() -> Path:
    return resolve_data_dir() / _JSON_NAME


def _get_conn() -> sqlite3.Connection:
    """单 connection（check_same_thread=False + 外层 Lock 串行，线程安全）。

    WAL 模式 + synchronous=NORMAL（事务耐崩溃 + 写不 fsync 每次，够 kline cache 场景）。
    WITHOUT ROWID：code 是主键查询，无 rowid 节省空间 + 加速 PK 查。
    """
    global _conn
    if _conn is not None:
        return _conn
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS kline ("
        "  code TEXT PRIMARY KEY,"
        "  bars_json TEXT NOT NULL"
        ") WITHOUT ROWID"
    )
    _conn = conn
    return conn


def _ensure_migrated() -> None:
    """首次访问检测 SQLite 空表 → 从 JSON 自动迁移（一次性 2.19GB 峰值）。

    幂等：``_migrated`` flag 避免反复 COUNT。JSON 也不在时标记已试（返空让
    调用方跳过，复刻 bars_provider 原 fallback-empty 范式）。
    """
    global _migrated
    if _migrated:
        return
    with _lock:
        if _migrated:
            return
        conn = _get_conn()
        n = conn.execute("SELECT COUNT(*) FROM kline").fetchone()[0]
        if n > 0:
            _migrated = True
            return
        jp = _json_path()
        if not jp.exists():
            _migrated = True
            _logger.warning("kline_cache_store: SQLite 空 + JSON 不在，返空（首次部署）")
            return
        _logger.info("kline_cache_store: SQLite 空表，从 %s 迁移（一次性 ~2GB 峰值）...", jp.name)
        try:
            data = json.loads(jp.read_bytes())
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning("kline_cache_store: JSON 损坏 %s，跳过迁移（返空，不崩）", e)
            _migrated = True
            return
        # 显式事务（isolation_level=None autocommit，BEGIN/COMMIT 包 executemany 原子；
        # crash 中途 ROLLBACK 不留残表，下次重试迁移）
        conn.execute("BEGIN")
        try:
            conn.executemany(
                "INSERT INTO kline (code, bars_json) VALUES (?, ?)",
                ((code, json.dumps(bars, ensure_ascii=False)) for code, bars in data.items()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        _migrated = True
        _logger.info("kline_cache_store: 迁移完成，%d stocks → %s", len(data), _db_path().name)


def get_bars(code: str) -> list[dict[str, Any]]:
    """per-code 查 SQLite（O(log n) ~2ms，~0 常驻，~300KB 临时）。

    返 ``[{date, open, high, low, close, volume, amount, ...}, ...]``。
    code 不存在 / 查询失败 / bars_json 损坏返 []（不臆造）。
    """
    _ensure_migrated()
    with _lock:
        conn = _get_conn()
        row = conn.execute("SELECT bars_json FROM kline WHERE code=?", (code,)).fetchone()
    if row is None:
        return []
    try:
        result = json.loads(row[0])
    except json.JSONDecodeError:
        _logger.warning("kline_cache_store: %s bars_json 损坏，返空", code)
        return []
    if not isinstance(result, list):
        _logger.warning("kline_cache_store: %s bars_json 非 list (%s)，返空", code, type(result).__name__)
        return []
    return result


def upsert_bars(code: str, bars: list[dict[str, Any]]) -> None:
    """per-code 增量更新（refresh 用，替代全量 read+dump JSON 2.19GB 峰值）。

    INSERT OR REPLACE：code 存在替换（全量覆盖），不存在插入。
    isolation_level=NORMAL autocommit，单 INSERT 原子（无需显式 commit）。
    """
    if not isinstance(bars, list):
        raise TypeError(f"upsert_bars bars must be list, got {type(bars).__name__}")
    _ensure_migrated()
    payload = json.dumps(bars, ensure_ascii=False)
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO kline (code, bars_json) VALUES (?, ?)",
            (code, payload),
        )


def upsert_many(items: list[tuple[str, list[dict[str, Any]]]]) -> int:
    """批量 upsert（refresh 多 code 用，单事务 executemany 提速）。

    Args:
        items: [(code, bars), ...]。

    Returns:
        写入行数。
    """
    _ensure_migrated()
    payload = []
    for code, bars in items:
        if not isinstance(bars, list):
            raise TypeError(f"upsert_many bars must be list for {code}, got {type(bars).__name__}")
        payload.append((code, json.dumps(bars, ensure_ascii=False)))
    if not payload:
        return 0
    with _lock:
        conn = _get_conn()
        conn.executemany(
            "INSERT OR REPLACE INTO kline (code, bars_json) VALUES (?, ?)",
            payload,
        )
    return len(payload)


def get_all_codes() -> list[str]:
    """全量 code 列表（替代 ``list(_load_cache().keys())``，~0 内存）。"""
    _ensure_migrated()
    with _lock:
        conn = _get_conn()
        return [r[0] for r in conn.execute("SELECT code FROM kline ORDER BY code")]


def load_all() -> dict[str, list[dict[str, Any]]]:
    """全量读（offline 工具兼容 ``_load_cache``；2.19GB 峰值一次性）。

    **生产热路径勿用**——用 ``get_bars(code)`` per-code（~300KB 临时 vs 2.19GB 峰值）。
    本函数供 offline 工具（s198_gate_verify / verify_gap_classification / backfill_kline_to_2018）
    全量遍历用，它们是一次性脚本，峰值可接受。
    """
    _ensure_migrated()
    with _lock:
        conn = _get_conn()
        out: dict[str, list[dict[str, Any]]] = {}
        for code, bars_json in conn.execute("SELECT code, bars_json FROM kline"):
            try:
                out[code] = json.loads(bars_json)
            except json.JSONDecodeError:
                _logger.warning("kline_cache_store: load_all code %s bars_json 损坏，跳过", code)
                continue
    return out


def invalidate() -> None:
    """清 connection + 重置迁移 flag（refresh 后 / 测试用）。

    WAL 模式下读连接自动看新 commit，但 refresh 大批量 upsert 后清连接释放
    SQLite page cache（长会话累积占 RSS）。重置 ``_migrated`` 让下次 ``get_bars``
    重新 COUNT 检测（~ms，无性能问题；防 DB 被外部删后 stale flag）。
    """
    global _conn, _migrated
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:  # noqa: BLE001
                pass
        _conn = None
        _migrated = False


# 进程退出时清 connection（释放 SQLite page cache + WAL checkpoint，防 WAL 文件残留）
import atexit  # noqa: E402

atexit.register(invalidate)


__all__ = [
    "get_bars",
    "upsert_bars",
    "upsert_many",
    "get_all_codes",
    "load_all",
    "invalidate",
]
