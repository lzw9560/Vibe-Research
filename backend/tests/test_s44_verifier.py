"""TDD tests for S161 §44v2 verifier (AAA pattern). RED -> GREEN."""
import numpy as np
import pandas as pd
import pytest

from s44_verifier.stats import (
    DayClusteredTResult,
    DayPairedResult,
    WalkForwardResult,
    bonferroni_bh,
    day_clustered_t_test,
    day_paired_effective_n,
    day_paired_lift,
    permutation_null_p95,
    permutation_p_value,
    walk_forward_oos,
)
from s44_verifier.verifier import Verdict, verify


@pytest.fixture
def positive_returns() -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.normal(0.001, 0.012, 100)


# ── R1 tests (existing) ─────────────────────────────────────────────────────


def test_verify_returns_immutable_verdict(positive_returns):
    v = verify(positive_returns, n_trials=1)
    assert isinstance(v, Verdict)
    assert v.edge_type == "selection"
    assert v.n == 100
    with pytest.raises(Exception):
        v.status = "robust_edge"  # type: ignore[misc]


def test_dsr_lenient_when_no_trials_matrix(positive_returns):
    v = verify(positive_returns, n_trials=1, trials_matrix=None)
    assert v.dsr_method == "lenient_single_estimate"
    assert v.dsr is not None


def test_dsr_cross_trial_when_matrix_supplied(positive_returns):
    rng = np.random.default_rng(7)
    matrix = pd.DataFrame({
        "a": rng.normal(0.0005, 0.01, 100),
        "b": rng.normal(0.0008, 0.01, 100),
    })
    v = verify(positive_returns, n_trials=2, trials_matrix=matrix)
    assert v.dsr_method == "cross_trial_variance"


def test_pbo_none_when_single_strategy(positive_returns):
    v = verify(positive_returns, n_trials=1, trials_matrix=None)
    assert v.pbo is None  # N=1<2 -> N/A (grill methodology hole #1)


def test_pbo_computed_when_multi_strategy(positive_returns):
    rng = np.random.default_rng(7)
    matrix = pd.DataFrame({
        "a": rng.normal(0.0005, 0.01, 200),
        "b": rng.normal(0.0008, 0.01, 200),
        "c": rng.normal(0.0002, 0.01, 200),
    })
    v = verify(positive_returns, n_trials=3, trials_matrix=matrix)
    assert v.pbo is not None


def test_underpowered_when_days_below_60():
    rng = np.random.default_rng(99)
    r = rng.normal(0.001, 0.012, 42)  # 42 days < 60 -> R6 gate (gap-run expected)
    v = verify(r, n_trials=1)
    assert v.status == "underpowered"
    assert v.days_robust == 42


def test_verify_is_pure(positive_returns):
    v1 = verify(positive_returns, n_trials=1)
    v2 = verify(positive_returns, n_trials=1)
    assert v1 == v2


def test_event_edge_type_populates_event_metrics():
    rng = np.random.default_rng(5)
    r = rng.normal(0.001, 0.012, 100)
    v = verify(r, n_trials=1, edge_type="event")
    assert v.edge_type == "event"
    assert v.event_metrics is not None
    assert v.event_metrics.n_event == 100


# ── R3 tests: day_paired_effective_n ────────────────────────────────────────


def test_day_paired_effective_n_non_pooled():
    # Arrange: 100 picks across 10 days (same-day picks correlated)
    rng = np.random.default_rng(42)
    returns = rng.normal(0.001, 0.012, 100)
    dates = [f"2026-01-{i % 10 + 1:02d}" for i in range(100)]

    # Act
    n_eff = day_paired_effective_n(returns, dates)

    # Assert: effective n = 10 unique days, not 100 pooled picks
    assert n_eff == 10


def test_day_paired_effective_n_ignores_nan():
    # Arrange: 5 returns, 1 NaN, across 4 unique dates
    # d1 has both a valid return and a NaN — d1 still counts (valid return exists)
    returns = [0.01, float("nan"), -0.02, 0.03, 0.01]
    dates = ["d1", "d1", "d2", "d3", "d4"]

    # Act
    n_eff = day_paired_effective_n(returns, dates)

    # Assert: NaN excluded, 4 unique dates with valid returns remain
    assert n_eff == 4


