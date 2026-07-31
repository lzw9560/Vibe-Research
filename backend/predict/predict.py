"""Cascade prediction core + snapshot store — S017 T9.

Produces a per-stage :class:`Snapshot` from a trained artifact and persists it
to the project-local data dir (``.vibe-research/predict/snapshots/<head>/<date>/<stage>.json``).
Snapshots never enter git, never leave the project dir, and never travel to the
home dir (per the 2026-07-30 user constraint).

Compliance: this module computes research-grade probabilities only.  It emits
no buy/sell/stop-loss/take-profit instructions — the disclaimer layer lives at
the router/frontend (T10+).  Return-quantiles (10/50/90) and live per-row SHAP
are honest TODOs: they require a regression conformal head and live feature
values respectively, and are left empty rather than fabricated (禁止臆造).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from vr_paths import resolve_data_dir

# ── Module constants ───────────────────────────────────────────────────

#: Canonical S1→S4 stage ordering (cascade timeline).
STAGE_ORDER: tuple[str, ...] = ("s1", "s2", "s3", "s4")

#: Semantic version of the short_sector model artifact (audit provenance).
MODEL_VERSION = "short_sector-v0"


# ── Snapshot ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Snapshot:
    """Immutable prediction snapshot for one (head, stage, date).

    Attributes
    ----------
    head:
        Prediction head identifier (e.g. ``"short_sector"``).
    stage:
        Cascade stage (``s1``/``s2``/``s3``/``s4``).
    t:
        Trade date (ISO ``YYYY-MM-DD``).
    prob:
        Calibrated-ish probability of the up class (research reference).
    quantiles:
        10/50/90 return quantiles — **TODO** (needs regression conformal
        head); empty tuple until then, never fabricated.
    shap_topk:
        Top-k (feature, attribution) pairs — **TODO** (needs live SHAP
        per-row); empty tuple until then.
    features_used:
        Names of features consumed at this stage.
    backends:
        Ensemble backends actually used (audit).
    model_version:
        Artifact version tag (audit / reproducibility).
    """

    head: str
    stage: str
    t: str
    prob: float
    quantiles: tuple[float, ...]
    shap_topk: tuple[tuple[str, float], ...]
    features_used: tuple[str, ...]
    backends: tuple[str, ...]
    model_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "head": self.head,
            "stage": self.stage,
            "t": self.t,
            "prob": self.prob,
            "quantiles": list(self.quantiles),
            "shap_topk": [list(pair) for pair in self.shap_topk],
            "features_used": list(self.features_used),
            "backends": list(self.backends),
            "model_version": self.model_version,
        }


# ── predict_stage ─────────────────────────────────────────────────────


def predict_stage(
    head: str,
    stage: str,
    t: str,
    *,
    artifact: dict[str, Any],
    X_row: np.ndarray,
    feature_names: list[str],
) -> Snapshot:
    """Score a single row at *stage* with a trained *artifact*.

    The feature subset available at *stage* is the caller's responsibility
    (resolved via :func:`predict.feature_interface.list_available_features`
    once S008 live data lands).  Here we consume the already-assembled row.
    """
    ensemble = artifact["ensemble"]
    row = np.asarray(X_row, dtype=float).reshape(1, -1)
    proba = ensemble.predict_proba(row)
    prob = float(proba[0, 1] if proba.ndim == 2 else proba[0])

    return Snapshot(
        head=head,
        stage=stage,
        t=t,
        prob=prob,
        quantiles=(),  # TODO: regression conformal head (10/50/90)
        shap_topk=(),  # TODO: live per-row SHAP attribution
        features_used=tuple(feature_names),
        backends=tuple(artifact.get("backends", [])),
        model_version=MODEL_VERSION,
    )


# ── snapshot store ────────────────────────────────────────────────────


def _snapshot_dir(head: str, t: str, *, data_dir: Path | None = None) -> Path:
    base = (data_dir or resolve_data_dir()) / "predict" / "snapshots" / head / t
    base.mkdir(parents=True, exist_ok=True)
    return base


def cascade_store(snapshot: Snapshot, *, data_dir: Path | None = None) -> Path:
    """Persist *snapshot* as ``<stage>.json`` and return its path.

    One file per (head, date, stage); rewriting the same stage overwrites the
    latest, but cross-stage evolution is preserved (概率级联不跨阶段覆盖).
    """
    d = _snapshot_dir(snapshot.head, snapshot.t, data_dir=data_dir)
    path = d / f"{snapshot.stage}.json"
    path.write_text(
        json.dumps(snapshot.to_dict(), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _stage_rank(stage: str) -> int:
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return len(STAGE_ORDER)


def load_cascade(
    head: str,
    t: str,
    *,
    data_dir: Path | None = None,
) -> list[Snapshot]:
    """Load all stage snapshots for *head* on date *t*, ordered S1→S4.

    Returns an empty list when none exist.
    """
    base = (data_dir or resolve_data_dir()) / "predict" / "snapshots" / head / t
    if not base.exists():
        return []
    snaps: list[Snapshot] = []
    for path in sorted(base.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        snaps.append(
            Snapshot(
                head=data["head"],
                stage=data["stage"],
                t=data["t"],
                prob=float(data["prob"]),
                quantiles=tuple(data.get("quantiles", [])),
                shap_topk=tuple(tuple(p) for p in data.get("shap_topk", [])),
                features_used=tuple(data.get("features_used", [])),
                backends=tuple(data.get("backends", [])),
                model_version=data.get("model_version", ""),
            )
        )
    snaps.sort(key=lambda s: _stage_rank(s.stage))
    return snaps
