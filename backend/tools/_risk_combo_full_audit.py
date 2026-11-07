# -*- coding: utf-8 -*-
"""Risk-control focused combo audit (2026-11-08).

Verifies task claims + computes Kelly / drawdown / position-sizing inputs.
mode=filtered (exclude limit-up), top-20 equal weight, 5-day hold, COST=0.004.
"""

from __future__ import annotations
import json
import sqlite3
import statistics
import math
from collections import defaultdict
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


DB = resolve_data_dir() / "baostock_kline_cache.db"
COST = 0.004
TOP_N = 20
BONF_N = 50  # Bonferroni x50 (task claim)

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
    closes = [0.0] * nb
    opens = [0.0] * nb
    amts = [0.0] * nb
    dates_l = [""] * nb
    for j in range(nb):
        b = bars[j]
        dates_l[j] = b.get("date", "")
        closes[j] = float(b.get("close", 0) or 0)
        opens[j] = float(b.get("open", 0) or 0)
        amts[j] = float(b.get("amount", 0) or 0)
    cumsum = [0.0] * (nb + 1)
    for j in range(nb):
        cumsum[j + 1] = cumsum[j] + closes[j]
    for i in range(60, nb - 5):
        prev_c = closes[i - 1]
        o = opens[i]
        c = closes[i]
        amt = amts[i]
        if not prev_c or not c or not o:
            continue
        ma60 = (cumsum[i] - cumsum[i - 60]) / 60.0
        if not ma60:
            continue
        today_ret = (c - prev_c) / prev_c
        gap = (o - prev_c) / prev_c
        past5_c = closes[i - 5] if i >= 5 else prev_c
        past_5d = (c - past5_c) / past5_c if past5_c else 0.0
        nc = closes[i + 5]
        if not nc:
            continue
        fwd5 = (nc - c) / c
        by_date[dates_l[i]].append(
            {
                "code": code,
                "gap": gap,
                "tr": today_ret,
                "amt": amt,
                "fwd5": fwd5,
                "up": c > ma60,
                "past5": past_5d,
                "limit": today_ret >= bl * 0.98,
            }
        )
    n_done += 1
    if n_done % 1000 == 0:
        print(f"  processed {n_done}/{len(rows)} stocks...", flush=True)

all_d = sorted(by_date.keys())
print(f"dates={len(all_d)} range={all_d[0]}~{all_d[-1]}", flush=True)


def rank_top(lst, n=TOP_N):
    """mode=filtered: exclude limit-up stocks, then rank composite."""
    pool = [x for x in lst if not x["limit"]]
    if len(pool) < n * 10:
        return None
    nn = len(pool)
    sg = sorted(range(nn), key=lambda k: pool[k]["gap"])
    st = sorted(range(nn), key=lambda k: pool[k]["tr"])
    sa = sorted(range(nn), key=lambda k: pool[k]["amt"])
    rg = {o: r / nn for r, o in enumerate(sg)}
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    top_idx = sorted(range(nn), key=lambda k: rg[k] + rt[k] + ra[k], reverse=True)[:n]
    return [pool[k] for k in top_idx]


