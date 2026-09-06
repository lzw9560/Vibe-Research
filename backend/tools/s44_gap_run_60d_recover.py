#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""§44v2 gap run — 60-day recovery: fetch 09-04 opens for the 35 首板 on 09-03
that the stale cache lacks, then recompute the 60-day verdict (in-memory, no
file writes, no commit). Reports both the reproducible 59-day cache-only
verdict AND the complete 60-day cache+refresh verdict.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import baostock as bs
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from s44_verifier.verifier import verify  # noqa: E402

VR = ROOT / ".vibe-research"
UNIVERSE = VR / "first_board_universe_baostock_60d.json"
KLINE = VR / "baostock_kline_cache.json"
COST = 0.0070
FROZEN_COMMIT = "b4e7446"
DATA_SNAPSHOT_ID = "94d33018a4bd"


def baostock_code(code: str) -> str:
    if code.startswith("6"):
        return f"sh.{code}"
    if code.startswith(("0", "3")):
        return f"sz.{code}"
    return f"bj.{code}"


def load_and_index():
    with open(UNIVERSE, encoding="utf-8") as f:
        uni = json.load(f)
    fbs = uni["first_boards"]
    print(f"[universe] {len(fbs)} first_boards", flush=True)
    with open(KLINE, encoding="utf-8") as f:
        cache = json.load(f)
    idx_maps = {c: {b["date"]: i for i, b in enumerate(bars)} for c, bars in cache.items()}
    return fbs, cache, idx_maps


def cache_gap_series(fbs, cache, idx_maps):
    """59-day cache-only series (excludes 09-03 首板 — no D+1 bar in cache)."""
    returns, dates = [], []
    n_unbuyable = 0
    for r in fbs:
        code, d, close_d = r["code"], r["date"], r.get("close")
        if close_d is None or close_d <= 0:
            continue
        bars = cache.get(code)
        if bars is None:
            continue
        i = idx_maps[code].get(d)
        if i is None or i + 1 >= len(bars):
            n_unbuyable += 1
            continue
        open_next = bars[i + 1]["open"]
        if open_next is None or open_next <= 0:
            n_unbuyable += 1
            continue
        returns.append(open_next / close_d - 1.0 - COST)
        dates.append(d)
    return returns, dates, n_unbuyable


def fetch_0904_opens(fbs_0903, cache, idx_maps):
    """Fetch 09-04 opens from baostock (adjustflag=2 前复权) for the 35 首板 on 09-03.

    Verifies adjustment: for each code, compare baostock 09-03 close to cache
    09-03 close — must match (within 0.01) before trusting the 09-04 open.
    """
    lg = bs.login()
    print(f"[baostock] login={lg.error_code} {lg.error_msg}", flush=True)
    fetched = {}  # code -> (open_0904, adj_ok)
    adj_mismatches = []
    for r in fbs_0903:
        code = r["code"]
        bs_code = baostock_code(code)
        close_0903_cache = r["close"]  # universe close == cache close (limit price)
        # fetch 09-03..09-04 to verify adjustment + get 09-04 open
        rs = bs.query_history_k_data_plus(
            bs_code, "date,open,close",
            start_date="2026-09-03", end_date="2026-09-04",
            frequency="d", adjustflag="2",
        )
        rows = {}
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            rows[row[0]] = (float(row[1]), float(row[2]))
        if "2026-09-04" not in rows:
            fetched[code] = (None, None, "no 09-04 bar (suspended?)")
            continue
        open_0904 = rows["2026-09-04"][0]
        # adjustment verification: baostock 09-03 close vs cache 09-03 close
        close_0903_baostock = rows["2026-09-03"][1] if "2026-09-03" in rows else None
        adj_ok = True
        if close_0903_baostock is not None:
            if abs(close_0903_baostock - close_0903_cache) > 0.01:
                adj_ok = False
                adj_mismatches.append((code, close_0903_cache, close_0903_baostock))
        fetched[code] = (open_0904, adj_ok, None)
    bs.logout()
    return fetched, adj_mismatches


