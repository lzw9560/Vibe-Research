# -*- coding: utf-8 -*-
"""S217 TDD: chronological_holdout_event_check (forward-OOS for event edges).

Pre-registered 2/3-1/3 chronological holdout reusing day_clustered_t_test.
Per spec S217 §Pre-registration: zero tunable parameters, decision rule frozen
BEFORE seeing results.

Tests are deterministic by construction (low-noise / below-floor branches,
not relying on stochastic non-significance).
"""
import pytest

from s44_verifier import stats


# ── helpers ──────────────────────────────────────────────────────────────


def _group(dates, day_mean, per_day=8, noise=0.002, seed=42):
    """Synthetic returns for a group of dates: each day has `per_day` picks
    all ≈ day_mean + uniform(-noise, noise)."""
    import random as _r

    rng = _r.Random(seed)
    rets, dts = [], []
    for d in dates:
        for _ in range(per_day):
            rets.append(day_mean + rng.uniform(-noise, noise))
            dts.append(d)
    return rets, dts


def _dates_10():
    """10 contiguous unique dates → n_train=ceil(6.67)=7, n_test=3."""
    return [f"2025-06-{i:02d}" for i in range(3, 13)]  # 06-03 .. 06-12


# ── tests ────────────────────────────────────────────────────────────────


def test_insufficient_too_few_days():
    """<4 unique dates → cannot split meaningfully → decision='insufficient'."""
    rets, dts = _group(["2025-06-03", "2025-06-04", "2025-06-05"], 0.02, per_day=5)
    r = stats.chronological_holdout_event_check(rets, dts, round_trip_cost=0.00961)
    assert r["decision"] == "insufficient"
    assert r["n_test_days"] == 0
    assert r["test_p_one_sided"] is None


def test_pre_registered_split_ratio_2_3_1_3():
    """train_ratio=0.667 → n_train=ceil(N*0.667), n_test=rest. Zero-tunable.

    10 unique days → n_train=7, n_test=3. Split is chronological (first 7 train,
    last 3 test), not shuffled.
    """
    rets, dts = _group(_dates_10(), 0.02, per_day=4)
    r = stats.chronological_holdout_event_check(rets, dts, round_trip_cost=0.00961)
    assert r["n_train_days"] == 7
    assert r["n_test_days"] == 3


def test_oos_supporting_when_test_third_materially_positive():
    """Test third materially positive + significant → 'oos_supporting'.

    First 7 dates mild, last 3 dates strongly positive (low noise → p<0.05,
    mean 0.03 > floor 0.004805).
    """
    train_dates = _dates_10()[:7]  # 06-03 .. 06-09
    test_dates = _dates_10()[7:]  # 06-10, 11, 12
    tr_r, tr_d = _group(train_dates, 0.005, noise=0.001)
    te_r, te_d = _group(test_dates, 0.03, noise=0.002, seed=7)
    r = stats.chronological_holdout_event_check(tr_r + te_r, tr_d + te_d, 0.00961)
    assert r["n_train_days"] == 7
    assert r["n_test_days"] == 3
    assert r["test_day_mean"] > 0.004805  # > floor
    assert r["test_p_one_sided"] < 0.05
    assert r["decision"] == "oos_supporting"
    assert r["train_day_mean"] is not None


def test_inconclusive_when_test_positive_but_below_floor():
    """Test third positive + significant BUT below floor → 'inconclusive'.

    Deterministic: mean 0.001 < floor 0.004805, so the AND(mean>floor) fails
    even though p<0.05. Falls through to inconclusive.
    """
    train_dates = _dates_10()[:7]
    test_dates = _dates_10()[7:]
    tr_r, tr_d = _group(train_dates, 0.02, noise=0.001)
    te_r, te_d = _group(test_dates, 0.001, noise=0.0002, seed=7)
    r = stats.chronological_holdout_event_check(tr_r + te_r, tr_d + te_d, 0.00961)
    assert r["n_test_days"] == 3
    assert r["test_day_mean"] > 0  # positive
    assert r["test_day_mean"] < 0.004805  # below floor
    assert r["decision"] == "inconclusive"


def test_strong_negative_when_test_significantly_negative():
    """Test third significantly negative (mean<0 AND p>0.95) → 'strong_negative'."""
    train_dates = _dates_10()[:7]
    test_dates = _dates_10()[7:]
    tr_r, tr_d = _group(train_dates, 0.02, noise=0.001)
    te_r, te_d = _group(test_dates, -0.03, noise=0.002, seed=7)
    r = stats.chronological_holdout_event_check(tr_r + te_r, tr_d + te_d, 0.00961)
    assert r["n_test_days"] == 3
    assert r["test_day_mean"] < 0
    assert r["test_p_one_sided"] > 0.95
    assert r["decision"] == "strong_negative"


def test_floor_respects_round_trip_cost():
    """materiality floor = max(0.003, cost*0.5). cost=0.02 → floor=0.01.

    Test third mean ~0.005 < 0.01 → inconclusive (positive but below floor).
    """
    rets, dts = _group(_dates_10(), 0.005, per_day=6, noise=0.0005)
    r = stats.chronological_holdout_event_check(rets, dts, round_trip_cost=0.02)
    assert r["decision"] == "inconclusive"


def test_does_not_mutate_inputs():
    """Immutability: function must not mutate returns/dates lists."""
    rets, dts = _group(_dates_10(), 0.02, per_day=4)
    rets_copy, dts_copy = list(rets), list(dts)
    stats.chronological_holdout_event_check(rets, dts, round_trip_cost=0.00961)
    assert rets == rets_copy
    assert dts == dts_copy


def test_train_ratio_is_pre_registered_and_overridable():
    """train_ratio defaults to 0.667 (pre-registered); caller can override
    only by passing explicitly (no tuning in the real harness)."""
    rets, dts = _group(_dates_10(), 0.02, per_day=4)
    # default 0.667 → 7/3
    r_default = stats.chronological_holdout_event_check(rets, dts, 0.00961)
    assert r_default["n_train_days"] == 7
    # explicit 0.5 → 5/5
    r_half = stats.chronological_holdout_event_check(
        rets, dts, 0.00961, train_ratio=0.5
    )
    assert r_half["n_train_days"] == 5
    assert r_half["n_test_days"] == 5
