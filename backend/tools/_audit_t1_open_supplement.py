# -*- coding: utf-8 -*-
"""Supplementary: walk-forward + 2023-2026 fresh BHAR + split by entry discount."""

import json
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt

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


def build_picks(etf_data, calendar, threshold=-0.3, hold_days=1, date_lo=None, date_hi=None):
    date_idx = {d: i for i, d in enumerate(calendar)}
    exit_offset = 1 + hold_days
    picks = []
    for code, days in etf_data.items():
        for d, b in days.items():
            if date_lo and d < date_lo:
                continue
            if date_hi and d > date_hi:
                continue
            nav_T = b.get("nav")
            close_T = b.get("close")
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
            entry = t1.get("open")
            exit_close = ex.get("close")
            nav_T1 = t1.get("nav")
            nav_exit = ex.get("nav")
            if None in (entry, exit_close, nav_T1, nav_exit):
                continue
            if entry <= 0 or exit_close <= 0 or nav_T1 <= 0 or nav_exit <= 0:
                continue
            if is_yizi_etf_proxy(entry, close_T):
                continue
            picks.append(
                {
                    "code": code,
                    "signal_date": d,
                    "zt_date": d,
                    "discount_t": disc,
                    "nav_T": nav_T,
                    "entry": entry,
                    "nav_T1": nav_T1,
                    "exit_close": exit_close,
                    "nav_exit": nav_exit,
                }
            )
    return picks


def norm_sf_positive(t):
    return 0.5 * (1 - erf(t / sqrt(2)))


def day_paired_t(picks, ret_fn):
    by_date = defaultdict(list)
    for p in picks:
        r = ret_fn(p)
        if r is not None:
            by_date[p["signal_date"]].append(r)
    day_means = [sum(rs) / len(rs) for rs in by_date.values() if rs]
    n = len(day_means)
    if n == 0:
        return {"n_days": 0, "mean": 0, "t": 0, "p": 1.0}
    mean = sum(day_means) / n
    std = statistics.pstdev(day_means) if n > 1 else 0
    se = std / sqrt(n) if n > 0 else 0
    t = mean / se if se > 0 else 0
    p = norm_sf_positive(t)
    return {"n_days": n, "mean": round(mean, 4), "t": round(t, 2), "p": round(p, 8), "std": round(std, 4)}


def walk_forward(picks, ret_fn):
    if not picks:
        return {}
    ps = sorted(picks, key=lambda p: p["zt_date"])
    dates = sorted(set(p["zt_date"] for p in ps))
    if len(dates) < 4:
        return {"status": "too_few", "n_dates": len(dates)}
    mid = len(dates) // 2
    train_dates = set(dates[:mid])
    test_dates = set(dates[mid:])
    train_picks = [p for p in ps if p["zt_date"] in train_dates]
    test_picks = [p for p in ps if p["zt_date"] in test_dates]
    return {
        "status": "ok",
        "n_train_dates": len(train_dates),
        "n_test_dates": len(test_dates),
        "train": day_paired_t(train_picks, ret_fn),
        "test": day_paired_t(test_picks, ret_fn),
    }


def bhar_stale(p):
    d_entry = (p["entry"] - p["nav_T"]) / p["nav_T"] * 100
    d_exit = (p["exit_close"] - p["nav_exit"]) / p["nav_exit"] * 100
    return d_exit - d_entry


def bhar_fresh(p):
    d_entry = (p["entry"] - p["nav_T1"]) / p["nav_T1"] * 100
    d_exit = (p["exit_close"] - p["nav_exit"]) / p["nav_exit"] * 100
    return d_exit - d_entry


def bhar_r1(p):
    price_ret = (p["exit_close"] - p["entry"]) / p["entry"] * 100
    nav_ret = (p["nav_exit"] - p["nav_T1"]) / p["nav_T1"] * 100
    return price_ret - nav_ret


def raw_ev(p):
    return (p["exit_close"] - p["entry"]) / p["entry"] * 100


