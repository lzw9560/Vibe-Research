# -*- coding: utf-8 -*-
"""Tail-risk adversarial audit: long-holiday A group.
Refute-default: assume edge is false positive, find flaws from tail perspective.
"""
from __future__ import annotations
import json
import statistics
import random
from datetime import datetime
from collections import defaultdict
from math import erf, sqrt

DATA_DIR = '/Users/lizhiwei/project/code/stock/Vibe-Research/.vibe-research'
with open(f'{DATA_DIR}/index_ohlc_cache.json') as f:
    idx_data = json.load(f)

bars_sh = sorted(idx_data['sh.000001'], key=lambda b: b['date'])
calendar = [b['date'] for b in bars_sh]
bar_map = {b['date']: b for b in bars_sh}

HOLIDAY_GAP = 4
ETF_COST = 0.10

def classify_holiday(h):
    last_dt = datetime.strptime(h['last_before'], '%Y-%m-%d')
    month, gap = last_dt.month, h['gap']
    if month in (1, 2) and gap >= 7: return '春节'
    if month in (9, 10) and gap >= 5: return '国庆'
    if month == 9 and gap < 5: return '中秋'
    if month in (4, 5) and 3 <= gap <= 6:
        return '清明' if month == 4 else '劳动节'
    if month == 6 and gap >= 3: return '端午'
    if month in (12, 1) and gap < 7: return '元旦'
    return '其他'

holidays = []
for i in range(1, len(calendar)):
    d0 = datetime.strptime(calendar[i - 1], '%Y-%m-%d')
    d1 = datetime.strptime(calendar[i], '%Y-%m-%d')
    gap = (d1 - d0).days
    if gap >= HOLIDAY_GAP:
        holidays.append({'last_before': calendar[i - 1], 'first_after': calendar[i],
                         'gap': gap, 'idx_last': i - 1, 'idx_first': i})
for h in holidays:
    h['type'] = classify_holiday(h)

holiday_zone = set()
for h in holidays:
    for k in range(max(0, h['idx_last'] - 2), min(len(calendar), h['idx_last'] + 1)):
        holiday_zone.add(calendar[k])
    for k in range(h['idx_first'], min(len(calendar), h['idx_first'] + 2)):
        holiday_zone.add(calendar[k])

def is_turn_of_month(date_str):
    ym = date_str[:7]
    month_days = [d for d in calendar if d[:7] == ym]
    if not month_days: return False
    return date_str in month_days[:3] or date_str in month_days[-3:]

# A group picks (holiday + TOM overlap) — same logic as audit script
a_picks = []
for h in holidays:
    i_last = h['idx_last']
    if i_last - 1 >= 0:
        d_buy, d_sell = calendar[i_last - 1], calendar[i_last]
        b_buy, b_sell = bar_map[d_buy], bar_map[d_sell]
        o, c = b_buy.get('open'), b_sell.get('close')
        if o and c and o > 0 and c > 0:
            ret = (c - o) / o * 100 - ETF_COST
            tom = is_turn_of_month(d_buy) or is_turn_of_month(d_sell)
            if tom:
                a_picks.append({'type': h['type'], 'buy_date': d_buy, 'sell_date': d_sell,
                                'ret': ret, 'year': int(d_buy[:4]), 'month': int(d_buy[5:7])})

a_rets = sorted([p['ret'] for p in a_picks])
n = len(a_rets)
mean = sum(a_rets) / n
std_p = statistics.pstdev(a_rets)
std_s = statistics.stdev(a_rets)
se = std_s / sqrt(n)
t_stat = mean / se
p_val = 0.5 * (1 - erf(t_stat / sqrt(2)))
median = statistics.median(a_rets)

print("=" * 72)
print("TAIL-RISK ADVERSARIAL AUDIT: 长假节前 A 组")
print("=" * 72)
print(f"\nn={n}  mean={mean:.4f}%  median={median:.4f}%  WR={sum(1 for x in a_rets if x>0)/n*100:.1f}%")
print(f"mean-median gap={mean-median:.4f}%  t={t_stat:.2f}  p={p_val:.4f}")

# ===== 1. Skewness + max/min/percentiles =====
print(f"\n{'='*72}")
print("1. SKEWNESS + TAIL DISTRIBUTION")
print(f"{'='*72}")

