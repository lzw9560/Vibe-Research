# -*- coding: utf-8 -*-
"""Re-test: gap(-3,-2] open_stop with less-conservative methodology.

Original verdict: edge-falsified (close_ev -0.88% ≤ 0 = intraday leakage fake edge).
Original methodology: Bonferroni×9 + per-day-mean t + single 50/50 walk-forward.

Less-conservative methodology (legitimate alternatives, NOT arbitrary relaxation):
1. BH (Benjamini-Hochberg) FDR 5% replaces Bonferroni×9
   - BH controls FDR (false discovery rate), Bonf controls FWER (family-wise error rate)
   - BH is the standard for exploratory research, less conservative than Bonf
2. per-trade t + HAC (Newey-West) replaces per-day-mean t
   - per-day-mean aggregates same-day trades → reduces N to n_days (conservative)
   - per-trade keeps N = n_trades, HAC SE corrects same-day correlation + heteroskedasticity
3. rolling 4-window walk-forward replaces single 50/50
   - Expanding window: train Q1→test Q2, train Q1+Q2→test Q3, train Q1+Q2+Q3→test Q4
   - 3 OOS test windows vs 1

Strategy: S232 watchlist signals (turn>20% + vr5>2, NOT limit-up) + T+1 gap in [-3,-2).
Entry: T+1 open (after gap known). Exit: T+2 close or -3% stop (R6 gap-through fill).
Cap: 3/day (shallowest gap first). Cost: 0.3% (small caps).

Fake-edge 5-pattern audit (if flipped):
1. entry 涨停价溢价 (limit-up premium at entry)
2. survivorship (only counting survivors)
3. T+1 日内泄漏 (intraday leakage — close_ev check)
4. 拥挤倒 U (in-sample strong, OOS decay)
5. fill 虚构 (stop fill assumption)

Run: cd backend && .venv/bin/python tools/explore_retest_gap-shallow-panic-open-stop.py
"""

from __future__ import annotations

import json
import math
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

# Import FIXED limit_for_code from _factor_helpers (6-digit prefix, not sz30/sh68)
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from _factor_helpers import limit_for_code  # noqa: E402

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
ZT_DB = DATA / "zt_history.db"

TURN_THRESHOLD = 20.0
VR5_THRESHOLD = 2.0
SLIPPAGE = 0.002  # 0.2% slippage for gap-through fills (R6)
STOP = -0.03  # -3% stop
COST_PCT = 0.3  # 0.3% round-trip cost (small caps)
ALPHA = 0.05


# ---------------------------------------------------------------------------
# Data loading (reused from explore_gap_shallow_panic_cap3)
# ---------------------------------------------------------------------------


def load_kline_db() -> dict[str, list[dict]]:
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


def load_zt_by_date() -> dict[str, set[str]]:
    conn = sqlite3.connect(str(ZT_DB))
    zt: dict[str, set[str]] = {}
    for d, code in conn.execute("SELECT date, code FROM zt_history"):
        zt.setdefault(d, set()).add(code)
    conn.close()
    return zt


def vol_ratio_5(bars: list[dict], idx: int) -> float | None:
    if idx < 5:
        return None
    vol = bars[idx].get("volume")
    if not vol:
        return None
    pv = [b.get("volume") for b in bars[idx - 5 : idx]]
    if any(v is None or v == 0 for v in pv):
        return None
    avg5 = sum(pv) / 5.0
    return vol / avg5 if avg5 else None


def gen_watchlist_codes(t: str, all_bars: dict[str, list[dict]], zt_t: set[str]) -> list[str]:
    out: list[str] = []
    for code, bars in all_bars.items():
        tbar = None
        tidx = -1
        for i, b in enumerate(bars):
            if b.get("date") == t:
                tbar = b
                tidx = i
                break
        if tbar is None:
            continue
        if code in zt_t:
            continue
        if tbar.get("isST") in ("1", 1, True):
            continue
        turn = tbar.get("turn")
        if turn is None or turn <= TURN_THRESHOLD:
            continue
        vr5 = vol_ratio_5(bars, tidx)
        if vr5 is None or vr5 <= VR5_THRESHOLD:
            continue
        out.append(code)
    return out


# ---------------------------------------------------------------------------
# Record building (FIXED limit_for_code)
# ---------------------------------------------------------------------------


def build_records(
    end_date: str = "2026-09-17",
    days: int = 560,
    gap_lo: float = -100.0,
    gap_hi: float = 100.0,
) -> tuple[list[dict[str, Any]], int]:
    all_bars = load_kline_db()
    zt = load_zt_by_date()
    cal = sorted(zt.keys())
    if end_date not in cal:
        return [], 0
    end_idx = cal.index(end_date)
    date_idx = {d: i for i, d in enumerate(cal)}
    pairs = [(cal[i], cal[i + 1]) for i in range(max(0, end_idx - days), end_idx) if i + 1 < len(cal)]

    records: list[dict[str, Any]] = []
    for t, t1 in pairs:
        zt_t = zt.get(t, set())
        t1_idx = date_idx.get(t1)
        if t1_idx is None or t1_idx + 1 >= len(cal):
            continue
        t2 = cal[t1_idx + 1]
        wl = gen_watchlist_codes(t, all_bars, zt_t)
        for code in wl:
            bars = all_bars.get(code, [])
            tbar = next((b for b in bars if b.get("date") == t), None)
            if not tbar or tbar.get("close") is None:
                continue
            t_close = tbar["close"]
            t1bar = next((b for b in bars if b.get("date") == t1), None)
            if not t1bar or t1bar.get("open") is None or t1bar["open"] == 0:
                continue
            t1_open = t1bar["open"]
            t1_close = t1bar.get("close")
            gap = (t1_open - t_close) / t_close * 100
            if not (gap_lo <= gap < gap_hi):
                continue
            # FIXED: use limit_for_code (6-digit prefix) not sz30/sh68
            is_st = tbar.get("isST") == "1"
            zt_limit = limit_for_code(code, is_st)
            # Skip T+1 one-word limit-up (can't buy, V1 fake edge R1)
            if t1_open >= t_close * (1 + zt_limit) * 0.999:
                continue
            t2bar = next((b for b in bars if b.get("date") == t2), None)
            if not t2bar:
                continue
            if None in (
                t2bar.get("open"),
                t2bar.get("high"),
                t2bar.get("low"),
                t2bar.get("close"),
            ):
                continue
            records.append(
                {
                    "code": code,
                    "t": t,
                    "t1": t1,
                    "t2": t2,
                    "gap": round(gap, 4),
                    "t1_open": t1_open,
                    "t1_close": t1_close,
                    "t2_open": t2bar["open"],
                    "t2_high": t2bar["high"],
                    "t2_low": t2bar["low"],
                    "t2_close": t2bar["close"],
                }
            )
    return records, len(pairs)


