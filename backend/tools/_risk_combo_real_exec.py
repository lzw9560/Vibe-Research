# -*- coding: utf-8 -*-
"""Risk-control: real_exec edge + non-overlapping drawdown + Kelly (2026-11-08).

Computes the TRADABLE edge (T+1 open -> T+5 close) with proper overlap-corrected
NW-t, slippage sensitivity, non-overlapping 5-bucket equity curve, and Kelly sizing.
"""
from __future__ import annotations
import json
import sqlite3
import statistics
import math
from collections import defaultdict
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
DB = resolve_data_dir() / "baostock_kline_cache.db"
COST = 0.004
TOP_N = 20
BONF_N = 50

print("loading cache...", flush=True)
conn = sqlite3.connect(str(DB))
rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
conn.close()
print(f"stocks={len(rows)}", flush=True)

by_date: dict = defaultdict(list)
n_done = 0
for code, bj in rows:
    try:
        bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
    except Exception:
        continue
    nb = len(bars)
    if nb < 70:
        continue
    c0 = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    bl = 0.20 if (c0.startswith("30") or c0.startswith("68")) else (0.30 if (c0.startswith("8") or c0.startswith("4")) else 0.10)
    for i in range(60, nb - 5):
        prev_c = float(bars[i - 1].get("close", 0) or 0)
        o = float(bars[i].get("open", 0) or 0)
        c = float(bars[i].get("close", 0) or 0)
        amt = float(bars[i].get("amount", 0) or 0)
        isST = str(bars[i].get("isST", "0"))
        if not prev_c or not c or not o or not amt:
            continue
        today_ret = (c - prev_c) / prev_c
        gap = (o - prev_c) / prev_c
        # mode=filtered: exclude ST, 920, limit-up
        if isST not in ("0", "", "0.0"):
            continue
        if code.startswith("920"):
            continue
        if today_ret >= bl:
            continue
        # MA60 for regime gate
        ma60 = statistics.mean(float(bars[j].get("close", 0) or 0) for j in range(i - 60, i))
        if not ma60:
            continue
        t1_bar = bars[i + 1]
        t1_open = float(t1_bar.get("open", 0) or 0)
        t1_high = float(t1_bar.get("high", 0) or 0)
        t1_low = float(t1_bar.get("low", 0) or 0)
        t1_vol = float(t1_bar.get("volume", 0) or 0)
        t5_close = float(bars[i + 5].get("close", 0) or 0)
        if not t1_open or not t5_close:
            continue
        if t1_vol <= 0:
            continue  # T+1 suspended
        t1_gap = (t1_open - c) / c if c else 0
        if t1_gap >= bl:
            continue  # T+1 open limit-up, unbuyable
        if t1_open == t1_high == t1_low and t1_gap >= bl * 0.98:
            continue  # T+1 one-line board
        real_exec = (t5_close - t1_open) / t1_open  # TRADABLE return
        close_close = (t5_close - c) / c  # idealized
        # past5 for gate
        past5_c = float(bars[i - 5].get("close", 0) or 0) if i >= 5 else prev_c
        past_5d = (c - past5_c) / past5_c if past5_c else 0.0
        by_date[bars[i].get("date", "")].append({
            "code": code, "gap": gap, "tr": today_ret, "amt": amt,
            "real_exec": real_exec, "close_close": close_close,
            "entry_gap": t1_gap, "up": c > ma60, "past5": past_5d,
        })
    n_done += 1
    if n_done % 1000 == 0:
        print(f"  processed {n_done}/{len(rows)}...", flush=True)

all_d = sorted(by_date.keys())
print(f"dates={len(all_d)} range={all_d[0]}~{all_d[-1]}", flush=True)

def rank_top(lst, n=TOP_N):
    if len(lst) < n * 10:
        return None
    nn = len(lst)
    sg = sorted(range(nn), key=lambda k: lst[k]["gap"])
    st = sorted(range(nn), key=lambda k: lst[k]["tr"])
    sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
    rg = {o: r / nn for r, o in enumerate(sg)}
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    top_idx = sorted(range(nn), key=lambda k: rg[k]+rt[k]+ra[k], reverse=True)[:n]
    return [lst[k] for k in top_idx]

