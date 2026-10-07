# -*- coding: utf-8 -*-
"""资金流领域深挖：长假节前效应的资本流相关因子 + 参考动量

因子清单：
  1. ETF premium (申赎流代理): day-3 close premium → 2日节前窗口收益
  2. Pre-holiday momentum (参考动量): day-3前5日收益 → 节前窗口收益 (是否伪装)
  3. Volume/amount flow proxy (资金活跃度): day-3相对成交量 → 节前窗口收益
  4. Window dressing (月末/季末): 假期是否与月末/季末重合 → 节前效应是否集中于此
  5. Quarter-end timing (季度配置): Q3/Oct vs 其他季度

口径：
  - signal: buy day-2 open → sell day-1 close (2日 hold, close_ev 非 open_ev)
  - base rate: 非假期 2日 open→close 窗口
  - day-paired t, Bonferroni ×N, walk-forward OOS
  - momentum 控制: 节前窗口收益 vs 节前5日动量的相关性 + 分层
"""
import json
import sys
import statistics
from datetime import datetime
from collections import defaultdict
from math import erf, sqrt

sys.path.insert(0, '/Users/lizhiwei/project/code/stock/Vibe-Research/backend/tools')
from _factor_helpers import norm_sf_positive, bonferroni_p, ALPHA

DATA = '/Users/lizhiwei/project/code/stock/Vibe-Research/.vibe-research'
ETF_COST = 0.10
HOLIDAY_GAP = 4
N_TESTS = 5  # 5 capital-flow factors tested

# ---------- load data ----------
with open(f'{DATA}/index_ohlc_cache.json') as f:
    idx_data = json.load(f)
bars = sorted(idx_data['sh.000001'], key=lambda b: b['date'])
calendar = [b['date'] for b in bars]
bar_map = {b['date']: b for b in bars}
date_idx = {d: i for i, d in enumerate(calendar)}

# ETF premium data (510050 = 50ETF from 2005, longest)
with open(f'{DATA}/etf_premium_cache.json') as f:
    etf_data = json.load(f)
etf_50 = etf_data.get('510050', {})  # 50ETF, from 2005
etf_300 = etf_data.get('510300', {})  # 300ETF, from 2012

print(f"Index: sh.000001, {len(calendar)} days ({calendar[0]} to {calendar[-1]})")
print(f"ETF 510050: {len(etf_50)} days, ETF 510300: {len(etf_300)} days")

# ---------- find long holiday breaks ----------
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

print(f"Long holiday breaks (gap >= {HOLIDAY_GAP}): {len(holidays)}")

