# -*- coding: utf-8 -*-
"""T+1 open entry false-negative audit — 跌停打开 (limit-down open bounce).

HYPOTHESIS: 跌停打开 event is INTRADAY T (board opens during T day).
The bounce happens intraday T (from low to close). T+1 open entry buys
AFTER the bounce, capturing mean reversion instead. T close entry (when
board has opened, close > low) may capture the post-bounce drift.

Tests 3 entry timings for the same events:
  A) T close   — buy at event-day close (board opened, can buy)
  B) T+1 open  — original script's entry (CONSERVATIVE — after bounce)
  C) T+1 close — alternative (captures overnight + T+1 intraday)

For each, compute BHAR vs 上证综指 and day-paired t. Compare verdicts.

T+1 settlement: if buy at T close, earliest sell = T+1 close (1-day hold
from T close = sell T+1 close). If buy T+1 open, earliest sell T+2 close.
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
INDEX_CACHE = DATA / "index_ohlc_cache.json"

COST = 0.003  # 0.3% round-trip
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


def limit_for_code(code, is_st=False):
    if is_st:
        return 0.05
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    if code.startswith(("4", "8")):
        return 0.30
    return 0.10


def build_limit_down_open_picks(code_map, calendar, index_map):
    """跌停打开 events: T day low≈prev_close*(1-limit) AND close>low.

    Store T bar + T+1..T+5 bars + index bars for all entry-timing tests.
    """
    date_idx = {d: i for i, d in enumerate(calendar)}
    picks = []

    for code, dmap in code_map.items():
        bars_sorted = sorted(dmap.values(), key=lambda b: b.get("date", ""))
        if len(bars_sorted) < 2:
            continue
        for i in range(1, len(bars_sorted)):
            b = bars_sorted[i]
            prev = bars_sorted[i - 1]
            prev_close = prev.get("close")
            if prev_close is None or prev_close <= 0:
                continue
            event_date = b.get("date")
            if event_date is None:
                continue
            low = b.get("low")
            close = b.get("close")
            if low is None or close is None or low <= 0:
                continue
            is_st = b.get("isST") == "1"
            limit = limit_for_code(code, is_st)
            lim_down = prev_close * (1 - limit)
            if lim_down <= 0:
                continue
            # 跌停板触及
            if abs(low - lim_down) / lim_down >= 0.005:
                continue
            # 板打开
            if close <= low:
                continue

            di = date_idx.get(event_date)
            if di is None or di + 5 >= len(calendar):
                continue

            t1_date = calendar[di + 1]
            t2_date = calendar[di + 2]
            t5_date = calendar[di + 5]
            t1_bar = dmap.get(t1_date)
            t2_bar = dmap.get(t2_date)
            t5_bar = dmap.get(t5_date)
            if None in (t1_bar, t2_bar, t5_bar):
                continue

            t_close = close  # event day close (board opened)
            t1_open = t1_bar.get("open")
            t1_close = t1_bar.get("close")
            t2_close = t2_bar.get("close")
            t5_close = t5_bar.get("close")
            if None in (t1_open, t1_close, t2_close, t5_close):
                continue
            if t1_open <= 0 or t1_close <= 0 or t2_close <= 0 or t5_close <= 0:
                continue

            # Index bars for BHAR
            i_t = index_map.get(event_date)
            i_t1 = index_map.get(t1_date)
            i_t2 = index_map.get(t2_date)
            i_t5 = index_map.get(t5_date)
            if None in (i_t, i_t1, i_t2, i_t5):
                continue
            i_t_close = i_t.get("close")
            i_t1_open = i_t1.get("open")
            i_t1_close = i_t1.get("close")
            i_t2_close = i_t2.get("close")
            i_t5_close = i_t5.get("close")
            if None in (i_t_close, i_t1_open, i_t1_close, i_t2_close, i_t5_close):
                continue
            if i_t_close <= 0 or i_t1_open <= 0:
                continue

            picks.append(
                {
                    "code": code,
                    "event_date": event_date,
                    "t_close": t_close,
                    "t1_open": t1_open,
                    "t1_close": t1_close,
                    "t2_close": t2_close,
                    "t5_close": t5_close,
                    "i_t_close": i_t_close,
                    "i_t1_open": i_t1_open,
                    "i_t1_close": i_t1_close,
                    "i_t2_close": i_t2_close,
                    "i_t5_close": i_t5_close,
                    "open_degree": (close - low) / low,
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
    """Analyze one entry/exit combo."""
    if not picks:
        print(f"  {label}: no picks")
        return

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
        raw_by_date[p["event_date"]].append(raw)
        b = bhar_fn(p, e, x)
        if b is not None:
            bhar_rets.append(b)
            bhar_by_date[p["event_date"]].append(b)

    if not raw_rets:
        print(f"  {label}: no valid returns")
        return

    raw_s = ev_stats(raw_rets)
    raw_dt = day_paired_t(raw_by_date)
    bhar_s = ev_stats(bhar_rets) if bhar_rets else {"n": 0, "ev": 0, "t": 0, "wr": 0}
    bhar_dt = day_paired_t(bhar_by_date) if bhar_rets else {"n_days": 0, "t": 0, "p": 1.0}

    raw_net = raw_s["ev"] - COST * 100
    bhar_net = bhar_s["ev"] - COST * 100
    p_bonf = bonferroni_p(bhar_dt["p"], 6)  # ×3 strategies × 2 windows

    print(f"\n  {label}:")
    print(f"    raw EV:  gross={raw_s['ev']:+.4f}% net={raw_net:+.4f}% WR={raw_s['wr']}% t={raw_s['t']} n={raw_s['n']}")
    print(f"    raw day-t: n_days={raw_dt['n_days']} t={raw_dt['t']} p={raw_dt['p']}")
    print(f"    BHAR:    gross={bhar_s['ev']:+.4f}% net={bhar_net:+.4f}% WR={bhar_s['wr']}% t={bhar_s['t']}")
    print(f"    BHAR day-t: n_days={bhar_dt['n_days']} t={bhar_dt['t']} p={bhar_dt['p']} Bonf×6={p_bonf:.6f}")
    print(f"    beta_leak = raw-BHAR = {raw_s['ev'] - bhar_s['ev']:+.4f}%")

    # Verdict cascade (simplified)
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
    }


def main():
    print("=" * 78)
    print("T+1 OPEN ENTRY FALSE-NEGATIVE AUDIT — 跌停打开 (limit-down open bounce)")
    print("=" * 78)
    print("HYPOTHESIS: event is intraday T. T+1 open buys AFTER bounce.")
    print("T close entry may capture post-bounce drift better.")
    print()

    code_map = load_kline_db()
    index_map, calendar = load_index()
    print(f"[data] kline: {len(code_map)} codes | index: {len(calendar)} days")

    picks = build_limit_down_open_picks(code_map, calendar, index_map)
    n_dates = len(set(p["event_date"] for p in picks))
    ev_dates = sorted(set(p["event_date"] for p in picks))
    print(f"[build] limit-down-open events: {len(picks)} across {n_dates} days ({ev_dates[0]} ~ {ev_dates[-1]})")

    if not picks:
        print("[ERROR] no picks")
        return

    # ================================================================
    # TEST: 3 entry timings × 2 exit windows
    # ================================================================
    print("\n" + "=" * 78)
    print("ENTRY TIMING COMPARISON")
    print("=" * 78)

    results = []

    # --- Entry A: T close, Exit T+1 close (1-day hold from T close) ---
    print("\n--- Entry A: T close → T+1 close (overnight + T+1 intraday) ---")
    r = analyze_entry(
        picks,
        "T_close→T1_close",
        entry_fn=lambda p: p["t_close"],
        exit_fn=lambda p: p["t1_close"],
        bhar_fn=lambda p, e, x: ((x - e) / e * 100) - ((p["i_t1_close"] - p["i_t_close"]) / p["i_t_close"] * 100),
    )
    if r:
        results.append(r)

    # --- Entry A2: T close, Exit T+2 close (2-day hold) ---
    print("\n--- Entry A2: T close → T+2 close (2-day hold) ---")
    r = analyze_entry(
        picks,
        "T_close→T2_close",
        entry_fn=lambda p: p["t_close"],
        exit_fn=lambda p: p["t2_close"],
        bhar_fn=lambda p, e, x: ((x - e) / e * 100) - ((p["i_t2_close"] - p["i_t_close"]) / p["i_t_close"] * 100),
    )
    if r:
        results.append(r)

    # --- Entry A5: T close, Exit T+5 close (5-day hold) ---
    print("\n--- Entry A5: T close → T+5 close (5-day hold) ---")
    r = analyze_entry(
        picks,
        "T_close→T5_close",
        entry_fn=lambda p: p["t_close"],
        exit_fn=lambda p: p["t5_close"],
        bhar_fn=lambda p, e, x: ((x - e) / e * 100) - ((p["i_t5_close"] - p["i_t_close"]) / p["i_t_close"] * 100),
    )
    if r:
        results.append(r)

    # --- Entry B: T+1 open, Exit T+2 close (ORIGINAL, 1-day hold) ---
    print("\n--- Entry B: T+1 open → T+2 close (ORIGINAL script entry) ---")
    r = analyze_entry(
        picks,
        "T1_open→T2_close",
        entry_fn=lambda p: p["t1_open"],
        exit_fn=lambda p: p["t2_close"],
        bhar_fn=lambda p, e, x: ((x - e) / e * 100) - ((p["i_t2_close"] - p["i_t1_open"]) / p["i_t1_open"] * 100),
    )
    if r:
        results.append(r)

    # --- Entry B5: T+1 open, Exit T+5 close (ORIGINAL, 4-day hold) ---
    print("\n--- Entry B5: T+1 open → T+5 close (ORIGINAL, 4-day hold) ---")
    r = analyze_entry(
        picks,
        "T1_open→T5_close",
        entry_fn=lambda p: p["t1_open"],
        exit_fn=lambda p: p["t5_close"],
        bhar_fn=lambda p, e, x: ((x - e) / e * 100) - ((p["i_t5_close"] - p["i_t1_open"]) / p["i_t1_open"] * 100),
    )
    if r:
        results.append(r)

    # --- Entry C: T+1 close, Exit T+2 close (alternative) ---
    print("\n--- Entry C: T+1 close → T+2 close (alternative) ---")
    r = analyze_entry(
        picks,
        "T1_close→T2_close",
        entry_fn=lambda p: p["t1_close"],
        exit_fn=lambda p: p["t2_close"],
        bhar_fn=lambda p, e, x: ((x - e) / e * 100) - ((p["i_t2_close"] - p["i_t1_close"]) / p["i_t1_close"] * 100),
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
    # KEY DIAGNOSTIC: T close → T+1 open overnight gap
    # ================================================================
    print("\n" + "=" * 78)
    print("DIAGNOSTIC: overnight gap T close → T+1 open")
    print("=" * 78)
    print("If gap is strongly positive, T+1 open entry MISSES the bounce")
    gaps = [(p["t1_open"] - p["t_close"]) / p["t_close"] * 100 for p in picks]
    print(f"  overnight gap (T close → T+1 open):")
    print(f"    mean={statistics.mean(gaps):+.4f}% median={statistics.median(gaps):+.4f}%")
    gap_up = sum(1 for g in gaps if g > 0)
    print(f"    gap_up: {gap_up}/{len(gaps)} ({gap_up / len(gaps) * 100:.1f}%)")

    # The bounce intraday T (low → close)
    print("\n  intraday T bounce (event low → event close):")
    # Need event low — reconstruct from picks
    bounces = [p["open_degree"] * 100 for p in picks]
    print(f"    mean={statistics.mean(bounces):+.4f}% median={statistics.median(bounces):+.4f}%")


if __name__ == "__main__":
    main()
