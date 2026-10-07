# -*- coding: utf-8 -*-
"""
首板次日低吸战法 — 诚实回测。

战法逻辑（用户版）：首板涨停次日低开(-2%~-5%)低吸，博反包/震荡上行。
关键修正（T+1 制度）：D 日首板 → D+1 低开买入 → T+1 锁仓 → D+2 才能卖。
  用户写的"当日冲高止盈"在 A 股 T+1 下不可能（买入当日不能卖）。
  诚实口径：entry=D+1 open，exit=D+2 open（隔夜锁仓）或 D+2 close。

数据：zt_history(lbc=1 首板) + baostock_kline_cache(D/D+1/D+2 OHLC)。
窗口：D 在 2025-12-25 ~ 2026-09-16（需 D+1 D+2 kline，kline 终于 09-18）。

防 V1 假 edge 4 根因：
  R1 entry 非涨停价：entry=D+1 open（低开市场价），非 D close 涨停价 ✓
  R2 exit 非一字：排除 D+2 一字涨停（卖不掉）+ 一字跌停（虽能卖但 mark）
  R3 survivorship：首板股池本身是涨停股（强动量 universe），须对比 base 非首板
  R4 momentum 过滤：首板=已涨停（momentum 极强），对比高开追 vs 低吸拆分

不臆造：所有数字实算。
"""
import json
import math
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict

KLINE_DB = "/Users/lizhiwei/project/code/stock/Vibe-Research/.vibe-research/baostock_kline_cache.db"
ZT_DB = "/Users/lizhiwei/project/code/stock/Vibe-Research/.vibe-research/zt_history.db"

# ---- load zt_history: first-board (lbc=1) only ----
zdb = sqlite3.connect(ZT_DB)
zcur = zdb.cursor()
zcur.execute("SELECT date, code, lbc FROM zt_history")
zt_by_date = defaultdict(set)  # date -> set(code) all limit-up
first_board_by_date = defaultdict(set)  # date -> set(code) first-board only
all_zt_codes = set()
for d, c, lbc in zcur.fetchall():
    zt_by_date[d].add(c)
    all_zt_codes.add(c)
    if lbc == 1:
        first_board_by_date[d].add(c)
zdb.close()

cal = sorted(zt_by_date.keys())  # trading calendar
date_idx = {d: i for i, d in enumerate(cal)}


def next_td(d, k=1):
    i = date_idx.get(d)
    if i is None or i + k >= len(cal):
        return None
    return cal[i + k]


# ---- load kline ----
kdb = sqlite3.connect(KLINE_DB)
kcur = kdb.cursor()
kcur.execute("SELECT code, bars_json FROM kline")
code_bars = {}
for code, bj in kcur.fetchall():
    try:
        bars = json.loads(bj)
    except Exception:
        continue
    if isinstance(bars, list) and bars:
        code_bars[code] = bars
kdb.close()
print(f"loaded {len(code_bars)} codes kline", file=sys.stderr)

# index bars by date per code
code_map = {}  # code -> {date: bar}
code_dates = {}  # code -> sorted dates
for code, bars in code_bars.items():
    m = {b["date"]: b for b in bars if b.get("date")}
    if m:
        code_map[code] = m
        code_dates[code] = sorted(m.keys())

# ---- build first-board records ----
# D = first-board day. Need D, D+1, D+2 kline bars.
T_MIN, T_MAX = "2025-12-25", "2026-09-16"  # D range; D+2 <= 09-18

records = []
n_fb_total = 0
n_no_kline = 0
n_no_d1 = 0
n_no_d2 = 0

