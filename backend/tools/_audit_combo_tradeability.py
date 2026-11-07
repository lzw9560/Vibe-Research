# -*- coding: utf-8 -*-
"""轮4：组合 survivor 可交易性审计（2026-10-20）。

轮3 combo（gap+动量+小盘）OOS survivor（test t=3.06, diff +0.170%）。但量级小 +
gap 跳空不可买。本脚本审：① median/WR（lottery vs 稳）② 扣成本后还正否
③ 去掉 gap 的组合（动量+小盘）是否独立 OOS（gap 不可交易）。
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
COST = 0.4  # 双边成本+滑点估算（小盘偏高）


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

    def top_decile_details(dates, use_gap=True):
        daily_mean, daily_median, daily_wr, all_picks = [], [], [], []
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
            if use_gap:
                scored = sorted(range(n), key=lambda k: rg[k] + rt[k] + ra[k], reverse=True)
            else:
                scored = sorted(range(n), key=lambda k: rt[k] + ra[k], reverse=True)  # 去 gap
            dec = max(1, n // 10)
            top = [lst[k]["nxt"] for k in scored[:dec]]
            daily_mean.append(statistics.mean(top))
            daily_median.append(statistics.median(top))
            daily_wr.append(sum(1 for x in top if x > 0) / len(top))
            all_picks.extend(top)
        if not daily_mean:
            return None
        m = statistics.mean(daily_mean)
        med = statistics.mean(daily_median)  # 日 median 的平均
        wr = statistics.mean(daily_wr)
        net = m - COST
        # t on daily mean vs 0
        std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
        se = std / (len(daily_mean) ** 0.5) if len(daily_mean) else 0
        t = m / se if se > 0 else 0
        return {
            "n_days": len(daily_mean),
            "mean": m,
            "median": med,
            "wr": wr,
            "net": net,
            "t": t,
            "n_picks": len(all_picks),
        }

    train = sorted(d for d in by_date if d < SPLIT)
    test = sorted(d for d in by_date if d >= SPLIT)
    print(f"=== 轮4 组合 survivor 可交易性审计 ===\n")
    for label, use_gap in [("combo(gap+动量+小盘)", True), ("combo-no-gap(动量+小盘)", False)]:
        tr = top_decile_details(train, use_gap)
        te = top_decile_details(test, use_gap)
        if not tr or not te:
            continue
        print(f"--- {label} ---")
        print(
            f"  train: mean {tr['mean'] * 100:+.4f}% median {tr['median'] * 100:+.4f}% WR {tr['wr'] * 100:.1f}% t={tr['t']:.2f} (n_days={tr['n_days']})"
        )
        print(f"  test:  mean {te['mean'] * 100:+.4f}% median {te['median'] * 100:+.4f}% WR {te['wr'] * 100:.1f}% t={te['t']:.2f}")
        print(
            f"         扣成本({COST}%): net {te['net'] * 100:+.4f}%  | median {'正(稳)' if te['median'] > 0 else '负(lottery)'} | WR {'>50%' if te['wr'] > 0.5 else '<50%'}"
        )
        oos = te["t"] > 2.4 and te["mean"] > 0
        print(f"  OOS(Bonf×3,t>2.4): {'✅' if oos else '❌'}")
        print()
    print("读法：net(扣成本)正 + median 正 + WR>50% = 可交易 edge；net 负 或 median 负 = lottery/不可交易")
    print("combo-no-gap OOS 过 = 去 gap 仍成立（可交易，无跳空问题）；不过 = edge 全靠 gap（不可交易）")


if __name__ == "__main__":
    main()
