# -*- coding: utf-8 -*-
"""轮3：组合因子 walk-forward（2026-10-20）。

轮2 singles OOS 全 FAIL（test t 1.3-1.6，方向正但不显著）。组合 3 候选
(gap + today_ret + 小盘) 成 composite score，看 top-decile 是否 OOS 显著。
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
        for i in range(5, len(bars) - 1):
            prev_c = float(bars[i - 1].get("close", 0) or 0)
            o = float(bars[i].get("open", 0) or 0)
            c = float(bars[i].get("close", 0) or 0)
            amt = float(bars[i].get("amount", 0) or 0)
            if not prev_c or not c or not o:
                continue
            today_ret = (c - prev_c) / prev_c
            gap = (o - prev_c) / prev_c
            nxt_c = float(bars[i + 1].get("close", 0) or 0)
            if not nxt_c:
                continue
            nxt_ret = (nxt_c - c) / c
            by_date[bars[i].get("date", "")].append({"gap": gap, "tr": today_ret, "amt": amt, "nxt": nxt_ret})

    def composite_top_decile(dates):
        daily = []
        for d in dates:
            lst = by_date[d]
            if len(lst) < 20:
                continue
            # cross-sectional rank percentile (0..1) per factor
            n = len(lst)
            sg = sorted(range(n), key=lambda k: lst[k]["gap"])
            st = sorted(range(n), key=lambda k: lst[k]["tr"])
            sa = sorted(range(n), key=lambda k: lst[k]["amt"])  # low amt = small cap = high score
            rg = {orig: r / n for r, orig in enumerate(sg)}
            rt = {orig: r / n for r, orig in enumerate(st)}
            ra = {orig: (1 - r / n) for r, orig in enumerate(sa)}  # invert: small amt → high score
            scored = sorted(range(n), key=lambda k: rg[k] + rt[k] + ra[k], reverse=True)
            dec = max(1, n // 10)
            daily.append(statistics.mean(lst[k]["nxt"] for k in scored[:dec]))
        if not daily:
            return None
        m = statistics.mean(daily)
        std = statistics.pstdev(daily) if len(daily) > 1 else 0
        se = std / (len(daily) ** 0.5) if len(daily) else 0
        base_daily = [statistics.mean(x["nxt"] for x in by_date[d]) for d in dates if len(by_date[d]) >= 20]
        base_m = statistics.mean(base_daily) if base_daily else 0
        diff = m - base_m
        t = diff / se if se > 0 else 0
        return {"n": len(daily), "mean": m, "base": base_m, "diff": diff, "t": t}

    train_dates = sorted(d for d in by_date if d < SPLIT)
    test_dates = sorted(d for d in by_date if d >= SPLIT)
    print(f"=== 轮3 组合因子 walk-forward（train {len(train_dates)} / test {len(test_dates)} 日）===")
    print("composite = rank(gap) + rank(today_ret) + rank(-amount小盘)\n")
    tr = composite_top_decile(train_dates)
    te = composite_top_decile(test_dates)
    if tr and te:
        print(f"train: top-decile mean {tr['mean'] * 100:+.4f}% (base {tr['base'] * 100:+.4f}%, diff {tr['diff'] * 100:+.4f}%, t={tr['t']:.2f})")
        print(f"test:  top-decile mean {te['mean'] * 100:+.4f}% (base {te['base'] * 100:+.4f}%, diff {te['diff'] * 100:+.4f}%, t={te['t']:.2f})")
        oos = te["t"] > 2.4 and te["diff"] > 0  # Bonferroni×3 粗
        print(f"\nOOS (Bonferroni×3, t>2.4): {'✅ SURVIVOR' if oos else '❌ FAIL'}")
        if oos:
            print("§44-survivor! 须再核可交易性（成本/滑点/跳空）+ 单独 Bonferroni 精算")
        else:
            print("组合也 OOS 不成立 → singles 弱非组合能救 → 轮4 换族（regime 条件化 / 板块轮动）")


if __name__ == "__main__":
    main()