fb_dates = sorted(first_board_by_date.keys())
for d in fb_dates:
    if d < T_MIN or d > T_MAX:
        continue
    d1 = next_td(d, 1)
    d2 = next_td(d, 2)
    if d1 is None or d2 is None:
        continue
    for code in first_board_by_date[d]:
        n_fb_total += 1
        m = code_map.get(code)
        if m is None:
            n_no_kline += 1
            continue
        bar_d = m.get(d)
        bar_d1 = m.get(d1)
        bar_d2 = m.get(d2)
        if bar_d is None or bar_d1 is None:
            n_no_d1 += 1
            continue
        if bar_d2 is None:
            n_no_d2 += 1
            continue
        d_close = bar_d.get("close")  # = limit-up price
        d1_open = bar_d1.get("open")
        d1_close = bar_d1.get("close")
        d1_high = bar_d1.get("high")
        d1_low = bar_d1.get("low")
        d2_open = bar_d2.get("open")
        d2_close = bar_d2.get("close")
        d2_high = bar_d2.get("high")
        d2_low = bar_d2.get("low")
        if None in (d_close, d1_open, d1_close, d1_high, d1_low, d2_open, d2_close, d2_high, d2_low):
            continue
        if d_close <= 0 or d1_open <= 0:
            continue
        gap_pct = (d1_open - d_close) / d_close * 100  # D+1 open vs D close(涨停价). negative=low open
        # 一字涨停 D+1: open=close=high=low near limit-up → can't buy at low (locked up)
        # 一字涨停 D+2: can't sell
        d1_locked_up = (d1_open >= d_close * 0.995 and d1_low >= d_close * 0.995)  # D+1 一字涨停(开盘即封)
        d2_locked_up = (d2_open >= d1_close * 1.095 and d2_low >= d1_close * 1.095)  # D+2 一字涨停
        d2_locked_dn = (d2_open <= d1_close * 0.905 and d2_high <= d1_close * 0.905)  # D+2 一字跌停
        # is ST? (5% limit) — use isST field
        is_st = bar_d.get("isST") == "1"
        # board type by code prefix
        is_kcb = code.startswith("688")  # 科创板 20%
        is_cyb = code.startswith("30")   # 创业板 20%
        records.append({
            "code": code, "d": d, "d1": d1, "d2": d2,
            "d_close": d_close, "d1_open": d1_open, "d1_close": d1_close,
            "d1_high": d1_high, "d1_low": d1_low,
            "d2_open": d2_open, "d2_close": d2_close,
            "d2_high": d2_high, "d2_low": d2_low,
            "gap_pct": gap_pct,
            "d1_locked_up": d1_locked_up, "d2_locked_up": d2_locked_up,
            "d2_locked_dn": d2_locked_dn,
            "is_st": is_st, "is_kcb": is_kcb, "is_cyb": is_cyb,
        })

print(f"first-board records: {len(records)} (total fb {n_fb_total}, no_kline {n_no_kline}, no_d1 {n_no_d1}, no_d2 {n_no_d2})", file=sys.stderr)


def stats(name, recs, retfn, cost=0.003):
    """Compute return stats. cost=round-trip 0.3%."""
    if not recs:
        print(f"{name:52s} | n=0")
        return
    rets = [retfn(r) for r in recs]
    n = len(rets)
    mean = statistics.mean(rets)
    med = statistics.median(rets)
    wins = sum(1 for x in rets if x > 0)
    wr = wins / n
    net = mean - cost
    sd = statistics.stdev(rets) if n > 1 else 0
    se = sd / math.sqrt(n) if n > 1 else 0
    t = mean / se if se else 0
    # one-sided p (H1: mean>0)
    from math import erfc, sqrt
    z = t
    p_one = 0.5 * erfc(z / sqrt(2)) if z > 0 else 1 - 0.5 * erfc(-z / sqrt(2))
    # day-clustered: count unique days
    days = len(set(r["d"] for r in recs))
    print(f"{name:52s} | n={n:5d} days={days:3d} gross={mean*100:6.2f}% net~{net*100:6.2f}% med={med*100:6.2f}% WR={wr*100:5.1f}% t={t:5.2f} p1={p_one:.4f}")


# ---- return functions ----
# entry = D+1 open (buy at low-open market price, NOT limit-up price)
# exit D+2 open (overnight hold, T+1 forced — most conservative, sell at open)
def ret_d2_open(r):
    return (r["d2_open"] - r["d1_open"]) / r["d1_open"]


# exit D+2 close (hold full D+2)
def ret_d2_close(r):
    return (r["d2_close"] - r["d1_open"]) / r["d1_open"]


