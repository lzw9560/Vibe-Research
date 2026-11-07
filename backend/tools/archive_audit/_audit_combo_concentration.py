# -*- coding: utf-8 -*-
"""combo-5d 集中度收敛测试（2026-11-05，用户"策略还能收敛吗"）。

生产口径 = T+1 close 买点 + 去涨停去gap rank（动量+小盘）+ mode=filtered（剔920+涨停）。
当前 top-20 real-exec net +0.389%。测 top-3/5/7/10/15/20/30/50 集中度梯度：
  - edge 是否随集中单调升（memory 轮6：decile+0.40%→top50+1.12%→top20+2.06% close-to-close）
  - 容量是否随集中非线性降（top20 1%ADV总450万→top10~225万→top5~112万）
  - binding 约束 = 最不流动票 1%ADV（equal-weight 等权受 min 限制）

复用 _audit_combo_real_exec_entry_point.py 的 rank 逻辑（去gap 动量+小盘）+ T+1 close 买点。
优化 build（cumsum rolling MA60）复用 _audit_combo_risk_focused.py。
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / ".vibe-research" / "baostock_kline_cache.db"
COST = 0.004  # 双边 0.4%
TOP_NS = [3, 5, 7, 10, 15, 20, 30, 50]


def board_limit(code: str) -> float:
    c = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    if c.startswith("30") or c.startswith("68"):
        return 0.20
    if c.startswith("8") or c.startswith("4"):
        return 0.30
    return 0.10


def build_by_date() -> dict:
    """每日：每只票 {tr, amt, t1_close_ret, t1_open_ret}。mode=filtered 剔920+涨停。"""
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    by_date: dict = defaultdict(list)
    for code, bj in rows:
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        nb = len(bars)
        if nb < 70:
            continue
        c0 = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
        bl = 0.20 if (c0.startswith("30") or c0.startswith("68")) else (
            0.30 if (c0.startswith("8") or c0.startswith("4")) else 0.10)
        # pre-extract floats + cumsum for rolling MA60
        closes = [0.0] * nb
        opens = [0.0] * nb
        amts = [0.0] * nb
        dates_l = [""] * nb
        for j in range(nb):
            b = bars[j]
            dates_l[j] = b.get("date", "")
            closes[j] = float(b.get("close", 0) or 0)
            opens[j] = float(b.get("open", 0) or 0)
            amts[j] = float(b.get("amount", 0) or 0)
        cumsum = [0.0] * (nb + 1)
        for j in range(nb):
            cumsum[j + 1] = cumsum[j] + closes[j]
        for i in range(60, nb - 5):
            prev_c = closes[i - 1]
            o = opens[i]
            c = closes[i]
            amt = amts[i]
            if not prev_c or not c or not o or not amt:
                continue
            ma60 = (cumsum[i] - cumsum[i - 60]) / 60.0
            if not ma60:
                continue
            today_ret = (c - prev_c) / prev_c
            if code.startswith("920"):
                continue
            if today_ret >= bl:  # 剔涨停（mode=filtered）
                continue
            t1_open = opens[i + 1] if i + 1 < nb else 0.0
            t1_close = closes[i + 1] if i + 1 < nb else 0.0
            t5_close = closes[i + 5]
            if not t1_close or not t5_close:
                continue
            by_date[dates_l[i]].append({
                "code": code,
                "tr": today_ret,
                "amt": amt,
                "t1_close": (t5_close - t1_close) / t1_close,  # 生产口径买点
                "t1_open": (t5_close - t1_open) / t1_open if t1_open else None,
            })
    return by_date


def rank_top_nogap(lst: list, n: int) -> list | None:
    """rank 动量+小盘（不用 gap）top-N。与 entry_point 一致。"""
    if len(lst) < n * 10:
        return None
    nn = len(lst)
    st = sorted(range(nn), key=lambda k: lst[k]["tr"])
    sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    return [lst[k] for k in sorted(range(nn), key=lambda k: rt[k] + ra[k], reverse=True)[:n]]


def run_concentration(by_date: dict, n: int) -> dict:
    all_d = sorted(by_date.keys())
    daily_mean, daily_median, all_picks, all_amts = [], [], [], []
    for d in all_d:
        top = rank_top_nogap(by_date[d], n)
        if not top:
            continue
        rets = [x["t1_close"] for x in top]
        daily_mean.append(statistics.mean(rets))
        daily_median.append(statistics.median(rets))
        all_picks.extend(rets)
        all_amts.extend(x["amt"] for x in top)
    if not daily_mean:
        return {}
    m = statistics.mean(daily_mean)
    med = statistics.mean(daily_median)
    wr = sum(1 for x in all_picks if x > 0) / len(all_picks)
    std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
    se = std / (len(daily_mean) ** 0.5)
    t = m / se if se > 0 else 0
    # capacity: 1%ADV = amt * 0.01 (元). equal-weight binding = min(1%ADV)*n
    adv1pct = [a * 0.01 for a in all_amts]  # per-pick 1%ADV in 元
    med_adv = statistics.median(adv1pct)
    # binding: per-day min 1%ADV across basket, then median over days
    per_day_min = []
    for d in all_d:
        top = rank_top_nogap(by_date[d], n)
        if top:
            per_day_min.append(min(x["amt"] for x in top) * 0.01)
    med_binding = statistics.median(per_day_min) if per_day_min else 0
    return {
        "n": n, "n_days": len(daily_mean), "n_picks": len(all_picks),
        "mean": m, "median": med, "wr": wr, "net": m - COST, "t": t,
        "med_adv1pct_wan": med_adv / 1e4,  # 万元 per pick
        "sum_adv1pct_wan": med_adv * n / 1e4,  # 万元 total (median*pick)
        "binding_min_adv1pct_wan": med_binding / 1e4,  # 万元 binding per pick
        "binding_total_wan": med_binding * n / 1e4,  # 万元 equal-weight binding total
    }


def main() -> None:
    print("loading cache (5255 stocks x 8yr)...", flush=True)
    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    print(f"dates={len(all_d)} range={all_d[0]}~{all_d[-1]}\n", flush=True)

    print("=== combo 集中度收敛测试（T+1 close 去涨停去gap mode=filtered）===")
    print(f"{'topN':>5}{'days':>6}{'picks':>8}{'mean':>9}{'median':>9}{'WR':>7}{'net':>9}{'t':>7}"
          f"{'medADV1%':>10}{'sumADV1%':>10}{'bindMin':>9}{'bindTotal':>10}")
    print("-" * 100)
    results = []
    for n in TOP_NS:
        r = run_concentration(by_date, n)
        if r:
            results.append(r)
            print(f"{r['n']:>5}{r['n_days']:>6}{r['n_picks']:>8}"
                  f"{r['mean']*100:>+8.3f}%{r['median']*100:>+8.3f}%{r['wr']*100:>6.1f}%"
                  f"{r['net']*100:>+8.3f}%{r['t']:>6.2f}"
                  f"{r['med_adv1pct_wan']:>9.1f}万{r['sum_adv1pct_wan']:>9.1f}万"
                  f"{r['binding_min_adv1pct_wan']:>8.1f}万{r['binding_total_wan']:>9.1f}万")

    # edge per unit capacity (efficiency)
    print("\n=== edge/容量 效率（net% ÷ binding容量万元 → 每万元 edge）===")
    print(f"{'topN':>5}{'net%':>9}{'bindTotal万':>12}{'edge/万':>12}{'门槛+0.3%':>10}")
    for r in results:
        eff = r["net"] * 100 / r["binding_total_wan"] if r["binding_total_wan"] else 0
        ok = "✅过" if r["net"] > 0.003 else ("🟡灰" if r["net"] > 0.0015 else "❌不过")
        print(f"{r['n']:>5}{r['net']*100:>+8.3f}%{r['binding_total_wan']:>11.1f}万{eff:>11.6f}{ok:>10}")


if __name__ == "__main__":
    main()
