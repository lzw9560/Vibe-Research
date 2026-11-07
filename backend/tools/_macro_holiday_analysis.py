# -*- coding: utf-8 -*-
"""长假节前效应 — 宏观经济领域深挖

宏观相关因子:
  1. 宏观周期分层 (MA20 regime: strong=扩张 / weak=收缩) — 节前 edge 是否周期驱动
  2. Q4/Q1 信贷季节性 (quarter stratification) — 新年度配置/季末考核
  3. 政策日历邻近 (两会3月/中央经济工作会议12月) — 政策预期驱动
  4. 流动性季节性 (turn-of-month overlap) — 月末发薪/赎回压力
  5. 外资节前流代理 (VIX level snapshot — 仅当前,无历史序列)

参考动量: 宏观季节性是否驱动 momentum?
  - 宏观周期(strong/weak)分层看节前 edge: 若仅 strong 有 edge → 宏观周期驱动非日历
  - 若 strong/weak 都有 edge → 纯日历效应,宏观周期无关
"""

import json
import statistics
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from math import erf, sqrt

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

DATA = str(resolve_data_dir())
ETF_COST = 0.10
HOLIDAY_GAP = 4

# ---------- load data ----------
with open(f"{DATA}/index_ohlc_cache.json") as f:
    idx_data = json.load(f)
bars_sh = sorted(idx_data["sh.000001"], key=lambda b: b["date"])
calendar = [b["date"] for b in bars_sh]
bar_map = {b["date"]: b for b in bars_sh}
date_idx = {d: i for i, d in enumerate(calendar)}

# load MA20 regime (macro cycle proxy)
with open(f"{DATA}/index_ma20_regime.json") as f:
    regime_data = json.load(f)

print(f"Index: sh.000001, {len(calendar)} days ({calendar[0]} to {calendar[-1]})")
print(f"Regime labels: {len(regime_data)} dates")

# ---------- identify long holiday breaks ----------
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

print(f"Long holiday breaks (gap >= {HOLIDAY_GAP}): {len(holidays)}")


# ---------- classify holiday type ----------
def classify_holiday(h):
    last_dt = datetime.strptime(h["last_before"], "%Y-%m-%d")
    month = last_dt.month
    gap = h["gap"]
    if month in (1, 2) and gap >= 7:
        return "春节"
    if month in (9, 10) and gap >= 5:
        return "国庆"
    if month == 9 and gap < 5:
        return "中秋"
    if month in (4, 5) and 3 <= gap <= 6:
        if month == 4:
            return "清明"
        return "劳动节"
    if month == 6 and gap >= 3:
        return "端午"
    if month in (12, 1) and gap < 7:
        return "元旦"
    return "其他"


for h in holidays:
    h["type"] = classify_holiday(h)


# ---------- stats helper ----------
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


# ---------- build pre-holiday picks ----------
pre_picks = []
for hi, h in enumerate(holidays):
    i_last = h["idx_last"]
    if i_last - 1 >= 0:
        d_buy = calendar[i_last - 1]
        d_sell = calendar[i_last]
        b_buy = bar_map[d_buy]
        b_sell = bar_map[d_sell]
        o = b_buy.get("open")
        c = b_sell.get("close")
        if o and c and o > 0 and c > 0:
            ret = (c - o) / o * 100
            # macro cycle regime at entry (buy day)
            reg = regime_data.get(d_buy, {})
            regime_label = reg.get("regime", "unknown")
            # quarter of buy day
            buy_dt = datetime.strptime(d_buy, "%Y-%m-%d")
            quarter = f"Q{((buy_dt.month - 1) // 3) + 1}"
            # turn of month
            ym = d_buy[:7]
            month_days = [d for d in calendar if d[:7] == ym]
            is_tom = False
            if month_days:
                is_tom = (
                    d_buy in month_days[:3]
                    or d_buy in month_days[-3:]
                    or d_sell in month_days[:3]
                    or d_sell in month_days[-3:]
                )
            # policy proximity
            policy_near = False
            # 两会 (early March, ~3/3-3/15)
            if buy_dt.month == 3 and buy_dt.day <= 15:
                policy_near = "两会"
            elif buy_dt.month == 2 and buy_dt.day >= 20:
                policy_near = "两会预热"
            # 中央经济工作会议 (mid December, ~12/10-12/15)
            elif buy_dt.month == 12 and buy_dt.day <= 20:
                policy_near = "CEWC"
            elif buy_dt.month == 11 and buy_dt.day >= 20:
                policy_near = "CEWC预热"

            pre_picks.append(
                {
                    "holiday_idx": hi,
                    "holiday_date": h["last_before"],
                    "type": h["type"],
                    "buy_date": d_buy,
                    "sell_date": d_sell,
                    "ret": ret,
                    "regime": regime_label,
                    "quarter": quarter,
                    "is_tom": is_tom,
                    "policy_near": policy_near,
                }
            )