# exit D+2: if D+2 high touches +X%, take profit; else close
def ret_tp(tp_pct):
    def fn(r):
        tp_px = r["d1_open"] * (1 + tp_pct)
        if r["d2_high"] >= tp_px:
            return tp_pct
        return (r["d2_close"] - r["d1_open"]) / r["d1_open"]
    return fn


# stop loss: if D+2 low breaks -X%, exit at stop; else close (or tp)
def ret_stop(sl_pct, tp_pct=None):
    def fn(r):
        sl_px = r["d1_open"] * (1 - sl_pct)
        if r["d2_low"] <= sl_px:
            return -sl_pct
        if tp_pct is not None:
            tp_px = r["d1_open"] * (1 + tp_pct)
            if r["d2_high"] >= tp_px:
                return tp_pct
        return (r["d2_close"] - r["d1_open"]) / r["d1_open"]
    return fn


# realizability-aware: exclude D+1 一字涨停(买不到) + D+2 一字涨停(卖不掉)
def realizable(recs):
    out = [r for r in recs if not r["d1_locked_up"] and not r["d2_locked_up"]]
    excl_buy = sum(1 for r in recs if r["d1_locked_up"])
    excl_sell = sum(1 for r in recs if r["d1_locked_up"] == 0 and r["d2_locked_up"])
    return out, excl_buy, excl_sell


# ---- categorize by D+1 gap ----
def categorize(gap):
    if gap <= -5.0:
        return "deep_low(<-5%)"
    if -5.0 < gap <= -2.0:
        return "low_open(-5~-2%)"  # target bucket
    if -2.0 < gap <= 0.0:
        return "slight_low(-2~0%)"
    if 0.0 < gap <= 2.0:
        return "slight_high(0~+2%)"
    if 2.0 < gap <= 5.0:
        return "high_open(+2~+5%)"
    return "deep_high(>+5%)"


print("\n" + "=" * 100)
print("首板次日低吸战法 — entry=D+1 open, exit=D+2 (T+1 强制锁仓)")
print("  对比：低开(-5~-2%) vs 高开(+2~+5%) vs 全样本")
print("=" * 100)

# full sample first
print("\n--- 全首板样本（未过滤一字）---")
stats("ALL first-board → D+2 open", records, ret_d2_open)
stats("ALL first-board → D+2 close", records, ret_d2_close)

# by gap category
print("\n--- 按 D+1 开盘缺口分组（entry=D+1 open, exit=D+2 open）---")
cats = defaultdict(list)
for r in records:
    cats[categorize(r["gap_pct"])].append(r)
for cat in ["deep_low(<-5%)", "low_open(-5~-2%)", "slight_low(-2~0%)",
            "slight_high(0~+2%)", "high_open(+2~+5%)", "deep_high(>+5%)"]:
    stats(f"{cat} → D+2 open", cats.get(cat, []), ret_d2_open)

print("\n--- 按 D+1 开盘缺口分组（exit=D+2 close）---")
for cat in ["deep_low(<-5%)", "low_open(-5~-2%)", "slight_low(-2~0%)",
            "slight_high(0~+2%)", "high_open(+2~+5%)", "deep_high(>+5%)"]:
    stats(f"{cat} → D+2 close", cats.get(cat, []), ret_d2_close)

# ---- REALIZABILITY-AWARE (exclude 一字) ----
print("\n" + "=" * 100)
print("可实现口径（排除 D+1 一字涨停买不到 + D+2 一字涨停卖不掉）")
print("=" * 100)
real_all, eb, es = realizable(records)
print(f"全样本: {len(records)} → 可实现 {len(real_all)} (排除 D+1一字买不到 {eb}, D+2一字卖不掉 {es})")
stats("REAL ALL → D+2 open", real_all, ret_d2_open)
stats("REAL ALL → D+2 close", real_all, ret_d2_close)

print("\n--- 可实现 + 按 D+1 缺口分组（exit=D+2 open）---")
real_cats = defaultdict(list)
for r in real_all:
    real_cats[categorize(r["gap_pct"])].append(r)