# Fisher-Pearson skewness (sample, adjusted)
m3 = sum((x - mean) ** 3 for x in a_rets) / n
m2 = sum((x - mean) ** 2 for x in a_rets) / n
skew_fp = m3 / (m2 ** 1.5) if m2 > 0 else 0
# Adjusted skewness (sample)
skew_adj = (sqrt(n * (n - 1)) / (n - 2)) * skew_fp if n > 2 else 0

p5 = a_rets[int(n * 0.05)]
p10 = a_rets[int(n * 0.10)]
p25 = a_rets[int(n * 0.25)]
p75 = a_rets[int(n * 0.75)]
p90 = a_rets[int(n * 0.90)]
p95 = a_rets[int(n * 0.95)]
p99 = a_rets[min(int(n * 0.99), n - 1)]
mx = max(a_rets)
mn = min(a_rets)

print(f"  skewness (Fisher-Pearson): {skew_fp:.3f}")
print(f"  skewness (adjusted/sample): {skew_adj:.3f}")
print(f"  min={mn:.3f}%  p5={p5:.3f}%  p10={p10:.3f}%  p25={p25:.3f}%")
print(f"  p75={p75:.3f}%  p90={p90:.3f}%  p95={p95:.3f}%  p99={p99:.3f}%  max={mx:.3f}%")
print(f"  range: [{mn:.3f}, {mx:.3f}]  IQR: [{p25:.3f}, {p75:.3f}]")

# For comparison: inst_dominant is lottery (median -2.168%, WR 36.4%)
# A group: median +0.431%, WR 63.8%
# Positive skew = right-tail driven, negative skew = left-tail driven
if skew_adj > 0.5:
    print(f"  >>> POSITIVE SKEW ({skew_adj:.2f}) — right-tail heavy, mean pulled by big winners")
elif skew_adj < -0.5:
    print(f"  >>> NEGATIVE SKEW ({skew_adj:.2f}) — left-tail heavy, mean pulled down by big losers")
else:
    print(f"  >>> LOW SKEW ({skew_adj:.2f}) — distribution roughly symmetric")

# ===== 2. WR vs lottery pattern =====
print(f"\n{'='*72}")
print("2. WR / WIN-LOSS STRUCTURE")
print(f"{'='*72}")
wins = [x for x in a_rets if x > 0]
losses = [x for x in a_rets if x <= 0]
print(f"  wins={len(wins)} ({len(wins)/n*100:.1f}%)  losses={len(losses)} ({len(losses)/n*100:.1f}%)")
if wins and losses:
    print(f"  avg win={sum(wins)/len(wins):.3f}%  avg loss={sum(losses)/len(losses):.3f}%")
    print(f"  win/loss ratio (avg): {abs(sum(wins)/len(wins) / (sum(losses)/len(losses))):.3f}")
# Compare: lottery = WR<50% + few huge wins. A group WR=63.8% > 50%
# But check: is WR driven by many tiny wins + few big wins?
tiny_wins = [x for x in wins if x < 0.5]
big_wins = [x for x in wins if x >= 1.0]
print(f"  tiny wins (<0.5%): {len(tiny_wins)} ({len(tiny_wins)/n*100:.1f}%)")
print(f"  big wins (>=1.0%): {len(big_wins)} ({len(big_wins)/n*100:.1f}%)")

# ===== 3. Top/bottom picks + leave-out-top-3 =====
print(f"\n{'='*72}")
print("3. TOP/BOTTOM PICKS + LEAVE-OUT-TOP-3 INFLUENCE")
print(f"{'='*72}")
a_sorted_desc = sorted(a_picks, key=lambda p: p['ret'], reverse=True)
print(f"  TOP 5 picks:")
for p in a_sorted_desc[:5]:
    print(f"    {p['buy_date']} {p['type']:4s} ret={p['ret']:+.3f}%")
print(f"  BOTTOM 5 picks:")
for p in a_sorted_desc[-5:]:
    print(f"    {p['buy_date']} {p['type']:4s} ret={p['ret']:+.3f}%")

# Leave out top 3
top3_sum = sum(a_sorted_desc[i]['ret'] for i in range(3))
mean_excl_top3 = (sum(a_rets) - top3_sum) / (n - 3)
std_excl = statistics.stdev([a_sorted_desc[i]['ret'] for i in range(3, n)])
se_excl = std_excl / sqrt(n - 3)
t_excl = mean_excl_top3 / se_excl if se_excl > 0 else 0
p_excl = 0.5 * (1 - erf(t_excl / sqrt(2))) if t_excl > 0 else 1.0
print(f"\n  TOP 3 sum={top3_sum:.3f}%  contribution to mean: {top3_sum/n:.4f}% (of {mean:.4f}%)")
print(f"  After removing TOP 3: n={n-3} mean={mean_excl_top3:.4f}% median={statistics.median([a_sorted_desc[i]['ret'] for i in range(3,n)]):.4f}%")
print(f"  t={t_excl:.2f} p={p_excl:.4f}  {'STILL SIGNIFICANT' if p_excl<0.05 else 'NOT SIGNIFICANT'}")