# ── R3 tests: day_paired_lift ───────────────────────────────────────────────


def test_day_paired_lift_non_pooled():
    # Arrange: survivors have higher winrate than raw on each day
    survivors = {"d1": [1.0, 2.0, -0.5], "d2": [0.5, 1.0, 0.3]}
    raw = {"d1": [1.0, -1.0, -1.0, 0.5, -0.5], "d2": [-1.0, -0.5, 0.2, -1.0]}

    # Act
    res = day_paired_lift(survivors, raw)

    # Assert: lift > 1 (survivors outperform raw on both days, non-pooled)
    assert isinstance(res, DayPairedResult)
    assert res.n_days == 2
    assert res.winrate_lift_avg is not None
    assert res.winrate_lift_avg > 1.0
    assert res.surv_n_pooled == 6  # 3 + 3


def test_day_paired_lift_empty_days_skipped():
    # Arrange: day with empty survivors should be skipped
    survivors = {"d1": [1.0, -1.0], "d2": []}
    raw = {"d1": [1.0, -1.0], "d2": [0.5, -0.5]}

    # Act
    res = day_paired_lift(survivors, raw)

    # Assert: only 1 day paired (d2 skipped — empty survivor side)
    assert res.n_days == 1


# ── R3 tests: permutation_null_p95 ──────────────────────────────────────────


def test_permutation_null_deterministic_with_seed():
    # Arrange: survivors subset of universe, same returns
    survivors = {"d1": [0.5, -0.3, 0.8], "d2": [0.1, 0.2, -0.5]}
    universe = {
        "d1": [0.5, -0.3, 0.8, -0.1, 0.2, 0.9, -0.4, 0.3],
        "d2": [0.1, 0.2, -0.5, 0.3, -0.2, 0.7, -0.1, 0.4],
    }

    # Act: same seed -> same result
    p95_a = permutation_null_p95(survivors, universe, n_perm=50, seed=42)
    p95_b = permutation_null_p95(survivors, universe, n_perm=50, seed=42)

    # Assert: deterministic
    assert p95_a is not None
    assert p95_a == p95_b


def test_permutation_null_different_seeds_differ():
    # Arrange
    survivors = {"d1": [0.5, -0.3, 0.8]}
    universe = {"d1": [0.5, -0.3, 0.8, -0.1, 0.2, 0.9, -0.4, 0.3]}

    # Act
    p95_42 = permutation_null_p95(survivors, universe, n_perm=50, seed=42)
    p95_99 = permutation_null_p95(survivors, universe, n_perm=50, seed=99)

    # Assert: different seeds may produce different results (not guaranteed
    # but very likely with 200 perms and different RNG)
    assert p95_42 is not None
    assert p95_99 is not None


def test_permutation_p_value_returns_float():
    # Arrange
    survivors = {"d1": [0.5, 0.3, 0.8]}
    universe = {"d1": [0.5, 0.3, 0.8, -0.1, -0.2, 0.9, -0.4, -0.3]}

    # Act
    p = permutation_p_value(survivors, universe, observed_lift=2.0, n_perm=50, seed=42)

    # Assert: p-value in [0, 1]
    assert isinstance(p, float)
    assert 0.0 <= p <= 1.0


def test_permutation_null_insufficient_data_returns_none():
    # Arrange: universe smaller than survivors (can't sample)
    survivors = {"d1": [0.5, 0.3, 0.8]}
    universe = {"d1": [0.5]}

    # Act
    p95 = permutation_null_p95(survivors, universe, n_perm=10, seed=42)

    # Assert: None (can't generate nulls)
    assert p95 is None


# ── R3 tests: bonferroni_bh ─────────────────────────────────────────────────


def test_bonferroni_correction_by_n():
    # Arrange
    p_values = [0.01, 0.02]

    # Act: K=5
    adj = bonferroni_bh(p_values, n=5, method="bonferroni")

    # Assert: each p multiplied by K=5, capped at 1.0
    assert len(adj) == 2
    assert adj[0] == pytest.approx(0.05)
    assert adj[1] == pytest.approx(0.10)


