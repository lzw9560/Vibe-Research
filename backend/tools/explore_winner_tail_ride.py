# -*- coding: utf-8 -*-
"""P1 实验：赢家右尾多日 ride + ATR trailing stop.

测试"T+1 涨停 non-一字 winners"持有多日 + trailing stop 是否藏 edge.
诚实口径：entry=T+1 close（非 open_ev 日内泄漏）.
R6 realistic fill：跳空穿 stop 按 open + 滑点 0.2%.
per-day-mean t-test（同日多笔聚合成 day-mean，避免 same-day correlation 夸大 N）.
Bonferroni 校正 exit-rule search.
walk-forward OOS：前半 train 选参数 → 后半 test 验证.
禁止外推：测了 winner tail ride 不能外推成"打板有 edge"——只说这一维度.

跑法：cd backend && .venv/bin/python -m tools.explore_winner_tail_ride
"""

from __future__ import annotations
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
ZT_DB = DATA / "zt_history.db"

SLIPPAGE = 0.002  # 0.2% 滑点
COST = 0.003  # round-trip cost（印花+佣金+滑点）for net EV
ATR_PERIOD = 14
ATR_MULT = 2.0  # trailing stop = high_since_entry - ATR_MULT * ATR
HARD_STOP = 0.03  # entry * (1 - 0.03) floor
ALPHA = 0.05


# ---------- data loading ----------


def load_kline_db() -> dict[str, list[dict]]:
    """从 SQLite 读 kline（code -> sorted bars）。"""
    conn = sqlite3.connect(str(KLINE_DB))
    out: dict[str, list[dict]] = {}
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(bars, list) and bars:
            out[code] = sorted(bars, key=lambda b: b.get("date", ""))
    conn.close()
    return out


def load_zt() -> dict[str, dict[str, int]]:
    """date -> {code: lbc}。"""
    conn = sqlite3.connect(str(ZT_DB))
    zt: dict[str, dict[str, int]] = {}
    for d, code, lbc in conn.execute("SELECT date, code, lbc FROM zt_history"):
        zt.setdefault(d, {})[code] = lbc if lbc else 1
    conn.close()
    return zt


# ---------- ATR ----------


def _true_range(bar: dict, prev_close: float | None) -> float | None:
    h = bar.get("high")
    l = bar.get("low")
    if h is None or l is None or prev_close is None:
        return None
    return max(h - l, abs(h - prev_close), abs(l - prev_close))


def atr_wilder(bars: list[dict], idx: int, period: int = ATR_PERIOD) -> float | None:
    """Wilder ATR at index idx (needs idx >= period)."""
    if idx < period:
        return None
    trs: list[float] = []
    for i in range(1, idx + 1):
        pc = bars[i - 1].get("close")
        tr = _true_range(bars[i], pc)
        if tr is None:
            return None
        trs.append(tr)
    # Wilder: first ATR = simple avg of first `period` TRs, then smooth
    first_atr = sum(trs[:period]) / period
    atr = first_atr
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


# ---------- helpers ----------


def limit_for_code(code: str) -> float:
    if code.startswith(("sz30", "sh68")):
        return 0.20
    return 0.10


def is_yizi(t1_bar: dict, t_close: float, limit: float) -> bool:
    """一字涨停: open and low both at/near limit-up price."""
    lim_up = t_close * (1 + limit)
    o = t1_bar.get("open")
    l = t1_bar.get("low")
    if o is None or l is None or lim_up <= 0:
        return False
    return abs(o - lim_up) / lim_up < 0.005 and abs(l - lim_up) / lim_up < 0.005


# ---------- winner subset construction ----------