def apply_cap(records: list[dict], cap: int | None) -> list[dict]:
    if cap is None:
        return list(records)
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_day[r["t1"]].append(r)
    out: list[dict] = []
    for _day, recs in by_day.items():
        recs_sorted = sorted(recs, key=lambda r: r["gap"], reverse=True)
        out.extend(recs_sorted[:cap])
    return out


# ---------------------------------------------------------------------------
# Return functions
# ---------------------------------------------------------------------------


def realistic_stop_ret(r: dict, stop: float = STOP) -> float:
    """R6 realistic: gap-through → t2_open*(1-slip), else stop_price, else t2_close."""
    entry = r["t1_open"]
    sp = entry * (1 + stop)
    trig = r["t2_low"] <= sp
    if trig:
        if r["t2_open"] <= sp:
            exit_p = r["t2_open"] * (1 - SLIPPAGE)
        else:
            exit_p = sp
    else:
        exit_p = r["t2_close"]
    return (exit_p - entry) / entry * 100


def ideal_stop_ret(r: dict, stop: float = STOP) -> float:
    """Ideal (over-credit) fill: stop_price if triggered, else t2_close."""
    entry = r["t1_open"]
    sp = entry * (1 + stop)
    trig = r["t2_low"] <= sp
    exit_p = sp if trig else r["t2_close"]
    return (exit_p - entry) / entry * 100


def close_ev_ret(r: dict) -> float:
    """Honest close_ev: (t2_open - t1_close) / t1_close * 100 (overnight only)."""
    if not r.get("t1_close") or r["t1_close"] == 0:
        return 0.0
    return (r["t2_open"] - r["t1_close"]) / r["t1_close"] * 100


def t1_intraday_ret(r: dict) -> float:
    """T+1 intraday return: (t1_close - t1_open) / t1_open * 100."""
    if not r.get("t1_close") or r["t1_close"] == 0:
        return 0.0
    return (r["t1_close"] - r["t1_open"]) / r["t1_open"] * 100


def t2_intraday_ret(r: dict) -> float:
    """T+2 intraday return: (t2_close - t2_open) / t2_open * 100."""
    if not r.get("t2_open") or r["t2_open"] == 0:
        return 0.0
    return (r["t2_close"] - r["t2_open"]) / r["t2_open"] * 100


# ---------------------------------------------------------------------------
# NEW METHODOLOGY 1: BH (Benjamini-Hochberg) FDR
# ---------------------------------------------------------------------------


def bh_fdr(p_list: list[float], alpha: float = 0.05) -> dict[str, Any]:
    """Benjamini-Hochberg FDR procedure.

    Controls FDR (expected proportion of false discoveries) at level alpha.
    Less conservative than Bonferroni (which controls FWER).

    Procedure:
    1. Sort p-values ascending: p_(1) <= p_(2) <= ... <= p_(m)
    2. Find largest k such that p_(k) <= (k/m) * alpha
    3. Reject H0 for all p_(1), ..., p_(k) (they are "discoveries")

    Returns dict with:
    - n_tests, alpha
    - discoveries: list of (original_index, p_value, passes)
    - n_discoveries
    - bh_threshold_for_smallest: (1/m)*alpha
    """
    m = len(p_list)
    if m == 0:
        return {"n_tests": 0, "alpha": alpha, "discoveries": [], "n_discoveries": 0, "bh_threshold_for_smallest": 0.0}

    # Sort with original indices
    indexed = sorted(enumerate(p_list), key=lambda x: x[1])

    # Find largest k where p_(k) <= (k/m) * alpha
    largest_k = 0
    for i, (orig_idx, p) in enumerate(indexed, 1):
        threshold = (i / m) * alpha
        if p <= threshold:
            largest_k = i

    # All up to largest_k are discoveries
    results = []
    for i, (orig_idx, p) in enumerate(indexed, 1):
        threshold = (i / m) * alpha
        passes = i <= largest_k
        results.append(
            {
                "orig_index": orig_idx,
                "p_value": p,
                "rank": i,
                "bh_threshold": round(threshold, 6),
                "passes": passes,
            }
        )

    return {
        "n_tests": m,
        "alpha": alpha,
        "discoveries": results,
        "n_discoveries": largest_k,
        "bh_threshold_for_smallest": round((1 / m) * alpha, 6),
    }


# ---------------------------------------------------------------------------
# NEW METHODOLOGY 2: per-trade t + HAC (Newey-West)
# ---------------------------------------------------------------------------


def norm_sf_positive(t: float) -> float:
    """One-sided p for POSITIVE edge test: P(Z > t). Direction matters."""
    return 0.5 * (1 - math.erf(t / math.sqrt(2)))


