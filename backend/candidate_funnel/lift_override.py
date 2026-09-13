# -*- coding: utf-8 -*-
"""§44v2 P0 闭环后半段：R3 30/60 天写回 + override-aware reader。

S159 R4（回溯主场）+ S161 R8（lift_to_multiplier 接线，前半段已落地）的后半段：
evaluation_backtest 到点不再 reminder-only，自动写回 revalidation 结果到
``$VR_DATA_DIR/evaluation_lifts.db`` 新表 ``dimension_lift_overrides``，reader
（lift_for_arm / _apply_evaluation_layer / scoring）override 优先 fallback frozen。

工程底线（CLAUDE.md §1.2）：**不改 frozen dict**（DIMENSION_LIFT_REGISTRY FROZEN_COMMIT
b1aba21 read-only baseline）——override 走新表 + 新 frozen DimensionValidation 实例，
frozen baseline 原样保留作 provenance。升降级经 lift_to_multiplier（days≥60+lift≥2→
validated×1.0；lift<1 robust→劣于随机×0.1；days<60→待复验×0.5，规约④ cap 一致）。

§44v2 方法论不破坏（day_paired + permutation + Bonferroni + walk_forward 在 s44_verifier）；
本模块只做 writeback + reader，compute 注入（default = path_lift 从 forward_test DB 算）。
"""
from __future__ import annotations

import logging
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from candidate_funnel.evaluation import (
    DIMENSION_LIFT_REGISTRY,
    DimensionValidation,
    FROZEN_COMMIT,
    lift_to_multiplier,
)

logger = logging.getLogger("vibe-research")

_OVERRIDE_DB_FILENAME = "evaluation_lifts.db"
_OVERRIDE_CACHE_TTL_S = 60  # override 每 30-60 天才变，60s staleness 可接受

# db_path_str -> {dim_id: (effective_dim, fetched_at_ts)}
_EFFECTIVE_CACHE: dict[str, dict[str, tuple[DimensionValidation, float]]] = {}


@dataclass(frozen=True)
class RevalidationResult:
    """单维度 revalidation 算出的输入（compute_fn 返回）——write_override 据此算 status/mult。"""
    lift: Optional[float]
    n: int
    days_robust: int
    ci_overlap: bool = True
    robust: bool = True
    source_script: str = ""


# ---------------------------------------------------------------------------
# DB path + schema
# ---------------------------------------------------------------------------
def _override_db_path() -> Path:
    """override DB 路径：$VR_DATA_DIR/evaluation_lifts.db（resolve_data_dir 防 home 分裂）。"""
    from vr_paths import resolve_data_dir
    return Path(resolve_data_dir()) / _OVERRIDE_DB_FILENAME


_OVERRIDE_SQL = """
CREATE TABLE IF NOT EXISTS dimension_lift_overrides (
    dimension_id TEXT PRIMARY KEY,
    lift REAL,
    n INTEGER,
    days_robust INTEGER,
    validation_status TEXT,
    weight_multiplier REAL,
    phase TEXT,
    source_script TEXT,
    ci_overlap INTEGER,
    robust INTEGER,
    revalidated_at TEXT,
    frozen_commit TEXT
);
"""


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(_OVERRIDE_SQL)
    conn.commit()


def _connect(db_path: Optional[str]) -> sqlite3.Connection:
    p = Path(db_path) if db_path else Path(_override_db_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=10)
    _ensure_table(conn)
    return conn