def gate_on(d):
    lst = by_date[d]
    if len(lst) < 20:
        return False
    breadth = sum(1 for x in lst if x["up"]) / len(lst)
    srt = sorted(lst, key=lambda x: x["amt"])
    dec = max(1, len(srt) // 10)
    sm5 = statistics.mean(x["past5"] for x in srt[:dec])
    return breadth > 0.4 and sm5 > 0


def nw_t(series, min_lag=5):
    n = len(series)
    if n < 5:
        return 0.0
    m = statistics.mean(series)
    gamma0 = statistics.pvariance(series)
    lag = max(min_lag, int(4 * (n / 100) ** (2 / 9)))
    lag = min(lag, n - 1)
    s = gamma0
    for l in range(1, lag + 1):
        cov = sum((series[t] - m) * (series[t + l] - m) for t in range(n - l)) / n
        w = 1 - l / (lag + 1)
        s += 2 * w * cov
    if s <= 0:
        return 0.0
    se = (s / n) ** 0.5
    return m / se if se > 0 else 0.0


def max_drawdown(eq):
    peak = eq[0]
    mdd = 0.0
    mdd_len = 0
    cur_len = 0
    for v in eq[1:]:
        if v > peak:
            peak = v
            cur_len = 0
        else:
            cur_len += 1
            dd = v / peak - 1.0
            if dd < mdd:
                mdd = dd
                mdd_len = cur_len
    return mdd, mdd_len


def equity_and_stats(dates, cost=COST):
    daily_rets = []
    for d in dates:
        top = rank_top(by_date[d])
        if not top:
            continue
        daily_rets.append(statistics.mean(x["fwd5"] for x in top))
    if not daily_rets:
        return None
    eq = [1.0]
    for r in daily_rets:
        eq.append(eq[-1] * (1.0 + r - cost))
    mdd, mlen = max_drawdown(eq)
    m = statistics.mean(daily_rets)
    gross_m = statistics.mean([r for r in daily_rets])  # before cost
    std = statistics.pstdev(daily_rets) if len(daily_rets) > 1 else 0
    se = std / (len(daily_rets) ** 0.5) if std > 0 else 0
    t_nw = nw_t([r - cost for r in daily_rets])
    t_naive = m / se if se > 0 else 0
    wr = sum(1 for x in daily_rets if x > 0) / len(daily_rets)
    # Kelly (continuous): f* = mean / variance
    net_rets = [r - cost for r in daily_rets]
    var = statistics.pvariance(net_rets) if len(net_rets) > 1 else 0
    kelly_cont = m_net / var if (var > 0 and (m_net := statistics.mean(net_rets)) > 0) else 0.0
    # Kelly (discrete binary approx): f* = (b*p - q) / b where b = win/loss ratio
    wins = [x for x in net_rets if x > 0]
    losses = [x for x in net_rets if x <= 0]
    if wins and losses:
        avg_win = statistics.mean(wins)
        avg_loss = abs(statistics.mean(losses))
        p = len(wins) / len(net_rets)
        b = avg_win / avg_loss if avg_loss > 0 else 0
        kelly_disc = (b * p - (1 - p)) / b if b > 0 else 0
    else:
        kelly_disc = 0
        avg_win = avg_loss = 0
    worst = min(daily_rets)
    best = max(daily_rets)
    n_picks = len(daily_rets) * TOP_N
    return {
        "n_days": len(daily_rets),
        "n_picks": n_picks,
        "gross_mean": gross_m,
        "net_mean": m - cost,
        "std": std,
        "t_naive": t_naive,
        "t_nw": t_nw,
        "wr": wr,
        "max_dd": mdd,
        "dd_len": mlen,
        "kelly_cont": kelly_cont,
        "kelly_disc": kelly_disc,
        "avg_win": avg_win if wins else 0,
        "avg_loss": avg_loss if losses else 0,
        "worst_day": worst,
        "best_day": best,
        "final_eq": eq[-1],
    }


print("\n=== FULL BACKTEST (mode=filtered, top-20, 5d hold, cost=0.4%) ===", flush=True)
full = equity_and_stats(all_d)
if full:
    for k, v in full.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.6f}" if abs(v) < 1 else f"  {k}: {v:.4f}")
        else:
            print(f"  {k}: {v}")

# Break-even cost
if full:
    print(f"\n=== BREAK-EVEN COST ===")
    print(f"  gross_mean (no cost): {full['gross_mean'] * 100:.4f}%")
    print(f"  break-even cost = gross_mean = {full['gross_mean'] * 100:.4f}% (= {full['gross_mean']:.6f} decimal)")
    print(f"  current cost 0.4%: net = {(full['gross_mean'] - 0.004) * 100:.4f}%")

# Bonferroni
if full:
    bonf_thresh = 2.78 * math.sqrt(BONF_N)  # approx Bonf x50 single-sided
    # More precisely, Bonferroni alpha=0.05/50=0.001, one-sided z~3.09
    print(f"\n=== BONFERRONI x{BONF_N} ===")
    print(f"  t_nw = {full['t_nw']:.4f}")
    print(f"  Bonf alpha = 0.05/{BONF_N} = {0.05 / BONF_N:.6f}")
    print(f"  z threshold (one-sided) ~ 3.09 | NW-t with n={full['n_days']} critical ~ {3.09:.2f}")
    print(f"  PASS: {full['t_nw'] > 3.09}")

# Regime stratified
print("\n=== REGIME STRATIFIED ===", flush=True)
on_d = [d for d in all_d if gate_on(d)]
off_d = [d for d in all_d if not gate_on(d)]
for label, ds in [("gate=ON ", on_d), ("gate=OFF", off_d)]:
    s = equity_and_stats(ds)
    if s:
        print(
            f"  {label}: days={s['n_days']} gross={s['gross_mean'] * 100:.4f}% net={s['net_mean'] * 100:.4f}% t_nw={s['t_nw']:.2f} WR={s['wr'] * 100:.1f}% maxDD={s['max_dd'] * 100:.2f}%(len {s['dd_len']}) kelly_cont={s['kelly_cont']:.4f} kelly_disc={s['kelly_disc']:.4f}"
        )

# Yearly breakdown
print("\n=== YEARLY ===", flush=True)
for yr in ["2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"]:
    ds = [d for d in all_d if d.startswith(yr)]
    if not ds:
        continue
    s = equity_and_stats(ds)
    if s:
        print(
            f"  {yr}: days={s['n_days']} net={s['net_mean'] * 100:.4f}% t_nw={s['t_nw']:.2f} WR={s['wr'] * 100:.1f}% maxDD={s['max_dd'] * 100:.2f}%"
        )

# Walk-forward
print("\n=== WALK-FORWARD (train<2023 / test>=2023) ===", flush=True)
train_d = [d for d in all_d if d < "2023-01-01"]
test_d = [d for d in all_d if d >= "2023-01-01"]
for label, ds in [("train", train_d), ("test", test_d)]:
    s = equity_and_stats(ds)
    if s:
        print(
            f"  {label}: days={s['n_days']} gross={s['gross_mean'] * 100:.4f}% net={s['net_mean'] * 100:.4f}% t_nw={s['t_nw']:.2f} maxDD={s['max_dd'] * 100:.2f}%"
        )