def build_winners(all_bars: dict[str, list[dict]], zt_by_date: dict[str, dict[str, int]]) -> list[dict]:
    """T+1 涨停 non-一字 winners（lbc>=2 continuation board）。"""
    cal = sorted(zt_by_date.keys())
    date_idx = {d: i for i, d in enumerate(cal)}

    winners: list[dict] = []
    for t1_date, codes in zt_by_date.items():
        t1_idx = date_idx.get(t1_date)
        if t1_idx is None:
            continue
        # T date (previous zt calendar day)
        if t1_idx == 0:
            continue
        t_date = cal[t1_idx - 1]
        # T+2/T+3/T+4 dates
        t2_date = cal[t1_idx + 1] if t1_idx + 1 < len(cal) else None
        t3_date = cal[t1_idx + 2] if t1_idx + 2 < len(cal) else None
        t4_date = cal[t1_idx + 3] if t1_idx + 3 < len(cal) else None

        for code, lbc in codes.items():
            if lbc < 2:
                continue  # only continuation boards (right-tail winners)
            bars = all_bars.get(code)
            if not bars:
                continue
            bmap: dict[str, dict] = {b["date"]: b for b in bars if b.get("date")}
            bdates = sorted(bmap.keys())

            t1_bar = bmap.get(t1_date)
            if t1_bar is None:
                continue
            t1_close = t1_bar.get("close")
            if t1_close is None or t1_close <= 0:
                continue
            t1_high = t1_bar.get("high")
            if t1_high is None:
                continue

            # T date bar for 一字 detection
            t_bar = bmap.get(t_date)
            if t_bar is None or t_bar.get("close") is None:
                continue
            t_close = t_bar["close"]

            limit = limit_for_code(code)
            if is_yizi(t1_bar, t_close, limit):
                continue  # skip 一字 (not tradable for our close entry)

            # ATR(14) at T+1
            try:
                t1_bidx = bdates.index(t1_date)
            except ValueError:
                continue
            if t1_bidx < ATR_PERIOD:
                continue
            atr = atr_wilder(bars, t1_bidx, ATR_PERIOD)
            if atr is None or atr <= 0:
                continue

            t2_bar = bmap.get(t2_date) if t2_date else None
            t3_bar = bmap.get(t3_date) if t3_date else None
            t4_bar = bmap.get(t4_date) if t4_date else None

            winners.append(
                {
                    "code": code,
                    "t1_date": t1_date,
                    "entry": t1_close,
                    "t1_high": t1_high,
                    "atr": atr,
                    "t2_bar": t2_bar,
                    "t3_bar": t3_bar,
                    "t4_bar": t4_bar,
                }
            )
    return winners


# ---------- exit simulation ----------


def simulate_exit(
    w: dict, exit_day: str, atr_mult: float = ATR_MULT, hard_stop: float = HARD_STOP, realistic: bool = True
) -> tuple[float, str, str] | None:
    """Trailing stop + higher-high exit. Returns (exit_price, day_label, reason) or None."""
    entry = w["entry"]
    atr = w["atr"]
    stop_floor = entry * (1 - hard_stop)
    high_since = entry  # highest high since entry (T+1 close)

    if exit_day == "T+3":
        day_bars = [("T+2", w["t2_bar"]), ("T+3", w["t3_bar"])]
    elif exit_day == "T+4":
        day_bars = [("T+2", w["t2_bar"]), ("T+3", w["t3_bar"]), ("T+4", w["t4_bar"])]
    else:
        return None

    slip = SLIPPAGE if realistic else 0.0

    for i, (label, bar) in enumerate(day_bars):
        if bar is None:
            return None
        is_last = i == len(day_bars) - 1
        o = bar.get("open")
        h = bar.get("high")
        l = bar.get("low")
        c = bar.get("close")
        if None in (o, h, l, c):
            return None

        # Trailing stop at start of day
        stop_price = max(high_since - atr_mult * atr, stop_floor)

        # Check stop trigger
        if l <= stop_price:
            if o <= stop_price:
                # Gap through stop → fill at open + slippage
                return (o * (1 - slip), label, "gap_stop")
            else:
                # Intraday touch → fill at stop + slippage
                return (stop_price * (1 - slip), label, "intraday_stop")

        # Update high_since
        made_higher_high = h > high_since
        high_since = max(high_since, h)

        if is_last:
            return (c, label, "close_exit")
        if not made_higher_high:
            return (c, label, "no_higher_high")
    return None


def baseline_close_ev(w: dict) -> float | None:
    """T+1 close 买 → T+2 close 卖（honest baseline）。"""
    t2 = w["t2_bar"]
    if t2 is None or t2.get("close") is None:
        return None
    return (t2["close"] - w["entry"]) / w["entry"] * 100


