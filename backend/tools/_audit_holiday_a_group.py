# -*- coding: utf-8 -*-
"""长假节前 A 组（节前+TOM 重叠）§44 v3 严测（2026-10-08）。

disentangle 发现长假节前 edge 主要来自 A 组（节前+TOM 重叠）：
- A 组全期 n=105 EV+0.785% > 全 picks +0.52%
- 2022 后 A 组 n=21 EV+0.910%（仍正，underpowered）

本脚本跑 A 组独立严测（§44 v3）：
1. 全期 stats + lift vs base
2. Bonf×6（6 长假类型多重校正）
3. walk-forward（时间 split train/test）
4. DSR（deflated sharpe）
5. 衰减检查（按年/按 era）

verdict 判定：Bonf 后 p<0.05 + walk-forward test PASS + 无单 regime → edge-confirmed
"""
from __future__ import annotations
import json
import statistics
from datetime import datetime
from collections import defaultdict
from math import erf, sqrt

DATA = '/Users/lizhiwei/project/code/stock/Vibe-Research/.vibe-research'
with open(f'{DATA}/index_ohlc_cache.json') as f:
    idx_data = json.load(f)

bars_sh = sorted(idx_data['sh.000001'], key=lambda b: b['date'])
calendar = [b['date'] for b in bars_sh]
bar_map = {b['date']: b for b in bars_sh}

HOLIDAY_GAP = 4
ETF_COST = 0.10  # ETF 双边 0.10%


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


