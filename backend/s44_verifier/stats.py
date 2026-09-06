"""S161 R3: §44v2 statistical methodology — merged from backend/tools/.

Owns ALL statistical methodology (Accounting does NOT). Internal components
used by ``verifier.verify()``. The tools/ scripts remain as CLI wrappers — they
keep their own copies of the logic; this module is the canonical home.

Sources merged:
- day_paired_lift: ``first_board_layer_lift.py:138`` + ``pead_event_study.py:275`` (fast)
- permutation null: ``pead_event_study.py:316`` (N_PERM=500, seed=42) +
  ``platform_breakout_lift.py:40`` (day_cluster_permutation, N_PERM=2000)
- bonferroni/bh: ``pead_event_study.py`` ALPHA_ADJ=0.05/5 +
  ``platform_breakout_lift.py`` K=8 + ``multifactor_combo_test.py`` K=10
  -> generalized by-n (NEVER K=20 per S159 v2)
- walk-forward: ``platform_breakout_lift.py:179`` (train=100/test=20/step=20) +
  ``low_absorption_c3_lift.py:170`` + ``multifactor_combo_test.py`` (LODO/expanding)
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy import stats as sp_stats

# ── constants (merged from sources) ──────────────────────────────────────────
_N_PERM_DEFAULT = 500          # pead_event_study.py N_PERM
_PERM_SEED_DEFAULT = 42        # pead_event_study.py PERM_SEED
_WALK_TRAIN_DEFAULT = 100      # platform_breakout_lift.py WALK_TRAIN
_WALK_TEST_DEFAULT = 20        # platform_breakout_lift.py WALK_TEST
_WALK_STEP_DEFAULT = 20        # platform_breakout_lift.py WALK_STEP
_MAX_BONFERRONI_K = 8          # §44v2: cap K at 8, NEVER K=20 (v1 over-correction)


@dataclass(frozen=True)
class DayPairedResult:
    """Non-pooled day-clustered lift result."""

    n_days: int
    winrate_lift_avg: float | None
    mean_lift_avg: float | None
    surv_n_pooled: int
    raw_n_pooled: int


@dataclass(frozen=True)
class WalkForwardResult:
    """Rolling walk-forward OOS result.

    Status:
    - ``"insufficient_skipped"``: 0 windows (not enough days — graceful degradation)
    - ``"oos_stable"``: all test windows have lift >= 1.0
    - ``"oos_unstable"``: some test windows have lift < 1.0
    """

    n_windows: int
    test_lifts: tuple[float, ...]
    test_n_per_window: tuple[int, ...]
    mean_test_lift: float | None
    status: Literal["oos_stable", "oos_unstable", "insufficient_skipped"]


@dataclass(frozen=True)
class DayClusteredTResult:
    """One-sample day-clustered t-test result (is mean > 0 after cost).

    Day-clustering accounts for within-day correlation: each trading day is
    one observation (day_mean = mean of returns on that day). The t-test then
    tests whether the mean of day-means is significantly > 0.

    This is the correct test for event edges where same-day picks are
    correlated — a pooled t-test inflates n and produces false significance
    (§44 proven: 1000 picks across 14 days -> effective n ~ 14, not 1000).
    """

    t_stat: float
    p_one_sided: float
    n_days: int
    day_mean: float
    day_std: float


# ── helpers ──────────────────────────────────────────────────────────────────


def _winrate(returns: list[float]) -> float:
    """Winrate = fraction of positive returns. Empty -> 0.0."""
    if not returns:
        return 0.0
    return sum(1 for r in returns if r > 0) / len(returns)


def _fast_sample(lst: list, k: int, rng: random.Random) -> list:
    """Sample k from lst without O(n) copy. O(k) for k << n (set-based).

    Merged from ``pead_event_study.py:299`` (_fast_sample).
    """
    n = len(lst)
    if k >= n:
        return list(lst)
    if k == 0:
        return []
    selected: set[int] = set()
    result: list = []
    while len(result) < k:
        idx = rng.randrange(n)
        if idx not in selected:
            selected.add(idx)
            result.append(lst[idx])
    return result


# ── public API ───────────────────────────────────────────────────────────────


def day_paired_effective_n(
    returns: list[float] | np.ndarray,
    dates: list[str] | np.ndarray,
) -> int:
    """Day-clustered effective n = number of unique dates with non-NaN returns.

    Replaces pooled n (misleading when same-day picks are correlated).
    Per §44v2: 1000 picks across 14 days -> effective n ~ 14, not 1000.
    """
    r = np.asarray(returns, dtype=float)
    d = np.asarray(dates, dtype=object)
    mask = ~np.isnan(r)
    unique_dates = set(d[mask].tolist())
    return len(unique_dates)


def day_clustered_t_test(
    returns: list[float] | np.ndarray,
    dates: list[str] | np.ndarray,
) -> DayClusteredTResult | None:
    """One-sample day-clustered t-test (is the mean gap > 0 after cost).

    Clusters by date: for each trading day D, compute day_mean = mean(returns
    on D); then t = overall_day_mean / (day_std / sqrt(n_days)) where n_days =
    unique dates, day_std = std of day_means (ddof=1). p_one_sided = 1 -
    t_dist.cdf(t, df=n_days-1) (one-sided: mean > 0).

    Returns None if n_days < 2 (can't compute std with ddof=1).
    """
    r = np.asarray(returns, dtype=float)
    d = np.asarray(dates, dtype=object)
    mask = ~np.isnan(r)
    r_valid = r[mask]
    d_valid = d[mask]

    unique_dates = sorted(set(d_valid.tolist()))
    n_days = len(unique_dates)
    if n_days < 2:
        return None

    day_means: list[float] = []
    for date in unique_dates:
        day_returns = r_valid[d_valid == date]
        day_means.append(float(day_returns.mean()))

    overall_day_mean = float(np.mean(day_means))
    day_std = float(np.std(day_means, ddof=1))

    # Degenerate: all day-means identical (zero variance)
    if day_std == 0:
        if overall_day_mean > 0:
            return DayClusteredTResult(
                t_stat=float("inf"), p_one_sided=0.0,
                n_days=n_days, day_mean=overall_day_mean, day_std=day_std,
            )
        return DayClusteredTResult(
            t_stat=0.0 if overall_day_mean == 0 else float("-inf"),
            p_one_sided=1.0,
            n_days=n_days, day_mean=overall_day_mean, day_std=day_std,
        )

    se = day_std / (n_days ** 0.5)
    t_stat = overall_day_mean / se
    p_one_sided = 1.0 - float(sp_stats.t.cdf(t_stat, df=n_days - 1))

    return DayClusteredTResult(
        t_stat=round(t_stat, 6),
        p_one_sided=round(p_one_sided, 6),
        n_days=n_days,
        day_mean=round(overall_day_mean, 8),
        day_std=round(day_std, 8),
    )


def day_paired_lift(
    survivors_by_day: dict[str, list[float]],
    raw_by_day: dict[str, list[float]],
) -> DayPairedResult:
    """Non-pooled day-clustered winrate lift.

    Merged from ``first_board_layer_lift.py:138``. Per-day:
    survivor_winrate / raw_winrate, then average (NON-pooled) — prevents
    survivor clustering on up-days from inflating pooled lift (§44 proven
    this artifact: 4.686x pooled -> 1.723x day-clustered).

    Empty side on a day -> skip (not pairable).
    """
    day_lifts: list[dict] = []
    for date in sorted(set(survivors_by_day) | set(raw_by_day)):
        s = survivors_by_day.get(date, [])
        r = raw_by_day.get(date, [])
        if not s or not r:
            continue
        s_wr = _winrate(s)
        r_wr = _winrate(r)
        s_mean = statistics.mean(s)
        r_mean = statistics.mean(r)
        day_lifts.append({
            "surv_n": len(s),
            "raw_n": len(r),
            "winrate_lift": s_wr / r_wr if r_wr > 0 else None,
            "mean_lift": s_mean / r_mean if r_mean != 0 else None,
        })
    wr_lifts = [d["winrate_lift"] for d in day_lifts if d["winrate_lift"] is not None]
    m_lifts = [d["mean_lift"] for d in day_lifts if d["mean_lift"] is not None]
    return DayPairedResult(
        n_days=len(day_lifts),
        winrate_lift_avg=round(statistics.mean(wr_lifts), 4) if wr_lifts else None,
        mean_lift_avg=round(statistics.mean(m_lifts), 4) if m_lifts else None,
        surv_n_pooled=sum(d["surv_n"] for d in day_lifts),
        raw_n_pooled=sum(d["raw_n"] for d in day_lifts),
    )


def _generate_null_distribution(
    survivors_by_day: dict[str, list[float]],
    universe_by_day: dict[str, list[float]],
    n_perm: int,
    seed: int,
) -> list[float]:
    """Within-day survivor resampling null distribution.

    Merged from ``pead_event_study.py:316`` (permutation_null_fast) +
    ``platform_breakout_lift.py:40`` (day_cluster_permutation).

    Null model: for each day, sample len(survivors) from universe (within-day,
    without replacement), compute null winrate lift, average across days.
    Repeat n_perm times. Returns list of null lift values.
    """
    rng = random.Random(seed)
    nulls: list[float] = []
    event_days = sorted(survivors_by_day.keys())

    # Pre-compute universe winrates (pead optimization: compute once, not per perm)
    universe_wr_by_day: dict[str, float] = {}
    for date in event_days:
        raw_rets = universe_by_day.get(date, [])
        if raw_rets:
            universe_wr_by_day[date] = _winrate(raw_rets)

    for _ in range(n_perm):
        day_lifts: list[float] = []
        for date in event_days:
            surv_rets = survivors_by_day.get(date, [])
            raw_rets = universe_by_day.get(date, [])
            r_wr = universe_wr_by_day.get(date)
            if not surv_rets or not raw_rets or len(raw_rets) < len(surv_rets):
                continue
            if r_wr is None or r_wr <= 0:
                continue
            null_surv = _fast_sample(raw_rets, len(surv_rets), rng)
            null_wr = _winrate(null_surv)
            day_lifts.append(null_wr / r_wr)
        if day_lifts:
            nulls.append(statistics.mean(day_lifts))
    return nulls


def permutation_null_p95(
    survivors_by_day: dict[str, list[float]],
    universe_by_day: dict[str, list[float]],
    n_perm: int = _N_PERM_DEFAULT,
    seed: int = _PERM_SEED_DEFAULT,
) -> float | None:
    """Within-day survivor resampling null p95.

    Returns the 95th percentile of the null lift distribution, or None if
    insufficient data to generate any nulls.
    """
    nulls = _generate_null_distribution(survivors_by_day, universe_by_day, n_perm, seed)
    if not nulls:
        return None
    nulls_sorted = sorted(nulls)
    p95_idx = min(int(0.95 * len(nulls_sorted)), len(nulls_sorted) - 1)
    return round(nulls_sorted[p95_idx], 4)


def permutation_p_value(
    survivors_by_day: dict[str, list[float]],
    universe_by_day: dict[str, list[float]],
    observed_lift: float | None,
    n_perm: int = _N_PERM_DEFAULT,
    seed: int = _PERM_SEED_DEFAULT,
) -> float:
    """Within-day permutation p-value = P(null_lift >= observed).

    Returns 1.0 if observed is None or no nulls generated.
    """
    if observed_lift is None:
        return 1.0
    nulls = _generate_null_distribution(survivors_by_day, universe_by_day, n_perm, seed)
    if not nulls:
        return 1.0
    return round(sum(1 for x in nulls if x >= observed_lift) / len(nulls), 4)


def bonferroni_bh(
    p_values: list[float],
    n: int | None = None,
    method: Literal["BH", "bonferroni"] = "BH",
) -> list[float]:
    """Multiple-testing correction by-n.

    Bonferroni: adjusted_p = min(p * K, 1.0) — conservative, for mature results
    (days_robust >= 60). K capped at 8 per §44v2 (NEVER K=20, v1 over-correction).

    BH (Benjamini-Hochberg): step-up procedure — less conservative, for
    exploratory / small-n (days_robust < 60).

    Args:
        p_values: raw p-values
        n: number of comparisons (K). If None, uses len(p_values).
            For Bonferroni, capped at _MAX_BONFERRONI_K (8).
        method: ``"BH"`` or ``"bonferroni"``
    """
    if not p_values:
        return []

    k = n if n is not None else len(p_values)

    if method == "bonferroni":
        k = min(k, _MAX_BONFERRONI_K)
        if k <= 1:
            return [min(p, 1.0) for p in p_values]
        return [min(p * k, 1.0) for p in p_values]

    # BH (Benjamini-Hochberg) step-up
    m = len(p_values)
    if m <= 1:
        return [min(p, 1.0) for p in p_values]

    # Sort p-values with original indices
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adjusted = [0.0] * m

    # Step-up: from largest rank to smallest
    prev_adj = 1.0
    for rank in range(m, 0, -1):
        orig_idx, p = indexed[rank - 1]
        adj = min(p * m / rank, prev_adj, 1.0)
        adjusted[orig_idx] = adj
        prev_adj = adj

    return [round(a, 6) for a in adjusted]


def walk_forward_oos(
    survivors_by_day: dict[str, list[float]],
    raw_by_day: dict[str, list[float]],
    train: int = _WALK_TRAIN_DEFAULT,
    test: int = _WALK_TEST_DEFAULT,
    step: int = _WALK_STEP_DEFAULT,
) -> WalkForwardResult:
    """Rolling walk-forward OOS with graceful degradation.

    Merged from ``platform_breakout_lift.py:179`` + ``low_absorption_c3_lift.py:170``.
    Train window is NOT optimized (frozen/pre-registered thresholds). Test window
    computes day_paired_lift to check OOS stability.

    Graceful: if 0 windows can be formed (not enough days), returns
    ``status="insufficient_skipped"`` — never crashes on small n.
    """
    all_dates = sorted(set(survivors_by_day) | set(raw_by_day))
    if len(all_dates) < train + test:
        return WalkForwardResult(
            n_windows=0,
            test_lifts=(),
            test_n_per_window=(),
            mean_test_lift=None,
            status="insufficient_skipped",
        )

    test_lifts: list[float] = []
    test_ns: list[int] = []

    for start in range(0, max(0, len(all_dates) - train - test + 1), step):
        test_dates = set(all_dates[start + train : start + train + test])
        if not test_dates:
            continue
        test_surv = {d: r for d, r in survivors_by_day.items() if d in test_dates}
        test_raw = {d: r for d, r in raw_by_day.items() if d in test_dates}
        if not test_surv or not test_raw:
            continue
        wf = day_paired_lift(test_surv, test_raw)
        if wf.winrate_lift_avg is not None:
            test_lifts.append(wf.winrate_lift_avg)
            test_ns.append(wf.surv_n_pooled)

    if not test_lifts:
        return WalkForwardResult(
            n_windows=0,
            test_lifts=(),
            test_n_per_window=(),
            mean_test_lift=None,
            status="insufficient_skipped",
        )

    mean_lift = round(statistics.mean(test_lifts), 4)
    all_stable = all(l >= 1.0 for l in test_lifts)

    return WalkForwardResult(
        n_windows=len(test_lifts),
        test_lifts=tuple(test_lifts),
        test_n_per_window=tuple(test_ns),
        mean_test_lift=mean_lift,
        status="oos_stable" if all_stable else "oos_unstable",
    )
