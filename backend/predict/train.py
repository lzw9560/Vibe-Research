"""Training pipeline — S017 T7.

Purged walk-forward splitting with embargo + purge (no random K-fold), rolling
retrain that never crosses the 2024-08-19 northbound rule-change boundary, and a
thin ``train_short_sector`` orchestrator wiring the ensemble/regime/calibration
models onto the last feasible fold.

The split functions are **pure** (operate on a sorted date index, no network,
no I/O) so the leakage-critical core is fully unit-testable offline.  Live
feature/label materialisation lands with S008 and is injected as ``X``/``y``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from predict.labels import SHORT_HORIZON_DAYS
from predict.models.calibration import ConformalCalibrator
from predict.models.ensemble import SoftVoteEnsemble
from predict.models.regime import GaussianMixtureRegimeSwitcher

# ── Module constants ───────────────────────────────────────────────────

# Must match predict.features.fund_flow.NorthFlowSegmenter.RULE_CHANGE_DATE.
# Single source of truth for "禁止跨段拟合" (no cross-segment fitting).
NORTHBOUND_RULE_CHANGE_DATE = "2024-08-19"

# Embargo: empty gap between the last train sample and the first test sample
# (defends against label-horizon leakage across the train/test boundary).
DEFAULT_EMBARGO_DAYS = 5

# Purge: drop train samples whose label window overlaps the test window.
# Defaults to the short label horizon (3 days) — a train sample at date d
# carries a label computed from d-h..d, so it must not sit within h of a test
# sample.
DEFAULT_PURGE_DAYS = SHORT_HORIZON_DAYS


# ── Immutable config / split ───────────────────────────────────────────


@dataclass(frozen=True)
class TrainConfig:
    """Immutable training configuration for one head."""

    train_size: int = 20
    test_size: int = 5
    step_days: int = 5
    embargo_days: int = DEFAULT_EMBARGO_DAYS
    purge_days: int = DEFAULT_PURGE_DAYS
    random_state: int = 42


@dataclass(frozen=True)
class TrainSplit:
    """One walk-forward split — immutable, index + date provenance."""

    train_idx: tuple[int, ...]
    test_idx: tuple[int, ...]
    train_dates: tuple[str, ...]
    test_dates: tuple[str, ...]


# ── Pure split functions ───────────────────────────────────────────────


def _gap(embargo_days: int, purge_days: int) -> int:
    """Total forbidden index-gap between train and test."""
    return embargo_days + purge_days


def purged_walk_forward(
    dates: list[str],
    *,
    train_size: int,
    test_size: int,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
    purge_days: int = DEFAULT_PURGE_DAYS,
) -> list[TrainSplit]:
    """Time-ordered walk-forward splits with embargo + purge.

    Test windows are contiguous and non-overlapping, stepping forward by
    ``test_size``.  For each test window starting at index ``t``, the train
    window is the most recent ``train_size`` samples ending ``embargo_days +
    purge_days`` before ``t``.  No shuffling — splits are deterministic.

    Returns an empty list when there is insufficient data.

    Leakage invariants (enforced & unit-tested):
        * every train index < every test index
        * ``min(test) - max(train) >= embargo_days + purge_days``
        * train / test index sets are disjoint
    """
    n = len(dates)
    gap = _gap(embargo_days, purge_days)
    first_t = train_size + gap  # smallest t with a full train window
    splits: list[TrainSplit] = []
    t = first_t
    while t + test_size <= n:
        train_end = t - gap  # exclusive
        train_start = train_end - train_size
        if train_start < 0:
            break
        train_idx = tuple(range(train_start, train_end))
        test_idx = tuple(range(t, t + test_size))
        splits.append(
            TrainSplit(
                train_idx=train_idx,
                test_idx=test_idx,
                train_dates=tuple(dates[i] for i in train_idx),
                test_dates=tuple(dates[i] for i in test_idx),
            )
        )
        t += test_size
    return splits


def segment_index(
    dates: list[str],
    boundary: str = NORTHBOUND_RULE_CHANGE_DATE,
) -> list[int]:
    """Return segment id per date: 0 before *boundary*, 1 on/after.

    ISO date strings compare lexicographically == chronologically.
    """
    return [0 if d < boundary else 1 for d in dates]


def roll_retrain(
    dates: list[str],
    *,
    train_size: int,
    test_size: int,
    step_days: int,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
    purge_days: int = DEFAULT_PURGE_DAYS,
) -> list[TrainSplit]:
    """Rolling retrain windows stepping by *step_days*.

    Unlike :func:`purged_walk_forward`, test windows may overlap (step <
    test_size) — this is expected for rolling retrain.  Splits that would
    straddle the northbound rule-change boundary are **dropped** so no model
    is fit across the 2024-08-19 regime break (禁跨段拟合).
    """
    n = len(dates)
    gap = _gap(embargo_days, purge_days)
    seg = segment_index(dates)
    first_t = train_size + gap
    splits: list[TrainSplit] = []
    t = first_t
    while t + test_size <= n:
        train_end = t - gap
        train_start = train_end - train_size
        if train_start < 0:
            t += step_days
            continue
        train_idx = tuple(range(train_start, train_end))
        test_idx = tuple(range(t, t + test_size))
        all_idx = train_idx + test_idx
        segs = {seg[i] for i in all_idx}
        if len(segs) == 1:  # same-segment only
            splits.append(
                TrainSplit(
                    train_idx=train_idx,
                    test_idx=test_idx,
                    train_dates=tuple(dates[i] for i in train_idx),
                    test_dates=tuple(dates[i] for i in test_idx),
                )
            )
        t += step_days
    return splits


# ── Orchestrator ───────────────────────────────────────────────────────


def _regime_features(X: np.ndarray) -> np.ndarray:
    """Build (n, 2) regime features: per-sample return proxy + volatility.

    Pure projection of the feature matrix — no live data.  Column 0 is treated
    as a return proxy; volatility is the per-sample std across features.
    """
    return np.column_stack([X[:, 0], np.std(X, axis=1)])


def train_short_sector(
    X: np.ndarray,
    y: np.ndarray,
    dates: list[str],
    *,
    config: TrainConfig | None = None,
) -> dict[str, Any]:
    """Train the short_sector head on the last feasible rolling fold.

    Wires :class:`SoftVoteEnsemble` + :class:`ConformalCalibrator` +
    :class:`GaussianMixtureRegimeSwitcher` onto the train slice of the last
    split produced by :func:`roll_retrain`.

    Parameters
    ----------
    X, y:
        Feature matrix and binary label vector, aligned with *dates*.
    dates:
        Ascending ISO date strings (same length as ``X``/``y``).
    config:
        Optional :class:`TrainConfig`; defaults are sane for the short head.

    Returns
    -------
    dict
        Keys: ``ensemble``, ``calibrator``, ``regime``, ``backends``,
        ``split`` (the :class:`TrainSplit` actually used).

    Raises
    ------
    ValueError
        If the data is insufficient to form even one training fold.
    """
    cfg = config or TrainConfig()
    splits = roll_retrain(
        dates,
        train_size=cfg.train_size,
        test_size=cfg.test_size,
        step_days=cfg.step_days,
        embargo_days=cfg.embargo_days,
        purge_days=cfg.purge_days,
    )
    if not splits:
        raise ValueError(
            "insufficient data to form a training fold "
            f"(dates={len(dates)}, train_size={cfg.train_size}, "
            f"gap={_gap(cfg.embargo_days, cfg.purge_days)})"
        )

    last = splits[-1]
    tr = list(last.train_idx)
    Xtr = X[tr]
    ytr = y[tr]

    ensemble = SoftVoteEnsemble()
    ensemble.fit(Xtr, ytr)

    calibrator = ConformalCalibrator(random_state=cfg.random_state)
    calibrator.fit(Xtr, ytr)

    regime = GaussianMixtureRegimeSwitcher(random_state=cfg.random_state)
    regime.fit(_regime_features(Xtr))

    return {
        "ensemble": ensemble,
        "calibrator": calibrator,
        "regime": regime,
        "backends": ensemble.backends(),
        "split": last,
    }
