"""SnapshotStore——SQLite append-only PIT (point-in-time) 快照存储。

设计文档：specs/S162-反前视引擎三层/PIT-store-design.md §2.2-§2.3

核心不变量：
- **append-only / 不可变**：仅 INSERT，无 UPDATE/DELETE。同 (source, data_date, as_of)
  再 ``put`` 创建新行（snapshot_id 递增），不覆盖旧行——前复权 mutation 锁定靠此。
- **零新依赖**：SQLite + as_of column（匹配项目 JSON+SQLite 全栈）。
- **双保险建表**：``_ensure_schema`` 防御性幂等 CREATE IF NOT EXISTS（store 一构造即有表）；
  ``run_migrations`` 走 MigrationManager 版本跟踪（约定一致，供 startup 显式调用）。

存储路径：``<VR_DATA_DIR>/pit_store/pit_store.db``（.vibe-research 子目录，gitignored）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from vr_paths import BEIJING_TZ, resolve_data_dir

logger = logging.getLogger(__name__)

#: 幂等建表 SQL（与 migrations/pit_store/20260906-001_create_snapshots.sql 同步）。
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of TEXT NOT NULL,
  data_date TEXT,
  source TEXT NOT NULL,
  query_spec TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  raw_blob BLOB,
  fetched_at TEXT NOT NULL,
  generator_commit TEXT
);
CREATE INDEX IF NOT EXISTS idx_as_of ON snapshots(as_of);
CREATE INDEX IF NOT EXISTS idx_source_date ON snapshots(source, data_date);
"""


def _default_db_path() -> Path:
    """默认 DB 路径：<私有数据根>/pit_store/pit_store.db（gitignored，绝不进 git）。"""
    return resolve_data_dir() / "pit_store" / "pit_store.db"


def _now_iso() -> str:
    """取数时刻 ISO（北京时区 UTC+8，精确到秒——杜绝 naive datetime 时区 bug）。"""
    return datetime.now(BEIJING_TZ).isoformat(timespec="seconds")


