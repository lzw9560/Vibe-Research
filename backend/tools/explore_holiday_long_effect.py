# -*- coding: utf-8 -*-
"""长假效应 (Long-Holiday Effect) — §44 v3 + 10 flaw 全套口径严测

策略:
  Pre-holiday: 长假前倒数第3交易日 close 信号 → T+1 open(day -2) 买指数 ETF →
    长假前最后1交易日(day -1) close 卖 (2日 hold, 节前平仓不留假期风险)
  Post-holiday: 长假后首个交易日(day +1) open 买 → 第2交易日(day +2) close 卖 (2日 hold)
  BHAR: sh.000001 同窗口 (tautological — 交易的就是指数本身, BHAR≈0, 须报 raw_ev)
  day_paired: 假期2日窗口 vs 随机2日窗口 lift>2x
  Walk-forward: chrono split, 前半 train → 后半 test
  成本: ETF 0.10% round-trip

10 flaw check:
  1. entry 涨停价溢价 — N/A (ETF 无涨停限制)
  2. survivorship — N/A (买全市场指数)
  3. exit 一字 over-credit — N/A (ETF 无一字涨停)
  4. T+1 日内泄漏 — check: 用 close_ev (open→close) 非 open_ev
  5. 拥挤倒 U — check: walk-forward + 时段衰减
  6. R6 gap-through fill — check: 用实际 open (gap 已含在 open 价)
  7. timing mismatch — check: 基准同时窗 (非假期2日窗口作 base rate)
  8. 成本乐观 — ETF 0.10% 非 股票 0.30%
  9. phantom alpha — CRITICAL: BHAR vs 同 instrument = 0, 须报 raw_ev
  10. 退化 OLS — N/A (单因子)
"""

import json
import sys
import statistics
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from math import erf, sqrt

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import ev_stats, norm_sf_positive, day_paired_t, bonferroni_p, ALPHA

DATA = str(resolve_data_dir())
ETF_COST = 0.10  # round-trip cost % for index ETF
HOLIDAY_GAP = 4  # gap >= 4 calendar days = long holiday break
N_TESTS = 6  # 3 strategies (panel top-3) x 2 subsets (pre/post)

# ---------- load data ----------
with open(f"{DATA}/index_ohlc_cache.json") as f:
    idx_data = json.load(f)
bars = sorted(idx_data["sh.000001"], key=lambda b: b["date"])
calendar = [b["date"] for b in bars]
bar_map = {b["date"]: b for b in bars}
date_idx = {d: i for i, d in enumerate(calendar)}

print(f"Index: sh.000001 (Shanghai Composite)")
print(f"Trading days: {len(calendar)} ({calendar[0]} to {calendar[-1]})")

# ---------- find long holiday breaks ----------
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

# also count 2018-2026 subset
holidays_2018 = [h for h in holidays if h["last_before"] >= "2018-01-01"]
print(f"  2018-2026 subset: {len(holidays_2018)}")

# ---------- build picks ----------
pre_picks = []
post_picks = []
for hi, h in enumerate(holidays):
    # Pre-holiday: buy open of day -2 (idx_last-1), sell close of day -1 (idx_last)
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
            pre_picks.append(
                {
                    "holiday_idx": hi,
                    "holiday_date": h["last_before"],
                    "buy_date": d_buy,
                    "sell_date": d_sell,
                    "entry": o,
                    "exit": c,
                    "ret": ret,
                }
            )

    # Post-holiday: buy open of day +1 (idx_first), sell close of day +2 (idx_first+1)
    i_first = h["idx_first"]
    if i_first + 1 < len(calendar):
        d_buy = calendar[i_first]
        d_sell = calendar[i_first + 1]
        b_buy = bar_map[d_buy]
        b_sell = bar_map[d_sell]
        o = b_buy.get("open")
        c = b_sell.get("close")
        if o and c and o > 0 and c > 0:
            ret = (c - o) / o * 100
            post_picks.append(
                {
                    "holiday_idx": hi,
                    "holiday_date": h["first_after"],
                    "buy_date": d_buy,
                    "sell_date": d_sell,
                    "entry": o,
                    "exit": c,
                    "ret": ret,
                }
            )

