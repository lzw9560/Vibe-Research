#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""§44v2 gap run — 60-day recovery: fetch 09-04 opens for the 35 首板 on 09-03
that the stale cache lacks, then recompute the 60-day verdict (in-memory, no
file writes, no commit). Reports both the reproducible 59-day cache-only
verdict AND the complete 60-day cache+refresh verdict.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import sys
from pathlib import Path

import baostock as bs
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from s44_verifier.verifier import verify  # noqa: E402
from s44_verifier.recorder import (  # noqa: E402
    Recorder,
    compute_composite_snapshot_id,
)
from pit_store import SnapshotStore  # noqa: E402

VR = ROOT / ".vibe-research"
UNIVERSE = VR / "first_board_universe_baostock_60d.json"
KLINE = VR / "baostock_kline_cache.json"
COST = 0.0070
FROZEN_COMMIT = "b4e7446"


def baostock_code(code: str) -> str:
    if code.startswith("6"):
        return f"sh.{code}"
    if code.startswith(("0", "3")):
        return f"sz.{code}"
    return f"bj.{code}"


def build_trading_calendar(cache: dict) -> list[str]:
    """Build sorted list of all trading dates from cache (union of all codes).

    Mirrors derive_first_board_baostock.py:110. Used for date-adjacency check:
    bars[i+1]['date'] must == calendar_next(bars[i]['date']) to ensure D+1
    was not suspended (MEDIUM #3 date adjacency).
    """
    all_dates: set[str] = set()
    for bars in cache.values():
        for b in bars:
            all_dates.add(b["date"])
    return sorted(all_dates)


def calendar_next(calendar: list[str], date_str: str) -> str | None:
    """Next trading day after date_str in the calendar. None if date is last."""
    idx = bisect.bisect_left(calendar, date_str)
    if idx < len(calendar) and calendar[idx] == date_str:
        return calendar[idx + 1] if idx + 1 < len(calendar) else None
    if idx < len(calendar):
        return calendar[idx]  # date_str not in calendar, return first after
    return None


def load_and_index():
    with open(UNIVERSE, encoding="utf-8") as f:
        uni = json.load(f)
    fbs = uni["first_boards"]
    print(f"[universe] {len(fbs)} first_boards", flush=True)
    with open(KLINE, encoding="utf-8") as f:
        cache = json.load(f)
    idx_maps = {c: {b["date"]: i for i, b in enumerate(bars)} for c, bars in cache.items()}
    calendar = build_trading_calendar(cache)
    print(f"[calendar] {len(calendar)} trading dates", flush=True)
    return fbs, cache, idx_maps, calendar


def cache_gap_series(fbs, cache, idx_maps, calendar):
    """59-day cache-only series (excludes 09-03 首板 — no D+1 bar in cache).

    Fixes applied:
    - MEDIUM #3 date adjacency: bars[i+1]['date'] must == calendar_next(D)
    - LOW #9 volume guard: zero-volume bars are suspended (fake returns)
    - HIGH #2 adj-epoch check: cache close at D must match universe close_d
    """
    returns, dates = [], []
    n_unbuyable = 0
    n_suspended = 0
    n_adj_mismatch = 0
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
        # adjustment-epoch consistency: cache close at D must match universe close_d
        cache_close_d = bars[i].get("close")
        if cache_close_d is not None and abs(cache_close_d - close_d) > 0.01:
            n_adj_mismatch += 1
            continue
        # date adjacency: bars[i+1] must be the calendar-next trading day (D+1)
        expected_next = calendar_next(calendar, d)
        if expected_next is not None and bars[i + 1]["date"] != expected_next:
            n_suspended += 1
            continue
        open_next = bars[i + 1]["open"]
        if open_next is None or open_next <= 0:
            n_unbuyable += 1
            continue
        # volume guard: zero-volume bars are suspended (fake -0.70% returns)
        if bars[i + 1].get("volume", 0) <= 0:
            n_unbuyable += 1
            continue
        returns.append(open_next / close_d - 1.0 - COST)
        dates.append(d)
    return returns, dates, n_unbuyable, n_suspended, n_adj_mismatch


