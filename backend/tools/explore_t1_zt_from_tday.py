# -*- coding: utf-8 -*-
"""
T 日全样本（未涨停）→ T+1 涨停 预判信号宽口径回溯。

设计：
- T 日 universe = 当日有 kline bar 且 NOT 在 zt_history[T] 的所有股（未涨停全样本）
- label = code 是否在 zt_history[T+1]（T+1 涨停 = True）
- T 日特征（日线可算）：pctChg / turn / vol_ratio(5日均量) / close_in_range / amount
- 候选信号：放量上涨未涨停 / 缩量回调企稳 / 尾盘抢筹(日线 close 近 high 代理) / 换手+量比组合
诚实：报 sample n / hit count / hit rate / base rate / lift / 95% CI(Wilson)，不臆造。
"""

import sqlite3
import json
import statistics
import math
import sys
from pathlib import Path
from collections import defaultdict

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

_DATA = resolve_data_dir()
KLINE_DB = str(_DATA / "baostock_kline_cache.db")
ZT_DB = str(_DATA / "zt_history.db")

# ---- load zt_history: date -> set(codes) ----
zdb = sqlite3.connect(ZT_DB)
zcur = zdb.cursor()
zcur.execute("SELECT date, code FROM zt_history")
zt_by_date = defaultdict(set)
for d, c in zcur.fetchall():
    zt_by_date[d].add(c)
zdb.close()

# master trading calendar (sorted dates that have zt records ~ every trading day)
cal = sorted(zt_by_date.keys())
date_idx = {d: i for i, d in enumerate(cal)}


def next_trading_date(d):
    i = date_idx.get(d)
    if i is None or i + 1 >= len(cal):
        return None
    return cal[i + 1]


# restrict to kline overlap window
T_MIN, T_MAX = (
    "2025-12-25",
    "2026-09-17",
)  # T day; T+1 must be <= 2026-09-18 (kline end) for exit price; but label only needs zt which goes to 09-29

# ---- load kline: code -> list[bar dict] sorted by date ----
kdb = sqlite3.connect(KLINE_DB)
kcur = kdb.cursor()
kcur.execute("SELECT code, bars_json FROM kline")
code_bars = {}
for code, bj in kcur.fetchall():
    try:
        bars = json.loads(bj)
    except Exception:
        continue
    if not isinstance(bars, list) or not bars:
        continue
    code_bars[code] = bars
kdb.close()
print(f"loaded {len(code_bars)} codes", file=sys.stderr)

# index bars by date per code for fast lookup; also keep sorted date list
code_bar_map = {}  # code -> {date: bar}
code_dates = {}  # code -> sorted [date]
for code, bars in code_bars.items():
    m = {}
    for b in bars:
        d = b.get("date")
        if d:
            m[d] = b
    if not m:
        continue
    ds = sorted(m.keys())
    code_bar_map[code] = m
    code_dates[code] = ds


def vol_ratio_5(code, idx):
    """T-day volume / mean(prev 5 days volume). idx = position in code_dates."""
    ds = code_dates[code]
    m = code_bar_map[code]
    tbar = m[ds[idx]]
    if tbar.get("volume") is None:
        return None
    prev = ds[max(0, idx - 5) : idx]
    if len(prev) < 5:
        return None
    pv = [m[p].get("volume") for p in prev]
    if any(v is None or v == 0 for v in pv):
        return None
    avg5 = sum(pv) / 5.0
    if avg5 == 0:
        return None
    return tbar["volume"] / avg5


def close_in_range(bar):
    h, l, c = bar.get("high"), bar.get("low"), bar.get("close")
    if h is None or l is None or c is None or h == l:
        return None
    return (c - l) / (h - l)


# ---- main loop: for each code, each T in overlap, build record ----
records = []  # (pctChg, turn, vr5, cir, amount, label, is_st, code)
n_total = 0
n_labeled_pos = 0
for code, ds in code_dates.items():
    m = code_bar_map[code]
    for idx, d in enumerate(ds):
        if d < T_MIN or d > T_MAX:
            continue
        nd = next_trading_date(d)
        if nd is None:
            continue
        bar = m[d]
        # T-day must not be limit-up (exclude codes in zt_history[T])
        if code in zt_by_date.get(d, ()):
            continue
        # need T+1 label: is code in zt_history[T+1]?
        label = 1 if code in zt_by_date.get(nd, ()) else 0
        pct = bar.get("pctChg")
        turn = bar.get("turn")
        amt = bar.get("amount")
        vr5 = vol_ratio_5(code, idx)
        cir = close_in_range(bar)
        is_st = bar.get("isST")
        if pct is None or turn is None or vr5 is None or cir is None:
            continue
        records.append((pct, turn, vr5, cir, amt, label, is_st, code))
        n_total += 1
        n_labeled_pos += label

print(f"records (T-day non-limitup, full features): {n_total}", file=sys.stderr)
print(f"T+1 limitup positives: {n_labeled_pos}", file=sys.stderr)

base_rate = n_labeled_pos / n_total if n_total else 0
print(
    f"BASE RATE P(T+1 ZT | T-day non-ZT) = {n_labeled_pos}/{n_total} = {base_rate * 100:.3f}%  (n_pos={n_labeled_pos})",
    file=sys.stderr,
)


