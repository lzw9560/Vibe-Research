# -*- coding: utf-8 -*-
"""Optimized focused: regime drawdown only. Rolling MA60, pre-extracted floats."""
from __future__ import annotations
import json, sqlite3, statistics, sys
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / ".vibe-research" / "baostock_kline_cache.db"
COST = 0.004; TOP_N = 20
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
    # pre-extract floats
    closes = [0.0]*nb
    opens = [0.0]*nb
    lows = [0.0]*nb
    amts = [0.0]*nb
    dates_l = [""]*nb
    for j in range(nb):
        b = bars[j]
        dates_l[j] = b.get("date", "")
        closes[j] = float(b.get("close", 0) or 0)
        opens[j] = float(b.get("open", 0) or 0)
        amts[j] = float(b.get("amount", 0) or 0)
    # rolling MA60 via cumulative sum
    cumsum = [0.0]*(nb+1)
    for j in range(nb):
        cumsum[j+1] = cumsum[j] + closes[j]
    for i in range(60, nb - 5):
        prev_c = closes[i-1]; o = opens[i]; c = closes[i]; amt = amts[i]
        if not prev_c or not c or not o:
            continue
        ma60 = (cumsum[i] - cumsum[i-60]) / 60.0
        if not ma60:
            continue
        today_ret = (c - prev_c) / prev_c
        gap = (o - prev_c) / prev_c
        past5_c = closes[i-5] if i >= 5 else prev_c
        past_5d = (c - past5_c) / past5_c if past5_c else 0.0
        nc = closes[i+5]
        if not nc:
            continue
        fwd5 = (nc - c) / c
        by_date[dates_l[i]].append({
            "code": code, "gap": gap, "tr": today_ret, "amt": amt,
            "entry": c, "fwd5": fwd5, "up": c > ma60, "past5": past_5d,
            "limit": today_ret >= bl * 0.98,
        })
    n_done += 1
    if n_done % 1000 == 0:
        print(f"  processed {n_done}/{len(rows)} stocks...", flush=True)

all_d = sorted(by_date.keys())
print(f"dates={len(all_d)} range={all_d[0]}~{all_d[-1]}", flush=True)

def rank_top(lst, n=TOP_N):
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
    top_idx = sorted(range(nn), key=lambda k: rg[k]+rt[k]+ra[k], reverse=True)[:n]
    return [pool[k] for k in top_idx]

def gate_on(d):
    lst = by_date[d]
    if len(lst) < 20: return False
    breadth = sum(1 for x in lst if x["up"]) / len(lst)
    srt = sorted(lst, key=lambda x: x["amt"])
    dec = max(1, len(srt) // 10)
    sm5 = statistics.mean(x["past5"] for x in srt[:dec])
    return breadth > 0.4 and sm5 > 0

def equity_curve(dates):
    daily_rets = []
    for d in dates:
        top = rank_top(by_date[d])
        if not top: continue
        daily_rets.append(statistics.mean(x["fwd5"] for x in top))
    eq = [1.0]
    for r in daily_rets:
        eq.append(eq[-1] * (1.0 + r - COST))
    return eq, daily_rets

def max_drawdown(eq):
    peak = eq[0]; mdd = 0.0; mdd_len = 0; cur_len = 0
    for v in eq[1:]:
        if v > peak: peak = v; cur_len = 0
        else:
            cur_len += 1
            dd = v / peak - 1.0
            if dd < mdd: mdd = dd; mdd_len = cur_len
    return mdd, mdd_len

print("\n=== regime drawdown ===", flush=True)
on_d = [d for d in all_d if gate_on(d)]
off_d = [d for d in all_d if not gate_on(d)]
for label, ds in [("gate=ON ", on_d), ("gate=OFF", off_d)]:
    if not ds: continue
    eq, rets = equity_curve(ds)
    mdd, mlen = max_drawdown(eq)
    m = statistics.mean(rets)
    wr = sum(1 for x in rets if x > 0) / len(rets) if rets else 0
    worst = min(rets) if rets else 0
    print(f"  {label}: days={len(rets)} mean={m*100:+.3f}% WR={wr*100:.1f}% maxDD={mdd*100:+.2f}%(持续{mlen}日) worst_day={worst*100:+.2f}% 终值={eq[-1]:.3f}", flush=True)

d2026 = [d for d in all_d if d.startswith("2026")]
if d2026:
    eq26, rets26 = equity_curve(d2026)
    mdd26, mlen26 = max_drawdown(eq26)
    m26 = statistics.mean(rets26) if rets26 else 0
    print(f"  2026单独: days={len(rets26)} mean={m26*100:+.3f}% maxDD={mdd26*100:+.2f}%(持续{mlen26}日) 终值={eq26[-1]:.3f}", flush=True)

last_d = all_d[-1] if all_d else None
if last_d:
    g = gate_on(last_d)
    lst = by_date[last_d]
    breadth = sum(1 for x in lst if x["up"]) / len(lst) if lst else 0
    srt = sorted(lst, key=lambda x: x["amt"]) if lst else []
    dec = max(1, len(srt) // 10)
    sm5 = statistics.mean(x["past5"] for x in srt[:dec]) if srt else 0
    print(f"\n  最新日 {last_d}: gate={'ON' if g else 'OFF'} breadth={breadth*100:.1f}% small5d={sm5*100:.2f}%", flush=True)
