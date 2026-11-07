"""Momentum reference + decay + holiday-type split for pre-holiday signal."""

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
sh = idx["sh.000001"]
dates = [r["date"] for r in sh]
by_date = {r["date"]: r for r in sh}

# long holidays >=7 cal days
holiday_gaps = []
for i in range(1, len(dates)):
    d0 = datetime.strptime(dates[i - 1], "%Y-%m-%d")
    d1 = datetime.strptime(dates[i], "%Y-%m-%d")
    gap = (d1 - d0).days
    if gap >= 7:
        m = d0.month
        htype = "春节" if m in (1, 2) else ("国庆" if m in (9, 10) else "其他")
        holiday_gaps.append(
            {
                "last_pre": dates[i - 1],
                "first_post": dates[i],
                "gap": gap,
                "i_last": i - 1,
                "i_post": i,
                "type": htype,
                "year": d0.year,
            }
        )


def st(v):
    v = [x for x in v if x is not None]
    if not v:
        return "n/a"
    return {
        "n": len(v),
        "mean": round(mean(v), 4),
        "med": round(median(v), 4),
        "wr": round(sum(1 for x in v if x > 0) / len(v) * 100, 1),
    }


# signal: buy open(il-1) sell close(il)
def sig_ret(g):
    il = g["i_last"]
    if il - 1 < 0 or il >= len(dates):
        return None
    bo = by_date[dates[il - 1]]["open"]
    sc = by_date[dates[il]]["close"]
    return (sc / bo - 1) * 100


# PRIOR momentum: return over N days BEFORE signal window
# signal window = open(il-1)->close(il). prior momentum = close(il-3) / close(il-3-N) - 1
def prior_mom(g, N):
    il = g["i_last"]
    if il - 3 - N < 0 or il - 3 < 0:
        return None
    c0 = by_date[dates[il - 3 - N]]["close"]
    c1 = by_date[dates[il - 3]]["close"]
    if c0 == 0:
        return None
    return (c1 / c0 - 1) * 100


print("=== 1. SIGNAL by holiday type ===")
for t in ["春节", "国庆", "其他"]:
    rs = [sig_ret(g) for g in holiday_gaps if g["type"] == t and sig_ret(g) is not None]
    print(f"{t}: {st(rs)}")
print(f"ALL: {st([sig_ret(g) for g in holiday_gaps if sig_ret(g) is not None])}")

print("\n=== 2. TIME DECAY (era split) ===")
for era_lo, era_hi, name in [(2004, 2010, "2004-2010"), (2011, 2017, "2011-2017"), (2018, 2026, "2018-2026")]:
    rs = [sig_ret(g) for g in holiday_gaps if era_lo <= g["year"] <= era_hi and sig_ret(g) is not None]
    print(f"{name}: {st(rs)}")

print("\n=== 3. MOMENTUM REFERENCE: signal return vs prior momentum ===")
# Test: is signal return driven by prior run-up?
for N in [5, 10, 20]:
    pairs = []
    for g in holiday_gaps:
        r = sig_ret(g)
        m = prior_mom(g, N)
        if r is not None and m is not None:
            pairs.append((r, m))
    if len(pairs) < 5:
        print(f"prior{N}d: too few")
        continue
    # split into prior-up vs prior-down
    up = [r for r, m in pairs if m > 0]
    dn = [r for r, m in pairs if m <= 0]
    # correlation
    rs = [r for r, _ in pairs]
    ms = [m for _, m in pairs]
    mr = mean(rs)
    mm = mean(ms)
    cov = sum((r - mr) * (m - mm) for r, m in pairs) / len(pairs)
    vr = sum((r - mr) ** 2 for r, _ in pairs) / len(pairs) or 1
    vm = sum((m - mm) ** 2 for _, m in pairs) / len(pairs) or 1
    corr = cov / (vr**0.5 * vm**0.5) if vr > 0 and vm > 0 else 0
    print(f"prior{N}d: corr(signal,prior)={corr:+.3f} | prior_UP n={len(up)} sig={st(up)} | prior_DOWN n={len(dn)} sig={st(dn)}")

print("\n=== 4. RANDOM HOLIDAY control: non-holiday 1-day windows matched by era ===")
import random

random.seed(7)
ctrl = []
# sample from non-holiday trading days, same 2004-2026
holiday_il_set = set(g["i_last"] for g in holiday_gaps)
candidates = [i for i in range(2, len(dates) - 1) if i not in holiday_il_set]
for _ in range(5000):
    i = random.choice(candidates)
    bo = by_date[dates[i]]["open"]
    sc = by_date[dates[i + 1]]["close"]
    ctrl.append((sc / bo - 1) * 100)
print(f"Control (non-holiday open->close+1, 5000): {st(ctrl)}")

print("\n=== 5. POST-holiday drift (first_post open -> close) ===")


def post_ret(g):
    fp = g["first_post"]
    if fp not in by_date:
        return None
    r = by_date[fp]
    return (r["close"] / r["open"] - 1) * 100


print(f"POST first-day: {st([post_ret(g) for g in holiday_gaps if post_ret(g) is not None])}")