def main():
    fbs, cache, idx_maps = load_and_index()
    # 59-day cache-only series
    r59, d59, n_unbuy = cache_gap_series(fbs, cache, idx_maps)
    print(f"[59d] n={len(r59)} unbuyable={n_unbuy} unique_dates={len(set(d59))}", flush=True)

    # 35 首板 on 09-03
    fbs_0903 = [r for r in fbs if r["date"] == "2026-09-03"]
    print(f"[recover] 首板 on 09-03 = {len(fbs_0903)}", flush=True)

    fetched, adj_mm = fetch_0904_opens(fbs_0903, cache, idx_maps)
    n_got = sum(1 for v in fetched.values() if v[0] is not None)
    n_adj_bad = sum(1 for v in fetched.values() if v[0] is not None and not v[1])
    print(f"[recover] fetched 09-04 opens: {n_got}/{len(fbs_0903)}", flush=True)
    print(f"[recover] adjustment mismatches: {n_adj_bad}", flush=True)
    if adj_mm:
        print(f"[recover] mismatch details: {adj_mm}", flush=True)

    # build 35 additional gap_returns (date=09-03), only adj_ok ones
    new_returns, new_dates = [], []
    n_skip_adj = 0
    n_skip_noopen = 0
    for r in fbs_0903:
        code = r["code"]
        close_d = r["close"]
        res = fetched.get(code)
        if res is None or res[0] is None:
            n_skip_noopen += 1
            continue
        open_0904, adj_ok, _ = res
        if not adj_ok:
            n_skip_adj += 1
            continue
        new_returns.append(open_0904 / close_d - 1.0 - COST)
        new_dates.append("2026-09-03")
    print(f"[recover] valid new gaps: {len(new_returns)} (skip no_open={n_skip_noopen} skip adj_bad={n_skip_adj})", flush=True)

    # 60-day series = 59d + new
    r60 = r59 + new_returns
    d60 = d59 + new_dates

    def stats(arr, dates):
        a = np.asarray(arr, dtype=float)
        n = a.size
        days = len(set(dates))
        gross = float((a + COST).mean()) * 100 if n else 0.0
        net = float(a.mean()) * 100 if n else 0.0
        wr = float((a > 0).mean()) if n else 0.0
        med = float(np.median(a)) * 100 if n else 0.0
        std = float(a.std(ddof=1)) * 100 if n > 1 else 0.0
        t = net / (std / (n ** 0.5)) if n > 1 and std > 0 else 0.0
        return dict(n=n, days=days, gross=gross, net=net, wr=wr, med=med, std=std, t=t)

    s59 = stats(r59, d59)
    s60 = stats(r60, d60)
    print("\n=== SERIES STATS ===", flush=True)
    print(f"{'':12} {'n':>6} {'days':>5} {'gross%':>8} {'net%':>8} {'net_wr':>7} {'med%':>7} {'std%':>6} {'naive_t':>8}", flush=True)
    print(f"{'59d cache':12} {s59['n']:>6} {s59['days']:>5} {s59['gross']:>8.4f} {s59['net']:>8.4f} {s59['wr']:>7.4f} {s59['med']:>7.4f} {s59['std']:>6.4f} {s59['t']:>8.4f}", flush=True)
    print(f"{'60d +recov':12} {s60['n']:>6} {s60['days']:>5} {s60['gross']:>8.4f} {s60['net']:>8.4f} {s60['wr']:>7.4f} {s60['med']:>7.4f} {s60['std']:>6.4f} {s60['t']:>8.4f}", flush=True)

    def run_event(returns, dates, snap_id):
        v = verify(
            returns=np.asarray(returns, dtype=float),
            n_trials=1, edge_type="event", dates=dates,
            frozen_commit=FROZEN_COMMIT, data_snapshot_id=snap_id,
        )
        return v

    print("\n=== EVENT VERDICT: 59-DAY (cache-only, reproducible) ===", flush=True)
    v59 = run_event(r59, d59, "94d33018a4bd")
    _print_verdict(v59)

    print("\n=== EVENT VERDICT: 60-DAY (cache + 09-04 refresh for 35 codes) ===", flush=True)
    v60 = run_event(r60, d60, "94d33018a4bd+baostock_0904_refresh_35codes")
    _print_verdict(v60)

    # R6 gate
    print("\n=== R6 GATE ===", flush=True)
    print(f"59d: days_robust={v59.days_robust} -> {'CROSSES R6' if v59.days_robust>=60 else 'UNDERPOWERED (<60)'}", flush=True)
    print(f"60d: days_robust={v60.days_robust} -> {'CROSSES R6' if v60.days_robust>=60 else 'UNDERPOWERED (<60)'}", flush=True)

    # honest label 60d
    print("\n=== HONEST LABEL (60d) ===", flush=True)
    if v60.event_metrics and v60.event_metrics.mean_return > 0:
        print("mean>0 but event t-test STUBBED -> event_thin_positive", flush=True)
    print(f"60d status: {v60.status}", flush=True)
    if v60.status == "exploratory" and v60.event_metrics and v60.event_metrics.mean_return > 0:
        print(f"-> exploratory + event_thin_positive (positive, NOT robust_edge: lift<2x or t-test stubbed)", flush=True)

    # comparison
    print("\n=== vs 14-DAY NAIVE BASELINE ===", flush=True)
    print("14d (cost 0.40%): N=899 gross_mean=1.3345% net=0.9345% t=10.6549 net_wr=0.5061 (14d, NAIVE POOLED t)", flush=True)
    print(f"60d (cost 0.70%): N={s60['n']} gross_mean={s60['gross']:.4f}% net={s60['net']:.4f}% net_wr={s60['wr']:.4f} naive_t={s60['t']:.4f} (day-clustered days_robust={v60.days_robust}, event t-test STUBBED)", flush=True)
    print("NOTE: 60d cost more conservative (0.70 vs 0.40); net_mean lower but gross_mean matches 14d (~1.32 vs 1.33).", flush=True)
    print("DONE.", flush=True)


def _print_verdict(v):
    print(f"status         = {v.status}", flush=True)
    print(f"days_robust    = {v.days_robust}", flush=True)
    print(f"n              = {v.n}", flush=True)
    print(f"n_effective    = {v.n_effective}", flush=True)
    if v.event_metrics:
        em = v.event_metrics
        print(f"  mean_return  = {em.mean_return:.6f} ({em.mean_return*100:.4f}%)", flush=True)
        print(f"  win_rate     = {em.win_rate:.4f}", flush=True)
        print(f"  t_stat_day_clust = {em.t_stat_day_clustered}  (STUB TODO)", flush=True)
        print(f"  n_event      = {em.n_event}", flush=True)
    print(f"event_status   = {v.event_status}", flush=True)
    print(f"dsr            = {v.dsr} ({v.dsr_method})", flush=True)
    print(f"pbo            = {v.pbo}  (single-strategy N/A)", flush=True)
    print(f"note           = {v.note!r}", flush=True)


if __name__ == "__main__":
    main()
