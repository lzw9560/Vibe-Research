# -*- coding: utf-8 -*-
"""轮5：组合 survivor 延长持有（2026-10-20）。

轮4 combo OOS survivor 但 1 日 mean +0.25% 被成本 0.4% 吃（net 负）+ lottery（median 负）。
本脚本测 1/3/5 日持有，看 mean 累积是否超成本（1 次成本摊多日）+ lottery 是否持续。
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
SPLIT = "2023-01-01"
COST = 0.004  # 双边成本 0.4%（decimal）


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
        if len(bars) < 30:
            continue
        for i in range(5, len(bars) - 5):
            prev_c = float(bars[i-1].get("close", 0) or 0)
            o = float(bars[i].get("open", 0) or 0)
            c = float(bars[i].get("close", 0) or 0)
            amt = float(bars[i].get("amount", 0) or 0)
            if not prev_c or not c or not o:
                continue
            today_ret = (c - prev_c) / prev_c
            gap = (o - prev_c) / prev_c
            # forward returns 1/3/5 day (close-to-close)
            fwd = {}
            for n in (1, 3, 5):
                if i + n < len(bars):
                    nc = float(bars[i+n].get("close", 0) or 0)
                    fwd[n] = (nc - c) / c if c else None
                else:
                    fwd[n] = None
            if fwd[1] is None:
                continue
            by_date[bars[i].get("date", "")].append({"gap": gap, "tr": today_ret, "amt": amt, "fwd": fwd})

    def combo_top_decile_fwd(dates, hold_n):
        daily_mean, daily_median, daily_wr = [], [], []
        for d in dates:
            lst = by_date[d]
            if len(lst) < 20:
                continue
            n = len(lst)
            sg = sorted(range(n), key=lambda k: lst[k]["gap"])
            st = sorted(range(n), key=lambda k: lst[k]["tr"])
            sa = sorted(range(n), key=lambda k: lst[k]["amt"])
            rg = {orig: r / n for r, orig in enumerate(sg)}
            rt = {orig: r / n for r, orig in enumerate(st)}
            ra = {orig: (1 - r / n) for r, orig in enumerate(sa)}
            scored = sorted(range(n), key=lambda k: rg[k] + rt[k] + ra[k], reverse=True)
            dec = max(1, n // 10)
            fwds = [lst[k]["fwd"][hold_n] for k in scored[:dec] if lst[k]["fwd"][hold_n] is not None]
            if not fwds:
                continue
            daily_mean.append(statistics.mean(fwds))
            daily_median.append(statistics.median(fwds))
            daily_wr.append(sum(1 for x in fwds if x > 0) / len(fwds))
        if not daily_mean:
            return None
        m = statistics.mean(daily_mean)
        med = statistics.mean(daily_median)
        wr = statistics.mean(daily_wr)
        net = m - COST  # 1 次成本摊 hold_n 日
        std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
        se = std / (len(daily_mean) ** 0.5) if len(daily_mean) else 0
        t = m / se if se > 0 else 0
        return {"mean": m, "median": med, "wr": wr, "net": net, "t": t, "n": len(daily_mean)}

    test = sorted(d for d in by_date if d >= SPLIT)
    print(f"=== 轮5 combo 延长持有（test {len(test)} 日）===")
    print(f"combo = rank(gap)+rank(动量)+rank(-小盘) top decile，1 次成本 {COST*100}% 摊 N 日\n")
    print(f"{'持有':<6}{'mean':>10}{'median':>10}{'WR':>8}{'net(扣成本)':>14}{'t':>7}{'可交易?':>9}")
    print("-" * 64)
    for n in (1, 3, 5):
        r = combo_top_decile_fwd(test, n)
        if not r:
            continue
        ok = r["net"] > 0 and r["median"] > 0 and r["wr"] > 0.5
        print(f"{n}日{'':<4}{r['mean']*100:>+9.4f}%{r['median']*100:>+9.4f}%{r['wr']*100:>6.1f}%{r['net']*100:>+12.4f}%{r['t']:>6.2f}{'✅' if ok else '❌':>6}")
    print()
    print("读法：net 正 + median 正 + WR>50% = 可交易；否则 lottery/成本吃光")


if __name__ == "__main__":
    main()
