# -*- coding: utf-8 -*-
"""轮6 combo 深度验证（2026-10-20）。

combo 5日 edge 找到了(test t=5.65 net+0.405%)，但 3 个关键没测：
1. regime 分层 — inst/A组都死在 2025-2026，combo 呢？
2. 集中度 — top decile(~500只/日)不可交易，top 20/50 行不行？
3. 因子分解 — gap/动量/小盘 谁在扛？是不是就是小盘 beta 换皮？
4. 尾部分布 — mean+0.805% 是不是少数暴利票拉的？

全在 test 期(2023-2026)做，5日持有，复用 combo_hold 的 rank 逻辑。
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / ".vibe-research" / "baostock_kline_cache.db"
SPLIT = "2023-01-01"
COST = 0.004  # 双边 0.4%


def build_by_date() -> dict:
    """每日：每只票的 {gap, tr, amt, fwd5, up}。up=收盘>60日均线(uptrend regime)。"""
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
            nc = float(bars[i + 5].get("close", 0) or 0)
            if not nc:
                continue
            fwd5 = (nc - c) / c
            by_date[bars[i].get("date", "")].append({
                "gap": gap, "tr": today_ret, "amt": amt, "fwd5": fwd5,
                "up": c > ma60,
            })
    return by_date


def rank_scores(lst: list, use_gap: bool, use_tr: bool, use_amt: bool) -> list:
    """返回按组合 rank 降序的 top 索引。rank 归一 0-1。"""
    n = len(lst)
    sg = sorted(range(n), key=lambda k: lst[k]["gap"])
    st = sorted(range(n), key=lambda k: lst[k]["tr"])
    sa = sorted(range(n), key=lambda k: lst[k]["amt"])
    rg = {orig: r / n for r, orig in enumerate(sg)}
    rt = {orig: r / n for r, orig in enumerate(st)}
    ra = {orig: (1 - r / n) for r, orig in enumerate(sa)}  # 小盘=高分
    def score(k):
        s = 0.0
        if use_gap:
            s += rg[k]
        if use_tr:
            s += rt[k]
        if use_amt:
            s += ra[k]
        return s
    return sorted(range(n), key=score, reverse=True)


def stats_for(dates: list, by_date: dict, use_gap=True, use_tr=True, use_amt=True,
              top_n: int | None = None) -> dict | None:
    """对给定日期集，取 top（decile 或固定 N），算 5日 fwd 的日均值统计。"""
    daily_mean, daily_median, daily_wr, all_picks = [], [], [], []
    for d in dates:
        lst = by_date[d]
        if len(lst) < 20:
            continue
        scored = rank_scores(lst, use_gap, use_tr, use_amt)
        if top_n is None:
            dec = max(1, len(lst) // 10)
        else:
            if len(lst) < top_n * 10:  # 集中度要求
                continue
            dec = top_n
        top = [lst[k]["fwd5"] for k in scored[:dec]]
        if not top:
            continue
        daily_mean.append(statistics.mean(top))
        daily_median.append(statistics.median(top))
        daily_wr.append(sum(1 for x in top if x > 0) / len(top))
        all_picks.extend(top)
    if not daily_mean:
        return None
    m = statistics.mean(daily_mean)
    med = statistics.mean(daily_median)
    wr = statistics.mean(daily_wr)
    net = m - COST
    std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
    se = std / (len(daily_mean) ** 0.5) if len(daily_mean) else 0
    t = m / se if se > 0 else 0
    return {
        "n_days": len(daily_mean), "mean": m, "median": med, "wr": wr,
        "net": net, "t": t, "n_picks": len(all_picks), "picks": all_picks,
    }


def pct(vals: list, p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round(p / 100 * (len(s) - 1)))))
    return s[k]


def main() -> None:
    by_date = build_by_date()
    all_test = sorted(d for d in by_date if d >= SPLIT)
    h1 = sorted(d for d in all_test if d < "2025-01-01")       # 2023-2024
    h2 = sorted(d for d in all_test if d >= "2025-01-01")       # 2025-2026

    print(f"=== 轮6 combo 深度验证（test {len(all_test)} 日：2023-2024={len(h1)}日 / 2025-2026={len(h2)}日）===\n")

    # 1. regime 分层
    print("【1】regime 分层（combo top-decile 5日）")
    print(f"{'区间':<14}{'mean':>10}{'median':>10}{'WR':>8}{'net':>10}{'t':>7}{'n_days':>8}")
    print("-" * 60)
    for label, ds in [("全test", all_test), ("2023-2024", h1), ("2025-2026", h2)]:
        r = stats_for(ds, by_date)
        if not r:
            continue
        print(f"{label:<14}{r['mean']*100:>+9.4f}%{r['median']*100:>+9.4f}%{r['wr']*100:>6.1f}%{r['net']*100:>+9.4f}%{r['t']:>6.2f}{r['n_days']:>8}")
    # 2025-2026 by year
    for yr in ("2025", "2026"):
        ds = sorted(d for d in h2 if d.startswith(yr))
        r = stats_for(ds, by_date)
        if r:
            print(f"{yr:<14}{r['mean']*100:>+9.4f}%{r['median']*100:>+9.4f}%{r['wr']*100:>6.1f}%{r['net']*100:>+9.4f}%{r['t']:>6.2f}{r['n_days']:>8}")
    print()

    # 2. 集中度
    print("【2】集中度（全test，combo 5日）")
    print(f"{'选股':<14}{'mean':>10}{'median':>10}{'WR':>8}{'net':>10}{'t':>7}{'n_days':>8}")
    print("-" * 60)
    for label, tn in [("top decile", None), ("top 100", 100), ("top 50", 50), ("top 20", 20)]:
        r = stats_for(all_test, by_date, top_n=tn)
        if not r:
            print(f"{label:<14} (n不足跳过)")
            continue
        print(f"{label:<14}{r['mean']*100:>+9.4f}%{r['median']*100:>+9.4f}%{r['wr']*100:>6.1f}%{r['net']*100:>+9.4f}%{r['t']:>6.2f}{r['n_days']:>8}")
    print()

    # 3. 因子分解
    print("【3】因子分解（全test top-decile 5日）— 谁在扛？")
    print(f"{'组合':<22}{'mean':>10}{'median':>10}{'WR':>8}{'net':>10}{'t':>7}")
    print("-" * 66)
    for label, g, tr, a in [
        ("gap 单", True, False, False),
        ("动量 单", False, True, False),
        ("小盘 单", False, False, True),
        ("gap+动量", True, True, False),
        ("gap+小盘", True, False, True),
        ("动量+小盘", False, True, True),
        ("全 combo", True, True, True),
    ]:
        r = stats_for(all_test, by_date, use_gap=g, use_tr=tr, use_amt=a)
        if not r:
            continue
        print(f"{label:<22}{r['mean']*100:>+9.4f}%{r['median']*100:>+9.4f}%{r['wr']*100:>6.1f}%{r['net']*100:>+9.4f}%{r['t']:>6.2f}")
    print()

    # 4. 尾部分布（全 combo top-decile 全test）
    print("【4】尾部分布（全 combo top-decile 全test 5日）— mean 是不是尾部拉的？")
    r = stats_for(all_test, by_date)
    if r:
        pk = r["picks"]
        n = len(pk)
        print(f"  picks={n} mean={statistics.mean(pk)*100:+.3f}% median={statistics.median(pk)*100:+.3f}%")
        print(f"  p10={pct(pk,10)*100:+.3f}%  p25={pct(pk,25)*100:+.3f}%  p75={pct(pk,75)*100:+.3f}%  p90={pct(pk,90)*100:+.3f}%  p95={pct(pk,95)*100:+.3f}%")
        big_win = sum(1 for x in pk if x > 0.05) / n
        huge_win = sum(1 for x in pk if x > 0.10) / n
        big_loss = sum(1 for x in pk if x < -0.05) / n
        huge_loss = sum(1 for x in pk if x < -0.10) / n
        print(f"  >+5%:{big_win*100:.1f}%  >+10%:{huge_win*100:.1f}%  <-5%:{big_loss*100:.1f}%  <-10%:{huge_loss*100:.1f}%")
        # 去掉 top 5% 暴利票后 mean（看核心是否还正）
        cut = int(n * 0.05)
        trimmed = sorted(pk)[:-cut] if cut else pk
        if trimmed:
            print(f"  去 top5%暴利后 mean={statistics.mean(trimmed)*100:+.3f}% median={statistics.median(trimmed)*100:+.3f}%（核心是否还正）")


if __name__ == "__main__":
    main()