# ---------------------------------------------------------------------------
# write_override：写盘 + 经 lift_to_multiplier 升降级 + 不改 frozen dict
# ---------------------------------------------------------------------------
def write_override(
    dim_id: str,
    lift: Optional[float],
    n: int,
    days_robust: int,
    phase: str,
    source_script: str = "",
    ci_overlap: bool = True,
    robust: bool = True,
    db_path: Optional[str] = None,
) -> dict:
    """写一条 override + 算 status/mult（经 lift_to_multiplier）+ upsert + 清缓存。

    不改 frozen DIMENSION_LIFT_REGISTRY（baseline b1aba21 read-only）——override 躺新表，
    reader 经 get_effective_dimension 覆盖读。返回写入的 {dimension_id, lift, n, days_robust,
    validation_status, weight_multiplier, phase}。
    """
    status, mult = lift_to_multiplier(lift, n, ci_overlap=ci_overlap,
                                     robust=robust, days_robust=days_robust)
    now = datetime.now().isoformat()
    src = source_script or f"R3 {phase} auto-writeback"
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT INTO dimension_lift_overrides
               (dimension_id, lift, n, days_robust, validation_status,
                weight_multiplier, phase, source_script, ci_overlap, robust,
                revalidated_at, frozen_commit)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(dimension_id) DO UPDATE SET
                 lift=excluded.lift, n=excluded.n, days_robust=excluded.days_robust,
                 validation_status=excluded.validation_status,
                 weight_multiplier=excluded.weight_multiplier, phase=excluded.phase,
                 source_script=excluded.source_script, ci_overlap=excluded.ci_overlap,
                 robust=excluded.robust, revalidated_at=excluded.revalidated_at""",
            (dim_id, lift, n, days_robust, status, mult, phase, src,
             int(ci_overlap), int(robust), now, FROZEN_COMMIT),
        )
        conn.commit()
    finally:
        conn.close()
    # 清缓存（同进程；跨进程靠 TTL）
    _EFFECTIVE_CACHE.pop(str(db_path or _override_db_path()), None)
    logger.info("[write_override] %s lift=%s n=%d days=%d → %s ×%.2f (phase=%s)",
                dim_id, lift, n, days_robust, status, mult, phase)
    return {"dimension_id": dim_id, "lift": lift, "n": n, "days_robust": days_robust,
            "validation_status": status, "weight_multiplier": mult, "phase": phase}


# ---------------------------------------------------------------------------
# get_effective_dimension：override 优先 fallback frozen + cache + 不污染 frozen
# ---------------------------------------------------------------------------
def _read_override_row(conn: sqlite3.Connection, dim_id: str) -> dict | None:
    row = conn.execute(
        """SELECT lift, n, days_robust, validation_status, weight_multiplier,
                  phase, source_script, revalidated_at
           FROM dimension_lift_overrides WHERE dimension_id=?""",
        (dim_id,),
    ).fetchone()
    if not row:
        return None
    return {"lift": row[0], "n": row[1], "days_robust": row[2],
            "validation_status": row[3], "weight_multiplier": row[4],
            "phase": row[5], "source_script": row[6], "revalidated_at": row[7]}


def get_effective_dimension(
    dim_id: str, db_path: Optional[str] = None,
) -> Optional[DimensionValidation]:
    """override 优先 fallback frozen。返新 frozen DimensionValidation（不改 baseline）。

    缓存 60s（override 稀有，TTL staleness 可接受；write_override 清同进程缓存）。
    未知 dim（不在 frozen registry）→ None。
    """
    frozen = DIMENSION_LIFT_REGISTRY.get(dim_id)
    if frozen is None:
        return None  # 未知 dim，不臆造

    cache_key = str(db_path) if db_path else str(_override_db_path())
    now = datetime.now().timestamp()
    bucket = _EFFECTIVE_CACHE.get(cache_key)
    if bucket and dim_id in bucket:
        dim, ts = bucket[dim_id]
        if now - ts < _OVERRIDE_CACHE_TTL_S:
            return dim  # cache hit

    conn = _connect(db_path)
    try:
        row = _read_override_row(conn, dim_id)
    finally:
        conn.close()

    if row is None:
        # 无 override → 用 frozen baseline（缓存 frozen 实例本身）
        effective = frozen
    else:
        # 构建新 frozen 实例（不改 baseline）——label/source 保留 provenance，note 标 override
        note = (frozen.note + " | " if frozen.note else "") + (
            f"override@{row['revalidated_at']} phase={row['phase']} "
            f"({row['source_script']})")
        effective = DimensionValidation(
            dimension_id=frozen.dimension_id, label=frozen.label,
            lift=row["lift"], n=row["n"], days_robust=row["days_robust"],
            validation_status=row["validation_status"],
            weight_multiplier=row["weight_multiplier"],
            source_script=row["source_script"] or frozen.source_script,
            note=note, frozen_commit=FROZEN_COMMIT, frozen_at=frozen.frozen_at,
        )

    _EFFECTIVE_CACHE.setdefault(cache_key, {})[dim_id] = (effective, now)
    return effective


# ---------------------------------------------------------------------------
# apply_revalidation：到点调 compute_fn 写 override（injectable，default=path_lift）
# ---------------------------------------------------------------------------
def _day_paired_winrate_lift(
    survivors_by_day: dict[str, list[float]],
    universe_by_day: dict[str, list[float]],
) -> tuple[float | None, int, int]:
    """非池化 day-clustered winrate lift（mirrors s44_verifier.stats.day_paired_lift）。

    内联而非 import s44_verifier.stats：s44_verifier package __init__ → verifier → wiring
    → deflated_sharpe（vendor），无 vendor/ 的环境 import 链断。stats.day_paired_lift 是纯函数，
    此处镜像其 winrate_lift_avg/n_days/surv_n_pooled（canonical 在 stats.py，DRY 注释防漂移）。
    防 4.686x→1.723x 池化假象：按日算 winrate_lift 再平均（非池化）。
    """
    day_lifts: list[tuple[float, int]] = []
    for date in sorted(set(survivors_by_day) | set(universe_by_day)):
        s = survivors_by_day.get(date, [])
        r = universe_by_day.get(date, [])
        if not s or not r:
            continue
        s_wr = sum(1 for x in s if x > 0) / len(s)
        r_wr = sum(1 for x in r if x > 0) / len(r)
        if r_wr > 0:
            day_lifts.append((s_wr / r_wr, len(s)))
    if not day_lifts:
        return None, 0, 0
    avg = round(statistics.mean(l for l, _ in day_lifts), 4)
    return avg, len(day_lifts), sum(n for _, n in day_lifts)


def _compute_path_lift_from_forward_test(
    dim_id: str, gene_scores_db_path: Optional[str] = None,
) -> Optional[RevalidationResult]:
    """default compute：path_lift 从 forward_test DB 算 day_paired winrate lift。

    仅 dim_id=="path_lift"（其余返 None——其他维度 compute 待 follow-up 接线）。
    survivors = forward_test_records.return_path（buyable），universe = universe_returns.return_path（buyable），
    按 signal_date 聚类 → _day_paired_winrate_lift（非池化防 4.686x→1.723x 假象）。
    """
    if dim_id != "path_lift":
        return None
    from config import GENE_SCORES_DB_PATH

    db = gene_scores_db_path or GENE_SCORES_DB_PATH
    conn = sqlite3.connect(db, timeout=10)
    try:
        survivors_by_day: dict[str, list[float]] = {}
        for date, rp in conn.execute(
            "SELECT signal_date, return_path FROM forward_test_records "
            "WHERE return_path IS NOT NULL AND is_unbuyable = 0"
        ).fetchall():
            survivors_by_day.setdefault(date, []).append(float(rp))
        universe_by_day: dict[str, list[float]] = {}
        for date, rp in conn.execute(
            "SELECT signal_date, return_path FROM universe_returns "
            "WHERE return_path IS NOT NULL AND is_unbuyable = 0"
        ).fetchall():
            universe_by_day.setdefault(date, []).append(float(rp))
    finally:
        conn.close()

    lift, n_days, surv_n = _day_paired_winrate_lift(survivors_by_day, universe_by_day)
    if lift is None or n_days == 0:
        return None  # 无可配对日 → 不写（不臆造）
    return RevalidationResult(
        lift=lift, n=surv_n, days_robust=n_days,
        ci_overlap=True, robust=True,
        source_script="forward_test_records.return_path (R3 auto day_paired)",
    )


# dim_id → default compute callable（返 RevalidationResult | None）
_DEFAULT_COMPUTE_REGISTRY: dict[str, Callable[[str], Optional[RevalidationResult]]] = {
    "path_lift": _compute_path_lift_from_forward_test,
}


def apply_revalidation(
    phase: str,
    compute_fn: Optional[Callable[[str], Optional[RevalidationResult]]] = None,
    db_path: Optional[str] = None,
    gene_scores_db_path: Optional[str] = None,
) -> dict:
    """到点对每个 §44-可测维度调 compute_fn 写 override。

    compute_fn=None → 用 _DEFAULT_COMPUTE_REGISTRY（当前仅 path_lift 接线，其余 skip——
    不臆造）。compute_fn(dim_id) 返 None → skip；抛错 → 记 errors 不崩。
    返回 {phase, written: [dim_id...], skipped: [...], errors: [...]}。
    """
    written: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    for dim_id, dim in DIMENSION_LIFT_REGISTRY.items():
        if dim_id.endswith("_ref"):
            continue  # 参照维度不参与选股降权（vol_surge_ref），跳
        if dim_id == "low_volatility":
            continue  # 外部验证（学术定论），非本系统 §44 回溯
        try:
            if compute_fn is not None:
                result = compute_fn(dim_id)
            else:
                compute = _DEFAULT_COMPUTE_REGISTRY.get(dim_id)
                if compute is None:
                    skipped.append(dim_id)
                    continue  # 该维度无 default compute 接线（待 follow-up）
                result = (_compute_path_lift_from_forward_test(dim_id, gene_scores_db_path)
                           if dim_id == "path_lift" else compute(dim_id))
            if result is None:
                skipped.append(dim_id)
                continue
            write_override(dim_id, result.lift, result.n, result.days_robust, phase,
                           source_script=result.source_script, ci_overlap=result.ci_overlap,
                           robust=result.robust, db_path=db_path)
            written.append(dim_id)
        except Exception as e:  # noqa: BLE001 — 单维度崩不阻断其他 + 不崩 scheduled task
            errors.append(dim_id)
            logger.warning("[apply_revalidation] %s compute 失败: %s", dim_id, e)
    logger.info("[apply_revalidation] phase=%s written=%s skipped=%s errors=%s",
                phase, written, skipped, errors)
    return {"phase": phase, "written": written, "skipped": skipped, "errors": errors}
