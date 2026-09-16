"""S161 R4 Recorder — experiment tracking + reproducibility.

Persists data_snapshot_id + input artifact hashes + COMPLETE return series
(not just hash — hash is verify-but-not-regenerate, qlib Recorder save_objects
stores the full series) + params + frozen_commit + verdict + timestamp.

Two reproducibility criteria (spec §2 R4):
  (a) verdict-reproducibility: recompute Verdict from stored full series
      (deterministic — same inputs → same Verdict, always succeeds).
  (b) data-revalidation: re-derive series from pinned as_of PIT bundle +
      hash compare; mismatch → honest "前复权重算" label, not fake-green.

Storage: SQLite in ``<VR_DATA_DIR>/verifier_recorder/recorder.db``
(.vibe-research subdirectory, gitignored, never in git).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from vr_paths import BEIJING_TZ, resolve_data_dir

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS verifier_records (
  recorder_id TEXT PRIMARY KEY,
  data_snapshot_id TEXT NOT NULL,
  input_hashes TEXT NOT NULL,       -- JSON: {artifact: sha256[:12]}
  return_series TEXT NOT NULL,     -- JSON: complete list[float]
                                   -- P4 latent: intent is hash-only (sha256
                                   -- of series) to reduce row size, but NOT
                                   -- NULL constraint on 85 existing rows
                                   -- requires ALTER TABLE migration. Keep full
                                   -- series for now; migrate when adding a
                                   -- return_series_hash column + backfill.
  dates TEXT,                      -- JSON: list[str] | null
  params TEXT NOT NULL,            -- JSON: {edge_type, n_trials, cost, ...}
  frozen_commit TEXT,
  verdict TEXT NOT NULL,           -- JSON: serialized Verdict
  timestamp TEXT NOT NULL           -- ISO (Beijing tz, seconds)
);
CREATE INDEX IF NOT EXISTS idx_snapshot ON verifier_records(data_snapshot_id);
"""


def _now_iso() -> str:
    return datetime.now(BEIJING_TZ).isoformat(timespec="seconds")


def _default_db_path() -> Path:
    return resolve_data_dir() / "verifier_recorder" / "recorder.db"


