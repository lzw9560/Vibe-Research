# -*- coding: utf-8 -*-
"""窒息量低吸回测（STR 短期反转，Lehmann 1990，2026-10-08）。

用户建议"逆向低吸/均值回归"，但项目已证伪朴素均值回归（9/9 falsified）。
本脚本回测更窄子集：窒息量（量能衰竭）+ 连续大跌，验证是否有真 edge。

因子：
- 连续3日累计跌≥15%（恐慌割肉门槛）
- 当日 volume < 前5日均 volume × 30%（量能衰竭/窒息量，baostock turn=0 用 volume 代理）
- 排除 ST（isST=1）

真实口径（T+1）：
- T+0（窒息日）close 尾盘买（14:50-14:57 量能定型后）
- T+1 open 卖 / T+2 close / T+3 close（多窗口，STR 半衰期≤5日）

caveat：
- 无残差过滤（Da-Liu-Schaumburg），基本面跌幅未剔除（朴素版，预期 edge 弱）
- baostock stale（最新 9-23/9-30），2018-2023 历史够
- 量能衰竭用 volume（非换手率，baostock turn=0）
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from pathlib import Path
from collections import defaultdict
from math import erf, sqrt

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
COST = 0.3
DROP_THRESH = -15.0  # 连续3日累计跌≥15%
VOL_RATIO = 0.30     # 当日 volume < 前5日均 × 30%


def load_all_klines():
    conn = sqlite3.connect(str(KLINE_DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    for code, bj in rows:
        try:
            bars = json.loads(bj)
            bars = [b for b in bars if b.get("volume", 0) > 0 and b.get("close", 0) > 0]
            bars.sort(key=lambda b: b.get("date", ""))
            yield code, bars
        except Exception:
            continue


def find_suffocation_picks(code, bars):
    """找窒息点：连续3日累计跌≥15% + 当日 volume<前5日均30%。"""
    picks = []
    for i in range(5, len(bars) - 4):
        # 排除 ST
        if bars[i].get("isST", "0") in ("1", 1, True):
            continue
        # 连续3日（i-2, i-1, i）累计跌
        p3 = [bars[j].get("pctChg", 0) or 0 for j in range(i - 2, i + 1)]
        cum = ((1 + p3[0] / 100) * (1 + p3[1] / 100) * (1 + p3[2] / 100) - 1) * 100
        if cum > DROP_THRESH:  # 累计跌 < -15%（cum 是负值，> -15 = 不足）
            continue
        # 当日 volume < 前5日均 × 30%
        v_today = bars[i].get("volume", 0)
        v_ma5 = sum(bars[j].get("volume", 0) for j in range(i - 5, i)) / 5
        if v_ma5 <= 0 or v_today >= v_ma5 * VOL_RATIO:
            continue
        # 窒息点：i 日 close 买（尾盘）
        buy = bars[i].get("close", 0)
        if buy <= 0:
            continue
        date = bars[i].get("date", "")
        # 多窗口卖出
        rets = {}
        if i + 1 < len(bars):
            sell_t1_open = bars[i + 1].get("open", 0)
            if sell_t1_open > 0:
                rets["t1_open"] = (sell_t1_open - buy) / buy * 100 - COST
        for n in (2, 3, 5):
            if i + n < len(bars):
                sell = bars[i + n].get("close", 0)
                if sell > 0:
                    rets[f"t{n}_close"] = (sell - buy) / buy * 100 - COST
        if rets:
            picks.append((date, code, cum, v_today / v_ma5, rets))
    return picks


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


def main():
    print(f"=== 窒息量低吸回测（STR，连续3日跌≥{abs(DROP_THRESH)}% + volume<前5日均×{VOL_RATIO}）===\n")
    all_picks = []
    code_count = 0
    for code, bars in load_all_klines():
        code_count += 1
        picks = find_suffocation_picks(code, bars)
        for date, c, cum, vr, rets in picks:
            all_picks.append((date, c, cum, vr, rets))
    print(f"扫描 codes: {code_count}, 窒息 picks: {len(all_picks)}\n")
    if not all_picks:
        print("无窒息 picks（阈值过严或数据缺）")
        return
    # 多窗口统计
    windows = ["t1_open", "t2_close", "t3_close", "t5_close"]
    print(f"{'窗口':<12} {'net EV%':>9} {'WR%':>6} {'median':>8} {'t':>6} {'p':>9} {'n':>8}")
    print("-" * 55)
    for w in windows:
        rets = [p[4][w] for p in all_picks if w in p[4]]
        s = stats(rets)
        if s['n'] == 0:
            continue
        sig = '✅' if s['p'] < 0.05 else '❌'
        print(f"{w:<12} {s['mean']:>+8.3f} {s['wr']*100:>5.1f}% {s['median']:>+8.3f} {s['t']:>6.2f} {s['p']:>8.4f}{sig} {s['n']:>8}")
    # walk-forward（t1_open 主窗口）
    main_rets = [(p[0], p[4].get("t1_open")) for p in all_picks if "t1_open" in p[4]]
    main_rets = [(d, r) for d, r in main_rets if r is not None]
    main_rets.sort(key=lambda x: x[0])
    if main_rets:
        sp = int(len(main_rets) * 0.7)
        train = [r for _, r in main_rets[:sp]]
        test = [r for _, r in main_rets[sp:]]
        tr = stats(train); te = stats(test)
        print(f"\nwalk-forward (t1_open): train n={tr['n']} EV={tr['mean']:+.3f}% p={tr['p']:.4f} / test n={te['n']} EV={te['mean']:+.3f}% p={te['p']:.4f}")
    # 样本期分布
    dates = [p[0] for p in all_picks]
    if dates:
        print(f"\n样本期: {min(dates)} ~ {max(dates)}")
    print(f"\n⚠️ caveat:")
    print(f"  - 无残差过滤（Da-Liu-Schaumburg），基本面跌幅未剔除（朴素版，预期 edge 弱）")
    print(f"  - baostock turn=0，用 volume 代理换手（非严格换手率）")
    print(f"  - 若 edge 真→加残差过滤强化；若 falsify→朴素窒息量无 edge")


if __name__ == "__main__":
    main()
