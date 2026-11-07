# -*- coding: utf-8 -*-
"""A组跟庄多窗口 sanity（R5）——修正 ① T+3 卖太早的口径问题。

_a_group_honest.py ① 只测 T+2open→T+3close（1 天），mean -0.725% falsified。
但 playbook 持有 T+2~T+15（最长 15 天等拉升），T+3 卖太早没等拉升。
本脚本测多窗口：T+2open→T+3/T+5/T+10/T+15 close，看是否回升。
"""
import json
import sqlite3
import statistics
from pathlib import Path
from collections import defaultdict
from math import erf

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
DT_DB = DATA / "dragon_tiger_history.db"
KLINE_DB = DATA / "baostock_kline_cache.db"


def load_a_group_picks() -> list:
    """A组条件：涨幅-3%~+10% + 净买<0.5亿(5e7元) + 净买>0。"""
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute("""
        SELECT trade_date, security_code, SUM(net) as total_net, MAX(change_rate) as chg
        FROM dragon_tiger_rows
        WHERE side='buy' AND net IS NOT NULL
        GROUP BY trade_date, security_code
    """).fetchall()
    conn.close()
    picks = []
    for date, code, total_net, chg in rows:
        if total_net is None or chg is None:
            continue
        if not (-3 <= chg <= 10):
            continue
        if total_net <= 0:
            continue
        if total_net > 5e7:  # 净买<0.5亿 = <5e7 元
            continue
        picks.append((date, code))
    return sorted(picks)


def load_kline(code: str) -> list:
    conn = sqlite3.connect(str(KLINE_DB))
    row = conn.execute("SELECT bars_json FROM kline WHERE code=?", (code,)).fetchone()
    conn.close()
    if not row:
        return []
    try:
        return sorted(json.loads(row[0]), key=lambda b: b.get("date", ""))
    except Exception:
        return []


_KLINE_CACHE: dict = {}


def compute_window_return(code: str, trade_date: str, hold_days: int) -> float | None:
    """T+2 open 买 → T+(2+hold_days) close 卖。hold_days=1→T+3, 3→T+5, 8→T+10, 13→T+15。"""
    if code not in _KLINE_CACHE:
        _KLINE_CACHE[code] = load_kline(code)
    bars = _KLINE_CACHE[code]
    after = [b for b in bars if b.get("date", "") > trade_date]
    # T+2 = after[1], T+(2+hold_days) = after[1+hold_days]
    buy_idx = 1  # T+2
    sell_idx = 1 + hold_days  # T+(2+hold_days)
    if len(after) <= sell_idx:
        return None
    t2_open = after[buy_idx].get("open")
    sell_close = after[sell_idx].get("close")
    if not t2_open or t2_open <= 0 or not sell_close:
        return None
    return (sell_close / t2_open - 1) * 100


def normal_p(t: float) -> float:
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / (2 ** 0.5))))


def audit_multiwindow() -> None:
    picks = load_a_group_picks()
    print(f"=== A组 多窗口 sanity（R5）——修正 ① T+3 口径 ===")
    print(f"A组 picks: {len(picks)}\n")

    windows = [(1, "T+2→T+3"), (3, "T+2→T+5"), (8, "T+2→T+10"), (13, "T+2→T+15")]
    for hold, label in windows:
        rbd: dict = defaultdict(list)
        ar: list = []
        for date, code in picks:
            r = compute_window_return(code, date, hold)
            if r is not None:
                rbd[date].append(r)
                ar.append(r)
        if not ar:
            print(f"  {label}: 无数据")
            continue
        day_means = [statistics.mean(rs) for rs in rbd.values() if rs]
        if len(day_means) < 2:
            print(f"  {label}: days<2")
            continue
        mean = statistics.mean(day_means)
        n_days = len(day_means)
        se = statistics.stdev(day_means) / (n_days ** 0.5) if n_days > 1 else 0
        t = mean / se if se > 0 else 0
        n = len(ar)
        wr = sum(1 for r in ar if r > 0) / n * 100 if n else 0
        sr = sorted(ar)
        median = sr[n // 2] if n else 0
        p = normal_p(t)
        verdict = "PASS" if p < 0.05 else "FAIL"
        print(f"  {label}: n={n} days={n_days} mean={mean:.3f}% median={median:.3f}% "
              f"WR={wr:.1f}% day_t={t:.2f} p={p:.4f} {verdict}")

    print(f"\n对比 playbook: 59% WR +5.3% mean (3月304只, 10采样日)")
    print(f"诚实口径 8年25347 picks 多窗口——看持有期是否救活")


if __name__ == "__main__":
    audit_multiwindow()
