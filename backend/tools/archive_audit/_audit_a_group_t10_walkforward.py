# -*- coding: utf-8 -*-
"""A组 T+10 walk-forward OOS（#3 8步 ⑤，T+10 中持有正 edge 的 OOS 确认）。

_a_group_multiwindow.py: T+10 mean+0.989% WR49.1% day_t=7.43 p=0.0000（raw edge）。
但须 walk-forward OOS 确认（防 regime 过拟合）+ Bonf×N + R11 median。
train 2018-2022 / test 2023-2026，T+10 hold（T+2 open→T+12 close）。
gate: train mean>0 + test mean>0 + test p<0.05 + 同方向 → OOS edge-confirmed
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
TRAIN_END = "2022-12-31"
HOLD = 8  # T+10 = T+2 + 8 days
ALPHA = 0.05


def load_a_group_picks() -> list:
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
        if total_net > 5e7:
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
    """T+2 open → T+(2+hold_days) close。hold_days=8→T+10。"""
    if code not in _KLINE_CACHE:
        _KLINE_CACHE[code] = load_kline(code)
    bars = _KLINE_CACHE[code]
    after = [b for b in bars if b.get("date", "") > trade_date]
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


def stats(rbd: dict, ar: list) -> dict:
    day_means = [statistics.mean(rs) for rs in rbd.values() if rs]
    if len(day_means) < 2:
        return {}
    mean = statistics.mean(day_means)
    n_days = len(day_means)
    se = statistics.stdev(day_means) / (n_days ** 0.5) if n_days > 1 else 0
    t = mean / se if se > 0 else 0
    n = len(ar)
    wr = sum(1 for r in ar if r > 0) / n * 100 if n else 0
    sr = sorted(ar)
    median = sr[n // 2] if n else 0
    return {"n": n, "days": n_days, "mean": mean, "median": median, "wr": wr, "t": t, "p": normal_p(t)}


def walk_forward() -> None:
    picks = load_a_group_picks()
    train_picks = [(d, c) for d, c in picks if d <= TRAIN_END]
    test_picks = [(d, c) for d, c in picks if d > TRAIN_END]

    print(f"=== A组 T+10 walk-forward OOS（#3 8步 ⑤）===")
    print(f"train: 2018-{TRAIN_END} ({len(train_picks)} picks)")
    print(f"test:  {TRAIN_END}后-2026 ({len(test_picks)} picks)\n")

    results = {}
    for label, subset in [("train", train_picks), ("test", test_picks)]:
        rbd: dict = defaultdict(list)
        ar: list = []
        for date, code in subset:
            r = compute_window_return(code, date, HOLD)
            if r is not None:
                rbd[date].append(r)
                ar.append(r)
        s = stats(rbd, ar)
        if not s:
            print(f"  {label}: 数据不足")
            continue
        results[label] = s
        # Bonf×4（T+3/T+5/T+10/T+15 四窗口已测）
        p_bonf4 = min(1.0, s["p"] * 4)
        v = "PASS" if p_bonf4 < ALPHA else "FAIL"
        print(f"  {label}: n={s['n']} days={s['days']} mean={s['mean']:.3f}% median={s['median']:.3f}% "
              f"WR={s['wr']:.1f}% day_t={s['t']:.2f} p={s['p']:.4f} Bonf×4={p_bonf4:.4f} {v}")

    if "train" in results and "test" in results:
        train_s = results["train"]
        test_s = results["test"]
        gates = {
            "train_mean>0": train_s["mean"] > 0,
            "test_mean>0": test_s["mean"] > 0,
            "test_p<0.05": test_s["p"] < 0.05,
            "train_test同方向": (train_s["mean"] > 0) == (test_s["mean"] > 0),
        }
        print(f"\n  walk-forward gate:")
        for g, v in gates.items():
            print(f"    {g}: {'PASS' if v else 'FAIL'}")
        all_pass = all(gates.values())
        print(f"\n  → A组 T+10 walk-forward OOS verdict: {'edge-confirmed' if all_pass else 'NOT confirmed'}")
        if train_s["mean"] > 0:
            decay = (train_s["mean"] - test_s["mean"]) / abs(train_s["mean"]) * 100
            print(f"  decay: {decay:.0f}%")


if __name__ == "__main__":
    walk_forward()
