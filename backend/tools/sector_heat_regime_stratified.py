#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sector_heat zt>=5 regime stratify probe (2026-09-18).

Question (from gap-window-rerun memory): the zt>=5 binary arm lift 1.819 was
the closest to 2.0 but the 313 zt_history days span a bear regime period
(2025-06 -> 2026-06). Is 1.82 a real signal, or a bear base-rate artifact
(cold base falls faster than hot in bear days -> lift rises without hot
getting absolutely better)?

Method: reuse sector_heat_gap_validation.py's binary framing (zt>=5 hot /
0-zt cold / exclude D-ZT) but accumulate hm/hn/cm/cn PER regime (bull/bear/
range) using compute_regime_labels() from gap_regime_stratified.py (Shanghai
Composite MA20 + slope, same as evaluation.py:87 regime_caps).

Per-regime lift = hot_rate_regime / cold_rate_regime. Each regime has its
OWN base rate (cold_rate), so this directly tests whether hot beats cold
WITHIN each regime — isolating the bear-artifact confound.

§44 v2 rules applied:
- Pre-window sanity: sector_heat's main window is next-day-ZT binary (not
  gap). This is the right window for this signal.
- Heavy methodology only on adequate n: <60 day-pairs in a regime ->
  "exploratory/underpowered", NOT "劣于随机".
- Bonferroni by n: K=2 (bull, bear) mild correction; range reported but
  not a primary comparison.

Reuses (no modification to existing harnesses):
  - load_industry_map, load_zt_pools from sector_heat_gap_validation
  - compute_regime_labels from gap_regime_stratified
  - _wilson CI helper
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tools.sector_heat_gap_validation import (  # noqa: E402
    _wilson,
    load_industry_map,
    load_zt_pools,
)
from tools.gap_regime_stratified import compute_regime_labels  # noqa: E402

REGIMES = ("bull", "bear", "range")
# zt>=5 is the probe target (1.819 in memory); zt>=3 kept for comparison.
DEFS = [("zt>=3", 3), ("zt>=5", 5)]


def _verdict(lift: float) -> str:
    if lift >= 2.0:
        return ">=2x validated"
    if lift >= 1.0:
        return "<2x unvalidated"
    return "falsified(劣于随机)"