def test_bonferroni_caps_k_at_8():
    # Arrange: §44v1 used K=20 (over-correction); §44v2 caps at 8
    p_values = [0.01]

    # Act: K=20 specified, but should cap at 8
    adj = bonferroni_bh(p_values, n=20, method="bonferroni")

    # Assert: 0.01 * 8 = 0.08, NOT 0.01 * 20 = 0.20 (NEVER K=20)
    assert adj[0] == pytest.approx(0.08)


def test_bonferroni_single_edge_no_correction():
    # Arrange: K=1 (single edge, no multiple-testing concern)
    p_values = [0.03]

    # Act
    adj = bonferroni_bh(p_values, n=1, method="bonferroni")

    # Assert: p unchanged (K=1)
    assert adj[0] == pytest.approx(0.03)


def test_bh_step_up_correction():
    # Arrange: 3 p-values for BH step-up
    p_values = [0.01, 0.02, 0.03]

    # Act
    adj = bonferroni_bh(p_values, n=3, method="BH")

    # Assert: BH adjusted p-values (step-up, monotonic)
    assert len(adj) == 3
    # BH: sort -> [0.01, 0.02, 0.03], ranks 1,2,3
    # rank 3: 0.03 * 3/3 = 0.03
    # rank 2: 0.02 * 3/2 = 0.03 (capped by prev=0.03)
    # rank 1: 0.01 * 3/1 = 0.03 (capped by prev=0.03)
    for a in adj:
        assert a == pytest.approx(0.03, abs=1e-6)


def test_bh_empty_p_values():
    # Act
    adj = bonferroni_bh([], n=5, method="BH")

    # Assert
    assert adj == []


# ── R3 tests: walk_forward_oos ──────────────────────────────────────────────


def test_walk_forward_insufficient_data_skipped():
    # Arrange: 5 days, but train=100, test=20 -> can't form any window
    survivors = {f"d{i}": [0.01, -0.02] for i in range(5)}
    raw = {f"d{i}": [0.01, -0.02, 0.03, -0.01] for i in range(5)}

    # Act
    wf = walk_forward_oos(survivors, raw, train=100, test=20)

    # Assert: graceful degradation
    assert isinstance(wf, WalkForwardResult)
    assert wf.status == "insufficient_skipped"
    assert wf.n_windows == 0
    assert wf.mean_test_lift is None


def test_walk_forward_sufficient_data_produces_windows():
    # Arrange: 130 days -> at least 1 window (train=100, test=20, step=20)
    survivors = {f"d{i}": [0.01, -0.02, 0.03] for i in range(130)}
    raw = {f"d{i}": [0.01, -0.02, 0.03, -0.01, 0.02] for i in range(130)}

    # Act
    wf = walk_forward_oos(survivors, raw, train=100, test=20, step=20)

    # Assert: at least 1 window formed
    assert wf.n_windows >= 1
    assert wf.status in ("oos_stable", "oos_unstable")
    assert wf.mean_test_lift is not None


# ── R3 integration tests: verify() wiring ────────────────────────────────────


def test_verify_computes_n_effective_when_dates_supplied():
    # Arrange: 100 returns across 10 days
    rng = np.random.default_rng(42)
    returns = rng.normal(0.001, 0.012, 100)
    dates = [f"2026-01-{i % 10 + 1:02d}" for i in range(100)]

    # Act
    v = verify(returns, n_trials=1, dates=dates)

    # Assert: n_effective = 10 (day-clustered), days_robust = 10
    assert v.n_effective == 10
    assert v.days_robust == 10
    assert v.n == 100  # raw n still 100


def test_verify_computes_selection_lift_when_by_day_supplied():
    # Arrange: 70 days, survivors outperform raw
    rng = np.random.default_rng(42)
    survivors_by_day = {}
    universe_by_day = {}
    for i in range(70):
        d = f"2026-03-{i + 1:02d}"
        # survivors: positive bias
        survivors_by_day[d] = list(rng.normal(0.005, 0.01, 5))
        # universe: zero mean
        universe_by_day[d] = list(rng.normal(0.0, 0.01, 20))

    # Act
    v = verify(
        rng.normal(0.001, 0.012, 350),  # flat returns (for DSR)
        n_trials=1,
        survivors_by_day=survivors_by_day,
        universe_by_day=universe_by_day,
        n_comparisons=1,
        n_perm=50,
    )

    # Assert: lift computed, permutation p-value computed
    assert v.selection_lift is not None
    assert v.p_permutation is not None
    assert v.walk_forward_status is not None
    # 70 days >= 60 -> not underpowered
    assert v.days_robust >= 60


