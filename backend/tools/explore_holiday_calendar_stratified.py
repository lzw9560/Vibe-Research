# -*- coding: utf-8 -*-
"""长假节前效应 — 日历/季节性领域深挖

分长假类型(春节/国庆/中秋/端午/劳动节/清明/元旦)分层算 BHAR/raw_EV,
看是"所有长假普适"还是"特定长假"(春节躁动/国庆红包)。
参考动量: 节前是否是 momentum 的提前反应(节前 return vs 前20日 momentum 相关性)。
相关因子: 月末月初/周内/1月效应/月末发薪。
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

with open(f'{DATA}/index_ohlc_cache.json') as f:
    idx_data = json.load(f)

bars_sh = sorted(idx_data['sh.000001'], key=lambda b: b['date'])

calendar = [b['date'] for b in bars_sh]
bar_map = {b['date']: b for b in bars_sh}
date_idx = {d: i for i, d in enumerate(calendar)}

HOLIDAY_GAP = 4
ETF_COST = 0.10

# ---------- identify long holiday breaks ----------
holidays = []
for i in range(1, len(calendar)):
    d0 = datetime.strptime(calendar[i - 1], '%Y-%m-%d')
    d1 = datetime.strptime(calendar[i], '%Y-%m-%d')
    gap = (d1 - d0).days
    if gap >= HOLIDAY_GAP:
        holidays.append({
            'last_before': calendar[i - 1],
            'first_after': calendar[i],
            'gap': gap,
            'idx_last': i - 1,
            'idx_first': i,
        })

# ---------- classify holiday type by month + gap ----------
def classify_holiday(h):
    """按月+gap推断长假类型. last_before 是节前最后交易日."""
    last_dt = datetime.strptime(h['last_before'], '%Y-%m-%d')
    month = last_dt.month
    gap = h['gap']
    # 春节: 1月底-2月, gap >= 7 (最长)
    if month in (1, 2) and gap >= 7:
        return '春节'
    # 国庆: 9月底-10月, gap >= 5
    if month in (9, 10) and gap >= 5:
        return '国庆'
    # 中秋: 9月, gap 3-4 (非国庆)
    if month == 9 and gap < 5:
        return '中秋'
    # 劳动节: 4月底-5月, gap >= 3
    if month in (4, 5) and 3 <= gap <= 6:
        # 清明也在4月, 但清明通常 gap 3, 劳动节 gap 3-5
        # 区分: 清明 ~4/4-6, 劳动节 ~5/1-5
        if month == 4:
            return '清明'
        return '劳动节'
    # 端午: 6月, gap 3-4
    if month == 6 and gap >= 3:
        return '端午'
    # 元旦: 12月底-1月, gap 3-4 (非春节)
    if month in (12, 1) and gap < 7:
        return '元旦'
    return '其他'


for h in holidays:
    h['type'] = classify_holiday(h)

print(f"Total long holidays: {len(holidays)}")
type_counts = defaultdict(int)
for h in holidays:
    type_counts[h['type']] += 1
for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
    print(f"  {t}: {c}")

# ---------- build pre-holiday picks per type ----------
def build_pre_picks(holiday_list):
    picks = []
    for hi, h in enumerate(holiday_list):
        i_last = h['idx_last']
        if i_last - 1 >= 0:
            d_buy = calendar[i_last - 1]
            d_sell = calendar[i_last]
            b_buy = bar_map[d_buy]
            b_sell = bar_map[d_sell]
            o = b_buy.get('open')
            c = b_sell.get('close')
            if o and c and o > 0 and c > 0:
                ret = (c - o) / o * 100
                picks.append({
                    'holiday_idx': hi,
                    'holiday_date': h['last_before'],
                    'type': h['type'],
                    'buy_date': d_buy,
                    'sell_date': d_sell,
                    'entry': o,
                    'exit': c,
                    'ret': ret,
                })
    return picks

pre_picks_all = build_pre_picks(holidays)

# ---------- stratified stats by holiday type ----------
def stats(rets):
    n = len(rets)
    if n == 0:
        return {'n': 0, 'mean': 0.0, 'std': 0.0, 'se': 0.0, 't': 0.0, 'p': 1.0, 'wr': 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    # one-sided p (edge > 0)
    p = 0.5 * (1 - erf(t / sqrt(2))) if t > 0 else 1.0
    wr = sum(1 for x in rets if x > 0) / n
    return {'n': n, 'mean': mean, 'std': std, 'se': se, 't': t, 'p': p, 'wr': wr}

print(f"\n{'='*70}")
print("PRE-HOLIDAY by TYPE (stratified)")
print(f"{'='*70}")
print(f"{'Type':<8} {'n':>4} {'gross_EV%':>10} {'net_EV%':>9} {'WR%':>6} {'t':>6} {'p_raw':>10} {'lift':>6}")
print("-" * 70)

# base rate
holiday_zone = set()
for h in holidays:
    for k in range(max(0, h['idx_last'] - 2), min(len(calendar), h['idx_last'] + 1)):
        holiday_zone.add(calendar[k])
    for k in range(h['idx_first'], min(len(calendar), h['idx_first'] + 2)):
        holiday_zone.add(calendar[k])
base_returns = []
for i in range(len(calendar) - 1):
    d_start, d_end = calendar[i], calendar[i + 1]
    if d_start in holiday_zone or d_end in holiday_zone:
        continue
    b_s, b_e = bar_map[d_start], bar_map[d_end]
    o, c = b_s.get('open'), b_e.get('close')
    if o and c and o > 0 and c > 0:
        base_returns.append((c - o) / o * 100)
base_s = stats(base_returns)
print(f"{'BASE':<8} {base_s['n']:>4} {base_s['mean']:>10.4f} {'':>9} {base_s['wr']*100:>6.1f} {'':>6} {'':>10} {'1.00x':>6}")

type_results = {}
for htype in ['春节', '国庆', '中秋', '端午', '劳动节', '清明', '元旦', '其他']:
    sub = [p for p in pre_picks_all if p['type'] == htype]
    if not sub:
        continue
    s = stats([p['ret'] for p in sub])
    lift = s['mean'] / base_s['mean'] if base_s['mean'] != 0 else float('inf')
    type_results[htype] = {'stats': s, 'lift': lift, 'picks': sub}
    print(f"{htype:<8} {s['n']:>4} {s['mean']:>10.3f} {s['mean']-ETF_COST:>9.3f} "
          f"{s['wr']*100:>6.1f} {s['t']:>6.2f} {s['p']:>10.6f} {lift:>5.2f}x")

# ---------- index comparison note ----------
print(f"\n{'='*70}")
print("NOTE: Only sh.000001 (Shanghai Composite) in cache. HS300/ZZ500 not cached.")
print(f"{'='*70}")

# ---------- MOMENTUM REFERENCE: is pre-holiday return just prior trend continuation? ----------
print(f"\n{'='*70}")
print("MOMENTUM REFERENCE: pre-holiday return vs prior 20-day momentum")
print(f"{'='*70}")
# For each holiday, compute:
# 1. pre-holiday return (day-2 open -> day-1 close)
# 2. prior 20-trading-day return (momentum before the pre-holiday window)
# If pre-holiday is momentum continuation -> high correlation
momentum_data = []
for h in holidays:
    i_last = h['idx_last']
    if i_last - 21 >= 0 and i_last - 1 >= 0:
        d_mom_start = calendar[i_last - 21]
        d_mom_end = calendar[i_last - 2]  # day before buy
        b_ms = bar_map.get(d_mom_start)
        b_me = bar_map.get(d_mom_end)
        d_buy = calendar[i_last - 1]
        d_sell = calendar[i_last]
        b_buy = bar_map.get(d_buy)
        b_sell = bar_map.get(d_sell)
        if all(b and b.get('close') and b.get('open') for b in [b_ms, b_me, b_buy, b_sell]):
            mom = (b_me['close'] - b_ms['close']) / b_ms['close'] * 100
            pre_ret = (b_sell['close'] - b_buy['open']) / b_buy['open'] * 100
            momentum_data.append({
                'type': h['type'],
                'mom_20d': mom,
                'pre_ret': pre_ret,
            })

if momentum_data:
    moms = [d['mom_20d'] for d in momentum_data]
    pres = [d['pre_ret'] for d in momentum_data]
    n = len(momentum_data)
    mean_mom = sum(moms) / n
    mean_pre = sum(pres) / n
    # Pearson correlation
    cov = sum((m - mean_mom) * (p - mean_pre) for m, p in zip(moms, pres)) / n
    std_mom = statistics.pstdev(moms)
    std_pre = statistics.pstdev(pres)
    corr = cov / (std_mom * std_pre) if std_mom > 0 and std_pre > 0 else 0
    print(f"  n={n}")
    print(f"  Prior 20-day momentum mean: {mean_mom:.3f}%")
    print(f"  Pre-holiday return mean: {mean_pre:.3f}%")
    print(f"  Pearson correlation (mom vs pre_ret): {corr:.3f}")
    # Split: holidays where prior momentum > 0 vs < 0
    up = [d for d in momentum_data if d['mom_20d'] > 0]
    dn = [d for d in momentum_data if d['mom_20d'] <= 0]
    if up:
        up_rets = [d['pre_ret'] for d in up]
        up_s = stats(up_rets)
        print(f"  Prior momentum UP (n={len(up)}): pre-holiday EV={up_s['mean']:.3f}% WR={up_s['wr']*100:.1f}%")
    if dn:
        dn_rets = [d['pre_ret'] for d in dn]
        dn_s = stats(dn_rets)
        print(f"  Prior momentum DOWN (n={len(dn)}): pre-holiday EV={dn_s['mean']:.3f}% WR={dn_s['wr']*100:.1f}%")
    print(f"  -> If corr ~0 and both up/down positive => NOT momentum, pure calendar effect")
    print(f"  -> If corr high (>0.3) and down-subset EV<=0 => momentum disguise")

# ---------- RELATED CALENDAR FACTORS ----------
print(f"\n{'='*70}")
print("RELATED CALENDAR FACTORS (all non-holiday windows excluded)")
print(f"{'='*70}")

# Factor 1: Turn of month (last 3 trading days + first 3 trading days)
def is_turn_of_month(date_str):
    """Check if date is in last 3 or first 3 trading days of month."""
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    # get all trading days in this month
    ym = date_str[:7]
    month_days = [d for d in calendar if d[:7] == ym]
    if not month_days:
        return False
    if date_str in month_days[:3] or date_str in month_days[-3:]:
        return True
    return False

tom_rets = []
for i in range(len(calendar) - 1):
    d_start, d_end = calendar[i], calendar[i + 1]
    if d_start in holiday_zone or d_end in holiday_zone:
        continue
    if is_turn_of_month(d_start):
        b_s, b_e = bar_map[d_start], bar_map[d_end]
        o, c = b_s.get('open'), b_e.get('close')
        if o and c and o > 0:
            tom_rets.append((c - o) / o * 100)
tom_s = stats(tom_rets)
print(f"  Turn-of-month (last3+first3): n={tom_s['n']} EV={tom_s['mean']:.4f}% WR={tom_s['wr']*100:.1f}% lift={tom_s['mean']/base_s['mean']:.2f}x")

# Factor 2: January effect (all January windows)
jan_rets = []
for i in range(len(calendar) - 1):
    d_start, d_end = calendar[i], calendar[i + 1]
    if d_start in holiday_zone or d_end in holiday_zone:
        continue
    if d_start[5:7] == '01':
        b_s, b_e = bar_map[d_start], bar_map[d_end]
        o, c = b_s.get('open'), b_e.get('close')
        if o and c and o > 0:
            jan_rets.append((c - o) / o * 100)
jan_s = stats(jan_rets)
print(f"  January effect: n={jan_s['n']} EV={jan_s['mean']:.4f}% WR={jan_s['wr']*100:.1f}% lift={jan_s['mean']/base_s['mean']:.2f}x")

# Factor 3: Day of week
print(f"\n  Day-of-week effect (non-holiday 2-day windows):")
for dow_name, dow_num in [('Mon', 0), ('Tue', 1), ('Wed', 2), ('Thu', 3), ('Fri', 4)]:
    dow_rets = []
    for i in range(len(calendar) - 1):
        d_start, d_end = calendar[i], calendar[i + 1]
        if d_start in holiday_zone or d_end in holiday_zone:
            continue
        dt = datetime.strptime(d_start, '%Y-%m-%d')
        if dt.weekday() == dow_num:
            b_s, b_e = bar_map[d_start], bar_map[d_end]
            o, c = b_s.get('open'), b_e.get('close')
            if o and c and o > 0:
                dow_rets.append((c - o) / o * 100)
    s = stats(dow_rets)
    print(f"    {dow_name}: n={s['n']} EV={s['mean']:.4f}% WR={s['wr']*100:.1f}% lift={s['mean']/base_s['mean']:.2f}x")

# Factor 4: Pre-holiday overlap with turn-of-month
print(f"\n  Pre-holiday overlap with turn-of-month:")
tom_overlap = 0
for p in pre_picks_all:
    if is_turn_of_month(p['buy_date']) or is_turn_of_month(p['sell_date']):
        tom_overlap += 1
print(f"    {tom_overlap}/{len(pre_picks_all)} pre-holiday picks overlap turn-of-month ({tom_overlap/len(pre_picks_all)*100:.0f}%)")

# Factor 5: Pre-holiday overlap with end-of-month (payday effect)
print(f"\n  Pre-holiday overlap with end-of-month (last 3 days):")
eom_overlap = 0
for p in pre_picks_all:
    ym = p['buy_date'][:7]
    month_days = [d for d in calendar if d[:7] == ym]
    if month_days and (p['buy_date'] in month_days[-3:] or p['sell_date'] in month_days[-3:]):
        eom_overlap += 1
print(f"    {eom_overlap}/{len(pre_picks_all)} pre-holiday picks overlap end-of-month ({eom_overlap/len(pre_picks_all)*100:.0f}%)")

# ---------- Spring Festival specific deep dive ----------
print(f"\n{'='*70}")
print("SPRING FESTIVAL deep dive (春节躁动)")
print(f"{'='*70}")
cny = [p for p in pre_picks_all if p['type'] == '春节']
if cny:
    cny_s = stats([p['ret'] for p in cny])
    print(f"  n={cny_s['n']} EV={cny_s['mean']:.3f}% WR={cny_s['wr']*100:.1f}% t={cny_s['t']:.2f}")
    # by period
    for pname, y0, y1 in [('2004-2010', '2004', '2010'), ('2011-2016', '2011', '2016'),
                          ('2017-2022', '2017', '2022'), ('2023-2026', '2023', '2026')]:
        sub = [p for p in cny if y0 <= p['holiday_date'][:4] <= y1]
        if sub:
            s = stats([p['ret'] for p in sub])
            print(f"    {pname}: n={s['n']} EV={s['mean']:.3f}% WR={s['wr']*100:.1f}%")

# ---------- National Day specific deep dive ----------
print(f"\n{'='*70}")
print("NATIONAL DAY deep dive (国庆红包)")
print(f"{'='*70}")
nd = [p for p in pre_picks_all if p['type'] == '国庆']
if nd:
    nd_s = stats([p['ret'] for p in nd])
    print(f"  n={nd_s['n']} EV={nd_s['mean']:.3f}% WR={nd_s['wr']*100:.1f}% t={nd_s['t']:.2f}")
    for pname, y0, y1 in [('2004-2010', '2004', '2010'), ('2011-2016', '2011', '2016'),
                          ('2017-2022', '2017', '2022'), ('2023-2026', '2023', '2026')]:
        sub = [p for p in nd if y0 <= p['holiday_date'][:4] <= y1]
        if sub:
            s = stats([p['ret'] for p in sub])
            print(f"    {pname}: n={s['n']} EV={s['mean']:.3f}% WR={s['wr']*100:.1f}%")

print(f"\n{'='*70}")
print("SUMMARY: is pre-holiday universal or holiday-specific?")
print(f"{'='*70}")
universal_types = []
specific_types = []
for htype, res in type_results.items():
    s = res['stats']
    if s['n'] >= 5 and s['mean'] > base_s['mean'] and s['p'] < 0.10:
        specific_types.append((htype, s['mean'], s['p']))
    elif s['n'] >= 5 and s['mean'] <= base_s['mean']:
        universal_types.append((htype, s['mean']))
print(f"  Edge-positive types (EV>base, p<0.10): {specific_types if specific_types else 'NONE'}")
print(f"  Edge-absent types (EV<=base): {universal_types if universal_types else 'NONE'}")
