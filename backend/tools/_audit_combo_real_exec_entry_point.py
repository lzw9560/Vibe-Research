# -*- coding: utf-8 -*-
"""combo real-exec T+1 买点优化（2026-11-05，优化空间测试，用户"持续推进"）。

测 T+1 open（当前）vs T+1 close vs T+2 open 买点，避开 entry gap 高点。
- T+1 open（当前）：集合竞价买，但 entry gap 高（吃 +0.916%）
- T+1 close：收盘买，避开盘高开，但持有变 4 天（T+1 close→T+5 close）
- T+2 open：次日次日开盘买，避 T+1 高开，但信号滞后 1 天 + 持有 3 天
去 gap rank（动量+小盘），mode=filtered。
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
            if isST not in ("0", "", "0.0"):
                continue
            if code.startswith("920"):
                continue
            if today_ret >= bl:
                continue
            t1_open = float(bars[i + 1].get("open", 0) or 0)
            t1_close = float(bars[i + 1].get("close", 0) or 0)
            t2_open = float(bars[i + 2].get("open", 0) or 0) if i + 2 < len(bars) else 0
            t5_close = float(bars[i + 5].get("close", 0) or 0)
            if not t1_open or not t1_close or not t5_close:
                continue
            by_date[bars[i].get("date", "")].append(
                {
                    "code": code,
                    "tr": today_ret,
                    "amt": amt,
                    "t1_open": (t5_close - t1_open) / t1_open,
                    "t1_close": (t5_close - t1_close) / t1_close,
                    "t2_open": (t5_close - t2_open) / t2_open if t2_open else None,
                }
            )
    return by_date


def rank_top(lst: list, n: int = TOP_N) -> list | None:
    if len(lst) < n * 10:
        return None
    nn = len(lst)
    st = sorted(range(nn), key=lambda k: lst[k]["tr"])
    sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    return [lst[k] for k in sorted(range(nn), key=lambda k: rt[k] + ra[k], reverse=True)[:n]]


def stats(dates: list, by_date: dict, field: str) -> dict | None:
    daily_mean, all_picks = [], []
    for d in dates:
        top = rank_top(by_date[d])
        if not top:
            continue
        rets = [x[field] for x in top if x[field] is not None]
        if not rets:
            continue
        daily_mean.append(statistics.mean(rets))
        all_picks.extend(rets)
    if not daily_mean:
        return None
    m = statistics.mean(daily_mean)
    wr = sum(1 for x in all_picks if x > 0) / len(all_picks)
    std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
    se = std / (len(daily_mean) ** 0.5) if daily_mean else 0
    t = m / se if se > 0 else 0
    return {"n_days": len(daily_mean), "mean": m, "wr": wr, "net": m - COST, "t": t}


def main() -> None:
    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    print(f"\n=== combo T+1 买点优化（去 gap rank mode=filtered，{len(all_d)} 日）===\n")
    print(f"{'买点':<16}{'days':>6}{'net':>10}{'mean':>10}{'WR':>7}{'t':>7}")
    print("-" * 56)
    results = []
    for label, field in [("T+1 open(当前)", "t1_open"), ("T+1 close", "t1_close"), ("T+2 open", "t2_open")]:
        r = stats(all_d, by_date, field)
        results.append((label, r))
        if r:
            print(f"{label:<16}{r['n_days']:>6}{r['net'] * 100:>+9.3f}%{r['mean'] * 100:>+9.3f}%{r['wr'] * 100:>6.1f}%{r['t']:>6.2f}")
    print()
    valid = [(l, r) for l, r in results if r]
    if valid:
        best = max(valid, key=lambda x: x[1]["net"])
        base = next(r for l, r in results if "T+1 open" in l)
        if base:
            delta = best[1]["net"] - base["net"]
            print(
                f"最佳买点: {best[0]} net {best[1]['net'] * 100:+.3f}%（vs T+1 open {base['net'] * 100:+.3f}%，{'提升' if delta > 0 else '降'} {delta * 100:+.3f}%）"
            )
            if best[0] != "T+1 open(当前)":
                print(f"→ 改买点 {best[0]} 可能避开 entry gap 高点提升 edge（但注意持有期变 + 滞后）")


if __name__ == "__main__":
    main()
