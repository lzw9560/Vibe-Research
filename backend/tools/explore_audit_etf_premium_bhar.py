# -*- coding: utf-8 -*-
"""ETF 折溢价 BHAR 公式诚实性验证——用户质疑"不可能 edge 方法肯定有问题"。

数学推导（见对话）：
  r = entry/nav_signal (入场折价比, 如 0.95)
  s = exit_close/nav_exit (出场折价比)
  m = nav_exit/nav_signal (NAV 收益 = 市场 beta)
  散户收益 = (s/r)·m - 1
  BHAR = (s-1) - (r-1) = s - r (折价变化)

Case A (NAV平, price涨收敛): 散户 ≥ BHAR (散户捕获收敛)
Case B (NAV跌收敛, price平): 散户 = 0%, BHAR = +5% (BHAR 虚增!)

本脚本实测：
  1. 每 pick 分解: 散户收益 / BHAR / NAV收益 / 收敛分量 / beta分量
  2. Case A vs Case B 占比 (Case B = 散户收益 < BHAR 的子集)
  3. 散户收益 = 收敛alpha + beta 分量 (验证分解恒等式)
  4. 危机 vs 非危机 BHAR (用户疑点2)
  5. T+1 open 折价 vs T close 折价 (用户疑点3——隔夜收敛)
"""

from __future__ import annotations
import json
import statistics
from collections import defaultdict
from pathlib import Path
from math import sqrt

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
ETF_CACHE = DATA / "etf_premium_cache.json"
INDEX_CACHE = DATA / "index_ohlc_cache.json"

CRISIS_WINDOWS = [
    ("2008-GFC", "2008-01-01", "2009-03-31"),
    ("2015-崩盘", "2015-06-01", "2016-02-29"),
    ("2018-贸易战", "2018-03-01", "2019-01-31"),
    ("2020-COVID", "2020-02-01", "2020-04-30"),
    ("2024-1月崩盘", "2024-01-01", "2024-03-31"),
]


def load_etf():
    with open(ETF_CACHE) as f:
        return json.load(f)


def load_index():
    with open(INDEX_CACHE) as f:
        raw = json.load(f)
    bars = raw.get("sh.000001", [])
    return {b["date"]: b for b in bars if "date" in b}


def is_crisis(date: str) -> bool:
    for _, lo, hi in CRISIS_WINDOWS:
        if lo <= date <= hi:
            return True
    return False


def build_picks(etf_data, threshold=-0.3, hold_days=1):
    """disc < threshold, entry=T+1 open, exit=T+(1+hold) close."""
    all_dates = set()
    for days in etf_data.values():
        all_dates.update(days.keys())
    calendar = sorted(all_dates)
    date_idx = {d: i for i, d in enumerate(calendar)}
    exit_offset = 1 + hold_days
    picks = []
    for code, days in etf_data.items():
        for d, b in days.items():
            nav_sig = b.get("nav")
            close_sig = b.get("close")
            if nav_sig is None or close_sig is None or nav_sig <= 0 or close_sig <= 0:
                continue
            disc_t = (close_sig - nav_sig) / nav_sig * 100  # T 收盘折价
            if disc_t >= threshold:
                continue
            di = date_idx.get(d)
            if di is None or di + exit_offset >= len(calendar):
                continue
            t1_date = calendar[di + 1]
            exit_date = calendar[di + exit_offset]
            t1 = days.get(t1_date)
            ex = days.get(exit_date)
            if t1 is None or ex is None:
                continue
            entry = t1.get("open")
            exit_close = ex.get("close")
            nav_t1 = t1.get("nav")
            nav_exit = ex.get("nav")
            t1_close = t1.get("close")
            if None in (entry, exit_close, nav_t1, nav_exit) or entry <= 0 or exit_close <= 0:
                continue
            # T+1 一字涨停代理跳过
            if close_sig > 0 and entry / close_sig >= 1.099:
                continue
            picks.append(
                {
                    "code": code,
                    "signal_date": d,
                    "t1_date": t1_date,
                    "exit_date": exit_date,
                    "disc_t_close": disc_t,  # T 收盘折价（信号时）
                    "entry": entry,
                    "exit_close": exit_close,
                    "nav_signal": nav_sig,
                    "nav_t1": nav_t1,
                    "nav_exit": nav_exit,
                    "t1_close": t1_close,  # T+1 收盘价（测隔夜收敛用）
                    "is_crisis": is_crisis(d),
                }
            )
    return picks