def gate_on(d):
    lst = by_date[d]
    if len(lst) < 20: return False
    breadth = sum(1 for x in lst if x["up"]) / len(lst)
    srt = sorted(lst, key=lambda x: x["amt"])
    dec = max(1, len(srt) // 10)
    sm5 = statistics.mean(x["past5"] for x in srt[:dec])
    return breadth > 0.4 and sm5 > 0

def nw_t_overlap(daily_mean, cost=COST):
    """Overlap-corrected NW-t (L=5, covers 5-day hold overlap of 4 days)."""
    n = len(daily_mean)
    if n < 10: return 0.0, float(n)
    net = [r - cost for r in daily_mean]
    m = statistics.mean(net)
    std = statistics.pstdev(net) if n > 1 else 0
    if std <= 0: return 0.0, float(n)
    var = std * std
    rho_sum = 0.0
    for k in range(1, 6):
        if n - k <= 0: break
        cov_k = sum((net[i] - m) * (net[i - k] - m) for i in range(k, n)) / n
        rho_k = cov_k / var if var > 0 else 0
        rho_sum += rho_k
    denom = 1 + 2 * rho_sum
    n_eff = n / denom if denom > 0 else float(n)
    se_nw = std / (n_eff ** 0.5) if n_eff > 0 else 0
    t_nw = m / se_nw if se_nw > 0 else 0
    return t_nw, n_eff

def max_dd(eq):
    peak = eq[0]; mdd = 0.0; mlen = 0; cur = 0
    for v in eq[1:]:
        if v > peak: peak = v; cur = 0
        else:
            cur += 1
            dd = v / peak - 1
            if dd < mdd: mdd = dd; mlen = cur
    return mdd, mlen

def compute(dates, field, cost=COST):
    daily = []
    for d in dates:
        top = rank_top(by_date[d])
        if not top: continue
        daily.append(statistics.mean(x[field] for x in top))
    if not daily: return None
    m = statistics.mean(daily)
    std = statistics.pstdev(daily) if len(daily) > 1 else 0
    wr = sum(1 for x in daily if x > cost) / len(daily)
    net_m = m - cost
    t_nw, n_eff = nw_t_overlap(daily, cost)
    # Kelly continuous on net returns
    net_rets = [r - cost for r in daily]
    var = statistics.pvariance(net_rets) if len(net_rets) > 1 else 0
    kelly_c = net_m / var if (var > 0 and net_m > 0) else 0.0
    # Kelly discrete
    wins = [x for x in net_rets if x > 0]
    losses = [x for x in net_rets if x <= 0]
    if wins and losses:
        aw = statistics.mean(wins); al = abs(statistics.mean(losses))
        p = len(wins)/len(net_rets); b = aw/al if al > 0 else 0
        kelly_d = (b*p - (1-p))/b if b > 0 else 0
    else:
        kelly_d = 0; aw = al = 0
    # Overlapping equity (full capital daily)
    eq_ov = [1.0]
    for r in daily:
        eq_ov.append(eq_ov[-1]*(1 + r - cost))
    mdd_ov, mlen_ov = max_dd(eq_ov)
    # Non-overlapping: 5 buckets, each bucket trades every 5th day
    buckets = [[] for _ in range(5)]
    for idx, d in enumerate(sorted(dates)):
        top = rank_top(by_date[d])
        if top:
            buckets[idx % 5].append(statistics.mean(x[field] for x in top))
    eq_no = [1.0]
    for b_idx in range(5):
        if not buckets[b_idx]: continue
        # each bucket gets 1/5 of capital, compounds independently
        bret = 1.0
        for r in buckets[b_idx]:
            bret *= (1 + r - cost)
        eq_no.append(bret)  # not quite right, let me do proper
    # Proper non-overlapping: average of 5 bucket equity curves
    bucket_eqs = []
    for b_idx in range(5):
        eq = [1.0]
        for r in buckets[b_idx]:
            eq.append(eq[-1]*(1+r-cost))
        bucket_eqs.append(eq[-1])
    avg_bucket = statistics.mean(bucket_eqs)
    # Combined non-overlapping drawdown: simulate 5-bucket portfolio
    # Each day, 1/5 capital in a new portfolio, 4/5 in existing ones
    # Approximate: weighted average of bucket equity curves sampled daily
    all_dates = sorted(dates)
    portfolio_ret = []
    active = {}  # bucket_idx -> current return
    for idx, d in enumerate(all_dates):
        top = rank_top(by_date[d])
        bucket_id = idx % 5
        if top:
            active[bucket_id] = statistics.mean(x[field] for x in top) - cost
        # today's portfolio return = average of active buckets
        if active:
            portfolio_ret.append(statistics.mean(active.values()))
    eq_portfolio = [1.0]
    for r in portfolio_ret:
        eq_portfolio.append(eq_portfolio[-1]*(1+r))
    mdd_port, mlen_port = max_dd(eq_portfolio)
    # Slippage sensitivity
    slip = {f"slip={s*100:.1f}%": (m - cost - s)*100 for s in (0.0, 0.002, 0.004, 0.006, 0.008, 0.010)}
    return {
        "n_days": len(daily), "gross_mean": m, "net_mean": net_m,
        "std": std, "wr": wr, "t_nw": t_nw, "n_eff": n_eff,
        "kelly_cont": kelly_c, "kelly_disc": kelly_d,
        "avg_win": aw if wins else 0, "avg_loss": al if losses else 0,
        "max_dd_overlap": mdd_ov, "dd_len_overlap": mlen_ov,
        "max_dd_portfolio": mdd_port, "dd_len_portfolio": mlen_port,
        "final_eq_portfolio": eq_portfolio[-1],
        "slip_sens": slip, "worst_day": min(daily), "best_day": max(daily),
    }

print("\n" + "="*70)
print("REAL-EXECUTION EDGE (T+1 open -> T+5 close, mode=filtered)")
print("="*70)
full = compute(all_d, "real_exec")
if full:
    for k,v in full.items():
        if k == "slip_sens":
            print(f"  slip_sens: " + " | ".join(f"{sk}={sv:+.3f}%" for sk,sv in v.items()))
        elif isinstance(v, float):
            print(f"  {k}: {v:.6f}" if abs(v)<1 else f"  {k}: {v:.4f}")
        else:
            print(f"  {k}: {v}")
    print(f"\n  Quarter Kelly (cont): {full['kelly_cont']*0.25:.4f} = {full['kelly_cont']*0.25*100:.2f}% of capital")
    print(f"  Quarter Kelly (disc): {full['kelly_disc']*0.25:.4f} = {full['kelly_disc']*0.25*100:.2f}% of capital")
    print(f"  Eighth Kelly (disc):  {full['kelly_disc']*0.125:.4f} = {full['kelly_disc']*0.125*100:.2f}% of capital")

print("\n" + "="*70)
print("CLOSE-TO-CLOSE EDGE (T close -> T+5 close, IDEALIZED)")
print("="*70)
cc = compute(all_d, "close_close")
if cc:
    print(f"  n_days={cc['n_days']} gross={cc['gross_mean']*100:.4f}% net={cc['net_mean']*100:.4f}% t_nw={cc['t_nw']:.2f}(n_eff={cc['n_eff']:.0f}) WR={cc['wr']*100:.1f}%")
    print(f"  max_dd_overlap={cc['max_dd_overlap']*100:.2f}% max_dd_portfolio={cc['max_dd_portfolio']*100:.2f}%")
    print(f"  entry gap eaten = {(cc['gross_mean']-full['gross_mean'])*100:.4f}%")

if full and cc:
    print(f"\n  ENTRY GAP IMPACT: close_close net {cc['net_mean']*100:.4f}% -> real_exec net {full['net_mean']*100:.4f}% = eaten {(cc['net_mean']-full['net_mean'])*100:.4f}%")

print("\n" + "="*70)
print("REGIME STRATIFIED (real_exec)")
print("="*70)
on_d = [d for d in all_d if gate_on(d)]
off_d = [d for d in all_d if not gate_on(d)]
for label, ds in [("ON ", on_d), ("OFF", off_d)]:
    s = compute(ds, "real_exec")
    if s:
        print(f"  gate={label}: days={s['n_days']} net={s['net_mean']*100:.4f}% t_nw={s['t_nw']:.2f}(n_eff={s['n_eff']:.0f}) WR={s['wr']*100:.1f}% maxDD_port={s['max_dd_portfolio']*100:.2f}% kelly_d={s['kelly_disc']:.4f}")

print("\n" + "="*70)
print("YEARLY (real_exec net)")
print("="*70)
for yr in ["2018","2019","2020","2021","2022","2023","2024","2025","2026"]:
    ds = [d for d in all_d if d.startswith(yr)]
    if not ds: continue
    s = compute(ds, "real_exec")
    if s:
        print(f"  {yr}: days={s['n_days']} net={s['net_mean']*100:.4f}% t_nw={s['t_nw']:.2f} WR={s['wr']*100:.1f}% maxDD_port={s['max_dd_portfolio']*100:.2f}%")

print("\n" + "="*70)
print("WALK-FORWARD (real_exec)")
print("="*70)
for label, ds in [("train(<2023)", [d for d in all_d if d<"2023-01-01"]), ("test(>=2023)", [d for d in all_d if d>="2023-01-01"])]:
    s = compute(ds, "real_exec")
    if s:
        print(f"  {label}: days={s['n_days']} net={s['net_mean']*100:.4f}% t_nw={s['t_nw']:.2f}(n_eff={s['n_eff']:.0f}) WR={s['wr']*100:.1f}% maxDD_port={s['max_dd_portfolio']*100:.2f}%")

print("\n" + "="*70)
print("BONFERRONI x50")
print("="*70)
if full:
    print(f"  real_exec t_nw = {full['t_nw']:.4f}, n_eff = {full['n_eff']:.0f}")
    print(f"  Bonf alpha = 0.05/{BONF_N} = {0.05/BONF_N:.6f}, z_crit(one-sided) ~ 3.09")
    print(f"  PASS: {full['t_nw'] > 3.09} (margin: {full['t_nw']-3.09:.4f})")
    print(f"  If t=3.64 (task claim): margin = {3.64-3.09:.2f} (razor thin)")
