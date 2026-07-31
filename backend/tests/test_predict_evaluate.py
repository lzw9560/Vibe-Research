"""Tests for predict.evaluate — S017 T8 evaluation metrics.

Covers win_rate, confusion_matrix, calibration_curve, decay_curve and the
evaluate_short_sector orchestrator.  Pure & deterministic (synthetic data).
"""

from __future__ import annotations

import numpy as np
import pytest

from predict.evaluate import (
    calibration_curve,
    confusion_matrix,
    decay_curve,
    evaluate_short_sector,
    win_rate,
)
from predict.train import TrainConfig, train_short_sector


# ── helpers ────────────────────────────────────────────────────────────


def _dates(n: int, start: str = "2024-09-02") -> list[str]:
    from datetime import date, timedelta

    d0 = date.fromisoformat(start)
    out: list[str] = []
    d = d0
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _synthetic_xy(n: int = 80, n_features: int = 4, seed: int = 42):
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, n_features))
    y = (X[:, 0] + 0.3 * rng.standard_normal(n) > 0).astype(int)
    return X, y


# ── (a) win_rate ───────────────────────────────────────────────────────


class TestWinRate:
    def test_all_correct(self) -> None:
        y = np.array([1, 0, 1, 0])
        assert win_rate(y, y) == 1.0

    def test_all_wrong(self) -> None:
        y = np.array([1, 0, 1, 0])
        pred = np.array([0, 1, 0, 1])
        assert win_rate(y, pred) == 0.0

    def test_half(self) -> None:
        y = np.array([1, 1, 0, 0])
        pred = np.array([1, 0, 0, 1])
        assert win_rate(y, pred) == 0.5

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            win_rate(np.array([]), np.array([]))


# ── (b) confusion_matrix ───────────────────────────────────────────────


class TestConfusionMatrix:
    def test_counts(self) -> None:
        y = np.array([1, 1, 0, 0, 1, 0])
        pred = np.array([1, 0, 0, 1, 1, 0])
        cm = confusion_matrix(y, pred)
        # tp: idx0,4 | fn: idx1 | tn: idx2,5 | fp: idx3
        assert cm == {"tp": 2, "fp": 1, "tn": 2, "fn": 1}

    def test_counts_sum_to_n(self) -> None:
        y = np.array([1, 0, 1, 0, 1, 1, 0, 0])
        pred = np.array([0, 0, 1, 1, 1, 0, 0, 1])
        cm = confusion_matrix(y, pred)
        assert cm["tp"] + cm["fp"] + cm["tn"] + cm["fn"] == len(y)


# ── (c) calibration_curve ──────────────────────────────────────────────


class TestCalibrationCurve:
    def test_perfect_calibration(self) -> None:
        y = np.array([1, 1, 0, 0])
        prob = np.array([1.0, 1.0, 0.0, 0.0])
        curve = calibration_curve(y, prob, n_bins=5)
        # bin [0,0.2): prob 0.0, freq 0.0 ; bin [0.8,1.0]: prob 1.0, freq 1.0
        by_prob = {round(p, 4): f for p, f in curve}
        assert by_prob[0.0] == 0.0
        assert by_prob[1.0] == 1.0

    def test_n_bins(self) -> None:
        rng = np.random.default_rng(1)
        y = (rng.random(100) > 0.5).astype(int)
        prob = rng.random(100)
        curve = calibration_curve(y, prob, n_bins=5)
        assert len(curve) == 5

    def test_empty_bin_skipped(self) -> None:
        # all probs in one bin → only one populated bin returned
        y = np.array([1, 0, 1])
        prob = np.array([0.01, 0.02, 0.015])
        curve = calibration_curve(y, prob, n_bins=5)
        assert len(curve) == 1


# ── (d) decay_curve ───────────────────────────────────────────────────


class TestDecayCurve:
    def test_closer_horizon_higher_auc(self) -> None:
        rng = np.random.default_rng(7)
        n = 200
        y = (rng.random(n) > 0.5).astype(int)
        prob_s1 = y * 0.9 + (1 - y) * 0.1 + 0.01 * rng.standard_normal(n)
        prob_s3 = rng.random(n)
        out = decay_curve(
            {"s1": y, "s3": y}, {"s1": prob_s1, "s3": prob_s3}
        )
        assert out["s1"] > out["s3"]
        assert 0.0 <= out["s1"] <= 1.0

    def test_constant_prob_returns_half(self) -> None:
        y = np.array([1, 0, 1, 0, 1, 0])
        prob = np.full(6, 0.5)
        out = decay_curve({"s1": y}, {"s1": prob})
        assert out["s1"] == 0.5

    def test_single_class_raises(self) -> None:
        y = np.ones(5)
        prob = np.array([0.6, 0.7, 0.8, 0.5, 0.9])
        with pytest.raises(ValueError):
            decay_curve({"s1": y}, {"s1": prob})


# ── (e) evaluate_short_sector orchestrator ────────────────────────────


class TestEvaluateShortSector:
    def test_returns_metrics_keys(self) -> None:
        dates = _dates(80)
        X, y = _synthetic_xy(80)
        art = train_short_sector(X, y, dates, config=TrainConfig(train_size=20, test_size=5, step_days=5))
        te = list(art["split"].test_idx)
        Xte, yte = X[te], y[te]
        m = evaluate_short_sector(art, Xte, yte)
        for k in ("win_rate", "confusion", "calibration", "auc", "leakage_flag"):
            assert k in m
        assert 0.0 <= m["win_rate"] <= 1.0
        assert 0.0 <= m["auc"] <= 1.0
        assert isinstance(m["leakage_flag"], bool)

    def test_leakage_flag_true_when_too_high(self) -> None:
        # evaluate on the train fold the model was fit on → high win_rate → flag
        dates = _dates(80)
        X, y = _synthetic_xy(80)
        art = train_short_sector(X, y, dates, config=TrainConfig(train_size=20, test_size=5, step_days=5))
        tr = list(art["split"].train_idx)
        m = evaluate_short_sector(art, X[tr], y[tr])
        assert m["leakage_flag"] is True

    def test_leakage_flag_clear_on_random(self) -> None:
        rng = np.random.default_rng(3)
        dates = _dates(80)
        X, y = _synthetic_xy(80)
        art = train_short_sector(X, y, dates, config=TrainConfig(train_size=20, test_size=5, step_days=5))
        y_noise = (rng.random(len(art["split"].test_idx)) > 0.5).astype(int)
        te = list(art["split"].test_idx)
        m = evaluate_short_sector(art, X[te], y_noise)
        assert m["leakage_flag"] is False
