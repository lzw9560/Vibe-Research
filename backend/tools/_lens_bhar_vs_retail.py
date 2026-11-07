# -*- coding: utf-8 -*-
"""BHAR vs Retail Return decomposition lens.

Core question: BHAR (corrected) = d_exit - d_entry (discount change).
Retail return = raw_ev = (exit_close - entry)/entry (price change).
When discount converges via NAV dropping, BHAR > 0 but retail = 0.
Quantify how much of BHAR is capturable vs NAV-driven (not capturable).
"""

import json
import sys
import statistics
from collections import defaultdict
from pathlib import Path
from math import sqrt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._factor_helpers import ev_stats, day_paired_t

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
ETF_CACHE = DATA / "etf_premium_cache.json"

ETF_COST = 0.15

ETF_UNIVERSE = {
    "510300": ("沪深300ETF", "broad"),
    "510050": ("上证50ETF", "broad"),
    "510500": ("中证500ETF", "broad"),
    "510880": ("红利ETF", "broad"),
    "512890": ("红利低波ETF", "broad"),
    "512100": ("中证1000ETF", "broad"),
    "588000": ("科创50ETF", "broad"),
    "159901": ("深100ETF", "broad"),
    "510310": ("价值ETF", "broad"),
    "159955": ("中小盘ETF", "broad"),
    "159915": ("创业板ETF", "broad"),
    "512760": ("半导体ETF", "sector"),
    "159995": ("芯片ETF", "sector"),
    "515790": ("光伏ETF", "sector"),
    "512660": ("军工ETF", "sector"),
}


def load_etf_data():
    with open(ETF_CACHE) as f:
        return json.load(f)


def build_calendar(etf_data):
    all_dates = set()
    for days in etf_data.values():
        all_dates.update(days.keys())
    return sorted(all_dates)


def is_yizi_etf_proxy(t1_open, t_close):
    if t_close <= 0:
        return False
    return t1_open / t_close >= 1.099


def build_picks(etf_data, calendar, threshold=-0.3, hold_days=1):
    date_idx = {d: i for i, d in enumerate(calendar)}
    exit_offset = 1 + hold_days
    picks = []
    for code, days in etf_data.items():
        for d, b in days.items():
            nav_signal = b.get("nav")
            close_signal = b.get("close")
            if nav_signal is None or nav_signal <= 0 or close_signal is None:
                continue
            disc = (close_signal - nav_signal) / nav_signal * 100
            if disc >= threshold:
                continue
            di = date_idx.get(d)
            if di is None or di + exit_offset >= len(calendar):
                continue
            t1_date = calendar[di + 1]
            exit_date = calendar[di + exit_offset]
            t1 = days.get(t1_date)
            ex = days.get(exit_date)
            if t1 is None or ex is None:
                continue
            entry = t1.get("open")
            exit_close = ex.get("close")
            nav_t1 = t1.get("nav")
            nav_exit = ex.get("nav")
            if None in (entry, exit_close, nav_t1, nav_exit):
                continue
            if entry <= 0 or exit_close <= 0 or nav_t1 <= 0 or nav_exit <= 0:
                continue
            if is_yizi_etf_proxy(entry, close_signal):
                continue
            picks.append(
                {
                    "code": code,
                    "signal_date": d,
                    "t1_date": t1_date,
                    "exit_date": exit_date,
                    "hold_days": hold_days,
                    "discount_t": disc,
                    "entry": entry,
                    "exit_close": exit_close,
                    "nav_signal": nav_signal,
                    "nav_t1": nav_t1,
                    "nav_exit": nav_exit,
                    "zt_date": d,
                }
            )
    return picks


def bhar_corrected(p):
    """Corrected BHAR = d_exit - d_entry (discount change, beta-neutral)."""
    d_entry = (p["entry"] - p["nav_signal"]) / p["nav_signal"] * 100
    d_exit = (p["exit_close"] - p["nav_exit"]) / p["nav_exit"] * 100
    return d_exit - d_entry


def raw_ev(p):
    """Retail investor actual P&L = (exit_close - entry)/entry."""
    return (p["exit_close"] - p["entry"]) / p["entry"] * 100


