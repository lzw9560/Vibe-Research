# -*- coding: utf-8 -*-
"""T+1 open entry false-negative audit — 除权除息 (dividend ex-right).

HYPOTHESIS: ex-date T is the key event. The script uses T+1 open entry
("T close 已除权, 散户 T+1 才能买" — but this is WRONG: you CAN buy on
the ex-date T at the adjusted price). T+1 open misses the ex-date
fill-rights (填权) dynamics. T open or T close entry may be better.

Tests 3 entry timings:
  A) T open   — buy at ex-date open (adjusted price, captures full 填权)
  B) T close  — buy at ex-date close
  C) T+1 open — original script's entry (conservative — misses ex-date)

For each, compute BHAR vs 上证综指 and day-paired t. Compare verdicts.

NOTE: baostock kline is 前复权 (forward-adjusted). On ex-date, the
adjustment factor applies to ALL bars equally (pre and post ex). So the
return from T open to T+k close is adjustment-invariant (the script's
own comment confirms this: "前复权对除权日后的收益无影响").
"""

import json
import sqlite3
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
KLINE_DB = DATA / "baostock_kline_cache.db"
DIV_CACHE = DATA / "dividend_events_cache.json"
INDEX_CACHE = DATA / "index_ohlc_cache.json"

COST = 0.003
ALPHA = 0.05


def load_kline_db():
    conn = sqlite3.connect(str(KLINE_DB))
    code_map = {}
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or not bars:
            continue
        dmap = {}
        for b in bars:
            d = b.get("date")
            if d:
                dmap[d] = b
        if dmap:
            code_map[code] = dmap
    conn.close()
    return code_map


def load_index():
    with open(INDEX_CACHE) as f:
        raw = json.load(f)
    bars = raw.get("sh.000001", [])
    idx_map = {b["date"]: b for b in bars if "date" in b}
    calendar = sorted(idx_map.keys())
    return idx_map, calendar


def load_dividend_events():
    with open(DIV_CACHE) as f:
        return json.load(f)


def is_locked_bar(bar):
    o = bar.get("open")
    h = bar.get("high")
    l = bar.get("low")
    if o is None or h is None or l is None or o <= 0:
        return False
    return abs(o - h) / o < 0.001 and abs(o - l) / o < 0.001


def build_dividend_picks(events, code_map, calendar, index_map):
    """Build picks for dividend ex-date. Store T bar + T+1..T+5 bars."""
    date_idx = {d: i for i, d in enumerate(calendar)}
    picks = []

    for ev in events:
        code = ev["code"]
        ex_date = ev["ex_date"]
        d_idx = date_idx.get(ex_date)
        if d_idx is None or d_idx + 6 >= len(calendar):
            continue

        dmap = code_map.get(code)
        if not dmap:
            continue

        t_bar = dmap.get(ex_date)
        if t_bar is None:
            continue
        t_open = t_bar.get("open")
        t_close = t_bar.get("close")
        if t_open is None or t_close is None or t_open <= 0 or t_close <= 0:
            continue
        if is_locked_bar(t_bar):
            continue

        t1_date = calendar[d_idx + 1]
        t3_date = calendar[d_idx + 3]
        t5_date = calendar[d_idx + 5]
        t1_bar = dmap.get(t1_date)
        t3_bar = dmap.get(t3_date)
        t5_bar = dmap.get(t5_date)
        if None in (t1_bar, t3_bar, t5_bar):
            continue

        t1_open = t1_bar.get("open")
        t1_close = t1_bar.get("close")
        t3_close = t3_bar.get("close")
        t5_close = t5_bar.get("close")
        if None in (t1_open, t1_close, t3_close, t5_close):
            continue
        if t1_open <= 0 or t1_close <= 0 or t3_close <= 0 or t5_close <= 0:
            continue
        if is_locked_bar(t1_bar):
            continue

        # Index bars
        i_t = index_map.get(ex_date)
        i_t1 = index_map.get(t1_date)
        i_t3 = index_map.get(t3_date)
        i_t5 = index_map.get(t5_date)
        if None in (i_t, i_t1, i_t3, i_t5):
            continue
        i_t_open = i_t.get("open")
        i_t_close = i_t.get("close")
        i_t1_open = i_t1.get("open")
        i_t1_close = i_t1.get("close")
        i_t3_close = i_t3.get("close")
        i_t5_close = i_t5.get("close")
        if None in (i_t_open, i_t_close, i_t1_open, i_t1_close, i_t3_close, i_t5_close):
            continue
        if i_t_open <= 0 or i_t_close <= 0 or i_t1_open <= 0:
            continue

        picks.append(
            {
                "code": code,
                "ex_date": ex_date,
                "t_open": t_open,
                "t_close": t_close,
                "t1_open": t1_open,
                "t1_close": t1_close,
                "t3_close": t3_close,
                "t5_close": t5_close,
                "i_t_open": i_t_open,
                "i_t_close": i_t_close,
                "i_t1_open": i_t1_open,
                "i_t1_close": i_t1_close,
                "i_t3_close": i_t3_close,
                "i_t5_close": i_t5_close,
            }
        )
    return picks


