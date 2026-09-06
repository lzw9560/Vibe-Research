#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""§44v2 gap run on 60-day baostock-derived 首板 universe (TEMP, uncommitted).

Culmination of A (baostock backfill) + B (S161 verifier). Answers the user's
north-star: is the overnight gap a real edge?

Inputs:
  - .vibe-research/first_board_universe_baostock_60d.json  (A's output, 4076 首板)
  - .vibe-research/baostock_kline_cache.json  (D+1 opens, 160MB)
  - backend/s44_verifier/  (B's verifier)

Cost: COST=0.0070 (0.70% round-trip) per task spec.
NOTE: the 14-day baseline.json used cost_pct=0.4 (0.40%, percent units); the
60-day run uses a MORE conservative 0.70% per the task instruction. The
comparison is therefore not cost-matched (disclosed in report).
"""
from __future__ import annotations

import bisect
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from s44_verifier.verifier import verify  # noqa: E402
from s44_verifier.recorder import compute_composite_snapshot_id  # noqa: E402

VR = ROOT / ".vibe-research"
UNIVERSE = VR / "first_board_universe_baostock_60d.json"
KLINE = VR / "baostock_kline_cache.json"
GENE_DB = VR / "gene_scores.db"

COST = 0.0070  # 0.70% round-trip (task spec; baseline.json used 0.40%)
FROZEN_COMMIT = "b4e7446"
# data_snapshot_id computed at runtime (HIGH #2: composite universe+cache hash)


def load_universe() -> list[dict]:
    with open(UNIVERSE, encoding="utf-8") as f:
        data = json.load(f)
    print(f"[universe] meta window_days={data['meta']['window_days']} "
          f"window={data['meta']['window']}")
    print(f"[universe] totals first_board={data['totals']['first_board']} "
          f"zt={data['totals']['zt']} lianban={data['totals']['lianban']}")
    fbs = data["first_boards"]
    print(f"[universe] flat records={len(fbs)}")
    return fbs


def build_kline_index():
    """Load kline cache once; build per-code date->index map for O(1) D+1 lookup.

    Returns (code -> list[bars], code -> {date_str: idx}, trading_calendar).
    """
    print("[kline] loading 160MB cache ...")
    with open(KLINE, encoding="utf-8") as f:
        cache = json.load(f)
    print(f"[kline] codes={len(cache)}")
    # global max date across all codes
    max_date = ""
    all_dates: set[str] = set()
    for bars in cache.values():
        if bars:
            d = bars[-1]["date"]
            if d > max_date:
                max_date = d
            for b in bars:
                all_dates.add(b["date"])
    print(f"[kline] global max date={max_date}")
    trading_calendar = sorted(all_dates)
    print(f"[calendar] {len(trading_calendar)} trading dates")
    # build date->idx maps lazily per code on demand (5226 codes * avg ~120 bars
    # = ~600k entries, fine). Build all upfront for speed.
    idx_maps: dict[str, dict[str, int]] = {}
    for code, bars in cache.items():
        idx_maps[code] = {b["date"]: i for i, b in enumerate(bars)}
    return cache, idx_maps, trading_calendar


def calendar_next(calendar: list[str], date_str: str) -> str | None:
    """Next trading day after date_str in the calendar. None if date is last.

    MEDIUM #3 date adjacency: ensures bars[i+1] is the calendar-next of D
    (not D+2 or later, which means D+1 was suspended).
    """
    idx = bisect.bisect_left(calendar, date_str)
    if idx < len(calendar) and calendar[idx] == date_str:
        return calendar[idx + 1] if idx + 1 < len(calendar) else None
    if idx < len(calendar):
        return calendar[idx]
    return None


def compute_gap_series(fbs, cache, idx_maps, calendar):
    """For each (code, D, close) -> gap_return = open(D+1)/close - 1 - COST.

    Fixes applied:
    - MEDIUM #3 date adjacency: bars[i+1]['date'] must == calendar_next(D)
    - LOW #9 volume guard: zero-volume bars are suspended (fake returns)
    - HIGH #2 adj-epoch check: cache close at D must match universe close_d

    Returns (returns, dates, n_unbuyable, n_no_code, n_bad_close, n_suspended, n_adj_mismatch).
    """
    returns: list[float] = []
    dates: list[str] = []
    n_unbuyable = 0
    n_no_code = 0
    n_bad_close = 0
    n_suspended = 0
    n_adj_mismatch = 0
    for r in fbs:
        code = r["code"]
        d = r["date"]
        close_d = r.get("close")
        if close_d is None or close_d <= 0:
            n_bad_close += 1
            continue
        bars = cache.get(code)
        if bars is None:
            n_no_code += 1
            continue
        dmap = idx_maps[code]
        i = dmap.get(d)
        if i is None:
            # D bar missing in kline for this code (use universe close as fallback?
            # close(D) from universe is authoritative limit_price; but we need D+1 open
            # which requires the kline bar at D to find the NEXT bar). Try date-sorted
            # neighbor lookup: find first bar with date > d.
            nxt = None
            # bars sorted ascending; bisect
            lo, hi = 0, len(bars)
            while lo < hi:
                mid = (lo + hi) // 2
                if bars[mid]["date"] < d:
                    lo = mid + 1
                else:
                    hi = mid
            # lo = first index with date >= d
            if lo < len(bars) and bars[lo]["date"] > d:
                nxt = bars[lo]
            if nxt is None:
                n_unbuyable += 1
                continue
            # date adjacency: nxt must be the calendar-next trading day (D+1)
            expected_next = calendar_next(calendar, d)
            if expected_next is not None and nxt["date"] != expected_next:
                n_suspended += 1
                continue
            open_next = nxt["open"]
            # volume guard (LOW #9)
            if nxt.get("volume", 0) <= 0:
                n_unbuyable += 1
                continue
        else:
            # adjustment-epoch consistency: cache close at D must match universe close_d
            cache_close_d = bars[i].get("close")
            if cache_close_d is not None and abs(cache_close_d - close_d) > 0.01:
                n_adj_mismatch += 1
                continue
            if i + 1 >= len(bars):
                n_unbuyable += 1
                continue
            # date adjacency: bars[i+1] must be the calendar-next trading day (D+1)
            expected_next = calendar_next(calendar, d)
            if expected_next is not None and bars[i + 1]["date"] != expected_next:
                n_suspended += 1
                continue
            open_next = bars[i + 1]["open"]
            # volume guard (LOW #9)
            if bars[i + 1].get("volume", 0) <= 0:
                n_unbuyable += 1
                continue
        if open_next is None or open_next <= 0:
            n_unbuyable += 1
            continue
        gap = open_next / close_d - 1.0 - COST
        returns.append(gap)
        dates.append(d)
    return returns, dates, n_unbuyable, n_no_code, n_bad_close, n_suspended, n_adj_mismatch


def event_verdict(returns, dates, snap_id):
    arr = np.asarray(returns, dtype=float)
    v = verify(
        returns=arr,
        n_trials=1,
        edge_type="event",
        dates=dates,
        frozen_commit=FROZEN_COMMIT,
        data_snapshot_id=snap_id,
        round_trip_cost=COST,
    )
    return v


def selection_verdict(fbs, cache, idx_maps, returns, dates, calendar, snap_id):
    """Attempt selection verdict: can gene_score select which 首板 gaps bigger?

    Join: for 首板 (code, D) with gap_return, gene_score available before D+1 open
    lives in gene_scores.date == (D+1 next trading day), code == code (gene_scores
    for target day T are written T-1=D after close using D's 首板 — matches).

    survivors_by_day[D] = top-quintile gap_returns by gene_score that day.
    universe_by_day[D] = all gap_returns that day.
    """
    # build (code,D)->gap_return and (code,D)->next_trading_date map
    gap_map: dict[tuple[str, str], float] = {}
    next_td_map: dict[tuple[str, str], str] = {}
    for r in fbs:
        code = r["code"]
        d = r["date"]
        close_d = r.get("close")
        if close_d is None or close_d <= 0:
            continue
        bars = cache.get(code)
        if bars is None:
            continue
        dmap = idx_maps[code]
        i = dmap.get(d)
        if i is None:
            # bisect fallback
            lo, hi = 0, len(bars)
            while lo < hi:
                mid = (lo + hi) // 2
                if bars[mid]["date"] < d:
                    lo = mid + 1
                else:
                    hi = mid
            if not (lo < len(bars) and bars[lo]["date"] > d):
                continue
            # date adjacency (MEDIUM #3)
            expected_next = calendar_next(calendar, d)
            if expected_next is not None and bars[lo]["date"] != expected_next:
                continue
            # volume guard (LOW #9)
            if bars[lo].get("volume", 0) <= 0:
                continue
            open_next = bars[lo]["open"]
            next_td = bars[lo]["date"]
        else:
            if i + 1 >= len(bars):
                continue
            # date adjacency (MEDIUM #3)
            expected_next = calendar_next(calendar, d)
            if expected_next is not None and bars[i + 1]["date"] != expected_next:
                continue
            # volume guard (LOW #9)
            if bars[i + 1].get("volume", 0) <= 0:
                continue
            open_next = bars[i + 1]["open"]
            next_td = bars[i + 1]["date"]
        if open_next is None or open_next <= 0:
            continue
        gap = open_next / close_d - 1.0 - COST
        gap_map[(code, d)] = gap
        next_td_map[(code, d)] = next_td

    # load gene_scores (code, date)->total_score
    con = sqlite3.connect(str(GENE_DB))
    cur = con.cursor()
    # only need dates that are next-trading-days present
    needed_dates = set(next_td_map.values())
    if not needed_dates:
        con.close()
        return None, {}, {}
    placeholders = ",".join("?" for _ in needed_dates)
    rows = cur.execute(
        f"SELECT date, code, total_score FROM gene_scores WHERE date IN ({placeholders})",
        sorted(needed_dates),
    ).fetchall()
    con.close()
    score_lookup: dict[tuple[str, str], float] = {}
    n_score_rows = 0
    for date, code, ts in rows:
        if ts is None:
            continue
        score_lookup[(code, date)] = float(ts)
        n_score_rows += 1

    # join: for each (code, D), gene_score = score_lookup[(code, next_td)]
    by_day: dict[str, list[tuple[float, float]]] = {}  # D -> [(gap, score)]
    n_joined = 0
    n_no_score = 0
    for (code, d), gap in gap_map.items():
        ntd = next_td_map[(code, d)]
        sc = score_lookup.get((code, ntd))
        if sc is None:
            n_no_score += 1
            continue
        by_day.setdefault(d, []).append((gap, sc))
        n_joined += 1

    coverage = n_joined / len(gap_map) if gap_map else 0.0
    print(f"[selection] gap_map={len(gap_map)} score_rows_matched={n_score_rows} "
          f"joined={n_joined} no_score={n_no_score} coverage={coverage:.2%}")

    if coverage < 0.40:
        print("[selection] coverage < 40% -> STUB (not run)")
        return None, {}, {}

    # build survivors (top-quintile by score) / universe per day
    survivors_by_day: dict[str, list[float]] = {}
    universe_by_day: dict[str, list[float]] = {}
    for d, pairs in by_day.items():
        gaps = [p[0] for p in pairs]
        universe_by_day[d] = gaps
        n = len(pairs)
        if n < 5:
            # too few for a quintile; no survivors this day
            continue
        k = max(1, n // 5)
        top = sorted(pairs, key=lambda x: x[1], reverse=True)[:k]
        survivors_by_day[d] = [p[0] for p in top]

    if not survivors_by_day:
        print("[selection] no day with >=5 picks -> STUB")
        return None, universe_by_day, {}

    arr_all = np.asarray(
        [g for gs in universe_by_day.values() for g in gs], dtype=float
    )
    v = verify(
        returns=arr_all,
        n_trials=1,
        edge_type="selection",
        survivors_by_day=survivors_by_day,
        universe_by_day=universe_by_day,
        n_comparisons=1,
        frozen_commit=FROZEN_COMMIT,
        data_snapshot_id=snap_id,
    )
    return v, survivors_by_day, universe_by_day


def main():
    fbs = load_universe()
    cache, idx_maps, calendar = build_kline_index()

    # composite data_snapshot_id (HIGH #2: pins BOTH universe + kline cache)
    snap_id = compute_composite_snapshot_id(UNIVERSE, KLINE)
    print(f"[snapshot] composite data_snapshot_id = {snap_id}")

    returns, dates, n_unbuyable, n_no_code, n_bad_close, n_suspended, n_adj_mm = compute_gap_series(
        fbs, cache, idx_maps, calendar
    )
    arr = np.asarray(returns, dtype=float)
    n = arr.size
    mean_pct = float(arr.mean()) * 100 if n else 0.0
    net_mean_pct = mean_pct  # already cost-subtracted
    gross_mean_pct = float((arr + COST).mean()) * 100 if n else 0.0
    win_rate = float((arr > 0).mean()) if n else 0.0
    gross_win = float(((arr + COST) > 0).mean()) if n else 0.0
    median_pct = float(np.median(arr)) * 100 if n else 0.0
    std_pct = float(arr.std(ddof=1)) * 100 if n > 1 else 0.0
    unique_dates = sorted(set(dates))
    days_robust = len(unique_dates)

    print("\n=== GAP SERIES STATS ===")
    print(f"n picks (valid gap)   = {n}")
    print(f"n unbuyable (no D+1)  = {n_unbuyable}")
    print(f"n suspended (D+1 skip) = {n_suspended}")
    print(f"n adj_mismatch         = {n_adj_mm}")
    print(f"n no_code in kline     = {n_no_code}")
    print(f"n bad close            = {n_bad_close}")
    print(f"unique dates (days_robust raw) = {days_robust}")
    print(f"date range            = {unique_dates[0] if unique_dates else '-'}"
          f" -> {unique_dates[-1] if unique_dates else '-'}")
    print(f"gross mean %          = {gross_mean_pct:.4f}")
    print(f"net mean % (after {COST*100:.2f}% cost) = {net_mean_pct:.4f}")
    print(f"median net %         = {median_pct:.4f}")
    print(f"std %               = {std_pct:.4f}")
    print(f"net win_rate (>0)    = {win_rate:.4f}")
    print(f"gross win_rate       = {gross_win:.4f}")
    # naive t-stat (pooled, for reference vs 14-day baseline t=10.65)
    if n > 1 and std_pct > 0:
        t_naive = mean_pct / (std_pct / (n ** 0.5))
        print(f"naive pooled t-stat  = {t_naive:.4f}  (ref 14d baseline t=10.6549)")

    print("\n=== EVENT VERDICT (primary: is gap a real edge?) ===")
    ev = event_verdict(returns, dates, snap_id)
    print(f"status               = {ev.status}")
    print(f"edge_type            = {ev.edge_type}")
    print(f"tradeable            = {ev.tradeable}")
    print(f"days_robust          = {ev.days_robust}")
    print(f"n                    = {ev.n}")
    print(f"n_effective          = {ev.n_effective}")
    if ev.event_metrics:
        em = ev.event_metrics
        print(f"event_metrics:")
        print(f"  mean_return        = {em.mean_return:.6f} ({em.mean_return*100:.4f}%)")
        print(f"  net_mean           = {em.net_mean}")
        print(f"  win_rate           = {em.win_rate:.4f}")
        print(f"  t_stat_day_clust   = {em.t_stat_day_clustered}")
        print(f"  n_event            = {em.n_event}")
        print(f"  base_rate          = {em.base_rate}")
    print(f"event_status         = {ev.event_status}")
    print(f"dsr                  = {ev.dsr}")
    print(f"dsr_method           = {ev.dsr_method}")
    print(f"pbo                  = {ev.pbo}  (single-strategy N/A)")
    print(f"selection_lift       = {ev.selection_lift}")
    print(f"p_bonferroni         = {ev.p_bonferroni}")
    print(f"p_permutation        = {ev.p_permutation}")
    print(f"walk_forward_status  = {ev.walk_forward_status}")
    print(f"n_comparisons        = {ev.n_comparisons}")
    print(f"frozen_commit        = {ev.frozen_commit}")
    print(f"data_snapshot_id     = {ev.data_snapshot_id}")
    print(f"note                 = {ev.note!r}")

    # R6 gate assessment
    print("\n=== R6 GATE ===")
    if ev.days_robust >= 60:
        print(f"days_robust={ev.days_robust} >= 60 -> CROSSES R6 (not underpowered)")
        print(f"status='{ev.status}' is authoritative (NOT 'underpowered')")
    else:
        print(f"days_robust={ev.days_robust} < 60 -> UNDERPOWERED (R6 gate)")
        print(f"missing {60 - ev.days_robust} day(s) to cross R6")

    # honest label
    print("\n=== HONEST LABEL ===")
    if ev.event_metrics and ev.event_metrics.mean_return > 0:
        if ev.event_status == "event_robust":
            print(f"event_robust: p<0.05 + days>=60 + day_mean>{ev.event_metrics.day_mean} -> robust_edge")
        elif ev.event_status == "event_thin_positive":
            print(f"event_thin_positive: positive but NOT fully confirmed (p={ev.event_metrics.p_one_sided})")
        else:
            print(f"event_status={ev.event_status}")
    label = ev.status
    if ev.event_metrics and ev.event_metrics.mean_return > 0 and ev.event_status == "event_not_tested":
        label = f"{ev.status} + event_thin_positive"
    print(f"final honest label   = {label}")

    print("\n=== SELECTION VERDICT (secondary: can factors select bigger gaps?) ===")
    sv, surv, univ = selection_verdict(fbs, cache, idx_maps, returns, dates, calendar, snap_id)
    if sv is None:
        print("selection verdict: NOT RUN (stubbed)")
        if univ:
            print(f"  universe days={len(univ)} survivors days={len(surv)}")
        print("  reason: factor-join coverage insufficient OR no day with >=5 picks")
    else:
        print(f"status               = {sv.status}")
        print(f"selection_lift       = {sv.selection_lift}")
        print(f"days_robust          = {sv.days_robust}")
        print(f"n                    = {sv.n}")
        print(f"p_permutation        = {sv.p_permutation}")
        print(f"p_bonferroni         = {sv.p_bonferroni}")
        print(f"p_bh                 = {sv.p_bh}")
        print(f"walk_forward_status  = {sv.walk_forward_status}")
        print(f"walk_forward_mean_lift = {sv.walk_forward_mean_lift}")
        print(f"n_comparisons        = {sv.n_comparisons}")

    print("\n=== COMPARISON TO 14-DAY NAIVE BASELINE ===")
    print("14-day baseline.json (cost 0.40%):")
    print("  N=899 mean=1.3345% net_mean=0.9345% t=10.6549 p_one_sided=0.0")
    print("  pos_ratio=0.5684 net_pos_ratio=0.5061 (14 days, 2026-07-28..08-14)")
    print(f"60-day §44v2 (cost {COST*100:.2f}%):")
    print(f"  N={n} gross_mean={gross_mean_pct:.4f}% net_mean={net_mean_pct:.4f}%")
    print(f"  net_win_rate={win_rate:.4f} days_robust={ev.days_robust}")
    print("NOTE: cost not matched (0.70% vs 0.40%); 60d more conservative.")
    print("NOTE: 14d t=10.65 is NAIVE POOLED (inflates n); 60d uses day-clustered")
    print("  days_robust (honest effective n). Volume guard + date-adjacency applied.")
    print("DONE.")


if __name__ == "__main__":
    main()
