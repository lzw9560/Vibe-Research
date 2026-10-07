# -*- coding: utf-8 -*-
"""短线策略探索: 均值回归/超跌反弹 (mean-reversion/oversold bounce)

策略: 全市场扫描超跌信号 (非涨停股), T+1 open 买, T+N close 卖 (N=2/3/5)

信号定义 (9 个 sub-strategy):
  - 5日跌幅反转: close[t]/close[t-5]-1 <= -10%/-15%/-20%
  - RSI(14) 超卖: RSI < 20 / < 30
  - 破MA20 -5%: close < MA20 * 0.95
  - 连阴反弹: 连续 4/5/6 日下跌

过严口径 (§44 v3):
  - entry = T+1 open (非涨停价, realistic)
  - close_ev 非 open_ev (防日内泄漏)
  - T+1 一字涨停跳过 (买不进)
  - T+2/N 一字跌停跳过 (卖不出)
  - per-day-mean t (同日 picks 聚 day-mean, 非 per-trade t)
  - Bonferroni cross-strategy ×N (9 signals × 3 holds = 27)
  - walk-forward OOS + train_ev>0 检查
  - -3% stop + R6 gap-through fill
  - 禁止外推: 单策略 ≠ 短线有/无 edge

跑法:
  cd backend && .venv/bin/python tools/explore_shortterm_mean-reversion-oversold.py
"""
from __future__ import annotations

import json
import sys
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt

# Add backend to path for import
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tools._factor_helpers import (
    load_kline_db,
    limit_for_code,
    is_yizi_t1,
    close_ev_basic,
    close_ev_stop,
    ev_stats,
    day_paired_t,
    bonferroni_p,
    walk_forward,
    verdict_for,
    COST,
    STOP_PCT,
    ALPHA,
    SLIPPAGE,
)

ROOT = Path(__file__).resolve().parents[2]
REGIME_PATH = ROOT / ".vibe-research" / "index_ma20_regime.json"

# Total cross-strategy tests for Bonferroni: 9 signals × 3 hold periods
N_SIGNALS = 9
N_HOLDS = 3
N_CROSS_FACTOR = N_SIGNALS * N_HOLDS  # 27


# ------------------------------------------------------------------
# 一字跌停检测 (can't sell on exit day)
# ------------------------------------------------------------------

def is_yizi_down(bar: dict, prev_close: float, limit: float) -> bool:
    """一字跌停: open 和 high 都在跌停价附近 (locked at limit-down, 卖不出).

    与 is_yizi_t1 互补:
    - is_yizi_t1: T+1 一字涨停 (买不进)
    - is_yizi_down: T+N 一字跌停 (卖不出)
    """
    lim_down = prev_close * (1 - limit)
    o = bar.get("open")
    h = bar.get("high")
    if o is None or h is None or lim_down <= 0:
        return False
    return abs(o - lim_down) / lim_down < 0.005 and abs(h - lim_down) / lim_down < 0.005


# ------------------------------------------------------------------
# indicator computation (no look-ahead)
# ------------------------------------------------------------------

