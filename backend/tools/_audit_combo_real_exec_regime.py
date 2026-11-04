# -*- coding: utf-8 -*-
"""combo real-exec regime 分层 + walk-forward + 60天滚动前向模拟（2026-11-04，用户"拉历史不等"）。

用 8 年历史 cache 模拟前向，不用等真实 60 天：
1. real-exec regime 分层（gate ON/OFF）——解释 live 10-26/10-27 负（OFF 日 real-exec 也负？）
2. real-exec walk-forward（train/test 滚动）
3. 60 天滚动前向模拟（每 60 天窗口 real-exec net 分布）+ 10 日 batch 连续负 streak（STOP 标准）
去 gap 版（rank 动量+小盘），mode=filtered 过滤。
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / ".vibe-research" / "baostock_kline_cache.db"
COST = 0.004
TOP_N = 20


def board_limit(code: str) -> float:
    c = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    if c.startswith("30") or c.startswith("68"):
        return 0.20
    if c.startswith("8") or c.startswith("4"):
        return 0.30
    return 0.10


def build_by_date() -> dict:
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
            isST = str(bars[i].get("isST", "0"))
            if not prev_c or not c or not o or not amt:
                continue
            ma60 = statistics.mean(float(bars[j].get("close", 0) or 0) for j in range(i - 60, i))
            if not ma60:
                continue
            today_ret = (c - prev_c) / prev_c
            gap = (o - prev_c) / prev_c
            if isST not in ("0", "", "0.0"):
                continue
            if code.startswith("920"):
                continue
            if today_ret >= bl:
                continue
            t1_open = float(bars[i + 1].get("open", 0) or 0)
            t5_close = float(bars[i + 5].get("close", 0) or 0)
            if not t1_open or not t5_close:
                continue
            real_exec = (t5_close - t1_open) / t1_open
            past5_c = float(bars[i - 5].get("close", 0) or 0) if i >= 5 else prev_c
            past5 = (c - past5_c) / past5_c if past5_c else 0.0
            by_date[bars[i].get("date", "")].append({
                "code": code, "gap": gap, "tr": today_ret, "amt": amt,
                "real_exec": real_exec, "up": c > ma60, "past5": past5,
            })
    return by_date


def rank_top_nogap(lst: list, n: int = TOP_N) -> list | None:
    if len(lst) < n * 10:
        return None
    nn = len(lst)
    st = sorted(range(nn), key=lambda k: lst[k]["tr"])
    sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    score = lambda k: rt[k] + ra[k]
    return [lst[k] for k in sorted(range(nn), key=score, reverse=True)[:n]]


def gate_on(lst: list) -> bool:
    if len(lst) < 20:
        return False
    breadth = sum(1 for x in lst if x["up"]) / len(lst)
    srt = sorted(lst, key=lambda x: x["amt"])
    dec = max(1, len(srt) // 10)
    sm5 = statistics.mean(x["past5"] for x in srt[:dec])
    return breadth > 0.4 and sm5 > 0


def stats(dates: list, by_date: dict) -> dict | None:
    daily_mean, daily_median, all_picks = [], [], []
    for d in dates:
        top = rank_top_nogap(by_date[d])
        if not top:
            continue
        rets = [x["real_exec"] for x in top]
        daily_mean.append(statistics.mean(rets))
        daily_median.append(statistics.median(rets))
        all_picks.extend(rets)
    if not daily_mean:
        return None
    m = statistics.mean(daily_mean)
    med = statistics.mean(daily_median)
    wr = sum(1 for x in all_picks if x > 0) / len(all_picks)
    std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
    se = std / (len(daily_mean) ** 0.5) if daily_mean else 0
    t = m / se if se > 0 else 0
    return {"n_days": len(daily_mean), "n_picks": len(all_picks),
            "mean": m, "median": med, "wr": wr, "net": m - COST, "t": t}


def main() -> None:
    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    print(f"\n=== combo real-exec regime 分层 + walk-forward + 60天滚动（去 gap mode=filtered，{len(all_d)} 日）===\n")

    # 1. regime 分层
    on_d = [d for d in all_d if gate_on(by_date[d])]
    off_d = [d for d in all_d if not gate_on(by_date[d])]
    print("【1】real-exec regime 分层（gate ON/OFF）——解释 live 10-26/10-27 负")
    for label, ds in [("gate=ON", on_d), ("gate=OFF", off_d), ("全", all_d)]:
        r = stats(ds, by_date)
        if r:
            print(f"  {label}: days={r['n_days']} mean={r['mean']*100:+.3f}% median={r['median']*100:+.3f}% WR={r['wr']*100:.1f}% net={r['net']*100:+.3f}% t={r['t']:.2f}")
    print()

    # 2. walk-forward（train 60% / test 40%）
    split = int(len(all_d) * 0.6)
    train, test = all_d[:split], all_d[split:]
    print(f"【2】real-exec walk-forward（train {len(train)} / test {len(test)}）")
    for label, ds in [("train", train), ("test", test)]:
        r = stats(ds, by_date)
        if r:
            print(f"  {label}: mean={r['mean']*100:+.3f}% net={r['net']*100:+.3f}% t={r['t']:.2f} WR={r['wr']*100:.1f}% median={r['median']*100:+.3f}%")
    print()

    # 3. 60 天滚动前向模拟
    windows = []
    for i in range(0, len(all_d) - 60, 60):
        r = stats(all_d[i:i + 60], by_date)
        if r:
            windows.append(r["net"])
    if windows:
        print(f"【3】60 天滚动前向模拟（{len(windows)} 个 60 天窗口）")
        print(f"  net 分布: mean={statistics.mean(windows)*100:+.3f}% median={statistics.median(windows)*100:+.3f}%")
        pos = sum(1 for w in windows if w > 0)
        print(f"  正窗口: {pos}/{len(windows)} ({pos/len(windows)*100:.1f}%)")
        print(f"  最差: {min(windows)*100:+.3f}% / 最好: {max(windows)*100:+.3f}%")
        # 10 日 batch 连续负 streak（STOP 标准）
        batches = []
        for i in range(0, len(all_d) - 10, 10):
            r = stats(all_d[i:i + 10], by_date)
            if r:
                batches.append(r["net"])
        if batches:
            neg_streak = max_consec_neg = 0
            for b in batches:
                if b < 0:
                    neg_streak += 1
                    max_consec_neg = max(max_consec_neg, neg_streak)
                else:
                    neg_streak = 0
            print(f"  10 日 batch 连续负 max streak: {max_consec_neg}（前 10 clean batch 都负=STOP 的历史最坏）")
            print(f"  10 日 batch 正占比: {sum(1 for b in batches if b>0)}/{len(batches)} ({sum(1 for b in batches if b>0)/len(batches)*100:.1f}%)")


if __name__ == "__main__":
    main()