# Leave out top 5
top5_sum = sum(a_sorted_desc[i]['ret'] for i in range(5))
mean_excl_top5 = (sum(a_rets) - top5_sum) / (n - 5)
std5 = statistics.stdev([a_sorted_desc[i]['ret'] for i in range(5, n)])
se5 = std5 / sqrt(n - 5)
t5 = mean_excl_top5 / se5 if se5 > 0 else 0
p5_leave = 0.5 * (1 - erf(t5 / sqrt(2))) if t5 > 0 else 1.0
print(f"  After removing TOP 5: n={n-5} mean={mean_excl_top5:.4f}% t={t5:.2f} p={p5_leave:.4f}  "
      f"{'STILL SIGNIFICANT' if p5_leave<0.05 else 'NOT SIGNIFICANT'}")

# ===== 4. Clustering / independence =====
print(f"\n{'='*72}")
print("4. CLUSTERING / INDEPENDENCE (effective n)")
print(f"{'='*72}")
# Group by year-month
ym_groups = defaultdict(list)
for p in a_picks:
    ym = f"{p['year']}-{p['month']:02d}"
    ym_groups[ym].append(p['ret'])
print(f"  Unique year-month clusters: {len(ym_groups)} (n={n})")
print(f"  Max picks in one year-month: {max(len(v) for v in ym_groups.values())}")
# Month distribution
month_dist = defaultdict(int)
for p in a_picks:
    month_dist[p['month']] += 1
print(f"  Month distribution: {dict(sorted(month_dist.items()))}")
# Type distribution
type_dist = defaultdict(list)
for p in a_picks:
    type_dist[p['type']].append(p['ret'])
print(f"  Holiday type counts: ", end="")
print(", ".join(f"{k}={len(v)}" for k, v in sorted(type_dist.items())))

# Effective n via clustering: if picks within same month are correlated,
# effective n ~ number of independent clusters
n_clusters = len(ym_groups)
print(f"\n  If clustered by year-month: effective n ~ {n_clusters} (vs n={n})")
# Conservative: inflate SE by sqrt(n/n_eff)
inflation = sqrt(n / n_clusters)
se_inflated = se * inflation
t_inflated = mean / se_inflated if se_inflated > 0 else 0
p_inflated = 0.5 * (1 - erf(t_inflated / sqrt(2))) if t_inflated > 0 else 1.0
print(f"  Inflated SE (x{inflation:.2f}): t={t_inflated:.2f} p={p_inflated:.4f}  "
      f"{'STILL <0.05' if p_inflated<0.05 else 'FAILS <0.05'}")

# ===== 5. Skewness-adjusted t + block bootstrap =====
print(f"\n{'='*72}")
print("5. SKEWNESS-ADJUSTED t + BLOCK BOOTSTRAP")
print(f"{'='*72}")

# Johnson skewness-adjusted t: t_adj = t / sqrt(1 + skew^2/4 * ... )
# Simple adjustment: t_skew = (mean - 0) / (se * sqrt(1 + |skew|/sqrt(n)))
# More standard: use skew-adjusted standard error
# t_adj = t * (1 - skew*mean/(6*std^2)) approx (from Edgeworth expansion)
# Or use: corrected t = t / sqrt(1 + skew^2 / (4*n))
t_skew_adj = t_stat / sqrt(1 + skew_adj**2 / (4 * n)) if (1 + skew_adj**2 / (4*n)) > 0 else 0
p_skew_adj = 0.5 * (1 - erf(t_skew_adj / sqrt(2))) if t_skew_adj > 0 else 1.0
print(f"  Skewness-adjusted t (Johnson approx): t={t_skew_adj:.2f} p={p_skew_adj:.4f}  "
      f"{'STILL <0.05' if p_skew_adj<0.05 else 'FAILS'}")

# Block bootstrap (resample with replacement, n=105 per sample)
# Conservative: also try block bootstrap by year-month clusters
random.seed(42)
B = 10000
# Standard bootstrap (assume independence)
boot_means = []
for _ in range(B):
    sample = [random.choice(a_rets) for _ in range(n)]
    boot_means.append(sum(sample) / n)