for cat in ["deep_low(<-5%)", "low_open(-5~-2%)", "slight_low(-2~0%)",
            "slight_high(0~+2%)", "high_open(+2~+5%)", "deep_high(>+5%)"]:
    sub = real_cats.get(cat, [])
    stats(f"REAL {cat} → D+2 open", sub, ret_d2_open)

print("\n--- 可实现 + 按 D+1 缺口分组（exit=D+2 close）---")
for cat in ["deep_low(<-5%)", "low_open(-5~-2%)", "slight_low(-2~0%)",
            "slight_high(0~+2%)", "high_open(+2~+5%)", "deep_high(>+5%)"]:
    sub = real_cats.get(cat, [])
    stats(f"REAL {cat} → D+2 close", sub, ret_d2_close)

# ---- target: low_open(-5~-2%) realizability-aware stop/tp sensitivity ----
print("\n" + "=" * 100)
print("目标组 REAL low_open(-5~-2%) 止盈止损敏感性")
print("=" * 100)
target = real_cats.get("low_open(-5~-2%)", [])
stats("target → D+2 close (no TP/SL)", target, ret_d2_close)
for tp in [0.03, 0.05, 0.08, 0.10]:
    stats(f"target → TP {tp*100:.0f}% (else D+2 close)", target, ret_tp(tp))
print()
for sl in [0.03, 0.05, 0.08]:
    stats(f"target → SL {sl*100:.0f}% (else D+2 close)", target, ret_stop(sl))
print()
print("--- TP+SL 组合 ---")
for tp in [0.05, 0.08]:
    for sl in [0.03, 0.05]:
        stats(f"target → TP {tp*100:.0f}% / SL {sl*100:.0f}%", target, ret_stop(sl, tp))

# ---- "不破昨日涨停价" filter interpretation ----
# Interp: D+1 low stays above D close (涨停价). But if low-open -2~-5%, open is BELOW
# 涨停价, so low < open < 涨停价 → this filter would eliminate almost all low-open.
# Test the OPPOSITE interp: D+1 close recovers above some level (反包/企稳)
print("\n" + "=" * 100)
print('过滤：D+1 收盘企稳（close >= open，即当日不破开盘/反包迹象）')
print("=" * 100)
for cat in ["low_open(-5~-2%)", "slight_low(-2~0%)", "high_open(+2~+5%)"]:
    sub = [r for r in real_cats.get(cat, []) if r["d1_close"] >= r["d1_open"]]
    stats(f"REAL {cat} & D+1close>=D+1open → D+2 open", sub, ret_d2_open)
    stats(f"REAL {cat} & D+1close>=D+1open → D+2 close", sub, ret_d2_close)

# ---- D+1 intraday low-stop variant (buy at open, stop at D+1 low break) ----
# T+1: can't sell D+1. But if D+1 low breaks open*(1-sl), mark as "would stop D+2 open at sl"
print("\n" + "=" * 100)
print("变体：D+1 盘中破开盘止损标记（T+1 实际 D+2 open 执行）")
print("=" * 100)
for cat in ["low_open(-5~-2%)", "high_open(+2~+5%)"]:
    sub = real_cats.get(cat, [])
    n_break = sum(1 for r in sub if r["d1_low"] < r["d1_open"] * 0.97)
    print(f"{cat}: n={len(sub)} D+1破开盘3%数={n_break} ({n_break/max(len(sub),1)*100:.1f}%)")