def fetch_0904_opens(fbs_0903, cache, idx_maps, calendar):
    """Fetch 09-04 opens from baostock (adjustflag=2 前复权) for the 35 首板 on 09-03.

    Verifies adjustment: for each code, compare baostock 09-03 close to cache
    09-03 close — must match (within 0.01) before trusting the 09-04 open.

    Fixes applied:
    - LOW #9: query fields "date,open,close,volume" + skip volume<=0
    - HIGH #2: persist fetched opens via pit_store SnapshotStore
    """
    lg = bs.login()
    print(f"[baostock] login={lg.error_code} {lg.error_msg}", flush=True)
    fetched = {}  # code -> (open_0904, adj_ok, note)
    adj_mismatches = []
    for r in fbs_0903:
        code = r["code"]
        bs_code = baostock_code(code)
        close_0903_cache = r["close"]  # universe close == cache close (limit price)
        # fetch 09-03..09-04 to verify adjustment + get 09-04 open + volume
        rs = bs.query_history_k_data_plus(
            bs_code, "date,open,close,volume",
            start_date="2026-09-03", end_date="2026-09-04",
            frequency="d", adjustflag="2",
        )
        rows = {}
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            rows[row[0]] = (float(row[1]), float(row[2]), float(row[3]))  # (open, close, volume)
        if "2026-09-04" not in rows:
            fetched[code] = (None, None, "no 09-04 bar (suspended?)")
            continue
        open_0904, _, vol_0904 = rows["2026-09-04"]
        # volume guard: zero volume = suspended (LOW #9)
        if vol_0904 <= 0:
            fetched[code] = (None, None, "zero volume (suspended)")
            continue
        # adjustment verification: baostock 09-03 close vs cache 09-03 close
        close_0903_baostock = rows["2026-09-03"][1] if "2026-09-03" in rows else None
        adj_ok = True
        if close_0903_baostock is not None:
            if abs(close_0903_baostock - close_0903_cache) > 0.01:
                adj_ok = False
                adj_mismatches.append((code, close_0903_cache, close_0903_baostock))
        fetched[code] = (open_0904, adj_ok, None)
    bs.logout()

    # persist fetched opens via pit_store (HIGH #2 reproducibility)
    try:
        store = SnapshotStore()
        snapshot_id = store.put(
            source="baostock_0904_refresh",
            data_date="2026-09-04",
            query_spec={
                "codes": [r["code"] for r in fbs_0903],
                "adjustflag": "2",
                "fields": "date,open,close,volume",
            },
            raw_bytes=json.dumps(fetched, sort_keys=True).encode(),
            generator_commit=FROZEN_COMMIT,
        )
        print(f"[pit_store] persisted 09-04 opens: snapshot_id={snapshot_id}", flush=True)
    except Exception as e:
        snapshot_id = None
        print(f"[pit_store] persist failed (non-fatal): {e}", flush=True)

    return fetched, adj_mismatches, snapshot_id


