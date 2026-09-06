"""S161 §44v2 verifier — design-agnostic statistical judge.

Given a return series + n_trials + optional trials_matrix -> Verdict. Pure and
immutable. Edge-type is explicit so a selection-falsified result is never
misread as "no edge" (spec-grill S161 honesty hole #24).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
import pandas as pd

from . import wiring  # noqa: TID252  (relative import within package)
from . import stats as stats_mod  # noqa: TID252  (R3 merged methodology)
from .stats import _EVENT_MATERIALITY_FLOOR  # noqa: TID252

_EdgeType = Literal["selection", "event", "population"]
_Status = Literal["robust_edge", "underpowered", "falsified", "not_validated", "exploratory"]
_DsrMethod = Literal["cross_trial_variance", "lenient_single_estimate", "N/A"]
_EventStatus = Literal["event_robust", "event_thin_positive", "event_falsified", "event_not_tested"]

#: R5 window sanity — maps edge_type to the window that should show advantage.
#: event (gap) → overnight_gap; selection → path (full path return);
#: population → overnight_gap (same as event, the population-level gap).
_WINDOW_FOR_EDGE: dict[str, str] = {
    "event": "overnight_gap",
    "selection": "path",
    "population": "overnight_gap",
}


@dataclass(frozen=True)
class EventMetrics:
    mean_return: float
    net_mean: Optional[float]
    win_rate: float
    t_stat_day_clustered: Optional[float]
    n_event: int
    base_rate: Optional[float]
    # ── day-clustered t-test details (populated when t-test runs) ──
    p_one_sided: Optional[float] = None
    n_days: Optional[int] = None
    day_mean: Optional[float] = None
    day_std: Optional[float] = None


@dataclass(frozen=True)
class Verdict:
    status: _Status
    edge_type: _EdgeType
    tradeable: bool
    selection_lift: Optional[float] = None
    event_metrics: Optional[EventMetrics] = None
    event_status: Optional[_EventStatus] = None
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None
    p_bonferroni: Optional[float] = None
    p_bh: Optional[float] = None
    dsr: Optional[float] = None
    dsr_method: _DsrMethod = "N/A"
    pbo: Optional[float] = None
    haircut: Optional[float] = None
    min_trl: Optional[float] = None
    days_robust: int = 0
    n: int = 0
    n_effective: Optional[int] = None
    p_permutation: Optional[float] = None
    walk_forward_status: Optional[str] = None
    walk_forward_mean_lift: Optional[float] = None
    n_comparisons: int = 1
    frozen_commit: Optional[str] = None
    updated_commit: Optional[str] = None
    updated_at: Optional[str] = None
    data_snapshot_id: Optional[str] = None
    note: str = ""


def _extract_trial_cols(
    trials_matrix: "pd.DataFrame | np.ndarray | None",
) -> Optional[list[np.ndarray]]:
    if trials_matrix is None:
        return None
    if isinstance(trials_matrix, pd.DataFrame):
        return [np.asarray(trials_matrix.iloc[:, i].values, dtype=float) for i in range(trials_matrix.shape[1])]
    arr = np.asarray(trials_matrix, dtype=float)
    if arr.ndim != 2:
        return None
    return [arr[:, i] for i in range(arr.shape[1])]


def verify(
    returns: "pd.Series | np.ndarray",
    n_trials: int,
    trials_matrix: "pd.DataFrame | np.ndarray | None" = None,
    periods_per_year: int = 252,
    window_sanity: Optional[dict] = None,
    edge_type: _EdgeType = "selection",
    tradeable: bool = True,
    frozen_commit: Optional[str] = None,
    data_snapshot_id: Optional[str] = None,
    # ── R3: §44v2 methodology merge ──────────────────────────────────────────
    dates: "list[str] | np.ndarray | None" = None,
    survivors_by_day: "dict[str, list[float]] | None" = None,
    universe_by_day: "dict[str, list[float]] | None" = None,
    n_comparisons: int = 1,
    n_perm: int = 500,
    perm_seed: int = 42,
    walk_train: int = 100,
    walk_test: int = 20,
    # ── R5: window sanity (S159 §5A, enforced per spec) ─────────────────────
    # window_sanity = {"overnight_gap": {mean,median,winrate,base_rate}, ...}
    # When provided, checks edge_type's window for advantage; no advantage →
    # force exploratory + skip heavy methodology. When None, note says skipped.
    # ── MEDIUM #7: materiality floor (extracted from magic 0.003) ──────────
    event_materiality_floor: float = _EVENT_MATERIALITY_FLOOR,
    round_trip_cost: float = 0.0,
) -> Verdict:
    """Statistical judge. Pure: same inputs -> same Verdict.

    R6 gate: days_robust<60 -> ``"underpowered"`` (never robust/falsified on
    small n). Edge-type explicit so selection-falsified != "no edge".

    R3 merge: when ``dates`` supplied, ``days_robust`` uses day-clustered
    effective n (non-pooled). When ``survivors_by_day`` + ``universe_by_day``
    supplied, computes selection_lift (day_paired non-pooled), permutation
    p-value, Bonferroni/BH correction, and walk-forward OOS.

    R5 window sanity: when ``window_sanity`` dict provided, validates
    per-window {mean, median, winrate, base_rate} for the edge_type's matching
    window. No advantage → force ``"exploratory"`` + skip heavy methodology
    (treats §44v1 wrong-window root cause). When None, note states skipped.

    MEDIUM #7: ``event_materiality_floor`` extracted from magic 0.003;
    ``round_trip_cost`` enables cost-relative floor = max(floor, cost*0.5).
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = int(r.size)

    trial_cols = _extract_trial_cols(trials_matrix)
    dsr, dsr_method = wiring.compute_dsr(r, n_trials, trial_cols)
    pbo = wiring.compute_pbo(trial_cols)

    # ── day-clustered effective n (replaces naive pooled n) ───────────────
    if dates is not None:
        n_effective = stats_mod.day_paired_effective_n(returns, dates)
        days_robust = n_effective
    elif survivors_by_day is not None:
        # derive from by-day data: unique days = effective n
        n_effective = len(survivors_by_day)
        days_robust = n_effective
    else:
        n_effective = None
        days_robust = n

    # ── R5: window sanity (S159 §5A, enforced per spec line 61) ───────────
    # When window_sanity provided, check edge_type's matching window for
    # advantage (mean > 0 AND winrate > base_rate). No advantage → skip heavy
    # methodology + force exploratory (treats §44v1 wrong-window root cause).
    r5_skip_heavy = False
    r5_note = ""
    if window_sanity is not None:
        edge_window = _WINDOW_FOR_EDGE.get(edge_type)
        if edge_window and edge_window in window_sanity:
            ws = window_sanity[edge_window]
            ws_mean = float(ws.get("mean", 0.0))
            ws_winrate = float(ws.get("winrate", 0.0))
            ws_base_rate = float(ws.get("base_rate", 0.5))
            has_advantage = ws_mean > 0 and ws_winrate > ws_base_rate
            if not has_advantage:
                r5_skip_heavy = True
                r5_note = (
                    f"R5 window sanity: no advantage in '{edge_window}' window "
                    f"(mean={ws_mean:.4f}, winrate={ws_winrate:.4f}, "
                    f"base_rate={ws_base_rate:.4f}) → exploratory, "
                    f"heavy methodology skipped"
                )
        # edge_window not in window_sanity → R5 can't check this edge_type,
        # proceed normally (honest: we tried but no data for this window)
    else:
        r5_note = "R5 window sanity: not provided, skipped"

    # ── selection lift + permutation + walk-forward ───────────────────────
    selection_lift: Optional[float] = None
    p_perm: Optional[float] = None
    p_bonf: Optional[float] = None
    p_bh: Optional[float] = None
    wf_status: Optional[str] = None
    wf_mean_lift: Optional[float] = None

    has_lift_data = survivors_by_day is not None and universe_by_day is not None
    if has_lift_data and not r5_skip_heavy:
        lift_res = stats_mod.day_paired_lift(survivors_by_day, universe_by_day)
        selection_lift = lift_res.winrate_lift_avg

        # permutation p-value (within-day survivor resampling)
        p_perm = stats_mod.permutation_p_value(
            survivors_by_day, universe_by_day, selection_lift, n_perm, perm_seed,
        )

        # multiple-testing correction: compute both for transparency
        # (by-n: BH for small n<60, Bonferroni for large n>=60, NEVER K=20)
        bonf_adj = stats_mod.bonferroni_bh([p_perm], n_comparisons, "bonferroni")
        bh_adj = stats_mod.bonferroni_bh([p_perm], n_comparisons, "BH")
        p_bonf = bonf_adj[0] if bonf_adj else None
        p_bh = bh_adj[0] if bh_adj else None

        # walk-forward OOS (graceful: "insufficient_skipped" if 0 windows)
        wf_res = stats_mod.walk_forward_oos(
            survivors_by_day, universe_by_day, walk_train, walk_test,
        )
        wf_status = wf_res.status
        wf_mean_lift = wf_res.mean_test_lift

    # ── event metrics + event_status (day-clustered one-sample t-test) ────
    event_metrics: Optional[EventMetrics] = None
    event_status: Optional[_EventStatus] = None
    if edge_type == "event" and n > 0 and not r5_skip_heavy:
        t_res = (
            # HIGH #8: pass original `returns` (with NaN), NOT stripped `r`.
            # day_clustered_t_test does its own NaN masking aligned to both
            # r and d (stats.py:148-150). Passing stripped `r` (line 114)
            # with original-length `dates` → mask length mismatch → IndexError.
            # mean_return/win_rate/n_event still use stripped `r` below
            # (NaN must NOT count toward mean/winrate/count).
            stats_mod.day_clustered_t_test(returns, dates) if dates is not None else None
        )
        mean_return = float(r.mean())
        win_rate = float((r > 0).mean())

        if t_res is not None:
            t_stat_val: Optional[float] = t_res.t_stat
            base_rate_val: Optional[float] = 0.0  # one-sample mean>0: null = 0
            net_mean_val: Optional[float] = t_res.day_mean  # day-clustered net mean

            if t_res.day_mean <= 0:
                event_status = "event_falsified"
            elif t_res.p_one_sided < 0.05:
                # Directionally confirmed (p < 0.05)
                # MEDIUM #7: materiality floor extracted from magic 0.003.
                # Cost-relative: floor = max(param, round_trip_cost * 0.5)
                # ensures day-mean must clear half the round-trip cost to be
                # "robust" (not just barely positive + statistically significant).
                effective_floor = max(event_materiality_floor, round_trip_cost * 0.5)
                if days_robust >= 60 and t_res.day_mean > effective_floor:
                    event_status = "event_robust"
                else:
                    event_status = "event_thin_positive"
            else:
                # p >= 0.05 but mean > 0: positive but not statistically significant
                event_status = "event_thin_positive"
        else:
            t_stat_val = None
            base_rate_val = None
            net_mean_val = None
            event_status = "event_not_tested"

        event_metrics = EventMetrics(
            mean_return=mean_return,
            net_mean=net_mean_val,
            win_rate=win_rate,
            t_stat_day_clustered=t_stat_val,
            n_event=n,
            base_rate=base_rate_val,
            p_one_sided=t_res.p_one_sided if t_res else None,
            n_days=t_res.n_days if t_res else None,
            day_mean=t_res.day_mean if t_res else None,
            day_std=t_res.day_std if t_res else None,
        )

    # ── status: R6 gate + edge-type-specific logic ──────────────────────
    if r5_skip_heavy:
        # R5 window sanity found no advantage → exploratory, skip heavy methodology
        status: _Status = "exploratory"
    elif edge_type == "event":
        # Event edges: status driven by event_status (not selection_lift)
        if days_robust < 60:
            status: _Status = "underpowered"
        elif event_status == "event_robust":
            status = "robust_edge"
        elif event_status == "event_falsified":
            status = "falsified"
        else:  # event_thin_positive, event_not_tested
            status = "exploratory"
    elif days_robust < 60:
        status = "underpowered"
    elif selection_lift is not None and selection_lift < 1.0:
        status = "falsified"
    elif selection_lift is not None and selection_lift >= 2.0:
        # days_robust >= 60 here -> Bonferroni is the decision p-value
        p_decision = p_bonf
        if p_decision is not None and p_decision < 0.05:
            status = "robust_edge"
        else:
            status = "not_validated"
    else:
        # 1 <= lift < 2, or lift None with enough days
        status = "exploratory"

    notes: list[str] = []
    if r5_note:
        notes.append(r5_note)
    if status == "underpowered" and days_robust < 60:
        notes.append(f"underpowered: days_robust={days_robust}<60 (R6 gate)")
    if wf_status == "insufficient_skipped":
        notes.append("walk-forward: insufficient data, skipped")

    return Verdict(
        status=status,
        edge_type=edge_type,
        tradeable=tradeable,
        selection_lift=selection_lift,
        event_metrics=event_metrics,
        event_status=event_status,
        ci_low=None,
        ci_high=None,
        p_bonferroni=p_bonf,
        p_bh=p_bh,
        dsr=dsr,
        dsr_method=dsr_method,
        pbo=pbo,
        days_robust=days_robust,
        n=n,
        n_effective=n_effective,
        p_permutation=p_perm,
        walk_forward_status=wf_status,
        walk_forward_mean_lift=wf_mean_lift,
        n_comparisons=n_comparisons,
        frozen_commit=frozen_commit,
        data_snapshot_id=data_snapshot_id,
        note="; ".join(notes) if notes else "",
    )
