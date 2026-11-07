# -*- coding: utf-8 -*-
"""长假节前 vs 月末月初 — 解耦分析

77% 节前 picks 与 turn-of-month 重叠。本脚本分离:
1. 节前 but NOT turn-of-month — edge 是否独立存活?
2. turn-of-month but NOT 节前 — 单独 lift 多少?
3. 元旦 vs January effect — 元旦正 vs 1月负, 哪个主导?
4. partial correlation: 节前 return ~ turn-of-month + momentum
"""

import json
import statistics
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from math import erf, sqrt

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

DATA = str(resolve_data_dir())
with open(f"{DATA}/index_ohlc_cache.json") as f:
    idx_data = json.load(f)

bars_sh = sorted(idx_data["sh.000001"], key=lambda b: b["date"])
calendar = [b["date"] for b in bars_sh]
bar_map = {b["date"]: b for b in bars_sh}

HOLIDAY_GAP = 4
ETF_COST = 0.10

holidays = []
for i in range(1, len(calendar)):
    d0 = datetime.strptime(calendar[i - 1], "%Y-%m-%d")
    d1 = datetime.strptime(calendar[i], "%Y-%m-%d")
    gap = (d1 - d0).days
    if gap >= HOLIDAY_GAP:
        holidays.append(
            {
                "last_before": calendar[i - 1],
                "first_after": calendar[i],
                "gap": gap,
                "idx_last": i - 1,
                "idx_first": i,
            }
        )


def classify_holiday(h):
    last_dt = datetime.strptime(h["last_before"], "%Y-%m-%d")
    month, gap = last_dt.month, h["gap"]
    if month in (1, 2) and gap >= 7:
        return "春节"
    if month in (9, 10) and gap >= 5:
        return "国庆"
    if month == 9 and gap < 5:
        return "中秋"
    if month in (4, 5) and 3 <= gap <= 6:
        return "清明" if month == 4 else "劳动节"
    if month == 6 and gap >= 3:
        return "端午"
    if month in (12, 1) and gap < 7:
        return "元旦"
    return "其他"


for h in holidays:
    h["type"] = classify_holiday(h)

# holiday zone for base rate exclusion
holiday_zone = set()
for h in holidays:
    for k in range(max(0, h["idx_last"] - 2), min(len(calendar), h["idx_last"] + 1)):
        holiday_zone.add(calendar[k])
    for k in range(h["idx_first"], min(len(calendar), h["idx_first"] + 2)):
        holiday_zone.add(calendar[k])