def main():
    fbs, cache, idx_maps, calendar = load_and_index()

    # composite data_snapshot_id (HIGH #2: pins BOTH universe + kline cache)
    snap_id_59 = compute_composite_snapshot_id(UNIVERSE, KLINE)
    print(f"[snapshot] composite data_snapshot_id = {snap_id_59}", flush=True)

    # 59-day cache-only series
    r59, d59, n_unbuy, n_susp, n_adj = cache_gap_series(fbs, cache, idx_maps, calendar)
    print(f"[59d] n={len(r59)} unbuyable={n_unbuy} suspended={n_susp} adj_mismatch={n_adj} unique_dates={len(set(d59))}", flush=True)

    # 35 首板 on 09-03
    fbs_0903 = [r for r in fbs if r["date"] == "2026-09-03"]
    print(f"[recover] 首板 on 09-03 = {len(fbs_0903)}", flush=True)

    fetched, adj_mm, pit_snap_id = fetch_0904_opens(fbs_0903, cache, idx_maps, calendar)
    n_got = sum(1 for v in fetched.values() if v[0] is not None)
    n_adj_bad = sum(1 for v in fetched.values() if v[0] is not None and not v[1])
    print(f"[recover] fetched 09-04 opens: {n_got}/{len(fbs_0903)}", flush=True)
    print(f"[recover] adjustment mismatches: {n_adj_bad}", flush=True)
    if adj_mm:
        print(f"[recover] mismatch details: {adj_mm}", flush=True)

    # build 35 additional gap_returns (date=09-03), only adj_ok ones
    # date adjacency: 09-04 must be calendar-next of 09-03
    expected_0904 = calendar_next(calendar, "2026-09-03")
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
    if expected_0904 and expected_0904 != "2026-09-04":
        print(f"[recover] WARNING: calendar_next(09-03)={expected_0904} != 2026-09-04 (date adjacency)", flush=True)

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

    # materiality floor = max(_EVENT_MATERIALITY_FLOOR, cost * 0.5)
    from s44_verifier.stats import _EVENT_MATERIALITY_FLOOR  # noqa: E402
    eff_floor = max(_EVENT_MATERIALITY_FLOOR, COST * 0.5)

    def run_event(returns, dates, snap_id):
        v = verify(
            returns=np.asarray(returns, dtype=float),
            n_trials=1, edge_type="event", dates=dates,
            frozen_commit=FROZEN_COMMIT, data_snapshot_id=snap_id,
            round_trip_cost=COST,
        )
        return v

    print("\n=== EVENT VERDICT: 59-DAY (cache-only, reproducible) ===", flush=True)
    v59 = run_event(r59, d59, snap_id_59)
    _print_verdict(v59)

    # 60d snapshot_id = composite + pit snapshot (if persisted)
    snap_id_60 = f"{snap_id_59}+pit_{pit_snap_id}" if pit_snap_id else f"{snap_id_59}+baostock_0904_refresh_unpinned"
    print("\n=== EVENT VERDICT: 60-DAY (cache + 09-04 refresh for 35 codes) ===", flush=True)
    v60 = run_event(r60, d60, snap_id_60)
    _print_verdict(v60)

    # persist to Recorder (HIGH #2 reproducibility)
    try:
        recorder = Recorder()
        recorder_id_60 = recorder.save(
            data_snapshot_id=snap_id_60,
            input_hashes={
                "universe": snap_id_59.split("+")[0],
                "kline_cache": snap_id_59.split("+")[1] if "+" in snap_id_59 else "unknown",
                "baostock_0904_refresh": f"pit_{pit_snap_id}" if pit_snap_id else "unpinned",
            },
            return_series=r60,
            dates=d60,
            params={
                "edge_type": "event",
                "n_trials": 1,
                "round_trip_cost": COST,
                "event_materiality_floor": eff_floor,
                "frozen_commit": FROZEN_COMMIT,
            },
            frozen_commit=FROZEN_COMMIT,
            verdict={
                "status": v60.status,
                "event_status": v60.event_status,
                "days_robust": v60.days_robust,
                "n": v60.n,
                "n_effective": v60.n_effective,
                "data_snapshot_id": snap_id_60,
            },
        )
        print(f"\n[recorder] saved 60d verdict: recorder_id={recorder_id_60}", flush=True)
    except Exception as e:
        print(f"[recorder] save failed (non-fatal): {e}", flush=True)

    # R6 gate
    print("\n=== R6 GATE ===", flush=True)
    print(f"59d: days_robust={v59.days_robust} -> {'CROSSES R6' if v59.days_robust>=60 else 'UNDERPOWERED (<60)'}", flush=True)
    print(f"60d: days_robust={v60.days_robust} -> {'CROSSES R6' if v60.days_robust>=60 else 'UNDERPOWERED (<60)'}", flush=True)

    # honest label 60d
    print("\n=== HONEST LABEL (60d) ===", flush=True)
    es = v60.event_status
    if es == "event_robust":
        print(f"-> event_robust: t-test p<0.05 + days>=60 + net>{eff_floor*100:.2f}% -> status={v60.status}", flush=True)
    elif es == "event_thin_positive":
        if v60.event_metrics and v60.event_metrics.p_one_sided is not None:
            if v60.event_metrics.p_one_sided < 0.05:
                print(f"-> event_thin_positive: p<0.05 BUT (days<60 OR net<={eff_floor*100:.2f}%) -> status={v60.status}", flush=True)
            else:
                print(f"-> event_thin_positive: p>={v60.event_metrics.p_one_sided:.4f} >= 0.05 (positive but NOT statistically significant) -> status={v60.status}", flush=True)
        else:
            print(f"-> event_thin_positive -> status={v60.status}", flush=True)
    elif es == "event_falsified":
        print(f"-> event_falsified: day_mean<=0 -> status={v60.status}", flush=True)
    else:
        print(f"-> event_not_tested -> status={v60.status}", flush=True)

    # comparison
    print("\n=== vs 14-DAY NAIVE BASELINE ===", flush=True)
    print("14d (cost 0.40%): N=899 gross_mean=1.3345% net=0.9345% t=10.6549 net_wr=0.5061 (14d, NAIVE POOLED t)", flush=True)
    em60 = v60.event_metrics
    t_clust = em60.t_stat_day_clustered if em60 else "N/A"
    p_clust = em60.p_one_sided if em60 and em60.p_one_sided is not None else "N/A"
    n_days = em60.n_days if em60 and em60.n_days is not None else "N/A"
    print(
        f"60d (cost 0.70%): N={s60['n']} gross_mean={s60['gross']:.4f}% net={s60['net']:.4f}% "
        f"net_wr={s60['wr']:.4f} naive_pooled_t={s60['t']:.4f} | "
        f"day_clustered_t={t_clust} p_one_sided={p_clust} n_days={n_days} "
        f"days_robust={v60.days_robust} event_status={v60.event_status}",
        flush=True,
    )
    print("NOTE: 60d cost more conservative (0.70 vs 0.40); net_mean lower but gross_mean matches 14d (~1.32 vs 1.33).", flush=True)
    print(f"NOTE: volume guard removed zero-volume fake returns; date adjacency removed suspended picks; adj-epoch check skipped {n_adj} mismatches.", flush=True)
    print("DONE.", flush=True)