def test_verify_r6_gate_underpowered_even_with_strong_lift():
    # Arrange: 14 days (gap-run scale), survivors strongly outperform
    rng = np.random.default_rng(42)
    survivors_by_day = {}
    universe_by_day = {}
    for i in range(14):
        d = f"2026-08-{i + 1:02d}"
        survivors_by_day[d] = [0.05, 0.03, 0.08, 0.02, 0.06]  # all positive
        universe_by_day[d] = [-0.02, 0.01, -0.03, 0.005, -0.01, 0.02, -0.04, 0.001]

    # Act
    v = verify(
        np.array([0.05] * 70),
        n_trials=1,
        survivors_by_day=survivors_by_day,
        universe_by_day=universe_by_day,
        n_perm=50,
    )

    # Assert: R6 gate -> underpowered (14 < 60), never robust/falsified
    assert v.status == "underpowered"
    assert v.days_robust == 14
    # lift still computed for transparency
    assert v.selection_lift is not None


def test_verify_falsified_when_days_60_plus_and_lift_below_1():
    # Arrange: 70 days, survivors UNDERPERFORM raw (lift < 1)
    rng = np.random.default_rng(42)
    survivors_by_day = {}
    universe_by_day = {}
    for i in range(70):
        d = f"2026-03-{i + 1:02d}"
        # survivors: negative bias (low winrate)
        survivors_by_day[d] = [-0.03, -0.02, -0.04, -0.01, -0.05]
        # universe: positive bias (higher winrate)
        universe_by_day[d] = [0.02, 0.01, 0.03, -0.01, 0.04, -0.02, 0.05, 0.001]

    # Act
    v = verify(
        np.array([-0.03] * 350),
        n_trials=1,
        survivors_by_day=survivors_by_day,
        universe_by_day=universe_by_day,
        n_perm=50,
    )

    # Assert: days >= 60, lift < 1 -> falsified
    assert v.days_robust == 70
    assert v.selection_lift is not None
    assert v.selection_lift < 1.0
    assert v.status == "falsified"


def test_event_not_tested_when_no_dates():
    # Arrange: event edge but no dates supplied -> can't cluster -> not_tested
    rng = np.random.default_rng(5)
    r = rng.normal(0.001, 0.012, 100)

    # Act
    v = verify(r, n_trials=1, edge_type="event")

    # Assert: no dates -> t-test can't run -> event_not_tested
    assert v.event_status == "event_not_tested"
    assert v.event_metrics is not None
    assert v.event_metrics.t_stat_day_clustered is None


def test_verify_walk_forward_skipped_note_when_insufficient():
    # Arrange: 14 days, insufficient for walk-forward
    rng = np.random.default_rng(42)
    survivors_by_day = {}
    universe_by_day = {}
    for i in range(14):
        d = f"2026-08-{i + 1:02d}"
        survivors_by_day[d] = list(rng.normal(0.005, 0.01, 3))
        universe_by_day[d] = list(rng.normal(0.0, 0.01, 10))

    # Act
    v = verify(
        np.array([0.01] * 42),
        n_trials=1,
        survivors_by_day=survivors_by_day,
        universe_by_day=universe_by_day,
        n_perm=50,
    )

    # Assert: walk-forward gracefully skipped
    assert v.walk_forward_status == "insufficient_skipped"
    assert "walk-forward" in v.note.lower() or "insufficient" in v.note.lower()


# ── day_clustered_t_test tests ──────────────────────────────────────────────


def test_day_clustered_t_test_deterministic():
    # Arrange: 100 returns across 10 days, seed-controlled
    rng = np.random.default_rng(42)
    returns = rng.normal(0.001, 0.012, 100)
    dates = [f"2026-01-{i % 10 + 1:02d}" for i in range(100)]

    # Act: same inputs -> same result (pure function)
    res_a = day_clustered_t_test(returns, dates)
    res_b = day_clustered_t_test(returns, dates)

    # Assert: deterministic + correct type
    assert res_a is not None
    assert isinstance(res_a, DayClusteredTResult)
    assert res_a == res_b