def stats(rets):
    n = len(rets)
    if n == 0:
        return {"n": 0, "mean": 0.0, "std": 0.0, "se": 0.0, "t": 0.0, "p": 1.0, "wr": 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = 0.5 * (1 - erf(t / sqrt(2))) if t > 0 else 1.0
    wr = sum(1 for x in rets if x > 0) / n
    return {"n": n, "mean": mean, "std": std, "se": se, "t": t, "p": p, "wr": wr}


def is_turn_of_month(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    ym = date_str[:7]
    month_days = [d for d in calendar if d[:7] == ym]
    if not month_days:
        return False
    return date_str in month_days[:3] or date_str in month_days[-3:]


def is_end_of_month(date_str):
    ym = date_str[:7]
    month_days = [d for d in calendar if d[:7] == ym]
    if not month_days:
        return False
    return date_str in month_days[-3:]


# base rate
base_returns = []
for i in range(len(calendar) - 1):
    d_start, d_end = calendar[i], calendar[i + 1]
    if d_start in holiday_zone or d_end in holiday_zone:
        continue
    b_s, b_e = bar_map[d_start], bar_map[d_end]
    o, c = b_s.get("open"), b_e.get("close")
    if o and c and o > 0:
        base_returns.append((c - o) / o * 100)
base_s = stats(base_returns)

print(f"Base rate: n={base_s['n']} EV={base_s['mean']:.4f}% WR={base_s['wr'] * 100:.1f}%")

# ---------- build pre-holiday picks ----------
pre_picks = []
for h in holidays:
    i_last = h["idx_last"]
    if i_last - 1 >= 0:
        d_buy, d_sell = calendar[i_last - 1], calendar[i_last]
        b_buy, b_sell = bar_map[d_buy], bar_map[d_sell]
        o, c = b_buy.get("open"), b_sell.get("close")
        if o and c and o > 0 and c > 0:
            ret = (c - o) / o * 100
            pre_picks.append(
                {
                    "type": h["type"],
                    "buy_date": d_buy,
                    "sell_date": d_sell,
                    "ret": ret,
                    "tom": is_turn_of_month(d_buy) or is_turn_of_month(d_sell),
                    "eom": is_end_of_month(d_buy) or is_end_of_month(d_sell),
                }
            )

# ---------- 1. Pre-holiday NOT overlapping turn-of-month ----------
print(f"\n{'=' * 70}")
print("1. PRE-HOLIDAY disentangled from turn-of-month")
print(f"{'=' * 70}")
pre_tom = [p for p in pre_picks if p["tom"]]
pre_not_tom = [p for p in pre_picks if not p["tom"]]
pre_all_s = stats([p["ret"] for p in pre_picks])
pre_tom_s = stats([p["ret"] for p in pre_tom])
pre_not_tom_s = stats([p["ret"] for p in pre_not_tom])
print(
    f"  All pre-holiday:           n={pre_all_s['n']} EV={pre_all_s['mean']:.3f}% WR={pre_all_s['wr'] * 100:.1f}% lift={pre_all_s['mean'] / base_s['mean']:.2f}x"
)
print(
    f"  Pre-holiday + ToM overlap: n={pre_tom_s['n']} EV={pre_tom_s['mean']:.3f}% WR={pre_tom_s['wr'] * 100:.1f}% lift={pre_tom_s['mean'] / base_s['mean']:.2f}x"
)
print(
    f"  Pre-holiday NOT ToM:       n={pre_not_tom_s['n']} EV={pre_not_tom_s['mean']:.3f}% WR={pre_not_tom_s['wr'] * 100:.1f}% lift={pre_not_tom_s['mean'] / base_s['mean']:.2f}x"
)
print(f"  -> If pre-not-Tom still > base => holiday effect independent of ToM")

# ---------- 2. Turn-of-month NOT overlapping pre-holiday ----------
print(f"\n{'=' * 70}")
print("2. TURN-OF-MONTH disentangled from pre-holiday")
print(f"{'=' * 70}")
# ToM windows = 2-day open->close where start is in last3/first3 of month
tom_all_rets = []
tom_not_pre_rets = []
tom_pre_rets = []
for i in range(len(calendar) - 1):
    d_start, d_end = calendar[i], calendar[i + 1]
    b_s, b_e = bar_map[d_start], bar_map[d_end]
    o, c = b_s.get("open"), b_e.get("close")
    if not (o and c and o > 0):
        continue
    ret = (c - o) / o * 100
    if is_turn_of_month(d_start):
        tom_all_rets.append(ret)
        # check if this overlaps a holiday window
        if d_start in holiday_zone or d_end in holiday_zone:
            tom_pre_rets.append(ret)
        else:
            tom_not_pre_rets.append(ret)

tom_all_s = stats(tom_all_rets)
tom_not_pre_s = stats(tom_not_pre_rets)
tom_pre_s = stats(tom_pre_rets)
print(
    f"  All ToM:              n={tom_all_s['n']} EV={tom_all_s['mean']:.4f}% WR={tom_all_s['wr'] * 100:.1f}% lift={tom_all_s['mean'] / base_s['mean']:.2f}x"
)
print(
    f"  ToM NOT pre-holiday:  n={tom_not_pre_s['n']} EV={tom_not_pre_s['mean']:.4f}% WR={tom_not_pre_s['wr'] * 100:.1f}% lift={tom_not_pre_s['mean'] / base_s['mean']:.2f}x"
)
print(
    f"  ToM + pre-holiday:    n={tom_pre_s['n']} EV={tom_pre_s['mean']:.4f}% WR={tom_pre_s['wr'] * 100:.1f}% lift={tom_pre_s['mean'] / base_s['mean']:.2f}x"
)
print(f"  -> If ToM-not-pre ~ base => ToM effect is actually holiday effect, not ToM")

# ---------- 3. January effect vs 元旦 ----------
print(f"\n{'=' * 70}")
print("3. JANUARY effect vs 元旦 (holiday)")
print(f"{'=' * 70}")
# January non-holiday
jan_not_pre = []
for i in range(len(calendar) - 1):
    d_start, d_end = calendar[i], calendar[i + 1]
    if d_start in holiday_zone or d_end in holiday_zone:
        continue
    if d_start[5:7] == "01":
        b_s, b_e = bar_map[d_start], bar_map[d_end]
        o, c = b_s.get("open"), b_e.get("close")
        if o and c and o > 0:
            jan_not_pre.append((c - o) / o * 100)
jan_s = stats(jan_not_pre)
print(
    f"  January (non-holiday): n={jan_s['n']} EV={jan_s['mean']:.4f}% WR={jan_s['wr'] * 100:.1f}% lift={jan_s['mean'] / base_s['mean']:.2f}x"
)
yuan = [p for p in pre_picks if p["type"] == "元旦"]
yuan_s = stats([p["ret"] for p in yuan])
print(
    f"  元旦 pre-holiday:       n={yuan_s['n']} EV={yuan_s['mean']:.3f}% WR={yuan_s['wr'] * 100:.1f}% lift={yuan_s['mean'] / base_s['mean']:.2f}x"
)
print(f"  -> 元旦 positive + January non-holiday negative => holiday-specific, not January effect")

# ---------- 4. Partial: pre-holiday return controlling for ToM ----------
print(f"\n{'=' * 70}")
print("4. PARTIAL: pre-holiday return controlling for turn-of-month")
print(f"{'=' * 70}")
# Dummy regression: pre_ret = a + b1*is_pre_holiday + b2*is_tom + e
# But pre-holiday windows are all 2-day. Let's compare:
# Group A: pre-holiday + ToM overlap
# Group B: ToM but not pre-holiday
# Group C: pre-holiday but not ToM
# Group D: neither (base rate)
a_rets = [p["ret"] for p in pre_picks if p["tom"]]
b_rets = tom_not_pre_rets
c_rets = [p["ret"] for p in pre_picks if not p["tom"]]
d_rets = base_returns
print(f"  A: pre+holiday+ToM:     n={len(a_rets)} EV={sum(a_rets) / len(a_rets) if a_rets else 0:.3f}%")
print(f"  B: ToM not pre-holiday: n={len(b_rets)} EV={sum(b_rets) / len(b_rets) if b_rets else 0:.4f}%")
print(f"  C: pre-holiday not ToM: n={len(c_rets)} EV={sum(c_rets) / len(c_rets) if c_rets else 0:.3f}%")
print(f"  D: base (neither):      n={len(d_rets)} EV={sum(d_rets) / len(d_rets) if d_rets else 0:.4f}%")
print(f"  -> A-C = ToM contribution; C-D = pure holiday contribution; A-D = combined")

# ---------- 5. Decay check by holiday type ----------
print(f"\n{'=' * 70}")
print("5. DECAY by type (train/test split)")
print(f"{'=' * 70}")
for htype in ["春节", "国庆", "清明", "元旦"]:
    sub = [p for p in pre_picks if p["type"] == htype]
    sub = sorted(sub, key=lambda p: p["buy_date"])
    n = len(sub)
    if n < 6:
        continue
    mid = n // 2
    train = sub[:mid]
    test = sub[mid:]
    tr_s = stats([p["ret"] for p in train])
    te_s = stats([p["ret"] for p in test])
    print(
        f"  {htype}: train n={len(train)} EV={tr_s['mean']:.3f}% | test n={len(test)} EV={te_s['mean']:.3f}% WR={te_s['wr'] * 100:.1f}%"
    )

# ---------- 6. Non-holiday-specific test: any 4+ day gap ----------
print(f"\n{'=' * 70}")
print("6. CONTROL: weekend gap (Fri->Mon, 3-day gap, NON-holiday)")
print(f"{'=' * 70}")
# Normal weekend = gap 3 (Fri close -> Mon open). But our pre-holiday uses 2-day open->close.
# Compare: regular Mon (buy open) -> Tue (sell close) when NOT pre-holiday
mon_rets = []
for i in range(len(calendar) - 1):
    d_start = calendar[i]
    dt = datetime.strptime(d_start, "%Y-%m-%d")
    if d_start in holiday_zone:
        continue
    if dt.weekday() == 0:  # Monday
        d_end = calendar[i + 1]
        if d_end in holiday_zone:
            continue
        b_s, b_e = bar_map[d_start], bar_map[d_end]
        o, c = b_s.get("open"), b_e.get("close")
        if o and c and o > 0:
            mon_rets.append((c - o) / o * 100)
mon_s = stats(mon_rets)
print(
    f"  Monday open->Tue close (non-holiday): n={mon_s['n']} EV={mon_s['mean']:.4f}% WR={mon_s['wr'] * 100:.1f}% lift={mon_s['mean'] / base_s['mean']:.2f}x"
)
print(f"  -> If Monday ~ base => no weekend-gap premium; holiday effect is distinct")

# ---------- 7. 2022 后分层（验证 TOM 死延伸，2026-10-07 加）----------
print(f"\n{'=' * 70}")
print("7. 2022 后分层（TOM 2022 后死，验 A 组是否也死）")
pre_2022 = [p for p in pre_picks if p["buy_date"] >= "2022-01-01"]
a22 = [p["ret"] for p in pre_2022 if p["tom"]]
c22 = [p["ret"] for p in pre_2022 if not p["tom"]]
print(f"  2022 后 A (pre+ToM): n={len(a22)} EV={sum(a22) / len(a22) if a22 else 0:.3f}%")
print(f"  2022 后 C (pre非ToM): n={len(c22)} EV={sum(c22) / len(c22) if c22 else 0:.3f}%")
if a22:
    s22 = stats(a22)
    print(f"  2022 后 A stats: mean={s22['mean']:.3f}% WR={s22['wr'] * 100:.1f}% n={s22['n']}")
print(f"  -> 若 2022 后 A 仍正显著 → 节假日放大 TOM 独立于 TOM 死；若 FAIL → 长假节前真死")