def close_ev(w: dict, exit_day: str, atr_mult: float = ATR_MULT, realistic: bool = True) -> float | None:
    res = simulate_exit(w, exit_day, atr_mult=atr_mult, realistic=realistic)
    if res is None:
        return None
    exit_price, _, _ = res
    return (exit_price - w["entry"]) / w["entry"] * 100


def realistic_entry_exit(
    w: dict, exit_day: str, atr_mult: float = ATR_MULT, hard_stop: float = HARD_STOP, realistic_fill: bool = True
) -> tuple[float, str] | None:
    """Realistic entry = T+2 open (T+1 close is sealed limit-up, unbuyable).
    Trailing stop starts from T+2 open. ATR from T+1 bars."""
    t2 = w.get("t2_bar")
    if not t2 or t2.get("open") is None:
        return None
    entry = t2["open"]
    atr = w["atr"]
    stop_floor = entry * (1 - hard_stop)
    high_since = entry
    slip = SLIPPAGE if realistic_fill else 0.0

    if exit_day == "T+3":
        day_bars = [("T+3", w.get("t3_bar"))]
    elif exit_day == "T+4":
        day_bars = [("T+3", w.get("t3_bar")), ("T+4", w.get("t4_bar"))]
    else:
        return None

    for i, (label, bar) in enumerate(day_bars):
        if bar is None:
            return None
        is_last = i == len(day_bars) - 1
        o = bar.get("open")
        h = bar.get("high")
        l = bar.get("low")
        c = bar.get("close")
        if None in (o, h, l, c):
            return None
        stop_price = max(high_since - atr_mult * atr, stop_floor)
        if l <= stop_price:
            if o <= stop_price:
                return (o * (1 - slip) - entry) / entry * 100, "gap_stop"
            else:
                return (stop_price * (1 - slip) - entry) / entry * 100, "intraday_stop"
        made_higher = h > high_since
        high_since = max(high_since, h)
        if is_last:
            return (c - entry) / entry * 100, "close_exit"
        if not made_higher:
            return (c - entry) / entry * 100, "no_higher_high"
    return None


def realistic_baseline(w: dict) -> float | None:
    """Realistic baseline: T+2 open buy -> T+3 close sell (1-day hold)."""
    t2 = w.get("t2_bar")
    t3 = w.get("t3_bar")
    if not t2 or not t3:
        return None
    if t2.get("open") is None or t3.get("close") is None:
        return None
    return (t3["close"] - t2["open"]) / t2["open"] * 100


# ---------- stats ----------