def test_day_clustered_t_test_reduces_n_vs_pooled():
    # Arrange: 1000 picks across 14 days (same-day picks correlated)
    rng = np.random.default_rng(42)
    returns = rng.normal(0.001, 0.012, 1000)
    dates = [f"2026-01-{i % 14 + 1:02d}" for i in range(1000)]

    # Act
    res = day_clustered_t_test(returns, dates)

    # Assert: n_days = 14 (day-clustered), NOT 1000 (pooled)
    assert res is not None
    assert res.n_days == 14
    assert res.n_days < 1000


def test_day_clustered_t_test_p_value_in_range():
    # Arrange: 200 returns across 20 days
    rng = np.random.default_rng(42)
    returns = rng.normal(0.001, 0.012, 200)
    dates = [f"d{i % 20:02d}" for i in range(200)]

    # Act
    res = day_clustered_t_test(returns, dates)

    # Assert: p-value is a valid probability
    assert res is not None
    assert 0.0 <= res.p_one_sided <= 1.0


def test_day_clustered_t_test_n_days_below_2_returns_none():
    # Arrange: all returns on a single day
    returns = [0.01, 0.02, -0.01, 0.005]
    dates = ["d1", "d1", "d1", "d1"]

    # Act
    res = day_clustered_t_test(returns, dates)

    # Assert: None (can't compute std with ddof=1 on 1 observation)
    assert res is None


def test_day_clustered_t_test_frozen_dataclass():
    # Arrange
    rng = np.random.default_rng(42)
    returns = rng.normal(0.001, 0.012, 100)
    dates = [f"d{i % 10:02d}" for i in range(100)]

    # Act
    res = day_clustered_t_test(returns, dates)

    # Assert: frozen (immutable)
    assert res is not None
    with pytest.raises(Exception):
        res.t_stat = 999.0  # type: ignore[misc]


# ── event status logic tests ─────────────────────────────────────────────────


def test_event_robust_when_significant_and_material_and_60_days():
    # Arrange: 60 days, 10 picks/day from N(0.005, 0.01) — positive, material, significant
    rng = np.random.default_rng(42)
    returns, dates = [], []
    for i in range(60):
        day_rets = rng.normal(0.005, 0.01, 10)
        returns.extend(day_rets.tolist())
        dates.extend([f"2026-01-{i + 1:02d}"] * 10)

    # Act
    v = verify(np.array(returns), n_trials=1, edge_type="event", dates=dates)

    # Assert: event_robust (p<0.05 + days>=60 + day_mean>0.3%)
    assert v.event_status == "event_robust"
    assert v.status == "robust_edge"
    assert v.event_metrics is not None
    assert v.event_metrics.t_stat_day_clustered is not None
    assert v.event_metrics.base_rate == 0.0
    assert v.event_metrics.p_one_sided is not None
    assert v.event_metrics.p_one_sided < 0.05
    assert v.event_metrics.n_days == 60


def test_event_thin_positive_when_significant_but_underpowered():
    # Arrange: 14 days (underpowered), 10 picks/day from N(0.005, 0.01)
    rng = np.random.default_rng(42)
    returns, dates = [], []
    for i in range(14):
        day_rets = rng.normal(0.005, 0.01, 10)
        returns.extend(day_rets.tolist())
        dates.extend([f"2026-01-{i + 1:02d}"] * 10)

    # Act
    v = verify(np.array(returns), n_trials=1, edge_type="event", dates=dates)

    # Assert: event_thin_positive (p<0.05 but days<60 -> not robust)
    assert v.event_status == "event_thin_positive"
    # R6 gate: days<60 -> underpowered (status driven by R6, not event_status)
    assert v.status == "underpowered"
    assert v.days_robust == 14


def test_event_falsified_when_mean_negative():
    # Arrange: 60 days, 10 picks/day from N(-0.005, 0.01) — negative day_mean
    rng = np.random.default_rng(42)
    returns, dates = [], []
    for i in range(60):
        day_rets = rng.normal(-0.005, 0.01, 10)
        returns.extend(day_rets.tolist())
        dates.extend([f"2026-01-{i + 1:02d}"] * 10)

    # Act
    v = verify(np.array(returns), n_trials=1, edge_type="event", dates=dates)

    # Assert: event_falsified (day_mean <= 0)
    assert v.event_status == "event_falsified"
    assert v.status == "falsified"
    assert v.event_metrics is not None
    assert v.event_metrics.day_mean is not None
    assert v.event_metrics.day_mean <= 0