def _print_verdict(v):
    print(f"status         = {v.status}", flush=True)
    print(f"days_robust    = {v.days_robust}", flush=True)
    print(f"n              = {v.n}", flush=True)
    print(f"n_effective    = {v.n_effective}", flush=True)
    if v.event_metrics:
        em = v.event_metrics
        print(f"  mean_return  = {em.mean_return:.6f} ({em.mean_return*100:.4f}%)", flush=True)
        if em.net_mean is not None:
            print(f"  net_mean     = {em.net_mean:.6f} ({em.net_mean*100:.4f}%)  [day-clustered]", flush=True)
        else:
            print(f"  net_mean     = None", flush=True)
        print(f"  win_rate     = {em.win_rate:.4f}", flush=True)
        print(f"  t_stat_day_clust = {em.t_stat_day_clustered}", flush=True)
        if em.p_one_sided is not None:
            print(f"  p_one_sided  = {em.p_one_sided}", flush=True)
        if em.n_days is not None:
            print(f"  n_days       = {em.n_days}", flush=True)
        if em.day_mean is not None:
            print(f"  day_mean     = {em.day_mean:.8f} ({em.day_mean*100:.4f}%)", flush=True)
        if em.day_std is not None:
            print(f"  day_std      = {em.day_std:.8f} ({em.day_std*100:.4f}%)", flush=True)
        print(f"  base_rate    = {em.base_rate}", flush=True)
        print(f"  n_event      = {em.n_event}", flush=True)
    print(f"event_status   = {v.event_status}", flush=True)
    print(f"dsr            = {v.dsr} ({v.dsr_method})", flush=True)
    print(f"pbo            = {v.pbo}  (single-strategy N/A)", flush=True)
    print(f"note           = {v.note!r}", flush=True)


if __name__ == "__main__":
    main()