def main():
    etf_data = load_etf_data()
    calendar = build_calendar(etf_data)

    picks_full = build_picks(etf_data, calendar, -0.3, 1)
    n = len(picks_full)
    print(f"Full sample: n={n}")

    # ================================================================
    # Walk-forward: stale vs fresh vs R1
    # ================================================================
    print("\n" + "=" * 78)
    print("WALK-FORWARD OOS: stale vs fresh vs R1")
    print("=" * 78)

    for label, fn in [
        ("BHAR stale (R2)", bhar_stale),
        ("BHAR fresh (nav_T1)", bhar_fresh),
        ("BHAR R1", bhar_r1),
        ("raw EV", raw_ev),
    ]:
        wf = walk_forward(picks_full, fn)
        if wf.get("status") != "ok":
            print(f"  {label}: {wf.get('status')}")
            continue
        tr = wf["train"]
        te = wf["test"]
        # per-pick mean
        rets = [fn(p) for p in picks_full]
        mean_ret = statistics.mean(rets)
        net = mean_ret - ETF_COST
        print(f"\n  {label}:")
        print(f"    full: per-pick={mean_ret:+.4f}% net={net:+.4f}% day_t={day_paired_t(picks_full, fn)['t']}")
        print(f"    train: n_dates={wf['n_train_dates']} mean={tr['mean']:+.4f}% day_t={tr['t']} p={tr['p']}")
        print(f"    test:  n_dates={wf['n_test_dates']} mean={te['mean']:+.4f}% day_t={te['t']} p={te['p']}")
        # Bonferroni ×30 on test p
        p_bonf = min(1.0, te["p"] * 30)
        print(f"    test p Bonf×30={p_bonf:.6f} ({'PASS' if p_bonf < 0.05 else 'FAIL'})")

    # ================================================================
    # 2023-2026: stale vs fresh
    # ================================================================
    print("\n" + "=" * 78)
    print("2023-2026: stale vs fresh vs R1")
    print("=" * 78)

    picks_recent = build_picks(etf_data, calendar, -0.3, 1, date_lo="2023-01-01", date_hi="2026-12-31")
    n_r = len(picks_recent)
    print(f"\n  n={n_r}")

    for label, fn in [
        ("BHAR stale (R2)", bhar_stale),
        ("BHAR fresh (nav_T1)", bhar_fresh),
        ("BHAR R1", bhar_r1),
        ("raw EV", raw_ev),
    ]:
        dt = day_paired_t(picks_recent, fn)
        rets = [fn(p) for p in picks_recent]
        mean_ret = statistics.mean(rets)
        net = mean_ret - ETF_COST
        print(f"  {label:<22}: per-pick={mean_ret:+.4f}% net={net:+.4f}% n_days={dt['n_days']} day_t={dt['t']} p={dt['p']}")

    # ================================================================
    # Split by entry discount: converged vs not-converged at T+1 open
    # ================================================================
    print("\n" + "=" * 78)
    print("SPLIT: entry discount (stale nav_T) < -0.3% vs >= -0.3%")
    print("=" * 78)

    conv_picks = [p for p in picks_full if (p["entry"] - p["nav_T"]) / p["nav_T"] * 100 >= -0.3]
    notconv_picks = [p for p in picks_full if (p["entry"] - p["nav_T"]) / p["nav_T"] * 100 < -0.3]

    print(f"\n  Converged at T+1 open (stale disc >= -0.3%): n={len(conv_picks)}")
    for label, fn in [("BHAR stale", bhar_stale), ("BHAR fresh", bhar_fresh)]:
        dt = day_paired_t(conv_picks, fn)
        rets = [fn(p) for p in conv_picks]
        print(f"    {label}: per-pick={statistics.mean(rets):+.4f}% n_days={dt['n_days']} day_t={dt['t']}")

    print(f"\n  NOT converged at T+1 open (stale disc < -0.3%): n={len(notconv_picks)}")
    for label, fn in [("BHAR stale", bhar_stale), ("BHAR fresh", bhar_fresh)]:
        dt = day_paired_t(notconv_picks, fn)
        rets = [fn(p) for p in notconv_picks]
        print(f"    {label}: per-pick={statistics.mean(rets):+.4f}% n_days={dt['n_days']} day_t={dt['t']}")

    # ================================================================
    # Why day_t is inflated: within-day consistency (stale NAV creates
    # systematic market-direction component)
    # ================================================================
    print("\n" + "=" * 78)
    print("WHY day_t inflated: stale NAV adds systematic market-direction component")
    print("=" * 78)

    # Compute day-mean std for stale vs fresh
    stale_day_means = []
    fresh_day_means = []
    stale_by_date = defaultdict(list)
    fresh_by_date = defaultdict(list)
    for p in picks_full:
        stale_by_date[p["signal_date"]].append(bhar_stale(p))
        fresh_by_date[p["signal_date"]].append(bhar_fresh(p))
    stale_day_means = [sum(rs) / len(rs) for rs in stale_by_date.values() if rs]
    fresh_day_means = [sum(rs) / len(rs) for rs in fresh_by_date.values() if rs]

    print(f"  stale day-means: std={statistics.pstdev(stale_day_means):.4f}% mean={statistics.mean(stale_day_means):.4f}%")
    print(f"  fresh day-means: std={statistics.pstdev(fresh_day_means):.4f}% mean={statistics.mean(fresh_day_means):.4f}%")
    print(f"  -> stale std {'<' if statistics.pstdev(stale_day_means) < statistics.pstdev(fresh_day_means) else '>'} fresh std")
    print(
        f"  -> stale NAV {'reduces' if statistics.pstdev(stale_day_means) < statistics.pstdev(fresh_day_means) else 'increases'} day-mean dispersion -> {'inflates' if statistics.pstdev(stale_day_means) < statistics.pstdev(fresh_day_means) else 'deflates'} day_t"
    )

    # The bias adds a market-direction term to every pick on the same day.
    # Since all picks on day D share the same nav_overnight_gap, the bias
    # is the same for all -> reduces within-day variance but is spurious.
    # Check: per-pick std (cross-sectional dispersion)
    stale_rets = [bhar_stale(p) for p in picks_full]
    fresh_rets = [bhar_fresh(p) for p in picks_full]
    print(f"\n  Per-pick std: stale={statistics.pstdev(stale_rets):.4f}% fresh={statistics.pstdev(fresh_rets):.4f}%")
    print(
        f"  -> stale per-pick std {'<' if statistics.pstdev(stale_rets) < statistics.pstdev(fresh_rets) else '>'} fresh (stale compresses cross-sectional variance)"
    )


if __name__ == "__main__":
    main()