def sha256_file(path: str | Path, chunk_size: int = 65536) -> str:
    """SHA256 of a file (chunked for large files like the 160MB kline cache).

    Returns full hexdigest; callers truncate as needed.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compute_composite_snapshot_id(
    universe_path: str | Path,
    kline_cache_path: str | Path,
) -> str:
    """Composite data_snapshot_id = f"{universe_hash[:12]}+{cache_hash[:12]}".

    Pins BOTH universe (close_d denominator) AND kline cache (D+1 open
    numerator). The old magic string '94d33018a4bd' only pinned universe;
    the mutable 前复权 cache was unpinned (HIGH #2/#5/#6 reproducibility gap).
    """
    uni_hash = sha256_file(universe_path)[:12]
    cache_hash = sha256_file(kline_cache_path)[:12]
    return f"{uni_hash}+{cache_hash}"


@dataclass(frozen=True)
class VerifierRecord:
    """Immutable record of one verification run."""

    recorder_id: str
    data_snapshot_id: str
    input_hashes: dict[str, str]
    return_series: list[float]
    dates: list[str] | None
    params: dict[str, Any]
    frozen_commit: str | None
    verdict: dict[str, Any]
    timestamp: str


class Recorder:
    """SQLite-backed experiment tracker + reproducibility checker.

    Append-only (INSERT only, no UPDATE/DELETE). Same as PIT SnapshotStore
    design — historical verdicts are immutable once recorded.
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path) if db_path is not None else str(_default_db_path())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        conn = self._conn()
        try:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    def save(
        self,
        *,
        data_snapshot_id: str,
        input_hashes: dict[str, str],
        return_series: list[float],
        dates: list[str] | None = None,
        params: dict[str, Any],
        frozen_commit: str | None = None,
        verdict: dict[str, Any],
    ) -> str:
        """Persist a verification record. Returns recorder_id (timestamp-based).

        Stores the COMPLETE return series (not just hash) so criterion (a)
        verdict-reproducibility can recompute without re-deriving from data.
        """
        ts = _now_iso()
        # recorder_id = timestamp + snapshot_id tail + line_id tail (unique + traceable)
        # S209 T6 fix: line_id 区分 selection/event（同秒同 snapshot 不撞 UNIQUE）
        snap_tail = data_snapshot_id.replace("+", "-")[-12:]
        line_id = str(params.get("line_id", "")) if isinstance(params, dict) else ""
        line_tail = hashlib.sha256(line_id.encode("utf-8")).hexdigest()[:8] if line_id else "noline"
        recorder_id = f"{ts.replace(':', '').replace('-', '')}-{snap_tail}-{line_tail}"

        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO verifier_records "
                "(recorder_id, data_snapshot_id, input_hashes, return_series, "
                "dates, params, frozen_commit, verdict, timestamp) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    recorder_id,
                    data_snapshot_id,
                    json.dumps(input_hashes, sort_keys=True),
                    json.dumps(return_series),
                    json.dumps(dates) if dates is not None else None,
                    json.dumps(params, sort_keys=True, default=str),
                    frozen_commit,
                    json.dumps(verdict, sort_keys=True, default=str),
                    ts,
                ),
            )
            conn.commit()
            return recorder_id
        finally:
            conn.close()

    def load(self, recorder_id: str) -> VerifierRecord | None:
        """Load a record by recorder_id. Returns None if not found."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM verifier_records WHERE recorder_id = ?",
                (recorder_id,),
            ).fetchone()
            if not row:
                return None
            return VerifierRecord(
                recorder_id=row["recorder_id"],
                data_snapshot_id=row["data_snapshot_id"],
                input_hashes=json.loads(row["input_hashes"]),
                return_series=json.loads(row["return_series"]),
                dates=json.loads(row["dates"]) if row["dates"] else None,
                params=json.loads(row["params"]),
                frozen_commit=row["frozen_commit"],
                verdict=json.loads(row["verdict"]),
                timestamp=row["timestamp"],
            )
        finally:
            conn.close()

    def latest_snapshot_ids_by_dimension(
        self, dimension_ids: list[str]
    ) -> dict[str, str]:
        """Batch lookup: dimension_id → latest data_snapshot_id.

        Queries ``params.dimension_id`` (JSON field) for each dimension.
        Returns only dimensions that have at least one matching record.
        Dimensions with no records are absent from the result (caller
        defaults to None). Used by GET /api/evaluation/dims (S162 R4).
        """
        if not dimension_ids:
            return {}
        placeholders = ",".join("?" for _ in dimension_ids)
        conn = self._conn()
        try:
            rows = conn.execute(
                f"SELECT json_extract(params, '$.dimension_id') AS dim, "
                f"data_snapshot_id, recorder_id "
                f"FROM verifier_records "
                f"WHERE json_extract(params, '$.dimension_id') IN ({placeholders}) "
                f"ORDER BY timestamp DESC, recorder_id DESC",
                dimension_ids,
            ).fetchall()
            # Keep only the first (latest, since DESC) per dimension
            result: dict[str, str] = {}
            for row in rows:
                dim = row["dim"]
                if dim and dim not in result:
                    result[dim] = row["data_snapshot_id"]
            return result
        finally:
            conn.close()

    def count(self) -> int:
        conn = self._conn()
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM verifier_records").fetchone()
            return int(row["n"])
        finally:
            conn.close()

    def list_records(self, limit: int = 100) -> list[VerifierRecord]:
        """List records, most recent first (DESC by timestamp).

        Bounded by ``limit`` (default 100) per unbounded-query rule.
        Used by GET /api/verifier/records (S165 frontend wiring).
        """
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM verifier_records ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                VerifierRecord(
                    recorder_id=row["recorder_id"],
                    data_snapshot_id=row["data_snapshot_id"],
                    input_hashes=json.loads(row["input_hashes"]),
                    return_series=json.loads(row["return_series"]),
                    dates=json.loads(row["dates"]) if row["dates"] else None,
                    params=json.loads(row["params"]),
                    frozen_commit=row["frozen_commit"],
                    verdict=json.loads(row["verdict"]),
                    timestamp=row["timestamp"],
                )
                for row in rows
            ]
        finally:
            conn.close()
