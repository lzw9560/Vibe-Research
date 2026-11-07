# -*- coding: utf-8 -*-
"""combo-5d cache 污染审计——判定存活是真 edge 还是幸存者偏差。

策略复盘发现：combo 用的 baostock_kline_cache.db 是 inst/A组被证伪的同一数据源。
A组实证 56% 残缺→53% picks 信号日不在 cache→correct-period 零 edge（LHB 信号日 vs
kline first_date 不匹配）。combo picks 来自 cache 本身（信号日=bar date），不存在
A组式"信号日不在 cache"，但有 universe 残缺风险（小盘股 backfill 不全→某些日某些
code 缺 bar→cross-sectional rank 偏差→top-20 不是真 top-20）+ fwd5 跳过偏差
（i+5 bar 缺→跳过，可能系统偏差）。

本脚本测：
1. combo 信号日 universe 覆盖率（有 bar 的 code 数 / 总 code 数）
2. correct-period（universe 完整）vs wrong-period（残缺）edge 对比
3. fwd5 跳过率（信号日 bar 有但 i+5 bar 缺）
4. 不同覆盖率阈值的 edge 趋势（看 edge 是否随 universe 完整度变化）
5. 判定 combo 存活是真 edge 还是幸存者偏差
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from math import erf, sqrt
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


DB = resolve_data_dir() / "baostock_kline_cache.db"
SPLIT = "2023-01-01"
COST = 0.004


def board_threshold(code: str) -> float:
    if code.startswith(("30", "68")):
        return 0.198
    if code.startswith(("8", "920", "9")):
        return 0.298
    return 0.098


def load_all() -> tuple:
    """返 (code->bars, date->set(codes) universe 覆盖图, total_codes)。"""
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    code_bars: dict = {}
    date_universe: dict = defaultdict(set)
    for code, bj in rows:
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        if not bars:
            continue
        code_bars[code] = bars
        for b in bars:
            d = b.get("date", "")
            if d:
                date_universe[d].add(code)
    return code_bars, date_universe, len(rows)


def build_by_date_with_skip(code_bars: dict) -> tuple:
    """combo by_date（去涨停口径）+ 统计 fwd5 跳过。

    返 (by_date, n_fwd5_skip, n_total_signals)。
    fwd5 跳过 = 信号日 bar 有但 i+5 bar 缺（nc=0 continue）。
    """
    by_date: dict = defaultdict(list)
    n_fwd5_skip = 0
    n_total_signals = 0
    for code, bars in code_bars.items():
        if len(bars) < 70:
            continue
        thr = board_threshold(code)
        for i in range(60, len(bars) - 5):
            prev_c = float(bars[i - 1].get("close", 0) or 0)
            o = float(bars[i].get("open", 0) or 0)
            c = float(bars[i].get("close", 0) or 0)
            amt = float(bars[i].get("amount", 0) or 0)
            if not prev_c or not c or not o or not amt:
                continue
            n_total_signals += 1
            nc = float(bars[i + 5].get("close", 0) or 0)
            if not nc:
                n_fwd5_skip += 1
                continue
            today_ret = (c - prev_c) / prev_c
            by_date[bars[i].get("date", "")].append({
                "code": code, "gap": (o - prev_c) / prev_c, "tr": today_ret,
                "amt": amt, "fwd5": (nc - c) / c, "is_zt": today_ret >= thr,
            })
    return by_date, n_fwd5_skip, n_total_signals


def combo_top_fwd(dates: list, by_date: dict, exclude_zt: bool = True) -> list:
    """combo top-20 去涨停 5日 daily_mean list（tradeable 版）。"""
    daily_means = []
    for d in dates:
        lst = by_date.get(d, [])
        if len(lst) < 200:
            continue
        n = len(lst)
        sg = sorted(range(n), key=lambda k: lst[k]["gap"])
        st = sorted(range(n), key=lambda k: lst[k]["tr"])
        sa = sorted(range(n), key=lambda k: lst[k]["amt"])
        rg = {o: r / n for r, o in enumerate(sg)}
        rt = {o: r / n for r, o in enumerate(st)}
        ra = {o: (1 - r / n) for r, o in enumerate(sa)}
        scored = sorted(range(n), key=lambda k: rg[k] + rt[k] + ra[k], reverse=True)
        picks = [lst[k] for k in scored[:20]]
        if exclude_zt:
            picks = [p for p in picks if not p["is_zt"]]
            if len(picks) < 10:
                continue
        fwds = [p["fwd5"] for p in picks]
        if not fwds:
            continue
        daily_means.append(statistics.mean(fwds))
    return daily_means


def stats(dm: list) -> dict | None:
    if not dm:
        return None
    n = len(dm)
    m = statistics.mean(dm)
    std = statistics.pstdev(dm) if n > 1 else 0
    se = std / sqrt(n) if n else 0
    t = m / se if se > 0 else 0
    p = 0.5 * (1 - erf(t / sqrt(2))) if t > 0 else 1.0
    return {"n": n, "mean": m, "net": m - COST, "t": t, "p": p}


def main() -> None:
    print("=== combo-5d cache 污染审计（判定存活是真 edge 还是幸存者偏差）===\n")
    code_bars, date_universe, total_codes = load_all()
    print(f"cache 总 code 数: {total_codes}")
    print(f"日期覆盖: {len(date_universe)} 日（{min(date_universe)} ~ {max(date_universe)}）")

    by_date, n_skip, n_total_sig = build_by_date_with_skip(code_bars)
    print(f"\ncombo 信号总数: {n_total_sig}（其中 fwd5 跳过 {n_skip} = {n_skip/n_total_sig*100:.1f}%）")
    print(f"combo test 信号日（>=2023-01-01）: {len([d for d in by_date if d >= SPLIT])} 日")

    test_dates = sorted(d for d in by_date if d >= SPLIT)

    # 1. 信号日 universe 覆盖率分布
    print("\n【1】信号日 universe 覆盖率（有 bar 的 code 数 / 总 code 数）")
    coverages = []
    for d in test_dates:
        cov = len(date_universe.get(d, set())) / total_codes
        coverages.append((d, cov))
    cov_vals = sorted(c for _, c in coverages)
    if cov_vals:
        print(f"  覆盖率: mean {statistics.mean(cov_vals)*100:.1f}% median {statistics.median(cov_vals)*100:.1f}%")
        print(f"  p10 {cov_vals[len(cov_vals)//10]*100:.1f}% p25 {cov_vals[len(cov_vals)//4]*100:.1f}% "
              f"p75 {cov_vals[3*len(cov_vals)//4]*100:.1f}% p90 {cov_vals[9*len(cov_vals)//10]*100:.1f}%")
        low_cov = sum(1 for c in cov_vals if c < 0.8)
        print(f"  覆盖率<80% 的日数: {low_cov} / {len(cov_vals)} ({low_cov/len(cov_vals)*100:.1f}%)")

    # 2. correct-period（universe>=80%）vs wrong-period（<80%）edge 对比
    print("\n【2】correct-period（universe>=80%）vs wrong-period（<80%）edge 对比")
    correct_dates = [d for d, c in coverages if c >= 0.8]
    wrong_dates = [d for d, c in coverages if c < 0.8]
    print(f"  correct（>=80%）: {len(correct_dates)} 日 ({len(correct_dates)/len(test_dates)*100:.1f}%)")
    print(f"  wrong（<80%）: {len(wrong_dates)} 日 ({len(wrong_dates)/len(test_dates)*100:.1f}%)")

    for label, dates in [("correct-period", correct_dates), ("wrong-period", wrong_dates), ("ALL", test_dates)]:
        dm = combo_top_fwd(dates, by_date, exclude_zt=True)
        s = stats(dm)
        if s:
            sig = "✅" if s["p"] < 0.05 else "❌"
            print(f"  {label}: n={s['n']} mean {s['mean']*100:+.4f}% net {s['net']*100:+.4f}% "
                  f"t={s['t']:.2f} p={s['p']:.4f} {sig}")
        else:
            print(f"  {label}: 无数据")

    # 3. 不同覆盖率阈值的 edge 趋势
    print("\n【3】不同覆盖率阈值的 combo edge 趋势（edge 是否随 universe 完整度变化）")
    for thr in [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]:
        dates = [d for d, c in coverages if c >= thr]
        dm = combo_top_fwd(dates, by_date, exclude_zt=True)
        s = stats(dm)
        if s:
            print(f"  覆盖率>={thr*100:.0f}%: n={s['n']} mean {s['mean']*100:+.4f}% t={s['t']:.2f} p={s['p']:.4f}")

    # 4. 判定
    print("\n【4】判定")
    correct_dm = combo_top_fwd(correct_dates, by_date, exclude_zt=True)
    correct_s = stats(correct_dm)
    wrong_dm = combo_top_fwd(wrong_dates, by_date, exclude_zt=True)
    wrong_s = stats(wrong_dm)
    all_dm = combo_top_fwd(test_dates, by_date, exclude_zt=True)
    all_s = stats(all_dm)

    print(f"  ALL test: n={all_s['n'] if all_s else 0} t={all_s['t']:.2f if all_s else 0}（vs memory 去涨停 net t10.29）")
    if correct_s:
        print(f"  correct-period（universe 完整）: t={correct_s['t']:.2f} p={correct_s['p']:.4f}")
    if wrong_s:
        print(f"  wrong-period（universe 残缺）: t={wrong_s['t']:.2f} p={wrong_s['p']:.4f}")

    print()
    if correct_s and correct_s["t"] > 2 and correct_s["p"] < 0.05:
        print("  → ✅ combo 存活是真 edge（universe 完整时 edge 仍显著，不是幸存者偏差）")
        print("    combo 的 edge 不是建在残缺 universe 上，cache 污染不适用 combo")
    elif correct_s and (correct_s["t"] <= 2 or correct_s["p"] >= 0.05):
        print("  → ❌ combo 存活是幸存者偏差（universe 完整时 edge 归零）")
        print("    combo 的 edge 来自残缺 universe 的 rank 偏差，和 inst/A组一样被 cache 污染证伪")
        print("    整个投研体系 = 0 个经审计 edge")
    elif not correct_dates:
        print("  → ⚠️ 全部信号日 universe 残缺（无 correct 组对比）—— combo 的 edge 全部来自残缺 universe")
        print("    combo 存活高度可疑，需 backfill 补全 universe 后重测")
    else:
        print("  → 不确定（需人工判读上方数字）")


if __name__ == "__main__":
    main()
