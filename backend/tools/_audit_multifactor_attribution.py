# -*- coding: utf-8 -*-
"""多因子横截面归因（2026-10-20）——认真找短端 edge。

之前单因子前兆（+5%+量比）lift 有但 EV 负。本脚本横截面（每日按因子排序 top decile）
测多个因子，看哪个的 top decile 次日 mean return 正且 > base。

因子（每日横截面排序）：
1. today_ret（今日涨幅，动量/反转）
2. vol_ratio（量比，放量）
3. range（振幅 (high-low)/close，日内波动）
4. prior5d_ret（5日累计涨幅，中动量）
5. gap（开盘跳空 open/prev_close-1）
6. amount（今日成交额，流动性/规模代理——低 amount = 小盘）

每日：按因子排序取 top decile（amount 取 bottom decile = 小盘），算次日 mean return。
横截面平均。对比 base（全样本次日 mean）。

caveat：6 因子多重检验，显著的须 walk-forward 复验（§44）。关联 _audit_precursor_*
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / ".vibe-research" / "baostock_kline_cache.db"


def main() -> None:
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    # 收集 per stock-day: (date, today_ret, vol_ratio, range, prior5d, gap, amount, next_ret)
    by_date: dict = defaultdict(list)  # date -> list of dict
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
            h = float(bars[i].get("high", 0) or 0)
            lo = float(bars[i].get("low", 0) or 0)
            c = float(bars[i].get("close", 0) or 0)
            amt = float(bars[i].get("amount", 0) or 0)
            if not prev_c or not c or not o:
                continue
            today_ret = (c - prev_c) / prev_c
            ma20 = statistics.mean(vols[max(0, i-20):i]) if i >= 1 else 0
            vol_ratio = (vols[i] / ma20) if ma20 else 0
            rng = (h - lo) / c if c else 0
            # prior 5d ret: bars[i-5].close -> bars[i].close? 用 i-1 close 到 i close 的前5天
            p5c = float(bars[i-5].get("close", 0) or 0)
            prior5d = (c - p5c) / p5c if p5c else 0
            gap = (o - prev_c) / prev_c
            nxt_c = float(bars[i+1].get("close", 0) or 0)
            if not nxt_c:
                continue
            nxt_ret = (nxt_c - c) / c
            by_date[bars[i].get("date", "")].append({
                "today_ret": today_ret, "vol_ratio": vol_ratio, "range": rng,
                "prior5d": prior5d, "gap": gap, "amount": amt, "nxt_ret": nxt_ret,
            })

    # base: 全样本次日 mean（按日平均，再平均）
    all_daily_means = [statistics.mean(d["nxt_ret"] for d in lst) for lst in by_date.values() if lst]
    base_mean = statistics.mean(all_daily_means) if all_daily_means else 0

    print(f"=== 多因子横截面归因（{len(by_date)} 日, 每日 top decile）===")
    print(f"base 次日 mean（全样本日均）= {base_mean*100:+.4f}%\n")
    print(f"{'因子':<18}{'top-decile 次日mean':>20}{'vs base':>10}{'显著?':>8}")
    print("-" * 58)

    factors = [
        ("today_ret(动量)", "today_ret", True),
        ("today_ret(反转-btm)", "today_ret", False),
        ("vol_ratio(放量)", "vol_ratio", True),
        ("range(高振幅)", "range", True),
        ("prior5d(中动量)", "prior5d", True),
        ("gap(高开)", "gap", True),
        ("amount(小盘-btm)", "amount", False),
    ]
    for label, key, top in factors:
        daily_top = []
        for lst in by_date.values():
            if len(lst) < 20:
                continue
            s = sorted(lst, key=lambda x: x[key], reverse=top)
            dec = max(1, len(s) // 10)
            daily_top.append(statistics.mean(d["nxt_ret"] for d in s[:dec]))
        if not daily_top:
            continue
        m = statistics.mean(daily_top)
        diff = m - base_mean
        # 简单显著：日 mean 与 base 的 t（粗）
        std = statistics.pstdev(daily_top) if len(daily_top) > 1 else 0
        se = std / (len(daily_top) ** 0.5) if len(daily_top) else 0
        t = diff / se if se > 0 else 0
        sig = "✅" if (t > 2 and diff > 0) else ("❌" if t < -2 else "≈")
        print(f"{label:<18}{m*100:>+17.4f}%{diff*100:>+9.4f}%{sig:>6} (t={t:.1f})")

    print()
    print("读法：top-decile 次日 mean > base 且 t>2 = 该因子 top 表现次日真赚钱（候选 edge）")
    print("caveat：7 因子多重检验，显著的须 walk-forward + Bonferroni 复验（§44）")


if __name__ == "__main__":
    main()