def binary_framing_stratified(
    zt: dict[str, set[str]],
    industry: dict[str, str],
    calendar: list[str],
    cal_idx: dict[str, int],
    regime_map: dict[str, str],
) -> None:
    """Binary next-day-new-ZT framing, stratified by D-day regime.

    For each day-pair (D -> D+1) where both have ZT pools:
      - tag D with regime (bull/bear/range)
      - zt_by_ind = Counter of D's ZT stocks by industry
      - d_zt = set of D's ZT codes (excluded from members = new-ZT framing)
      - hot_inds = {ind: zt_count(D) >= thresh}
      - all_inds = set of industries with any ZT on D
      - hot_mem / cold_mem = members of hot / 0-ZT industries, excl d_zt
      - d1_zt = ZT pool on D+1
      - accumulate hm/hn/cm/cn per regime
    """
    zt_dates = sorted(d for d in zt if d in cal_idx)
    daily = []
    n_untagged = 0
    for d in zt_dates:
        ni = cal_idx[d] + 1
        if ni >= len(calendar):
            continue
        d1 = calendar[ni]
        if d1 not in zt:
            continue  # binary framing needs D+1 ZT pool
        tag = regime_map.get(d)
        if tag is None:
            n_untagged += 1
            continue
        zt_by_ind: dict[str, int] = {}
        d_zt: set[str] = set()
        for code in zt[d]:
            ind = industry.get(code)
            if ind:
                zt_by_ind[ind] = zt_by_ind.get(ind, 0) + 1
                d_zt.add(code)
        daily.append((d, tag, zt_by_ind, d_zt, zt[d1]))

    print(f"\n=== sector_heat BINARY framing, regime-stratified "
          f"(zt_history {len(daily)} tagged day-pairs) ===")
    if n_untagged:
        print(f"[regime] {n_untagged} day-pairs had no regime tag (skipped)")

    # regime distribution of signal days
    reg_counts = {r: 0 for r in REGIMES}
    for _, tag, _, _, _ in daily:
        reg_counts[tag] = reg_counts.get(tag, 0) + 1
    print("regime distribution (signal days D):")
    for r in REGIMES:
        c = reg_counts.get(r, 0)
        print(f"  {r:5s}: {c} day-pairs"
              f"{' (UNDERPOWERED <60)' if 0 < c < 60 else ''}")

    for name, thresh in DEFS:
        # per-regime accumulators
        acc = {r: {"hm": 0, "hn": 0, "cm": 0, "cn": 0} for r in REGIMES}
        for _, tag, zt_by_ind, d_zt, d1_zt in daily:
            hot_inds = {ind for ind, c in zt_by_ind.items() if c >= thresh}
            all_inds = set(zt_by_ind.keys())
            hot_mem = [c for c, ind in industry.items()
                       if ind in hot_inds and c not in d_zt]
            cold_mem = [c for c, ind in industry.items()
                        if ind not in all_inds and c not in d_zt]
            if not hot_mem or not cold_mem:
                continue
            a = acc[tag]
            a["hm"] += len(hot_mem)
            a["cm"] += len(cold_mem)
            a["hn"] += sum(1 for c in hot_mem if c in d1_zt)
            a["cn"] += sum(1 for c in cold_mem if c in d1_zt)

        print(f"\n--- {name} hot / 0-zt cold, stratified ---")
        # pooled (all regimes) sanity check vs memory's 1.819
        phm = sum(acc[r]["hm"] for r in REGIMES)
        phn = sum(acc[r]["hn"] for r in REGIMES)
        pcm = sum(acc[r]["cm"] for r in REGIMES)
        pcn = sum(acc[r]["cn"] for r in REGIMES)
        phr = phn / phm if phm else 0.0
        pcr = pcn / pcm if pcm else 0.0
        plift = phr / pcr if pcr else 0.0
        print(f"  POOLED (all regimes): hot {phn}/{phm}={phr*100:.3f}%  "
              f"cold {pcn}/{pcm}={pcr*100:.3f}%  lift={plift:.3f}x "
              f"-> {_verdict(plift)}  [sanity vs memory 1.819]")

        for r in REGIMES:
            a = acc[r]
            hm, hn = a["hm"], a["hn"]
            cm, cn = a["cm"], a["cn"]
            n_days = reg_counts.get(r, 0)
            if hm == 0 or cm == 0:
                print(f"  {r:5s}: no data (hot_mem or cold_mem empty)")
                continue
            hr = hn / hm
            cr = cn / cm
            lift = hr / cr if cr else 0.0
            hlo, hhi = _wilson(hn, hm)
            clo, chi = _wilson(cn, cm)
            sig = "CI不重叠" if hlo > chi else "CI重叠"
            under = " UNDERPOWERED(<60d, exploratory)" if n_days < 60 else ""
            print(f"  {r:5s}: n_days={n_days}  "
                  f"hot {hn}/{hm}={hr*100:.3f}%[{hlo*100:.2f},{hhi*100:.2f}]  "
                  f"cold {cn}/{cm}={cr*100:.3f}%[{clo*100:.2f},{chi*100:.2f}]  "
                  f"lift={lift:.3f}x -> {_verdict(lift)}({sig}){under}")


def main() -> None:
    print("sector_heat regime stratify probe (zt>=5 binary arm)")
    industry = load_industry_map()
    zt = load_zt_pools()
    regime_map = compute_regime_labels()
    if not regime_map:
        print("[FATAL] no regime labels, aborting")
        return

    # build calendar from zt dates is NOT enough — we need the global trading
    # calendar to find D+1. Reuse the kline-derived calendar like the gap
    # variant does. But to avoid loading 435MB kline just for the calendar,
    # build a minimal calendar from zt_history dates union regime cache dates.
    zt_dates = set(zt.keys())
    regime_dates = set(regime_map.keys())
    calendar = sorted(zt_dates | regime_dates)
    cal_idx = {d: i for i, d in enumerate(calendar)}
    print(f"industry map: {len(industry)} codes | zt pools: {len(zt)} days | "
          f"regime labels: {len(regime_map)} dates | "
          f"calendar: {len(calendar)} trading days")

    binary_framing_stratified(zt, industry, calendar, cal_idx, regime_map)

    print("\n=== VERDICT LOGIC ===")
    print("bull also >2.0  -> REAL signal (un-freeze condition 3: 2nd edge)")
    print("only bear >2.0  -> bear artifact (archive, same as late_lock)")
    print("both <2.0       -> unvalidated, keep weight_multiplier=0.5, R3 monitor")
    print("\ncaveat: <60 day-pairs in a regime = underpowered (§44 v2). "
          "Bonferroni K=2 (bull,bear) mild; range is secondary.")


if __name__ == "__main__":
    main()