class SnapshotStore:
    """append-only PIT 快照存储。不可变——不提供 UPDATE/DELETE 方法。"""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path) if db_path is not None else str(_default_db_path())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # ── 内部 ────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """新连接（check_same_thread=False 适配 FastAPI 多线程；row_factory Row 便于 dict 化）。"""
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        """幂等建表（防御性自建；run_migrations 另走版本跟踪，双保险）。"""
        conn = self._conn()
        try:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    # ── 写入（append-only，唯一 mutator）────────────────────────────────

    def put(
        self,
        *,
        as_of: str | None = None,
        data_date: str | None = None,
        source: str,
        query_spec: dict | str,
        raw_bytes: bytes | str,
        generator_commit: str | None = None,
    ) -> int:
        """存快照，返回 snapshot_id。

        append-only——同 key 再 put 创建**新行**不覆盖旧行（前复权 mutation 锁定靠此）。
        - ``as_of`` 缺省取当前时刻（北京时区 ISO 精确秒）。
        - ``content_hash`` = sha256(raw_bytes)，复现校验用。
        - ``fetched_at`` = as_of（冗余便于纯 fetched_at 排序查询）。
        """
        as_of = as_of or _now_iso()
        if isinstance(raw_bytes, str):
            raw_bytes = raw_bytes.encode("utf-8")
        elif not isinstance(raw_bytes, (bytes, bytearray)):
            raise TypeError(
                f"raw_bytes 须为 bytes/str，得到 {type(raw_bytes).__name__}"
            )
        raw_bytes = bytes(raw_bytes)
        spec_str = (
            query_spec
            if isinstance(query_spec, str)
            else json.dumps(query_spec, ensure_ascii=False, default=str, sort_keys=True)
        )
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        conn = self._conn()
        try:
            cur = conn.execute(
                "INSERT INTO snapshots "
                "(as_of, data_date, source, query_spec, content_hash, raw_blob, "
                "fetched_at, generator_commit) VALUES (?,?,?,?,?,?,?,?)",
                (
                    as_of,
                    data_date,
                    source,
                    spec_str,
                    content_hash,
                    raw_bytes,
                    as_of,
                    generator_commit,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    # ── 读取 ────────────────────────────────────────────────────────────

    def get(self, snapshot_id: int) -> dict | None:
        """取整行（含 raw_blob/content_hash/query_spec）。不存在返 None。"""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def latest_snapshot_id(
        self, source: str, data_date: str | None
    ) -> int | None:
        """(source, data_date) 下最新 snapshot_id——给 S161 Recorder 作 data_snapshot_id。

        无则 None。``data_date IS ?`` 用 IS 而非 =，NULL 安全（data_date=None 也匹配 NULL）。
        """
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT snapshot_id FROM snapshots "
                "WHERE source = ? AND data_date IS ? "
                "ORDER BY snapshot_id DESC LIMIT 1",
                (source, data_date),
            ).fetchone()
            return int(row["snapshot_id"]) if row else None
        finally:
            conn.close()

    def query_as_of(
        self,
        source: str,
        data_date: str | None,
        as_of: str | None = None,
    ) -> bytes | None:
        """point-in-time 查询：返回 ≤ as_of 的最近快照 raw_blob。

        - ``as_of=None`` → 返回 (source, data_date) 下最新快照 raw。
        - ``as_of`` 给定 → 返回该时点可见的最新快照 raw（≤ as_of，按 as_of DESC + snapshot_id DESC 取首）。
        无匹配返 None。
        """
        conn = self._conn()
        try:
            if as_of is None:
                row = conn.execute(
                    "SELECT raw_blob FROM snapshots "
                    "WHERE source = ? AND data_date IS ? "
                    "ORDER BY snapshot_id DESC LIMIT 1",
                    (source, data_date),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT raw_blob FROM snapshots "
                    "WHERE source = ? AND data_date IS ? AND as_of <= ? "
                    "ORDER BY as_of DESC, snapshot_id DESC LIMIT 1",
                    (source, data_date, as_of),
                ).fetchone()
            return bytes(row["raw_blob"]) if row else None
        finally:
            conn.close()

    def recompute_input(self, snapshot_id: int) -> bytes | None:
        """复现取数：从 pinned snapshot 取 raw（不 re-fetch）。不存在返 None。

        §2.6 复现判据 (b) data-revalidation 源：从 pinned as_of snapshot 重导 series
        + content_hash 比；不匹配 → 诚实标"前复权重算（corporate action 后）"。
        """
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT raw_blob FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            return bytes(row["raw_blob"]) if row else None
        finally:
            conn.close()

    def content_hash(self, snapshot_id: int) -> str | None:
        """取快照 content_hash（复现校验用）。不存在返 None。"""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT content_hash FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            return row["content_hash"] if row else None
        finally:
            conn.close()

    def count(self, source: str | None = None) -> int:
        """快照数（调试/健康检查用；可选按 source 过滤）。"""
        conn = self._conn()
        try:
            if source is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM snapshots WHERE source = ?", (source,)
                ).fetchone()
            return int(row["n"])
        finally:
            conn.close()


def run_migrations(db_path: str | Path | None = None) -> None:
    """走 MigrationManager 版本跟踪建表（约定一致；store._ensure_schema 另作防御）。

    供 app startup 或显式调用。版本：``20260906-001``。``db_path`` 缺省走默认路径。
    与 ``limitup_sti/data.py.run_initial_migrations`` 同构。
    """
    from migrations import MigrationManager  # noqa: PLC0415（避免顶层循环 import）

    sql_path = (
        Path(__file__).resolve().parent.parent
        / "migrations"
        / "pit_store"
        / "20260906-001_create_snapshots.sql"
    )
    manager = MigrationManager(db_path=db_path or _default_db_path())
    manager.upgrade(
        [
            {
                "version": "20260906-001",
                "name": "create_snapshots",
                "sql": sql_path.read_text(encoding="utf-8"),
            }
        ]
    )
