"""Tests for predict.predict — S017 T9 cascade + snapshot store.

Covers the S1-S3 cascade core and the project-local snapshot store
(``.vibe-research/predict/snapshots/<head>/<date>/<stage>.json``).
Synthetic data; conftest isolates VR_DATA_DIR to a temp dir.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from predict.predict import (
    STAGE_ORDER,
    Snapshot,
    cascade_store,
    load_cascade,
    predict_stage,
)
from predict.train import TrainConfig, train_short_sector
from vr_paths import resolve_data_dir

# Forbidden trade-instruction words (compliance: research-grade output only).
_FORBIDDEN = ("买入", "卖出", "止损", "止盈", "荐股", "保证收益", "承诺收益")


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
    return X, y, [f"f{i}" for i in range(n_features)]


@pytest.fixture(scope="module")
def artifact():
    dates = _dates(80)
    X, y, _ = _synthetic_xy(80)
    return train_short_sector(
        X, y, dates, config=TrainConfig(train_size=20, test_size=5, step_days=5)
    )


# ── (a) predict_stage ─────────────────────────────────────────────────


class TestPredictStage:
    def test_returns_snapshot_with_prob(self, artifact) -> None:
        X, _, names = _synthetic_xy(80)
        row = X[0]
        snap = predict_stage(
            "short_sector", "s1", "2024-10-15", artifact=artifact,
            X_row=row, feature_names=names,
        )
        assert isinstance(snap, Snapshot)
        assert snap.head == "short_sector"
        assert snap.stage == "s1"
        assert snap.t == "2024-10-15"
        assert 0.0 <= snap.prob <= 1.0
        assert snap.features_used == tuple(names)
        assert snap.backends  # audit provenance

    def test_prob_consistent_with_ensemble(self, artifact) -> None:
        X, _, names = _synthetic_xy(80)
        row = X[7]
        snap = predict_stage(
            "short_sector", "s2", "2024-10-16", artifact=artifact,
            X_row=row, feature_names=names,
        )
        expected = float(artifact["ensemble"].predict_proba(row.reshape(1, -1))[0, 1])
        assert abs(snap.prob - expected) < 1e-9

    def test_quantiles_and_shap_empty_todo(self, artifact) -> None:
        X, _, names = _synthetic_xy(80)
        snap = predict_stage(
            "short_sector", "s1", "2024-10-15", artifact=artifact,
            X_row=X[3], feature_names=names,
        )
        # honest TODO: return-quantile (regression head) & live SHAP not yet wired
        assert snap.quantiles == ()
        assert snap.shap_topk == ()

    def test_snapshot_immutable(self, artifact) -> None:
        X, _, names = _synthetic_xy(80)
        snap = predict_stage(
            "short_sector", "s1", "2024-10-15", artifact=artifact,
            X_row=X[0], feature_names=names,
        )
        with pytest.raises(Exception):
            snap.prob = 0.99  # frozen


# ── (b) cascade_store ─────────────────────────────────────────────────


class TestCascadeStore:
    def _snap(self, artifact, stage, t, row_idx=0):
        X, _, names = _synthetic_xy(80)
        return predict_stage(
            "short_sector", stage, t, artifact=artifact,
            X_row=X[row_idx], feature_names=names,
        )

    def test_writes_json_under_data_dir(self, artifact) -> None:
        snap = self._snap(artifact, "s1", "2024-10-15")
        path = cascade_store(snap)
        assert path.exists()
        assert path.suffix == ".json"
        # under the active (temp) data dir, not the home dir
        assert resolve_data_dir() in path.parents
        assert Path.home() not in path.parents

    def test_roundtrip_reproducible(self, artifact) -> None:
        snap = self._snap(artifact, "s2", "2024-10-15", row_idx=5)
        path = cascade_store(snap)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["head"] == snap.head
        assert data["stage"] == snap.stage
        assert data["t"] == snap.t
        assert abs(data["prob"] - snap.prob) < 1e-12
        assert tuple(data["features_used"]) == snap.features_used

    def test_no_forbidden_trade_words_in_output(self, artifact) -> None:
        snap = self._snap(artifact, "s3", "2024-10-15")
        path = cascade_store(snap)
        text = path.read_text(encoding="utf-8")
        for word in _FORBIDDEN:
            assert word not in text, f"forbidden trade word in snapshot: {word}"


# ── (c) load_cascade ──────────────────────────────────────────────────


class TestLoadCascade:
    def test_returns_stages_sorted(self, artifact) -> None:
        X, _, names = _synthetic_xy(80)
        for stage, idx in (("s3", 9), ("s1", 1)):
            snap = predict_stage(
                "short_sector", stage, "2024-10-17", artifact=artifact,
                X_row=X[idx], feature_names=names,
            )
            cascade_store(snap)
        loaded = load_cascade("short_sector", "2024-10-17")
        assert [s.stage for s in loaded] == ["s1", "s3"]

    def test_empty_when_none(self) -> None:
        loaded = load_cascade("short_sector", "1999-01-01")
        assert loaded == []

    def test_stage_order_constant(self) -> None:
        assert STAGE_ORDER == ("s1", "s2", "s3", "s4")