def price_ret(p):
    """Price return = same as raw_ev."""
    return (p["exit_close"] - p["entry"]) / p["entry"] * 100


def nav_ret_signal_to_exit(p):
    """NAV return from signal (T close) to exit (T+k close).
    This is the market beta proxy. When this is negative, NAV dropped,
    causing discount to narrow mechanically (not capturable by retail)."""
    return (p["nav_exit"] - p["nav_signal"]) / p["nav_signal"] * 100


def nav_ret_t1_to_exit(p):
    """NAV return from T+1 close to T+k close (matches holding period better)."""
    return (p["nav_exit"] - p["nav_t1"]) / p["nav_t1"] * 100


def main():
    etf_data = load_etf_data()
    calendar = build_calendar(etf_data)

    picks = build_picks(etf_data, calendar, -0.3, hold_days=1)
    print(f"Total picks (disc<-0.3%, 1d hold): {len(picks)}")

    # Compute all metrics per pick
    for p in picks:
        p["bhar"] = bhar_corrected(p)
        p["raw"] = raw_ev(p)
        p["price_ret"] = price_ret(p)
        p["nav_ret_s2x"] = nav_ret_signal_to_exit(p)  # NAV signal->exit
        p["nav_ret_t1x"] = nav_ret_t1_to_exit(p)  # NAV T+1->exit

    # ---- Aggregate stats ----
    bhars = [p["bhar"] for p in picks]
    raws = [p["raw"] for p in picks]
    navs_s2x = [p["nav_ret_s2x"] for p in picks]
    navs_t1x = [p["nav_ret_t1x"] for p in picks]

    bh_s = ev_stats(bhars)
    rw_s = ev_stats(raws)
    nv_s = ev_stats(navs_s2x)
    nv_t1_s = ev_stats(navs_t1x)

    print(f"\n{'=' * 78}")
    print("AGGREGATE STATS (disc<-0.3%, 1d hold, full sample)")
    print(f"{'=' * 78}")
    print(f"BHAR (corrected):      mean={bh_s['ev']:+.3f}%  std={bh_s['std']}%  WR={bh_s['wr']}%")
    print(f"Raw EV (retail P&L):   mean={rw_s['ev']:+.3f}%  std={rw_s['std']}%  WR={rw_s['wr']}%")
    print(f"NAV ret (sig->exit):   mean={nv_s['ev']:+.3f}%  std={nv_s['std']}%")
    print(f"NAV ret (T+1->exit):   mean={nv_t1_s['ev']:+.3f}%  std={nv_t1_s['std']}%")
    print(f"\nDecomposition: raw_ev ≈ BHAR + nav_ret")
    print(f"  BHAR + nav_ret(s2x) = {bh_s['ev']:+.3f} + {nv_s['ev']:+.3f} = {bh_s['ev'] + nv_s['ev']:+.3f}%")
    print(f"  Actual raw_ev         = {rw_s['ev']:+.3f}%")
    print(f"  Residual (2nd-order)  = {rw_s['ev'] - (bh_s['ev'] + nv_s['ev']):+.3f}% (cross-term)")

    # ---- Day-paired t-test for raw_ev ----
    raw_by_date = defaultdict(list)
    bhar_by_date = defaultdict(list)
    for p in picks:
        raw_by_date[p["signal_date"]].append(p["raw"])
        bhar_by_date[p["signal_date"]].append(p["bhar"])
    raw_dt = day_paired_t(raw_by_date)
    bhar_dt = day_paired_t(bhar_by_date)

    print(f"\nDay-paired t-test:")
    print(f"  BHAR:     day_t={bhar_dt['t']}  p={bhar_dt['p_one_sided']}  n_days={bhar_dt['n_days']}")
    print(f"  Raw EV:   day_t={raw_dt['t']}  p={raw_dt['p_one_sided']}  n_days={raw_dt['n_days']}")

    # ---- KEY: Decompose BHAR into capturable vs non-capturable ----
    print(f"\n{'=' * 78}")
    print("KEY DECOMPOSITION: How much BHAR is capturable by retail?")
    print(f"{'=' * 78}")
    print("Discount converges via:")
    print("  A) Price rising (nav flat) → retail captures → CAPTURABLE")
    print("  B) NAV dropping (price flat) → retail does NOT capture → NOT CAPTURABLE")
    print("  C) Both → partially capturable")
    print()

    # For each pick, decompose:
    # BHAR ≈ price_ret - nav_ret (first-order approximation)
    # price_ret = raw_ev (retail captures)
    # nav_ret = market beta proxy (retail does NOT capture the convergence from this)
    # So: capturable portion of BHAR ≈ price_ret when nav_ret=0
    #     non-capturable portion ≈ -nav_ret (when nav drops, discount narrows)

    # Categorize picks
    nav_flat_thresh = 0.05  # within 0.05% = "flat"

    cat_price_rise = []  # nav flat, price rose → capturable
    cat_nav_drop = []  # price flat, nav dropped → not capturable
    cat_both_up = []  # both rose
    cat_both_down = []  # both fell
    cat_other = []

    for p in picks:
        pr = p["price_ret"]
        nr = p["nav_ret_s2x"]
        nav_flat = abs(nr) < nav_flat_thresh
        price_flat = abs(pr) < nav_flat_thresh

        if nav_flat and pr > 0:
            cat_price_rise.append(p)
        elif price_flat and nr < 0:
            cat_nav_drop.append(p)
        elif pr > 0 and nr > 0:
            cat_both_up.append(p)
        elif pr < 0 and nr < 0:
            cat_both_down.append(p)
        else:
            cat_other.append(p)

    print(f"Category breakdown (nav_flat thresh={nav_flat_thresh}%):")
    print(f"  A. Price rises, NAV flat (CAPTURABLE):   n={len(cat_price_rise):>5}")
    print(f"  B. Price flat, NAV drops (NOT CAPTURABLE): n={len(cat_nav_drop):>5}")
    print(f"  C. Both rise:                              n={len(cat_both_up):>5}")
    print(f"  D. Both fall:                              n={len(cat_both_down):>5}")
    print(f"  E. Other (mixed):                         n={len(cat_other):>5}")

    # ---- Split by nav_ret sign (more robust than flat threshold) ----
    print(f"\n{'=' * 78}")
    print("SPLIT BY NAV RETURN SIGN (more robust)")
    print(f"{'=' * 78}")

    nav_pos = [p for p in picks if p["nav_ret_s2x"] > 0]  # NAV rose
    nav_neg = [p for p in picks if p["nav_ret_s2x"] <= 0]  # NAV dropped/flat

    print(f"\nNAV rose (nav_ret > 0): n={len(nav_pos)} ({len(nav_pos) / len(picks) * 100:.1f}%)")
    if nav_pos:
        bhar_pos = ev_stats([p["bhar"] for p in nav_pos])
        raw_pos = ev_stats([p["raw"] for p in nav_pos])
        nav_pos_s = ev_stats([p["nav_ret_s2x"] for p in nav_pos])
        print(f"  BHAR:     mean={bhar_pos['ev']:+.3f}%  WR={bhar_pos['wr']}%")
        print(f"  Raw EV:   mean={raw_pos['ev']:+.3f}%  WR={raw_pos['wr']}%")
        print(f"  NAV ret:  mean={nav_pos_s['ev']:+.3f}%")
        print(f"  → Retail captures raw_ev ({raw_pos['ev']:+.3f}%) which is HIGHER than BHAR ({bhar_pos['ev']:+.3f}%)")
        print(f"    because market beta (nav_ret={nav_pos_s['ev']:+.3f}%) adds to price")

    print(f"\nNAV dropped/flat (nav_ret <= 0): n={len(nav_neg)} ({len(nav_neg) / len(picks) * 100:.1f}%)")
    if nav_neg:
        bhar_neg = ev_stats([p["bhar"] for p in nav_neg])
        raw_neg = ev_stats([p["raw"] for p in nav_neg])
        nav_neg_s = ev_stats([p["nav_ret_s2x"] for p in nav_neg])
        print(f"  BHAR:     mean={bhar_neg['ev']:+.3f}%  WR={bhar_neg['wr']}%")
        print(f"  Raw EV:   mean={raw_neg['ev']:+.3f}%  WR={raw_neg['wr']}%")
        print(f"  NAV ret:  mean={nav_neg_s['ev']:+.3f}%")
        print(f"  → Retail captures raw_ev ({raw_neg['ev']:+.3f}%) which is LOWER than BHAR ({bhar_neg['ev']:+.3f}%)")
        print(f"    because NAV drop creates phantom convergence alpha")

        # How many NAV-negative picks have positive BHAR but negative/zero retail?
        phantom = [p for p in nav_neg if p["bhar"] > 0 and p["raw"] <= 0]
        phantom_bhar = sum(p["bhar"] for p in phantom)
        total_bhar_neg = sum(p["bhar"] for p in nav_neg)
        print(f"\n  PHANTOM ALPHA picks (BHAR>0 but retail<=0): n={len(phantom)}")
        print(f"    Their BHAR sum: {phantom_bhar:+.2f}%")
        print(f"    Total BHAR sum (nav-neg group): {total_bhar_neg:+.2f}%")
        if total_bhar_neg != 0:
            print(f"    Phantom fraction: {phantom_bhar / total_bhar_neg * 100:.1f}% of nav-neg BHAR")

    # ---- Sum-level decomposition ----
    print(f"\n{'=' * 78}")
    print("SUM-LEVEL DECOMPOSITION (total BHAR vs capturable)")
    print(f"{'=' * 78}")

    total_bhar = sum(p["bhar"] for p in picks)
    total_raw = sum(p["raw"] for p in picks)
    total_nav = sum(p["nav_ret_s2x"] for p in picks)

    print(f"Sum BHAR:        {total_bhar:+.2f}%  (mean={total_bhar / len(picks):+.3f}%)")
    print(f"Sum Raw EV:      {total_raw:+.2f}%  (mean={total_raw / len(picks):+.3f}%)")
    print(f"Sum NAV ret:     {total_nav:+.2f}%  (mean={total_nav / len(picks):+.3f}%)")
    print(f"Sum BHAR+NAV:    {total_bhar + total_nav:+.2f}%  (should ≈ Sum Raw EV)")

    # The non-capturable portion = BHAR from picks where NAV dropped
    bhar_from_nav_neg = sum(p["bhar"] for p in picks if p["nav_ret_s2x"] <= 0)
    bhar_from_nav_pos = sum(p["bhar"] for p in picks if p["nav_ret_s2x"] > 0)
    raw_from_nav_neg = sum(p["raw"] for p in picks if p["nav_ret_s2x"] <= 0)
    raw_from_nav_pos = sum(p["raw"] for p in picks if p["nav_ret_s2x"] > 0)

    print(
        f"\nBHAR from NAV-negative picks: {bhar_from_nav_neg:+.2f}% (mean={bhar_from_nav_neg / max(1, len([p for p in picks if p['nav_ret_s2x'] <= 0])):+.3f}%)"
    )
    print(
        f"  Retail (raw) from same:     {raw_from_nav_neg:+.2f}% (mean={raw_from_nav_neg / max(1, len([p for p in picks if p['nav_ret_s2x'] <= 0])):+.3f}%)"
    )
    print(f"  Gap (BHAR - Retail):        {bhar_from_nav_neg - raw_from_nav_neg:+.2f}% ← PHANTOM (not capturable)")
    print(
        f"\nBHAR from NAV-positive picks: {bhar_from_nav_pos:+.2f}% (mean={bhar_from_nav_pos / max(1, len([p for p in picks if p['nav_ret_s2x'] > 0])):+.3f}%)"
    )
    print(
        f"  Retail (raw) from same:      {raw_from_nav_pos:+.2f}% (mean={raw_from_nav_pos / max(1, len([p for p in picks if p['nav_ret_s2x'] > 0])):+.3f}%)"
    )
    print(f"  Gap (Retail - BHAR):         {raw_from_nav_pos - bhar_from_nav_pos:+.2f}% ← market beta bonus")

    # ---- THE CRITICAL TEST: Is raw_ev (retail return) positive & significant? ----
    print(f"\n{'=' * 78}")
    print("CRITICAL TEST: Is raw_ev (retail return) positive & significant?")
    print(f"{'=' * 78}")
    print(f"  Raw EV gross:   {rw_s['ev']:+.3f}%  net (after {ETF_COST}% cost): {rw_s['ev'] - ETF_COST:+.3f}%")
    print(f"  Raw EV day_t:   {raw_dt['t']}  p={raw_dt['p_one_sided']}  n_days={raw_dt['n_days']}")
    print(f"  Raw EV WR:      {rw_s['wr']}%")
    print(f"  Raw EV CI:      [{rw_s['ci_lo']}, {rw_s['ci_hi']}]")

    if rw_s["ev"] - ETF_COST > 0 and raw_dt["p_one_sided"] < 0.05:
        print(f"  → Raw EV net POSITIVE and significant → retail CAN capture edge")
    elif rw_s["ev"] - ETF_COST > 0:
        print(f"  → Raw EV net POSITIVE but day_t not significant → edge weak for retail")
    else:
        print(f"  → Raw EV net NEGATIVE → retail CANNOT capture edge (BHAR is phantom)")

    # ---- NAV-negative subset: is retail return positive? ----
    print(f"\n{'=' * 78}")
    print("NAV-NEGATIVE SUBSET: When market falls, does retail still profit?")
    print(f"{'=' * 78}")
    if nav_neg:
        raw_neg_dt = day_paired_t(
            defaultdict(
                list,
                {d: [p["raw"] for p in nav_neg if p["signal_date"] == d] for d in set(p["signal_date"] for p in nav_neg)},
            )
        )
        # rebuild properly
        raw_neg_by_date = defaultdict(list)
        bhar_neg_by_date = defaultdict(list)
        for p in nav_neg:
            raw_neg_by_date[p["signal_date"]].append(p["raw"])
            bhar_neg_by_date[p["signal_date"]].append(p["bhar"])
        raw_neg_dt = day_paired_t(raw_neg_by_date)
        bhar_neg_dt = day_paired_t(bhar_neg_by_date)

        print(f"  n={len(nav_neg)}  n_days={raw_neg_dt['n_days']}")
        print(f"  BHAR:     mean={bhar_neg['ev']:+.3f}%  day_t={bhar_neg_dt['t']}  p={bhar_neg_dt['p_one_sided']}")
        print(f"  Raw EV:   mean={raw_neg['ev']:+.3f}%  day_t={raw_neg_dt['t']}  p={raw_neg_dt['p_one_sided']}")
        print(f"  Raw net:  {raw_neg['ev'] - ETF_COST:+.3f}%")
        if raw_neg["ev"] - ETF_COST <= 0:
            print(f"  → WARNING: When NAV drops, retail return is net NEGATIVE")
            print(f"    BHAR shows +{bhar_neg['ev']:.3f}% but retail gets {raw_neg['ev'] - ETF_COST:+.3f}% net")
            print(f"    This is the PHANTOM ALPHA: BHAR inflates by {bhar_neg['ev'] - (raw_neg['ev'] - ETF_COST):.3f}%")

    # ---- Quantify the inflation: BHAR vs raw_ev difference ----
    print(f"\n{'=' * 78}")
    print("BHAR INFLATION QUANTIFICATION")
    print(f"{'=' * 78}")
    inflation = bh_s["ev"] - rw_s["ev"]
    print(f"  BHAR mean:     {bh_s['ev']:+.3f}%")
    print(f"  Raw EV mean:   {rw_s['ev']:+.3f}%")
    print(f"  Inflation:     {inflation:+.3f}% (BHAR - Raw)")
    if inflation > 0:
        print(f"  → BHAR INFLATES edge by {inflation:.3f}% ({abs(inflation) / max(abs(bh_s['ev']), 0.001) * 100:.1f}% of BHAR)")
        print(f"    This means BHAR OVERSTATES the capturable alpha")
        print(f"    Corrected edge (retail-capturable) = raw_ev = {rw_s['ev']:+.3f}% gross, {rw_s['ev'] - ETF_COST:+.3f}% net")
    elif inflation < 0:
        print(f"  → BHAR DEFLATES edge by {abs(inflation):.3f}% (BHAR is more conservative)")
        print(f"    Retail captures MORE than BHAR due to positive market beta")
        print(f"    But market beta is not a reliable alpha (can be negative)")

    # ---- Walk-forward on raw_ev (retail return) ----
    print(f"\n{'=' * 78}")
    print("WALK-FORWARD ON RAW_EV (retail return, the capturable metric)")
    print(f"{'=' * 78}")

    from tools._factor_helpers import walk_forward

    wf_raw = walk_forward(picks, lambda p: raw_ev(p))
    if wf_raw["status"] == "ok":
        tr = wf_raw["train_ev"]
        te = wf_raw["test_ev"]
        te_dt = wf_raw["test_day_t"]
        print(f"  train: n={tr['n']}  EV={tr['ev']:+.3f}%  t={tr['t']}")
        print(f"  test:  n={te['n']}  EV={te['ev']:+.3f}%  t={te['t']}  day_t={te_dt['t']}  p={te_dt['p_one_sided']}")
        print(f"  test net: {te['ev'] - ETF_COST:+.3f}%")
    else:
        print(f"  {wf_raw['status']}")

    # Also walk-forward on BHAR for comparison
    wf_bhar = walk_forward(picks, lambda p: bhar_corrected(p))
    if wf_bhar["status"] == "ok":
        tr = wf_bhar["train_ev"]
        te = wf_bhar["test_ev"]
        te_dt = wf_bhar["test_day_t"]
        print(f"\n  [BHAR for comparison]:")
        print(f"  train: n={tr['n']}  EV={tr['ev']:+.3f}%  t={tr['t']}")
        print(f"  test:  n={te['n']}  EV={te['ev']:+.3f}%  t={te['t']}  day_t={te_dt['t']}  p={te_dt['p_one_sided']}")

    # ---- Distribution of nav_ret ----
    print(f"\n{'=' * 78}")
    print("NAV RETURN DISTRIBUTION (market beta during holding period)")
    print(f"{'=' * 78}")
    nav_rets_sorted = sorted(navs_s2x)
    n = len(nav_rets_sorted)
    print(f"  n={n}")
    print(f"  mean={nv_s['ev']:+.3f}%  std={nv_s['std']}%")
    print(f"  p10={nav_rets_sorted[int(n * 0.10)]:+.3f}%")
    print(f"  p25={nav_rets_sorted[int(n * 0.25)]:+.3f}%")
    print(f"  p50={nav_rets_sorted[n // 2]:+.3f}%")
    print(f"  p75={nav_rets_sorted[int(n * 0.75)]:+.3f}%")
    print(f"  p90={nav_rets_sorted[int(n * 0.90)]:+.3f}%")
    pct_neg = sum(1 for x in nav_rets_sorted if x <= 0) / n * 100
    print(f"  % with NAV drop (<=0): {pct_neg:.1f}%")
    pct_neg_1 = sum(1 for x in nav_rets_sorted if x <= -0.1) / n * 100
    print(f"  % with NAV drop (<-0.1%): {pct_neg_1:.1f}%")

    # ---- THE EXACT RELATIONSHIP: discount change decomposition ----
    print(f"\n{'=' * 78}")
    print("EXACT DISCOUNT CHANGE DECOMPOSITION")
    print(f"{'=' * 78}")
    print("For each pick: BHAR = d_exit - d_entry (discount change)")
    print("d_exit - d_entry can be decomposed as:")
    print("  = [P_x/N_x - 1] - [P_e/N_s - 1]")
    print("  = P_x/N_x - P_e/N_s")
    print()
    print("If we hold NAV constant (N_x = N_s = N):")
    print("  counterfactual_BHAR = (P_x - P_e)/N = price_ret * (P_e/N) ≈ price_ret")
    print("  → This is what retail captures")
    print()
    print("If we hold PRICE constant (P_x = P_e = P):")
    print("  counterfactual_BHAR_nav = P/N_x - P/N_s = P*(1/N_x - 1/N_s)")
    print("  → This is phantom alpha from NAV change alone")
    print()

    # Compute counterfactual BHARs
    for p in picks:
        P_e = p["entry"]
        P_x = p["exit_close"]
        N_s = p["nav_signal"]
        N_x = p["nav_exit"]
        # Counterfactual: hold NAV constant at N_s, only price changes
        p["bhar_price_only"] = (P_x / N_s - P_e / N_s) * 100  # = (P_x - P_e)/N_s * 100
        # Counterfactual: hold price constant at P_e, only NAV changes
        p["bhar_nav_only"] = (P_e / N_x - P_e / N_s) * 100  # phantom from NAV
        # Actual BHAR
        p["bhar_actual"] = (P_x / N_x - P_e / N_s) * 100

    bhar_price_s = ev_stats([p["bhar_price_only"] for p in picks])
    bhar_nav_s = ev_stats([p["bhar_nav_only"] for p in picks])
    bhar_actual_s = ev_stats([p["bhar_actual"] for p in picks])

    print(f"  Actual BHAR:              mean={bhar_actual_s['ev']:+.3f}%")
    print(f"  Price-only BHAR (cap):    mean={bhar_price_s['ev']:+.3f}%  ← what retail captures")
    print(f"  NAV-only BHAR (phantom):  mean={bhar_nav_s['ev']:+.3f}%  ← phantom, not capturable")
    print(f"  Sum (price+nav):          mean={bhar_price_s['ev'] + bhar_nav_s['ev']:+.3f}%  (should ≈ actual)")
    print(f"  Cross-term:               mean={bhar_actual_s['ev'] - (bhar_price_s['ev'] + bhar_nav_s['ev']):+.3f}%")

    # ---- Yearly breakdown of phantom alpha ----
    print(f"\n{'=' * 78}")
    print("YEARLY: BHAR vs Raw EV vs Phantom (NAV-only)")
    print(f"{'=' * 78}")
    print(f"{'year':<6} {'n':>5} {'BHAR%':>8} {'Raw%':>8} {'Phantom%':>10} {'Capturable%':>12}")
    for yr in range(2015, 2027):
        yr_picks = [p for p in picks if p["signal_date"][:4] == str(yr)]
        if not yr_picks:
            continue
        bh = ev_stats([p["bhar"] for p in yr_picks])
        rw = ev_stats([p["raw"] for p in yr_picks])
        ph = ev_stats([p["bhar_nav_only"] for p in yr_picks])
        cp = ev_stats([p["bhar_price_only"] for p in yr_picks])
        print(f"{yr:<6} {len(yr_picks):>5} {bh['ev']:>+8} {rw['ev']:>+8} {ph['ev']:>+10} {cp['ev']:>+12}")

    # ---- FINAL VERDICT ----
    print(f"\n{'=' * 78}")
    print("FINAL VERDICT (BHAR-vs-Retail lens)")
    print(f"{'=' * 78}")
    print(f"  BHAR (corrected):     {bh_s['ev']:+.3f}% gross  {bh_s['ev'] - ETF_COST:+.3f}% net")
    print(f"  Raw EV (retail):      {rw_s['ev']:+.3f}% gross  {rw_s['ev'] - ETF_COST:+.3f}% net")
    print(f"  Phantom (NAV-only):   {bhar_nav_s['ev']:+.3f}%")
    print(f"  Capturable (price-only): {bhar_price_s['ev']:+.3f}%")
    print()
    print(f"  If edge-confirmed is based on BHAR ({bh_s['ev']:+.3f}%) but retail only")
    print(f"  captures raw_ev ({rw_s['ev']:+.3f}%), the gap is {bh_s['ev'] - rw_s['ev']:+.3f}%.")
    if rw_s["ev"] - ETF_COST > 0 and raw_dt["p_one_sided"] < 0.05:
        print(f"  → Raw EV is net positive AND significant → edge IS capturable")
        print(f"    BHAR may overstate but retail return still positive")
    elif rw_s["ev"] - ETF_COST > 0:
        print(f"  → Raw EV net positive but day_t={raw_dt['t']} not significant enough")
        print(f"    Edge may not be reliably capturable by retail")
    else:
        print(f"  → Raw EV net NEGATIVE → edge NOT capturable by retail")
        print(f"    BHAR is phantom alpha (discount convergence via NAV drop)")


if __name__ == "__main__":
    main()