def compute_rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI. None for first `period` elements (not enough data)."""
    n = len(closes)
    if n < period + 1:
        return [None] * n
    rsi: list[float | None] = [None] * n
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        gains[i] = max(diff, 0.0)
        losses[i] = max(-diff, 0.0)

    # Initial SMA-based average
    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - 100.0 / (1.0 + rs)

    # Wilder's smoothing for subsequent values
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)
    return rsi


def compute_ma(closes: list[float], period: int = 20) -> list[float | None]:
    """Simple moving average. None for first period-1 elements."""
    n = len(closes)
    ma: list[float | None] = [None] * n
    for i in range(period - 1, n):
        ma[i] = sum(closes[i - period + 1 : i + 1]) / period
    return ma


def compute_consecutive_down(closes: list[float]) -> list[int]:
    """Consecutive down day count: how many consecutive closes < prev close."""
    n = len(closes)
    counts = [0] * n
    for i in range(1, n):
        if closes[i] < closes[i - 1]:
            counts[i] = counts[i - 1] + 1
        else:
            counts[i] = 0
    return counts


# ------------------------------------------------------------------
# build picks from kline (non-zt based, scans full market)
# ------------------------------------------------------------------

SIGNALS: list[tuple[str, str]] = [
    ("drop5_-10", "5日跌幅<=-10%"),
    ("drop5_-15", "5日跌幅<=-15%"),
    ("drop5_-20", "5日跌幅<=-20%"),
    ("rsi_lt20", "RSI(14)<20"),
    ("rsi_lt30", "RSI(14)<30"),
    ("below_ma20_5pct", "收盘<MA20*0.95 (破MA20 5%)"),
    ("consec_down_4", "连续4日下跌"),
    ("consec_down_5", "连续5日下跌"),
    ("consec_down_6", "连续6日下跌"),
]


def _check_signal(
    signal_type: str,
    closes: list[float],
    rsi_series: list[float | None],
    ma20_series: list[float | None],
    consec_down: list[int],
    i: int,
) -> bool:
    """Return True if oversold signal triggers at index i."""
    close = closes[i]
    if close <= 0:
        return False

    if signal_type.startswith("drop5_"):
        threshold = -float(signal_type.split("_")[1]) / 100  # e.g. -10 -> -0.10
        if i < 5:
            return False
        prev = closes[i - 5]
        if prev <= 0:
            return False
        return close / prev - 1 <= threshold

    if signal_type == "rsi_lt20":
        rsi = rsi_series[i]
        return rsi is not None and rsi < 20

    if signal_type == "rsi_lt30":
        rsi = rsi_series[i]
        return rsi is not None and rsi < 30

    if signal_type == "below_ma20_5pct":
        ma = ma20_series[i]
        return ma is not None and ma > 0 and close < ma * 0.95

    if signal_type == "consec_down_4":
        return consec_down[i] >= 4
    if signal_type == "consec_down_5":
        return consec_down[i] >= 5
    if signal_type == "consec_down_6":
        return consec_down[i] >= 6

    return False


def build_picks_from_kline(
    code_map: dict[str, dict[str, dict]],
    calendar: list[str],
    signal_type: str,
    regime_map: dict[str, str] | None = None,
    regime_filter: str | None = None,
    min_bars: int = 25,
) -> list[dict]:
    """Scan all codes for oversold signals. Build picks with T+1..T+5 bars.

    Signal computed at close of day T using data up to T (no look-ahead).
    Entry = T+1 open (next trading day's open price).
    Exit = T+N close where N in {2, 3, 5}.

    Filters (§44 v3):
      - Skip ST stocks (distorted limits, survivorship issues)
      - Skip T+1 一字涨停 (can't buy)
      - Skip T+2 一字跌停 (can't sell at exit)

    Returns picks list with keys: code, zt_date (signal date), t1_date,
    t2_date, t3_date, t4_date, t5_date, entry, t1_bar..t5_bar, t_close, lbc.
    """
    date_idx = {d: i for i, d in enumerate(calendar)}
    picks: list[dict] = []

    for code, dmap in code_map.items():
        sorted_dates = sorted(dmap.keys())
        if len(sorted_dates) < min_bars:
            continue

        bars_list = [dmap[d] for d in sorted_dates]
        closes = [b.get("close", 0.0) or 0.0 for b in bars_list]

        # Compute indicators once per code
        rsi_series = compute_rsi_series(closes, 14)
        ma20_series = compute_ma(closes, 20)
        consec_down = compute_consecutive_down(closes)

        # Scan for signals starting from index 20 (need MA20)
        start_idx = max(20, 5)
        for i in range(start_idx, len(sorted_dates)):
            d = sorted_dates[i]

            # Regime filter
            if regime_filter is not None and regime_map is not None:
                r = regime_map.get(d)
                if r != regime_filter:
                    continue

            if not _check_signal(
                signal_type, closes, rsi_series, ma20_series, consec_down, i
            ):
                continue

            # Need T+1 through T+5 in calendar
            d_cal_idx = date_idx.get(d)
            if d_cal_idx is None or d_cal_idx + 5 >= len(calendar):
                continue

            t1_date = calendar[d_cal_idx + 1]
            t2_date = calendar[d_cal_idx + 2]
            t3_date = calendar[d_cal_idx + 3]
            t4_date = calendar[d_cal_idx + 4]
            t5_date = calendar[d_cal_idx + 5]

            t1_bar = dmap.get(t1_date)
            t2_bar = dmap.get(t2_date)
            if t1_bar is None or t2_bar is None:
                continue

            t1_open = t1_bar.get("open")
            t2_close = t2_bar.get("close")
            if t1_open is None or t2_close is None or t1_open <= 0 or t2_close <= 0:
                continue

            # Skip ST stocks
            is_st = bars_list[i].get("isST") == "1"
            if is_st:
                continue

            # Limit calculation
            limit = limit_for_code(code, is_st)
            close = closes[i]

            # Skip T+1 一字涨停 (can't buy)
            if is_yizi_t1(t1_bar, close, limit):
                continue

            # Skip T+2 一字跌停 (can't sell at basic exit)
            if is_yizi_down(t2_bar, close, limit):
                continue

            picks.append({
                "code": code,
                "zt_date": d,  # signal date (key name for walk_forward compat)
                "t1_date": t1_date,
                "t2_date": t2_date,
                "t3_date": t3_date,
                "t4_date": t4_date,
                "t5_date": t5_date,
                "entry": t1_open,
                "t1_bar": t1_bar,
                "t2_bar": t2_bar,
                "t3_bar": dmap.get(t3_date),
                "t4_bar": dmap.get(t4_date),
                "t5_bar": dmap.get(t5_date),
                "t_close": close,
                "lbc": 0,
            })

    return picks


# ------------------------------------------------------------------
# return functions for different hold periods (close_ev, no open_ev)
# ------------------------------------------------------------------

def close_ev_t3(p: dict) -> float | None:
    """Exit at T+3 close. Skip if T+3 一字跌停 (can't sell)."""
    t3 = p.get("t3_bar")
    if t3 is None:
        return None
    c = t3.get("close")
    if c is None or c <= 0:
        return None
    code = p["code"]
    limit = limit_for_code(code)
    if is_yizi_down(t3, p["t_close"], limit):
        return None  # can't sell, skip
    return (c - p["entry"]) / p["entry"] * 100


def close_ev_t5(p: dict) -> float | None:
    """Exit at T+5 close. Skip if T+5 一字跌停 (can't sell)."""
    t5 = p.get("t5_bar")
    if t5 is None:
        return None
    c = t5.get("close")
    if c is None or c <= 0:
        return None
    code = p["code"]
    limit = limit_for_code(code)
    if is_yizi_down(t5, p["t_close"], limit):
        return None
    return (c - p["entry"]) / p["entry"] * 100


def close_ev_stop_t3(
    p: dict, stop_pct: float = STOP_PCT, realistic: bool = True
) -> tuple[float, str] | None:
    """-3% stop + R6, exit T+3 close if no stop hit.

    Checks stop on T+1 (can't sell → T+2 open), T+2, T+3.
    """
    entry = p["entry"]
    stop_px = entry * (1 - stop_pct)
    slip = SLIPPAGE if realistic else 0.0

    t1 = p["t1_bar"]
    t2 = p["t2_bar"]
    t3 = p.get("t3_bar")
    if t3 is None:
        return None

    t1_low = t1.get("low")
    t2_low = t2.get("low")
    t2_open = t2.get("open")
    t3_open = t3.get("open")
    t3_low = t3.get("low")
    t3_close = t3.get("close")
    if None in (t1_low, t2_low, t2_open, t3_open, t3_low, t3_close):
        return None

    # T+1 stop triggered → sell T+2 open (T+1 rule: can't sell entry day)
    if t1_low <= stop_px:
        return (t2_open * (1 - slip) - entry) / entry * 100, "t1_triggered_t2_open"

    # T+2 stop
    if t2_low <= stop_px:
        if t2_open <= stop_px:
            return (t2_open * (1 - slip) - entry) / entry * 100, "t2_gap_stop"
        return (stop_px * (1 - slip) - entry) / entry * 100, "t2_intraday_stop"

    # T+3 stop
    if t3_low <= stop_px:
        if t3_open <= stop_px:
            return (t3_open * (1 - slip) - entry) / entry * 100, "t3_gap_stop"
        return (stop_px * (1 - slip) - entry) / entry * 100, "t3_intraday_stop"

    # No stop hit, exit at T+3 close
    code = p["code"]
    limit = limit_for_code(code)
    if is_yizi_down(t3, p["t_close"], limit):
        # Can't sell at T+3, fallback to T+2 close
        t2_c = t2.get("close")
        if t2_c:
            return (t2_c - entry) / entry * 100, "t3_yizi_fallback_t2"
        return None
    return (t3_close - entry) / entry * 100, "t3_close"


def close_ev_stop_t5(
    p: dict, stop_pct: float = STOP_PCT, realistic: bool = True
) -> tuple[float, str] | None:
    """-3% stop + R6, exit T+5 close if no stop hit.

    Checks stop on T+1, T+2, T+3, T+4, T+5.
    """
    entry = p["entry"]
    stop_px = entry * (1 - stop_pct)
    slip = SLIPPAGE if realistic else 0.0

    t1 = p["t1_bar"]
    t2 = p["t2_bar"]
    t3 = p.get("t3_bar")
    t4 = p.get("t4_bar")
    t5 = p.get("t5_bar")
    if t3 is None or t4 is None or t5 is None:
        return None

    t1_low = t1.get("low")
    t2_low = t2.get("low")
    t2_open = t2.get("open")
    if t1_low is None or t2_low is None or t2_open is None:
        return None

    # T+1 stop → sell T+2 open
    if t1_low <= stop_px:
        return (t2_open * (1 - slip) - entry) / entry * 100, "t1_triggered_t2_open"

    # T+2 stop
    if t2_low <= stop_px:
        if t2_open <= stop_px:
            return (t2_open * (1 - slip) - entry) / entry * 100, "t2_gap_stop"
        return (stop_px * (1 - slip) - entry) / entry * 100, "t2_intraday_stop"

    # Check T+3, T+4, T+5 stops
    for day_idx in range(3, 6):
        bar = {3: t3, 4: t4, 5: t5}[day_idx]
        if bar is None:
            continue
        bar_low = bar.get("low")
        bar_open = bar.get("open")
        if bar_low is None or bar_open is None:
            continue
        if bar_low <= stop_px:
            if bar_open <= stop_px:
                return (
                    (bar_open * (1 - slip) - entry) / entry * 100,
                    f"t{day_idx}_gap_stop",
                )
            return (
                (stop_px * (1 - slip) - entry) / entry * 100,
                f"t{day_idx}_intraday_stop",
            )

    # No stop hit, exit at T+5 close
    t5_close = t5.get("close")
    if t5_close is None or t5_close <= 0:
        return None
    code = p["code"]
    limit = limit_for_code(code)
    if is_yizi_down(t5, p["t_close"], limit):
        # Fallback to T+3 close
        t3_close = t3.get("close")
        if t3_close:
            return (t3_close - entry) / entry * 100, "t5_yizi_fallback_t3"
        return None
    return (t5_close - entry) / entry * 100, "t5_close"


# ------------------------------------------------------------------
# per-subset analysis (mirrors _factor_helpers.analyze_subset but with
# custom return functions for T+3/T+5 holds)
# ------------------------------------------------------------------

def analyze_hold_variant(
    name: str,
    picks: list[dict],
    ret_fn_basic,
    ret_fn_stop,
    hold_label: str,
) -> dict:
    """Analyze one sub-strategy × hold period combination."""
    print(f"\n{'=' * 70}")
    print(f"[{hold_label}] {name} (n_picks={len(picks)})")
    print(f"{'=' * 70}")

    if not picks:
        print("  无 picks, 跳过")
        return {"name": name, "hold": hold_label, "n_picks": 0}

    # ---- basic EV (no stop) ----
    basic_rets = [ret_fn_basic(p) for p in picks]
    basic_rets = [r for r in basic_rets if r is not None]
    basic_s = ev_stats(basic_rets)
    net_basic = basic_s["ev"] - COST * 100
    print(f"\n--- basic close_ev (no stop) ---")
    print(f"  n={basic_s['n']} gross_EV={basic_s['ev']}% std={basic_s['std']}% "
          f"WR={basic_s['wr']}% t={basic_s['t']} CI[{basic_s['ci_lo']},{basic_s['ci_hi']}]")
    print(f"  net EV (after {COST*100:.1f}% cost): {net_basic:.3f}%")

    # day-paired t
    basic_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        r = ret_fn_basic(p)
        if r is not None:
            basic_by_date[p["zt_date"]].append(r)
    basic_dt = day_paired_t(basic_by_date)
    print(f"  day-paired: n_days={basic_dt['n_days']} mean={basic_dt['mean']}% "
          f"t={basic_dt['t']} p_one_sided={basic_dt['p_one_sided']}")

    # ---- stop variant ----
    print(f"\n--- stop variant (-{STOP_PCT*100:.0f}% stop + R6 gap-through) ---")
    stop_rets = [ret_fn_stop(p) for p in picks]
    stop_rets_clean = [r[0] for r in stop_rets if r is not None]
    stop_s = ev_stats(stop_rets_clean)
    net_stop = stop_s["ev"] - COST * 100
    print(f"  n={stop_s['n']} gross_EV={stop_s['ev']}% std={stop_s['std']}% "
          f"WR={stop_s['wr']}% t={stop_s['t']} CI[{stop_s['ci_lo']},{stop_s['ci_hi']}]")
    print(f"  net EV (after cost): {net_stop:.3f}%")

    stop_reasons: dict[str, int] = defaultdict(int)
    for p in picks:
        r = ret_fn_stop(p)
        if r is not None:
            stop_reasons[r[1]] += 1
    total_r = sum(stop_reasons.values())
    if total_r > 0:
        print(f"  exit reasons:")
        for rsn, cnt in sorted(stop_reasons.items(), key=lambda x: -x[1]):
            print(f"    {rsn}: {cnt} ({cnt/max(total_r,1)*100:.1f}%)")

    stop_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        r = ret_fn_stop(p)
        if r is not None:
            stop_by_date[p["zt_date"]].append(r[0])
    stop_dt = day_paired_t(stop_by_date)
    print(f"  day-paired: n_days={stop_dt['n_days']} mean={stop_dt['mean']}% "
          f"t={stop_dt['t']} p_one_sided={stop_dt['p_one_sided']}")

    # ---- walk-forward OOS ----
    print(f"\n--- walk-forward OOS (basic, 前半 train → 后半 test) ---")
    wf = walk_forward(picks, ret_fn_basic)
    wf_train_ev = 0.0
    wf_test_ev = 0.0
    wf_test_p = 1.0
    if wf["status"] == "ok":
        tr = wf["train_ev"]
        te = wf["test_ev"]
        tr_dt = wf["train_day_t"]
        te_dt = wf["test_day_t"]
        wf_train_ev = tr["ev"]
        wf_test_ev = te["ev"]
        wf_test_p = te_dt["p_one_sided"]
        print(f"  train: n={tr['n']} n_dates={wf['n_train_dates']} "
              f"EV={tr['ev']}% t={tr['t']} day_t={tr_dt['t']}")
        print(f"  test:  n={te['n']} n_dates={wf['n_test_dates']} "
              f"EV={te['ev']}% t={te['t']} day_t={te_dt['t']} "
              f"p={te_dt['p_one_sided']}")
        decay = ((tr["ev"] - te["ev"]) / abs(tr["ev"]) * 100
                 if tr["ev"] != 0 else 0)
        print(f"  decay: {decay:.0f}% (train→test)")
    else:
        print(f"  {wf['status']} (n_dates={wf.get('n_dates', 0)})")

    return {
        "name": name,
        "hold": hold_label,
        "n_picks": len(picks),
        "n_days": basic_dt["n_days"],
        "basic_ev_gross": basic_s["ev"],
        "basic_ev_net": net_basic,
        "basic_day_t": basic_dt["t"],
        "basic_p_raw": basic_dt["p_one_sided"],
        "stop_ev_gross": stop_s["ev"],
        "stop_ev_net": net_stop,
        "stop_day_t": stop_dt["t"],
        "stop_p_raw": stop_dt["p_one_sided"],
        "wf_status": wf["status"],
        "wf_train_ev": wf_train_ev,
        "wf_test_ev": wf_test_ev,
        "wf_test_p": wf_test_p,
    }


# ------------------------------------------------------------------
# DSR (Deflated Sharpe Ratio) — simple implementation
# ------------------------------------------------------------------

def compute_dsr(
    rets: list[float],
    n_trials: int,
    cost_pct: float = COST * 100,
) -> dict:
    """Compute Deflated Sharpe Ratio (Bailey & López de Prado 2014).

    Corrects observed Sharpe for multiple testing (n_trials) and
    non-normality (skew, kurtosis).

    Returns DSR and related metrics. DSR > 0.95 → likely true edge.
    """
    n = len(rets)
    if n < 10:
        return {"dsr": 0.0, "sr_obs": 0.0, "sr_deflated": 0.0, "n": n, "note": "too few samples"}

    # Convert percent returns to decimal
    r = [x / 100 for x in rets]
    mean_r = sum(r) / n
    std_r = statistics.pstdev(r) if n > 1 else 0.0
    if std_r == 0:
        return {"dsr": 0.0, "sr_obs": 0.0, "sr_deflated": 0.0, "n": n, "note": "zero std"}

    # Annualized Sharpe (per-trade → annualized by sqrt(n_per_year))
    # Assuming ~250 trading days/year, and these are per-trade returns
    sr_obs = mean_r / std_r * sqrt(250)

    # Skewness and kurtosis (excess)
    if n > 3:
        skew = sum((x - mean_r) ** 3 for x in r) / (n * std_r ** 3)
        kurt = sum((x - mean_r) ** 4 for x in r) / (n * std_r ** 4) - 3
    else:
        skew = 0.0
        kurt = 0.0

    # Expected max Sharpe under H0 (all trials are noise)
    # SR_0 = sqrt(Variance) * ((1-γ)*Φ^{-1}(1-1/N) + γ*Φ^{-1}(1-1/(N*e)))
    # where γ ≈ 0.5772 (Euler-Mascheroni constant)
    from math import log, sqrt as msqrt, pi
    euler_gamma = 0.5772156649

    def norm_ppf(p: float) -> float:
        """Inverse CDF of standard normal (approximation)."""
        if p <= 0:
            return -10
        if p >= 1:
            return 10
        # Beasley-Springer-Moro approximation
        a = [-3.969683028665376e+01, 2.209460984245205e+02,
             -2.759285104469687e+02, 1.383577518672690e+02,
             -3.066479806614716e+01, 2.506628277459239e+00]
        b = [-5.447609879822406e+01, 1.615858368580409e+02,
             -1.556989798598866e+02, 6.680131188771972e+01,
             -1.328068155288572e+01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01,
             -2.400758277161838e+00, -2.549732539343734e+00,
             4.374664141444968e+00, 2.938163982698783e+00]
        d = [7.784695709041462e-03, 3.224671290700398e-01,
             2.445134137142996e+00, 3.754408661907416e+00]
        p_low = 0.02425
        p_high = 1 - p_low
        if p < p_low:
            q = msqrt(-2 * log(p))
            x = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        elif p <= p_high:
            q = p - 0.5
            r_val = q * q
            x = (((((a[0]*r_val+a[1])*r_val+a[2])*r_val+a[3])*r_val+a[4])*r_val+a[5]) * q / \
                (((((b[0]*r_val+b[1])*r_val+b[2])*r_val+b[3])*r_val+b[4])*r_val+1)
        else:
            q = msqrt(-2 * log(1 - p))
            x = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        return x

    # SR_0 = expected max Sharpe under H0
    z1 = norm_ppf(1 - 1 / n_trials)
    z2 = norm_ppf(1 - 1 / (n_trials * 2.718281828))
    sr_0 = sqrt(250) * ((1 - euler_gamma) * z1 + euler_gamma * z2) / sqrt(250)
    # Simpler: SR_0 ≈ sqrt(2*ln(n_trials)) * sqrt(annualization)
    # Use the standard formula: SR_0 = sqrt(2*ln(N)) * (annualization factor)
    # But the exact formula is more nuanced. Let's use the approximation.
    sr_0_annual = sqrt(2 * log(n_trials)) * sqrt(1)  # per-trade, not annualized

    # SR_deflated = (SR_obs - SR_0) * correction for skew/kurt
    # DSR = Φ(SR_deflated * sqrt(T) / sqrt(1 + skew*SR + (kurt-1)/4 * SR^2))
    # Using the per-trade Sharpe (not annualized) for DSR formula
    sr_per_trade = mean_r / std_r
    T = n
    numerator = (sr_per_trade - sr_0_annual) * sqrt(T)
    denominator_sq = 1 + skew * sr_per_trade + (kurt / 4) * sr_per_trade ** 2
    denominator = sqrt(max(denominator_sq, 0.01))
    z_dsr = numerator / denominator
    dsr = 0.5 * (1 + erf(z_dsr / sqrt(2)))

    return {
        "dsr": round(dsr, 4),
        "sr_obs": round(sr_obs, 3),
        "sr_0": round(sr_0_annual, 4),
        "skew": round(skew, 3),
        "kurt_excess": round(kurt, 3),
        "n_trials": n_trials,
        "n": n,
    }


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("短线策略探索: 均值回归/超跌反弹 (mean-reversion/oversold bounce)")
    print("§44 v3 过严口径: close_ev / per-day-t / Bonferroni / walk-forward OOS")
    print("=" * 70)

    # ---- load data ----
    print("\n[1] 加载 kline cache + regime 标签...")
    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    print(f"  codes: {len(code_map)}, trading days: {len(calendar)}")
    print(f"  calendar range: {calendar[0]} ~ {calendar[-1]}")

    regime_data = json.loads(REGIME_PATH.read_text())
    regime_map: dict[str, str] = {
        d: v.get("regime", "unknown") for d, v in regime_data.items()
    }
    regime_2018 = {d: r for d, r in regime_map.items() if d >= "2018-01-01"}
    from collections import Counter
    rc = Counter(regime_2018.values())
    print(f"  regime (2018+): strong={rc.get('strong', 0)}, weak={rc.get('weak', 0)}")

    # ---- main sweep: 9 signals × T+2 hold × all regime ----
    print(f"\n[2] 主 sweep: {N_SIGNALS} 信号 × T+2 hold × all regime")
    print(f"    Bonferroni n_cross_factor = {N_CROSS_FACTOR} (×{N_CROSS_FACTOR*2} tests)")
    print()

    results: list[dict] = []
    best_net_ev = -999.0
    best_signal = None
    best_picks = None

    for signal_name, signal_desc in SIGNALS:
        picks = build_picks_from_kline(code_map, calendar, signal_name, regime_map)
        r = analyze_hold_variant(
            f"{signal_name} ({signal_desc})",
            picks,
            close_ev_basic,
            close_ev_stop,
            "T+2 (1日持有)",
        )
        results.append(r)

        # Track best for further analysis
        if r.get("basic_ev_net", -999) > best_net_ev:
            best_net_ev = r["basic_ev_net"]
            best_signal = signal_name
            best_picks = picks

        # Per-signal verdict
        if r["n_picks"] > 0:
            verdict_for(
                ev_gross=r["basic_ev_gross"],
                t_day=r["basic_day_t"],
                p_raw=r["basic_p_raw"],
                wf_status=r["wf_status"],
                wf_train_ev=r["wf_train_ev"],
                wf_test_ev=r["wf_test_ev"],
                wf_test_p=r["wf_test_p"],
                n_days=r["n_days"],
                net_ev=r["basic_ev_net"],
                subset_name=f"  {signal_name} (T+2, all-regime)",
                n_cross_factor=N_CROSS_FACTOR,
            )

    # ---- summary table ----
    print(f"\n\n{'=' * 70}")
    print(f"[3] 主 sweep 汇总表 (T+2 hold, all regime)")
    print(f"{'=' * 70}")
    print(f"{'signal':<25} {'n_picks':>8} {'n_days':>7} {'gross%':>8} {'net%':>8} "
          f"{'day_t':>7} {'p_raw':>9} {'Bonf':>9} {'wf_tr':>7} {'wf_te':>7} {'wf_p':>9}")
    print("-" * 120)
    for r in results:
        if r["n_picks"] == 0:
            continue
        p_bonf = bonferroni_p(r["basic_p_raw"], N_CROSS_FACTOR * 2)
        print(f"{r['name'][:25]:<25} {r['n_picks']:>8} {r['n_days']:>7} "
              f"{r['basic_ev_gross']:>8.3f} {r['basic_ev_net']:>8.3f} "
              f"{r['basic_day_t']:>7.2f} {r['basic_p_raw']:>9.6f} {p_bonf:>9.6f} "
              f"{r['wf_train_ev']:>7.3f} {r['wf_test_ev']:>7.3f} {r['wf_test_p']:>9.6f}")
    print()

    # ---- hold variants for best signal ----
    if best_signal and best_picks and len(best_picks) > 0:
        print(f"\n{'=' * 70}")
        print(f"[4] 持有期变体: best signal = {best_signal} (n={len(best_picks)})")
        print(f"{'=' * 70}")

        hold_results: list[dict] = []
        for hold_label, ret_basic, ret_stop in [
            ("T+2 (1日持有)", close_ev_basic, close_ev_stop),
            ("T+3 (2日持有)", close_ev_t3, close_ev_stop_t3),
            ("T+5 (4日持有)", close_ev_t5, close_ev_stop_t5),
        ]:
            r = analyze_hold_variant(
                f"{best_signal}",
                best_picks,
                ret_basic,
                ret_stop,
                hold_label,
            )
            hold_results.append(r)
            if r["n_picks"] > 0:
                verdict_for(
                    ev_gross=r["basic_ev_gross"],
                    t_day=r["basic_day_t"],
                    p_raw=r["basic_p_raw"],
                    wf_status=r["wf_status"],
                    wf_train_ev=r["wf_train_ev"],
                    wf_test_ev=r["wf_test_ev"],
                    wf_test_p=r["wf_test_p"],
                    n_days=r["n_days"],
                    net_ev=r["basic_ev_net"],
                    subset_name=f"  {best_signal} ({hold_label})",
                    n_cross_factor=N_CROSS_FACTOR,
                )

        # ---- regime splits for best signal × best hold ----
        # Find best hold variant
        best_hold_r = max(hold_results, key=lambda x: x.get("basic_ev_net", -999))
        best_hold_label = best_hold_r["hold"]

        print(f"\n{'=' * 70}")
        print(f"[5] Regime 分层: {best_signal} × {best_hold_label}")
        print(f"{'=' * 70}")

        hold_fns = {
            "T+2 (1日持有)": (close_ev_basic, close_ev_stop),
            "T+3 (2日持有)": (close_ev_t3, close_ev_stop_t3),
            "T+5 (4日持有)": (close_ev_t5, close_ev_stop_t5),
        }
        ret_basic_best, ret_stop_best = hold_fns.get(best_hold_label, (close_ev_basic, close_ev_stop))

        for regime_filter in ["strong", "weak"]:
            picks_regime = build_picks_from_kline(
                code_map, calendar, best_signal, regime_map, regime_filter
            )
            r = analyze_hold_variant(
                f"{best_signal} ({regime_filter})",
                picks_regime,
                ret_basic_best,
                ret_stop_best,
                f"{best_hold_label} [{regime_filter}]",
            )
            if r["n_picks"] > 0:
                verdict_for(
                    ev_gross=r["basic_ev_gross"],
                    t_day=r["basic_day_t"],
                    p_raw=r["basic_p_raw"],
                    wf_status=r["wf_status"],
                    wf_train_ev=r["wf_train_ev"],
                    wf_test_ev=r["wf_test_ev"],
                    wf_test_p=r["wf_test_p"],
                    n_days=r["n_days"],
                    net_ev=r["basic_ev_net"],
                    subset_name=f"  {best_signal} ({best_hold_label}, {regime_filter})",
                    n_cross_factor=N_CROSS_FACTOR,
                )

        # ---- DSR for best signal × T+2 ----
        print(f"\n{'=' * 70}")
        print(f"[6] DSR (Deflated Sharpe Ratio) — 过拟合检测")
        print(f"{'=' * 70}")
        best_t2_rets = [close_ev_basic(p) for p in best_picks]
        best_t2_rets = [r for r in best_t2_rets if r is not None]
        dsr_result = compute_dsr(best_t2_rets, n_trials=N_CROSS_FACTOR)
        print(f"  {best_signal} T+2: DSR={dsr_result.get('dsr', 0)} "
              f"SR_obs={dsr_result.get('sr_obs', 0)} SR_0={dsr_result.get('sr_0', 0)} "
              f"skew={dsr_result.get('skew', 0)} kurt={dsr_result.get('kurt_excess', 0)} "
              f"n_trials={dsr_result.get('n_trials', 0)} n={dsr_result.get('n', 0)}")
        if dsr_result.get("dsr", 0) > 0.95:
            print(f"  → DSR > 0.95: Sharpe 可能在多重测试后仍显著 (低过拟合风险)")
        else:
            print(f"  → DSR <= 0.95: Sharpe 可能在多重测试后不显著 (高过拟合风险)")

    # ---- final summary ----
    print(f"\n\n{'=' * 70}")
    print(f"[7] 最终总结")
    print(f"{'=' * 70}")
    print(f"  策略: 均值回归/超跌反弹 (mean-reversion/oversold bounce)")
    print(f"  信号数: {N_SIGNALS} (5日跌幅×3 + RSI×2 + 破MA20×1 + 连阴×3)")
    print(f"  持有期: T+2/T+3/T+5 (1/2/4 日持有)")
    print(f"  Bonferroni n_cross_factor: {N_CROSS_FACTOR} (×{N_CROSS_FACTOR*2} tests)")
    print(f"  数据: {len(code_map)} codes, {len(calendar)} trading days "
          f"({calendar[0]}~{calendar[-1]})")

    # Count results
    n_falsified = sum(1 for r in results if r["n_picks"] > 0 and r["basic_ev_gross"] < 0)
    n_positive_gross = sum(1 for r in results if r["n_picks"] > 0 and r["basic_ev_gross"] > 0)
    n_positive_net = sum(1 for r in results if r["n_picks"] > 0 and r["basic_ev_net"] > 0)
    print(f"  结果: {n_falsified}/{len([r for r in results if r['n_picks']>0])} gross EV < 0, "
          f"{n_positive_gross} gross EV > 0, {n_positive_net} net EV > 0")

    if best_signal:
        best_r = next(r for r in results if r["name"].startswith(best_signal))
        print(f"\n  最佳信号: {best_signal}")
        print(f"    n_picks={best_r['n_picks']} n_days={best_r['n_days']}")
        print(f"    gross EV={best_r['basic_ev_gross']}% net EV={best_r['basic_ev_net']}%")
        print(f"    day_t={best_r['basic_day_t']} p_raw={best_r['basic_p_raw']}")
        p_bonf = bonferroni_p(best_r["basic_p_raw"], N_CROSS_FACTOR * 2)
        print(f"    Bonferroni p(×{N_CROSS_FACTOR*2})={p_bonf}")
        print(f"    walk-forward: train={best_r['wf_train_ev']}% test={best_r['wf_test_ev']}% "
              f"test_p={best_r['wf_test_p']}")
        if dsr_result:
            print(f"    DSR={dsr_result.get('dsr', 0)} (n_trials={N_CROSS_FACTOR})")

    print(f"\n  禁止外推: 本测试仅覆盖超跌反弹均值回归, 不代表短线策略整体有/无 edge")
    print(f"  局限性: 收盘价未复权 (除权日可能假信号但阈值>=10%影响小), "
          f"非组合级 (无再平衡), 仅日线粒度")


if __name__ == "__main__":
    main()
