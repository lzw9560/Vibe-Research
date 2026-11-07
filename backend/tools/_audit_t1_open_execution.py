# -*- coding: utf-8 -*-
"""T+1 open execution feasibility audit — ETF premium edge.

Tests:
1. Overnight discount convergence: T close discount vs T+1 open discount
2. Stale-NAV bias: bhar_corrected uses nav_T (T close) with open_T1 (T+1 morning)
   — market-direction-dependent bias
3. Recompute BHAR with fresh NAV (nav_T1) as entry reference — diagnostic
4. Correlate alpha bias with market direction
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path
from math import sqrt

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
ETF_CACHE = DATA / "etf_premium_cache.json"

ETF_COST = 0.15


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
            nav_T = b.get("nav")
            close_T = b.get("close")
            open_T = b.get("open")  # T open (for price gap analysis)
            if nav_T is None or nav_T <= 0 or close_T is None:
                continue
            disc = (close_T - nav_T) / nav_T * 100
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
            entry = t1.get("open")  # T+1 open price
            t1_close = t1.get("close")  # T+1 close price
            exit_close = ex.get("close")  # T+k close price
            nav_T1 = t1.get("nav")  # T+1 close NAV
            nav_exit = ex.get("nav")  # T+k close NAV
            if None in (entry, t1_close, exit_close, nav_T1, nav_exit):
                continue
            if entry <= 0 or t1_close <= 0 or exit_close <= 0 or nav_T1 <= 0 or nav_exit <= 0:
                continue
            if is_yizi_etf_proxy(entry, close_T):
                continue
            picks.append(
                {
                    "code": code,
                    "signal_date": d,
                    "discount_t": disc,
                    "close_T": close_T,
                    "open_T": open_T,
                    "nav_T": nav_T,
                    "entry": entry,  # T+1 open
                    "t1_close": t1_close,  # T+1 close
                    "nav_T1": nav_T1,  # T+1 close NAV
                    "exit_close": exit_close,
                    "nav_exit": nav_exit,
                }
            )
    return picks


def pct(x):
    return f"{x:+.4f}%"


def main():
    etf_data = load_etf_data()
    calendar = build_calendar(etf_data)
    print(f"ETFs: {len(etf_data)}, calendar: {calendar[0]} ~ {calendar[-1]} ({len(calendar)} dates)")

    picks = build_picks(etf_data, calendar, -0.3, hold_days=1)
    print(f"Picks (disc<-0.3%, hold 1d): n={len(picks)}")

    # ================================================================
    # TEST 1: Overnight discount convergence
    # ================================================================
    print("\n" + "=" * 78)
    print("TEST 1: Overnight discount convergence (T close -> T+1 open)")
    print("=" * 78)

    discount_t_list = []  # signal discount (T close)
    discount_t1_stale = []  # entry discount using stale nav_T: (open_T1 - nav_T)/nav_T
    overnight_price_gap = []  # (open_T1 - close_T)/close_T
    nav_overnight_gap = []  # (nav_T1 - nav_T)/nav_T — market direction proxy

    for p in picks:
        dt = p["discount_t"]
        d_entry_stale = (p["entry"] - p["nav_T"]) / p["nav_T"] * 100
        gap = (p["entry"] - p["close_T"]) / p["close_T"] * 100
        nav_gap = (p["nav_T1"] - p["nav_T"]) / p["nav_T"] * 100
        discount_t_list.append(dt)
        discount_t1_stale.append(d_entry_stale)
        overnight_price_gap.append(gap)
        nav_overnight_gap.append(nav_gap)

    n = len(picks)
    print(f"\n  n={n}")
    print(f"\n  Signal discount (T close, disc_t):")
    print(
        f"    mean={statistics.mean(discount_t_list):.4f}% "
        f"median={statistics.median(discount_t_list):.4f}% "
        f"p10={sorted(discount_t_list)[n // 10]:.4f}% "
        f"p90={sorted(discount_t_list)[n * 9 // 10]:.4f}%"
    )

    print(f"\n  Entry discount (T+1 open, stale nav_T): (open_T1 - nav_T)/nav_T")
    print(
        f"    mean={statistics.mean(discount_t1_stale):.4f}% "
        f"median={statistics.median(discount_t1_stale):.4f}% "
        f"p10={sorted(discount_t1_stale)[n // 10]:.4f}% "
        f"p90={sorted(discount_t1_stale)[n * 9 // 10]:.4f}%"
    )

    overnight_convergence = [discount_t1_stale[i] - discount_t_list[i] for i in range(n)]
    print(f"\n  Overnight convergence (d_entry_stale - disc_t):")
    print(f"    mean={statistics.mean(overnight_convergence):.4f}% median={statistics.median(overnight_convergence):.4f}%")
    print(f"    -> positive = discount narrowed overnight (price gapped toward NAV)")

    # How many picks still have discount < -0.3% at T+1 open (stale NAV)?
    still_discount = sum(1 for d in discount_t1_stale if d < -0.3)
    print(f"\n  Picks where T+1 open discount (stale nav_T) still < -0.3%: {still_discount}/{n} ({still_discount / n * 100:.1f}%)")
    print(
        f"  Picks where T+1 open discount (stale nav_T) >= -0.3% (converged): "
        f"{n - still_discount}/{n} ({(n - still_discount) / n * 100:.1f}%)"
    )

    # Overnight price gap
    print(f"\n  Overnight price gap (open_T1 - close_T)/close_T:")
    print(f"    mean={statistics.mean(overnight_price_gap):.4f}% median={statistics.median(overnight_price_gap):.4f}%")
    gap_up = sum(1 for g in overnight_price_gap if g > 0)
    print(f"    gap_up (positive): {gap_up}/{n} ({gap_up / n * 100:.1f}%)")
    print(f"    gap_down (negative): {n - gap_up}/{n} ({(n - gap_up) / n * 100:.1f}%)")

    # ================================================================
    # TEST 2: Stale-NAV bias in BHAR corrected
    # ================================================================
    print("\n" + "=" * 78)
    print("TEST 2: Stale-NAV bias — bhar_corrected uses nav_T with open_T1")
    print("=" * 78)
    print("d_entry_stale = (open_T1 - nav_T)/nav_T   [Round 2 uses this]")
    print("d_entry_fresh = (open_T1 - nav_T1)/nav_T1 [diagnostic: T+1 close NAV]")
    print("d_exit = (exit_close - nav_exit)/nav_exit  [same for both]")
    print()

    bhar_stale_list = []  # alpha using stale nav_T (Round 2 corrected)
    bhar_fresh_list = []  # alpha using fresh nav_T1 (diagnostic)
    bhar_r1_list = []  # Round 1 BHAR (price_ret - nav_ret)
    raw_ev_list = []  # raw P&L
    bias_list = []  # bhar_stale - bhar_fresh

    for p in picks:
        d_entry_stale = (p["entry"] - p["nav_T"]) / p["nav_T"] * 100
        d_entry_fresh = (p["entry"] - p["nav_T1"]) / p["nav_T1"] * 100
        d_exit = (p["exit_close"] - p["nav_exit"]) / p["nav_exit"] * 100

        alpha_stale = d_exit - d_entry_stale
        alpha_fresh = d_exit - d_entry_fresh

        price_ret = (p["exit_close"] - p["entry"]) / p["entry"] * 100
        nav_ret = (p["nav_exit"] - p["nav_T1"]) / p["nav_T1"] * 100
        bhar_r1 = price_ret - nav_ret

        raw = (p["exit_close"] - p["entry"]) / p["entry"] * 100

        bhar_stale_list.append(alpha_stale)
        bhar_fresh_list.append(alpha_fresh)
        bhar_r1_list.append(bhar_r1)
        raw_ev_list.append(raw)
        bias_list.append(alpha_stale - alpha_fresh)

    print(
        f"  BHAR corrected (stale nav_T, Round 2):  "
        f"mean={statistics.mean(bhar_stale_list):.4f}% "
        f"std={statistics.pstdev(bhar_stale_list):.4f}%"
    )
    print(
        f"  BHAR fresh (nav_T1, diagnostic):         "
        f"mean={statistics.mean(bhar_fresh_list):.4f}% "
        f"std={statistics.pstdev(bhar_fresh_list):.4f}%"
    )
    print(f"  BHAR R1 (price_ret - nav_ret, Round 1):  mean={statistics.mean(bhar_r1_list):.4f}%")
    print(f"  raw EV (retail P&L):                     mean={statistics.mean(raw_ev_list):.4f}%")
    print()
    print(f"  Stale-NAV bias (stale - fresh):          mean={statistics.mean(bias_list):.4f}% median={statistics.median(bias_list):.4f}%")
    print(f"  -> positive bias = stale NAV INFLATES alpha")
    print(f"  -> negative bias = stale NAV DEFLATES alpha")

    # ================================================================
    # TEST 3: Correlate bias with market direction (nav overnight gap)
    # ================================================================
    print("\n" + "=" * 78)
    print("TEST 3: Correlate stale-NAV bias with market direction")
    print("=" * 78)

    # Split picks by market direction
    up_picks = [(b, ng) for b, ng in zip(bias_list, nav_overnight_gap) if ng > 0]
    dn_picks = [(b, ng) for b, ng in zip(bias_list, nav_overnight_gap) if ng <= 0]

    if up_picks:
        up_bias = [b for b, _ in up_picks]
        print(f"\n  Market UP overnight (nav_T1 > nav_T): n={len(up_picks)}")
        print(
            f"    stale-NAV bias mean={statistics.mean(up_bias):.4f}% "
            f"(stale NAV {'inflates' if statistics.mean(up_bias) > 0 else 'deflates'} alpha)"
        )
        # fresh vs stale for up-market
        up_stale = [bhar_stale_list[i] for i, ng in enumerate(nav_overnight_gap) if ng > 0]
        up_fresh = [bhar_fresh_list[i] for i, ng in enumerate(nav_overnight_gap) if ng > 0]
        print(f"    BHAR stale={statistics.mean(up_stale):.4f}% vs fresh={statistics.mean(up_fresh):.4f}%")

    if dn_picks:
        dn_bias = [b for b, _ in dn_picks]
        print(f"\n  Market DOWN overnight (nav_T1 <= nav_T): n={len(dn_picks)}")
        print(
            f"    stale-NAV bias mean={statistics.mean(dn_bias):.4f}% "
            f"(stale NAV {'inflates' if statistics.mean(dn_bias) > 0 else 'deflates'} alpha)"
        )
        dn_stale = [bhar_stale_list[i] for i, ng in enumerate(nav_overnight_gap) if ng <= 0]
        dn_fresh = [bhar_fresh_list[i] for i, ng in enumerate(nav_overnight_gap) if ng <= 0]
        print(f"    BHAR stale={statistics.mean(dn_stale):.4f}% vs fresh={statistics.mean(dn_fresh):.4f}%")

    # Pearson correlation
    mean_b = statistics.mean(bias_list)
    mean_ng = statistics.mean(nav_overnight_gap)
    num = sum((bias_list[i] - mean_b) * (nav_overnight_gap[i] - mean_ng) for i in range(n))
    den_b = sqrt(sum((b - mean_b) ** 2 for b in bias_list))
    den_ng = sqrt(sum((ng - mean_ng) ** 2 for ng in nav_overnight_gap))
    corr = num / (den_b * den_ng) if den_b > 0 and den_ng > 0 else 0
    print(f"\n  Pearson corr(bias, nav_overnight_gap) = {corr:.4f}")
    print(f"  -> negative corr = stale NAV inflates alpha when market drops (confirms bias)")

    # ================================================================
    # TEST 4: Day-paired t on all three BHAR calibers
    # ================================================================
    print("\n" + "=" * 78)
    print("TEST 4: Day-paired t-test comparison (stale vs fresh vs R1)")
    print("=" * 78)

    def day_t(rets_by_date):
        day_means = [sum(rs) / len(rs) for rs in rets_by_date.values() if rs]
        m = len(day_means)
        if m == 0:
            return {"n_days": 0, "mean": 0, "t": 0}
        mean = sum(day_means) / m
        std = statistics.pstdev(day_means) if m > 1 else 0
        se = std / sqrt(m) if m > 0 else 0
        t = mean / se if se > 0 else 0
        return {"n_days": m, "mean": round(mean, 4), "t": round(t, 2)}

    for label, rets in [
        ("BHAR stale (Round 2)", bhar_stale_list),
        ("BHAR fresh (nav_T1)", bhar_fresh_list),
        ("BHAR R1 (Round 1)", bhar_r1_list),
        ("raw EV", raw_ev_list),
    ]:
        by_date = defaultdict(list)
        for p, r in zip(picks, rets):
            by_date[p["signal_date"]].append(r)
        dt = day_t(by_date)
        net = statistics.mean(rets) - ETF_COST
        print(f"  {label:<22}: per-pick={statistics.mean(rets):+.4f}% net={net:+.4f}% n_days={dt['n_days']} day_t={dt['t']}")

    # ================================================================
    # TEST 5: The REAL question — is T+1 open discount still capturable?
    # ================================================================
    print("\n" + "=" * 78)
    print("TEST 5: TRUE discount at T+1 open (using nav_T1 as iNAV proxy)")
    print("=" * 78)
    print("If iNAV at T+1 open ≈ nav_T1 (T+1 close NAV), then:")
    print("  true_discount_t1_open = (open_T1 - nav_T1)/nav_T1")
    print()

    true_disc_t1 = [(p["entry"] - p["nav_T1"]) / p["nav_T1"] * 100 for p in picks]
    print(f"  TRUE discount at T+1 open (nav_T1 proxy):")
    print(f"    mean={statistics.mean(true_disc_t1):.4f}% median={statistics.median(true_disc_t1):.4f}%")
    still_disc_true = sum(1 for d in true_disc_t1 if d < -0.3)
    print(f"    still < -0.3%: {still_disc_true}/{n} ({still_disc_true / n * 100:.1f}%)")
    print(f"    >= -0.3% (converged): {n - still_disc_true}/{n} ({(n - still_disc_true) / n * 100:.1f}%)")

    # alpha from TRUE entry discount to exit discount
    true_alpha = []
    for p in picks:
        d_entry_true = (p["entry"] - p["nav_T1"]) / p["nav_T1"] * 100
        d_exit = (p["exit_close"] - p["nav_exit"]) / p["nav_exit"] * 100
        true_alpha.append(d_exit - d_entry_true)
    print(f"\n  TRUE alpha (entry nav_T1 -> exit nav_exit): mean={statistics.mean(true_alpha):.4f}%")
    by_date = defaultdict(list)
    for p, r in zip(picks, true_alpha):
        by_date[p["signal_date"]].append(r)
    dt = day_t(by_date)
    print(f"    n_days={dt['n_days']} day_t={dt['t']} net={statistics.mean(true_alpha) - ETF_COST:+.4f}%")

    # ================================================================
    # TEST 6: entry discount stale vs fresh — distribution
    # ================================================================
    print("\n" + "=" * 78)
    print("TEST 6: Entry discount stale vs fresh — which drives the edge?")
    print("=" * 78)
    d_entry_stale_all = [(p["entry"] - p["nav_T"]) / p["nav_T"] * 100 for p in picks]
    d_entry_fresh_all = [(p["entry"] - p["nav_T1"]) / p["nav_T1"] * 100 for p in picks]
    print(f"  d_entry stale (nav_T):   mean={statistics.mean(d_entry_stale_all):.4f}% median={statistics.median(d_entry_stale_all):.4f}%")
    print(f"  d_entry fresh (nav_T1):  mean={statistics.mean(d_entry_fresh_all):.4f}% median={statistics.median(d_entry_fresh_all):.4f}%")
    print(f"  signal discount (nav_T): mean={statistics.mean(discount_t_list):.4f}% median={statistics.median(discount_t_list):.4f}%")
    print()
    print(f"  -> If d_entry_fresh >> d_entry_stale (less negative), stale NAV")
    print(f"     shows bigger entry discount than reality -> inflates convergence alpha")


if __name__ == "__main__":
    main()
