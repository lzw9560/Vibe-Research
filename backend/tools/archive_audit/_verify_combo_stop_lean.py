# -*- coding: utf-8 -*-
"""Lean verification of combo stop-convergence claim.
Caches per-date top-20 picks ONCE, then computes nostop + all stops from cache.
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vr_paths import resolve_data_dir


DB = resolve_data_dir() / "baostock_kline_cache.db"
COST = 0.004
TOP_N = 20
STOPS = [-0.05, -0.08, -0.10, -0.15]


def board_limit(code: str) -> float:
    c = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    if c.startswith("30") or c.startswith("68"):
        return 0.20
    if c.startswith("8") or c.startswith("4"):
        return 0.30
    return 0.10


def build_and_rank() -> tuple[dict, dict]:
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    by_date: dict = defaultdict(list)
    for code, bj in rows:
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        nb = len(bars)
        if nb < 70:
            continue
        c0 = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
        bl = board_limit(code)
        closes = [0.0] * nb
        opens = [0.0] * nb
        lows = [0.0] * nb
        amts = [0.0] * nb
        issts = ["0"] * nb
        dates_l = [""] * nb
        for j in range(nb):
            b = bars[j]
            dates_l[j] = b.get("date", "")
            closes[j] = float(b.get("close", 0) or 0)
            opens[j] = float(b.get("open", 0) or 0)
            lows[j] = float(b.get("low", 0) or 0)
            amts[j] = float(b.get("amount", 0) or 0)
            issts[j] = str(b.get("isST", "0"))
        for i in range(60, nb - 5):
            prev_c = closes[i - 1]
            c = closes[i]
            amt = amts[i]
            if not prev_c or not c or not amt:
                continue
            if issts[i] not in ("0", "", "0.0"):
                continue
            if code.startswith("920"):
                continue
            today_ret = (c - prev_c) / prev_c
            if today_ret >= bl:
                continue
            t1_close = closes[i + 1]
            t5_close = closes[i + 5]
            if not t1_close or not t5_close:
                continue
            path = []
            for k in (2, 3, 4):
                if i + k < nb:
                    path.append((lows[i + k], opens[i + k]))
            nostop = (t5_close - t1_close) / t1_close
            by_date[dates_l[i]].append({
                "code": code, "tr": today_ret, "amt": amt,
                "entry": t1_close, "nostop": nostop, "path": path,
            })
    # rank each date ONCE, cache
    ranked: dict = {}
    for d, lst in by_date.items():
        if len(lst) < TOP_N * 10:
            continue
        nn = len(lst)
        st = sorted(range(nn), key=lambda k: lst[k]["tr"])
        sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
        rt = {o: r / nn for r, o in enumerate(st)}
        ra = {o: 1 - r / nn for r, o in enumerate(sa)}
        top_idx = sorted(range(nn), key=lambda k: rt[k] + ra[k], reverse=True)[:TOP_N]
        ranked[d] = [lst[k] for k in top_idx]
    return by_date, ranked


def stop_ret_realistic(p, stop):
    e = p["entry"]
    if not e:
        return p["nostop"]
    trigger = e * (1.0 + stop)
    for low, opn in p["path"]:
        if low <= trigger:
            fill = opn if (opn and opn <= trigger) else trigger
            return (fill - e) / e
    return p["nostop"]


def trigger_maxdd(p):
    e = p["entry"]
    if not e or not p["path"]:
        return 0.0
    return min(low for low, _ in p["path"]) / e - 1.0


def stats_from_picks(dates, ranked, ret_fn):
    daily_mean, all_picks = [], []
    for d in dates:
        top = ranked.get(d)
        if not top:
            continue
        rets = [ret_fn(p) for p in top]
        daily_mean.append(statistics.mean(rets))
        all_picks.extend(rets)
    if not daily_mean:
        return {}
    m = statistics.mean(daily_mean)
    wr = sum(1 for x in all_picks if x > 0) / len(all_picks)
    std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
    se = std / (len(daily_mean) ** 0.5)
    t = m / se if se > 0 else 0
    return {"n_days": len(daily_mean), "n_picks": len(all_picks), "mean": m,
            "pick_median": statistics.median(all_picks), "wr": wr,
            "net": m - COST, "t": t, "daily": daily_mean}


def main():
    print("loading + ranking cache...", flush=True)
    by_date, ranked = build_and_rank()
    dates = sorted(ranked.keys())
    print(f"ranked dates={len(dates)} range={dates[0]}~{dates[-1]}", flush=True)
    all_picks = [p for d in dates for p in ranked[d]]
    n = len(all_picks)
    print(f"n_picks={n}")

    nostop = stats_from_picks(dates, ranked, lambda p: p["nostop"])
    print("\n=== nostop baseline (T+1 close -> T+5 close, de-zt top-20) ===")
    print(f"  days={nostop['n_days']} picks={nostop['n_picks']}")
    print(f"  mean={nostop['mean']*100:+.3f}% net={nostop['net']*100:+.3f}% "
          f"median={nostop['pick_median']*100:+.3f}% WR={nostop['wr']*100:.1f}% t={nostop['t']:.2f}")

    nostop_rets = [p["nostop"] for p in all_picks]
    lt10 = sum(1 for x in nostop_rets if x <= -0.10) / n
    gt10 = sum(1 for x in nostop_rets if x >= 0.10) / n
    lt5 = sum(1 for x in nostop_rets if x <= -0.05) / n
    gt5 = sum(1 for x in nostop_rets if x >= 0.05) / n
    print(f"  tails: <-10%={lt10*100:.1f}% <-5%={lt5*100:.1f}% >+5%={gt5*100:.1f}% >+10%={gt10*100:.1f}%")

    print("\n=== hard stop grid (realistic stop-order) ===")
    print(f"  {'stop':>7}{'mean':>10}{'net':>10}{'median':>10}{'WR':>7}{'t':>7}{'trig%':>7}{'Δnet':>9}")
    base_net = nostop["net"]
    base_mean = nostop["mean"]
    rows = []
    for s in STOPS:
        r = stats_from_picks(dates, ranked, lambda p, ss=s: stop_ret_realistic(p, ss))
        trig = sum(1 for p in all_picks if trigger_maxdd(p) <= s) / n
        dn = r["net"] - base_net
        dm = r["mean"] - base_mean
        rows.append((s, r, trig, dn, dm))
        print(f"  {s*100:>+6.0f}%{r['mean']*100:>+9.3f}%{r['net']*100:>+9.3f}%"
              f"{r['pick_median']*100:>+9.3f}%{r['wr']*100:>6.1f}%{r['t']:>6.2f}"
              f"{trig*100:>6.1f}%{dn*100:>+8.3f}%")

    # KEY: paired difference t-test nostop vs each stop (same picks, same days)
    print("\n=== PAIRED difference test (nostop - stop), same picks ===")
    from math import sqrt
    for s in STOPS:
        diffs = []
        for d in dates:
            top = ranked.get(d)
            if not top:
                continue
            dret = statistics.mean(p["nostop"] - stop_ret_realistic(p, s) for p in top)
            diffs.append(dret)
        m = statistics.mean(diffs)
        sd = statistics.pstdev(diffs) if len(diffs) > 1 else 0
        se = sd / sqrt(len(diffs)) if diffs else 0
        tt = m / se if se > 0 else 0
        print(f"  stop={s*100:+.0f}%: Δmean(nostop-stop)={m*100:+.4f}% paired_t={tt:.2f} "
              f"({'SIG' if abs(tt)>=2 else 'NOT SIG'} @ |t|>=2)")

    # trailing stop test (untested by original): lock 50% of peak gain
    print("\n=== UNTESTED: trailing stop (lock 50% peak gain, min +3% to arm) ===")
    def trailing_stop(p):
        e = p["entry"]
        if not e or not p["path"]:
            return p["nostop"]
        peak = e
        armed = False
        for low, opn in p["path"]:
            # use day high approx via low not available; approximate peak by entry*(1+max intraday)
            # we only have low/open; approximate: if open > peak, peak = open
            if opn and opn > peak:
                peak = opn
            trail = peak * 0.97  # lock 3% from peak
            if peak / e - 1 >= 0.03:
                armed = True
            if armed and low <= trail:
                fill = opn if (opn and opn <= trail) else trail
                return (fill - e) / e
        return p["nostop"]
    r_trail = stats_from_picks(dates, ranked, trailing_stop)
    print(f"  trailing: mean={r_trail['mean']*100:+.3f}% net={r_trail['net']*100:+.3f}% "
          f"median={r_trail['pick_median']*100:+.3f}% WR={r_trail['wr']*100:.1f}% "
          f"Δnet={ (r_trail['net']-base_net)*100:+.3f}%")

    # take-profit test (untested): exit at +8% target
    print("\n=== UNTESTED: take-profit +8% (exit at target) ===")
    def take_profit(p, tgt=0.08):
        e = p["entry"]
        if not e or not p["path"]:
            return p["nostop"]
        target = e * (1 + tgt)
        for low, opn in p["path"]:
            # we only have low; high unknown. approximate: if open >= target, fill at open
            if opn and opn >= target:
                return (opn - e) / e
        return p["nostop"]
    r_tp = stats_from_picks(dates, ranked, take_profit)
    print(f"  takeprof+8%: mean={r_tp['mean']*100:+.3f}% net={r_tp['net']*100:+.3f}% "
          f"Δnet={ (r_tp['net']-base_net)*100:+.3f}%")

    # convergence verdict
    print("\n=== CONVERGENCE VERDICT ===")
    any_stop_improve = any(r["net"] > base_net for _, r, *_ in rows)
    print(f"  nostop net={base_net*100:+.3f}% | any hard stop beats nostop? {any_stop_improve}")
    print(f"  trailing beats nostop? {r_trail['net'] > base_net} ({r_trail['net']*100:+.3f}%)")
    print(f"  takeprofit beats nostop? {r_tp['net'] > base_net} ({r_tp['net']*100:+.3f}%)")

    # OOS split: walk-forward style (first 60% train / last 40% test) — is ceiling stable OOS?
    split = int(len(dates) * 0.6)
    tr_d, te_d = dates[:split], dates[split:]
    print(f"\n=== OOS stability (60/40 split, train {tr_d[0]}~{tr_d[-1]} / test {te_d[0]}~{te_d[-1]}) ===")
    n_tr = stats_from_picks(tr_d, ranked, lambda p: p["nostop"])
    n_te = stats_from_picks(te_d, ranked, lambda p: p["nostop"])
    print(f"  nostop train net={n_tr['net']*100:+.3f}% (t={n_tr['t']:.2f}) | test net={n_te['net']*100:+.3f}% (t={n_te['t']:.2f})")
    print(f"  decay = {(n_te['net']-n_tr['net'])*100:+.3f}pp")


if __name__ == "__main__":
    main()