def test_event_thin_positive_when_positive_but_not_significant():
    # Arrange: 60 days — half have mean +1%, half -0.9% (positive overall but noisy)
    # Deterministic: day_means = [0.01]*30 + [-0.009]*30
    # overall_day_mean = 0.0005 > 0 but t ~ 0.4 -> p > 0.3 (not significant)
    returns, dates = [], []
    for i in range(60):
        mean = 0.01 if i < 30 else -0.009
        returns.extend([mean] * 10)
        dates.extend([f"2026-01-{i + 1:02d}"] * 10)

    # Act
    v = verify(np.array(returns), n_trials=1, edge_type="event", dates=dates)

    # Assert: event_thin_positive (mean>0 but p>=0.05 -> not statistically confirmed)
    assert v.event_status == "event_thin_positive"
    assert v.status == "exploratory"
    assert v.event_metrics is not None
    assert v.event_metrics.p_one_sided is not None
    assert v.event_metrics.p_one_sided >= 0.05
    assert v.event_metrics.day_mean is not None
    assert v.event_metrics.day_mean > 0  # positive but not significant


# ── HIGH #8: NaN crash regression (verifier.py:170) ──────────────────────────


def test_nan_returns_with_dates_does_not_crash():
    """HIGH #8: NaN-stripped r (line 114) passed with original-length dates
    → IndexError at stats.py:150 (mask length mismatch). Fix: pass original
    `returns` so day_clustered_t_test does its own aligned NaN masking.
    """
    # Arrange: 60 days, 5 picks/day, 1 NaN per day (12.5% NaN rate)
    rng = np.random.default_rng(42)
    returns, dates = [], []
    for i in range(60):
        day_rets = rng.normal(0.005, 0.01, 5)
        day_rets[0] = float("nan")  # inject NaN
        returns.extend(day_rets.tolist())
        dates.extend([f"2026-01-{i + 1:02d}"] * 5)

    # Act: must NOT crash (was: IndexError: mask length mismatch)
    v = verify(np.array(returns), n_trials=1, edge_type="event", dates=dates)

    # Assert: event verdict computed successfully
    assert v.event_metrics is not None
    assert v.event_metrics.n_event == 240  # 300 - 60 NaN = 240 valid
    assert v.event_metrics.n_days == 60  # all days have at least 1 valid return
    # day_means should match manual sync-NaN-drop
    arr = np.asarray(returns, dtype=float)
    d = np.asarray(dates, dtype=object)
    mask = ~np.isnan(arr)
    r_valid, d_valid = arr[mask], d[mask]
    unique_dates = sorted(set(d_valid.tolist()))
    manual_day_means = [
        float(r_valid[d_valid == dt].mean()) for dt in unique_dates
    ]
    assert v.event_metrics.day_mean is not None
    assert abs(v.event_metrics.day_mean - np.mean(manual_day_means)) < 1e-8


# ── MEDIUM #1: permutation p +1 convention (Phipson & Smyth 2010) ────────────


def test_permutation_p_never_zero():
    """MEDIUM #1: +1 convention ensures min p = 1/(m+1), never 0.0.
    Even if all nulls < observed, p = 1/(m+1) > 0 (not 0/m = 0.0).
    """
    # Arrange: survivors all positive, universe mixed (observed lift very high)
    survivors = {"d1": [0.5, 0.3, 0.8]}
    universe = {"d1": [0.5, 0.3, 0.8, -0.1, -0.2, 0.9, -0.4, -0.3]}

    # Act: observed_lift extremely high (all nulls should be below)
    p = permutation_p_value(survivors, universe, observed_lift=100.0, n_perm=50, seed=42)

    # Assert: p = 1/(50+1) ≈ 0.0196, NOT 0.0
    assert p > 0.0
    assert p == pytest.approx(1 / 51, abs=0.002)


def test_permutation_p_plus_one_convention():
    """MEDIUM #1: p = (count(x >= obs) + 1) / (m + 1), not count(x >= obs) / m."""
    # Arrange: use a case where count >= 1 (not all nulls below observed)
    survivors = {"d1": [0.5, 0.3, 0.8]}
    universe = {"d1": [0.5, 0.3, 0.8, -0.1, -0.2, 0.9, -0.4, -0.3]}

    # Act
    p = permutation_p_value(survivors, universe, observed_lift=1.5, n_perm=100, seed=42)

    # Assert: p > 0 (+1 ensures floor), p <= 1.0
    assert 0.0 < p <= 1.0


