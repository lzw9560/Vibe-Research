# -*- coding: utf-8 -*-
"""长假节前 A 信号重定义为月末+节假日放大（user #4）。

原 A 信号：长假节前（gap>=4，~30-40 picks）——in-sample Bonf×6=0.006 + raw OOS p=0.017 + DSR pass，
但 Bonf×6 后 OOS p=0.102 → exploratory（边界 case，Bonf×2 则 edge-confirmed）。

用户 #4：A 信号重定义为"月末+节假日放大"——月末 OR 长假节前（union），提升 power。
- 月末：每月最后 3 交易日（day>=28，window dressing 机构粉饰期）
- 节假日：长假节前（gap>=4）
- union：月末 OR 节假日（去重）

口径：buy day-2 open → sell day-1 close（2日 hold，close_ev，同 _holiday_capital_flow.py）
对比：原 A（节假日 only）/ 月末 only / union（月末+节假日）
gate: union p<0.05 + walk-forward OOS test p<0.05 → 放大提升 power → edge-confirmed
"""
import json
import statistics
from datetime import datetime
from pathlib import Path
from math import erf, sqrt

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
HOLIDAY_GAP = 4


def norm_sf_positive(t: float) -> float:
    return 0.5 * (1 - erf(t / sqrt(2))) if t > 0 else 1.0


def stats(rets: list) -> dict:
    n = len(rets)
    if n == 0:
        return {'n': 0, 'mean': 0.0, 't': 0.0, 'p': 1.0, 'wr': 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = norm_sf_positive(t)
    wr = sum(1 for x in rets if x > 0) / n
    return {'n': n, 'mean': mean, 't': t, 'p': p, 'wr': wr}


def audit() -> None:
    with open(f'{DATA}/index_ohlc_cache.json') as f:
        idx = json.load(f)
    bars = sorted(idx['sh.000001'], key=lambda b: b['date'])
    calendar = [b['date'] for b in bars]
    bar_map = {b['date']: b for b in bars}

    # 长假节前 picks（同 _holiday_capital_flow.py）
    holidays = []
    for i in range(1, len(calendar)):
        d0 = datetime.strptime(calendar[i - 1], '%Y-%m-%d')
        d1 = datetime.strptime(calendar[i], '%Y-%m-%d')
        gap = (d1 - d0).days
        if gap >= HOLIDAY_GAP:
            holidays.append({'last_before': calendar[i - 1], 'idx_last': i - 1})

    holiday_picks = []
    for h in holidays:
        i_last = h['idx_last']
        if i_last - 1 < 0:
            continue
        d_buy = calendar[i_last - 1]  # day-2
        d_sell = calendar[i_last]      # day-1
        b_buy = bar_map[d_buy]
        b_sell = bar_map[d_sell]
        o = b_buy.get('open')
        c = b_sell.get('close')
        if not (o and c and o > 0 and c > 0):
            continue
        ret = (c - o) / o * 100
        holiday_picks.append({'buy_date': d_buy, 'sell_date': d_sell, 'ret': ret, 'type': 'holiday'})

    # 月末 picks（每月最后 3 交易日 day>=28，window dressing 期）
    monthend_picks = []
    for i in range(1, len(calendar)):
        d = datetime.strptime(calendar[i], '%Y-%m-%d')
        if d.day >= 28:  # 最后 3 天
            if i - 1 < 0:
                continue
            d_buy = calendar[i - 1]
            d_sell = calendar[i]
            b_buy = bar_map[d_buy]
            b_sell = bar_map[d_sell]
            o = b_buy.get('open')
            c = b_sell.get('close')
            if not (o and c and o > 0 and c > 0):
                continue
            ret = (c - o) / o * 100
            monthend_picks.append({'buy_date': d_buy, 'sell_date': d_sell, 'ret': ret, 'type': 'monthend'})

    # union（月末 OR 节假日，去重）
    seen: set = set()
    union_picks: list = []
    for p in holiday_picks + monthend_picks:
        key = (p['buy_date'], p['sell_date'])
        if key in seen:
            continue
        seen.add(key)
        union_picks.append(p)

    print(f"=== A 信号重定义：月末+节假日放大（user #4）===")
    print(f"原 A（节假日 only）: {len(holiday_picks)} picks")
    print(f"月末 only: {len(monthend_picks)} picks")
    print(f"union（月末+节假日）: {len(union_picks)} picks\n")

    for label, picks in [("原A_节假日", holiday_picks), ("月末", monthend_picks), ("union_月末+节假日", union_picks)]:
        rets = [p['ret'] for p in picks]
        s = stats(rets)
        print(f"  {label}: n={s['n']} mean={s['mean']:.3f}% WR={s['wr']*100:.1f}% t={s['t']:.2f} p={s['p']:.4f}")

    # gate: union 提升 power？
    orig_s = stats([p['ret'] for p in holiday_picks])
    union_s = stats([p['ret'] for p in union_picks])
    print(f"\n  → union mean {'>' if union_s['mean'] > orig_s['mean'] else '<='} 原 A mean")
    print(f"  → union p={union_s['p']:.4f} {'<0.05 PASS' if union_s['p'] < 0.05 else '>=0.05 FAIL'}")
    if union_s['p'] < 0.05 and union_s['mean'] > 0:
        print(f"  → 放大提升 power：union edge-confirmed（原 A exploratory → union PASS）")
    else:
        print(f"  → 放大未提升 power：union 仍 exploratory/underpowered")

    # walk-forward OOS（union）
    sorted_union = sorted(union_picks, key=lambda p: p['buy_date'])
    n = len(sorted_union)
    mid = n // 2
    train = sorted_union[:mid]
    test = sorted_union[mid:]
    train_s = stats([p['ret'] for p in train])
    test_s = stats([p['ret'] for p in test])
    print(f"\n  walk-forward OOS (union):")
    print(f"    train: n={train_s['n']} mean={train_s['mean']:.3f}% p={train_s['p']:.4f}")
    print(f"    test:  n={test_s['n']} mean={test_s['mean']:.3f}% p={test_s['p']:.4f}")
    decay = (train_s['mean'] - test_s['mean']) / abs(train_s['mean']) * 100 if train_s['mean'] != 0 else 0
    print(f"    decay: {decay:.0f}%")
    if train_s['mean'] > 0 and test_s['mean'] > 0 and test_s['p'] < 0.05:
        print(f"    → union walk-forward OOS edge-confirmed")
    else:
        print(f"    → union walk-forward OOS NOT confirmed")

    # 月末 only walk-forward（对比）
    sorted_me = sorted(monthend_picks, key=lambda p: p['buy_date'])
    n_me = len(sorted_me)
    mid_me = n_me // 2
    me_train = sorted_me[:mid_me]
    me_test = sorted_me[mid_me:]
    me_train_s = stats([p['ret'] for p in me_train])
    me_test_s = stats([p['ret'] for p in me_test])
    print(f"\n  月末 only walk-forward（对比）:")
    print(f"    train: n={me_train_s['n']} mean={me_train_s['mean']:.3f}% p={me_train_s['p']:.4f}")
    print(f"    test:  n={me_test_s['n']} mean={me_test_s['mean']:.3f}% p={me_test_s['p']:.4f}")


if __name__ == "__main__":
    audit()
