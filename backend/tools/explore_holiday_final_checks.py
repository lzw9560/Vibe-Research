# -*- coding: utf-8 -*-
"""Final check: end-of-month disentanglement + type×ToM cross-tab + lag structure"""

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
import json
import statistics
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from math import erf, sqrt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

DATA = str(resolve_data_dir())
with open(f"{DATA}/index_ohlc_cache.json") as f:
    idx_data = json.load(f)

bars_sh = sorted(idx_data["sh.000001"], key=lambda b: b["date"])
calendar = [b["date"] for b in bars_sh]
bar_map = {b["date"]: b for b in bars_sh}

HOLIDAY_GAP = 4

holidays = []
for i in range(1, len(calendar)):
    d0 = datetime.strptime(calendar[i - 1], "%Y-%m-%d")
    d1 = datetime.strptime(calendar[i], "%Y-%m-%d")
    gap = (d1 - d0).days
    if gap >= HOLIDAY_GAP:
        holidays.append({"last_before": calendar[i - 1], "first_after": calendar[i], "gap": gap, "idx_last": i - 1, "idx_first": i})


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


def is_eom(date_str):
    ym = date_str[:7]
    month_days = [d for d in calendar if d[:7] == ym]
    if not month_days:
        return False
    return date_str in month_days[-3:]


def is_bom(date_str):
    ym = date_str[:7]
    month_days = [d for d in calendar if d[:7] == ym]
    if not month_days:
        return False
    return date_str in month_days[:3]


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
                    "eom": is_eom(d_buy) or is_eom(d_sell),
                    "bom": is_bom(d_buy) or is_bom(d_sell),
                }
            )

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

print(f"Base: n={base_s['n']} EV={base_s['mean']:.4f}%")

# ---------- End-of-month disentanglement ----------
print(f"\n{'=' * 70}")
print("END-OF-MONTH disentanglement")
print(f"{'=' * 70}")
pre_eom = [p for p in pre_picks if p["eom"]]
pre_not_eom = [p for p in pre_picks if not p["eom"]]
s_eom = stats([p["ret"] for p in pre_eom])
s_not_eom = stats([p["ret"] for p in pre_not_eom])
print(
    f"  Pre-holiday + EoM:     n={s_eom['n']} EV={s_eom['mean']:.3f}% WR={s_eom['wr'] * 100:.1f}% lift={s_eom['mean'] / base_s['mean']:.2f}x"
)
print(
    f"  Pre-holiday NOT EoM:  n={s_not_eom['n']} EV={s_not_eom['mean']:.3f}% WR={s_not_eom['wr'] * 100:.1f}% lift={s_not_eom['mean'] / base_s['mean']:.2f}x"
)

# ---------- Type × ToM cross-tab ----------
print(f"\n{'=' * 70}")
print("TYPE × turn-of-month cross-tab")
print(f"{'=' * 70}")
print(f"{'Type':<6} {'ToM?':<5} {'n':>4} {'EV%':>8} {'WR%':>6} {'lift':>6}")
for htype in ["春节", "国庆", "清明", "元旦", "端午", "中秋"]:
    for tom_flag in [True, False]:
        sub = [p for p in pre_picks if p["type"] == htype and (p["eom"] or p["bom"]) == tom_flag]
        if not sub:
            continue
        s = stats([p["ret"] for p in sub])
        lift = s["mean"] / base_s["mean"] if base_s["mean"] != 0 else 0
        print(f"  {htype:<6} {'ToM' if tom_flag else 'mid':<5} {s['n']:>4} {s['mean']:>8.3f} {s['wr'] * 100:>6.1f} {lift:>5.2f}x")

# ---------- Lag structure: which days carry the edge? ----------
print(f"\n{'=' * 70}")
print("LAG structure: which day carries the edge? (day-2 vs day-1)")
print(f"{'=' * 70}")
# Pre-holiday: buy day-2 open, sell day-1 close. This is a 2-bar window.
# Split into: day-2 open->close (intraday 1) vs day-1 open->close (intraday 2)
# vs day-2 close -> day-1 open (overnight gap between them)
day2_intraday = []
day1_intraday = []
overnight = []
for h in holidays:
    i_last = h["idx_last"]
    if i_last - 1 >= 0:
        b_d2 = bar_map.get(calendar[i_last - 1])
        b_d1 = bar_map.get(calendar[i_last])
        if b_d2 and b_d1:
            o2, c2 = b_d2.get("open"), b_d2.get("close")
            o1, c1 = b_d1.get("open"), b_d1.get("close")
            if all(v and v > 0 for v in [o2, c2, o1, c1]):
                day2_intraday.append((c2 - o2) / o2 * 100)  # day-2 intraday
                overnight.append((o1 - c2) / c2 * 100)  # overnight gap d2->d1
                day1_intraday.append((c1 - o1) / o1 * 100)  # day-1 intraday

s_d2 = stats(day2_intraday)
s_on = stats(overnight)
s_d1 = stats(day1_intraday)
print(f"  Day-2 intraday (o->c):  n={s_d2['n']} EV={s_d2['mean']:.3f}% WR={s_d2['wr'] * 100:.1f}%")
print(f"  Overnight gap (c->o):   n={s_on['n']} EV={s_on['mean']:.3f}% WR={s_on['wr'] * 100:.1f}%")
print(f"  Day-1 intraday (o->c):  n={s_d1['n']} EV={s_d1['mean']:.3f}% WR={s_d1['wr'] * 100:.1f}%")
print(f"  -> If overnight carries edge => gap/overnight premium (risk premium for holiday)")
print(f"  -> If day-1 intraday carries => last-day bidding up (窗口关闭前抢筹)")

# ---------- Verify 元旦 dates ----------
print(f"\n{'=' * 70}")
print("VERIFY 元旦 classified dates")
print(f"{'=' * 70}")
yuan = [p for p in pre_picks if p["type"] == "元旦"]
for p in yuan:
    print(f"  buy={p['buy_date']} sell={p['sell_date']} ret={p['ret']:.2f}% ToM={p['eom'] or p['bom']}")

# ---------- Quarter-end effect ----------
print(f"\n{'=' * 70}")
print("QUARTER-END effect (Mar/Jun/Sep/Dec last 3 days)")
print(f"{'=' * 70}")
qe_rets = []
for i in range(len(calendar) - 1):
    d_start = calendar[i]
    if d_start in holiday_zone:
        continue
    dt = datetime.strptime(d_start, "%Y-%m-%d")
    if dt.month in (3, 6, 9, 12) and is_eom(d_start):
        d_end = calendar[i + 1]
        if d_end in holiday_zone:
            continue
        b_s, b_e = bar_map[d_start], bar_map[d_end]
        o, c = b_s.get("open"), b_e.get("close")
        if o and c and o > 0:
            qe_rets.append((c - o) / o * 100)
qe_s = stats(qe_rets)
print(f"  Quarter-end ToM: n={qe_s['n']} EV={qe_s['mean']:.4f}% WR={qe_s['wr'] * 100:.1f}% lift={qe_s['mean'] / base_s['mean']:.2f}x")
print(f"  -> If Q-end > regular ToM => quarter-end window dressing amplifies")