def stats(rets):
    n = len(rets)
    if n == 0: return {'n': 0, 'mean': 0.0, 'std': 0.0, 'se': 0.0, 't': 0.0, 'p': 1.0, 'wr': 0.0, 'median': 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = 0.5 * (1 - erf(t / sqrt(2))) if t > 0 else 1.0
    wr = sum(1 for x in rets if x > 0) / n
    med = statistics.median(rets)
    return {'n': n, 'mean': mean, 'std': std, 'se': se, 't': t, 'p': p, 'wr': wr, 'median': med}


def is_turn_of_month(date_str):
    ym = date_str[:7]
    month_days = [d for d in calendar if d[:7] == ym]
    if not month_days: return False
    return date_str in month_days[:3] or date_str in month_days[-3:]


# base rate（非节假日 2-day open→close）
base_returns = []
for i in range(len(calendar) - 1):
    d_start, d_end = calendar[i], calendar[i + 1]
    if d_start in holiday_zone or d_end in holiday_zone: continue
    b_s, b_e = bar_map[d_start], bar_map[d_end]
    o, c = b_s.get('open'), b_e.get('close')
    if o and c and o > 0: base_returns.append((c - o) / o * 100)
base_s = stats(base_returns)

# A 组 picks（节前 + TOM 重叠）
a_picks = []
for h in holidays:
    i_last = h['idx_last']
    if i_last - 1 >= 0:
        d_buy, d_sell = calendar[i_last - 1], calendar[i_last]
        b_buy, b_sell = bar_map[d_buy], bar_map[d_sell]
        o, c = b_buy.get('open'), b_sell.get('close')
        if o and c and o > 0 and c > 0:
            ret = (c - o) / o * 100 - ETF_COST  # net
            tom = is_turn_of_month(d_buy) or is_turn_of_month(d_sell)
            if tom:  # A 组 = 节前 + TOM 重叠
                a_picks.append({'type': h['type'], 'buy_date': d_buy, 'sell_date': d_sell, 'ret': ret})

a_rets = [p['ret'] for p in a_picks]
a_s = stats(a_rets)
lift = a_s['mean'] / base_s['mean'] if base_s['mean'] != 0 else 0

print("=" * 70)
print("长假节前 A 组（节前+TOM 重叠）§44 v3 严测")
print("=" * 70)
print(f"\nBase rate: n={base_s['n']} EV={base_s['mean']:.4f}% WR={base_s['wr']*100:.1f}%")
print(f"A 组全期: n={a_s['n']} gross_EV={a_s['mean']:.4f}% WR={a_s['wr']*100:.1f}% "
      f"median={a_s['median']:.3f}% t={a_s['t']:.2f} p_raw={a_s['p']:.4f} lift={lift:.2f}x")

# ---------- 1. Bonf×6（6 长假类型多重校正）----------
print(f"\n{'='*70}")
print("1. Bonf×6 多重校正（6 长假类型）")
print(f"{'='*70}")
# 对每个长假类型单独算 p，Bonferroni ×6
types_present = sorted(set(p['type'] for p in a_picks))
min_p = 1.0
for ht in types_present:
    sub = [p['ret'] for p in a_picks if p['type'] == ht]
    s = stats(sub)
    bonf_p = min(s['p'] * 6, 1.0)  # Bonf×6
    print(f"  {ht}: n={s['n']} EV={s['mean']:.3f}% WR={s['wr']*100:.1f}% "
          f"p_raw={s['p']:.4f} Bonf×6={bonf_p:.4f} {'PASS' if bonf_p < 0.05 else 'FAIL'}")
    if s['p'] < min_p: min_p = s['p']
bonf6_overall = min(a_s['p'] * 6, 1.0)
print(f"  整体 A 组: p_raw={a_s['p']:.4f} Bonf×6={bonf6_overall:.4f} "
      f"{'PASS' if bonf6_overall < 0.05 else 'FAIL'}")

# ---------- 2. walk-forward（时间 split）----------
print(f"\n{'='*70}")
print("2. walk-forward（前 70% train / 后 30% test）")
print(f"{'='*70}")
a_sorted = sorted(a_picks, key=lambda p: p['buy_date'])
n = len(a_sorted)
split = int(n * 0.7)
train = a_sorted[:split]
test = a_sorted[split:]
tr_s = stats([p['ret'] for p in train])
te_s = stats([p['ret'] for p in test])
print(f"  train: n={tr_s['n']} EV={tr_s['mean']:.4f}% WR={tr_s['wr']*100:.1f}% "
      f"p={tr_s['p']:.4f} ({train[0]['buy_date']}~{train[-1]['buy_date']})")
print(f"  test:  n={te_s['n']} EV={te_s['mean']:.4f}% WR={te_s['wr']*100:.1f}% "
      f"p={te_s['p']:.4f} ({test[0]['buy_date']}~{test[-1]['buy_date']})")
decay = (tr_s['mean'] - te_s['mean']) / tr_s['mean'] * 100 if tr_s['mean'] != 0 else 0
print(f"  衰减: {decay:.1f}%  {'PASS' if te_s['mean'] > 0 and te_s['p'] < 0.05 else 'FAIL'}")

# ---------- 3. DSR（deflated sharpe）----------
print(f"\n{'='*70}")
print("3. DSR（deflated sharpe，N=1 单策略，Bonf×6）")
print(f"{'='*70}")
# DSR: SR_adjusted = SR * sqrt(1 - skew^2 - ... )，简化用 t 检验 + Bonf 校正
# 单策略 N=1，但测了 6 类型 → 等效 N=6 多重校正
sr = a_s['mean'] / a_s['std'] if a_s['std'] > 0 else 0
# DSR 简化：假设 null 下的 SR 期望 ≈ 0，用 Bonf×6 后 p 判
print(f"  Sharpe (per pick): {sr:.4f}")
print(f"  t={a_s['t']:.2f} Bonf×6 p={bonf6_overall:.4f}")
print(f"  DSR PASS if Bonf×6 p<0.05: {'PASS' if bonf6_overall < 0.05 else 'FAIL'}")

# ---------- 4. 衰减检查（按 era）----------
print(f"\n{'='*70}")
print("4. 衰减检查（按 era + 2022 后）")
print(f"{'='*70}")
eras = [('2004-2010', '2004-01-01', '2010-12-31'),
        ('2011-2017', '2011-01-01', '2017-12-31'),
        ('2018-2021', '2018-01-01', '2021-12-31'),
        ('2022+', '2022-01-01', '2099-12-31')]
for label, d0, d1 in eras:
    sub = [p['ret'] for p in a_picks if d0 <= p['buy_date'] <= d1]
    s = stats(sub)
    if s['n'] > 0:
        print(f"  {label}: n={s['n']} EV={s['mean']:.3f}% WR={s['wr']*100:.1f}% "
              f"median={s['median']:.3f}% p={s['p']:.4f}")

# ---------- verdict ----------
print(f"\n{'='*70}")
print("verdict 判定")
print(f"{'='*70}")
checks = {
    'lift>2x': lift > 2.0,
    'Bonf×6 PASS': bonf6_overall < 0.05,
    'walk-forward test PASS': te_s['mean'] > 0 and te_s['p'] < 0.05,
    'median>0': a_s['median'] > 0,
    'WR>55%': a_s['wr'] > 0.55,
    '2022后仍正': any(stats([p['ret'] for p in a_picks if p['buy_date'] >= '2022-01-01'])['mean'] > 0 for _ in [0]),
}
for k, v in checks.items():
    print(f"  {'✅' if v else '❌'} {k}")

passed = sum(checks.values())
total = len(checks)
if passed == total:
    verdict = "edge-confirmed"
elif passed >= total - 1:
    verdict = "provisional/exploratory"
else:
    verdict = "falsified"
print(f"\n  {passed}/{total} PASS → verdict: {verdict}")
print(f"\n  注：A 组是 TOM 在节假日语境的放大变体，TOM 2022 后死。")
print(f"  2022 后 A 组 n={stats([p['ret'] for p in a_picks if p['buy_date'] >= '2022-01-01'])['n']} underpowered。")
