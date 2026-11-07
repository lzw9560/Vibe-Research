# -*- coding: utf-8 -*-
"""短线策略探索: 窒息量低吸 (suffocation-volume mean-reversion sub-signal)

策略: 全市场扫描——连跌 N 日后成交量萎缩至 5 日均量 30% 以下 (窒息量),
      T 收盘买, T+1 开盘卖 (隔夜 gap 捕获反弹).

机制: 量缩非 RSI 超卖——成交量枯竭是不同子信号 (卖方力量衰竭 vs 价格超跌).
      先验: 均值回归家族已 falsified (RSI 9/9 Bonf fail), 本信号是同族不同子信号.

过严口径 (§44 v3):
  - entry = T close (隔夜 gap) 或 T+1 open (close_ev 标准, 双口径对比)
  - close_ev 非 open_ev (防日内泄漏)
  - BHAR gate (隔夜 gap 减市场隔夜 gap 基准, isolate alpha 非 beta)
  - 一字涨停跳过 (T+1 open 口径, 买不进)
  - 一字跌停跳过 (T+N close 口径, 卖不出)
  - per-day-mean t (同日 picks 聚 day-mean, 非 per-trade t)
  - Bonferroni cross-strategy ×5 + within-strategy ×3(N) = ×15
  - walk-forward OOS + train_ev>0 检查
  - -3% stop + R6 gap-through fill (close_ev 口径)
  - DSR (Deflated Sharpe Ratio) 过拟合检测
  - 除权日过滤 (robustness: kline 未复价, ex-div 日有假 gap)
  - 禁止外推: 单策略 ≠ 短线有/无 edge

跑法:
  cd backend && .venv/bin/python tools/explore_shortterm_suffocation-volume.py
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

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
REGIME_PATH = resolve_data_dir() / "index_ma20_regime.json"
DIVIDEND_PATH = resolve_data_dir() / "dividend_events_cache.json"

# Bonferroni: 3 N-variants × 5 cross-strategy = 15 (×2 subsets = 30 tests)
# Hold periods + vol thresholds are sensitivity, not independent hypotheses
N_VARIANTS = 3  # N_down = 3, 4, 5
N_CROSS_STRATEGY = 5
N_CROSS_FACTOR = N_VARIANTS * N_CROSS_STRATEGY  # 15

VOL_RATIO_THRESH = 0.30  # volume < 30% of 5-day average = suffocation
MIN_BARS = 25  # need at least 5 bars for vol avg + 20 for indicators


# ------------------------------------------------------------------
# 一字跌停检测 (can't sell on exit day) — from mean-reversion script
# ------------------------------------------------------------------


def is_yizi_down(bar: dict, prev_close: float, limit: float) -> bool:
    """一字跌停: open 和 high 都在跌停价附近 (locked at limit-down, 卖不出)."""
    lim_down = prev_close * (1 - limit)
    o = bar.get("open")
    h = bar.get("high")
    if o is None or h is None or lim_down <= 0:
        return False
    return abs(o - lim_down) / lim_down < 0.005 and abs(h - lim_down) / lim_down < 0.005


# ------------------------------------------------------------------
# market benchmark precompute (equal-weighted cross-section)
# ------------------------------------------------------------------


def precompute_market_benchmarks(
    code_map: dict[str, dict[str, dict]],
) -> tuple[dict[str, float], dict[str, float]]:
    """Precompute equal-weighted market overnight-gap and close-to-close per date.

    market_gap[date] = mean over all stocks of (T+1 open - T close) / T close
    market_cc[date]  = mean over all stocks of (T+1 close - T close) / T close

    Used as BHAR benchmark: BHAR = stock_return - market_return(same date).
    """
    gap_sum: dict[str, float] = defaultdict(float)
    gap_cnt: dict[str, int] = defaultdict(int)
    cc_sum: dict[str, float] = defaultdict(float)
    cc_cnt: dict[str, int] = defaultdict(int)

    for code, dm in code_map.items():
        sdates = sorted(dm.keys())
        for i in range(len(sdates) - 1):
            d = sdates[i]
            d1 = sdates[i + 1]
            tc = dm[d].get("close", 0) or 0
            t1o = dm[d1].get("open", 0) or 0
            t1c = dm[d1].get("close", 0) or 0
            if tc > 0 and t1o > 0:
                gap_sum[d] += (t1o - tc) / tc * 100
                gap_cnt[d] += 1
            if tc > 0 and t1c > 0:
                cc_sum[d] += (t1c - tc) / tc * 100
                cc_cnt[d] += 1

    market_gap = {d: gap_sum[d] / gap_cnt[d] for d in gap_cnt if gap_cnt[d] > 0}
    market_cc = {d: cc_sum[d] / cc_cnt[d] for d in cc_cnt if cc_cnt[d] > 0}
    return market_gap, market_cc


# ------------------------------------------------------------------
# build picks: suffocation signal (non-zt, scans full market)
# ------------------------------------------------------------------


def build_picks_suffocation(
    code_map: dict[str, dict[str, dict]],
    calendar: list[str],
    n_down: int = 3,
    vol_ratio_thresh: float = VOL_RATIO_THRESH,
    filter_ex_div: bool = False,
    ex_div_dates: set[str] | None = None,
    min_price: float = 0.0,
    regime_map: dict[str, str] | None = None,
    regime_filter: str | None = None,
) -> list[dict]:
    """Scan all codes for suffocation signals. Build picks with T, T+1, T+2, T+5 bars.

    Signal (computed at close of day T, no look-ahead):
      1. n_down consecutive close-to-close declines ending at day T
      2. volume[T] / mean(volume[T-5..T-1]) < vol_ratio_thresh  (suffocation)

    Entry/exit (dual口径):
      - overnight gap: entry=T close, exit=T+1 open  (task's stated exit)
      - close_ev:      entry=T+1 open, exit=T+2 close (§44 standard)

    Filters (§44 v3):
      - Skip T+1 一字涨停 (can't buy, for close_ev口径)
      - Skip T+2 一字跌停 (can't sell, for close_ev口径)
      - Optional: skip ex-div dates (unadjusted price confound)
      - Optional: skip low-priced stocks (pathological illiquidity)

    Returns picks list with keys: code, zt_date (signal date), t1_date,
    t2_date, t5_date, entry (T+1 open), t_close, t1_bar, t2_bar, t5_bar,
    vol_ratio, n_down_streak.
    """
    date_idx = {d: i for i, d in enumerate(calendar)}
    picks: list[dict] = []

    for code, dm in code_map.items():
        sdates = sorted(dm.keys())
        if len(sdates) < MIN_BARS:
            continue

        # compute consecutive down count
        downs = [0] * len(sdates)
        for i in range(1, len(sdates)):
            c0 = dm[sdates[i - 1]].get("close", 0) or 0
            c1 = dm[sdates[i]].get("close", 0) or 0
            if c1 < c0 and c0 > 0:
                downs[i] = downs[i - 1] + 1
            else:
                downs[i] = 0

        for i in range(5, len(sdates)):
            if downs[i] < n_down:
                continue

            # volume ratio: today / mean(past 5 days), no look-ahead
            vols = [dm[sdates[j]].get("volume", 0) or 0 for j in range(i - 5, i)]
            avg5 = sum(vols) / 5 if vols else 0
            vol_today = dm[sdates[i]].get("volume", 0) or 0
            if avg5 <= 0:
                continue
            vol_ratio = vol_today / avg5
            if vol_ratio >= vol_ratio_thresh:
                continue

            d = sdates[i]
            t_bar = dm[d]
            t_close = t_bar.get("close", 0) or 0
            if t_close <= 0:
                continue

            # price filter
            if t_close < min_price:
                continue

            # ex-div filter
            if filter_ex_div and ex_div_dates and d in ex_div_dates:
                continue

            # regime filter
            if regime_filter is not None and regime_map is not None:
                r = regime_map.get(d)
                if r != regime_filter:
                    continue

            # need T+1, T+2, T+5 in calendar (actual next trading days)
            d_ci = date_idx.get(d)
            if d_ci is None or d_ci + 5 >= len(calendar):
                continue

            t1_date = calendar[d_ci + 1]
            t2_date = calendar[d_ci + 2]
            t3_date = calendar[d_ci + 3]
            t4_date = calendar[d_ci + 4]
            t5_date = calendar[d_ci + 5]

            t1_bar = dm.get(t1_date)
            t2_bar = dm.get(t2_date)
            if t1_bar is None or t2_bar is None:
                continue  # suspended, skip

            t1_open = t1_bar.get("open", 0) or 0
            t2_close = t2_bar.get("close", 0) or 0
            if t1_open <= 0 or t2_close <= 0:
                continue

            # ST status (may be missing for 2018-2023, default non-ST)
            is_st = t_bar.get("isST") == "1"
            limit = limit_for_code(code, is_st)

            # Skip T+1 一字涨停 (can't buy, for close_ev口径)
            if is_yizi_t1(t1_bar, t_close, limit):
                continue

            picks.append(
                {
                    "code": code,
                    "zt_date": d,  # signal date (key name for walk_forward compat)
                    "t1_date": t1_date,
                    "t2_date": t2_date,
                    "t3_date": t3_date,
                    "t4_date": t4_date,
                    "t5_date": t5_date,
                    "entry": t1_open,  # T+1 open (for close_ev口径)
                    "t1_bar": t1_bar,
                    "t2_bar": t2_bar,
                    "t3_bar": dm.get(t3_date),
                    "t4_bar": dm.get(t4_date),
                    "t5_bar": dm.get(t5_date),
                    "t_close": t_close,  # T close (for overnight gap口径)
                    "t_bar": t_bar,
                    "vol_ratio": vol_ratio,
                    "n_down_streak": downs[i],
                    "lbc": 0,
                }
            )

    return picks


# ------------------------------------------------------------------
# return functions
# ------------------------------------------------------------------


def overnight_gap_ev(p: dict) -> float | None:
    """Overnight gap: entry=T close, exit=T+1 open.

    This is the task's stated exit (T收盘买, T+1开盘卖).
    Captures ONLY the overnight gap — cleanest measure, no intraday leakage.
    """
    t_close = p["t_close"]
    t1_open = p["t1_bar"].get("open", 0) or 0
    if t_close <= 0 or t1_open <= 0:
        return None
    return (t1_open - t_close) / t_close * 100


def overnight_gap_bhar(p: dict, market_gap: dict[str, float]) -> float | None:
    """BHAR-adjusted overnight gap: stock gap - market gap (same date)."""
    raw = overnight_gap_ev(p)
    if raw is None:
        return None
    mkt = market_gap.get(p["zt_date"], 0.0)
    return raw - mkt


def close_ev_t2(p: dict) -> float | None:
    """T+1 open → T+2 close. Standard §44 close_ev (1-day hold)."""
    return close_ev_basic(p)


def close_ev_t5(p: dict) -> float | None:
    """T+1 open → T+5 close. Skip if T+5 一字跌停 (can't sell)."""
    t5 = p.get("t5_bar")
    if t5 is None:
        return None
    c = t5.get("close", 0) or 0
    if c <= 0:
        return None
    code = p["code"]
    limit = limit_for_code(code)
    if is_yizi_down(t5, p["t_close"], limit):
        return None
    return (c - p["entry"]) / p["entry"] * 100


def close_ev_stop_t5(p: dict, stop_pct: float = STOP_PCT, realistic: bool = True) -> tuple[float, str] | None:
    """-3% stop + R6, exit T+5 close if no stop hit.

    Checks stop on T+1 (can't sell → T+2 open), T+2..T+5.
    """
    entry = p["entry"]
    stop_px = entry * (1 - stop_pct)
    slip = SLIPPAGE if realistic else 0.0

    t1 = p["t1_bar"]
    t2 = p["t2_bar"]
    t1_low = t1.get("low")
    t2_low = t2.get("low")
    t2_open = t2.get("open")
    if t1_low is None or t2_low is None or t2_open is None:
        return None

    # T+1 stop → sell T+2 open (T+1 rule: can't sell entry day)
    if t1_low <= stop_px:
        return (t2_open * (1 - slip) - entry) / entry * 100, "t1_triggered_t2_open"

    # T+2 stop
    if t2_low <= stop_px:
        if t2_open <= stop_px:
            return (t2_open * (1 - slip) - entry) / entry * 100, "t2_gap_stop"
        return (stop_px * (1 - slip) - entry) / entry * 100, "t2_intraday_stop"

    # Check T+3, T+4, T+5 stops
    code = p["code"]
    limit = limit_for_code(code)
    bars_by_day = {3: p.get("t3_bar"), 4: p.get("t4_bar"), 5: p.get("t5_bar")}
    for day_off in range(3, 6):
        bar = bars_by_day.get(day_off)
        if bar is None:
            continue
        bar_low = bar.get("low")
        bar_open = bar.get("open")
        if bar_low is None or bar_open is None:
            continue
        if bar_low <= stop_px:
            if bar_open <= stop_px:
                return (bar_open * (1 - slip) - entry) / entry * 100, f"t{day_off}_gap_stop"
            return (stop_px * (1 - slip) - entry) / entry * 100, f"t{day_off}_intraday_stop"

    # No stop hit, exit at T+5 close
    t5 = p.get("t5_bar")
    if t5 is None:
        return None
    t5_close = t5.get("close", 0) or 0
    if t5_close <= 0:
        return None
    if is_yizi_down(t5, p["t_close"], limit):
        return None
    return (t5_close - entry) / entry * 100, "t5_close"


# ------------------------------------------------------------------
# DSR (Deflated Sharpe Ratio) — from mean-reversion script
# ------------------------------------------------------------------


def compute_dsr(rets: list[float], n_trials: int) -> dict:
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014)."""
    n = len(rets)
    if n < 10:
        return {"dsr": 0.0, "sr_obs": 0.0, "sr_0": 0.0, "n": n, "note": "too few samples"}

    r = [x / 100 for x in rets]
    mean_r = sum(r) / n
    std_r = statistics.pstdev(r) if n > 1 else 0.0
    if std_r == 0:
        return {"dsr": 0.0, "sr_obs": 0.0, "sr_0": 0.0, "n": n, "note": "zero std"}

    sr_obs = mean_r / std_r * sqrt(250)

    if n > 3:
        skew = sum((x - mean_r) ** 3 for x in r) / (n * std_r**3)
        kurt = sum((x - mean_r) ** 4 for x in r) / (n * std_r**4) - 3
    else:
        skew = 0.0
        kurt = 0.0

    from math import log, sqrt as msqrt

    euler_gamma = 0.5772156649

    def norm_ppf(p: float) -> float:
        if p <= 0:
            return -10
        if p >= 1:
            return 10
        a = [
            -3.969683028665376e01,
            2.209460984245205e02,
            -2.759285104469687e02,
            1.383577518672690e02,
            -3.066479806614716e01,
            2.506628277459239e00,
        ]
        b = [
            -5.447609879822406e01,
            1.615858368580409e02,
            -1.556989798598866e02,
            6.680131188771972e01,
            -1.328068155288572e01,
        ]
        c = [
            -7.784894002430293e-03,
            -3.223964580411365e-01,
            -2.400758277161838e00,
            -2.549732539343734e00,
            4.374664141444968e00,
            2.938163982698783e00,
        ]
        d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
        p_low = 0.02425
        p_high = 1 - p_low
        if p < p_low:
            q = msqrt(-2 * log(p))
            x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        elif p <= p_high:
            q = p - 0.5
            rv = q * q
            x = (
                (((((a[0] * rv + a[1]) * rv + a[2]) * rv + a[3]) * rv + a[4]) * rv + a[5])
                * q
                / (((((b[0] * rv + b[1]) * rv + b[2]) * rv + b[3]) * rv + b[4]) * rv + 1)
            )
        else:
            q = msqrt(-2 * log(1 - p))
            x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        return x

    sr_0_annual = sqrt(2 * log(max(n_trials, 2)))
    sr_per_trade = mean_r / std_r
    T = n
    numerator = (sr_per_trade - sr_0_annual) * sqrt(T)
    denominator_sq = 1 + skew * sr_per_trade + (kurt / 4) * sr_per_trade**2
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
# analysis for one variant
# ------------------------------------------------------------------


def analyze_variant(
    name: str,
    picks: list[dict],
    ret_fn_basic,
    ret_fn_stop,
    hold_label: str,
    market_gap: dict[str, float] | None = None,
    use_bhar: bool = False,
) -> dict:
    """Analyze one sub-strategy × hold period combination.

    If use_bhar=True and market_gap provided, ret_fn_basic returns BHAR-adjusted
    returns (stock return - market benchmark for same date).
    """
    print(f"\n{'=' * 70}")
    print(f"[{hold_label}] {name} (n_picks={len(picks)})")
    if use_bhar:
        print(f"  [BHAR-adjusted: stock return - market overnight gap benchmark]")
    print(f"{'=' * 70}")

    if not picks:
        print("  无 picks, 跳过")
        return {"name": name, "hold": hold_label, "n_picks": 0}

    # ---- basic EV (no stop) ----
    if use_bhar and market_gap is not None:
        basic_rets = []
        for p in picks:
            raw = ret_fn_basic(p)
            if raw is None:
                continue
            mkt = market_gap.get(p["zt_date"], 0.0)
            basic_rets.append(raw - mkt)
    else:
        basic_rets = [ret_fn_basic(p) for p in picks]
        basic_rets = [r for r in basic_rets if r is not None]

    basic_s = ev_stats(basic_rets)
    net_basic = basic_s["ev"] - COST * 100
    print(f"\n--- basic {'BHAR' if use_bhar else 'close_ev'} (no stop) ---")
    print(f"  n={basic_s['n']} gross_EV={basic_s['ev']}% std={basic_s['std']}% WR={basic_s['wr']}% t={basic_s['t']} CI[{basic_s['ci_lo']},{basic_s['ci_hi']}]")
    print(f"  net EV (after {COST * 100:.1f}% cost): {net_basic:.3f}%")

    # day-paired t
    basic_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        if use_bhar and market_gap is not None:
            raw = ret_fn_basic(p)
            if raw is not None:
                basic_by_date[p["zt_date"]].append(raw - market_gap.get(p["zt_date"], 0.0))
        else:
            r = ret_fn_basic(p)
            if r is not None:
                basic_by_date[p["zt_date"]].append(r)
    basic_dt = day_paired_t(basic_by_date)
    print(f"  day-paired: n_days={basic_dt['n_days']} mean={basic_dt['mean']}% t={basic_dt['t']} p_one_sided={basic_dt['p_one_sided']}")

    # ---- stop variant (only for close_ev口径, not overnight gap) ----
    stop_s = {"n": 0, "ev": 0.0, "std": 0.0, "t": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "wr": 0.0}
    stop_dt = {"n_days": 0, "mean": 0.0, "std": 0.0, "t": 0.0, "p_one_sided": 1.0}
    stop_reasons: dict[str, int] = defaultdict(int)

    if ret_fn_stop is not None:
        print(f"\n--- stop variant (-{STOP_PCT * 100:.0f}% stop + R6 gap-through) ---")
        stop_rets = [ret_fn_stop(p) for p in picks]
        stop_rets_clean = [r[0] for r in stop_rets if r is not None]
        stop_s = ev_stats(stop_rets_clean)
        net_stop = stop_s["ev"] - COST * 100
        print(f"  n={stop_s['n']} gross_EV={stop_s['ev']}% std={stop_s['std']}% WR={stop_s['wr']}% t={stop_s['t']} CI[{stop_s['ci_lo']},{stop_s['ci_hi']}]")
        print(f"  net EV (after cost): {net_stop:.3f}%")

        for p in picks:
            r = ret_fn_stop(p)
            if r is not None:
                stop_reasons[r[1]] += 1
        total_r = sum(stop_reasons.values())
        if total_r > 0:
            print(f"  exit reasons:")
            for rsn, cnt in sorted(stop_reasons.items(), key=lambda x: -x[1]):
                print(f"    {rsn}: {cnt} ({cnt / max(total_r, 1) * 100:.1f}%)")

        stop_by_date: dict[str, list[float]] = defaultdict(list)
        for p in picks:
            r = ret_fn_stop(p)
            if r is not None:
                stop_by_date[p["zt_date"]].append(r[0])
        stop_dt = day_paired_t(stop_by_date)
        print(f"  day-paired: n_days={stop_dt['n_days']} mean={stop_dt['mean']}% t={stop_dt['t']} p_one_sided={stop_dt['p_one_sided']}")

    # ---- walk-forward OOS ----
    print(f"\n--- walk-forward OOS (basic, 前半 train → 后半 test) ---")
    # For BHAR, wrap ret_fn to include benchmark subtraction
    if use_bhar and market_gap is not None:

        def ret_fn_bhar(p, _fn=ret_fn_basic, _mg=market_gap):
            raw = _fn(p)
            if raw is None:
                return None
            return raw - _mg.get(p["zt_date"], 0.0)

        wf = walk_forward(picks, ret_fn_bhar)
    else:
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
        print(f"  train: n={tr['n']} n_dates={wf['n_train_dates']} EV={tr['ev']}% t={tr['t']} day_t={tr_dt['t']}")
        print(f"  test:  n={te['n']} n_dates={wf['n_test_dates']} EV={te['ev']}% t={te['t']} day_t={te_dt['t']} p={te_dt['p_one_sided']}")
        decay = (tr["ev"] - te["ev"]) / abs(tr["ev"]) * 100 if tr["ev"] != 0 else 0
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
        "stop_ev_net": stop_s["ev"] - COST * 100 if stop_s["n"] > 0 else 0.0,
        "stop_day_t": stop_dt["t"],
        "stop_p_raw": stop_dt["p_one_sided"],
        "wf_status": wf["status"],
        "wf_train_ev": wf_train_ev,
        "wf_test_ev": wf_test_ev,
        "wf_test_p": wf_test_p,
    }


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------


def main() -> None:
    print("=" * 70)
    print("短线策略探索: 窒息量低吸 (suffocation-volume mean-reversion)")
    print("§44 v3 过严口径: close_ev/BHAR / per-day-t / Bonferroni / walk-forward OOS")
    print("=" * 70)

    # ---- load data ----
    print("\n[1] 加载 kline cache + regime + ex-div dates...")
    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    print(f"  codes: {len(code_map)}, trading days: {len(calendar)}")
    print(f"  calendar range: {calendar[0]} ~ {calendar[-1]}")

    # volume field coverage check
    n_vol = sum(1 for dm in code_map.values() for b in dm.values() if b.get("volume") not in (None, 0))
    n_bars = sum(len(dm) for dm in code_map.values())
    print(f"  volume coverage: {n_vol}/{n_bars} ({n_vol / n_bars * 100:.1f}%)")

    # regime
    regime_data = json.loads(REGIME_PATH.read_text())
    regime_map: dict[str, str] = {d: v.get("regime", "unknown") for d, v in regime_data.items()}
    from collections import Counter

    rc = Counter(r for d, r in regime_map.items() if d >= "2018-01-01")
    print(f"  regime (2018+): strong={rc.get('strong', 0)}, weak={rc.get('weak', 0)}")

    # ex-div dates
    ex_div_dates: set[str] = set()
    if DIVIDEND_PATH.exists():
        div_data = json.loads(DIVIDEND_PATH.read_text())
        if isinstance(div_data, list):
            for e in div_data:
                ed = e.get("ex_date") or e.get("exdate")
                if ed:
                    ex_div_dates.add(ed)
        print(f"  ex-div dates: {len(ex_div_dates)}")

    # ---- precompute market benchmark ----
    print("\n[2] 预计算市场基准 (equal-weighted cross-section overnight gap + cc)...")
    market_gap, market_cc = precompute_market_benchmarks(code_map)
    gaps = [v for v in market_gap.values()]
    print(f"  market overnight gap: mean={statistics.mean(gaps):.4f}% std={statistics.pstdev(gaps):.4f}% n={len(gaps)}")
    ccs = [v for v in market_cc.values()]
    print(f"  market close-to-close: mean={statistics.mean(ccs):.4f}% std={statistics.pstdev(ccs):.4f}% n={len(ccs)}")

    # ---- main sweep: 3 N-variants × overnight gap (primary) ----
    N_CONFIGS = [(3, "连跌3日"), (4, "连跌4日"), (5, "连跌5日")]
    print(f"\n[3] 主 sweep: {N_VARIANTS} N-variants × overnight gap (primary exit)")
    print(f"    Bonferroni n_cross_factor = {N_CROSS_FACTOR} (×{N_CROSS_FACTOR * 2} tests)")

    results: list[dict] = []
    all_picks_by_n: dict[int, list[dict]] = {}

    for n_down, n_label in N_CONFIGS:
        picks = build_picks_suffocation(
            code_map,
            calendar,
            n_down=n_down,
            vol_ratio_thresh=VOL_RATIO_THRESH,
        )
        all_picks_by_n[n_down] = picks

        # primary: overnight gap (raw)
        r = analyze_variant(
            f"suffocation_{n_down}day ({n_label}, vol<{VOL_RATIO_THRESH})",
            picks,
            overnight_gap_ev,
            None,
            "overnight gap (T close→T+1 open)",
        )
        results.append(r)
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
                subset_name=f"  suffocation_{n_down}day overnight (raw)",
                n_cross_factor=N_CROSS_FACTOR,
            )

        # BHAR-adjusted overnight gap
        r_bhar = analyze_variant(
            f"suffocation_{n_down}day BHAR ({n_label}, vol<{VOL_RATIO_THRESH})",
            picks,
            overnight_gap_ev,
            None,
            "overnight gap BHAR (T close→T+1 open, mkt-adj)",
            market_gap=market_gap,
            use_bhar=True,
        )
        results.append(r_bhar)
        if r_bhar["n_picks"] > 0:
            verdict_for(
                ev_gross=r_bhar["basic_ev_gross"],
                t_day=r_bhar["basic_day_t"],
                p_raw=r_bhar["basic_p_raw"],
                wf_status=r_bhar["wf_status"],
                wf_train_ev=r_bhar["wf_train_ev"],
                wf_test_ev=r_bhar["wf_test_ev"],
                wf_test_p=r_bhar["wf_test_p"],
                n_days=r_bhar["n_days"],
                net_ev=r_bhar["basic_ev_net"],
                subset_name=f"  suffocation_{n_down}day overnight (BHAR)",
                n_cross_factor=N_CROSS_FACTOR,
            )

    # ---- summary table ----
    print(f"\n\n{'=' * 70}")
    print(f"[4] 主 sweep 汇总表 (overnight gap, vol<{VOL_RATIO_THRESH})")
    print(f"{'=' * 70}")
    print(f"{'variant':<45} {'n_picks':>8} {'n_days':>7} {'gross%':>8} {'net%':>8} {'day_t':>7} {'p_raw':>9} {'Bonf':>9}")
    print("-" * 110)
    for r in results:
        if r["n_picks"] == 0:
            continue
        p_bonf = bonferroni_p(r["basic_p_raw"], N_CROSS_FACTOR * 2)
        print(
            f"{r['name'][:45]:<45} {r['n_picks']:>8} {r['n_days']:>7} "
            f"{r['basic_ev_gross']:>8.3f} {r['basic_ev_net']:>8.3f} "
            f"{r['basic_day_t']:>7.2f} {r['basic_p_raw']:>9.6f} {p_bonf:>9.6f}"
        )
    print()

    # ---- hold variants for N=3 (most picks) ----
    best_n = 3
    best_picks = all_picks_by_n.get(best_n, [])
    if best_picks and len(best_picks) > 0:
        print(f"\n{'=' * 70}")
        print(f"[5] 持有期变体: N={best_n} (n={len(best_picks)})")
        print(f"{'=' * 70}")

        hold_results: list[dict] = []
        for hold_label, ret_basic, ret_stop in [
            ("overnight gap (T close→T+1 open)", overnight_gap_ev, None),
            ("close_ev T+2 (T+1 open→T+2 close)", close_ev_t2, close_ev_stop),
            ("close_ev T+5 (T+1 open→T+5 close)", close_ev_t5, close_ev_stop_t5),
        ]:
            r = analyze_variant(
                f"suffocation_{best_n}day",
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
                    subset_name=f"  suffocation_{best_n}day ({hold_label})",
                    n_cross_factor=N_CROSS_FACTOR,
                )

    # ---- robustness: ex-div filter + low-price filter ----
    if best_picks:
        print(f"\n{'=' * 70}")
        print(f"[6] 稳健性: ex-div 过滤 + 低价股过滤 (N={best_n}, overnight gap)")
        print(f"{'=' * 70}")

        # ex-div filtered
        picks_nodiv = build_picks_suffocation(
            code_map,
            calendar,
            n_down=best_n,
            vol_ratio_thresh=VOL_RATIO_THRESH,
            filter_ex_div=True,
            ex_div_dates=ex_div_dates,
        )
        r_nodiv = analyze_variant(
            f"suffocation_{best_n}day (ex-div filtered)",
            picks_nodiv,
            overnight_gap_ev,
            None,
            "overnight gap (ex-div removed)",
        )
        if r_nodiv["n_picks"] > 0:
            verdict_for(
                ev_gross=r_nodiv["basic_ev_gross"],
                t_day=r_nodiv["basic_day_t"],
                p_raw=r_nodiv["basic_p_raw"],
                wf_status=r_nodiv["wf_status"],
                wf_train_ev=r_nodiv["wf_train_ev"],
                wf_test_ev=r_nodiv["wf_test_ev"],
                wf_test_p=r_nodiv["wf_test_p"],
                n_days=r_nodiv["n_days"],
                net_ev=r_nodiv["basic_ev_net"],
                subset_name=f"  suffocation_{best_n}day overnight (ex-div filtered)",
                n_cross_factor=N_CROSS_FACTOR,
            )

        # low-price filtered (>5 yuan)
        picks_nolow = build_picks_suffocation(
            code_map,
            calendar,
            n_down=best_n,
            vol_ratio_thresh=VOL_RATIO_THRESH,
            min_price=5.0,
        )
        r_nolow = analyze_variant(
            f"suffocation_{best_n}day (price>=5)",
            picks_nolow,
            overnight_gap_ev,
            None,
            "overnight gap (price>=5)",
        )
        if r_nolow["n_picks"] > 0:
            verdict_for(
                ev_gross=r_nolow["basic_ev_gross"],
                t_day=r_nolow["basic_day_t"],
                p_raw=r_nolow["basic_p_raw"],
                wf_status=r_nolow["wf_status"],
                wf_train_ev=r_nolow["wf_train_ev"],
                wf_test_ev=r_nolow["wf_test_ev"],
                wf_test_p=r_nolow["wf_test_p"],
                n_days=r_nolow["n_days"],
                net_ev=r_nolow["basic_ev_net"],
                subset_name=f"  suffocation_{best_n}day overnight (price>=5)",
                n_cross_factor=N_CROSS_FACTOR,
            )

        # both filters
        picks_clean = build_picks_suffocation(
            code_map,
            calendar,
            n_down=best_n,
            vol_ratio_thresh=VOL_RATIO_THRESH,
            filter_ex_div=True,
            ex_div_dates=ex_div_dates,
            min_price=5.0,
        )
        r_clean = analyze_variant(
            f"suffocation_{best_n}day (ex-div+price filters)",
            picks_clean,
            overnight_gap_ev,
            None,
            "overnight gap (clean: ex-div+price>=5)",
        )
        if r_clean["n_picks"] > 0:
            verdict_for(
                ev_gross=r_clean["basic_ev_gross"],
                t_day=r_clean["basic_day_t"],
                p_raw=r_clean["basic_p_raw"],
                wf_status=r_clean["wf_status"],
                wf_train_ev=r_clean["wf_train_ev"],
                wf_test_ev=r_clean["wf_test_ev"],
                wf_test_p=r_clean["wf_test_p"],
                n_days=r_clean["n_days"],
                net_ev=r_clean["basic_ev_net"],
                subset_name=f"  suffocation_{best_n}day overnight (clean)",
                n_cross_factor=N_CROSS_FACTOR,
            )

    # ---- volume threshold sensitivity ----
    if best_picks:
        print(f"\n{'=' * 70}")
        print(f"[7] 量比阈值敏感性 (N={best_n}, overnight gap)")
        print(f"{'=' * 70}")
        for thresh in [0.20, 0.30, 0.50]:
            picks_s = build_picks_suffocation(
                code_map,
                calendar,
                n_down=best_n,
                vol_ratio_thresh=thresh,
            )
            r = analyze_variant(
                f"suffocation_{best_n}day (vol<{thresh})",
                picks_s,
                overnight_gap_ev,
                None,
                f"overnight gap (vol<{thresh})",
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
                    subset_name=f"  suffocation_{best_n}day overnight (vol<{thresh})",
                    n_cross_factor=N_CROSS_FACTOR,
                )

    # ---- regime splits ----
    if best_picks:
        print(f"\n{'=' * 70}")
        print(f"[8] Regime 分层 (N={best_n}, overnight gap)")
        print(f"{'=' * 70}")
        for regime_filter in ["strong", "weak"]:
            picks_reg = build_picks_suffocation(
                code_map,
                calendar,
                n_down=best_n,
                vol_ratio_thresh=VOL_RATIO_THRESH,
                regime_map=regime_map,
                regime_filter=regime_filter,
            )
            r = analyze_variant(
                f"suffocation_{best_n}day ({regime_filter})",
                picks_reg,
                overnight_gap_ev,
                None,
                f"overnight gap [{regime_filter}]",
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
                    subset_name=f"  suffocation_{best_n}day overnight [{regime_filter}]",
                    n_cross_factor=N_CROSS_FACTOR,
                )

    # ---- DSR ----
    if best_picks:
        print(f"\n{'=' * 70}")
        print(f"[9] DSR (Deflated Sharpe Ratio) — 过拟合检测")
        print(f"{'=' * 70}")
        overnight_rets = [overnight_gap_ev(p) for p in best_picks]
        overnight_rets = [r for r in overnight_rets if r is not None]
        dsr_overnight = compute_dsr(overnight_rets, n_trials=N_CROSS_FACTOR)
        print(
            f"  overnight gap (N={best_n}): DSR={dsr_overnight.get('dsr', 0)} "
            f"SR_obs={dsr_overnight.get('sr_obs', 0)} SR_0={dsr_overnight.get('sr_0', 0)} "
            f"skew={dsr_overnight.get('skew', 0)} kurt={dsr_overnight.get('kurt_excess', 0)} "
            f"n_trials={dsr_overnight.get('n_trials', 0)} n={dsr_overnight.get('n', 0)}"
        )
        if dsr_overnight.get("dsr", 0) > 0.95:
            print(f"  → DSR > 0.95: Sharpe 可能在多重测试后仍显著")
        else:
            print(f"  → DSR <= 0.95: Sharpe 在多重测试后不显著 (或负 edge 无 SR可言)")

        # close_ev DSR
        t2_rets = [close_ev_t2(p) for p in best_picks]
        t2_rets = [r for r in t2_rets if r is not None]
        if t2_rets:
            dsr_t2 = compute_dsr(t2_rets, n_trials=N_CROSS_FACTOR)
            print(f"  close_ev T+2 (N={best_n}): DSR={dsr_t2.get('dsr', 0)} SR_obs={dsr_t2.get('sr_obs', 0)} n={dsr_t2.get('n', 0)}")

    # ---- final summary ----
    print(f"\n\n{'=' * 70}")
    print(f"[10] 最终总结")
    print(f"{'=' * 70}")
    print(f"  策略: 窒息量低吸 (suffocation-volume mean-reversion)")
    print(f"  信号: 连跌N日 + 量比<5日均量{VOL_RATIO_THRESH} (volume 字段, {n_vol / n_bars * 100:.1f}%覆盖)")
    print(f"  口径: T close→T+1 open (隔夜 gap) + T+1 open→T+2/T+5 close (close_ev)")
    print(f"  Bonferroni: n_cross_factor={N_CROSS_FACTOR} (×{N_CROSS_FACTOR * 2} tests)")
    print(f"  数据: {len(code_map)} codes, {len(calendar)} trading days ({calendar[0]}~{calendar[-1]})")

    # primary result
    primary = next(
        (r for r in results if "3day" in r["name"] and "overnight" in r.get("hold", "") and "BHAR" not in r["name"]),
        None,
    )
    if primary and primary["n_picks"] > 0:
        print(f"\n  主结果 (N=3, overnight gap, raw):")
        print(f"    n_picks={primary['n_picks']} n_days={primary['n_days']}")
        print(f"    gross EV={primary['basic_ev_gross']}% net EV={primary['basic_ev_net']}%")
        print(f"    day_t={primary['basic_day_t']} p_raw={primary['basic_p_raw']}")
        p_bonf = bonferroni_p(primary["basic_p_raw"], N_CROSS_FACTOR * 2)
        print(f"    Bonferroni p(×{N_CROSS_FACTOR * 2})={p_bonf}")
        print(f"    walk-forward: train={primary['wf_train_ev']}% test={primary['wf_test_ev']}% test_p={primary['wf_test_p']}")

    n_neg = sum(1 for r in results if r["n_picks"] > 0 and r["basic_ev_gross"] < 0)
    n_pos = sum(1 for r in results if r["n_picks"] > 0 and r["basic_ev_gross"] > 0)
    n_total = sum(1 for r in results if r["n_picks"] > 0)
    print(f"\n  结果: {n_neg}/{n_total} variants gross EV < 0, {n_pos} gross EV > 0")

    print(f"\n  禁止外推: 本测试仅覆盖窒息量低吸, 不代表短线策略整体有/无 edge")
    print(
        f"  局限性: kline 未复价 (ex-div 日有假 gap, 已做 ex-div 过滤 robustness); "
        f"volume 字段非 turn (turn 仅 42.5% 覆盖, volume 99.5%); "
        f"非组合级 (无再平衡), 仅日线粒度"
    )
    print(f"  量缩信号在 A 股: volume 枯竭 = 无买盘/退市风险 非 卖方衰竭, gap 方向 = 继续下跌非反弹")


if __name__ == "__main__":
    main()
