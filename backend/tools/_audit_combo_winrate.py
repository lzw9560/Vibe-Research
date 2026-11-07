# -*- coding: utf-8 -*-
"""combo 历史胜率回溯（2026-10-29，用户"回溯历史计算胜率"）。

全历史 8 年（2018-2026，train+test）去涨停版（mode=filtered 真 edge），top-20 可交易，
算三种胜率口径：
  - per-pick WR：所有 picks 里 fwd5>0 的比例（买的票多少涨）
  - 日组合 WR：每日 top-20 中涨的比例（当日命中率）
  - 日胜率：每日组合 mean>0 的天数比例（多少天赚钱）
+ 各年分层 + gate 分层（breadth>40% AND 小盘5d>0）+ 含涨停对比。

复用 _audit_combo_deep.py 的 rank 逻辑，加：去涨停 + 全历史 + 三胜率 + gate。
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


DB = resolve_data_dir() / "baostock_kline_cache.db"
COST = 0.004  # 双边 0.4%
TOP_N = 20


def board_limit(code: str) -> float:
    """涨停板：创业科创20% / 北交30% / 主板10%。code 格式 sz.300xxx / sh.688xxx / bj.8xxxxx。"""
    c = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    if c.startswith("30") or c.startswith("68"):
        return 0.20
    if c.startswith("8") or c.startswith("4"):
        return 0.30
    return 0.10


def build_by_date() -> dict:
    """每日：每只票的 {gap, tr, amt, fwd5, up, past5, limit}。"""
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    by_date: dict = defaultdict(list)
    for code, bj in rows:
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        if len(bars) < 70:
            continue
        bl = board_limit(code)
        for i in range(60, len(bars) - 5):
            prev_c = float(bars[i - 1].get("close", 0) or 0)
            o = float(bars[i].get("open", 0) or 0)
            c = float(bars[i].get("close", 0) or 0)
            amt = float(bars[i].get("amount", 0) or 0)
            if not prev_c or not c or not o:
                continue
            ma60 = statistics.mean(float(bars[j].get("close", 0) or 0) for j in range(i - 60, i))
            if not ma60:
                continue
            today_ret = (c - prev_c) / prev_c
            gap = (o - prev_c) / prev_c
            # past 5d ret（小盘5d，gate 用）
            past5_c = float(bars[i - 5].get("close", 0) or 0) if i >= 5 else prev_c
            past_5d = (c - past5_c) / past5_c if past5_c else 0.0
            nc = float(bars[i + 5].get("close", 0) or 0)
            if not nc:
                continue
            fwd5 = (nc - c) / c
            by_date[bars[i].get("date", "")].append(
                {
                    "code": code,
                    "gap": gap,
                    "tr": today_ret,
                    "amt": amt,
                    "fwd5": fwd5,
                    "up": c > ma60,
                    "past5": past_5d,
                    "limit": today_ret >= bl * 0.98,  # 涨停（含接近涨停）
                }
            )
    return by_date


def rank_top(lst: list, n: int = TOP_N, exclude_limit: bool = True) -> list | None:
    """combo rank top-N（gap+tr-amt），可选去涨停。集中度要求 universe>=n*10。"""
    pool = [x for x in lst if not (exclude_limit and x["limit"])]
    if len(pool) < n * 10:
        return None
    nn = len(pool)
    sg = sorted(range(nn), key=lambda k: pool[k]["gap"])
    st = sorted(range(nn), key=lambda k: pool[k]["tr"])
    sa = sorted(range(nn), key=lambda k: pool[k]["amt"])
    rg = {o: r / nn for r, o in enumerate(sg)}
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}  # 小盘=高分
    score = lambda k: rg[k] + rt[k] + ra[k]
    top_idx = sorted(range(nn), key=score, reverse=True)[:n]
    return [pool[k] for k in top_idx]


def wr_stats(dates: list, by_date: dict, exclude_limit: bool = True) -> dict | None:
    """三种胜率 + mean/median/net/t（NW-t 简化为普通 t，胜率回溯够用）。"""
    daily_mean, daily_median, day_combo_wr = [], [], []
    all_picks = []
    for d in dates:
        lst = by_date[d]
        top = rank_top(lst, exclude_limit=exclude_limit)
        if not top:
            continue
        rets = [x["fwd5"] for x in top]
        daily_mean.append(statistics.mean(rets))
        daily_median.append(statistics.median(rets))
        day_combo_wr.append(sum(1 for x in rets if x > 0) / len(rets))
        all_picks.extend(rets)
    if not daily_mean:
        return None
    m = statistics.mean(daily_mean)
    med = statistics.mean(daily_median)
    per_pick_wr = sum(1 for x in all_picks if x > 0) / len(all_picks)  # per-pick
    combo_wr = statistics.mean(day_combo_wr)  # 日组合平均
    day_wr = sum(1 for x in daily_mean if x > 0) / len(daily_mean)  # 日胜率（赚钱天数）
    std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
    se = std / (len(daily_mean) ** 0.5) if daily_mean else 0
    t = m / se if se > 0 else 0
    return {
        "n_days": len(daily_mean),
        "n_picks": len(all_picks),
        "mean": m,
        "median": med,
        "net": m - COST,
        "t": t,
        "per_pick_wr": per_pick_wr,
        "combo_wr": combo_wr,
        "day_wr": day_wr,
    }


def gate_on(d: str, by_date: dict) -> bool:
    """gate: breadth>0.4 AND 小盘decile past5>0（FROZEN 阈值，amount 口径）。"""
    lst = by_date[d]
    if len(lst) < 20:
        return False
    breadth = sum(1 for x in lst if x["up"]) / len(lst)
    srt = sorted(lst, key=lambda x: x["amt"])
    dec = max(1, len(srt) // 10)
    small = srt[:dec]
    sm5 = statistics.mean(x["past5"] for x in small)
    return breadth > 0.4 and sm5 > 0


def main() -> None:
    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    print(f"\n=== combo 历史胜率回溯（全 {len(all_d)} 日 {all_d[0]}~{all_d[-1]}，去涨停 top-20 可交易版）===\n")

    # 全历史
    r = wr_stats(all_d, by_date)
    if r:
        print(f"【全历史】days={r['n_days']} picks={r['n_picks']}")
        print(
            f"  mean={r['mean'] * 100:+.3f}% median={r['median'] * 100:+.3f}% net={r['net'] * 100:+.3f}% t={r['t']:.2f}"
        )
        print(
            f"  胜率: per-pick={r['per_pick_wr'] * 100:.1f}% / 日组合={r['combo_wr'] * 100:.1f}% / 日胜率(赚钱天)={r['day_wr'] * 100:.1f}%\n"
        )

    # 各年分层
    print(
        f"{'年份':<8}{'mean':>10}{'median':>10}{'per-pick':>10}{'日组合':>10}{'日胜率':>10}{'net':>10}{'t':>7}{'days':>7}"
    )
    print("-" * 72)
    for yr in ["2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"]:
        ds = [d for d in all_d if d.startswith(yr)]
        if not ds:
            continue
        r = wr_stats(ds, by_date)
        if not r:
            continue
        print(
            f"{yr:<8}{r['mean'] * 100:>+9.3f}%{r['median'] * 100:>+9.3f}%{r['per_pick_wr'] * 100:>9.1f}%{r['combo_wr'] * 100:>9.1f}%{r['day_wr'] * 100:>9.1f}%{r['net'] * 100:>+9.3f}%{r['t']:>6.2f}{r['n_days']:>7}"
        )
    print()

    # gate 分层
    print("【gate 分层】（breadth>40% AND 小盘5d>0，FROZEN 阈值 amount 口径）")
    on_d = [d for d in all_d if gate_on(d, by_date)]
    off_d = [d for d in all_d if not gate_on(d, by_date)]
    for label, ds in [("gate=ON ", on_d), ("gate=OFF", off_d)]:
        if not ds:
            continue
        r = wr_stats(ds, by_date)
        if not r:
            continue
        print(
            f"  {label}: days={r['n_days']:>4} mean={r['mean'] * 100:+.3f}% per-pick={r['per_pick_wr'] * 100:.1f}% 日胜率={r['day_wr'] * 100:.1f}% net={r['net'] * 100:+.3f}% t={r['t']:.2f}"
        )
    print()

    # 含涨停 vs 去涨停对比（验证 R4：涨停贡献 40%）
    print("【含涨停 vs 去涨停】（全历史 top-20，验证涨停假 edge 占比）")
    r1 = wr_stats(all_d, by_date, exclude_limit=False)
    r2 = wr_stats(all_d, by_date, exclude_limit=True)
    if r1 and r2:
        print(
            f"  含涨停: mean={r1['mean'] * 100:+.3f}% per-pick={r1['per_pick_wr'] * 100:.1f}% 日胜率={r1['day_wr'] * 100:.1f}% t={r1['t']:.2f}"
        )
        print(
            f"  去涨停: mean={r2['mean'] * 100:+.3f}% per-pick={r2['per_pick_wr'] * 100:.1f}% 日胜率={r2['day_wr'] * 100:.1f}% t={r2['t']:.2f}"
        )
        ratio = r2["mean"] / r1["mean"] if r1["mean"] else 0
        print(f"  去涨停/含涨停={ratio * 100:.0f}% → 涨停贡献约 {(1 - ratio) * 100:.0f}%")
    print()

    # 持有期分布（去涨停全历史）
    r3 = wr_stats(all_d, by_date, exclude_limit=True)
    if r3:
        print("【持有 5 日收益分布】（去涨停全历史 top-20 picks）")
        # 重新收集 picks 算分布
        picks = []
        for d in all_d:
            top = rank_top(by_date[d], exclude_limit=True)
            if top:
                picks.extend(x["fwd5"] for x in top)
        if picks:
            n = len(picks)
            print(f"  n={n} mean={statistics.mean(picks) * 100:+.3f}% median={statistics.median(picks) * 100:+.3f}%")
            print(
                f"  >0(赚):{sum(1 for x in picks if x > 0) / n * 100:.1f}%  >+5%:{sum(1 for x in picks if x > 0.05) / n * 100:.1f}%  >+10%:{sum(1 for x in picks if x > 0.10) / n * 100:.1f}%"
            )
            print(
                f"  <0(亏):{sum(1 for x in picks if x < 0) / n * 100:.1f}%  <-5%:{sum(1 for x in picks if x < -0.05) / n * 100:.1f}%  <-10%:{sum(1 for x in picks if x < -0.10) / n * 100:.1f}%"
            )


if __name__ == "__main__":
    main()