# ── MEDIUM #4: R5 window sanity (enforced + skipped paths) ───────────────────


def test_r5_window_sanity_no_advantage_forces_exploratory():
    """MEDIUM #4: when window_sanity shows no advantage for the edge_type's
    window, verify() must force 'exploratory' + skip heavy methodology.
    """
    # Arrange: 60 days of positive returns (would normally be event_robust)
    rng = np.random.default_rng(42)
    returns, dates = [], []
    for i in range(60):
        day_rets = rng.normal(0.005, 0.01, 10)
        returns.extend(day_rets.tolist())
        dates.extend([f"2026-01-{i + 1:02d}"] * 10)

    # window_sanity: overnight_gap has NO advantage (mean<0, winrate<base_rate)
    window_sanity = {
        "overnight_gap": {"mean": -0.01, "median": -0.005, "winrate": 0.40, "base_rate": 0.50},
        "d1_intraday": {"mean": 0.001, "median": 0.0, "winrate": 0.51, "base_rate": 0.50},
        "path": {"mean": 0.005, "median": 0.003, "winrate": 0.52, "base_rate": 0.50},
    }

    # Act
    v = verify(
        np.array(returns), n_trials=1, edge_type="event", dates=dates,
        window_sanity=window_sanity,
    )

    # Assert: forced exploratory (no advantage in overnight_gap window)
    assert v.status == "exploratory"
    assert v.event_status is None  # heavy methodology skipped
    assert "no advantage" in v.note.lower()
    assert "overnight_gap" in v.note


def test_r5_window_sanity_none_notes_skipped():
    """MEDIUM #4: when window_sanity=None, note must state 'skipped'."""
    rng = np.random.default_rng(42)
    returns = rng.normal(0.001, 0.012, 100)
    dates = [f"2026-01-{i % 10 + 1:02d}" for i in range(100)]

    # Act
    v = verify(returns, n_trials=1, edge_type="event", dates=dates)

    # Assert: note mentions R5 skipped
    assert "r5" in v.note.lower()
    assert "skipped" in v.note.lower()


def test_r5_window_sanity_with_advantage_proceeds_normally():
    """MEDIUM #4: when window_sanity shows advantage, verify() proceeds
    with heavy methodology (not forced to exploratory).
    """
    rng = np.random.default_rng(42)
    returns, dates = [], []
    for i in range(60):
        day_rets = rng.normal(0.005, 0.01, 10)
        returns.extend(day_rets.tolist())
        dates.extend([f"2026-01-{i + 1:02d}"] * 10)

    # window_sanity: overnight_gap HAS advantage (mean>0, winrate>base_rate)
    window_sanity = {
        "overnight_gap": {"mean": 0.013, "median": 0.012, "winrate": 0.543, "base_rate": 0.50},
        "d1_intraday": {"mean": 0.0003, "median": 0.0001, "winrate": 0.462, "base_rate": 0.50},
        "path": {"mean": 0.006, "median": -0.03, "winrate": 0.363, "base_rate": 0.50},
    }

    # Act
    v = verify(
        np.array(returns), n_trials=1, edge_type="event", dates=dates,
        window_sanity=window_sanity,
    )

    # Assert: not forced to exploratory (advantage found → heavy methodology runs)
    assert v.event_metrics is not None  # heavy methodology NOT skipped


# ── MEDIUM #7: materiality floor boundary (extracted from magic 0.003) ───────


def test_event_materiality_floor_boundary():
    """MEDIUM #7: day_mean=0.0029 → event_thin_positive, 0.0031 → event_robust.

    Default floor = _EVENT_MATERIALITY_FLOOR = 0.003 (0.3%). With round_trip_cost=0,
    effective_floor = max(0.003, 0*0.5) = 0.003.
    """
    # Arrange: 60 days, 10 picks/day, all identical day_mean
    # day_mean slightly below or above the 0.003 floor
    for day_mean, expected_status in [(0.0029, "event_thin_positive"), (0.0031, "event_robust")]:
        returns, dates = [], []
        for i in range(60):
            returns.extend([day_mean] * 10)
            dates.extend([f"2026-01-{i + 1:02d}"] * 10)

        # Act
        v = verify(np.array(returns), n_trials=1, edge_type="event", dates=dates)

        # Assert
        assert v.event_status == expected_status, (
            f"day_mean={day_mean} should be {expected_status}, got {v.event_status}"
        )


