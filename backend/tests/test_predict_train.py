"""Tests for predict.train — S017 T7 purged walk-forward + embargo + rolling retrain.

Covers the leakage-critical pure split functions and the train_short_sector
orchestrator (synthetic data; no live network).
"""

from __future__ import annotations

import numpy as np
import pytest

from predict.train import (
    DEFAULT_EMBARGO_DAYS,
    DEFAULT_PURGE_DAYS,
    NORTHBOUND_RULE_CHANGE_DATE,
    TrainSplit,
    purged_walk_forward,
    roll_retrain,
    segment_index,
    train_short_sector,
)


# ── helpers ────────────────────────────────────────────────────────────


def _dates(n: int, start: str = "2024-09-02") -> list[str]:
    """Return *n* ascending ISO business-day date strings from *start*.

    Pure & deterministic (no randomness).  Business days only so the sequence
    is monotonically increasing in calendar time.
    """
    from datetime import date, timedelta

    d0 = date.fromisoformat(start)
    out: list[str] = []
    d = d0
    while len(out) < n:
        if d.weekday() < 5:  # Mon-Fri
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _crossing_dates() -> list[str]:
    """Dates straddling the 2024-08-19 northbound rule change."""
    from datetime import date, timedelta

    d0 = date(2024, 7, 1)
    out: list[str] = []
    d = d0
    while d <= date(2024, 10, 15):
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# ── (a) purged_walk_forward: leakage safety ───────────────────────────


class TestPurgedWalkForward:
    def test_train_strictly_before_test_with_gap(self) -> None:
        dates = _dates(60)
        splits = purged_walk_forward(
            dates, train_size=20, test_size=5, embargo_days=5, purge_days=3
        )
        assert splits, "expected at least one split for 60 dates"
        for sp in splits:
            assert max(sp.train_idx) < min(sp.test_idx)
            # gap between last train and first test >= embargo + purge
            gap = min(sp.test_idx) - max(sp.train_idx)
            assert gap >= 5 + 3

    def test_no_overlap(self) -> None:
        dates = _dates(50)
        splits = purged_walk_forward(
            dates, train_size=15, test_size=5, embargo_days=4, purge_days=2
        )
        for sp in splits:
            train_set = set(sp.train_idx)
            test_set = set(sp.test_idx)
            assert not (train_set & test_set)

    def test_deterministic_no_shuffle(self) -> None:
        """Two calls must yield identical splits (no random K-fold)."""
        dates = _dates(40)
        a = purged_walk_forward(dates, train_size=12, test_size=4)
        b = purged_walk_forward(dates, train_size=12, test_size=4)
        assert a == b
        # train idx must be ascending within each split
        for sp in a:
            assert list(sp.train_idx) == sorted(sp.train_idx)
            assert list(sp.test_idx) == sorted(sp.test_idx)

    def test_insufficient_data_returns_empty(self) -> None:
        dates = _dates(10)
        # need train_size + embargo + test_size <= 10; demand too much
        splits = purged_walk_forward(
            dates, train_size=20, test_size=5, embargo_days=5, purge_days=3
        )
        assert splits == []

    def test_respects_train_and_test_size(self) -> None:
        dates = _dates(80)
        splits = purged_walk_forward(
            dates, train_size=20, test_size=8, embargo_days=5, purge_days=3
        )
        for sp in splits:
            assert len(sp.train_idx) == 20
            assert len(sp.test_idx) == 8

    def test_train_dates_align_with_idx(self) -> None:
        dates = _dates(40)
        splits = purged_walk_forward(dates, train_size=12, test_size=4)
        for sp in splits:
            assert tuple(dates[i] for i in sp.train_idx) == sp.train_dates
            assert tuple(dates[i] for i in sp.test_idx) == sp.test_dates

    def test_test_windows_are_contiguous_and_non_overlapping(self) -> None:
        dates = _dates(60)
        splits = purged_walk_forward(
            dates, train_size=20, test_size=5, embargo_days=5, purge_days=3
        )
        starts = [min(sp.test_idx) for sp in splits]
        # each next test window starts exactly test_size after the previous
        for i in range(1, len(starts)):
            assert starts[i] == starts[i - 1] + 5


# ── (b) segment_index ──────────────────────────────────────────────────


class TestSegmentIndex:
    def test_pre_post_boundary(self) -> None:
        dates = ["2024-07-01", "2024-08-18", NORTHBOUND_RULE_CHANGE_DATE, "2024-09-02"]
        seg = segment_index(dates)
        assert seg == [0, 0, 1, 1]

    def test_all_pre(self) -> None:
        dates = ["2024-06-03", "2024-07-15"]
        assert segment_index(dates) == [0, 0]

    def test_all_post(self) -> None:
        dates = ["2024-09-02", "2024-10-15"]
        assert segment_index(dates) == [1, 1]


# ── (c) roll_retrain: northbound boundary ──────────────────────────────


class TestRollRetrain:
    def test_never_crosses_northbound_boundary(self) -> None:
        dates = _crossing_dates()
        splits = roll_retrain(
            dates,
            train_size=15,
            test_size=5,
            step_days=5,
            embargo_days=5,
            purge_days=3,
        )
        assert splits, "expected splits straddling the boundary to still produce same-side ones"
        seg = segment_index(dates)
        for sp in splits:
            all_idx = sp.train_idx + sp.test_idx
            segs = {seg[i] for i in all_idx}
            assert len(segs) == 1, (
                f"split crosses northbound rule boundary: segments={segs}"
            )

    def test_steps_forward(self) -> None:
        dates = _dates(80)
        splits = roll_retrain(
            dates,
            train_size=20,
            test_size=5,
            step_days=5,
            embargo_days=5,
            purge_days=3,
        )
        starts = [min(sp.test_idx) for sp in splits]
        assert starts == sorted(starts)
        # step_days=5 → consecutive test starts differ by 5
        for i in range(1, len(starts)):
            assert starts[i] - starts[i - 1] == 5


# ── (d) train_short_sector orchestrator ───────────────────────────────


def _synthetic_xy(n: int = 80, n_features: int = 4):
    rng = np.random.default_rng(42)
    X = rng.standard_normal((n, n_features))
    # label = 1 if feature 0 + noise > 0 (learnable but noisy)
    y = (X[:, 0] + 0.3 * rng.standard_normal(n) > 0).astype(int)
    return X, y


class TestTrainShortSector:
    def test_returns_artifact_with_keys(self) -> None:
        dates = _dates(80)
        X, y = _synthetic_xy(80)
        art = train_short_sector(X, y, dates)
        for k in ("ensemble", "calibrator", "regime", "backends", "split"):
            assert k in art, f"missing artifact key: {k}"
        # ensemble actually fitted
        assert art["ensemble"].backends()
        # regime fitted & labelled
        assert art["regime"].regime_labels()

    def test_uses_last_fold(self) -> None:
        dates = _dates(80)
        X, y = _synthetic_xy(80)
        art = train_short_sector(X, y, dates)
        sp: TrainSplit = art["split"]
        # last fold's test window ends at or near the end of the data
        assert max(sp.test_idx) >= 75

    def test_raises_on_insufficient_data(self) -> None:
        dates = _dates(10)
        X, y = _synthetic_xy(10)
        with pytest.raises(ValueError):
            train_short_sector(X, y, dates)
