"""Evaluation metrics — S017 T8.

Pure, auditable metric functions so every figure is可复算 (no sklearn
black-box): win_rate, confusion_matrix, calibration_curve, and a rank-based
AUC (Mann-Whitney with average ranks for ties) for the decay curve.

The orchestrator :func:`evaluate_short_sector` runs the trained artifact's
ensemble over a test fold and reports all metrics plus a leakage flag
(>60% win-rate on the reported fold → investigate leakage, per S017 spec).
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Win-rate above this on a reported fold triggers a leakage self-check
# (spec T16: sample-out short_sector win-rate expected ~51-55%; >60% ⇒ audit).
LEAKAGE_WIN_RATE_THRESHOLD = 0.60

_CALIB_DEFAULT_BINS = 10


# ── Pure metric functions ─────────────────────────────────────────────


def win_rate(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Fraction of correct predictions (binary accuracy)."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    if y_true.size == 0:
        raise ValueError("win_rate undefined for empty arrays")
    return float(np.mean(y_true == y_pred))


def confusion_matrix(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, int]:
    """Return {tp, fp, tn, fn} counts for binary predictions."""
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)
    tp = int(np.sum((y_pred == 1) & (y_true == 1)))
    fp = int(np.sum((y_pred == 1) & (y_true == 0)))
    tn = int(np.sum((y_pred == 0) & (y_true == 0)))
    fn = int(np.sum((y_pred == 0) & (y_true == 1)))
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def calibration_curve(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = _CALIB_DEFAULT_BINS,
) -> list[tuple[float, float]]:
    """Return [(mean_prob, empirical_freq), ...] per populated bin.

    Bins are equal-width over [0, 1]; empty bins are skipped.  Perfectly
    calibrated models return ``freq == mean_prob`` per bin.
    """
    y_true = np.asarray(y_true).astype(int)
    y_prob = np.asarray(y_prob, dtype=float)
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    # bin index in [0, n_bins-1]; prob==1.0 lands in the last bin
    bin_idx = np.minimum((y_prob * n_bins).astype(int), n_bins - 1)
    curve: list[tuple[float, float]] = []
    for b in range(n_bins):
        mask = bin_idx == b
        if not mask.any():
            continue
        mean_prob = float(y_prob[mask].mean())
        freq = float(y_true[mask].mean())
        curve.append((mean_prob, freq))
    return curve


def _rank_avg(a: np.ndarray) -> np.ndarray:
    """Ranks with **average ranks for ties** (1-based)."""
    a = np.asarray(a, dtype=float)
    n = a.size
    order = np.argsort(a, kind="mergesort")
    sorted_a = a[order]
    ranks = np.empty(n, dtype=float)
    i = 0
    while i < n:
        j = i + 1
        while j < n and sorted_a[j] == sorted_a[i]:
            j += 1
        # 1-based ranks i+1 .. j averaged
        avg_rank = (i + 1 + j) / 2.0
        ranks[order[i:j]] = avg_rank
        i = j
    return ranks


def _auc(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Rank-based AUC (Mann-Whitney U / (n_pos*n_neg)).

    Constant scores (all ties) → 0.5.  Single-class labels → ValueError.
    """
    y_true = np.asarray(y_true).astype(int)
    n_pos = int((y_true == 1).sum())
    n_neg = int((y_true == 0).sum())
    if n_pos == 0 or n_neg == 0:
        raise ValueError("AUC undefined for single-class labels")
    ranks = _rank_avg(y_prob)
    sum_ranks_pos = float(ranks[y_true == 1].sum())
    return (sum_ranks_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def decay_curve(
    y_true_by_stage: dict[str, np.ndarray],
    y_prob_by_stage: dict[str, np.ndarray],
) -> dict[str, float]:
    """Per-stage AUC showing how predictive power decays S1→S2→S3.

    Each stage's probability is scored against its outcome labels.  A
    monotonically-decreasing curve across S1>S2>S3 indicates the later
    stages add less incremental signal (or that earlier signal decays with
    lead time).
    """
    if set(y_true_by_stage) != set(y_prob_by_stage):
        raise ValueError("y_true_by_stage and y_prob_by_stage keys must match")
    out: dict[str, float] = {}
    for stage, y_true in y_true_by_stage.items():
        out[stage] = _auc(y_true, y_prob_by_stage[stage])
    return out


# ── Orchestrator ───────────────────────────────────────────────────────


def evaluate_short_sector(
    artifact: dict[str, Any],
    X_test: np.ndarray,
    y_test: np.ndarray,
) -> dict[str, Any]:
    """Evaluate a trained short_sector artifact on a test fold.

    Returns win_rate, confusion, calibration curve, AUC, and a
    ``leakage_flag`` (True when win-rate exceeds the audit threshold —
    investigate for train/test leakage).
    """
    ensemble = artifact["ensemble"]
    proba = ensemble.predict_proba(X_test)
    # column 1 = P(class=1)
    y_prob = proba[:, 1] if proba.ndim == 2 else proba
    y_pred = (y_prob >= 0.5).astype(int)

    y_test = np.asarray(y_test).astype(int)
    wr = win_rate(y_test, y_pred)
    try:
        auc = _auc(y_test, y_prob)
    except ValueError:
        auc = 0.5

    return {
        "win_rate": wr,
        "confusion": confusion_matrix(y_test, y_pred),
        "calibration": calibration_curve(y_test, y_prob),
        "auc": auc,
        "leakage_flag": wr > LEAKAGE_WIN_RATE_THRESHOLD,
    }