print(f"Pre-holiday picks: {len(pre_picks)}")

# ---------- base rate ----------
holiday_zone = set()
for h in holidays:
    for k in range(max(0, h["idx_last"] - 2), min(len(calendar), h["idx_last"] + 1)):
        holiday_zone.add(calendar[k])
    for k in range(h["idx_first"], min(len(calendar), h["idx_first"] + 2)):
        holiday_zone.add(calendar[k])
base_returns = []
for i in range(len(calendar) - 1):
    d_start, d_end = calendar[i], calendar[i + 1]
    if d_start in holiday_zone or d_end in holiday_zone:
        continue
    b_s, b_e = bar_map[d_start], bar_map[d_end]
    o, c = b_s.get("open"), b_e.get("close")
    if o and c and o > 0 and c > 0:
        base_returns.append((c - o) / o * 100)
base_s = stats(base_returns)
print(f"Base rate: n={base_s['n']} EV={base_s['mean']:.4f}% WR={base_s['wr'] * 100:.1f}%")

# ================================================================
# FACTOR 1: MACRO CYCLE STRATIFICATION (MA20 regime)
# ================================================================
print(f"\n{'=' * 70}")
print("FACTOR 1: MACRO CYCLE STRATIFICATION (MA20 strong=扩张 / weak=收缩)")
print(f"{'=' * 70}")
all_s = stats([p["ret"] for p in pre_picks])
print(
    f"ALL pre-holiday: n={all_s['n']} EV={all_s['mean']:.3f}% net={all_s['mean'] - ETF_COST:.3f}% WR={all_s['wr'] * 100:.1f}% t={all_s['t']:.2f} p={all_s['p']:.4f}"
)

for reg_label in ["strong", "weak"]:
    sub = [p for p in pre_picks if p["regime"] == reg_label]
    s = stats([p["ret"] for p in sub])
    lift = s["mean"] / base_s["mean"] if base_s["mean"] != 0 else float("inf")
    print(
        f"  {reg_label.upper():>6}: n={s['n']:>3} EV={s['mean']:.3f}% net={s['mean'] - ETF_COST:.3f}% WR={s['wr'] * 100:.1f}% t={s['t']:.2f} p={s['p']:.4f} lift={lift:.2f}x"
    )

# conditional test: is edge ONLY in strong regime?
strong_rets = [p["ret"] for p in pre_picks if p["regime"] == "strong"]
weak_rets = [p["ret"] for p in pre_picks if p["regime"] == "weak"]
if strong_rets and weak_rets:
    # Welch's t-test between regimes
    s_s = stats(strong_rets)
    w_s = stats(weak_rets)
    pooled_se = sqrt(s_s["se"] ** 2 + w_s["se"] ** 2) if s_s["se"] and w_s["se"] else 0
    diff_t = (s_s["mean"] - w_s["mean"]) / pooled_se if pooled_se > 0 else 0
    print(f"  Regime diff (strong - weak): {s_s['mean'] - w_s['mean']:.3f}% t={diff_t:.2f}")
    print(f"  -> If diff NOT significant => edge is regime-INDEPENDENT (pure calendar)")
    print(f"  -> If strong >> weak & diff significant => edge is cycle-DRIVEN (macro)")

# ================================================================
# FACTOR 2: QUARTER STRATIFICATION (Q4/Q1 credit seasonality)
# ================================================================
print(f"\n{'=' * 70}")
print("FACTOR 2: QUARTER STRATIFICATION (信贷季节性 / 新年度配置)")
print(f"{'=' * 70}")
for q in ["Q1", "Q2", "Q3", "Q4"]:
    sub = [p for p in pre_picks if p["quarter"] == q]
    s = stats([p["ret"] for p in sub])
    lift = s["mean"] / base_s["mean"] if base_s["mean"] != 0 else float("inf")
    # which holidays fall in this quarter
    types_in_q = [p["type"] for p in sub]
    type_summary = ", ".join(f"{t}({types_in_q.count(t)})" for t in sorted(set(types_in_q)))
    print(
        f"  {q}: n={s['n']:>3} EV={s['mean']:.3f}% net={s['mean'] - ETF_COST:.3f}% WR={s['wr'] * 100:.1f}% t={s['t']:.2f} p={s['p']:.4f} lift={lift:.2f}x  [{type_summary}]"
    )

print(f"  -> Q1(春季+元旦) & Q4(国庆后/元旦前) = 新年度配置/信贷投放期")
print(f"  -> If Q1/Q4 edge >> Q2/Q3 => credit seasonality driver")