pre_rets = [p["ret"] for p in pre_picks]
post_rets = [p["ret"] for p in post_picks]
all_rets = pre_rets + post_rets

# ---------- base rate (non-holiday 2-day open->close windows) ----------
holiday_zone_dates = set()
for h in holidays:
    i_last = h["idx_last"]
    i_first = h["idx_first"]
    # exclude day -3, -2, -1 (pre-holiday zone)
    for k in range(max(0, i_last - 2), min(len(calendar), i_last + 1)):
        holiday_zone_dates.add(calendar[k])
    # exclude day +1, +2 (post-holiday zone)
    for k in range(i_first, min(len(calendar), i_first + 2)):
        holiday_zone_dates.add(calendar[k])

base_returns = []
for i in range(len(calendar) - 1):
    d_start = calendar[i]
    d_end = calendar[i + 1]
    if d_start in holiday_zone_dates or d_end in holiday_zone_dates:
        continue
    b_start = bar_map[d_start]
    b_end = bar_map[d_end]
    o = b_start.get("open")
    c = b_end.get("close")
    if o and c and o > 0 and c > 0:
        base_returns.append((c - o) / o * 100)


# ---------- stats ----------
def stats(rets):
    n = len(rets)
    if n == 0:
        return {"n": 0, "mean": 0.0, "std": 0.0, "se": 0.0, "t": 0.0, "p": 1.0, "wr": 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = norm_sf_positive(t)
    wr = sum(1 for x in rets if x > 0) / n
    return {"n": n, "mean": mean, "std": std, "se": se, "t": t, "p": p, "wr": wr}


pre_s = stats(pre_rets)
post_s = stats(post_rets)
all_s = stats(all_rets)
base_s = stats(base_returns)

# lift
lift_pre = pre_s["mean"] / base_s["mean"] if base_s["mean"] != 0 else float("inf")
lift_post = post_s["mean"] / base_s["mean"] if base_s["mean"] != 0 else float("inf")

# day-paired t (each holiday = one observation)
pre_dt = day_paired_t({p["holiday_date"]: [p["ret"]] for p in pre_picks})
post_dt = day_paired_t({p["holiday_date"]: [p["ret"]] for p in post_picks})

# combined day-paired: group by holiday_idx (pre+post averaged per holiday)
combined_by_holiday = defaultdict(list)
for p in pre_picks:
    combined_by_holiday[p["holiday_idx"]].append(p["ret"])
for p in post_picks:
    combined_by_holiday[p["holiday_idx"]].append(p["ret"])
combined_dt = day_paired_t({str(k): v for k, v in combined_by_holiday.items()})


# two-sample Welch t-test (holiday vs base rate)
def welch_t(s1, s2):
    n1, n2 = s1["n"], s2["n"]
    m1, m2 = s1["mean"], s2["mean"]
    v1, v2 = s1["std"] ** 2, s2["std"] ** 2
    se = sqrt(v1 / n1 + v2 / n2) if n1 > 0 and n2 > 0 else 0
    t = (m1 - m2) / se if se > 0 else 0
    if n1 > 1 and n2 > 1 and (v1 / n1 + v2 / n2) > 0:
        df = (v1 / n1 + v2 / n2) ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    else:
        df = n1 + n2 - 2
    p = norm_sf_positive(t)
    return {"t": t, "p": p, "df": round(df, 1)}


welch_pre = welch_t(pre_s, base_s)
welch_post = welch_t(post_s, base_s)


# ---------- walk-forward (chronological split) ----------
def walk_forward_holiday(picks_list):
    sorted_picks = sorted(picks_list, key=lambda p: p["holiday_date"])
    n = len(sorted_picks)
    if n < 4:
        return {"status": "too_few", "n": n}
    mid = n // 2
    train = sorted_picks[:mid]
    test = sorted_picks[mid:]
    train_rets = [p["ret"] for p in train]
    test_rets = [p["ret"] for p in test]
    train_s = stats(train_rets)
    test_s = stats(test_rets)
    # day-paired for test half
    test_by_date = defaultdict(list)
    for p in test:
        test_by_date[p["holiday_date"]].append(p["ret"])
    test_dt = day_paired_t(test_by_date)
    return {
        "status": "ok",
        "n_train": len(train),
        "n_test": len(test),
        "train_s": train_s,
        "test_s": test_s,
        "test_dt": test_dt,
    }


wf_pre = walk_forward_holiday(pre_picks)
wf_post = walk_forward_holiday(post_picks)

# combined walk-forward (sort by date, but group pre+post per holiday)
combined_picks = sorted(pre_picks + post_picks, key=lambda p: p["holiday_date"])
wf_all = walk_forward_holiday(combined_picks)


# ---------- sub-period decay (拥挤倒U check) ----------
def stats_by_period(rets_with_dates, label):
    periods = [
        ("2004-2010", "2004", "2010"),
        ("2011-2016", "2011", "2016"),
        ("2017-2022", "2017", "2022"),
        ("2023-2026", "2023", "2026"),
    ]
    print(f"\n  {label} by period:")
    for pname, y0, y1 in periods:
        sub = [p for p in rets_with_dates if y0 <= p["holiday_date"][:4] <= y1]
        if sub:
            s = stats([p["ret"] for p in sub])
            print(f"    {pname}: n={s['n']} EV={s['mean']:.3f}% WR={s['wr'] * 100:.1f}% t={s['t']:.2f}")


# ---------- print results ----------
print(f"\n{'=' * 70}")
print(f"BASE RATE (non-holiday 2-day open->close windows)")
print(f"{'=' * 70}")
print(f"  n={base_s['n']} mean={base_s['mean']:.4f}% std={base_s['std']:.3f}% WR={base_s['wr'] * 100:.1f}%")

print(f"\n{'=' * 70}")
print(f"PRE-HOLIDAY (buy day-2 open -> sell day-1 close)")
print(f"{'=' * 70}")
print(f"  n_picks={pre_s['n']} n_holidays={pre_s['n']}")
print(f"  gross_EV={pre_s['mean']:.3f}% std={pre_s['std']:.3f}% WR={pre_s['wr'] * 100:.1f}%")
print(f"  net_EV={pre_s['mean'] - ETF_COST:.3f}% (cost {ETF_COST}%)")
print(f"  raw_EV (=gross, index return)={pre_s['mean']:.3f}%")
print(f"  BHAR vs sh.000001 same window = 0.000% (TAUTOLOGICAL — trading the index itself)")
print(
    f"  day-paired t={pre_dt['t']:.2f} n_days={pre_dt['n_days']} "
    f"p_raw={pre_dt['p_one_sided']:.6f} p_bonf(×{N_TESTS})={bonferroni_p(pre_dt['p_one_sided'], N_TESTS):.6f}"
)
print(f"  base_rate={base_s['mean']:.4f}% lift={lift_pre:.2f}x")
print(f"  Welch t (vs base)={welch_pre['t']:.2f} p={welch_pre['p']:.6f} df={welch_pre['df']}")
if wf_pre["status"] == "ok":
    print(
        f"  Walk-forward: train_EV={wf_pre['train_s']['mean']:.3f}% (n={wf_pre['n_train']}) "
        f"test_EV={wf_pre['test_s']['mean']:.3f}% (n={wf_pre['n_test']}) "
        f"test_p={wf_pre['test_dt']['p_one_sided']:.6f}"
    )

print(f"\n{'=' * 70}")
print(f"POST-HOLIDAY (buy day+1 open -> sell day+2 close)")
print(f"{'=' * 70}")
print(f"  n_picks={post_s['n']} n_holidays={post_s['n']}")
print(f"  gross_EV={post_s['mean']:.3f}% std={post_s['std']:.3f}% WR={post_s['wr'] * 100:.1f}%")
print(f"  net_EV={post_s['mean'] - ETF_COST:.3f}% (cost {ETF_COST}%)")
print(f"  raw_EV (=gross, index return)={post_s['mean']:.3f}%")
print(f"  BHAR vs sh.000001 same window = 0.000% (TAUTOLOGICAL)")
print(
    f"  day-paired t={post_dt['t']:.2f} n_days={post_dt['n_days']} "
    f"p_raw={post_dt['p_one_sided']:.6f} p_bonf(×{N_TESTS})={bonferroni_p(post_dt['p_one_sided'], N_TESTS):.6f}"
)
print(f"  base_rate={base_s['mean']:.4f}% lift={lift_post:.2f}x")
print(f"  Welch t (vs base)={welch_post['t']:.2f} p={welch_post['p']:.6f} df={welch_post['df']}")
if wf_post["status"] == "ok":
    print(
        f"  Walk-forward: train_EV={wf_post['train_s']['mean']:.3f}% (n={wf_post['n_train']}) "
        f"test_EV={wf_post['test_s']['mean']:.3f}% (n={wf_post['n_test']}) "
        f"test_p={wf_post['test_dt']['p_one_sided']:.6f}"
    )

print(f"\n{'=' * 70}")
print(f"COMBINED (pre + post, grouped by holiday)")
print(f"{'=' * 70}")
print(f"  n_picks={len(all_rets)} n_holidays={len(holidays)}")
print(f"  gross_EV={all_s['mean']:.3f}% std={all_s['std']:.3f}% WR={all_s['wr'] * 100:.1f}%")
print(f"  net_EV={all_s['mean'] - ETF_COST:.3f}% (cost {ETF_COST}%)")
print(f"  raw_EV (=gross)={all_s['mean']:.3f}%")
print(f"  BHAR vs sh.000001 same window = 0.000% (TAUTOLOGICAL)")
print(
    f"  day-paired (per-holiday) t={combined_dt['t']:.2f} n_days={combined_dt['n_days']} "
    f"p_raw={combined_dt['p_one_sided']:.6f} p_bonf(×{N_TESTS})={bonferroni_p(combined_dt['p_one_sided'], N_TESTS):.6f}"
)
if wf_all["status"] == "ok":
    decay = (
        (wf_all["train_s"]["mean"] - wf_all["test_s"]["mean"]) / abs(wf_all["train_s"]["mean"]) * 100
        if wf_all["train_s"]["mean"] != 0
        else 0
    )
    print(
        f"  Walk-forward: train_EV={wf_all['train_s']['mean']:.3f}% (n={wf_all['n_train']}) "
        f"test_EV={wf_all['test_s']['mean']:.3f}% (n={wf_all['n_test']}) "
        f"test_p={wf_all['test_dt']['p_one_sided']:.6f} decay={decay:.0f}%"
    )

# ---------- sub-period decay (flaw #5) ----------
print(f"\n{'=' * 70}")
print(f"FLAW #5: 拥挤倒U — sub-period decay check")
print(f"{'=' * 70}")
stats_by_period(pre_picks, "PRE-holiday")
stats_by_period(post_picks, "POST-holiday")

# ---------- 2018-2026 subset (compare with prior) ----------
print(f"\n{'=' * 70}")
print(f"2018-2026 SUBSET (compare with prior=0.28)")
print(f"{'=' * 70}")
pre_2018 = [p for p in pre_picks if p["holiday_date"] >= "2018-01-01"]
post_2018 = [p for p in post_picks if p["holiday_date"] >= "2018-01-01"]
pre_2018_s = stats([p["ret"] for p in pre_2018])
post_2018_s = stats([p["ret"] for p in post_2018_s if isinstance(p, dict)] if False else [p["ret"] for p in post_2018])
print(f"  Pre 2018-2026: n={pre_2018_s['n']} EV={pre_2018_s['mean']:.3f}% WR={pre_2018_s['wr'] * 100:.1f}%")
print(f"  Post 2018-2026: n={post_2018_s['n']} EV={post_2018_s['mean']:.3f}% WR={post_2018_s['wr'] * 100:.1f}%")

# ---------- flaw check summary ----------
print(f"\n{'=' * 70}")
print(f"10 FLAW CHECK")
print(f"{'=' * 70}")
flaws = []
print(f"  1. entry 涨停价溢价: N/A (ETF 无涨停限制, 高流动性)")
print(f"  2. survivorship: N/A (买全市场指数, 无选股)")
print(f"  3. exit 一字 over-credit: N/A (ETF 无一字涨停)")
print(f"  4. T+1 日内泄漏: NOT TRIGGERED (用 close_ev: open->close 多日 hold, 非开 ev)")
print(f"  5. 拥挤倒 U: CHECK (见 sub-period decay 上面)")
# Determine if decay is present
if wf_all["status"] == "ok":
    if wf_all["train_s"]["mean"] > 0 and wf_all["test_s"]["mean"] < wf_all["train_s"]["mean"]:
        flaws.append("5.拥挤倒U: train>test 衰减迹象")
        print(f"     -> TRIGGERED: train_EV > test_EV (衰减)")
    else:
        print(f"     -> NOT TRIGGERED: 无明显衰减")
print(f"  6. R6 gap-through fill: NOT TRIGGERED (用实际 open 价, gap 已含)")
print(f"  7. timing mismatch: HANDLED (base rate 排除假期窗口, 同 2日 open->close 口径)")
print(f"  8. 成本乐观: HANDLED (ETF 0.10% 非 股票 0.30%)")
print(f"  9. phantom alpha: TRIGGERD — BHAR vs 同 instrument = 0 (tautological)")
flaws.append("9.phantom-BHAR: 交易指数本身, BHAR=0 tautological, 须报 raw_ev")
print(f"     -> TRIGGERED: BHAR=0, 必须用 raw_ev (=gross index return) 而非 BHAR")
print(f"  10. 退化 OLS: N/A (单因子, 无多因子回归)")

# ---------- verdict ----------
print(f"\n{'=' * 70}")
print(f"VERDICT (combined strategy, §44 v3 cascade)")
print(f"{'=' * 70}")

gross_ev = all_s["mean"]
net_ev = all_s["mean"] - ETF_COST
day_t = combined_dt["t"]
n_days = combined_dt["n_days"]
p_raw = combined_dt["p_one_sided"]
p_bonf = bonferroni_p(p_raw, N_TESTS)

wf_train_ev = wf_all["train_s"]["mean"] if wf_all["status"] == "ok" else 0
wf_test_ev = wf_all["test_s"]["mean"] if wf_all["status"] == "ok" else 0
wf_test_p = wf_all["test_dt"]["p_one_sided"] if wf_all["status"] == "ok" else 1.0

print(f"  gross_EV={gross_ev:.3f}% net_EV={net_ev:.3f}%")
print(f"  day_t={day_t:.2f} n_days={n_days} p_raw={p_raw:.6f} p_bonf(×{N_TESTS})={p_bonf:.6f}")
print(f"  walk-forward: train_EV={wf_train_ev:.3f}% test_EV={wf_test_ev:.3f}% test_p={wf_test_p:.6f}")

# Verdict cascade (adapted from _factor_helpers.verdict_for)
if gross_ev < 0:
    verdict = "falsified"
    reason = "gross EV < 0 (negative edge)"
elif n_days < 60:
    verdict = "underpowered"
    reason = f"n_days={n_days} < 60"
elif p_bonf >= ALPHA:
    verdict = "falsified"
    reason = f"Bonferroni p={p_bonf:.6f} >= {ALPHA} (not significant)"
elif net_ev <= 0:
    verdict = "falsified"
    reason = f"net EV={net_ev:.3f}% <= 0 (gross edge eaten by cost)"
elif wf_all["status"] == "ok":
    if wf_train_ev <= 0:
        verdict = "exploratory"
        reason = f"train_EV={wf_train_ev:.3f}% <= 0 (edge not in train half)"
    elif wf_test_ev <= 0:
        verdict = "falsified"
        reason = f"walk-forward test_EV={wf_test_ev:.3f}% <= 0"
    elif bonferroni_p(wf_test_p, N_TESTS) >= ALPHA:
        verdict = "exploratory"
        reason = (
            f"OOS test EV={wf_test_ev:.3f}% > 0 but test p={wf_test_p:.6f} Bonf×{N_TESTS}={bonferroni_p(wf_test_p, N_TESTS):.6f} >= {ALPHA}"
        )
    else:
        verdict = "edge-confirmed"
        reason = f"all gates pass: gross+net>0, Bonf PASS, OOS significant"
else:
    verdict = "exploratory"
    reason = "walk-forward not available"

print(f"\n  -> VERDICT: {verdict.upper()}")
print(f"     Reason: {reason}")

# Also check pre and post separately
print(f"\n  Pre-holiday verdict:")
if pre_s["mean"] < 0:
    print(f"    -> FALSIFIED (gross EV={pre_s['mean']:.3f}% < 0)")
elif pre_dt["n_days"] < 60:
    print(f"    -> UNDERPOWERED (n_days={pre_dt['n_days']} < 60)")
elif bonferroni_p(pre_dt["p_one_sided"], N_TESTS) >= ALPHA:
    print(f"    -> FALSIFIED (Bonf p={bonferroni_p(pre_dt['p_one_sided'], N_TESTS):.6f} >= {ALPHA})")
else:
    print(f"    -> passes Bonf, checking walk-forward...")

print(f"\n  Post-holiday verdict:")
if post_s["mean"] < 0:
    print(f"    -> FALSIFIED (gross EV={post_s['mean']:.3f}% < 0)")
elif post_dt["n_days"] < 60:
    print(f"    -> UNDERPOWERED (n_days={post_dt['n_days']} < 60)")
elif bonferroni_p(post_dt["p_one_sided"], N_TESTS) >= ALPHA:
    print(f"    -> FALSIFIED (Bonf p={bonferroni_p(post_dt['p_one_sided'], N_TESTS):.6f} >= {ALPHA})")
else:
    print(f"    -> passes Bonf, checking walk-forward...")

# ---------- honest prior vs actual ----------
print(f"\n{'=' * 70}")
print(f"HONEST: 先验 vs 实际")
print(f"{'=' * 70}")
print(f"  Prior (expert panel): 0.28 (28% chance of edge)")
print(f"  Actual: gross_EV={gross_ev:.3f}% net_EV={net_ev:.3f}%")
print(f"  Base rate (2-day non-holiday): {base_s['mean']:.4f}%")
print(f"  Lift (combined/base): {all_s['mean'] / base_s['mean']:.2f}x" if base_s["mean"] != 0 else "  Lift: inf")
print(f"  Pre lift: {lift_pre:.2f}x  Post lift: {lift_post:.2f}x")
print(f"  Statistical significance: p_raw={p_raw:.6f} p_bonf={p_bonf:.6f}")
print(f"  Verdict: {verdict}")
if verdict == "falsified":
    print(f"  -> 先验 0.28 过高. 假期窗口收益不显著高于随机 2 日窗口.")
elif verdict == "underpowered":
    print(f"  -> 样本不足, 无法更新先验.")
elif verdict == "exploratory":
    print(f"  -> 有效果迹象但 OOS 不显著, 先验大致合理但未确认.")
elif verdict == "edge-confirmed":
    print(f"  -> 先验 0.28 过低! 实际有效 edge.")

print(f"\n  KEY: BHAR=0 is TAUTOLOGICAL (flaw #9 phantom). The honest metric is")
print(f"  raw_EV (= index return during holiday windows) vs base rate.")
print(f"  If gross_EV > base_rate and statistically significant => timing edge exists.")
print(f"  If not => calendar effect is noise or priced-in.")
