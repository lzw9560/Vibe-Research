"""S165: Verifier + evaluation dimension router.

Wires the S165 frontend (DimensionValidationCard + VerifierRecords) to the
backend:
- GET /api/verifier/records          — list Recorder experiment records (S161 R4)
- GET /api/verifier/records/{id}     — one record (reproduce-capable)
- GET /api/evaluation/dims           — DIMENSION_LIFT_REGISTRY (S151) → DimensionValidationRecord[]

Response shapes match ``frontend/src/lib/verifier-contract.ts`` EXACTLY
(contract-first, double-locked with S161 v2 Verdict + Recorder schema).

R8 wiring: weight_multiplier + status come from ``lift_to_multiplier`` (production,
replaces direct reads of frozen weight_multiplier — CLAUDE.md §1.2 P0).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from candidate_funnel.evaluation import (
    DIMENSION_LIFT_REGISTRY,
    FROZEN_COMMIT,
    lift_to_multiplier,
)
from s44_verifier.recorder import Recorder, VerifierRecord

router = APIRouter(tags=["verifier"])

# ── S159 §5A universe-level baseline (3362 obs, overnight_gap_decomposition.py) ──
# Per-dimension three_window_compare needs S161 daily-bar run (TODO).
# These are real measured values, not fabricated (field source map, S165 R3).
_S159_WINDOW_BASELINE: dict[str, Any] = {
    "overnight_gap": {"mean": 0.013, "median": 0.0028, "win_rate": 0.543, "base_rate": None},
    "d1_intraday": {"mean": 0.0003, "median": 0.0, "win_rate": 0.462, "base_rate": None},
    "path": {"mean": 0.0067, "median": -0.03, "win_rate": 0.363, "base_rate": None},
}

# S161 overfit stats — all null until backtest-overfit skill wired (待建).
_OVERFIT_PLACEHOLDER: dict[str, Any] = {
    "pbo": None, "cscv": None, "dsr": None, "haircut": None, "min_trl": None,
}


def _status_chinese_to_english(chinese: str) -> str:
    """Map Chinese validation_status → S161 English enum.

    Mirrors ``frontend/src/lib/verifier-contract.ts statusFromChinese`` exactly,
    including the substring-trap ordering (must check 未validated before validated).
    """
    if "劣于随机" in chinese:
        return "falsified"
    if "探索" in chinese:
        return "exploratory"
    # exact match FIRST — substring trap: "未validated".includes("validated") → true
    if chinese == "未validated":
        return "not_validated"
    if "待复验" in chinese:
        return "underpowered"
    if chinese == "validated":
        return "robust_edge"
    return "exploratory"  # 兜底：未知状态标探索性（不夸大）


def _normalize_verdict(verdict: dict[str, Any]) -> dict[str, Any]:
    """Ensure the stored verdict dict has a ``lift`` key (frontend contract).

    Backend Verdict dataclass uses ``selection_lift``; the frontend Verdict type
    uses ``lift``. Alias so the frontend gets what it expects. Does not mutate
    the input (immutable pattern).
    """
    if "lift" not in verdict and "selection_lift" in verdict:
        return {**verdict, "lift": verdict["selection_lift"]}
    return verdict


def _verifier_record_to_response(rec: VerifierRecord) -> dict[str, Any]:
    """Map backend VerifierRecord → frontend RecorderRecord (verifier-contract.ts).

    - input_snapshot_hash: stable JSON of the input_hashes dict (faithful composite)
    - n_trials: extracted from stored params (verify() takes n_trials) with
      len(return_series) fallback
    - verdict: normalized so ``lift`` key is present
    """
    params = dict(rec.params) if rec.params else {}
    n_trials = params.get("n_trials", len(rec.return_series))
    # Stable string representation of the full input-hash bundle.
    input_snapshot_hash = json.dumps(rec.input_hashes, sort_keys=True)
    return {
        "recorder_id": rec.recorder_id,
        "data_snapshot_id": rec.data_snapshot_id,
        "input_snapshot_hash": input_snapshot_hash,
        "params": params,
        "n_trials": n_trials,
        "verdict": _normalize_verdict(rec.verdict),
        "timestamp": rec.timestamp,
    }


def _dim_to_response(dim) -> dict[str, Any]:
    """Map DIMENSION_LIFT_REGISTRY entry → frontend DimensionValidationRecord.

    R8 wiring: status + weight_multiplier from lift_to_multiplier (production).
    ci_low/ci_high/n_effective/event_* → null (S161 v2 verdict fields, 待 verifier
    跑出 — field source map, no fabrication).
    """
    status_cn, multiplier = lift_to_multiplier(
        dim.lift, dim.n, days_robust=dim.days_robust,
    )
    return {
        "dimension_id": dim.dimension_id,
        "label": dim.label,
        "lift": dim.lift,
        "ci_low": None,           # 待 S161 v2 verifier
        "ci_high": None,          # 待 S161 v2 verifier
        "n": dim.n,
        "n_effective": None,      # 待 day_paired effective-n wiring
        "days_robust": dim.days_robust,
        "status": _status_chinese_to_english(status_cn),
        "edge_type": "selection",  # REGISTRY 12 维皆 selection-layer
        "tradeable": False,        # 选股层无 validated 维度
        "event_metrics": None,    # event edge 在 recorder records（§3 event verdict）
        "event_status": None,
        "weight_multiplier": multiplier,
        "source_script": dim.source_script,
        "note": dim.note,
        "dsr_method": "N/A",       # selection 维度 single-strategy
        "three_window_compare": _S159_WINDOW_BASELINE,  # universe-level, 待 per-dim
        "overfit_stats": _OVERFIT_PLACEHOLDER,         # 待 backtest-overfit wire
        "frozen_commit": dim.frozen_commit,
        "updated_commit": None,   # 待回溯 task 填充
        "updated_at": None,       # 待回溯 task 填充
        "data_snapshot_id": None, # 待 S162 pit_store
        "layer": "selection",     # R6 三层 reframe
    }


@router.get("/api/verifier/records")
async def list_verifier_records(limit: int = 100) -> list[dict[str, Any]]:
    """List experiment records (S161 R4 Recorder), most recent first.

    Returns ``RecorderRecord[]`` matching verifier-contract.ts.
    Empty list if no records yet (fresh DB / no verifier runs).
    """
    try:
        recorder = Recorder()
    except Exception as exc:  # noqa: BLE001 — DB init failure → honest empty, not 500
        raise HTTPException(status_code=503, detail=f"verifier_recorder_unavailable: {exc}") from exc
    records = recorder.list_records(limit=limit)
    return [_verifier_record_to_response(r) for r in records]


@router.get("/api/verifier/records/{recorder_id}")
async def get_verifier_record(recorder_id: str) -> dict[str, Any]:
    """One experiment record by recorder_id (S161 R4).

    Returns ``RecorderRecord`` matching verifier-contract.ts.
    404 if not found.
    """
    try:
        recorder = Recorder()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"verifier_recorder_unavailable: {exc}") from exc
    record = recorder.load(recorder_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"recorder_id not found: {recorder_id}")
    return _verifier_record_to_response(record)


@router.get("/api/evaluation/dims")
async def list_evaluation_dims() -> list[dict[str, Any]]:
    """§44 dimension validation registry → DimensionValidationRecord[].

    Reads S151 DIMENSION_LIFT_REGISTRY (12 dims). status + weight_multiplier
    from lift_to_multiplier (R8 production wiring). ci_low/ci_high/overfit_stats
    null where S161 v2 verifier hasn't run yet (honest, no fabrication).
    """
    return [_dim_to_response(dim) for dim in DIMENSION_LIFT_REGISTRY.values()]


__all__ = ["router"]