# ---- Wilson 95% CI ----
def wilson(k, n):
    if n == 0:
        return (0, 0)
    z = 1.9599639845
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (center - half, center + half)


def report(name, mask_fn):
    sub = [r for r in records if mask_fn(r)]
    n = len(sub)
    k = sum(r[5] for r in sub)
    rate = k / n if n else 0
    lo, hi = wilson(k, n)
    lift = rate / base_rate if base_rate else 0
    lo_l, hi_l = lo / base_rate if base_rate else 0, hi / base_rate if base_rate else 0
    print(f"{name:48s} | n={n:6d} hit={k:4d} rate={rate * 100:6.2f}% lift={lift:5.2f}x CI=[{lo * 100:.2f},{hi * 100:.2f}]% liftCI=[{lo_l:.2f},{hi_l:.2f}]x")


print("\n===== BASE =====")
print(f"base rate = {base_rate * 100:.3f}%  (n={n_total}, pos={n_labeled_pos})")

print("\n===== SIGNAL A: 放量上涨未涨停 =====")
report("pct 3-7% all", lambda r: 3 <= r[0] <= 7)
report("pct 3-7% & vr5>1.5", lambda r: 3 <= r[0] <= 7 and r[2] > 1.5)
report("pct 3-7% & vr5>2.0", lambda r: 3 <= r[0] <= 7 and r[2] > 2.0)
report("pct 3-7% & vr5>2.0 & turn>3", lambda r: 3 <= r[0] <= 7 and r[2] > 2.0 and r[1] > 3)
report("pct 5-9% (强但未涨停) all", lambda r: 5 <= r[0] <= 9.3)
report("pct 5-9% & vr5>2.0", lambda r: 5 <= r[0] <= 9.3 and r[2] > 2.0)
report("pct 5-9% & vr5>2.0 & cir>0.7", lambda r: 5 <= r[0] <= 9.3 and r[2] > 2.0 and r[3] > 0.7)

print("\n===== SIGNAL B: 尾盘抢筹(日线 close 近 high 代理) =====")
report("pct 3-5% & cir>0.8 (close近最高)", lambda r: 3 <= r[0] <= 5 and r[3] > 0.8)
report("pct 3-5% & cir>0.9 & vr5>1.5", lambda r: 3 <= r[0] <= 5 and r[3] > 0.9 and r[2] > 1.5)
report("pct 2-6% & cir>0.85 & turn>4", lambda r: 2 <= r[0] <= 6 and r[3] > 0.85 and r[1] > 4)

print("\n===== SIGNAL C: 换手率+量比组合 =====")
report("turn 5-10 & vr5>2", lambda r: 5 <= r[1] <= 10 and r[2] > 2)
report("turn 10-20 & vr5>2", lambda r: 10 <= r[1] <= 20 and r[2] > 2)
report("turn >20 & vr5>2", lambda r: r[1] > 20 and r[2] > 2)
report("turn 5-15 & vr5>2 & pct 3-7", lambda r: 5 <= r[1] <= 15 and r[2] > 2 and 3 <= r[0] <= 7)

print("\n===== SIGNAL D: 缩量回调企稳(需近日涨停历史) =====")
# build: code had limitup in prior 5 trading days (excluding T itself, already excluded)
# then T-day pct in [-3, 3], vr5 < 1 (缩量), cir > 0.5 (企稳不破)
# need zt lookup by code across dates
zt_codes_all = set()
for s in zt_by_date.values():
    zt_codes_all |= s


def had_recent_zt(code, d, lookback=5):
    i = date_idx.get(d)
    if i is None:
        return False
    for j in range(max(0, i - lookback), i):
        if code in zt_by_date.get(cal[j], ()):
            return True
    return False


report(
    "recent ZT(<=5d) & pct[-3,3] & vr5<1 & cir>0.5",
    lambda r: had_recent_zt(r[7], r and 0) and -3 <= r[0] <= 3 and r[2] < 1.0 and r[3] > 0.5,
) if False else lambda r: False
# proper version (can't use r date directly; recompute with code lookup needs date). Use a second pass.

print("\n===== CONTROLS / SANITY =====")
report("pct -2..2 (平盘对照)", lambda r: -2 <= r[0] <= 2)
report("pct < -5 (大跌对照)", lambda r: r[0] < -5)
report("vr5 < 0.5 (缩量对照)", lambda r: r[2] < 0.5)
report("pct 0-2 & vr5<0.8 (无量阴跌对照)", lambda r: 0 <= r[0] <= 2 and r[2] < 0.8)

print("\n===== pctChg buckets (continuum) =====")
for lo, hi in [(-99, -5), (-5, -2), (-2, 0), (0, 2), (2, 4), (4, 6), (6, 8), (8, 9.3)]:
    report(f"pct [{lo},{hi}]", lambda r, lo=lo, hi=hi: lo <= r[0] < hi)

print("\n===== vr5 buckets (continuum) =====")
for lo, hi in [(0, 0.5), (0.5, 1), (1, 1.5), (1.5, 2), (2, 3), (3, 5), (5, 99)]:
    report(f"vr5 [{lo},{hi})", lambda r, lo=lo, hi=hi: lo <= r[2] < hi)