# ---- survivorship / base comparison: non-first-board stocks next-day behavior ----
print("\n" + "=" * 100)
print("对照：非涨停股次日低开 D+2 收益（survivorship 检验）")
print("=" * 100)
# build non-ZT records: T-day non-limitup, D+1 low-open, entry=D+1 open exit=D+2
nzt_records = []
for code, ds in code_dates.items():
    m = code_map[code]
    for idx, d in enumerate(ds):
        if d < T_MIN or d > T_MAX:
            continue
        if code in zt_by_date.get(d, ()):
            continue  # skip limit-up day
        d1 = next_td(d, 1)
        d2 = next_td(d, 2)
        if d1 is None or d2 is None:
            continue
        bar_d = m.get(d)
        bar_d1 = m.get(d1)
        bar_d2 = m.get(d2)
        if bar_d is None or bar_d1 is None or bar_d2 is None:
            continue
        d_close = bar_d.get("close")
        d1_open = bar_d1.get("open")
        d2_open = bar_d2.get("open")
        d2_close = bar_d2.get("close")
        d1_low = bar_d1.get("low")
        d2_low = bar_d2.get("low")
        d2_high = bar_d2.get("high")
        d1_high = bar_d1.get("high")
        if None in (d_close, d1_open, d2_open, d2_close, d1_low, d2_low, d2_high, d1_high):
            continue
        if d_close <= 0 or d1_open <= 0:
            continue
        gap = (d1_open - d_close) / d_close * 100
        d1_locked = (d1_open >= d_close * 0.995 and d1_low >= d_close * 0.995)
        d2_locked_up = (d2_open >= bar_d1.get("close", d1_open) * 1.095 and d2_low >= bar_d1.get("close", d1_open) * 1.095)
        if d1_locked or d2_locked_up:
            continue
        nzt_records.append({"code": code, "d": d, "d_close": d_close, "d1_open": d1_open,
                            "d2_open": d2_open, "d2_close": d2_close, "d2_low": d2_low,
                            "d2_high": d2_high, "gap_pct": gap})
# sample down: too many non-ZT records, take random 20000 for speed
import random
random.seed(42)
if len(nzt_records) > 20000:
    nzt_records = random.sample(nzt_records, 20000)
nzt_low = [r for r in nzt_records if -5.0 < r["gap_pct"] <= -2.0]
nzt_high = [r for r in nzt_records if 2.0 < r["gap_pct"] <= 5.0]
def nr_open(r):
    return (r["d2_open"] - r["d1_open"]) / r["d1_open"]
def nr_close(r):
    return (r["d2_close"] - r["d1_open"]) / r["d1_open"]
stats("非涨停 低开(-5~-2%) → D+2 open (对照)", nzt_low, nr_open)
stats("非涨停 低开(-5~-2%) → D+2 close (对照)", nzt_low, nr_close)
stats("非涨停 高开(+2~+5%) → D+2 open (对照)", nzt_high, nr_open)
stats("非涨停 高开(+2~+5%) → D+2 close (对照)", nzt_high, nr_close)

# ---- regime: bull vs bear month distribution ----
print("\n" + "=" * 100)
print("月度分布（首板低开目标组）")
print("=" * 100)
target_all = real_cats.get("low_open(-5~-2%)", [])
mc = Counter(r["d"][:7] for r in target_all)
for mth in sorted(mc):
    print(f"  {mth}: {mc[mth]} picks")

# ---- high-open V1 comparison: high_open captures 涨停溢价? ----
print("\n" + "=" * 100)
print("V1 假 edge 检验：高开(+2~+5%) 是否含涨停封板溢价（D+2 涨停率）")
print("=" * 100)
for cat in ["low_open(-5~-2%)", "high_open(+2~+5%)"]:
    sub = real_cats.get(cat, [])
    if not sub:
        continue
    d2_zt = sum(1 for r in sub if r["d2_open"] >= r["d1_close"] * 1.095)
    print(f"{cat}: n={len(sub)} D+2涨停率={d2_zt/len(sub)*100:.1f}%")

print("\n" + "=" * 100)
print("诚实结论：低开低吸 vs 高开追 的 net return 对比 + 显著性")
print("=" * 100)
lo = real_cats.get("low_open(-5~-2%)", [])
ho = real_cats.get("high_open(+2~+5%)", [])
stats("LOW-OPEN 低吸 → D+2 close", lo, ret_d2_close)
stats("HIGH-OPEN 追 → D+2 close", ho, ret_d2_close)
print(f"\n低吸-追高 net 差 = {(statistics.mean([ret_d2_close(r) for r in lo]) - statistics.mean([ret_d2_close(r) for r in ho]))*100:.2f}% (gross, before cost)")
