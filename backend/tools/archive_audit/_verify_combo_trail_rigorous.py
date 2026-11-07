# -*- coding: utf-8 -*-
"""Rigorous trailing-stop test with proper intraday highs (refutation check).
Build extracts high into path so trailing stop uses real intraday peaks.
Also tests ATR-scaled stop and variable holding period (convergence levers
the original claim did NOT test).
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from math import sqrt

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vr_paths import resolve_data_dir


DB = resolve_data_dir() / "baostock_kline_cache.db"
COST = 0.004
TOP_N = 20


def board_limit(code: str) -> float:
    c = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    if c.startswith("30") or c.startswith("68"):
        return 0.20
    if c.startswith("8") or c.startswith("4"):
        return 0.30
    return 0.10


def build_ranked():
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
        bl = board_limit(code)
        closes = [0.0]*nb; highs = [0.0]*nb; lows = [0.0]*nb
        opens = [0.0]*nb; amts = [0.0]*nb; issts = ["0"]*nb; dates_l = [""]*nb
        for j in range(nb):
            b = bars[j]
            dates_l[j] = b.get("date", "")
            closes[j] = float(b.get("close", 0) or 0)
            highs[j] = float(b.get("high", 0) or 0)
            lows[j] = float(b.get("low", 0) or 0)
            opens[j] = float(b.get("open", 0) or 0)
            amts[j] = float(b.get("amount", 0) or 0)
            issts[j] = str(b.get("isST", "0"))
        for i in range(60, nb-5):
            prev_c = closes[i-1]; c = closes[i]; amt = amts[i]
            if not prev_c or not c or not amt:
                continue
            if issts[i] not in ("0", "", "0.0"):
                continue
            if code.startswith("920"):
                continue
            today_ret = (c - prev_c) / prev_c
            if today_ret >= bl:
                continue
            t1_close = closes[i+1]; t5_close = closes[i+5]
            if not t1_close or not t5_close:
                continue
            # path with HIGH for trailing stop
            path = []
            for k in (2, 3, 4):
                if i+k < nb:
                    path.append((lows[i+k], highs[i+k], opens[i+k], closes[i+k]))
            nostop = (t5_close - t1_close) / t1_close
            by_date[dates_l[i]].append({
                "code": code, "tr": today_ret, "amt": amt,
                "entry": t1_close, "nostop": nostop, "path": path,
            })
    ranked = {}
    for d, lst in by_date.items():
        if len(lst) < TOP_N*10:
            continue
        nn = len(lst)
        st = sorted(range(nn), key=lambda k: lst[k]["tr"])
        sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
        rt = {o: r/nn for r, o in enumerate(st)}
        ra = {o: 1-r/nn for r, o in enumerate(sa)}
        top_idx = sorted(range(nn), key=lambda k: rt[k]+ra[k], reverse=True)[:TOP_N]
        ranked[d] = [lst[k] for k in top_idx]
    return ranked


def stats(dates, ranked, ret_fn):
    dm = []; ap = []
    for d in dates:
        top = ranked.get(d)
        if not top: continue
        r = [ret_fn(p) for p in top]
        dm.append(statistics.mean(r)); ap.extend(r)
    if not dm: return {}
    m = statistics.mean(dm)
    wr = sum(1 for x in ap if x > 0)/len(ap)
    sd = statistics.pstdev(dm) if len(dm) > 1 else 0
    se = sd/sqrt(len(dm)) if dm else 0
    return {"mean": m, "net": m-COST, "med": statistics.median(ap), "wr": wr,
            "t": m/se if se > 0 else 0, "n": len(ap)}


def main():
    print("building with HIGH field...", flush=True)
    ranked = build_ranked()
    dates = sorted(ranked.keys())
    all_picks = [p for d in dates for p in ranked[d]]
    n = len(all_picks)
    print(f"dates={len(dates)} picks={n}")

    base = stats(dates, ranked, lambda p: p["nostop"])
    print(f"\nnostop: net={base['net']*100:+.3f}% med={base['med']*100:+.3f}% WR={base['wr']*100:.1f}% t={base['t']:.2f}")

    # Trailing stop v2: use real intraday HIGH as peak. Arm at +3%, trail 3%/5%/7% from peak.
    def trail(p, arm=0.03, pct=0.03):
        e = p["entry"]
        if not e or not p["path"]: return p["nostop"]
        peak = e; armed = False
        for low, high, opn, cls in p["path"]:
            if high > peak: peak = high
            if peak/e - 1 >= arm: armed = True
            if armed:
                trail_lvl = peak * (1 - pct)
                if low <= trail_lvl:
                    fill = opn if (opn and opn <= trail_lvl) else trail_lvl
                    return (fill - e)/e
        return p["nostop"]

    print("\n=== trailing stop (real intraday HIGH) ===")
    for arm in (0.02, 0.03, 0.05):
        for pct in (0.03, 0.05, 0.07):
            r = stats(dates, ranked, lambda p, a=arm, c=pct: trail(p, a, c))
            print(f"  arm+{arm*100:.0f}% trail{pct*100:.0f}%: net={r['net']*100:+.3f}% "
                  f"med={r['med']*100:+.3f}% WR={r['wr']*100:.1f}% t={r['t']:.2f} "
                  f"Δnet={ (r['net']-base['net'])*100:+.3f}%")

    # ATR-scaled stop (volatility-adjusted hard stop) — untested convergence lever
    # proxy ATR = avg true range of holding path using high/low
    def atr_stop(p, mult=2.0):
        e = p["entry"]
        if not e or not p["path"]: return p["nostop"]
        trs = []
        for low, high, opn, cls in p["path"]:
            trs.append(high - low)
        atr = statistics.mean(trs) if trs else e*0.03
        stop_dist = mult * atr / e
        trigger = e * (1 - stop_dist)
        for low, high, opn, cls in p["path"]:
            if low <= trigger:
                fill = opn if (opn and opn <= trigger) else trigger
                return (fill - e)/e
        return p["nostop"]
    print("\n=== ATR-scaled stop (volatility adjusted) ===")
    for mult in (1.5, 2.0, 2.5, 3.0):
        r = stats(dates, ranked, lambda p, m=mult: atr_stop(p, m))
        print(f"  ATR×{mult}: net={r['net']*100:+.3f}% med={r['med']*100:+.3f}% "
              f"WR={r['wr']*100:.1f}% t={r['t']:.2f} Δnet={ (r['net']-base['net'])*100:+.3f}%")

    # Variable exit: hold winners to T+5, cut losers at -3% intraday (asymmetric)
    def asym(p, cut=-0.03):
        e = p["entry"]
        if not e or not p["path"]: return p["nostop"]
        trigger = e * (1 + cut)
        for low, high, opn, cls in p["path"]:
            if low <= trigger:
                fill = opn if (opn and opn <= trigger) else trigger
                return (fill - e)/e
        return p["nostop"]
    r_asym = stats(dates, ranked, asym)
    print(f"\nasymmetric (cut -3% losers, ride winners to T+5): net={r_asym['net']*100:+.3f}% "
          f"Δnet={ (r_asym['net']-base['net'])*100:+.3f}%")

    # Best convergence lever found
    best_trail = None; best_net = base["net"]
    for arm in (0.02, 0.03, 0.05):
        for pct in (0.03, 0.05, 0.07):
            r = stats(dates, ranked, lambda p, a=arm, c=pct: trail(p, a, c))
            if r["net"] > best_net:
                best_net = r["net"]; best_trail = (arm, pct, r)
    print(f"\n=== BEST convergence lever ===")
    if best_trail:
        arm, pct, r = best_trail
        print(f"  trailing arm+{arm*100:.0f}% trail{pct*100:.0f}%: net={r['net']*100:+.3f}% "
              f"(+{(r['net']-base['net'])*100:.3f}pp over nostop {base['net']*100:+.3f}%)")
        print(f"  median {base['med']*100:+.3f}% -> {r['med']*100:+.3f}% | WR {base['wr']*100:.1f}% -> {r['wr']*100:.1f}%")
    else:
        print("  no lever beats nostop")

    # OOS: does best trailing stop hold out-of-sample?
    split = int(len(dates)*0.6)
    if best_trail:
        arm, pct, _ = best_trail
        n_tr = stats(dates[:split], ranked, lambda p, a=arm, c=pct: trail(p, a, c))
        n_te = stats(dates[split:], ranked, lambda p, a=arm, c=pct: trail(p, a, c))
        b_tr = stats(dates[:split], ranked, lambda p: p["nostop"])
        b_te = stats(dates[split:], ranked, lambda p: p["nostop"])
        print(f"\n=== OOS (60/40) trailing vs nostop ===")
        print(f"  train: nostop {b_tr['net']*100:+.3f}% | trail {n_tr['net']*100:+.3f}%")
        print(f"  test:  nostop {b_te['net']*100:+.3f}% | trail {n_te['net']*100:+.3f}%")


if __name__ == "__main__":
    main()
