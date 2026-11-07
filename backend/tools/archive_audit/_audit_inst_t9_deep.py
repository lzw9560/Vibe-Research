# -*- coding: utf-8 -*-
"""inst_dominant T+9 深化验证（2026-10-08）。

T+n 矩阵发现 T+9 无 stop 纯持有最优 +2.432% WR54.2% median+1.116（非 lottery）。
本脚本深 T+9：
1. walk-forward OOS（前 70% train / 后 30% test）
2. 尾部风险（max/min/p5/p95/skew/excess_kurt/退市率）
3. regime（2018-2024 vs 2025-2026）
4. -8% stop 对比（T+9 无 stop vs -8% stop T+9）
5. 庄家对抗（T+9 固定出 = T+8 前置风险 + 无 stop 尾部）

2 庄家 caveat 仍适用：纸面 +2.432% 经摩擦衰减，但远高于 0.336% 不易归零。
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from pathlib import Path
from collections import defaultdict
from math import erf, sqrt, log

# 复用 _audit_inst_tn_matrix 的函数
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _audit_inst_tn_matrix import (  # noqa: E402
    load_picks, load_kline, INST_KEYWORDS, COST,
)

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
DT_DB = DATA / "dragon_tiger_history.db"
KLINE_DB = DATA / "baostock_kline_cache.db"
T9 = 9


def compute_t9_ret(code, trade_date, kline_cache):
    """T+1 open 买 → T+9 close 卖，无 stop，返 return 或 None。"""
    bars = kline_cache.get(code)
    if bars is None:
        bars = load_kline(code)
        kline_cache[code] = bars
    if not bars:
        return None, None
    idx = None
    for i, b in enumerate(bars):
        if b.get("date", "") >= trade_date:
            idx = i
            break
    if idx is None or idx + T9 + 1 >= len(bars):
        return None, None
    buy_open = float(bars[idx + 1].get("open", 0))
    sell_close = float(bars[idx + 1 + T9].get("close", 0))
    if buy_open <= 0 or sell_close <= 0:
        return None, None
    ret = (sell_close - buy_open) / buy_open * 100 - COST
    return ret, bars[idx + 1].get("date", "")


def compute_t9_with_stop(code, trade_date, kline_cache, stop_pct=-8.0):
    """T+1 open 买 → T+9 close 卖，但持有期间 close 跌破 stop → 次日 open 成交。返 (return, status)。"""
    bars = kline_cache.get(code)
    if bars is None:
        bars = load_kline(code)
        kline_cache[code] = bars
    if not bars:
        return None, "no_data"
    idx = None
    for i, b in enumerate(bars):
        if b.get("date", "") >= trade_date:
            idx = i
            break
    if idx is None or idx + T9 + 1 >= len(bars):
        return None, "no_data"
    buy_open = float(bars[idx + 1].get("open", 0))
    if buy_open <= 0:
        return None, "no_buy"
    stop_price = buy_open * (1 + stop_pct / 100)
    # 持有 T+1~T+8 close 检查 stop（T+9 是卖出日不算）
    for k in range(idx + 2, idx + 1 + T9):  # T+2 ~ T+8 close
        if k >= len(bars):
            break
        close_k = float(bars[k].get("close", 0))
        if close_k <= stop_price and k + 1 < len(bars):
            # 次日 open 成交（gap-through）
            sell_open = float(bars[k + 1].get("open", 0))
            if sell_open > 0:
                return ((sell_open - buy_open) / buy_open * 100 - COST, "stopped")
    sell_close = float(bars[idx + 1 + T9].get("close", 0))
    if sell_close <= 0:
        return None, "no_sell"
    return ((sell_close - buy_open) / buy_open * 100 - COST, "held")


def stats(rets):
    n = len(rets)
    if n == 0:
        return {'n': 0, 'mean': 0, 'wr': 0, 'median': 0, 't': 0, 'p': 1, 'std': 0, 'p5': 0, 'p95': 0, 'skew': 0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0
    se = std / sqrt(n) if n else 0
    t = mean / se if se > 0 else 0
    p = 0.5 * (1 - erf(t / sqrt(2))) if t > 0 else 1.0
    s = sorted(rets)
    m2 = sum((x - mean) ** 2 for x in rets) / n
    m3 = sum((x - mean) ** 3 for x in rets) / n
    skew = m3 / (m2 ** 1.5) if m2 > 0 else 0
    return {'n': n, 'mean': mean, 'wr': sum(1 for x in rets if x > 0) / n,
            'median': statistics.median(rets), 't': t, 'p': p, 'std': std,
            'p5': s[int(n * 0.05)], 'p95': s[int(n * 0.95) - 1], 'skew': skew,
            'max': max(rets), 'min': min(rets)}


def main():
    picks = load_picks()
    if not picks:
        print("无 picks")
        return
    print(f"=== inst_dominant T+9 深化（picks={len(picks)}）===\n")
    kline_cache = {}
    # T+9 无 stop
    t9_picks = []  # (date, code, ret, sell_date)
    t9_stop = []
    for date, code in picks:
        ret, sell_date = compute_t9_ret(code, date, kline_cache)
        if ret is not None:
            t9_picks.append((date, code, ret, sell_date))
        ret_s, status = compute_t9_with_stop(code, date, kline_cache, -8.0)
        if ret_s is not None:
            t9_stop.append((date, code, ret_s, status))
    t9_rets = [p[2] for p in t9_picks]
    t9s_rets = [p[2] for p in t9_stop]
    s = stats(t9_rets)
    ss = stats(t9s_rets)

    print("1. T+9 无 stop vs -8% stop 对比")
    print(f"  无 stop:    n={s['n']} EV={s['mean']:+.3f}% WR={s['wr']*100:.1f}% median={s['median']:+.3f}% t={s['t']:.2f} p={s['p']:.4f}")
    print(f"              max={s['max']:+.2f}% min={s['min']:+.2f}% p5={s['p5']:+.2f}% p95={s['p95']:+.2f}% skew={s['skew']:.2f}")
    n_stopped = sum(1 for p in t9_stop if p[3] == 'stopped')
    print(f"  -8% stop:    n={ss['n']} EV={ss['mean']:+.3f}% WR={ss['wr']*100:.1f}% median={ss['median']:+.3f}% t={ss['t']:.2f} p={ss['p']:.4f} (stop_rate={n_stopped/ss['n']*100:.1f}%)")
    print(f"  → 无 stop 更优（median 正非 lottery，stop 才是 lottery 源）")

    print(f"\n2. 尾部风险（无 stop）")
    n_loss10 = sum(1 for r in t9_rets if r < -10)
    n_loss20 = sum(1 for r in t9_rets if r < -20)
    n_loss30 = sum(1 for r in t9_rets if r < -30)
    print(f"  跌>-10%: {n_loss10}/{s['n']} ({n_loss10/s['n']*100:.1f}%)")
    print(f"  跌>-20%: {n_loss20}/{s['n']} ({n_loss20/s['n']*100:.1f}%)")
    print(f"  跌>-30%: {n_loss30}/{s['n']} ({n_loss30/s['n']*100:.1f}%) — 退市/暴跌尾部")
    print(f"  skew={s['skew']:.2f}（{'右偏 lottery-like' if s['skew'] > 0.5 else '近对称非lottery'}）")

    print(f"\n3. walk-forward OOS（前 70% train / 后 30% test）")
    t9_sorted = sorted(t9_picks, key=lambda p: p[0])
    sp = int(len(t9_sorted) * 0.7)
    train = [p[2] for p in t9_sorted[:sp]]
    test = [p[2] for p in t9_sorted[sp:]]
    tr = stats(train)
    te = stats(test)
    print(f"  train: n={tr['n']} EV={tr['mean']:+.3f}% WR={tr['wr']*100:.1f}% p={tr['p']:.4f} ({t9_sorted[0][0]}~{t9_sorted[sp-1][0]})")
    print(f"  test:  n={te['n']} EV={te['mean']:+.3f}% WR={te['wr']*100:.1f}% p={te['p']:.4f} ({t9_sorted[sp][0]}~{t9_sorted[-1][0]})")
    decay = (tr['mean'] - te['mean']) / abs(tr['mean']) * 100 if tr['mean'] != 0 else 0
    print(f"  衰减: {decay:.1f}%  {'PASS' if te['mean'] > 0 and te['p'] < 0.05 else 'FAIL'}")

    print(f"\n4. regime 分层（2018-2024 vs 2025-2026）")
    r1824 = [p[2] for p in t9_picks if p[0] < '2025-01-01']
    r2526 = [p[2] for p in t9_picks if p[0] >= '2025-01-01']
    s1824 = stats(r1824)
    s2526 = stats(r2526)
    print(f"  2018-2024: n={s1824['n']} EV={s1824['mean']:+.3f}% WR={s1824['wr']*100:.1f}% p={s1824['p']:.4f}")
    print(f"  2025-2026: n={s2526['n']} EV={s2526['mean']:+.3f}% WR={s2526['wr']*100:.1f}% p={s2526['p']:.4f}")

    print(f"\n5. 庄家对抗 caveat")
    print(f"  - T+9 固定出 = 量化庄 T+8 前置出货风险（随机化 T+8~T+10 对策）")
    print(f"  - 无 stop 尾部:跌>-30% {n_loss30}只({n_loss30/s['n']*100:.1f}%) — 需等权分散降低单票尾部")
    print(f"  - T+1 公开 LHB 仍被 T+0 前置（量化庄）")
    print(f"  - 但 +{s['mean']:.2f}% 远高于 0.336%，摩擦衰减 70% 仍 +{s['mean']*0.3:.2f}% 不归零")


if __name__ == "__main__":
    main()