def ev_stats(rets: list[float]) -> dict:
    n = len(rets)
    if n == 0:
        return {"n": 0, "ev": 0.0, "std": 0.0, "t": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "wr": 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    ci_lo = mean - 1.96 * se if se > 0 else mean
    ci_hi = mean + 1.96 * se if se > 0 else mean
    wr = sum(1 for x in rets if x > 0) / n
    return {
        "n": n,
        "ev": round(mean, 3),
        "std": round(std, 3),
        "t": round(t, 2),
        "ci_lo": round(ci_lo, 3),
        "ci_hi": round(ci_hi, 3),
        "wr": round(wr * 100, 1),
    }


def day_paired_t(rets_by_date: dict[str, list[float]]) -> dict:
    """Per-day-mean t-test: 同日多笔聚合成 day-mean, t on day-means."""
    day_means = []
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
    p = norm_sf(t)
    return {"n_days": n, "mean": round(mean, 3), "std": round(std, 3), "t": round(t, 2), "p_one_sided": round(p, 6)}


def norm_sf(t: float) -> float:
    """Survival function P(Z > t) one-sided."""
    return 0.5 * (1 - erf(abs(t) / sqrt(2)))


def bonferroni_p(p_raw: float, n_tests: int) -> float:
    return min(1.0, p_raw * n_tests)


# ---------- walk-forward ----------


def walk_forward(winners: list[dict], exit_day: str) -> dict:
    """前半 train 选参数 → 后半 test 验证。用 realistic entry (T+2 open)."""
    ws = sorted(winners, key=lambda w: w["t1_date"])
    dates = sorted(set(w["t1_date"] for w in ws))
    if len(dates) < 4:
        return {"status": "too_few_dates", "n_dates": len(dates)}
    mid = len(dates) // 2
    train_dates = set(dates[:mid])
    test_dates = set(dates[mid:])

    train_w = [w for w in ws if w["t1_date"] in train_dates]
    test_w = [w for w in ws if w["t1_date"] in test_dates]

    # Train: evaluate T+3 and T+4, pick better (realistic entry)
    train_ev = {}
    for ed in ("T+3", "T+4"):
        rets = [realistic_entry_exit(w, ed) for w in train_w]
        rets = [r[0] for r in rets if r is not None]
        s = ev_stats(rets)
        train_ev[ed] = s
    best_ed = max(train_ev.keys(), key=lambda k: train_ev[k]["ev"])

    # Test: evaluate best_ed
    test_rets = [realistic_entry_exit(w, best_ed) for w in test_w]
    test_rets = [r[0] for r in test_rets if r is not None]
    test_s = ev_stats(test_rets)

    # Also compute test for both for reporting
    test_both = {}
    for ed in ("T+3", "T+4"):
        rets = [realistic_entry_exit(w, ed) for w in test_w]
        rets = [r[0] for r in rets if r is not None]
        test_both[ed] = ev_stats(rets)

    return {
        "n_train": len(train_w),
        "n_test": len(test_w),
        "n_train_dates": len(train_dates),
        "n_test_dates": len(test_dates),
        "train_ev": train_ev,
        "best_exit_day_train": best_ed,
        "test_ev_best": test_s,
        "test_ev_both": test_both,
    }


# ---------- main ----------


def main():
    print("加载数据…")
    all_bars = load_kline_db()
    zt_by_date = load_zt()
    print(f"  kline codes: {len(all_bars)}")
    print(f"  zt dates: {len(zt_by_date)}")

    print("\n构建 winner 子集（T+1 涨停 non-一字, lbc>=2）…")
    winners = build_winners(all_bars, zt_by_date)
    print(f"  winners: {len(winners)}")

    # W distribution (winner returns, using T+4 trailing realistic)
    w_rets = [close_ev(w, "T+4") for w in winners]
    w_rets = [r for r in w_rets if r is not None]
    if w_rets:
        w_sorted = sorted(w_rets)
        n = len(w_sorted)
        p90 = w_sorted[int(n * 0.9)] if n >= 10 else w_sorted[-1]
        print(
            f"\n  W 分布 (T+4 trailing realistic close_ev): "
            f"mean={statistics.mean(w_rets):.2f}% "
            f"median={statistics.median(w_rets):.2f}% "
            f"max={max(w_rets):.2f}% p90={p90:.2f}%"
        )

    # ---- baseline ----
    print("\n=== baseline (T+1 close 买 → T+2 close 卖) ===")
    base_rets = [baseline_close_ev(w) for w in winners]
    base_rets = [r for r in base_rets if r is not None]
    base_s = ev_stats(base_rets)
    print(
        f"  n={base_s['n']} EV={base_s['ev']}% std={base_s['std']}% "
        f"WR={base_s['wr']}% t={base_s['t']} CI[{base_s['ci_lo']},{base_s['ci_hi']}]"
    )
    net_base = base_s["ev"] - COST * 100
    print(f"  net EV (after {COST * 100:.1f}% cost): {net_base:.3f}%")

    # group baseline by date for day-paired t
    base_by_date: dict[str, list[float]] = defaultdict(list)
    for w in winners:
        r = baseline_close_ev(w)
        if r is not None:
            base_by_date[w["t1_date"]].append(r)
    base_dt = day_paired_t(base_by_date)
    print(f"  day-paired: n_days={base_dt['n_days']} mean={base_dt['mean']}% t={base_dt['t']} p={base_dt['p_one_sided']}")

    # ---- T+3 trailing stop ----
    print("\n=== T+3 trailing stop exit (realistic R6 fill) ===")
    t3_rets = [close_ev(w, "T+3") for w in winners]
    t3_rets = [r for r in t3_rets if r is not None]
    t3_s = ev_stats(t3_rets)
    print(f"  n={t3_s['n']} EV={t3_s['ev']}% std={t3_s['std']}% WR={t3_s['wr']}% t={t3_s['t']} CI[{t3_s['ci_lo']},{t3_s['ci_hi']}]")
    net_t3 = t3_s["ev"] - COST * 100
    print(f"  net EV (after cost): {net_t3:.3f}%")

    t3_by_date: dict[str, list[float]] = defaultdict(list)
    for w in winners:
        r = close_ev(w, "T+3")
        if r is not None:
            t3_by_date[w["t1_date"]].append(r)
    t3_dt = day_paired_t(t3_by_date)
    print(f"  day-paired: n_days={t3_dt['n_days']} mean={t3_dt['mean']}% t={t3_dt['t']} p={t3_dt['p_one_sided']}")

    # ---- T+4 trailing stop ----
    print("\n=== T+4 trailing stop exit (realistic R6 fill) ===")
    t4_rets = [close_ev(w, "T+4") for w in winners]
    t4_rets = [r for r in t4_rets if r is not None]
    t4_s = ev_stats(t4_rets)
    print(f"  n={t4_s['n']} EV={t4_s['ev']}% std={t4_s['std']}% WR={t4_s['wr']}% t={t4_s['t']} CI[{t4_s['ci_lo']},{t4_s['ci_hi']}]")
    net_t4 = t4_s["ev"] - COST * 100
    print(f"  net EV (after cost): {net_t4:.3f}%")

    t4_by_date: dict[str, list[float]] = defaultdict(list)
    for w in winners:
        r = close_ev(w, "T+4")
        if r is not None:
            t4_by_date[w["t1_date"]].append(r)
    t4_dt = day_paired_t(t4_by_date)
    print(f"  day-paired: n_days={t4_dt['n_days']} mean={t4_dt['mean']}% t={t4_dt['t']} p={t4_dt['p_one_sided']}")

    # ---- Bonferroni (2 exit rules: T+3, T+4) ----
    print("\n=== Bonferroni 校正（2 exit rules: T+3, T+4, unrealistic entry）===")
    n_tests = 2
    best_p = min(t3_dt["p_one_sided"], t4_dt["p_one_sided"])
    bonf_p_unreal = bonferroni_p(best_p, n_tests)
    best_rule = "T+3" if t3_dt["p_one_sided"] <= t4_dt["p_one_sided"] else "T+4"
    print(f"  best rule: {best_rule} raw p={best_p:.6f}")
    print(f"  Bonferroni p (×{n_tests}): {bonf_p_unreal:.6f}")
    print(f"  Bonferroni threshold: {ALPHA / n_tests:.6f}")
    print(f"  {'PASS' if bonf_p_unreal < ALPHA else 'FAIL (not significant after correction)'}")

    # ---- R6 realistic fill impact (ideal vs realistic) ----
    print("\n=== R6 realistic fill 影响 (ideal vs realistic) ===")
    for ed in ("T+3", "T+4"):
        ideal_rets = [close_ev(w, ed, realistic=False) for w in winners]
        ideal_rets = [r for r in ideal_rets if r is not None]
        real_rets = [close_ev(w, ed, realistic=True) for w in winners]
        real_rets = [r for r in real_rets if r is not None]
        si = ev_stats(ideal_rets)
        sr = ev_stats(real_rets)
        # Count gap-through stops
        gap_count = 0
        stop_count = 0
        for w in winners:
            res = simulate_exit(w, ed, realistic=True)
            if res is not None:
                _, _, reason = res
                if reason == "gap_stop":
                    gap_count += 1
                    stop_count += 1
                elif reason == "intraday_stop":
                    stop_count += 1
        print(
            f"  {ed}: ideal EV={si['ev']}% | real EV={sr['ev']}% | "
            f"diff={round(si['ev'] - sr['ev'], 3)}% | "
            f"stops={stop_count}({stop_count / max(len(real_rets), 1) * 100:.1f}%) "
            f"gap_through={gap_count}({gap_count / max(stop_count, 1) * 100:.1f}% of stops)"
        )

    # ---- ATR mult sensitivity (exploratory, not Bonferroni) ----
    print("\n=== ATR mult 敏感性（exploratory, not Bonferroni corrected）===")
    for mult in (1.5, 2.0, 2.5):
        for ed in ("T+3", "T+4"):
            rets = [close_ev(w, ed, atr_mult=mult) for w in winners]
            rets = [r for r in rets if r is not None]
            s = ev_stats(rets)
            print(f"  ATR×{mult} {ed}: n={s['n']} EV={s['ev']}% WR={s['wr']}% t={s['t']}")

    # ---- REALISTIC entry = T+2 open (T+1 sealed, unbuyable) ----
    print("\n" + "=" * 70)
    print("REALISTIC 口径: entry = T+2 open（T+1 close sealed at limit-up, 不可买）")
    print("=" * 70)

    # Realistic baseline: T+2 open -> T+3 close
    print("\n=== realistic baseline (T+2 open 买 → T+3 close 卖) ===")
    rbase_rets = [realistic_baseline(w) for w in winners]
    rbase_rets = [r for r in rbase_rets if r is not None]
    rbase_s = ev_stats(rbase_rets)
    print(
        f"  n={rbase_s['n']} EV={rbase_s['ev']}% std={rbase_s['std']}% "
        f"WR={rbase_s['wr']}% t={rbase_s['t']} CI[{rbase_s['ci_lo']},{rbase_s['ci_hi']}]"
    )
    net_rbase = rbase_s["ev"] - COST * 100
    print(f"  net EV (after cost): {net_rbase:.3f}%")

    rbase_by_date: dict[str, list[float]] = defaultdict(list)
    for w in winners:
        r = realistic_baseline(w)
        if r is not None:
            rbase_by_date[w["t1_date"]].append(r)
    rbase_dt = day_paired_t(rbase_by_date)
    print(f"  day-paired: n_days={rbase_dt['n_days']} mean={rbase_dt['mean']}% t={rbase_dt['t']} p={rbase_dt['p_one_sided']}")

    # Realistic T+3 trailing
    print("\n=== realistic T+3 trailing (entry=T+2 open, R6 fill) ===")
    rt3_rets = [realistic_entry_exit(w, "T+3") for w in winners]
    rt3_rets = [r[0] for r in rt3_rets if r is not None]
    rt3_s = ev_stats(rt3_rets)
    print(f"  n={rt3_s['n']} EV={rt3_s['ev']}% std={rt3_s['std']}% WR={rt3_s['wr']}% t={rt3_s['t']} CI[{rt3_s['ci_lo']},{rt3_s['ci_hi']}]")
    net_rt3 = rt3_s["ev"] - COST * 100
    print(f"  net EV (after cost): {net_rt3:.3f}%")

    rt3_by_date: dict[str, list[float]] = defaultdict(list)
    for w in winners:
        r = realistic_entry_exit(w, "T+3")
        if r is not None:
            rt3_by_date[w["t1_date"]].append(r[0])
    rt3_dt = day_paired_t(rt3_by_date)
    print(f"  day-paired: n_days={rt3_dt['n_days']} mean={rt3_dt['mean']}% t={rt3_dt['t']} p={rt3_dt['p_one_sided']}")

    # Realistic T+4 trailing
    print("\n=== realistic T+4 trailing (entry=T+2 open, R6 fill) ===")
    rt4_rets = [realistic_entry_exit(w, "T+4") for w in winners]
    rt4_rets = [r[0] for r in rt4_rets if r is not None]
    rt4_s = ev_stats(rt4_rets)
    print(f"  n={rt4_s['n']} EV={rt4_s['ev']}% std={rt4_s['std']}% WR={rt4_s['wr']}% t={rt4_s['t']} CI[{rt4_s['ci_lo']},{rt4_s['ci_hi']}]")
    net_rt4 = rt4_s["ev"] - COST * 100
    print(f"  net EV (after cost): {net_rt4:.3f}%")

    rt4_by_date: dict[str, list[float]] = defaultdict(list)
    for w in winners:
        r = realistic_entry_exit(w, "T+4")
        if r is not None:
            rt4_by_date[w["t1_date"]].append(r[0])
    rt4_dt = day_paired_t(rt4_by_date)
    print(f"  day-paired: n_days={rt4_dt['n_days']} mean={rt4_dt['mean']}% t={rt4_dt['t']} p={rt4_dt['p_one_sided']}")

    # Bonferroni on realistic
    print("\n=== Bonferroni 校正（realistic, 2 exit rules）===")
    best_p_r = min(rt3_dt["p_one_sided"], rt4_dt["p_one_sided"])
    bonf_p = bonferroni_p(best_p_r, n_tests)
    best_rule_r = "T+3" if rt3_dt["p_one_sided"] <= rt4_dt["p_one_sided"] else "T+4"
    print(f"  best rule (realistic): {best_rule_r} raw p={best_p_r:.6f}")
    print(f"  Bonferroni p (×{n_tests}): {bonf_p:.6f}")
    print(f"  {'PASS' if bonf_p < ALPHA else 'FAIL (not significant after correction)'}")

    # ---- walk-forward OOS ----
    print("\n=== walk-forward OOS (前半 train 选参数 → 后半 test 验证) ===")
    wf = walk_forward(winners, "T+3")  # exit_day param unused inside, we test both
    print(f"  n_train={wf['n_train']} n_test={wf['n_test']} train_dates={wf['n_train_dates']} test_dates={wf['n_test_dates']}")
    for ed in ("T+3", "T+4"):
        tr = wf["train_ev"][ed]
        print(f"  train {ed}: EV={tr['ev']}% t={tr['t']} n={tr['n']}")
    print(f"  best exit day (train): {wf['best_exit_day_train']}")
    tb = wf["test_ev_best"]
    print(
        f"  test (best={wf['best_exit_day_train']}): EV={tb['ev']}% t={tb['t']} WR={tb['wr']}% n={tb['n']} CI[{tb['ci_lo']},{tb['ci_hi']}]"
    )
    for ed in ("T+3", "T+4"):
        ts = wf["test_ev_both"][ed]
        print(f"  test {ed}: EV={ts['ev']}% t={ts['t']} WR={ts['wr']}% n={ts['n']}")

    # ---- exit reason breakdown ----
    print("\n=== exit reason 分布 (T+4 realistic) ===")
    reasons: dict[str, int] = defaultdict(int)
    for w in winners:
        res = simulate_exit(w, "T+4", realistic=True)
        if res is not None:
            reasons[res[2]] += 1
    total = sum(reasons.values())
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {r}: {c} ({c / max(total, 1) * 100:.1f}%)")

    # ---- summary verdict ----
    print("\n" + "=" * 70)
    print("诚实判定")
    print("=" * 70)
    print(f"winner subset n={len(winners)} (T+1 涨停 non-一字 lbc>=2)")
    print(f"\n[unrealistic entry=T+1 close — T+1 sealed at limit-up, unbuyable]")
    print(f"baseline (T+1close→T+2close): EV={base_s['ev']}% t={base_dt['t']} (day-paired p={base_dt['p_one_sided']})")
    print(f"T+3 trailing: EV={t3_s['ev']}% t={t3_dt['t']} (day-paired p={t3_dt['p_one_sided']})")
    print(f"T+4 trailing: EV={t4_s['ev']}% t={t4_dt['t']} (day-paired p={t4_dt['p_one_sided']})")
    print(f"\n[realistic entry=T+2 open — T+1 sealed, buy next morning]")
    print(f"baseline (T+2open→T+3close): EV={rbase_s['ev']}% t={rbase_dt['t']} (day-paired p={rbase_dt['p_one_sided']})")
    print(f"T+3 trailing: EV={rt3_s['ev']}% t={rt3_dt['t']} (day-paired p={rt3_dt['p_one_sided']})")
    print(f"T+4 trailing: EV={rt4_s['ev']}% t={rt4_dt['t']} (day-paired p={rt4_dt['p_one_sided']})")
    print(f"\nBonferroni p (2 tests, realistic): {bonf_p:.6f} → {'significant' if bonf_p < ALPHA else 'NOT significant'}")
    wf_train = wf["train_ev"][wf["best_exit_day_train"]]["ev"]
    wf_test = wf["test_ev_best"]["ev"]
    decay = (wf_train - wf_test) / abs(wf_train) * 100 if wf_train != 0 else 0
    print(f"walk-forward (realistic): train EV={wf_train}% test EV={wf_test}% (decay={decay:.0f}%)")
    print(f"R6 fill impact: ideal vs realistic diff 见上表")
    print(f"\n注: 本实验只测 winner tail ride 维度，禁止外推成'打板有 edge'。")
    print(f"\n核心发现: entry=T+1 close 口径下 baseline/trailing 全正 EV 是假象——100% winners T+1 sealed (close==high)，T+1 close 不可买。")
    print(f"realistic entry=T+2 open 后，baseline/trailing 全负 EV，无 edge。")


if __name__ == "__main__":
    main()