boot_means.sort()
ci_lo = boot_means[int(B * 0.025)]
ci_hi = boot_means[int(B * 0.975)]
boot_p = sum(1 for x in boot_means if x <= 0) / B
print(f"\n  Standard bootstrap (B={B}, independence assumed):")
print(f"    95% CI: [{ci_lo:.4f}%, {ci_hi:.4f}%]  {'EXCLUDES 0' if ci_lo>0 else 'INCLUDES 0'}")
print(f"    P(mean<=0) = {boot_p:.4f}  {'<0.05 SURVIVES' if boot_p<0.05 else 'FAILS'}")

# Block bootstrap by year-month clusters (accounts for clustering)
cluster_list = list(ym_groups.values())
boot_block_means = []
for _ in range(B):
    # Resample clusters with replacement, then pick randomly within each cluster
    total_ret = []
    for _ in range(len(cluster_list)):
        cluster = random.choice(cluster_list)
        total_ret.append(random.choice(cluster))
    boot_block_means.append(sum(total_ret) / len(total_ret))
boot_block_means.sort()
ci_lo_b = boot_block_means[int(B * 0.025)]
ci_hi_b = boot_block_means[int(B * 0.975)]
boot_p_b = sum(1 for x in boot_block_means if x <= 0) / B
print(f"\n  Block bootstrap by year-month cluster (B={B}):")
print(f"    95% CI: [{ci_lo_b:.4f}%, {ci_hi_b:.4f}%]  {'EXCLUDES 0' if ci_lo_b>0 else 'INCLUDES 0'}")
print(f"    P(mean<=0) = {boot_p_b:.4f}  {'<0.05 SURVIVES' if boot_p_b<0.05 else 'FAILS'}")

# ===== 6. Median bootstrap CI =====
print(f"\n{'='*72}")
print("6. MEDIAN BOOTSTRAP CI")
print(f"{'='*72}")
boot_medians = []
for _ in range(B):
    sample = [random.choice(a_rets) for _ in range(n)]
    boot_medians.append(statistics.median(sample))
boot_medians.sort()
med_lo = boot_medians[int(B * 0.025)]
med_hi = boot_medians[int(B * 0.975)]
print(f"  Median={median:.4f}%")
print(f"  95% CI: [{med_lo:.4f}%, {med_hi:.4f}%]  {'EXCLUDES 0' if med_lo>0 else 'INCLUDES 0'}")

# Also: sign test (non-parametric, no distributional assumption)
n_pos = sum(1 for x in a_rets if x > 0)
# Binomial test: under H0 p=0.5
# Exact binomial tail
from math import comb
p_sign = sum(comb(n, k) for k in range(n_pos, n + 1)) / (2 ** n)
print(f"  Sign test: n_pos={n_pos}/{n}  p(sign)={p_sign:.6f}  {'EXCLUDES 0' if p_sign<0.05 else 'INCLUDES 0'}")

# ===== VERDICT SUMMARY =====
print(f"\n{'='*72}")
print("VERDICT SUMMARY (tail-risk perspective)")
print(f"{'='*72}")
checks = {
    'low skew (|skew|<0.5)': abs(skew_adj) < 0.5,
    'mean-median gap small (<0.3%)': abs(mean - median) < 0.3,
    'leave-out-top-3 still sig': p_excl < 0.05,
    'leave-out-top-5 still sig': p5_leave < 0.05,
    'skew-adj t still sig': p_skew_adj < 0.05,
    'block bootstrap CI excludes 0': ci_lo_b > 0,
    'block bootstrap p<0.05': boot_p_b < 0.05,
    'median CI excludes 0': med_lo > 0,
    'sign test sig': p_sign < 0.05,
    'clustered-inflated SE sig': p_inflated < 0.05,
}
for k, v in checks.items():
    print(f"  {'PASS' if v else 'FAIL'}  {k}")
passed = sum(checks.values())
total = len(checks)
print(f"\n  {passed}/{total} checks survive tail-risk scrutiny")
if passed >= total - 2:
    print(f"  >>> EDGE SURVIVES tail-risk audit")
elif passed >= total - 4:
    print(f"  >>> PARTIAL SURVIVAL — some tail concerns but core holds")
else:
    print(f"  >>> EDGE DOES NOT SURVIVE — tail-driven false positive likely")
