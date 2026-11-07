"""ETF domain: full holiday signal + premium + momentum analysis."""
# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
import json
import sys
from pathlib import Path
from datetime import datetime
from statistics import mean, median, stdev
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir
CACHE = str(resolve_data_dir())
with open(f"{CACHE}/index_ohlc_cache.json") as f:
    idx = json.load(f)
with open(f"{CACHE}/etf_premium_cache.json") as f:
    etf = json.load(f)

sh = idx["sh.000001"]
dates = [r["date"] for r in sh]
by_date = {r["date"]: r for r in sh}
date_idx = {d: i for i, d in enumerate(dates)}

# long holidays
holiday_gaps = []
for i in range(1, len(dates)):
    d0 = datetime.strptime(dates[i-1], "%Y-%m-%d")
    d1 = datetime.strptime(dates[i], "%Y-%m-%d")
    gap = (d1 - d0).days
    if gap >= 7:
        holiday_gaps.append({"last_pre": dates[i-1], "first_post": dates[i], "gap_days": gap,
                             "i_last": i-1, "i_post": i})

print(f"Long holidays (gap>=7): {len(holiday_gaps)}\n")

# ---------- SIGNAL REPRODUCE on index ----------
# PRE signal: 倒数第3交易日 close -> T+1 open buy -> 长假前最后1交易日 close sell (2-day hold)
# i_last = index of last pre-holiday trading day. 倒数第3 = i_last-2
def index_ret_pct(d_buy_close, d_sell_close):
    return (by_date[d_sell_close]["close"] / by_date[d_buy_close]["close"] - 1) * 100

# Actually signal: buy at open of (i_last-2 + 1) = i_last-1 open?
# "倒数第3交易日close -> T+1 open 买 -> 最后1交易日close 卖"
# 倒数第3 = T-3 (i_last-2). T+1 of T-3 = i_last-1. buy at open(i_last-1). sell at close(i_last).
# 2-day hold: i_last-1 (buy day) -> i_last (sell day) = 1 day hold actually?
# Let me interpret: hold from open(i_last-1) to close(i_last). That's ~1.x days.
# But "2日hold" suggests buy day + sell day = 2 trading days. buy open(T-2) sell close(T-1last).
# Let me test BOTH interpretations and report.

results_pre = []
for g in holiday_gaps:
    il = g["i_last"]
    if il - 2 < 0: continue
    # interpretation A: 倒数第3=il-2 close as signal; buy open(il-1); sell close(il)
    try:
        buy_open = by_date[dates[il-1]]["open"]
        sell_close = by_date[dates[il]]["close"]
        ret_a = (sell_close/buy_open - 1)*100
        # also buy close(il-2) -> sell close(il) as alt
        ret_close2close = (by_date[dates[il]]["close"]/by_date[dates[il-2]]["close"] - 1)*100
        results_pre.append({"last_pre": g["last_pre"], "first_post": g["first_post"],
                            "gap": g["gap_days"], "ret_openA": ret_a,
                            "ret_c2c": ret_close2close})
    except KeyError:
        pass

def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals: return None
    m = mean(vals); s = stdev(vals) if len(vals)>1 else 0
    wr = sum(1 for v in vals if v>0)/len(vals)*100
    return {"n":len(vals),"mean":round(m,4),"med":round(median(vals),4),"sd":round(s,4),"wr":round(wr,1)}

print("=== PRE-holiday signal (index sh.000001) ===")
print(f"n={len(results_pre)}")
sa = stats([r["ret_openA"] for r in results_pre])
sc = stats([r["ret_c2c"] for r in results_pre])
print(f"Interpret A (buy open(il-1) sell close(il)): {sa}")
print(f"close(il-2)->close(il): {sc}")

# base rate: any random 2-day open->close window
import random
random.seed(42)
base_samples = []
for _ in range(5000):
    i = random.randint(2, len(dates)-2)
    bo = by_date[dates[i]]["open"]; sc2 = by_date[dates[i]]["close"]
    base_samples.append((sc2/bo-1)*100)
bs = stats(base_samples)
print(f"\nBase rate (random 1-day open->close, 5000 samples): mean={bs['mean']}% wr={bs['wr']}%")
# actually let me do open(i)->close(i+1) to match ~2 day hold
base2 = []
for _ in range(5000):
    i = random.randint(2, len(dates)-3)
    bo = by_date[dates[i]]["open"]; sc2 = by_date[dates[i+1]]["close"]
    base2.append((sc2/bo-1)*100)
bs2 = stats(base2)
print(f"Base rate (random open(i)->close(i+1), 5000 samples): mean={bs2['mean']}% wr={bs2['wr']}%")

# ---------- 2. ETF PREMIUM changes around holiday ----------
# premium = close/nav - 1 (in bps)
def premium_pct(code, d):
    r = etf.get(code, {}).get(d)
    if not r: return None
    nav = r.get("nav"); cl = r.get("close")
    if not nav or nav==0: return None
    return (cl/nav - 1)*100  # percent

# for each long holiday, compute premium change: premium(last_pre) - premium(last_pre - N)
# Use premium on last_pre day and on 3 trading days before
print("\n=== ETF premium/discount around long holidays ===")
# broad vs sector
broad = ["510300","510050","510500","159901","512100","588000"]
dividend = ["510880","512890"]
sector = ["512760","159995","515790","512660"]

def premium_change_around(code, g):
    il = g["i_last"]
    # need trading days il-3, il-2, il-1, il, and post il+1(=first_post)
    rows = []
    for off in [-3,-2,-1,0]:
        di = il+off
        if di<0 or di>=len(dates):
            rows.append(None); continue
        d = dates[di]
        p = premium_pct(code, d)
        rows.append((d,p))
    # post
    pp = premium_pct(code, g["first_post"])
    rows.append((g["first_post"], pp))
    return rows

print(f"{'code':8} {'prem@T-3':>9} {'prem@T-2':>9} {'prem@T-1':>9} {'prem@T0(last)':>13} {'prem@T+1(post)':>13}")
for code in broad+dividend+sector:
    all_rows = [premium_change_around(code, g) for g in holiday_gaps]
    # average premium at each offset across holidays (only where data exists)
    avgs = []
    for off in range(5):
        vals = [r[off][1] for r in all_rows if r and r[off] and r[off][1] is not None]
        avgs.append(mean(vals) if vals else None)
    def fmt(x): return f"{x:9.4f}" if x is not None else "      -  "
    print(f"{code:8} {fmt(avgs[0])} {fmt(avgs[1])} {fmt(avgs[2])} {fmt(avgs[3])} {fmt(avgs[4])}")

# premium CHANGE: last_pre premium minus premium 3 days before
print("\n=== Premium change (T0 last_pre minus T-3) in bps, pre-holiday ===")
for code in broad+dividend+sector:
    changes = []
    for g in holiday_gaps:
        il = g["i_last"]
        if il-3<0 or il>=len(dates): continue
        p0 = premium_pct(code, dates[il])
        p3 = premium_pct(code, dates[il-3])
        if p0 is None or p3 is None: continue
        changes.append((p0-p3)*100)  # bps
    if changes:
        st = stats(changes)
        print(f"{code:8} n={st['n']:3} mean_chg={st['mean']:+8.2f}bps med={st['med']:+8.2f} wr_pos={st['wr']}%")