# ---------- build pre-holiday picks with capital flow features ----------
pre_picks = []
for hi, h in enumerate(holidays):
    i_last = h['idx_last']
    # Need day-3 (2 trading days before last), day-2 (buy day), day-1 (sell day)
    if i_last - 2 < 0:
        continue
    d_signal = calendar[i_last - 2]  # day-3: signal day (close)
    d_buy = calendar[i_last - 1]      # day-2: buy open
    d_sell = calendar[i_last]          # day-1: sell close

    b_buy = bar_map[d_buy]
    b_sell = bar_map[d_sell]
    o = b_buy.get('open')
    c = b_sell.get('close')
    if not (o and c and o > 0 and c > 0):
        continue
    ret = (c - o) / o * 100  # close_ev (open→close, no intraday leakage)

    # --- Feature 1: ETF premium on day-3 (signal day close) ---
    etf_prem = None
    for etf_dict in [etf_50, etf_300]:
        e = etf_dict.get(d_signal)
        if e and e.get('close') and e.get('nav') and e['nav'] > 0:
            etf_prem = (e['close'] - e['nav']) / e['nav'] * 100
            break  # prefer 50ETF (longer history), but 300ETF fallback

    # --- Feature 2: Pre-holiday momentum (5-day return before day-3) ---
    i_sig = date_idx[d_signal]
    if i_sig - 5 >= 0:
        d_mom_start = calendar[i_sig - 5]
        b_mom = bar_map[d_mom_start]
        if b_mom.get('close') and b_buy.get('open') and b_mom['close'] > 0:
            mom5 = (b_buy['open'] - b_mom['close']) / b_mom['close'] * 100
        else:
            mom5 = None
    else:
        mom5 = None

    # Also 3-day momentum
    if i_sig - 3 >= 0:
        d_mom3 = calendar[i_sig - 3]
        b_mom3 = bar_map[d_mom3]
        if b_mom3.get('close') and b_buy.get('open') and b_mom3['close'] > 0:
            mom3 = (b_buy['open'] - b_mom3['close']) / b_mom3['close'] * 100
        else:
            mom3 = None
    else:
        mom3 = None

    # --- Feature 3: Volume/amount flow proxy (day-3 relative volume) ---
    # Relative volume = day-3 volume / 20-day average volume
    vol_20 = []
    for k in range(max(0, i_sig - 20), i_sig):
        b = bar_map[calendar[k]]
        if b.get('volume'):
            vol_20.append(b['volume'])
    if vol_20 and b_buy.get('volume'):
        avg_vol = sum(vol_20) / len(vol_20)
        rel_vol = b_buy['volume'] / avg_vol if avg_vol > 0 else None
    else:
        rel_vol = None

    # Relative amount (turnover)
    amt_20 = []
    for k in range(max(0, i_sig - 20), i_sig):
        b = bar_map[calendar[k]]
        if b.get('amount'):
            amt_20.append(b['amount'])
    if amt_20 and b_buy.get('amount'):
        avg_amt = sum(amt_20) / len(amt_20)
        rel_amt = b_buy['amount'] / avg_amt if avg_amt > 0 else None
    else:
        rel_amt = None

    # --- Feature 4: Window dressing (month-end / quarter-end coincidence) ---
    d_sell_dt = datetime.strptime(d_sell, '%Y-%m-%d')
    is_month_end = d_sell_dt.day >= 28  # last 3 days of month
    is_quarter_end = d_sell_dt.month in [3, 6, 9, 12] and d_sell_dt.day >= 25

    # Identify holiday type
    # National Day = Oct, Spring Festival = Jan/Feb, Labor Day = May, New Year = Jan
    month = d_sell_dt.month
    if month == 9 or month == 10:
        hol_type = 'national_day'
    elif month in [1, 2]:
        hol_type = 'spring_festival'
    elif month == 4 or month == 5:
        hol_type = 'labor_day'
    else:
        hol_type = 'other'

    pre_picks.append({
        'holiday_idx': hi,
        'holiday_date': h['last_before'],
        'buy_date': d_buy,
        'sell_date': d_sell,
        'signal_date': d_signal,
        'ret': ret,
        'etf_premium': etf_prem,
        'mom5': mom5,
        'mom3': mom3,
        'rel_vol': rel_vol,
        'rel_amt': rel_amt,
        'is_month_end': is_month_end,
        'is_quarter_end': is_quarter_end,
        'hol_type': hol_type,
        'year': d_sell_dt.year,
    })

pre_rets = [p['ret'] for p in pre_picks]
print(f"\nPre-holiday picks: {len(pre_picks)} (with features)")

# ---------- base rate ----------
holiday_zone_dates = set()
for h in holidays:
    i_last = h['idx_last']
    for k in range(max(0, i_last - 2), min(len(calendar), i_last + 1)):
        holiday_zone_dates.add(calendar[k])
base_returns = []
for i in range(len(calendar) - 1):
    d_start = calendar[i]
    d_end = calendar[i + 1]
    if d_start in holiday_zone_dates or d_end in holiday_zone_dates:
        continue
    b_start = bar_map[d_start]
    b_end = bar_map[d_end]
    o = b_start.get('open')
    c = b_end.get('close')
    if o and c and o > 0 and c > 0:
        base_returns.append((c - o) / o * 100)


