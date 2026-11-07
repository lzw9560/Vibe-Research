# -*- coding: utf-8 -*-
"""3 候选因子 walk-forward OOS 复验（轮 2，2026-10-20）。

轮1 找到 3 候选（top-decile 次日 mean 显著正）：gap(高开) t=3.2、today_ret(动量) t=2.5、
amount(小盘) t=2.7。本脚本拆 train(2018-2022)/test(2023-2026)，看正显著性是否出样本 hold。
Bonferroni ×3（3 候选）。通过 = §44-survivor（找到停）；不过 = 候选假阳，下一族。
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / ".vibe-research" / "baostock_kline_cache.db"
SPLIT = "2023-01-01"  # train < / test >=


def main() -> None:
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    by_date: dict = defaultdict(list)
    for code, bj in rows:
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        if len(bars) < 26:
            continue
        vols = [float(b.get("volume", 0) or 0) for b in bars]
        for i in range(5, len(bars) - 1):
            prev_c = float(bars[i-1].get("close", 0) or 0)
            o = float(bars[i].get("open", 0) or 0)
            c = float(bars[i].get("close", 0) or 0)
            amt = float(bars[i].get("amount", 0) or 0)
            if not prev_c or not c or not o:
                continue
            today_ret = (c - prev_c) / prev_c
            gap = (o - prev_c) / prev_c
            nxt_c = float(bars[i+1].get("close", 0) or 0)
            if not nxt_c:
                continue
            nxt_ret = (nxt_c - c) / c
            d = bars[i].get("date", "")
            by_date[d].append({"gap": gap, "today_ret": today_ret, "amount": amt, "nxt_ret": nxt_ret})

    train_dates = sorted(d for d in by_date if d < SPLIT)
    test_dates = sorted(d for d in by_date if d >= SPLIT)
    print(f"=== 3 候选 walk-forward OOS（train {len(train_dates)} 日 / test {len(test_dates)} 日）===")
    print(f"split = {SPLIT}\n")

    def period_stats(dates, key, top=True, label=""):
        # top=True: gap/today_ret 取 top decile；amount 取 bottom decile（小盘=top decile of -amount）
        daily_means = []
        for d in dates:
            lst = by_date[d]
            if len(lst) < 20:
                continue
            s = sorted(lst, key=lambda x: x[key], reverse=top)
            dec = max(1, len(s) // 10)
            daily_means.append(statistics.mean(x["nxt_ret"] for x in s[:dec]))
        if not daily_means:
            return None
        m = statistics.mean(daily_means)
        std = statistics.pstdev(daily_means) if len(daily_means) > 1 else 0
        se = std / (len(daily_means) ** 0.5) if len(daily_means) else 0
        # base for the period (all-stock daily mean)
        base_daily = [statistics.mean(x["nxt_ret"] for x in by_date[d] if len(by_date[d])>=20) for d in dates if len(by_date[d])>=20]
        base_m = statistics.mean(base_daily) if base_daily else 0
        diff = m - base_m
        t = diff / se if se > 0 else 0
        return {"n": len(daily_means), "mean": m, "base": base_m, "diff": diff, "t": t}

    cands = [
        ("gap(高开)", "gap", True),
        ("today_ret(动量)", "today_ret", True),
        ("amount(小盘)", "amount", False),  # bottom decile = 小盘
    ]
    print(f"{'候选':<18}{'train mean':>12}{'train t':>9}{'test mean':>12}{'test t':>9}{'OOS?':>6}")
    print("-" * 68)
    survivors = []
    for label, key, top in cands:
        tr = period_stats(train_dates, key, top)
        te = period_stats(test_dates, key, top)
        if not tr or not te:
            continue
        # Bonferroni ×3: p<0.05/3=0.0167 → t>~2.4 (粗)
        oos = te["t"] > 2.4 and te["diff"] > 0
        if oos:
            survivors.append(label)
        sig_t = "✅" if te["t"] > 2.4 else "❌"
        print(f"{label:<18}{tr['mean']*100:>+10.4f}%{tr['t']:>8.2f}{te['mean']*100:>+11.4f}%{te['t']:>8.2f}{sig_t:>4}")
        print(f"{'  (base)':<18}{tr['base']*100:>+10.4f}%{'':>9}{te['base']*100:>+11.4f}%")
    print()
    if survivors:
        print(f"§44-survivor（OOS + Bonferroni×3 过）: {survivors}")
        print("但须再核：量级 + 可交易性（成本/滑点/跳空）")
    else:
        print("无 §44-survivor——3 候选 OOS 不成立（假阳），下一族信号")


if __name__ == "__main__":
    main()
