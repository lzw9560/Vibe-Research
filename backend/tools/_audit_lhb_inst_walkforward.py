# -*- coding: utf-8 -*-
"""LHB inst_dominant walk-forward OOS（防 regime 过拟合）。

_full.py 全量 edge-confirmed（mean+0.390% day_t=9.02 p=0.0000 跨 regime 稳健）。
但 grilling 教训：V2 chrono test 半 regime 污染。本脚本 walk-forward：
  train 2018-2022（5 年）/ test 2023-2026（4 年）
  gate: train mean>0 + test mean>0 + test p<0.05 + test Bonf×3<0.05 → edge-confirmed OOS
"""

import json
import sqlite3
import statistics
from pathlib import Path
from collections import defaultdict
from math import erf

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
DT_DB = DATA / "dragon_tiger_history.db"
KLINE_DB = DATA / "baostock_kline_cache.db"

INST_KEYWORDS = (
    "机构专用",
    "总部",
    "高盛",
    "瑞银",
    "股通",
    "摩根",
    "中信证券股份有限公司上海分公司",
    "国际金融",
)
STOP_PCT = -3.0
ALPHA = 0.05
TRAIN_END = "2022-12-31"  # train 2018-2022 / test 2023-2026


def load_inst_dominant_picks() -> list:
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute("SELECT trade_date, security_code, dept_name, buy, net FROM dragon_tiger_rows WHERE side='buy' AND buy > 0").fetchall()
    conn.close()
    picks_by_dc: dict = defaultdict(list)
    for date, code, dept, buy, net in rows:
        picks_by_dc[(date, code)].append((dept or "", buy or 0, net or 0))

    inst_dominant: list = []
    for (date, code), seats in picks_by_dc.items():
        total_buy = sum(s[1] for s in seats)
        if total_buy <= 0:
            continue
        inst_buy = sum(s[1] for s in seats if any(k in s[0] for k in INST_KEYWORDS))
        if inst_buy / total_buy > 0.5:
            inst_dominant.append((date, code))
    return sorted(inst_dominant)


def load_kline(code: str) -> list:
    conn = sqlite3.connect(str(KLINE_DB))
    row = conn.execute("SELECT bars_json FROM kline WHERE code=?", (code,)).fetchone()
    conn.close()
    if not row:
        return []
    try:
        bars = json.loads(row[0])
        return sorted(bars, key=lambda b: b.get("date", ""))
    except Exception:
        return []


def compute_stop_intraday(code: str, trade_date: str, kline_cache: dict) -> float | None:
    if code not in kline_cache:
        kline_cache[code] = load_kline(code)
    bars = kline_cache[code]
    after = [b for b in bars if b.get("date", "") > trade_date]
    if len(after) < 2:
        return None
    t1 = after[0]
    t2 = after[1]
    t1_open = t1.get("open")
    t1_low = t1.get("low")
    t2_close = t2.get("close")
    if not t1_open or t1_open <= 0:
        return None
    stop_price = t1_open * (1 + STOP_PCT / 100)
    if t1_low is not None and t1_low <= stop_price:
        return (stop_price / t1_open - 1) * 100
    if not t2_close:
        return None
    return (t2_close / t1_open - 1) * 100


def normal_p(t: float) -> float:
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / (2**0.5))))


def stats(returns_by_date: dict, all_returns: list) -> dict:
    day_means = [statistics.mean(rs) for rs in returns_by_date.values() if rs]
    if len(day_means) < 2:
        return {}
    mean = statistics.mean(day_means)
    n_days = len(day_means)
    se = statistics.stdev(day_means) / (n_days**0.5) if n_days > 1 else 0
    t = mean / se if se > 0 else 0
    n = len(all_returns)
    wr = sum(1 for r in all_returns if r > 0) / n * 100 if n else 0
    sr = sorted(all_returns)
    median = sr[n // 2] if n else 0
    return {"n": n, "days": n_days, "mean": mean, "median": median, "wr": wr, "t": t, "p": normal_p(t)}


def walk_forward() -> None:
    picks = load_inst_dominant_picks()
    kline_cache: dict = {}

    # train / test 分半
    train_picks = [(d, c) for d, c in picks if d <= TRAIN_END]
    test_picks = [(d, c) for d, c in picks if d > TRAIN_END]

    print(f"=== inst_dominant walk-forward OOS ===")
    print(f"train: 2018-{TRAIN_END} ({len(train_picks)} picks)")
    print(f"test:  {TRAIN_END}后-2026 ({len(test_picks)} picks)\n")

    for label, subset in [("train", train_picks), ("test", test_picks)]:
        rbd: dict = defaultdict(list)
        ar: list = []
        for date, code in subset:
            r = compute_stop_intraday(code, date, kline_cache)
            if r is not None:
                rbd[date].append(r)
                ar.append(r)
        s = stats(rbd, ar)
        if not s:
            print(f"  {label}: 数据不足")
            continue
        p_bonf = min(1.0, s["p"] * 3)
        v = "PASS" if p_bonf < ALPHA else "FAIL"
        print(
            f"  {label}: n={s['n']} days={s['days']} mean={s['mean']:.3f}% "
            f"median={s['median']:.3f}% WR={s['wr']:.1f}% t={s['t']:.2f} "
            f"p={s['p']:.4f} Bonf×3={p_bonf:.4f} {v}"
        )

    # walk-forward gate
    print(f"\n  walk-forward gate:")
    train_s = stats(*[((), [])])  # placeholder, 重新算
    # 重新取 train/test stats
    train_rbd: dict = defaultdict(list)
    train_ar: list = []
    test_rbd: dict = defaultdict(list)
    test_ar: list = []
    for date, code in train_picks:
        r = compute_stop_intraday(code, date, kline_cache)
        if r is not None:
            train_rbd[date].append(r)
            train_ar.append(r)
    for date, code in test_picks:
        r = compute_stop_intraday(code, date, kline_cache)
        if r is not None:
            test_rbd[date].append(r)
            test_ar.append(r)
    train_s = stats(train_rbd, train_ar)
    test_s = stats(test_rbd, test_ar)
    if train_s and test_s:
        gates = {
            "train_mean>0": train_s["mean"] > 0,
            "test_mean>0": test_s["mean"] > 0,
            "test_p<0.05": test_s["p"] < 0.05,
            "test_bonf3<0.05": min(1.0, test_s["p"] * 3) < 0.05,
            "train_test同方向": (train_s["mean"] > 0) == (test_s["mean"] > 0),
        }
        for g, v in gates.items():
            print(f"    {g}: {'PASS' if v else 'FAIL'}")
        all_pass = all(gates.values())
        print(f"\n  → walk-forward OOS verdict: {'edge-confirmed' if all_pass else 'NOT confirmed'}")


if __name__ == "__main__":
    walk_forward()
