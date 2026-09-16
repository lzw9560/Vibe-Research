#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Consecutive-relay (lbc>=2 / zt_count_250d>=2) x MA20 3-way regime stratified S44 harness.

Question: is consecutive-relay (接力) overnight return a regime artifact?
Splits picks by MA20 3-way regime (bull/bear/range), then computes
per-regime S44v2 event verdict via wire_verdict.

Reuses (DRY -- no reimplementation):
  - gap_regime_stratified.compute_regime_labels (MA20 3-way: bull/bear/range)
  - gap_regime_stratified.stratify_gap (split returns by regime tag)
  - gap_regime_stratified.regime_stats (per-regime stats: n/winrate/t-stat)
  - _s44_wire.wire_verdict (n_comparisons=4 per family, K=12 split 3 family
    each K=4<=8, decision #9)

K-split: 3 regime families x K=4 = total K=12.  Each family K=4 <= 8
(decision #9).  Small-n regime -> R8 gate inside wire_verdict marks
underpowered, not extrapolated.

picks by D-day regime -> day-paired event lift -> wire_verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Direct execution: add backend/ to sys.path (tools. package + imports)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.gap_regime_stratified import (  # noqa: E402
    compute_regime_labels,
    regime_stats,
    stratify_gap,
)
from tools._s44_wire import wire_verdict  # noqa: E402

# K=4 per regime family (3 families x K=4 = total K=12; each K=4 <= 8, decision #9)
N_COMPARISONS_PER_FAMILY: int = 4

# Synthetic placeholder; real runs pass actual frozen commit
FROZEN_COMMIT: str = "synthetic"

REGIME_TAGS: tuple[str, ...] = ("bull", "bear", "range")

SCRIPT_PATH: str = "tools/regime_stratified_consecutive_relay_lift.py"

STRATEGY_NAME: str = "consecutive_relay"


def run(
    *,
    returns: list[float],
    dates: list[str],
    regime_map: dict[str, str] | None = None,
    universe_by_day: dict[str, list[float]] | None = None,
    frozen_commit: str = FROZEN_COMMIT,
    round_trip_cost: float = 0.0,
) -> dict[str, dict]:
    """Run per-regime S44v2 event verdict for consecutive-relay.

    Stratifies returns by MA20 3-way regime (bull/bear/range), computes
    per-regime stats, and wires verdict via _s44_wire.wire_verdict.

    If regime_map is None, computes it via compute_regime_labels() from
    gap_regime_stratified (requires index_ma20_regime.json or baostock).
    For testing, pass a synthetic regime_map.

    Returns ``{regime: {stats..., verdict_status, verdict_note}}``.
    Small-n regimes (n<2) are skipped; underpowered verdicts are produced
    but not extrapolated (R8 gate inside wire_verdict: n<200 or
    days_robust<60 -> status="underpowered").
    """
    if regime_map is None:
        regime_map = compute_regime_labels()
    if not regime_map:
        print("[FATAL] no regime labels, aborting")
        return {}

    by_regime, by_regime_day, n_untagged = stratify_gap(
        returns, dates, regime_map,
    )
    if n_untagged:
        print(f"[regime] WARNING: {n_untagged} trades have no regime tag")

    results: dict[str, dict] = {}
    for tag in REGIME_TAGS:
        rets = by_regime[tag]
        by_day = by_regime_day[tag]
        stats = regime_stats(rets, by_day)

        if len(rets) < 2:
            results[tag] = {
                **stats,
                "verdict_status": "skipped",
                "verdict_note": f"n={len(rets)} < 2, insufficient for verdict",
            }
            print(f"  {STRATEGY_NAME}_regime:{tag} -> SKIPS (n={len(rets)} < 2)")
            continue

        # Build per-regime dates list (aligned with returns order)
        regime_dates: list[str] = []
        for d in sorted(by_day.keys()):
            regime_dates.extend([d] * len(by_day[d]))

        # S210 T2: per regime filter universe（同 regime days）让 drift fix 控 regime-specific drift
        universe_by_regime: dict[str, list[float]] | None = None
        if universe_by_day is not None:
            universe_by_regime = {
                d: universe_by_day[d] for d in universe_by_day
                if regime_map.get(d) == tag
            }
        v = wire_verdict(
            line_id=f"{STRATEGY_NAME}_regime:{tag}",
            returns=rets,
            edge_type="event",
            frozen_commit=frozen_commit,
            dates=regime_dates,
            universe_by_day=universe_by_regime,
            n_comparisons=N_COMPARISONS_PER_FAMILY,
            round_trip_cost=round_trip_cost,
            script=SCRIPT_PATH,
            params={
                "regime": tag,
                "strategy": STRATEGY_NAME,
                "n_comparisons": N_COMPARISONS_PER_FAMILY,
            },
        )
        results[tag] = {
            **stats,
            "verdict_status": v.status,
            "verdict_note": v.note,
        }

    return results


def main() -> int:
    """Real-data entry point (requires consecutive-relay picks + regime cache).

    For programmatic usage (synthetic or pre-loaded data), call run()
    directly with returns / dates / regime_map.
    """
    print(f"[{STRATEGY_NAME}] regime-stratified harness -- real data mode")
    print("  Pass returns/dates/regime_map to run() for programmatic usage.")
    print("  Real data loading delegates to existing tools (gap_regime_stratified).")
    return 0


if __name__ == "__main__":
    main()