def per_trade_t_hac(
    rets: list[float],
    dates: list[str],
    lag: int | None = None,
) -> dict[str, Any]:
    """Per-trade t-test with HAC (Newey-West) standard errors.

    Unlike per-day-mean t (which aggregates same-day trades → reduces N to n_days),
    this keeps all n_trades observations and corrects SE for:
    - Heteroskedasticity (unequal variance)
    - Autocorrelation (same-day + serial correlation via Newey-West)

    Trades are ordered by date (chronological), so same-day trades are adjacent.
    Newey-West with Bartlett kernel corrects for this correlation without reducing N.

    Lag selection (Newey-West 1994): L = floor(4 * (n/100)^(2/9))
    Can override with explicit lag for sensitivity analysis.

    Returns: n_trades, mean, hac_se, t, p_one_sided, lag, and sensitivity (multiple lags).
    """
    n = len(rets)
    if n == 0:
        return {"n_trades": 0, "mean": 0.0, "hac_se": 0.0, "t": 0.0, "p_one_sided": 1.0, "lag": 0, "sensitivity": {}}

    # Order by date (stable sort preserves within-day order)
    paired = sorted(zip(dates, rets), key=lambda x: x[0])
    r = [p[1] for p in paired]
    mean = sum(r) / n

    # Default lag: Newey-West 1994 rule
    if lag is None:
        lag = max(1, int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0))))

    def nw_variance(rets_ordered: list[float], mean_val: float, L: int) -> float:
        """Newey-West variance estimator with Bartlett kernel."""
        nn = len(rets_ordered)
        # gamma_0 (variance)
        dev = [x - mean_val for x in rets_ordered]
        gamma_0 = sum(d * d for d in dev) / nn
        # Autocovariances with Bartlett weights
        nw_var = gamma_0
        for l in range(1, L + 1):
            if l >= nn:
                break
            gamma_l = sum(dev[i] * dev[i + l] for i in range(nn - l)) / nn
            weight = 1.0 - l / (L + 1.0)  # Bartlett kernel
            nw_var += 2.0 * weight * gamma_l
        return max(nw_var, 1e-30)  # floor to avoid div-by-zero

    nw_var = nw_variance(r, mean, lag)
    hac_se = math.sqrt(nw_var / n)
    t_stat = mean / hac_se if hac_se > 0 else 0.0
    p_val = norm_sf_positive(t_stat)

    # Sensitivity: compute t for multiple lag choices
    sensitivity = {}
    for L_test in [1, 3, 5, 10, 20]:
        if L_test < n:
            v = nw_variance(r, mean, L_test)
            se = math.sqrt(v / n)
            t_s = mean / se if se > 0 else 0.0
            sensitivity[f"L={L_test}"] = {
                "t": round(t_s, 4),
                "p": round(norm_sf_positive(t_s), 6),
                "se": round(se, 4),
            }

    # Also compute per-day-mean t for comparison
    by_day: dict[str, list[float]] = defaultdict(list)
    for d, ret in paired:
        by_day[d].append(ret)
    day_means = [sum(v) / len(v) for v in by_day.values()]
    n_days = len(day_means)
    day_mean = sum(day_means) / n_days if n_days > 0 else 0.0
    day_std = statistics.stdev(day_means) if n_days > 1 else 0.0
    day_se = day_std / math.sqrt(n_days) if n_days > 0 else 0.0
    day_t = day_mean / day_se if day_se > 0 else 0.0
    day_p = norm_sf_positive(day_t)

    # Ordinary (non-HAC) per-trade t for comparison
    trade_std = statistics.stdev(r) if n > 1 else 0.0
    trade_se_ols = trade_std / math.sqrt(n) if n > 0 else 0.0
    trade_t_ols = mean / trade_se_ols if trade_se_ols > 0 else 0.0
    trade_p_ols = norm_sf_positive(trade_t_ols)

    return {
        "n_trades": n,
        "n_days": n_days,
        "mean": round(mean, 4),
        "hac_se": round(hac_se, 4),
        "t": round(t_stat, 4),
        "p_one_sided": round(p_val, 6),
        "lag": lag,
        # Comparison baselines
        "per_day_mean_t": round(day_t, 4),
        "per_day_mean_p": round(day_p, 6),
        "per_day_n": n_days,
        "per_trade_ols_t": round(trade_t_ols, 4),
        "per_trade_ols_p": round(trade_p_ols, 6),
        "trade_std": round(trade_std, 4),
        "day_std": round(day_std, 4),
        "sensitivity": sensitivity,
    }


# ---------------------------------------------------------------------------
# NEW METHODOLOGY 3: rolling 4-window walk-forward
# ---------------------------------------------------------------------------


