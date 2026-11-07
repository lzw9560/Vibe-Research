# -*- coding: utf-8 -*-
"""combo 集中度 walk-forward OOS（2026-11-05，回答"收敛是真edge还是overfit"）。

concentration 测试显示 top-3 net +2.098% / top-5 +1.393% 远强于 top-20 +0.406%。
但 rank 是全样本算的——top-3 优势可能是 selection bias（极端排名最overfit）。
walk-forward：train(前60%日) vs test(后40%日)，看 top-N 在 test 是否仍 hold + 衰减率。

若 top-3 test t 仍高（衰减率同 top-20 ~13%）→ 真集中 edge 非 overfit。
若 top-3 train t>>test t（衰减率远高于 top-20）→ 极端集中是 overfit 信号。
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / ".vibe-research" / "baostock_kline_cache.db"
COST = 0.004
TOP_NS = [3, 5, 7, 10, 20, 50]
TRAIN_FRAC = 0.6


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
        nb = len(bars)
        if nb < 70:
            continue
        c0 = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
        bl = 0.20 if (c0.startswith("30") or c0.startswith("68")) else (
            0.30 if (c0.startswith("8") or c0.startswith("4")) else 0.10)
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
            prev_c = closes[i - 1]; o = opens[i]; c = closes[i]; amt = amts[i]
            if not prev_c or not c or not o or not amt:
                continue
            ma60 = (cumsum[i] - cumsum[i - 60]) / 60.0
            if not ma60:
                continue
            today_ret = (c - prev_c) / prev_c
            if code.startswith("920"):
                continue
            if today_ret >= bl:
                continue
            t1_close = closes[i + 1] if i + 1 < nb else 0.0
            t5_close = closes[i + 5]
            if not t1_close or not t5_close:
                continue
            by_date[dates_l[i]].append({
                "code": code, "tr": today_ret, "amt": amt,
                "t1_close": (t5_close - t1_close) / t1_close,
            })
    return by_date


def rank_top_nogap(lst: list, n: int) -> list | None:
    if len(lst) < n * 10:
        return None
    nn = len(lst)
    st = sorted(range(nn), key=lambda k: lst[k]["tr"])
    sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    return [lst[k] for k in sorted(range(nn), key=lambda k: rt[k] + ra[k], reverse=True)[:n]]


def stats_split(dates: list, by_date: dict, n: int) -> dict:
    daily_mean, daily_median, all_picks = [], [], []
    for d in dates:
        top = rank_top_nogap(by_date[d], n)
        if not top:
            continue
        rets = [x["t1_close"] for x in top]
        daily_mean.append(statistics.mean(rets))
        daily_median.append(statistics.median(rets))
        all_picks.extend(rets)
    if not daily_mean:
        return {}
    m = statistics.mean(daily_mean)
    med = statistics.mean(daily_median)
    wr = sum(1 for x in all_picks if x > 0) / len(all_picks)
    std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
    se = std / (len(daily_mean) ** 0.5)
    t = m / se if se > 0 else 0
    return {"n_days": len(daily_mean), "mean": m, "median": med, "wr": wr,
            "net": m - COST, "t": t}


def main() -> None:
    print("loading cache...", flush=True)
    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    split = int(len(all_d) * TRAIN_FRAC)
    train_d = all_d[:split]
    test_d = all_d[split:]
    print(f"dates={len(all_d)} train={len(train_d)}({train_d[0]}~{train_d[-1]}) "
          f"test={len(test_d)}({test_d[0]}~{test_d[-1]})\n", flush=True)

    print("=== combo 集中度 walk-forward OOS（T+1 close 去涨停去gap）===")
    print(f"{'topN':>5} | {'TRAIN net':>10}{'med':>8}{'t':>6} | {'TEST net':>10}{'med':>8}{'t':>6} | {'衰减':>7}{'判':>8}")
    print("-" * 80)
    for n in TOP_NS:
        tr = stats_split(train_d, by_date, n)
        te = stats_split(test_d, by_date, n)
        if not tr or not te:
            continue
        decay = (1 - te["net"] / tr["net"]) * 100 if tr["net"] else 0
        # survivor if test t > 2.4 (Bonferroni×3 approx) and decay < 50%
        ok = "✅survivor" if (te["t"] > 2.4 and decay < 50) else ("🟡weak" if te["t"] > 1.5 else "❌fail")
        print(f"{n:>5} | {tr['net']*100:>+9.3f}%{tr['median']*100:>+7.3f}%{tr['t']:>5.2f} | "
              f"{te['net']*100:>+9.3f}%{te['median']*100:>+7.3f}%{te['t']:>5.2f} | "
              f"{decay:>+6.1f}%{ok:>8}")

    print("\n判据: test t>2.4 + 衰减<50% = survivor（真集中edge非overfit）")
    print("      若 top-3 衰减率远高于 top-20(~13%) → 极端集中 overfit 信号")


if __name__ == "__main__":
    main()