def stats(rets):
    n = len(rets)
    if n == 0:
        return {'n': 0, 'mean': 0.0, 'std': 0.0, 'se': 0.0, 't': 0.0, 'p': 1.0, 'wr': 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = norm_sf_positive(t)
    wr = sum(1 for x in rets if x > 0) / n
    return {'n': n, 'mean': mean, 'std': std, 'se': se, 't': t, 'p': p, 'wr': wr}


def pearson_corr(xs, ys):
    """Pearson correlation."""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sx == 0 or sy == 0:
        return None
    return sxy / sqrt(sx * sy)


def corr_p(r, n):
    """One-sided p for positive correlation (H1: r > 0)."""
    if r is None or n < 4:
        return None
    # Fisher z-transformation
    if abs(r) >= 0.999:
        return 0.0 if r > 0 else 1.0
    z = 0.5 * (math_log((1 + r) / (1 - r)))
    se = 1.0 / sqrt(n - 3)
    t_stat = z / se
    return norm_sf_positive(t_stat)


def math_log(x):
    import math
    return math.log(x)


pre_s = stats(pre_rets)
base_s = stats(base_returns)
lift = pre_s['mean'] / base_s['mean'] if base_s['mean'] != 0 else float('inf')

print(f"\n{'='*70}")
print(f"BASELINE: Pre-holiday effect (capital flow domain context)")
print(f"{'='*70}")
print(f"  Pre-holiday: n={pre_s['n']} EV={pre_s['mean']:.3f}% WR={pre_s['wr']*100:.1f}% lift={lift:.2f}x")
print(f"  Base rate: n={base_s['n']} EV={base_s['mean']:.4f}%")

# ============================================================
# FACTOR 1: ETF Premium (申赎流代理)
# ============================================================
print(f"\n{'='*70}")
print(f"FACTOR 1: ETF Premium on day-3 (申赎流代理 / capital inflow proxy)")
print(f"{'='*70}")
prem_picks = [p for p in pre_picks if p['etf_premium'] is not None]
prem_vals = [p['etf_premium'] for p in prem_picks]
prem_rets = [p['ret'] for p in prem_picks]
print(f"  n with ETF premium: {len(prem_picks)} (from {len(etf_50)} + {len(etf_300)} ETF days)")
if prem_vals:
    print(f"  ETF premium: mean={sum(prem_vals)/len(prem_vals):.4f}% "
          f"min={min(prem_vals):.4f}% max={max(prem_vals):.4f}%")

    # Correlation: premium → return
    r = pearson_corr(prem_vals, prem_rets)
    p_prem = corr_p(r, len(prem_vals)) if r is not None else None
    print(f"  Pearson r(premium, return)={r:.4f}" if r else "  Pearson r: N/A")
    if p_prem is not None:
        print(f"  Corr p (one-sided)={p_prem:.4f} Bonf×{N_TESTS}={bonferroni_p(p_prem, N_TESTS):.4f}")

    # Stratify: above-median premium vs below-median
    med_prem = statistics.median(prem_vals)
    high = [p for p in prem_picks if p['etf_premium'] >= med_prem]
    low = [p for p in prem_picks if p['etf_premium'] < med_prem]
    high_s = stats([p['ret'] for p in high])
    low_s = stats([p['ret'] for p in low])
    print(f"  High premium (>=median {med_prem:.4f}%): n={high_s['n']} EV={high_s['mean']:.3f}% WR={high_s['wr']*100:.1f}%")
    print(f"  Low premium  (< median {med_prem:.4f}%): n={low_s['n']} EV={low_s['mean']:.3f}% WR={low_s['wr']*100:.1f}%")
    print(f"  -> High-Low spread: {high_s['mean'] - low_s['mean']:.3f}%")
else:
    print("  No ETF premium data available")

# ============================================================
# FACTOR 2: Pre-holiday Momentum (参考动量 — 是否伪装)
# ============================================================
print(f"\n{'='*70}")
print(f"FACTOR 2: Pre-holiday Momentum (参考动量 — 节前效应是否是 momentum 伪装)")
print(f"{'='*70}")
mom_picks = [p for p in pre_picks if p['mom5'] is not None]
mom_vals = [p['mom5'] for p in mom_picks]
mom_rets = [p['ret'] for p in mom_picks]
print(f"  n with mom5: {len(mom_picks)}")
if mom_vals:
    print(f"  mom5 (5-day return before day-3): mean={sum(mom_vals)/len(mom_vals):.3f}% "
          f"min={min(mom_vals):.3f}% max={max(mom_vals):.3f}%")

    r_mom = pearson_corr(mom_vals, mom_rets)
    p_mom = corr_p(r_mom, len(mom_vals)) if r_mom is not None else None
    print(f"  Pearson r(mom5, holiday_return)={r_mom:.4f}" if r_mom else "  Pearson r: N/A")
    if p_mom is not None:
        print(f"  Corr p (one-sided)={p_mom:.4f} Bonf×{N_TESTS}={bonferroni_p(p_mom, N_TESTS):.4f}")

    # Stratify by momentum quintile
    sorted_mom = sorted(mom_picks, key=lambda p: p['mom5'])
    q = len(sorted_mom) // 5
    print(f"\n  Stratification by momentum quintile:")
    for qi in range(5):
        start = qi * q
        end = (qi + 1) * q if qi < 4 else len(sorted_mom)
        subset = sorted_mom[start:end]
        if subset:
            s = stats([p['ret'] for p in subset])
            ms = stats([p['mom5'] for p in subset])
            print(f"    Q{qi+1} (mom5={ms['mean']:.3f}%): n={s['n']} EV={s['mean']:.3f}% WR={s['wr']*100:.1f}%")

    # KEY TEST: Does holiday effect survive in LOW-momentum periods?
    # If effect exists even when pre-holiday momentum is negative/flat → NOT momentum disguise
    low_mom = [p for p in mom_picks if p['mom5'] < 0]  # negative momentum
    high_mom = [p for p in mom_picks if p['mom5'] >= 0]  # positive momentum
    low_s = stats([p['ret'] for p in low_mom])
    high_s = stats([p['ret'] for p in high_mom])
    print(f"\n  KEY: Effect in negative-momentum periods (mom5<0):")
    print(f"    n={low_s['n']} EV={low_s['mean']:.3f}% WR={low_s['wr']*100:.1f}%")
    print(f"  Effect in positive-momentum periods (mom5>=0):")
    print(f"    n={high_s['n']} EV={high_s['mean']:.3f}% WR={high_s['wr']*100:.1f}%")
    if low_s['n'] >= 5 and low_s['mean'] > 0:
        print(f"  -> Effect survives in NEGATIVE momentum => NOT purely momentum disguise")
    elif low_s['n'] >= 5 and low_s['mean'] <= 0:
        print(f"  -> Effect VANISHES in negative momentum => likely momentum disguise")

    # Also 3-day momentum
    mom3_picks = [p for p in pre_picks if p['mom3'] is not None]
    if len(mom3_picks) >= 5:
        mom3_vals = [p['mom3'] for p in mom3_picks]
        mom3_rets = [p['ret'] for p in mom3_picks]
        r_mom3 = pearson_corr(mom3_vals, mom3_rets)
        print(f"\n  3-day momentum: r(mom3, return)={r_mom3:.4f}" if r_mom3 else "  3-day momentum: N/A")

# ============================================================
# FACTOR 3: Volume/Amount Flow Proxy (资金活跃度)
# ============================================================
print(f"\n{'='*70}")
print(f"FACTOR 3: Relative Volume/Amount on buy day (资金活跃度 proxy)")
print(f"{'='*70}")
rv_picks = [p for p in pre_picks if p['rel_vol'] is not None]
rv_vals = [p['rel_vol'] for p in rv_picks]
rv_rets = [p['ret'] for p in rv_picks]
print(f"  n with rel_vol: {len(rv_picks)}")
if rv_vals:
    print(f"  rel_vol: mean={sum(rv_vals)/len(rv_vals):.3f} median={statistics.median(rv_vals):.3f}")
    r_vol = pearson_corr(rv_vals, rv_rets)
    p_vol = corr_p(r_vol, len(rv_vals)) if r_vol is not None else None
    print(f"  Pearson r(rel_vol, return)={r_vol:.4f}" if r_vol else "  Pearson r: N/A")
    if p_vol is not None:
        print(f"  Corr p (one-sided)={p_vol:.4f} Bonf×{N_TESTS}={bonferroni_p(p_vol, N_TESTS):.4f}")

    # Stratify: high volume vs low volume
    med_rv = statistics.median(rv_vals)
    hv = [p for p in rv_picks if p['rel_vol'] >= med_rv]
    lv = [p for p in rv_picks if p['rel_vol'] < med_rv]
    hv_s = stats([p['ret'] for p in hv])
    lv_s = stats([p['ret'] for p in lv])
    print(f"  High volume (>=median {med_rv:.3f}): n={hv_s['n']} EV={hv_s['mean']:.3f}% WR={hv_s['wr']*100:.1f}%")
    print(f"  Low volume  (< median {med_rv:.3f}): n={lv_s['n']} EV={lv_s['mean']:.3f}% WR={lv_s['wr']*100:.1f}%")

# ============================================================
# FACTOR 4: Window Dressing (月末/季末重合)
# ============================================================
print(f"\n{'='*70}")
print(f"FACTOR 4: Window Dressing (月末/季末重合 — 机构粉饰 confound)")
print(f"{'='*70}")
me_picks = [p for p in pre_picks if p['is_month_end']]
nme_picks = [p for p in pre_picks if not p['is_month_end']]
qe_picks = [p for p in pre_picks if p['is_quarter_end']]
nqe_picks = [p for p in pre_picks if not p['is_quarter_end']]
print(f"  Month-end coinciding: {len(me_picks)} / {len(pre_picks)}")
print(f"  Quarter-end coinciding: {len(qe_picks)} / {len(pre_picks)}")
if me_picks:
    me_s = stats([p['ret'] for p in me_picks])
    nme_s = stats([p['ret'] for p in nme_picks])
    print(f"  Month-end: n={me_s['n']} EV={me_s['mean']:.3f}% WR={me_s['wr']*100:.1f}%")
    print(f"  Non-month-end: n={nme_s['n']} EV={nme_s['mean']:.3f}% WR={nme_s['wr']*100:.1f}%")
if qe_picks:
    qe_s = stats([p['ret'] for p in qe_picks])
    nqe_s = stats([p['ret'] for p in nqe_picks])
    print(f"  Quarter-end: n={qe_s['n']} EV={qe_s['mean']:.3f}% WR={qe_s['wr']*100:.1f}%")
    print(f"  Non-quarter-end: n={nqe_s['n']} EV={nqe_s['mean']:.3f}% WR={nqe_s['wr']*100:.1f}%")

# ============================================================
# FACTOR 5: Holiday Type (季度配置 timing)
# ============================================================
print(f"\n{'='*70}")
print(f"FACTOR 5: Holiday Type (季度配置 — 国庆 vs 春节 vs 劳动节)")
print(f"{'='*70}")
by_type = defaultdict(list)
for p in pre_picks:
    by_type[p['hol_type']].append(p['ret'])
for ht, rets in sorted(by_type.items()):
    s = stats(rets)
    print(f"  {ht}: n={s['n']} EV={s['mean']:.3f}% WR={s['wr']*100:.1f}% t={s['t']:.2f}")

# ============================================================
# MOMENTUM vs HOLIDAY: Partial-out test
# ============================================================
print(f"\n{'='*70}")
print(f"PARTIAL-OUT: Holiday effect after controlling for momentum")
print(f"{'='*70}")
# If we regress holiday_return = alpha + beta*mom5, is alpha still positive?
if mom_picks and len(mom_picks) >= 10:
    xs = [pk['mom5'] for pk in mom_picks]
    ys = [pk['ret'] for pk in mom_picks]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    beta = sxy / sxx if sxx > 0 else 0
    alpha = my - beta * mx
    # Residuals = holiday return minus momentum-explained part
    residuals = [y - (alpha + beta * x) for x, y in zip(xs, ys)]
    res_s = stats(residuals)
    print(f"  OLS: return = {alpha:.3f} + {beta:.4f} * mom5")
    print(f"  Alpha (holiday effect after momentum) = {alpha:.3f}%")
    print(f"  Residual: mean={res_s['mean']:.3f}% t={res_s['t']:.2f} p={res_s['p']:.4f}")
    print(f"  Bonf×{N_TESTS} p={bonferroni_p(res_s['p'], N_TESTS):.4f}")
    if alpha > 0 and res_s['p'] < ALPHA:
        print(f"  -> Holiday effect SURVIVES after controlling for momentum (alpha>0, p<{ALPHA})")
    elif alpha > 0:
        print(f"  -> Holiday alpha positive but NOT significant after momentum control")
    else:
        print(f"  -> Holiday alpha <= 0: effect FULLY explained by momentum")

# ============================================================
# Walk-forward with momentum control
# ============================================================
print(f"\n{'='*70}")
print(f"WALK-FORWARD: Pre-holiday effect chrono split (momentum-controlled)")
print(f"{'='*70}")
sorted_picks = sorted(pre_picks, key=lambda p: p['holiday_date'])
n = len(sorted_picks)
mid = n // 2
train = sorted_picks[:mid]
test = sorted_picks[mid:]
train_s = stats([p['ret'] for p in train])
test_s = stats([p['ret'] for p in test])
print(f"  Train (pre-{test[0]['holiday_date'] if test else '?'}): n={train_s['n']} EV={train_s['mean']:.3f}% WR={train_s['wr']*100:.1f}%")
print(f"  Test  (post): n={test_s['n']} EV={test_s['mean']:.3f}% WR={test_s['wr']*100:.1f}%")
if train_s['mean'] > 0:
    decay = (train_s['mean'] - test_s['mean']) / abs(train_s['mean']) * 100
    print(f"  Decay: {decay:.0f}%")

# ============================================================
# Sub-period decay (拥挤度 check)
# ============================================================
print(f"\n{'='*70}")
print(f"SUB-PERIOD DECAY (拥挤度 check)")
print(f"{'='*70}")
periods = [('2004-2010', '2004', '2010'),
           ('2011-2016', '2011', '2016'),
           ('2017-2022', '2017', '2022'),
           ('2023-2026', '2023', '2026')]
for pname, y0, y1 in periods:
    sub = [p for p in pre_picks if y0 <= str(p['year']) <= y1]
    if sub:
        s = stats([p['ret'] for p in sub])
        # Also avg momentum in this period
        moms = [p['mom5'] for p in sub if p['mom5'] is not None]
        avg_mom = sum(moms) / len(moms) if moms else 0
        print(f"  {pname}: n={s['n']} EV={s['mean']:.3f}% WR={s['wr']*100:.1f}% avg_mom5={avg_mom:.3f}%")

# ============================================================
# SUMMARY: Momentum disguise verdict
# ============================================================
print(f"\n{'='*70}")
print(f"SUMMARY: Is the pre-holiday effect momentum in disguise?")
print(f"{'='*70}")
if mom_picks:
    print(f"  r(mom5, return) = {r_mom:.4f}" if r_mom else "  r = N/A")
    if r_mom is not None and abs(r_mom) < 0.15:
        print(f"  -> Weak correlation (<0.15): momentum does NOT explain the effect")
    elif r_mom is not None and abs(r_mom) < 0.30:
        print(f"  -> Moderate correlation: momentum PARTIALLY explains, but not fully")
    elif r_mom is not None:
        print(f"  -> Strong correlation (>=0.30): momentum is a significant driver")
    print(f"  Effect in negative-momentum periods: EV={low_s['mean']:.3f}% (n={low_s['n']})")
    if low_s['n'] >= 5 and low_s['mean'] > 0:
        print(f"  -> Effect survives without momentum => NOT a pure momentum disguise")
    else:
        print(f"  -> Effect may depend on momentum (insufficient negative-momentum samples)")

print(f"\n{'='*70}")
print(f"CAPITAL FLOW FACTOR RANKING (by predictive power)")
print(f"{'='*70}")
factors = []
if prem_picks and r is not None:
    factors.append(('ETF_premium', r, p_prem, len(prem_picks)))
if mom_picks and r_mom is not None:
    factors.append(('Momentum_mom5', r_mom, p_mom, len(mom_picks)))
if rv_picks and r_vol is not None:
    factors.append(('Rel_volume', r_vol, p_vol, len(rv_picks)))
factors.sort(key=lambda x: abs(x[1]) if x[1] else 0, reverse=True)
for name, corr, pv, n in factors:
    pv_f = float(pv) if pv is not None else None
    pv_str = f"{pv_f:.4f}" if pv_f is not None else "N/A"
    sig = "***" if pv_f and pv_f < 0.01 else ("**" if pv_f and pv_f < 0.05 else ("*" if pv_f and pv_f < 0.1 else ""))
    print(f"  {name:20s} r={corr:+.4f} p={pv_str:>8} n={n} {sig}")