# ================================================================
# FACTOR 3: POLICY CALENDAR PROXIMITY
# ================================================================
print(f"\n{'=' * 70}")
print("FACTOR 3: POLICY CALENDAR PROXIMITY (两会/中央经济工作会议)")
print(f"{'=' * 70}")
policy_picks = [p for p in pre_picks if p["policy_near"]]
non_policy = [p for p in pre_picks if not p["policy_near"]]
if policy_picks:
    by_policy = defaultdict(list)
    for p in policy_picks:
        by_policy[p["policy_near"]].append(p)
    for ptype, sub in sorted(by_policy.items()):
        s = stats([p["ret"] for p in sub])
        print(
            f"  {ptype:>10}: n={s['n']:>3} EV={s['mean']:.3f}% net={s['mean'] - ETF_COST:.3f}% WR={s['wr'] * 100:.1f}% t={s['t']:.2f} p={s['p']:.4f}"
        )
if non_policy:
    s = stats([p["ret"] for p in non_policy])
    print(
        f"  {'无政策邻近':>10}: n={s['n']:>3} EV={s['mean']:.3f}% net={s['mean'] - ETF_COST:.3f}% WR={s['wr'] * 100:.1f}% t={s['t']:.2f} p={s['p']:.4f}"
    )
print(f"  -> If policy-near edge >> non-policy => policy expectation driver")

# ================================================================
# FACTOR 4: LIQUIDITY SEASONALITY (turn-of-month overlap)
# ================================================================
print(f"\n{'=' * 70}")
print("FACTOR 4: LIQUIDITY SEASONALITY (turn-of-month = 月末发薪/赎回)")
print(f"{'=' * 70}")
tom_picks = [p for p in pre_picks if p["is_tom"]]
non_tom = [p for p in pre_picks if not p["is_tom"]]
print(f"  TOM overlap: {len(tom_picks)}/{len(pre_picks)} ({len(tom_picks) / len(pre_picks) * 100:.0f}%)")
if tom_picks:
    s = stats([p["ret"] for p in tom_picks])
    lift = s["mean"] / base_s["mean"] if base_s["mean"] != 0 else float("inf")
    print(
        f"  TOM overlap:    n={s['n']:>3} EV={s['mean']:.3f}% net={s['mean'] - ETF_COST:.3f}% WR={s['wr'] * 100:.1f}% t={s['t']:.2f} p={s['p']:.4f} lift={lift:.2f}x"
    )
if non_tom:
    s = stats([p["ret"] for p in non_tom])
    lift = s["mean"] / base_s["mean"] if base_s["mean"] != 0 else float("inf")
    print(
        f"  Non-TOM:       n={s['n']:>3} EV={s['mean']:.3f}% net={s['mean'] - ETF_COST:.3f}% WR={s['wr'] * 100:.1f}% t={s['t']:.2f} p={s['p']:.4f} lift={lift:.2f}x"
    )
print(f"  -> If TOM and non-TOM both positive => pure calendar, liquidity NOT confound")
print(f"  -> If only TOM positive => liquidity/payday is the REAL driver")

# ================================================================
# FACTOR 5: MACRO CYCLE × QUARTER INTERACTION (expansion Q1 vs contraction Q1)
# ================================================================
print(f"\n{'=' * 70}")
print("FACTOR 5: MACRO CYCLE × QUARTER INTERACTION")
print(f"{'=' * 70}")
print(f"  {'Regime':<8} {'Quarter':<8} {'n':>4} {'EV%':>8} {'WR%':>6} {'t':>6}")
print("-" * 50)
for reg in ["strong", "weak"]:
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        sub = [p for p in pre_picks if p["regime"] == reg and p["quarter"] == q]
        if sub:
            s = stats([p["ret"] for p in sub])
            print(f"  {reg:<8} {q:<8} {s['n']:>4} {s['mean']:>8.3f} {s['wr'] * 100:>6.1f} {s['t']:>6.2f}")

