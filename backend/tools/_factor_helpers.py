# -*- coding: utf-8 -*-
"""因子回测共享 helper——所有 explore_factor_*.py 脚本 import 此模块。

含 §44 v3 anti-fake-edge 全套过严口径：
- limit_for_code (FIXED 2026-10-06: 6 位纯数字 code, 非 sz30/sh68 前缀)
- is_yizi_t1 (T+1 一字涨停跳过, 买不进)
- close_ev_basic (T+1 open 买 → T+2 close 卖, 非开 ev 防日内泄漏)
- close_ev_stop (R6 gap-through fill: 跳空穿 stop 按 T+2 open + 滑点)
- per-day-mean t (同日 picks 聚成 day-mean, 非 per-trade t——同日相关夸大 N)
- Bonferroni (cross-factor ×N, 非 within-factor ×2)
- walk-forward OOS (前半 train → 后半 test, 非 in-sample 分段)

诚实约束（P1 + 6 假 edge 教训）：
- entry = T+1 open (非 T+1 close——T close sealed 不可买; 100% winner T+1 close==high)
- 一字涨停跳过 (买不进)
- close_ev 非 open_ev (open_ev 有 T+1 日内泄漏)
- R6: 跳空穿 stop 按 t2_open 非 stop_price + 滑点 0.2%
- per-day-mean t 非 per-trade t
- 禁止外推: 单因子 ≠ 打板有/无 edge

跑法: import 后用 build_picks_generic + analyze_subset + verdict_for。
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt
from typing import Callable

# ---------- paths + constants ----------

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
ZT_DB = DATA / "zt_history.db"

SLIPPAGE = 0.002       # 0.2% 滑点 (R6 gap-through fill)
COST = 0.003           # round-trip cost (印花+佣金+滑点) for net EV
STOP_PCT = 0.03        # -3% stop for stop variant
ALPHA = 0.05


# ---------- data loading ----------

def load_kline_db() -> tuple[dict[str, dict[str, dict]], set[str]]:
    """从 SQLite 读 kline. 返回 (code -> {date: bar}, all_dates set)."""
    conn = sqlite3.connect(str(KLINE_DB))
    code_map: dict[str, dict[str, dict]] = {}
    all_dates: set[str] = set()
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or not bars:
            continue
        dmap: dict[str, dict] = {}
        for b in bars:
            d = b.get("date")
            if d:
                dmap[d] = b
                all_dates.add(d)
        if dmap:
            code_map[code] = dmap
    conn.close()
    return code_map, all_dates


def load_zt() -> list[tuple[str, str, int]]:
    """返回 [(date, code, lbc)] 列表. lbc NULL/0 当 1."""
    conn = sqlite3.connect(str(ZT_DB))
    rows: list[tuple[str, str, int]] = []
    for d, code, lbc in conn.execute("SELECT date, code, lbc FROM zt_history"):
        rows.append((d, code, lbc if lbc else 1))
    conn.close()
    return rows


# ---------- helpers (FIXED 2026-10-06) ----------

def limit_for_code(code: str, is_st: bool = False) -> float:
    """涨停幅度: ST 5%, 创业板(300/301)/科创板(688/689) 20%, 北交(4/8 开头) 30%, 其他 10%.

    FIX 2026-10-06: 原 explore_factor_first-board-vs-relay.py 用 code.startswith(("sz30","sh68"))
    判 20%——但数据库 code 是 6 位纯数字无交易所前缀 (如 "300650" 非 "sz300650")，
    导致创业板+科创板全部被当 10% limit → is_yizi_t1 用 *1.10 而非 *1.20 算涨停价 →
    46 个 T+1 一字涨停 (20% 封死) 没被跳过, 严重通胀 first_board EV +20%。

    正确判定: 按 6 位纯数字前缀。
    - 300/301 → 创业板 (20%)
    - 688/689 → 科创板 (20%)
    - 4/8 开头 → 北交 (30%, 罕见)
    - ST → 5%
    - 其他 (600/601/603/605, 000/001/002/003) → 10%
    """
    if is_st:
        return 0.05
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    if code.startswith(("4", "8")):
        return 0.30  # 北交
    return 0.10


def is_yizi_t1(t1_bar: dict, t_close: float, limit: float) -> bool:
    """T+1 一字涨停: open 和 low 都在涨停价附近 (locked, 买不进)."""
    lim_up = t_close * (1 + limit)
    o = t1_bar.get("open")
    l = t1_bar.get("low")
    if o is None or l is None or lim_up <= 0:
        return False
    return abs(o - lim_up) / lim_up < 0.005 and abs(l - lim_up) / lim_up < 0.005


# ---------- pick construction (generic, filter callback) ----------

def build_picks_generic(
    code_map: dict[str, dict[str, dict]],
    calendar: list[str],
    zt_rows: list[tuple[str, str, int]],
    filter_fn: Callable[[str, int, dict, dict, dict], bool] | None = None,
) -> list[dict]:
    """构建 picks: entry=T+1 open, exit=T+2 close.

    跳过: 无 kline / T+1 一字涨停 (买不进) / T+1 或 T+2 无 bar.
    filter_fn(code, lbc, t_bar, t1_bar, t2_bar) 返回 True 则纳入 (None=全纳).

    返回 picks list, 每条含 code/zt_date/t1_date/t2_date/entry/t1_bar/t2_bar/t_close/lbc.
    """
    date_idx = {d: i for i, d in enumerate(calendar)}
    picks: list[dict] = []
    for zt_date, code, lbc in zt_rows:
        d_idx = date_idx.get(zt_date)
        if d_idx is None or d_idx + 2 >= len(calendar):
            continue  # need T+1 and T+2
        dmap = code_map.get(code)
        if not dmap:
            continue

        t_bar = dmap.get(zt_date)
        if t_bar is None or t_bar.get("close") is None:
            continue
        t_close = t_bar["close"]
        if t_close <= 0:
            continue

        t1_date = calendar[d_idx + 1]
        t2_date = calendar[d_idx + 2]
        t1_bar = dmap.get(t1_date)
        t2_bar = dmap.get(t2_date)
        if t1_bar is None or t2_bar is None:
            continue
        t1_open = t1_bar.get("open")
        t2_close = t2_bar.get("close")
        if t1_open is None or t2_close is None:
            continue
        if t1_open <= 0 or t2_close <= 0:
            continue

        # 一字 check on T+1 (用 FIXED limit_for_code)
        is_st = t_bar.get("isST") == "1"
        limit = limit_for_code(code, is_st)
        if is_yizi_t1(t1_bar, t_close, limit):
            continue  # T+1 一字涨停, 买不进, 跳过

        # factor-specific filter
        if filter_fn is not None and not filter_fn(code, lbc, t_bar, t1_bar, t2_bar):
            continue

        picks.append({
            "code": code,
            "zt_date": zt_date,
            "t1_date": t1_date,
            "t2_date": t2_date,
            "entry": t1_open,
            "t1_bar": t1_bar,
            "t2_bar": t2_bar,
            "t_close": t_close,
            "lbc": lbc,
        })
    return picks


# ---------- close_ev (basic + R6 stop) ----------

def close_ev_basic(p: dict) -> float | None:
    """T+1 open 买 → T+2 close 卖. 无 stop, R6 N/A. close_ev 非 open_ev."""
    return (p["t2_bar"]["close"] - p["entry"]) / p["entry"] * 100


def close_ev_stop(p: dict, stop_pct: float = STOP_PCT,
                  realistic: bool = True) -> tuple[float, str] | None:
    """-3% stop + R6 gap-through fill.

    Entry = T+1 open. Stop = entry * (1 - stop_pct).
    T+1 (entry day): if low <= stop → intraday stop (open > stop, so no gap-through).
    T+2 (exit day): if low <= stop:
      - if T+2 open <= stop → gap-through, fill at T+2 open + slippage (R6)
      - else → intraday stop, fill at stop + slippage
    If no stop hit → exit at T+2 close.
    """
    entry = p["entry"]
    stop_px = entry * (1 - stop_pct)
    slip = SLIPPAGE if realistic else 0.0

    t1 = p["t1_bar"]
    t2 = p["t2_bar"]
    t1_low = t1.get("low")
    t2_open = t2.get("open")
    t2_low = t2.get("low")
    t2_close = t2.get("close")
    if None in (t1_low, t2_open, t2_low, t2_close):
        return None

    # T+1 settlement: 不能在入场日当天卖（A股 T+1）。
    # Fix 1 (2026-10-06): T+1 触及 stop 不卖（旧版 return t1_intraday_stop 违 T+1）。
    # Fix 2 (2026-10-06, bug#5): T+1 触及 stop = stop 已触发，T+2 开盘必须卖（first available），
    #   不能"等 T+2 回升看 close"——真实止损触发即执行，不等。旧版 pass 后走 T+2 评估，
    #   若 T+2 low>stop 则 exit at t2_close = leniency（通胀 stop EV +0.36~0.45%）。
    t1_triggered = t1_low is not None and t1_low <= stop_px
    if t1_triggered:
        return (t2_open * (1 - slip) - entry) / entry * 100, "t1_triggered_t2_open_sell"

    if t2_low <= stop_px:
        if t2_open <= stop_px:
            return (t2_open * (1 - slip) - entry) / entry * 100, "t2_gap_stop"
        else:
            return (stop_px * (1 - slip) - entry) / entry * 100, "t2_intraday_stop"

    return (t2_close - entry) / entry * 100, "t2_close"


# ---------- stats ----------

def ev_stats(rets: list[float]) -> dict:
    n = len(rets)
    if n == 0:
        return {"n": 0, "ev": 0.0, "std": 0.0, "t": 0.0,
                "ci_lo": 0.0, "ci_hi": 0.0, "wr": 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    ci_lo = mean - 1.96 * se if se > 0 else mean
    ci_hi = mean + 1.96 * se if se > 0 else mean
    wr = sum(1 for x in rets if x > 0) / n
    return {"n": n, "ev": round(mean, 3), "std": round(std, 3),
            "t": round(t, 2), "ci_lo": round(ci_lo, 3), "ci_hi": round(ci_hi, 3),
            "wr": round(wr * 100, 1)}


def norm_sf_positive(t: float) -> float:
    """One-sided p for POSITIVE edge test: P(Z > t).
    For t<0 (negative mean) returns ~1.0 (no positive edge).
    NB: does NOT use abs(t) — direction matters for one-sided test."""
    return 0.5 * (1 - erf(t / sqrt(2)))


def day_paired_t(rets_by_date: dict[str, list[float]]) -> dict:
    """Per-day-mean t-test: 同日多笔聚成 day-mean, t on day-means.
    effective N = n_days 非 n_trades (避免同日相关夸大 N)."""
    day_means: list[float] = []
    for d, rs in rets_by_date.items():
        if rs:
            day_means.append(sum(rs) / len(rs))
    n = len(day_means)
    if n == 0:
        return {"n_days": 0, "mean": 0.0, "std": 0.0, "t": 0.0, "p_one_sided": 1.0}
    mean = sum(day_means) / n
    std = statistics.pstdev(day_means) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = norm_sf_positive(t)
    return {"n_days": n, "mean": round(mean, 3), "std": round(std, 3),
            "t": round(t, 2), "p_one_sided": round(p, 6)}


def bonferroni_p(p_raw: float, n_tests: int) -> float:
    return min(1.0, p_raw * n_tests)


# ---------- walk-forward ----------

def walk_forward(picks: list[dict], ret_fn: Callable[[dict], float | None]) -> dict:
    """前半 train → 后半 test. 用 zt_date 排序分半. 非 in-sample 分段."""
    if not picks:
        return {"status": "no_picks"}
    ps = sorted(picks, key=lambda p: p["zt_date"])
    dates = sorted(set(p["zt_date"] for p in ps))
    if len(dates) < 4:
        return {"status": "too_few_dates", "n_dates": len(dates)}
    mid = len(dates) // 2
    train_dates = set(dates[:mid])
    test_dates = set(dates[mid:])

    train_picks = [p for p in ps if p["zt_date"] in train_dates]
    test_picks = [p for p in ps if p["zt_date"] in test_dates]

    train_rets = [ret_fn(p) for p in train_picks]
    train_rets = [r for r in train_rets if r is not None]
    test_rets = [ret_fn(p) for p in test_picks]
    test_rets = [r for r in test_rets if r is not None]

    train_by_date: dict[str, list[float]] = defaultdict(list)
    for p in train_picks:
        r = ret_fn(p)
        if r is not None:
            train_by_date[p["zt_date"]].append(r)
    test_by_date: dict[str, list[float]] = defaultdict(list)
    for p in test_picks:
        r = ret_fn(p)
        if r is not None:
            test_by_date[p["zt_date"]].append(r)

    return {
        "status": "ok",
        "n_train": len(train_rets), "n_test": len(test_rets),
        "n_train_dates": len(train_dates), "n_test_dates": len(test_dates),
        "train_ev": ev_stats(train_rets),
        "test_ev": ev_stats(test_rets),
        "train_day_t": day_paired_t(train_by_date),
        "test_day_t": day_paired_t(test_by_date),
    }


# ---------- per-subset analysis ----------

def analyze_subset(name: str, picks: list[dict],
                  ret_fn_basic: Callable[[dict], float | None] = close_ev_basic,
                  ret_fn_stop: Callable[[dict], tuple[float, str] | None] | None = close_ev_stop,
                  ret_fn_label: str = "close_ev") -> dict:
    """对一个子集跑全部分析: basic + stop variant + R6 + walk-forward.

    ret_fn_basic: (p) -> float | None  (basic EV, 默认 close_ev_basic)
    ret_fn_stop:  (p) -> (float, str) | None  (stop variant + exit reason, 默认 close_ev_stop)
    """
    print(f"\n{'=' * 70}")
    print(f"子集: {name} (n_picks={len(picks)})  [ret_fn={ret_fn_label}]")
    print(f"{'=' * 70}")

    if not picks:
        print("  无 picks, 跳过")
        return {"name": name, "n_picks": 0}

    # ---- basic ----
    print(f"\n--- basic {ret_fn_label} (no stop) ---")
    basic_rets = [ret_fn_basic(p) for p in picks]
    basic_rets = [r for r in basic_rets if r is not None]
    basic_s = ev_stats(basic_rets)
    print(f"  n={basic_s['n']} gross_EV={basic_s['ev']}% std={basic_s['std']}% "
          f"WR={basic_s['wr']}% t={basic_s['t']} CI[{basic_s['ci_lo']},{basic_s['ci_hi']}]")
    net_basic = basic_s['ev'] - COST * 100
    print(f"  net EV (after {COST*100:.1f}% cost): {net_basic:.3f}%")

    basic_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        r = ret_fn_basic(p)
        if r is not None:
            basic_by_date[p["zt_date"]].append(r)
    basic_dt = day_paired_t(basic_by_date)
    print(f"  day-paired: n_days={basic_dt['n_days']} mean={basic_dt['mean']}% "
          f"t={basic_dt['t']} p_one_sided={basic_dt['p_one_sided']}")

    # ---- stop variant ----
    stop_s = {"n": 0, "ev": 0.0, "std": 0.0, "t": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "wr": 0.0}
    stop_dt = {"n_days": 0, "mean": 0.0, "std": 0.0, "t": 0.0, "p_one_sided": 1.0}
    stop_reasons: dict[str, int] = defaultdict(int)
    r6_impact = {"ideal_ev": 0.0, "realistic_ev": 0.0, "diff": 0.0, "gap_through": 0}

    if ret_fn_stop is not None:
        print(f"\n--- stop variant (-{STOP_PCT*100:.0f}% stop + R6 gap-through fill) ---")
        stop_rets = [ret_fn_stop(p) for p in picks]
        stop_rets_clean = [r[0] for r in stop_rets if r is not None]
        stop_s = ev_stats(stop_rets_clean)
        print(f"  n={stop_s['n']} gross_EV={stop_s['ev']}% std={stop_s['std']}% "
              f"WR={stop_s['wr']}% t={stop_s['t']} CI[{stop_s['ci_lo']},{stop_s['ci_hi']}]")
        net_stop = stop_s['ev'] - COST * 100
        print(f"  net EV (after cost): {net_stop:.3f}%")

        stop_by_date: dict[str, list[float]] = defaultdict(list)
        for p in picks:
            r = ret_fn_stop(p)
            if r is not None:
                stop_by_date[p["zt_date"]].append(r[0])
        stop_dt = day_paired_t(stop_by_date)
        print(f"  day-paired: n_days={stop_dt['n_days']} mean={stop_dt['mean']}% "
              f"t={stop_dt['t']} p_one_sided={stop_dt['p_one_sided']}")

        for p in picks:
            r = ret_fn_stop(p)
            if r is not None:
                stop_reasons[r[1]] += 1
        total_r = sum(stop_reasons.values())
        print(f"  exit reasons:")
        for rsn, cnt in sorted(stop_reasons.items(), key=lambda x: -x[1]):
            print(f"    {rsn}: {cnt} ({cnt/max(total_r,1)*100:.1f}%)")

        # R6 impact
        print(f"\n--- R6 fill impact (ideal vs realistic stop) ---")
        ideal_rets = [ret_fn_stop(p, realistic=False) for p in picks]  # type: ignore[misc]
        ideal_rets_clean = [r[0] for r in ideal_rets if r is not None]
        si = ev_stats(ideal_rets_clean)
        sr = stop_s
        gap_count = stop_reasons.get("t2_gap_stop", 0)
        stop_count = sum(v for k, v in stop_reasons.items() if "stop" in k)
        r6_impact = {"ideal_ev": si['ev'], "realistic_ev": sr['ev'],
                     "diff": round(si['ev']-sr['ev'], 3),
                     "gap_through": gap_count}
        print(f"  ideal EV={si['ev']}% | realistic EV={sr['ev']}% | "
              f"diff={round(si['ev']-sr['ev'],3)}% | "
              f"stops={stop_count}({stop_count/max(len(stop_rets_clean),1)*100:.1f}%) "
              f"gap_through={gap_count}({gap_count/max(stop_count,1)*100:.1f}% of stops)")

    # ---- walk-forward ----
    print(f"\n--- walk-forward OOS (basic, 前半 train → 后半 test) ---")
    wf_basic = walk_forward(picks, ret_fn_basic)
    if wf_basic["status"] == "ok":
        tr = wf_basic["train_ev"]
        te = wf_basic["test_ev"]
        tr_dt = wf_basic["train_day_t"]
        te_dt = wf_basic["test_day_t"]
        print(f"  train: n={tr['n']} n_dates={wf_basic['n_train_dates']} "
              f"EV={tr['ev']}% t={tr['t']} day_t={tr_dt['t']}")
        print(f"  test:  n={te['n']} n_dates={wf_basic['n_test_dates']} "
              f"EV={te['ev']}% t={te['t']} day_t={te_dt['t']} "
              f"p={te_dt['p_one_sided']}")
        decay = ((tr['ev'] - te['ev']) / abs(tr['ev']) * 100
                 if tr['ev'] != 0 else 0)
        print(f"  decay: {decay:.0f}% (train→test)")
    else:
        print(f"  {wf_basic['status']} (n_dates={wf_basic.get('n_dates', 0)})")

    return {
        "name": name,
        "n_picks": len(picks),
        "basic_ev": basic_s,
        "basic_day_t": basic_dt,
        "stop_ev": stop_s,
        "stop_day_t": stop_dt,
        "r6_impact": r6_impact,
        "wf_basic": wf_basic,
    }


# ---------- honest verdict (parameterized cross-factor Bonferroni) ----------

def verdict_for(
    ev_gross: float,
    t_day: float,
    p_raw: float,
    wf_status: str,
    wf_train_ev: float,
    wf_test_ev: float,
    wf_test_p: float,
    n_days: int,
    net_ev: float,
    subset_name: str,
    n_cross_factor: int = 1,
) -> str:
    """诚实判定: edge-confirmed / falsified / underpowered / exploratory.

    n_cross_factor: 并行测试的因子数 (cross-factor Bonferroni ×n_cross_factor×2_subsets).
    单因子脚本 standalone 用 n_cross_factor=1 (×2 subsets).
    多因子 sweep 用 n_cross_factor=N (×N*2 subsets).

    判定级联 (过严口径):
    1. gross EV < 0 → falsified (loser signal)
    2. n_days < 60 → underpowered
    3. Bonferroni p (cross-factor ×N*2) >= 0.05 → falsified
    4. net EV <= 0 → falsified (gross edge eaten by cost)
    5. walk-forward test EV <= 0 → falsified
    6. walk-forward test p >= 0.05 → exploratory (OOS not significant)
    7. all pass → edge-confirmed
    """
    n_tests = max(2, n_cross_factor * 2)
    p_bonf = bonferroni_p(p_raw, n_tests)

    print(f"\n  {subset_name}:")
    print(f"    gross_EV={ev_gross}% net_EV={net_ev}% day_t={t_day} "
          f"Bonf_p(×{n_tests})={p_bonf:.6f} n_days={n_days}")
    if wf_status == "ok":
        print(f"    walk-forward: train_EV={wf_train_ev}% test_EV={wf_test_ev}% "
              f"test_p={wf_test_p}")

    if ev_gross < 0:
        print(f"    → FALSIFIED: gross EV < 0 (negative edge, loser signal)")
        return "falsified"
    if n_days < 60:
        print(f"    → UNDERPOWERED: n_days={n_days} < 60")
        return "underpowered"
    if p_bonf >= ALPHA:
        print(f"    → FALSIFIED: Bonferroni p={p_bonf} >= {ALPHA} (not significant)")
        return "falsified"
    if net_ev <= 0:
        print(f"    → FALSIFIED: net EV={net_ev}% <= 0 (gross edge eaten by cost)")
        return "falsified"
    if wf_status == "ok":
        # Fix 2026-10-06: train_ev>0 检查——train 半无 edge 而 test 半有 = regime 过拟合
        if wf_train_ev <= 0:
            print(f"    → EXPLORATORY: train_EV={wf_train_ev}% <= 0 (edge not in train half, "
                  f"test_EV={wf_test_ev}% may be regime overfitting)")
            return "exploratory"
        if wf_test_ev <= 0:
            print(f"    → FALSIFIED: walk-forward test_EV={wf_test_ev}% <= 0")
            return "falsified"
        # Fix 2026-10-06: OOS test_p 也施 Bonferroni（与 step3 一致，旧版用 raw test_p = leniency）
        wf_test_p_bonf = bonferroni_p(wf_test_p, n_tests)
        if wf_test_p_bonf >= ALPHA:
            print(f"    → EXPLORATORY: OOS test EV={wf_test_ev}% > 0 but "
                  f"test p={wf_test_p} Bonf×{n_tests}={wf_test_p_bonf} >= {ALPHA} (not significant OOS)")
            return "exploratory"
        print(f"    → EDGE-CONFIRMED: gross+net EV > 0, Bonferroni PASS, "
              f"OOS test EV={wf_test_ev}% significant (p={wf_test_p}, Bonf×{n_tests}={wf_test_p_bonf})")
        return "edge-confirmed"
    print(f"    → EXPLORATORY: walk-forward not available")
    return "exploratory"