def ev_stats(rets):
    n = len(rets)
    if n == 0:
        return {"n": 0, "ev": 0.0, "std": 0.0, "t": 0.0, "wr": 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    wr = sum(1 for x in rets if x > 0) / n
    return {"n": n, "ev": round(mean, 4), "std": round(std, 4), "t": round(t, 2), "wr": round(wr * 100, 1)}


def norm_sf_positive(t):
    return 0.5 * (1 - erf(t / sqrt(2)))


def day_paired_t(rets_by_date):
    day_means = []
    for d, rs in rets_by_date.items():
        if rs:
            day_means.append(sum(rs) / len(rs))
    n = len(day_means)
    if n == 0:
        return {"n_days": 0, "mean": 0.0, "t": 0.0, "p": 1.0}
    mean = sum(day_means) / n
    std = statistics.pstdev(day_means) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = norm_sf_positive(t)
    return {"n_days": n, "mean": round(mean, 4), "t": round(t, 2), "p": round(p, 8)}


def bonferroni_p(p_raw, n_tests):
    return min(1.0, p_raw * n_tests)


def analyze_entry(picks, label, entry_fn, exit_fn, bhar_fn):
    if not picks:
        print(f"  {label}: no picks")
        return None

    raw_rets = []
    bhar_rets = []
    raw_by_date = defaultdict(list)
    bhar_by_date = defaultdict(list)

    for p in picks:
        e = entry_fn(p)
        x = exit_fn(p)
        if e is None or x is None or e <= 0 or x <= 0:
            continue
        raw = (x - e) / e * 100
        raw_rets.append(raw)
        raw_by_date[p["ex_date"]].append(raw)
        b = bhar_fn(p, e, x)
        if b is not None:
            bhar_rets.append(b)
            bhar_by_date[p["ex_date"]].append(b)

    if not raw_rets:
        print(f"  {label}: no valid returns")
        return None

    raw_s = ev_stats(raw_rets)
    raw_dt = day_paired_t(raw_by_date)
    bhar_s = ev_stats(bhar_rets) if bhar_rets else {"n": 0, "ev": 0, "t": 0, "wr": 0}
    bhar_dt = day_paired_t(bhar_by_date) if bhar_rets else {"n_days": 0, "t": 0, "p": 1.0}

    raw_net = raw_s["ev"] - COST * 100
    bhar_net = bhar_s["ev"] - COST * 100
    p_bonf = bonferroni_p(bhar_dt["p"], 8)  # ×4 strategies × 2 windows

    print(f"\n  {label}:")
    print(f"    raw EV:  gross={raw_s['ev']:+.4f}% net={raw_net:+.4f}% WR={raw_s['wr']}% t={raw_s['t']} n={raw_s['n']}")
    print(f"    raw day-t: n_days={raw_dt['n_days']} t={raw_dt['t']} p={raw_dt['p']}")
    print(f"    BHAR:    gross={bhar_s['ev']:+.4f}% net={bhar_net:+.4f}% WR={bhar_s['wr']}% t={bhar_s['t']}")
    print(f"    BHAR day-t: n_days={bhar_dt['n_days']} t={bhar_dt['t']} p={bhar_dt['p']} Bonf×8={p_bonf:.6f}")
    print(f"    beta_leak = raw-BHAR = {raw_s['ev'] - bhar_s['ev']:+.4f}%")

    if bhar_s["ev"] < 0:
        v = "FALSIFIED (BHAR<0)"
    elif bhar_dt["n_days"] < 60:
        v = "UNDERPOWERED"
    elif p_bonf >= ALPHA:
        v = "FALSIFIED (Bonf fail)"
    elif bhar_net <= 0:
        v = "FALSIFIED (net<=0)"
    else:
        v = "survives"
    print(f"    verdict: {v}")
    return {
        "label": label,
        "raw_ev": raw_s["ev"],
        "bhar_ev": bhar_s["ev"],
        "bhar_net": bhar_net,
        "bhar_t": bhar_dt["t"],
        "bhar_p": bhar_dt["p"],
        "p_bonf": p_bonf,
        "verdict": v,
        "n": raw_s["n"],
        "n_days": bhar_dt["n_days"],
    }


def main():
    print("=" * 78)
    print("T+1 OPEN ENTRY FALSE-NEGATIVE AUDIT — 除权除息 (dividend ex-right)")
    print("=" * 78)
    print("HYPOTHESIS: ex-date T is key event. T+1 open misses ex-date dynamics.")
    print("T open (adjusted price) may capture 填权 drift better.")
    print()

    code_map = load_kline_db()
    index_map, calendar = load_index()
    events = load_dividend_events()
    print(f"[data] kline: {len(code_map)} codes | index: {len(calendar)} days")
    print(f"[data] dividend events: {len(events)}")

    picks = build_dividend_picks(events, code_map, calendar, index_map)
    n_dates = len(set(p["ex_date"] for p in picks))
    ex_dates = sorted(set(p["ex_date"] for p in picks))
    print(f"[build] dividend picks: {len(picks)} across {n_dates} days ({ex_dates[0]} ~ {ex_dates[-1]})")

    if not picks:
        print("[ERROR] no picks")
        return

    results = []

    # --- Entry A: T open → T+3 close (ex-date open, 3-day hold) ---
    print("\n--- Entry A: T open → T+3 close (ex-date open, captures full 填权) ---")
    r = analyze_entry(
        picks,
        "T_open→T3_close",
        entry_fn=lambda p: p["t_open"],
        exit_fn=lambda p: p["t3_close"],
        bhar_fn=lambda p, e, x: ((x - e) / e * 100) - ((p["i_t3_close"] - p["i_t_open"]) / p["i_t_open"] * 100),
    )
    if r:
        results.append(r)

    # --- Entry A5: T open → T+5 close (ex-date open, 5-day hold) ---
    print("\n--- Entry A5: T open → T+5 close (ex-date open, 5-day hold) ---")
    r = analyze_entry(
        picks,
        "T_open→T5_close",
        entry_fn=lambda p: p["t_open"],
        exit_fn=lambda p: p["t5_close"],
        bhar_fn=lambda p, e, x: ((x - e) / e * 100) - ((p["i_t5_close"] - p["i_t_open"]) / p["i_t_open"] * 100),
    )
    if r:
        results.append(r)

    # --- Entry B: T close → T+3 close (ex-date close, 3-day hold) ---
    print("\n--- Entry B: T close → T+3 close (ex-date close) ---")
    r = analyze_entry(
        picks,
        "T_close→T3_close",
        entry_fn=lambda p: p["t_close"],
        exit_fn=lambda p: p["t3_close"],
        bhar_fn=lambda p, e, x: ((x - e) / e * 100) - ((p["i_t3_close"] - p["i_t_close"]) / p["i_t_close"] * 100),
    )
    if r:
        results.append(r)

    # --- Entry C: T+1 open → T+3 close (ORIGINAL script entry) ---
    print("\n--- Entry C: T+1 open → T+3 close (ORIGINAL script entry) ---")
    r = analyze_entry(
        picks,
        "T1_open→T3_close",
        entry_fn=lambda p: p["t1_open"],
        exit_fn=lambda p: p["t3_close"],
        bhar_fn=lambda p, e, x: ((x - e) / e * 100) - ((p["i_t3_close"] - p["i_t1_open"]) / p["i_t1_open"] * 100),
    )
    if r:
        results.append(r)

    # --- Entry C5: T+1 open → T+5 close (ORIGINAL, 4-day hold) ---
    print("\n--- Entry C5: T+1 open → T+5 close (ORIGINAL, 4-day hold) ---")
    r = analyze_entry(
        picks,
        "T1_open→T5_close",
        entry_fn=lambda p: p["t1_open"],
        exit_fn=lambda p: p["t5_close"],
        bhar_fn=lambda p, e, x: ((x - e) / e * 100) - ((p["i_t5_close"] - p["i_t1_open"]) / p["i_t1_open"] * 100),
    )
    if r:
        results.append(r)

    # --- Entry D: T+1 close → T+3 close (alternative) ---
    print("\n--- Entry D: T+1 close → T+3 close (alternative) ---")
    r = analyze_entry(
        picks,
        "T1_close→T3_close",
        entry_fn=lambda p: p["t1_close"],
        exit_fn=lambda p: p["t3_close"],
        bhar_fn=lambda p, e, x: ((x - e) / e * 100) - ((p["i_t3_close"] - p["i_t1_close"]) / p["i_t1_close"] * 100),
    )
    if r:
        results.append(r)

    # ================================================================
    # SUMMARY
    # ================================================================
    print("\n" + "=" * 78)
    print("SUMMARY: entry timing comparison (BHAR net%)")
    print("=" * 78)
    print(f"{'entry→exit':<24} {'BHAR_gross':>10} {'BHAR_net':>9} {'day_t':>7} {'p_bonf':>9} {'verdict'}")
    for r in results:
        print(f"{r['label']:<24} {r['bhar_ev']:>+10.4f} {r['bhar_net']:>+9.4f} {r['bhar_t']:>7} {r['p_bonf']:>9.6f} {r['verdict']}")

    # ================================================================
    # DIAGNOSTIC: overnight gaps
    # ================================================================
    print("\n" + "=" * 78)
    print("DIAGNOSTIC: overnight gaps around ex-date")
    print("=" * 78)

    # T open → T close (ex-date intraday)
    intraday = [(p["t_close"] - p["t_open"]) / p["t_open"] * 100 for p in picks]
    print(f"\n  ex-date intraday (T open → T close):")
    print(f"    mean={statistics.mean(intraday):+.4f}% median={statistics.median(intraday):+.4f}%")

    # T close → T+1 open (overnight after ex-date)
    overnight = [(p["t1_open"] - p["t_close"]) / p["t_close"] * 100 for p in picks]
    print(f"\n  overnight (T close → T+1 open):")
    print(f"    mean={statistics.mean(overnight):+.4f}% median={statistics.median(overnight):+.4f}%")
    gap_up = sum(1 for g in overnight if g > 0)
    print(f"    gap_up: {gap_up}/{len(overnight)} ({gap_up / len(overnight) * 100:.1f}%)")

    # T open → T+1 open (full ex-date to next open)
    full = [(p["t1_open"] - p["t_open"]) / p["t_open"] * 100 for p in picks]
    print(f"\n  full ex-date→next open (T open → T+1 open):")
    print(f"    mean={statistics.mean(full):+.4f}% median={statistics.median(full):+.4f}%")


if __name__ == "__main__":
    main()
