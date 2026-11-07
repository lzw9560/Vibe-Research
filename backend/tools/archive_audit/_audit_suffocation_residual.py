# -*- coding: utf-8 -*-
"""残差过滤窒息量回测（Da-Liu-Schaumburg 简化版，2026-10-08）。

_suffocation_reversal.py 证否朴素窒息量（t1_open -8.188% WR1.9%）。
专家1说：需残差过滤（残差=原始收益−现金流消息，纯情绪跌幅非基本面）才可能 edge。

本脚本用大盘 beta 残差简化（个股3日累计收益 − 大盘3日累计收益）：
- 残差 ≤ -10% = 个股特有跌幅（非市场系统性跌幅），可能是情绪过度反应
- 对比：全窒息 picks vs 残差过滤后 picks 的收益

caveat：
- 大盘 beta 残差是简化（非 Da-Liu-Schaumburg 现金流消息残差，但近似剥离市场）
- 若残差过滤后 edge 改善 → 情绪跌幅有 edge，加现金流残差强化
- 若仍 falsified → 朴素+市场残差窒息量都死，低吸方向彻底 falsify
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
from _audit_suffocation_reversal import (  # noqa: E402
    load_all_klines, find_suffocation_picks, stats, DROP_THRESH, VOL_RATIO,
)

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
INDEX_OHLC = DATA / "index_ohlc_cache.json"
RESIDUAL_THRESH = -10.0  # 残差 ≤ -10% = 个股特有跌幅


def load_index():
    """加载上证综指 date→close。"""
    with open(INDEX_OHLC) as f:
        d = json.load(f)
    bars = sorted(d.get("sh.000001", []), key=lambda b: b.get("date", ""))
    return {b.get("date"): b.get("close", 0) for b in bars if b.get("close", 0) > 0}


def index_3d_return(idx_map, date_list):
    """大盘同期3日累计收益（date_list 是3个交易日 [d-2,d-1,d]）。"""
    if len(date_list) < 3:
        return None
    c_start = idx_map.get(date_list[0])  # 3日前 close
    c_end = idx_map.get(date_list[-1])   # 今日 close
    if not c_start or not c_end or c_start <= 0:
        return None
    return (c_end / c_start - 1) * 100


def main():
    print(f"=== 残差过滤窒息量回测（大盘 beta 残差 ≤ {RESIDUAL_THRESH}%）===\n")
    idx_map = load_index()
    print(f"上证综指交易日: {len(idx_map)}\n")
    all_picks = []
    residual_picks = []
    for code, bars in load_all_klines():
        picks = find_suffocation_picks(code, bars)
        for date, c, cum, vr, rets in picks:
            # 个股3日累计收益（cum 已是3日累计%）
            stock_3d = cum
            # 大盘同期3日累计
            # 找窒息日 i 在 bars 的 index，取前3日 date
            i = next((k for k, b in enumerate(bars) if b.get("date") == date), None)
            if i is None or i < 2:
                continue
            d3 = [bars[j].get("date") for j in range(i - 2, i + 1)]
            idx_3d = index_3d_return(idx_map, d3)
            if idx_3d is None:
                continue
            residual = stock_3d - idx_3d  # 残差 = 个股 - 大盘
            all_picks.append((date, code, cum, vr, rets, residual))
            if residual <= RESIDUAL_THRESH:
                residual_picks.append((date, code, cum, vr, rets, residual))
    print(f"全窒息 picks: {len(all_picks)}, 残差过滤后: {len(residual_picks)}\n")
    # 对比
    for label, picks in [("全窒息(无残差过滤)", all_picks), ("残差过滤(≤-10%个股特有跌幅)", residual_picks)]:
        print(f"--- {label} (n={len(picks)}) ---")
        print(f"{'窗口':<12} {'net EV%':>9} {'WR%':>6} {'median':>8} {'t':>6} {'p':>9}")
        for w in ["t1_open", "t2_close", "t3_close", "t5_close"]:
            rets = [p[4][w] for p in picks if w in p[4]]
            s = stats(rets)
            if s['n'] == 0:
                continue
            sig = '✅' if s['p'] < 0.05 else '❌'
            print(f"{w:<12} {s['mean']:>+8.3f} {s['wr']*100:>5.1f}% {s['median']:>+8.3f} {s['t']:>6.2f} {s['p']:>8.4f}{sig}")
        print()
    # walk-forward 残差过滤
    if residual_picks:
        main_rets = [(p[0], p[4].get("t1_open")) for p in residual_picks if "t1_open" in p[4]]
        main_rets = [(d, r) for d, r in main_rets if r is not None]
        main_rets.sort(key=lambda x: x[0])
        sp = int(len(main_rets) * 0.7)
        tr = stats([r for _, r in main_rets[:sp]])
        te = stats([r for _, r in main_rets[sp:]])
        print(f"残差过滤 walk-forward (t1_open): train n={tr['n']} EV={tr['mean']:+.3f}% p={tr['p']:.4f} / test n={te['n']} EV={te['mean']:+.3f}% p={te['p']:.4f}")
    print(f"\n⚠️ caveat: 大盘 beta 残差是简化（非 Da-Liu-Schaumburg 现金流消息残差）")
    print(f"若残差过滤后 edge 改善→情绪跌幅有 edge，加现金流残差强化")
    print(f"若仍 falsified→朴素+市场残差窒息量都死，低吸方向彻底 falsify")


if __name__ == "__main__":
    main()