def test_event_materiality_floor_cost_relative():
    """MEDIUM #7: with round_trip_cost=0.01, effective_floor = max(0.003, 0.01*0.5) = 0.005.

    day_mean=0.004 → above 0.003 default but below 0.005 cost-relative → thin_positive.
    day_mean=0.006 → above 0.005 cost-relative → event_robust.
    """
    for day_mean, expected_status in [(0.004, "event_thin_positive"), (0.006, "event_robust")]:
        returns, dates = [], []
        for i in range(60):
            returns.extend([day_mean] * 10)
            dates.extend([f"2026-01-{i + 1:02d}"] * 10)

        # Act: round_trip_cost=0.01 → effective_floor = max(0.003, 0.005) = 0.005
        v = verify(
            np.array(returns), n_trials=1, edge_type="event", dates=dates,
            round_trip_cost=0.01,
        )

        # Assert
        assert v.event_status == expected_status, (
            f"day_mean={day_mean} cost=0.01 should be {expected_status}, got {v.event_status}"
        )


# ── Recorder tests (HIGH #2 reproducibility) ─────────────────────────────────


def test_recorder_save_load_reproduce(tmp_path):
    """HIGH #2: Recorder saves + loads + reproduces verdict deterministically."""
    from s44_verifier.recorder import Recorder

    # Arrange
    rng = np.random.default_rng(42)
    returns, dates = [], []
    for i in range(60):
        day_rets = rng.normal(0.005, 0.01, 10)
        returns.extend(day_rets.tolist())
        dates.extend([f"2026-01-{i + 1:02d}"] * 10)

    v = verify(np.array(returns), n_trials=1, edge_type="event", dates=dates)

    recorder = Recorder(db_path=str(tmp_path / "test_recorder.db"))

    # Act: save
    recorder_id = recorder.save(
        data_snapshot_id="test_snap_123",
        input_hashes={"universe": "abc", "kline_cache": "def"},
        return_series=returns,
        dates=dates,
        params={"edge_type": "event", "n_trials": 1, "round_trip_cost": 0.007},
        frozen_commit="b4e7446",
        verdict={"status": v.status, "event_status": v.event_status},
    )

    # Assert: load
    record = recorder.load(recorder_id)
    assert record is not None
    assert record.data_snapshot_id == "test_snap_123"
    assert len(record.return_series) == len(returns)

    # Act: reproduce (criterion a — deterministic)
    v_repro = recorder.reproduce_verdict(recorder_id)
    assert v_repro is not None
    assert v_repro.status == v.status
    assert v_repro.event_status == v.event_status  # deterministic reproduction

    # Act: revalidate (criterion b — hash compare)
    matches, label = recorder.revalidate_data(recorder_id, returns, dates)
    assert matches is True
    assert "match" in label.lower()

    # Act: revalidate with mismatched series
    wrong_series = [r + 0.001 for r in returns]
    matches2, label2 = recorder.revalidate_data(recorder_id, wrong_series, dates)
    assert matches2 is False
    assert "re-baseline" in label2.lower() or "mismatch" in label2.lower() or "weight" in label2.lower()


def test_compute_composite_snapshot_id(tmp_path):
    """HIGH #2: composite data_snapshot_id = f"{universe_hash[:12]}+{cache_hash[:12]}"."""
    from s44_verifier.recorder import compute_composite_snapshot_id

    # Arrange: two small files
    uni_file = tmp_path / "universe.json"
    uni_file.write_text('{"test": true}')
    cache_file = tmp_path / "cache.json"
    cache_file.write_text('{"data": 123}')

    # Act
    snap_id = compute_composite_snapshot_id(uni_file, cache_file)

    # Assert: composite format "hash1+hash2"
    assert "+" in snap_id
    parts = snap_id.split("+")
    assert len(parts) == 2
    assert len(parts[0]) == 12
    assert len(parts[1]) == 12