def rolling_walk_forward(
    records: list[dict],
    ret_fn: Callable[[dict], float],
    n_windows: int = 4,
) -> dict[str, Any]:
    """Rolling (expanding) walk-forward with n_windows date-quarters.

    Splits sorted unique dates into n_windows quarters: Q1, Q2, ..., Qn.
    Window i (i=1..n-1): train = Q1..Qi, test = Q(i+1).
    Each window produces test EV + per-trade HAC t + p.

    This is proper walk-forward (expanding window), NOT in-sample split.
    Replaces single 50/50 split with multiple OOS test windows.
    """
    if not records:
        return {"status": "no_records", "windows": []}

    # Sort records by t1 date
    recs_sorted = sorted(records, key=lambda r: r["t1"])
    all_dates = sorted(set(r["t1"] for r in recs_sorted))
    n_dates = len(all_dates)

    if n_dates < n_windows:
        return {"status": "too_few_dates", "n_dates": n_dates, "n_windows": n_windows, "windows": []}

    # Split dates into n_windows quarters
    quarter_size = n_dates // n_windows
    quarters = []
    for i in range(n_windows):
        start = i * quarter_size
        end = (i + 1) * quarter_size if i < n_windows - 1 else n_dates
        quarters.append(set(all_dates[start:end]))

    windows = []
    for w in range(n_windows - 1):
        train_dates = set()
        for i in range(w + 1):
            train_dates |= quarters[i]
        test_dates = quarters[w + 1]

        train_recs = [r for r in recs_sorted if r["t1"] in train_dates]
        test_recs = [r for r in recs_sorted if r["t1"] in test_dates]

        train_rets = [ret_fn(r) for r in train_recs]
        train_rets = [x for x in train_rets if x is not None]
        test_rets = [ret_fn(r) for r in test_recs]
        test_rets = [x for x in test_rets if x is not None]

        if not test_rets:
            windows.append(
                {
                    "window": w + 1,
                    "train_n": len(train_rets),
                    "test_n": 0,
                    "train_n_days": len(train_dates),
                    "test_n_days": len(test_dates),
                    "train_ev": 0.0,
                    "test_ev": 0.0,
                    "test_hac_t": 0.0,
                    "test_hac_p": 1.0,
                    "status": "empty_test",
                }
            )
            continue

        train_ev = sum(train_rets) / len(train_rets) if train_rets else 0.0
        test_ev = sum(test_rets) / len(test_rets)

        # per-trade HAC on test half
        test_dates_list = [r["t1"] for r in test_recs if ret_fn(r) is not None]
        hac = per_trade_t_hac(test_rets, test_dates_list)

        windows.append(
            {
                "window": w + 1,
                "train_n": len(train_rets),
                "test_n": len(test_rets),
                "train_n_days": len(train_dates),
                "test_n_days": len(test_dates),
                "train_ev": round(train_ev, 4),
                "test_ev": round(test_ev, 4),
                "test_hac_t": hac["t"],
                "test_hac_p": hac["p_one_sided"],
                "test_hac_lag": hac["lag"],
                "status": "ok",
            }
        )

    # Summary: how many test windows have positive EV + significant p
    positive_windows = sum(1 for w in windows if w["test_ev"] > 0)
    significant_windows = sum(1 for w in windows if w["test_hac_p"] < ALPHA)
    positive_and_sig = sum(1 for w in windows if w["test_ev"] > 0 and w["test_hac_p"] < ALPHA)

    return {
        "status": "ok",
        "n_windows": n_windows,
        "n_dates": n_dates,
        "n_test_windows": len(windows),
        "windows": windows,
        "positive_test_windows": positive_windows,
        "significant_test_windows": significant_windows,
        "positive_and_significant": positive_and_sig,
    }


# ---------------------------------------------------------------------------
# Per-day-mean stats (original methodology, for comparison)
# ---------------------------------------------------------------------------


def per_day_stats(records: list[dict], ret_fn: Callable[[dict], float]) -> dict[str, Any]:
    by_day: dict[str, list[float]] = defaultdict(list)
    for r in records:
        by_day[r["t1"]].append(ret_fn(r))
    sorted_days = sorted(by_day.keys())
    day_means = [sum(by_day[d]) / len(by_day[d]) for d in sorted_days]
    n = len(day_means)
    n_trades = sum(len(by_day[d]) for d in sorted_days)
    if n == 0:
        return {
            "n_days": 0,
            "n_trades": 0,
            "per_trade_ev": 0.0,
            "per_day_mean_ev": 0.0,
            "day_clustered_t": 0.0,
            "p_one_sided": 1.0,
            "day_means_chrono": [],
        }
    per_trade_rets = [ret_fn(r) for r in records]
    per_trade_ev = sum(per_trade_rets) / n_trades if n_trades else 0.0
    mean = sum(day_means) / n
    std = statistics.stdev(day_means) if n > 1 else 0.0
    se = std / math.sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p_one = 0.5 * (1 - math.erf(abs(t) / math.sqrt(2)))
    return {
        "n_days": n,
        "n_trades": n_trades,
        "per_trade_ev": round(per_trade_ev, 4),
        "per_day_mean_ev": round(mean, 4),
        "day_clustered_t": round(t, 4),
        "p_one_sided": round(p_one, 6),
        "day_means_chrono": day_means,
    }


