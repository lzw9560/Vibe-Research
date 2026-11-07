# -*- coding: utf-8 -*-
"""inst_dominant **top6 combo** T+n 矩阵——查 spec 的 +0.457%(T+2=1天) 是否真，还是 top6 也得长持有。

matrix 宽 >50% 池显示 1-4 天亏、5-15 天才赚（peak T+9 +2.43%）。但 spec 的 edge-confirmed
+0.457% 是 >80% top6 combo 在 "T+2"(1天) 测的。这俩打架吗？本脚本用 spec 的精确选股
（>80% + top6 by 机构金额/日）跑 T+n，定位 top6 的 edge 在哪。

关联：S236 / _audit_inst_tn_matrix.py / memory inst-dominant-walkforward-oos-edge-confirmed
"""
from __future__ import annotations

import sqlite3
import statistics
from collections import defaultdict
from math import erf, sqrt

from _audit_inst_tn_matrix import (  # compute_tn_returns 已修 off-by-one（2026-10-18，同 spec 口径）
    COST, DT_DB, INST_KEYWORDS, KLINE_DB, MAX_N,
    compute_tn_returns, load_kline,
)

INST_PCT_MIN = 0.8  # S236 basic: >80% 纯化


def load_top6_picks() -> list:
    """每日 >80% 机构占比 + 按机构金额 top6（S236 basic 选股口径）。返 [(date, code)]。"""
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute(
        "SELECT trade_date, security_code, dept_name, buy "
        "FROM dragon_tiger_rows WHERE side='buy' AND buy > 0"
    ).fetchall()
    conn.close()
    by_date_code: dict = defaultdict(list)
    for date, code, dept, buy in rows:
        by_date_code[(date, code)].append((dept or "", buy or 0))
    by_date: dict = defaultdict(list)
    for (date, code), seats in by_date_code.items():
        total = sum(s[1] for s in seats)
        if total <= 0:
            continue
        inst_buy = sum(s[1] for s in seats if any(k in s[0] for k in INST_KEYWORDS))
        inst_pct = inst_buy / total
        if inst_pct > INST_PCT_MIN:
            by_date[date].append((code, inst_buy))
    picks: list = []
    for date, cands in by_date.items():
        cands.sort(key=lambda x: x[1], reverse=True)
        for code, _ in cands[:6]:  # top6 by 机构金额
            picks.append((date, code))
    return picks


def stats(rets: list) -> dict:
    n = len(rets)
    if n == 0:
        return {"n": 0, "mean": 0, "wr": 0, "median": 0, "t": 0, "p": 1}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0
    se = std / sqrt(n) if n else 0
    t = mean / se if se > 0 else 0
    p = 0.5 * (1 - erf(t / sqrt(2))) if t > 0 else 1.0
    return {"n": n, "mean": mean, "wr": sum(1 for x in rets if x > 0) / n,
            "median": statistics.median(rets), "t": t, "p": p}


def main() -> None:
    picks = load_top6_picks()
    if not picks:
        print("无 top6 picks（dragon_tiger_history.db 缺失或空）")
        return
    n_days = len({d for d, _ in picks})
    print(f"=== inst_dominant top6 combo T+n 矩阵（>80% + top6/日, n=1~{MAX_N}）===")
    print(f"picks: {len(picks)}  独立日: {n_days}  买: T+1 open  卖: T+n close  成本: {COST}% 双边\n")
    kc: dict = {}
    tn_rets: dict = defaultdict(list)
    for date, code in picks:
        rets = compute_tn_returns(code, date, kc)
        for n, r in rets.items():
            tn_rets[n].append(r)
    print(f"{'T+n':>4} {'net EV%':>9} {'WR%':>6} {'median':>8} {'t':>6} {'p':>9} {'n_obs':>8}")
    print("-" * 55)
    best_n = None
    best_ev = -999
    for n in range(1, MAX_N + 1):
        s = stats(tn_rets.get(n, []))
        if s["n"] == 0:
            continue
        sig = "✅" if s["p"] < 0.05 else "❌"
        print(f"T+{n:>2} {s['mean']:>8.3f} {s['wr']*100:>5.1f}% {s['median']:>8.3f} "
              f"{s['t']:>6.2f} {s['p']:>8.4f}{sig} {s['n']:>8}")
        if s["mean"] > best_ev and s["p"] < 0.05:
            best_ev = s["mean"]
            best_n = n
    print(f"\n最优 T+n（最高 EV + p<0.05）: T+{best_n} net EV+{best_ev:.3f}%")
    print(f"\n对照 spec S236: basic top6 nostop mean+0.457%（T+2=1天持有口径）")
    s1 = stats(tn_rets.get(1, []))
    print(f"本脚本 T+1(=spec 的'T+2'1天): mean {s1['mean']:+.3f}% WR {s1['wr']*100:.1f}% "
          f"median {s1['median']:+.3f} p={s1['p']:.4f}{' ✅' if s1['p']<0.05 else ' ❌'}")


if __name__ == "__main__":
    main()
