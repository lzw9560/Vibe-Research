#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S205 T5: 一字竞价 regime-stratified §44 harness.

DRY 复用 G5 e664353 范式：gap_regime_stratified + wire_verdict。
auction_signal BLOCKER（无免费源）→ harness picks 空 → underpowered。
picks by D-day regime -> day-paired event lift -> wire_verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.gap_regime_stratified import (  # noqa: E402
    compute_regime_labels,
    regime_stats,
    stratify_gap,
)
from tools._s44_wire import wire_verdict  # noqa: E402

N_COMPARISONS_PER_FAMILY: int = 4
FROZEN_COMMIT: str = "synthetic"
REGIME_TAGS: tuple[str, ...] = ("bull", "bear", "range")
SCRIPT_PATH: str = "tools/regime_stratified_dixi_longtou_lift.py"
STRATEGY_NAME: str = "dixi_longtou"


def run(
    *,
    returns: list[float],
    dates: list[str],
    regime_map: dict[str, str] | None = None,
    universe_by_day: dict[str, list[float]] | None = None,
    frozen_commit: str = FROZEN_COMMIT,
    round_trip_cost: float = 0.0,
) -> dict[str, dict]:
    if regime_map is None:
        regime_map = compute_regime_labels()
    if not regime_map:
        print("[FATAL] no regime labels, aborting")
        return {}

    by_regime, by_regime_day, n_untagged = stratify_gap(returns, dates, regime_map)
    if n_untagged:
        print(f"[regime] WARNING: {n_untagged} trades have no regime tag")

    results: dict[str, dict] = {}
    for tag in REGIME_TAGS:
        rets = by_regime[tag]
        by_day = by_regime_day[tag]
        stats = regime_stats(rets, by_day)

        if len(rets) < 2:
            results[tag] = {**stats, "verdict_status": "skipped",
                            "verdict_note": f"n={len(rets)} < 2"}
            continue

        regime_dates: list[str] = []
        for d in sorted(by_day.keys()):
            regime_dates.extend([d] * len(by_day[d]))

        universe_by_regime: dict[str, list[float]] | None = None
        if universe_by_day is not None:
            universe_by_regime = {
                d: universe_by_day[d] for d in universe_by_day
                if regime_map.get(d) == tag
            }
        v = wire_verdict(
            line_id=f"{STRATEGY_NAME}_regime:{tag}",
            returns=rets, edge_type="event",
            frozen_commit=frozen_commit, dates=regime_dates,
            universe_by_day=universe_by_regime,
            n_comparisons=N_COMPARISONS_PER_FAMILY,
            round_trip_cost=round_trip_cost, script=SCRIPT_PATH,
            params={"regime": tag, "strategy": STRATEGY_NAME},
        )
        results[tag] = {**stats, "verdict_status": v.status, "verdict_note": v.note}
    return results


def main() -> int:
    print(f"[{STRATEGY_NAME}] regime-stratified harness -- BLOCKER: auction_signal 无免费源")
    return 0


if __name__ == "__main__":
    main()