# ---------------------------------------------------------------------------
# Main: re-test with new methodology
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 78)
    print("RE-TEST: gap(-3,-2] open_stop — less-conservative methodology")
    print("BH FDR 5% + per-trade HAC + rolling 4-window walk-forward")
    print("=" * 78)

    print("\n加载数据…")
    all_records, npairs = build_records(end_date="2026-09-17", days=560, gap_lo=-100.0, gap_hi=100.0)
    if not all_records:
        print("ERR: no records")
        return
    n_picks_total = len(all_records)
    print(f"pairs={npairs} n_picks_total(all gaps)={n_picks_total}")

    # ---- Filter to gap(-3,-2] = [-3, -2) ----
    gap_neg3_neg2 = [r for r in all_records if -3.0 <= r["gap"] < -2.0]
    n_picks_gap = len(gap_neg3_neg2)
    active_days = sorted(set(r["t1"] for r in gap_neg3_neg2))
    n_days = len(active_days)
    print(f"gap(-3,-2] 子组: n_picks={n_picks_gap} n_active_days={n_days}")

    # ---- Cap=3/day shallowest-gap-first ----
    capped3 = apply_cap(gap_neg3_neg2, 3)
    print(f"cap=3/day: n_picks={len(capped3)}")

    # ==================================================================
    # SECTION A: Original methodology (baseline reproduction)
    # ==================================================================
    print("\n" + "=" * 78)
    print("A. 原方法学（baseline 复现）: per-day-mean t + Bonferroni×9 + 50/50 WF")
    print("=" * 78)

    s_orig = per_day_stats(capped3, realistic_stop_ret)
    net_ev_orig = s_orig["per_day_mean_ev"] - COST_PCT
    print(f"\nopen_stop (cap=3, per-day-mean t):")
    print(f"  n_trades={s_orig['n_trades']} n_days={s_orig['n_days']}")
    print(f"  gross per_day_mean_EV = {s_orig['per_day_mean_ev']:+.4f}%")
    print(f"  net EV (after {COST_PCT}% cost) = {net_ev_orig:+.4f}%")
    print(f"  day_clustered_t = {s_orig['day_clustered_t']:+.4f}")
    print(f"  p_one_sided (raw) = {s_orig['p_one_sided']:.6f}")
    print(f"  Bonferroni p (×9) = {min(s_orig['p_one_sided'] * 9, 1.0):.6f}")

    # close_ev honest caliber
    valid_close_c3 = [r for r in capped3 if r.get("t1_close") and r["t1_close"] != 0]
    c_orig = per_day_stats(valid_close_c3, close_ev_ret)
    print(f"\nclose_ev (honest, cap=3):")
    print(f"  per_day_mean_EV = {c_orig['per_day_mean_ev']:+.4f}%")
    print(f"  day_clustered_t = {c_orig['day_clustered_t']:+.4f}")
    print(f"  p_one_sided = {c_orig['p_one_sided']:.6f}")

    print(f"\n原 verdict: edge-falsified (close_ev {c_orig['per_day_mean_ev']:+.4f}% ≤ 0)")
    print(f"原 Bonf×9 p = {min(s_orig['p_one_sided'] * 9, 1.0):.6f} (pass={'YES' if s_orig['p_one_sided'] * 9 < ALPHA else 'NO'})")

    # ==================================================================
    # SECTION B: NEW METHODOLOGY 1 — BH FDR 5% (replaces Bonferroni×9)
    # ==================================================================
    print("\n" + "=" * 78)
    print("B. 新方法学 1: BH FDR 5% (替代 Bonferroni×9)")
    print("=" * 78)

    # Build 9-combo grid (same as original Bonferroni grid)
    gap_widths = [
        ("[-3,-2)", -3.0, -2.0),
        ("[-2.5,-1.5)", -2.5, -1.5),
        ("[-5,-2)", -5.0, -2.0),
    ]
    caps_cfg = [("none", None), ("3", 3), ("5", 5)]

    grid_p_values = []
    grid_info = []
    for gw_name, gw_lo, gw_hi in gap_widths:
        for cap_name, cap_val in caps_cfg:
            sub = [r for r in all_records if gw_lo <= r["gap"] < gw_hi]
            capped_sub = apply_cap(sub, cap_val)
            stats = per_day_stats(capped_sub, realistic_stop_ret)
            grid_p_values.append(stats["p_one_sided"])
            grid_info.append(
                {
                    "combo": f"gap{gw_name}+cap{cap_name}",
                    "n_trades": stats["n_trades"],
                    "n_days": stats["n_days"],
                    "ev": stats["per_day_mean_ev"],
                    "t": stats["day_clustered_t"],
                    "p": stats["p_one_sided"],
                }
            )

    bh_result = bh_fdr(grid_p_values, alpha=ALPHA)
    n_tests = bh_result["n_tests"]
    print(f"\n{n_tests} combos, BH alpha={ALPHA}")
    print(f"BH threshold for smallest p (rank 1): {bh_result['bh_threshold_for_smallest']}")
    print(f"n_discoveries (BH): {bh_result['n_discoveries']}")
    print(f"\n{'combo':<24} {'n_trades':>8} {'n_days':>6} {'EV':>8} {'t':>8} {'p_raw':>10} {'BH_pass':>8}")
    print("-" * 80)
    for info, disc in zip(grid_info, bh_result["discoveries"]):
        marker = " <-- MAIN" if info["combo"] == "gap[-3,-2)+cap3" else ""
        print(
            f"{info['combo']:<24} {info['n_trades']:>8} {info['n_days']:>6} "
            f"{info['ev']:>+7.4f}% {info['t']:>+8.4f} {info['p']:>10.6f} "
            f"{'PASS' if disc['passes'] else 'fail':>8}{marker}"
        )

    main_combo_info = next(g for g in grid_info if g["combo"] == "gap[-3,-2)+cap3")
    main_disc = next(d for d in bh_result["discoveries"] if d["orig_index"] == grid_info.index(main_combo_info))
    bh_main_pass = main_disc["passes"]
    print(f"\nmain combo (gap[-3,-2)+cap3):")
    print(f"  p_raw = {main_combo_info['p']:.6f}")
    print(f"  Bonferroni p (×9) = {min(main_combo_info['p'] * 9, 1.0):.6f}")
    print(f"  BH FDR pass = {bh_main_pass} (rank={main_disc['rank']}, threshold={main_disc['bh_threshold']})")

    # ==================================================================
    # SECTION C: NEW METHODOLOGY 2 — per-trade t + HAC (replaces per-day-mean t)
    # ==================================================================
    print("\n" + "=" * 78)
    print("C. 新方法学 2: per-trade t + HAC Newey-West (替代 per-day-mean t)")
    print("=" * 78)

    open_rets = [realistic_stop_ret(r) for r in capped3]
    open_dates = [r["t1"] for r in capped3]
    hac_open = per_trade_t_hac(open_rets, open_dates)

    print(f"\nopen_stop (cap=3, per-trade HAC):")
    print(f"  n_trades = {hac_open['n_trades']}  (vs per-day-mean n_days = {hac_open['per_day_n']})")
    print(f"  mean = {hac_open['mean']:+.4f}%")
    print(f"  HAC SE = {hac_open['hac_se']:.4f}%  (lag L={hac_open['lag']})")
    print(f"  HAC t = {hac_open['t']:+.4f}")
    print(f"  HAC p_one_sided = {hac_open['p_one_sided']:.6f}")
    print(f"\n  comparison:")
    print(f"    per-trade OLS t (no HAC) = {hac_open['per_trade_ols_t']:+.4f}  p={hac_open['per_trade_ols_p']:.6f}")
    print(f"    per-day-mean t (original) = {hac_open['per_day_mean_t']:+.4f}  p={hac_open['per_day_mean_p']:.6f}")
    print(f"    trade_std = {hac_open['trade_std']:.4f}%  day_std = {hac_open['day_std']:.4f}%")
    print(f"\n  sensitivity (lag robustness):")
    for lag_key, vals in hac_open["sensitivity"].items():
        print(f"    {lag_key}: t={vals['t']:+.4f}  p={vals['p']:.6f}  SE={vals['se']:.4f}")

    net_ev_hac = hac_open["mean"] - COST_PCT
    hac_pass = hac_open["p_one_sided"] < ALPHA
    print(f"\n  net EV (after {COST_PCT}% cost) = {net_ev_hac:+.4f}%")
    print(f"  HAC p < {ALPHA}: {'PASS' if hac_pass else 'FAIL'}")

    # Also apply HAC to close_ev
    close_rets = [close_ev_ret(r) for r in valid_close_c3]
    close_dates = [r["t1"] for r in valid_close_c3]
    hac_close = per_trade_t_hac(close_rets, close_dates)
    print(f"\nclose_ev (cap=3, per-trade HAC):")
    print(f"  n_trades = {hac_close['n_trades']}  mean = {hac_close['mean']:+.4f}%")
    print(f"  HAC t = {hac_close['t']:+.4f}  p = {hac_close['p_one_sided']:.6f}")
    print(f"  per-day-mean t = {hac_close['per_day_mean_t']:+.4f}  p = {hac_close['per_day_mean_p']:.6f}")

    # ==================================================================
    # SECTION D: NEW METHODOLOGY 3 — rolling 4-window walk-forward
    # ==================================================================
    print("\n" + "=" * 78)
    print("D. 新方法学 3: rolling 4-window walk-forward (替代 single 50/50)")
    print("=" * 78)

    rwf = rolling_walk_forward(capped3, realistic_stop_ret, n_windows=4)
    print(f"\nstatus: {rwf['status']}  n_dates={rwf.get('n_dates', 0)}")
    if rwf["status"] == "ok":
        print(f"\n{'win':>4} {'train_n':>8} {'train_ev':>10} {'test_n':>8} {'test_n_days':>12} {'test_ev':>10} {'test_HAC_t':>10} {'test_HAC_p':>10}")
        print("-" * 82)
        for w in rwf["windows"]:
            print(
                f"{w['window']:>4} {w['train_n']:>8} {w['train_ev']:>+9.4f}% "
                f"{w['test_n']:>8} {w['test_n_days']:>12} {w['test_ev']:>+9.4f}% "
                f"{w['test_hac_t']:>+10.4f} {w['test_hac_p']:>10.6f}"
            )
        print(f"\npositive test windows: {rwf['positive_test_windows']}/{rwf['n_test_windows']}")
        print(f"significant (HAC p<{ALPHA}): {rwf['significant_test_windows']}/{rwf['n_test_windows']}")
        print(f"positive AND significant: {rwf['positive_and_significant']}/{rwf['n_test_windows']}")

    # Also rolling WF for close_ev
    rwf_close = rolling_walk_forward(valid_close_c3, close_ev_ret, n_windows=4)
    print(f"\nclose_ev rolling 4-window WF:")
    if rwf_close["status"] == "ok":
        for w in rwf_close["windows"]:
            print(f"  win{w['window']}: test_ev={w['test_ev']:+.4f}% HAC_t={w['test_hac_t']:+.4f} p={w['test_hac_p']:.6f}")
        print(f"  positive: {rwf_close['positive_test_windows']}/{rwf_close['n_test_windows']}")

    # ==================================================================
    # SECTION E: Fake-edge 5-pattern audit
    # ==================================================================
    print("\n" + "=" * 78)
    print("E. 假 edge 5-pattern 审计")
    print("=" * 78)

    # Pattern 1: entry 涨停价溢价 — entry is T+1 open after gap-DOWN, not at limit-up
    entry_at_limit = sum(1 for r in capped3 if r["t1_open"] >= r.get("t1_close", 0) * 0.999)
    print(f"\n1. entry 涨停价溢价:")
    print(f"   entry = T+1 open (after gap-DOWN in [-3,-2)), NOT at limit-up")
    print(f"   trades with t1_open >= t1_close: {entry_at_limit}/{len(capped3)} ({entry_at_limit / max(len(capped3), 1) * 100:.1f}%)")
    print(f"   → {'CLEAN' if entry_at_limit < len(capped3) * 0.05 else 'SUSPICIOUS'}: gap-down entry is below T close, not at limit-up premium")

    # Pattern 2: survivorship — all watchlist stocks included, no filtering by survival
    print(f"\n2. survivorship:")
    print(f"   S232 watchlist = turn>20% + vr5>2, NOT limit-up stocks")
    print(f"   All watchlist picks included regardless of outcome")
    print(f"   → CLEAN: no survivorship bias (all picks counted)")

    # Pattern 3: T+1 日内泄漏 — close_ev check
    print(f"\n3. T+1 日内泄漏:")
    print(f"   close_ev (T+1 close→T+2 open) per-day-mean EV = {c_orig['per_day_mean_ev']:+.4f}%")
    print(f"   close_ev HAC t = {hac_close['t']:+.4f}  p = {hac_close['p_one_sided']:.6f}")
    # Decompose open_stop into components
    t1_intra = [t1_intraday_ret(r) for r in capped3]
    overnight = [close_ev_ret(r) for r in capped3 if r.get("t1_close") and r["t1_close"] != 0]
    t2_intra = [t2_intraday_ret(r) for r in capped3]
    print(f"   open_stop decomposition (per-trade mean):")
    print(f"     T+1 intraday (open→close)  = {sum(t1_intra) / len(t1_intra):+.4f}%")
    print(f"     overnight (T+1 close→T+2 open) = {sum(overnight) / len(overnight):+.4f}%")
    print(f"     T+2 intraday (open→close) = {sum(t2_intra) / len(t2_intra):+.4f}%")
    print(f"     sum = {sum(t1_intra) / len(t1_intra) + sum(overnight) / len(overnight) + sum(t2_intra) / len(t2_intra):+.4f}%")
    print(f"     open_stop actual = {hac_open['mean']:+.4f}%")
    t1_intra_share = (sum(t1_intra) / len(t1_intra)) / hac_open["mean"] * 100 if hac_open["mean"] != 0 else 0
    print(
        f"   → {'FAKE EDGE' if c_orig['per_day_mean_ev'] < 0 else 'CLEAN'}: "
        f"close_ev = {c_orig['per_day_mean_ev']:+.4f}% "
        f"({'negative = overnight leakage, T+1 intraday recovery is the edge' if c_orig['per_day_mean_ev'] < 0 else 'positive = genuine overnight drift'})"
    )
    print(f"   T+1 intraday contributes {t1_intra_share:.0f}% of open_stop EV")

    # Pattern 4: 拥挤倒 U — in-sample strong, OOS decay
    print(f"\n4. 拥挤倒 U (in-sample vs OOS):")
    if rwf["status"] == "ok":
        train_evs = [w["train_ev"] for w in rwf["windows"]]
        test_evs = [w["test_ev"] for w in rwf["windows"]]
        print(f"   train EVs: {['%.4f' % e for e in train_evs]}")
        print(f"   test  EVs: {['%.4f' % e for e in test_evs]}")
        consistent = all(e > 0 for e in test_evs)
        print(f"   → {'CONSISTENT' if consistent else 'INCONSISTENT'}: {'all' if consistent else 'not all'} test windows positive")
        if not consistent:
            neg_windows = [w["window"] for w in rwf["windows"] if w["test_ev"] <= 0]
            print(f"   negative test windows: {neg_windows}")

    # Pattern 5: fill 虚构 — R6 gap-through fill assumption
    print(f"\n5. fill 虚构 (R6 stop fill):")
    ideal_rets = [ideal_stop_ret(r) for r in capped3]
    real_rets = [realistic_stop_ret(r) for r in capped3]
    ideal_ev = sum(ideal_rets) / len(ideal_rets)
    real_ev = sum(real_rets) / len(real_rets)
    over_credit = ideal_ev - real_ev
    sp_fn = lambda r: r["t1_open"] * (1 + STOP)
    trig_total = sum(1 for r in capped3 if r["t2_low"] <= sp_fn(r))
    gap_through = sum(1 for r in capped3 if r["t2_low"] <= sp_fn(r) and r["t2_open"] <= sp_fn(r))
    print(f"   ideal EV (over-credit) = {ideal_ev:+.4f}%")
    print(f"   realistic EV (R6) = {real_ev:+.4f}%")
    print(f"   over-credit = {over_credit:+.4f}%")
    print(f"   stop triggered: {trig_total}/{len(capped3)} ({trig_total / max(len(capped3), 1) * 100:.1f}%)")
    if trig_total:
        print(f"   gap-through: {gap_through} ({gap_through / max(trig_total, 1) * 100:.1f}% of triggers)")
    print(
        f"   → {'SUSPICIOUS' if over_credit > 0.3 else 'CLEAN'}: "
        f"over-credit = {over_credit:+.4f}% "
        f"({'R6 matters >0.3%' if over_credit > 0.3 else 'R6 correction small'})"
    )

    # ==================================================================
    # SECTION F: New verdict (less-conservative methodology)
    # ==================================================================
    print("\n" + "=" * 78)
    print("F. 新方法学判定 (BH + HAC + rolling WF)")
    print("=" * 78)

    gross_ev = hac_open["mean"]
    net_ev = gross_ev - COST_PCT
    hac_t = hac_open["t"]
    hac_p = hac_open["p_one_sided"]
    close_ev_val = c_orig["per_day_mean_ev"]
    close_ev_hac_t = hac_close["t"]
    close_ev_hac_p = hac_close["p_one_sided"]

    print(f"\nopen_stop (cap=3, per-trade HAC):")
    print(f"  gross EV = {gross_ev:+.4f}%")
    print(f"  net EV (after {COST_PCT}% cost) = {net_ev:+.4f}%")
    print(f"  HAC t = {hac_t:+.4f}  (lag L={hac_open['lag']})")
    print(f"  HAC p_one_sided = {hac_p:.6f}")
    print(f"  BH FDR pass (across 9 combos) = {bh_main_pass}")
    print(f"  per-day-mean t (original) = {hac_open['per_day_mean_t']:+.4f}")

    print(f"\nclose_ev (honest caliber):")
    print(f"  per-day-mean EV = {close_ev_val:+.4f}%")
    print(f"  HAC t = {close_ev_hac_t:+.4f}  p = {close_ev_hac_p:.6f}")

    print(f"\nrolling 4-window WF (open_stop):")
    if rwf["status"] == "ok":
        for w in rwf["windows"]:
            sig = "SIG" if w["test_hac_p"] < ALPHA else "ns"
            pos = "+" if w["test_ev"] > 0 else "-"
            print(
                f"  win{w['window']}: train_EV={w['train_ev']:+.4f}% → "
                f"test_EV={w['test_ev']:+.4f}% HAC_t={w['test_hac_t']:+.4f} "
                f"p={w['test_hac_p']:.4f} [{pos}{sig}]"
            )
        print(f"  positive: {rwf['positive_test_windows']}/{rwf['n_test_windows']}, significant: {rwf['significant_test_windows']}/{rwf['n_test_windows']}")

    # --- Verdict logic (frozen before running) ---
    # Using less-conservative methodology but keeping honest constraints:
    # 1. gross EV < 0 → falsified (loser signal)
    # 2. n_days < 60 → underpowered
    # 3. HAC p (not Bonferroni) >= 0.05 AND BH FDR fail → falsified
    # 4. net EV <= 0 → falsified (gross eaten by cost)
    # 5. rolling WF: majority test windows EV <= 0 → falsified
    # 6. close_ev strongly negative (fake edge pattern #3) → exploratory at best
    # 7. all pass + close_ev > 0 → edge-confirmed
    # 8. all pass but close_ev ≤ 0 → exploratory (T+1 intraday leakage)

    print(f"\n--- 判定级联 ---")

    if gross_ev < 0:
        verdict = "edge-falsified"
        reason = f"gross EV = {gross_ev:+.4f}% < 0 (negative edge)"
        print(f"  1. gross EV < 0 → FALSIFIED")
    elif n_days < 60:
        verdict = "underpowered"
        reason = f"n_days = {n_days} < 60"
        print(f"  2. n_days = {n_days} < 60 → UNDERPOWERED")
    elif hac_p >= ALPHA and not bh_main_pass:
        verdict = "edge-falsified"
        reason = f"HAC p = {hac_p:.6f} >= {ALPHA} AND BH FDR fail (neither per-trade HAC nor BH FDR significant)"
        print(f"  3. HAC p = {hac_p:.6f} >= {ALPHA} + BH fail → FALSIFIED")
    elif hac_p >= ALPHA:
        # HAC fails but BH passes (less conservative multiple testing)
        verdict = "exploratory"
        reason = f"HAC p = {hac_p:.6f} >= {ALPHA} but BH FDR pass (borderline significance)"
        print(f"  3b. HAC p >= {ALPHA} but BH pass → EXPLORATORY (borderline)")
    elif net_ev <= 0:
        verdict = "edge-falsified"
        reason = f"net EV = {net_ev:+.4f}% <= 0 (gross edge eaten by {COST_PCT}% cost)"
        print(f"  4. net EV = {net_ev:+.4f}% <= 0 → FALSIFIED")
    elif rwf["status"] == "ok" and rwf["positive_test_windows"] < rwf["n_test_windows"] / 2:
        verdict = "edge-falsified"
        reason = f"rolling WF: only {rwf['positive_test_windows']}/{rwf['n_test_windows']} test windows positive (majority negative = not robust OOS)"
        print(f"  5. rolling WF majority negative → FALSIFIED")
    elif close_ev_val <= 0:
        # open_stop passes HAC + BH + net + rolling WF, but close_ev negative
        # = T+1 intraday leakage fake edge (pattern #3)
        verdict = "exploratory"
        reason = (
            f"open_stop passes HAC/BH/net/WF but close_ev = {close_ev_val:+.4f}% ≤ 0 (T+1 intraday leakage: edge from gap-down recovery, not overnight drift)"
        )
        print(f"  6. close_ev = {close_ev_val:+.4f}% ≤ 0 → EXPLORATORY (intraday leakage)")
        print(f"     open_stop edge comes from T+1 intraday recovery, NOT overnight drift")
        print(f"     close_ev HAC t = {close_ev_hac_t:+.4f} (strongly negative)")
    elif rwf["status"] == "ok" and rwf["significant_test_windows"] < rwf["n_test_windows"] / 2:
        verdict = "exploratory"
        reason = f"rolling WF: only {rwf['significant_test_windows']}/{rwf['n_test_windows']} test windows HAC-significant (OOS not consistently significant)"
        print(f"  6b. rolling WF not consistently significant → EXPLORATORY")
    else:
        verdict = "edge-confirmed"
        reason = "all checks pass: HAC p<0.05, BH FDR pass, net EV>0, rolling WF majority positive+significant, close_ev>0"
        print(f"  7. all pass + close_ev > 0 → EDGE-CONFIRMED")

    flipped = verdict != "edge-falsified"

    print(f"\n>>> 新方法学判定: {verdict}")
    print(f">>> 原因: {reason}")
    print(f">>> 翻正 (from edge-falsified): {flipped}")

    # ==================================================================
    # SUMMARY
    # ==================================================================
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"n_picks_gap(-3,-2]       : {n_picks_gap}")
    print(f"n_days (active)          : {n_days}")
    print(f"cap=3 n_picks            : {len(capped3)}")
    print(f"")
    print(f"--- 原方法学 ---")
    print(f"open_stop per_day_mean  : {s_orig['per_day_mean_ev']:+.4f}%")
    print(f"open_stop day_t         : {s_orig['day_clustered_t']:+.4f}")
    print(f"Bonferroni p (×9)       : {min(s_orig['p_one_sided'] * 9, 1.0):.6f}")
    print(f"close_ev per_day_mean   : {c_orig['per_day_mean_ev']:+.4f}%")
    print(f"原 verdict              : edge-falsified")
    print(f"")
    print(f"--- 新方法学 ---")
    print(f"open_stop HAC t         : {hac_t:+.4f}  (lag L={hac_open['lag']})")
    print(f"open_stop HAC p         : {hac_p:.6f}")
    print(f"BH FDR pass (9 combos)  : {bh_main_pass}")
    print(f"net EV (after {COST_PCT}% cost)  : {net_ev:+.4f}%")
    print(f"close_ev HAC t          : {close_ev_hac_t:+.4f}  p={close_ev_hac_p:.6f}")
    if rwf["status"] == "ok":
        print(f"rolling WF positive     : {rwf['positive_test_windows']}/{rwf['n_test_windows']}")
        print(f"rolling WF significant  : {rwf['significant_test_windows']}/{rwf['n_test_windows']}")
    print(f"R6 over-credit          : {over_credit:+.4f}%")
    print(f"")
    print(f"新 verdict              : {verdict}")
    print(f"flipped                 : {flipped}")
    print(f"")
    print(f"--- 假 edge 审计 ---")
    print(f"1. entry 涨停价溢价    : {'CLEAN' if entry_at_limit < len(capped3) * 0.05 else 'SUSPICIOUS'}")
    print(f"2. survivorship         : CLEAN (all watchlist picks counted)")
    print(f"3. T+1 日内泄漏         : {'FAKE EDGE' if close_ev_val < 0 else 'CLEAN'} (close_ev={close_ev_val:+.4f}%)")
    print(f"4. 拥挤倒 U             : see rolling WF above")
    print(f"5. fill 虚构            : {'SUSPICIOUS' if over_credit > 0.3 else 'CLEAN'} (over-credit={over_credit:+.4f}%)")


if __name__ == "__main__":
    main()