def decompose(p):
    """分解散户收益 = 收敛alpha + beta分量。验证 BHAR 诚实性。"""
    r = p["entry"] / p["nav_signal"]  # 入场折价比
    s = p["exit_close"] / p["nav_exit"]  # 出场折价比
    m = p["nav_exit"] / p["nav_signal"]  # NAV 收益比 (市场 beta)
    retail_ret = (s / r) * m - 1  # 散户收益 (数学恒等)
    bhar = s - r  # BHAR = 折价变化
    nav_ret = m - 1  # NAV 收益 (市场 beta)
    # 收敛分量 = 散户收益 - beta 分量 (散户超出市场部分)
    conv_component = retail_ret - nav_ret
    return {
        "retail_ret_pct": retail_ret * 100,
        "bhar_pct": bhar * 100,
        "nav_ret_pct": nav_ret * 100,
        "conv_component_pct": conv_component * 100,  # 散户捕获的收敛 alpha
        "r": r,
        "s": s,
        "m": m,
    }


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def main():
    etf_data = load_etf()
    index_map = load_index()
    picks = build_picks(etf_data, threshold=-0.3, hold_days=1)
    print(f"picks: {len(picks)} (disc<-0.3%, hold 1d)")

    # 分解每个 pick
    decs = [decompose(p) for p in picks]

    # 聚合
    retail_mean = mean([d["retail_ret_pct"] for d in decs])
    bhar_mean = mean([d["bhar_pct"] for d in decs])
    nav_mean = mean([d["nav_ret_pct"] for d in decs])
    conv_mean = mean([d["conv_component_pct"] for d in decs])

    print("\n" + "=" * 70)
    print("【验证1】BHAR 诚实性——散户收益 vs BHAR 分解")
    print("=" * 70)
    print(f"  散户收益(raw EV)   = {retail_mean:+.4f}%")
    print(f"  BHAR(折价变化)     = {bhar_mean:+.4f}%")
    print(f"  NAV收益(市场beta)  = {nav_mean:+.4f}%")
    print(f"  收敛分量(散户-beta)= {conv_mean:+.4f}%")
    print(f"  分解恒等式: 散户 = 收敛 + beta = {conv_mean + nav_mean:+.4f}% (应={retail_mean:+.4f}%)")
    print()
    print(f"  关键对比:")
    print(f"    BHAR = {bhar_mean:+.4f}%  vs  散户收敛分量 = {conv_mean:+.4f}%")
    if abs(bhar_mean - conv_mean) < 0.05:
        print(f"    → BHAR ≈ 散户收敛分量 (差 {bhar_mean - conv_mean:+.4f}%) → BHAR 诚实，散户捕获收敛 alpha")
    elif bhar_mean > conv_mean:
        print(f"    → BHAR > 散户收敛分量 (BHAR 虚增 {bhar_mean - conv_mean:+.4f}%) → Case B 主导，BHAR 高估")
    else:
        print(f"    → BHAR < 散户收敛分量 (BHAR 保守 {bhar_mean - conv_mean:+.4f}%)")

    # Case A vs Case B
    print("\n" + "=" * 70)
    print("【验证2】Case A vs Case B 占比（用户核心质疑）")
    print("=" * 70)
    case_a = [d for d in decs if d["retail_ret_pct"] >= d["bhar_pct"]]  # 散户 ≥ BHAR (price涨收敛)
    case_b = [d for d in decs if d["retail_ret_pct"] < d["bhar_pct"]]  # 散户 < BHAR (NAV跌收敛)
    print(f"  Case A (散户≥BHAR, price涨收敛): {len(case_a)} ({len(case_a) / len(decs) * 100:.1f}%)")
    print(f"  Case B (散户<BHAR, NAV跌收敛):  {len(case_b)} ({len(case_b) / len(decs) * 100:.1f}%)")
    if case_b:
        b_retail = mean([d["retail_ret_pct"] for d in case_b])
        b_bhar = mean([d["bhar_pct"] for d in case_b])
        print(f"  Case B 内: 散户={b_retail:+.4f}% vs BHAR={b_bhar:+.4f}% (BHAR 虚增 {b_bhar - b_retail:+.4f}%)")
    if case_a:
        a_retail = mean([d["retail_ret_pct"] for d in case_a])
        a_bhar = mean([d["bhar_pct"] for d in case_a])
        print(f"  Case A 内: 散户={a_retail:+.4f}% vs BHAR={a_bhar:+.4f}%")

    # Case B 进一步: 散户收益 < 0 (真亏) 占比
    case_b_loss = [d for d in case_b if d["retail_ret_pct"] < 0]
    print(f"  Case B 中散户真亏 (retail<0): {len(case_b_loss)} ({len(case_b_loss) / max(len(case_b), 1) * 100:.1f}% of Case B)")

    # 危机 vs 非危机
    print("\n" + "=" * 70)
    print("【验证3】危机集中（用户疑点2）——去掉危机 edge 还在？")
    print("=" * 70)
    crisis_decs = [d for d, p in zip(decs, picks) if p["is_crisis"]]
    noncrisis_decs = [d for d, p in zip(decs, picks) if not p["is_crisis"]]
    print(f"  危机 picks: {len(crisis_decs)} ({len(crisis_decs) / len(decs) * 100:.1f}%)")
    print(f"  非危机 picks: {len(noncrisis_decs)} ({len(noncrisis_decs) / len(decs) * 100:.1f}%)")
    if crisis_decs:
        c_retail = mean([d["retail_ret_pct"] for d in crisis_decs])
        c_bhar = mean([d["bhar_pct"] for d in crisis_decs])
        print(f"  危机: 散户={c_retail:+.4f}% BHAR={c_bhar:+.4f}%")
    if noncrisis_decs:
        n_retail = mean([d["retail_ret_pct"] for d in noncrisis_decs])
        n_bhar = mean([d["bhar_pct"] for d in noncrisis_decs])
        print(f"  非危机: 散户={n_retail:+.4f}% BHAR={n_bhar:+.4f}%")
        # 非危机 day-paired t
        by_date_nc = defaultdict(list)
        for d, p in zip(noncrisis_decs, picks):
            if not p["is_crisis"]:
                by_date_nc[p["signal_date"]].append(d["retail_ret_pct"])
        day_means = [sum(vs) / len(vs) for vs in by_date_nc.values() if vs]
        n_days = len(day_means)
        m = sum(day_means) / n_days if n_days else 0
        sd = statistics.pstdev(day_means) if n_days > 1 else 0
        se = sd / sqrt(n_days) if n_days else 0
        t = m / se if se > 0 else 0
        print(f"  非危机 day-paired: n_days={n_days} mean={m:+.4f}% t={t:.2f}")

    # T+1 open 折价 vs T close 折价（隔夜收敛）
    print("\n" + "=" * 70)
    print("【验证4】T+1 open 隔夜收敛（用户疑点3）——散户买在收敛后？")
    print("=" * 70)
    # T 收盘折价 vs T+1 open 折价（用 nav_signal 作 NAV 基准，T+1 open 是 entry）
    disc_t = [p["disc_t_close"] for p in picks]  # T 收盘折价
    disc_t1_open = [(p["entry"] - p["nav_signal"]) / p["nav_signal"] * 100 for p in picks]  # T+1 open 折价
    narrowing = [disc_t[i] - disc_t1_open[i] for i in range(len(picks))]  # 隔夜收敛（正=折价缩小）
    print(f"  T 收盘折价均值: {mean(disc_t):+.4f}%")
    print(f"  T+1 open 折价均值: {mean(disc_t1_open):+.4f}%")
    print(f"  隔夜收敛: {mean(narrowing):+.4f}% (正=折价隔夜缩小, 散户买在更小折价)")
    # T+1 open 折价还 < -0.3% 的占比
    still_discounted = [d for d in disc_t1_open if d < -0.3]
    print(f"  T+1 open 折价仍 <-0.3%: {len(still_discounted)}/{len(picks)} ({len(still_discounted) / len(picks) * 100:.1f}%)")
    # 隔夜收敛 > 0 的占比（散户买前已收敛）
    narrowed_overnight = [n for n in narrowing if n > 0]
    print(f"  隔夜已收敛的: {len(narrowed_overnight)}/{len(picks)} ({len(narrowed_overnight) / len(picks) * 100:.1f}%)")

    # 综合判定
    print("\n" + "=" * 70)
    print("【综合】用户质疑'不可能 edge 方法肯定有问题' 是否成立")
    print("=" * 70)
    print(f"  BHAR 诚实性: BHAR={bhar_mean:+.4f}% vs 散户收敛分量={conv_mean:+.4f}% (差 {bhar_mean - conv_mean:+.4f}%)")
    print(f"  Case B 占比: {len(case_b) / len(decs) * 100:.1f}% (BHAR 虚增风险)")
    print(f"  散户总收益: {retail_mean:+.4f}% ({'正=散户盈利' if retail_mean > 0 else '负=散户亏损'})")
    print(f"  非危机 edge: 散户={mean([d['retail_ret_pct'] for d in noncrisis_decs]) if noncrisis_decs else 0:+.4f}%")
    print(f"  隔夜收敛: {mean(narrowing):+.4f}% ({'散户买前已部分收敛' if mean(narrowing) > 0.01 else '隔夜未收敛'})")


if __name__ == "__main__":
    main()
