# -*- coding: utf-8 -*-
"""inst_dominant T+1 溢价三口径（2026-10-08，用户"明明T+1是否有溢价"）。

T+1 溢价的 3 个口径（LHB 上榜日 T+0，次日 T+1）：
1. 隔夜 gap: T+0 close → T+1 open（LHB 当日收盘到次日开盘，是否高开=溢价）
2. 日内: T+1 open → T+1 close（买日当天日内收益，矩阵 T+1=-0.414%）
3. 总次日: T+0 close → T+1 close（LHB 当日收盘到次日收盘，总次日收益）

澄清 T+1 是否有溢价 + 哪个口径。
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from pathlib import Path
from collections import defaultdict
from math import erf, sqrt
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _audit_inst_tn_matrix import load_picks, load_kline, INST_KEYWORDS  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / ".vibe-research"
KLINE_DB = DATA / "baostock_kline_cache.db"
COST = 0.3


def stats(rets):
    n = len(rets)
    if n == 0:
        return {'n': 0, 'mean': 0, 'wr': 0, 'median': 0, 't': 0, 'p': 1}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0
    se = std / sqrt(n) if n else 0
    t = mean / se if se > 0 else 0
    p = 0.5 * (1 - erf(t / sqrt(2))) if t > 0 else 1.0
    return {'n': n, 'mean': mean, 'wr': sum(1 for x in rets if x > 0) / n,
            'median': statistics.median(rets), 't': t, 'p': p}


def compute_t1(code, trade_date, kline_cache):
    """返 (gap, intraday, total_next) 或 None。"""
    bars = kline_cache.get(code)
    if bars is None:
        bars = load_kline(code)
        kline_cache[code] = bars
    if not bars:
        return None
    idx = None
    for i, b in enumerate(bars):
        if b.get("date", "") >= trade_date:
            idx = i
            break
    if idx is None or idx + 1 >= len(bars):
        return None
    t0_close = float(bars[idx].get("close", 0))
    t1_open = float(bars[idx + 1].get("open", 0))
    t1_close = float(bars[idx + 1].get("close", 0))
    if t0_close <= 0 or t1_open <= 0 or t1_close <= 0:
        return None
    gap = (t1_open - t0_close) / t0_close * 100  # 隔夜 gap（无成本，仅观察溢价）
    intraday = (t1_close - t1_open) / t1_open * 100 - COST  # 日内（扣成本）
    total_next = (t1_close - t0_close) / t0_close * 100 - COST  # 总次日（扣成本）
    return (gap, intraday, total_next)


def main():
    picks = load_picks()
    if not picks:
        print("无 picks")
        return
    print(f"=== inst_dominant T+1 溢价三口径（picks={len(picks)}）===")
    print(f"LHB 上榜日 T+0，次日 T+1。买 T+1 open（A 股 T+1 制度，LHB T+0 收盘公开后次日买）\n")
    kline_cache = {}
    gaps, intradays, totals = [], [], []
    for date, code in picks:
        r = compute_t1(code, date, kline_cache)
        if r:
            g, i, t = r
            gaps.append(g)
            intradays.append(i)
            totals.append(t)
    sg = stats(gaps)
    si = stats(intradays)
    st = stats(totals)
    print(f"{'口径':<16} {'mean%':>8} {'WR%':>6} {'median':>8} {'t':>6} {'p':>9} {'n':>8}")
    print("-" * 60)
    print(f"{'1.隔夜gap(T0c→T1o)':<16} {sg['mean']:>+8.3f} {sg['wr']*100:>5.1f}% {sg['median']:>+8.3f} {sg['t']:>6.2f} {sg['p']:>8.4f}{'✅' if sg['p']<0.05 else '❌'} {sg['n']:>8}")
    print(f"{'2.日内(T1o→T1c)':<16} {si['mean']:>+8.3f} {si['wr']*100:>5.1f}% {si['median']:>+8.3f} {si['t']:>6.2f} {si['p']:>8.4f}{'✅' if si['p']<0.05 else '❌'} {si['n']:>8}")
    print(f"{'3.总次日(T0c→T1c)':<16} {st['mean']:>+8.3f} {st['wr']*100:>5.1f}% {st['median']:>+8.3f} {st['t']:>6.2f} {st['p']:>8.4f}{'✅' if st['p']<0.05 else '❌'} {st['n']:>8}")
    print(f"\n解读:")
    print(f"  隔夜 gap {'正=有溢价(高开)' if sg['mean']>0 else '负=无溢价(低开)'}: {sg['mean']:+.3f}% WR{sg['wr']*100:.1f}%")
    print(f"  日内 {'正=日内涨' if si['mean']>0 else '负=日内跌(高开低走割散户)'}: {si['mean']:+.3f}% WR{si['wr']*100:.1f}%")
    print(f"  总次日 {'正=次日总收益' if st['mean']>0 else '负=次日亏'}: {st['mean']:+.3f}% WR{st['wr']*100:.1f}%")
    print(f"\n⚠️ 庄家视角:")
    print(f"  若 gap 正 + 日内负 = 高开低走（量化庄 T+0 前置 + T+1 砸盘割散户）")
    print(f"  若 gap 正 + 日内正 = 真溢价（次日延续涨）")


if __name__ == "__main__":
    main()