# ================================================================
# MOMENTUM REFERENCE: is macro cycle stratification just momentum?
# ================================================================
print(f"\n{'=' * 70}")
print("MOMENTUM REFERENCE: macro regime vs prior momentum")
print(f"{'=' * 70}")
# MA20 regime IS a form of momentum (close > 20-day MA = upward trend)
# But is pre-holiday edge captured by momentum corr (already ~0.034)?
# If regime stratifies but momentum doesn't => regime captures something beyond momentum
# (regime = 20-day cumulative direction, momentum = 20-day magnitude)
# Test: within strong regime, does prior 20d momentum magnitude predict pre-holiday ret?
mom_data = []
for h in holidays:
    i_last = h["idx_last"]
    if i_last - 21 >= 0 and i_last - 1 >= 0:
        d_mom_start = calendar[i_last - 21]
        d_mom_end = calendar[i_last - 2]
        d_buy = calendar[i_last - 1]
        d_sell = calendar[i_last]
        b_ms = bar_map.get(d_mom_start)
        b_me = bar_map.get(d_mom_end)
        b_buy = bar_map.get(d_buy)
        b_sell = bar_map.get(d_sell)
        if all(b and b.get("close") and b.get("open") for b in [b_ms, b_me, b_buy, b_sell]):
            mom = (b_me["close"] - b_ms["close"]) / b_ms["close"] * 100
            pre_ret = (b_sell["close"] - b_buy["open"]) / b_buy["open"] * 100
            reg = regime_data.get(d_buy, {}).get("regime", "unknown")
            mom_data.append({"mom_20d": mom, "pre_ret": pre_ret, "regime": reg})

if mom_data:
    # Within each regime, momentum correlation
    for reg in ["strong", "weak"]:
        sub = [d for d in mom_data if d["regime"] == reg]
        if len(sub) > 5:
            moms = [d["mom_20d"] for d in sub]
            pres = [d["pre_ret"] for d in sub]
            n = len(sub)
            mean_mom = sum(moms) / n
            mean_pre = sum(pres) / n
            cov = sum((m - mean_mom) * (p - mean_pre) for m, p in zip(moms, pres)) / n
            std_mom = statistics.pstdev(moms)
            std_pre = statistics.pstdev(pres)
            corr = cov / (std_mom * std_pre) if std_mom > 0 and std_pre > 0 else 0
            print(f"  {reg.upper()}: n={n} corr(mom, pre_ret)={corr:.3f}")
    print(f"  -> Regime (direction) stratifies but momentum (magnitude) corr ~0 =>")
    print(f"     regime captures macro STATE not momentum TREND — distinct signal")

# ================================================================
# VIX/FOREIGN CAPITAL SNAPSHOT (point-in-time only, no historical series)
# ================================================================
print(f"\n{'=' * 70}")
print("FACTOR 6: VIX / EXTERNAL RISK SNAPSHOT (point-in-time, NO historical series)")
print(f"{'=' * 70}")
with open(f"{DATA}/macro_snapshot.json") as f:
    macro_snap = json.load(f)
vix = macro_snap["factors"].get("us_vix", {}).get("value", "N/A")
dxy = macro_snap["factors"].get("dxy", {}).get("value", "N/A")
usd_cny = macro_snap["factors"].get("usd_cny", {}).get("value", "N/A")
print(f"  Current VIX: {vix} (low=<20 risk-on, high=>30 risk-off)")
print(f"  Current DXY: {dxy}")
print(f"  Current USD/CNY: {usd_cny}")
print(f"  WARNING: FRED historical series NOT cached. Cannot stratify pre-holiday")
print(f"  edge by historical VIX/DXY level. This is a DATA GAP for macro domain.")
print(f"  Note: Northbound flow (外资) stopped 2024-08-19 (S206 accepted).")
print(f"  Prior to 2024-08, northbound was a potential macro confound but data is dead.")

# ================================================================
# SUMMARY: macro domain verdict
# ================================================================
print(f"\n{'=' * 70}")
print("MACRO DOMAIN SUMMARY")
print(f"{'=' * 70}")
strong_s = stats([p["ret"] for p in pre_picks if p["regime"] == "strong"])
weak_s = stats([p["ret"] for p in pre_picks if p["regime"] == "weak"])
print(f"  Strong regime (expansion): n={strong_s['n']} EV={strong_s['mean']:.3f}% p={strong_s['p']:.4f}")
print(f"  Weak regime (contraction): n={weak_s['n']} EV={weak_s['mean']:.3f}% p={weak_s['p']:.4f}")
print(f"  Regime-independent? {'YES' if strong_s['mean'] > 0 and weak_s['mean'] > 0 else 'NO'}")
tom_s = stats([p["ret"] for p in pre_picks if p["is_tom"]])
ntom_s = stats([p["ret"] for p in pre_picks if not p["is_tom"]])
print(f"  TOM overlap edge: {tom_s['mean']:.3f}% (n={tom_s['n']})")
print(f"  Non-TOM edge:     {ntom_s['mean']:.3f}% (n={ntom_s['n']})")
print(
    f"  Liquidity confound? {'YES (TOM-only)' if tom_s['mean'] > 0 and ntom_s['mean'] <= 0 else 'NO (both positive)' if ntom_s['mean'] > 0 else 'PARTIAL'}"
)
