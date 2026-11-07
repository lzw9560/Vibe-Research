# -*- coding: utf-8 -*-
"""短线策略探索: 市场择时 MA (market timing with moving average)

策略: 上证综指(sh.000001) close 上穿 MA_N → 满仓(T+1); 下穿 → 空仓.
      vs buy-and-hold 基准. 5 变体: MA20/60/120/200/MA20-weekly.
      无选股 alpha, 纯 timing (WHEN in/out, 非 WHICH stock).

机制:
  - timing 的 edge 来自"弱市空仓避开跌幅" (非"强市满仓赚涨幅"——强市=持有=基准).
  - 每日 excess = (position_lagged - 1) * index_ret.
    强市日(position=1): excess=0; 弱市日(position=0): excess=-index_ret (避开的市场涨跌).
  - 若弱市日市场净跌 → excess 正 (timing 有效); 若弱市日市场涨 → excess 负 (miss 涨幅).

过严口径 (§44 v3):
  - position lagged 1 day (signal at T close, execute T+1 open) — 避 look-ahead.
  - close-to-close daily excess returns (position_T 基于 close_{T-1} vs MA_{T-1}).
  - per-day t + Newey-West HAC t (autocorrelation 调整——连续 0 强市日 inflate simple t).
  - Bonferroni cross-strategy ×5 (5 MA 变体共享 trend-following 哲学).
  - walk-forward OOS (前半 train → 后半 test, temporal split, train_ev>0 检查).
  - 交易成本: ETF one-way 0.1% per switch (round-trip 0.2%, 无印花税).
  - BHAR = cum_strategy - cum_benchmark (总超额).
  - 禁止外推: 单 timing 策略 ≠ 市场择时有/无 edge.

A 股特殊性:
  - 无做空 → timing 只能"逃跌"不能"赚跌", alpha 上限被削.
  - 拥挤倒 U: 若人人用 MA200, 信号自我实现后反转 (whipsaw).
  - regime 跳变: MA 在牛市/熊市转换期产生大量 false signal (whipsaw cost).

跑法:
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend && .venv/bin/python tools/explore_shortterm_market-timing-ma20.py
"""

from __future__ import annotations

import json
import sys
import time
import math
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt, log

# Add backend to path for import
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tools._factor_helpers import (
    ev_stats,
    day_paired_t,
    bonferroni_p,
    norm_sf_positive,
    verdict_for,
    COST,
    ALPHA,
)

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
REGIME_PATH = DATA / "index_ma20_regime.json"
OHLC_CACHE = DATA / "index_ohlc_cache.json"

# ETF one-way cost (commission + slippage, no stamp duty)
ETF_ONE_WAY_COST = 0.001  # 0.1% per buy or sell
N_CROSS_FACTOR = 5  # 5 MA variants sharing trend-following philosophy

# ------------------------------------------------------------------
# Data: fetch index OHLC from baostock (monthly chunks, cached)
# ------------------------------------------------------------------


def fetch_index_ohlc(code: str, start: str, end: str) -> list[dict]:
    """Fetch daily OHLC from baostock, monthly chunks. Returns list of bars."""
    try:
        import baostock as bs
    except ImportError:
        print("  baostock not available, will use regime file")
        return []

    bars: list[dict] = []
    lg = bs.login()
    if lg.error_code != "0":
        print(f"  baostock login failed: {lg.error_msg}")
        return []

    # Monthly chunks
    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    y, m = sy, sm
    while (y, m) <= (ey, em):
        ms = f"{y:04d}-{m:02d}-01"
        if m == 12:
            me = f"{y:04d}-12-31"
            ny, nm = y + 1, 1
        else:
            # last day of month
            if m in (1, 3, 5, 7, 8, 10, 12):
                md = 31
            elif m in (4, 6, 9, 11):
                md = 30
            else:
                md = 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28
            me = f"{y:04d}-{m:02d}-{md:02d}"
            ny, nm = y, m + 1

        rs = bs.query_history_k_data_plus(
            code,
            "date,open,high,low,close,volume,amount,pctChg",
            start_date=ms,
            end_date=me,
            frequency="d",
        )
        while (rs.error_code == "0") and rs.next():
            row = rs.get_row_data()
            try:
                bars.append(
                    {
                        "date": row[0],
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]) if row[5] else 0.0,
                        "amount": float(row[6]) if row[6] else 0.0,
                        "pctChg": float(row[7]) if row[7] else 0.0,
                    }
                )
            except (ValueError, IndexError):
                pass
        y, m = ny, nm

    bs.logout()
    return bars


def load_index_data() -> tuple[list[str], list[float], list[float] | None]:
    """Load index daily close (and open if available). Returns (dates, closes, opens)."""
    # Try OHLC cache first
    if OHLC_CACHE.exists():
        cache = json.loads(OHLC_CACHE.read_text())
        sh001 = cache.get("sh.000001", [])
        if sh001:
            dates = [b["date"] for b in sh001]
            closes = [b["close"] for b in sh001]
            opens = [b.get("open") for b in sh001]
            print(f"  [cache] sh.000001: {len(dates)} bars, {dates[0]}~{dates[-1]}")
            return dates, closes, opens

    # Try fetching from baostock
    print("  Fetching sh.000001 from baostock (monthly chunks)...")
    t0 = time.time()
    bars = fetch_index_ohlc("sh.000001", "2004-01-01", "2026-09-30")
    if bars:
        cache = {"sh.000001": bars}
        OHLC_CACHE.write_text(json.dumps(cache))
        dates = [b["date"] for b in bars]
        closes = [b["close"] for b in bars]
        opens = [b.get("open") for b in bars]
        print(f"  fetched {len(bars)} bars in {time.time() - t0:.1f}s, {dates[0]}~{dates[-1]}")
        return dates, closes, opens

    # Fallback: regime file (close only, no open)
    print("  baostock fetch failed, falling back to regime file...")
    if not REGIME_PATH.exists():
        print("  ERROR: no regime file either!")
        return [], [], None
    regime = json.loads(REGIME_PATH.read_text())
    dates = sorted(regime.keys())
    closes = [regime[d]["close"] for d in dates]
    opens = None
    print(f"  [regime file] {len(dates)} days, {dates[0]}~{dates[-1]}")
    return dates, closes, opens


# ------------------------------------------------------------------
# MA computation
# ------------------------------------------------------------------


def compute_ma(closes: list[float], n: int) -> list[float | None]:
    """Simple rolling mean of last n closes values."""
    ma: list[float | None] = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        ma[i] = sum(closes[i - n + 1 : i + 1]) / n
    return ma


# ------------------------------------------------------------------
# Build timing positions (lagged by 1 day to avoid look-ahead)
# ------------------------------------------------------------------


def build_timing_positions(
    closes: list[float],
    ma: list[float | None],
    rebalance_freq: int = 1,
) -> list[int]:
    """Position: 1 if close > MA (signal at T-1 close, executed at T).
    rebalance_freq: 1=daily, 5=weekly (only change position every N trading days).
    """
    n = len(closes)
    positions = [0] * n
    current_pos = 0
    for i in range(1, n):
        # Signal at i-1: is close[i-1] > ma[i-1]? (known at close of day i-1)
        if ma[i - 1] is not None and closes[i - 1] > ma[i - 1]:
            signal = 1
        elif ma[i - 1] is not None:
            signal = 0
        else:
            signal = current_pos  # MA not yet available, hold

        if rebalance_freq > 1 and i % rebalance_freq != 0:
            positions[i] = current_pos  # hold current position between rebalances
            continue
        current_pos = signal
        positions[i] = current_pos
    return positions


# ------------------------------------------------------------------
# Compute daily excess returns
# ------------------------------------------------------------------


def compute_excess_returns(
    closes: list[float],
    positions: list[int],
    cost_per_switch: float,
) -> dict:
    """Compute daily index/strategy/excess returns + switch count.

    index_ret[i]   = closes[i]/closes[i-1] - 1  (close-to-close)
    strategy_ret[i]= positions[i] * index_ret[i] (position lagged, no look-ahead)
    gross_excess[i]= strategy_ret[i] - index_ret[i] = (positions[i]-1) * index_ret[i]
    net_excess[i]  = gross_excess[i] - cost_if_switch[i]  (ETF one-way cost per switch)
    """
    n = len(closes)
    index_ret = [0.0] * n
    strategy_ret = [0.0] * n
    gross_excess = [0.0] * n
    net_excess = [0.0] * n
    n_switches = 0
    total_cost = 0.0

    for i in range(1, n):
        ir = closes[i] / closes[i - 1] - 1.0
        index_ret[i] = ir
        sr = positions[i] * ir
        ge = (positions[i] - 1) * ir
        gross_excess[i] = ge

        # Cost: position change = one trade (buy or sell)
        cost = 0.0
        if positions[i] != positions[i - 1]:
            cost = cost_per_switch
            n_switches += 1
            total_cost += cost

        strategy_ret[i] = sr - cost
        net_excess[i] = ge - cost

    return {
        "index_ret": index_ret,
        "strategy_ret": strategy_ret,
        "gross_excess": gross_excess,
        "net_excess": net_excess,
        "n_switches": n_switches,
        "total_cost": total_cost,
    }


# ------------------------------------------------------------------
# Newey-West HAC t-test (autocorrelation-consistent)
# ------------------------------------------------------------------


def newey_west_t(returns: list[float], max_lag: int = 20) -> tuple[float, float]:
    """Newey-West HAC t-stat for mean of autocorrelated series.
    Returns (t_stat, hac_se).
    """
    n = len(returns)
    if n < 2:
        return 0.0, 0.0
    mean = sum(returns) / n

    # Autocovariances (Bartlett kernel)
    gamma_0 = sum((r - mean) ** 2 for r in returns) / n
    nw_var = gamma_0
    for h in range(1, min(max_lag + 1, n)):
        cov = sum((returns[t] - mean) * (returns[t - h] - mean) for t in range(h, n)) / n
        nw_var += 2 * cov * (1 - h / (max_lag + 1))

    if nw_var <= 0:
        return 0.0, 0.0
    hac_se = sqrt(nw_var / n)
    t = mean / hac_se if hac_se > 0 else 0.0
    return t, hac_se


# ------------------------------------------------------------------
# Walk-forward for timing (temporal split)
# ------------------------------------------------------------------


def timing_walk_forward(
    dates: list[str],
    net_excess: list[float],
    max_lag: int = 20,
) -> dict:
    """Temporal split: first half = train, second half = test."""
    n = len(dates)
    if n < 4:
        return {"status": "too_few"}
    mid = n // 2
    train = net_excess[:mid]
    test = net_excess[mid:]

    train_mean = sum(train) / len(train) * 100  # in %
    test_mean = sum(test) / len(test) * 100
    train_t, _ = newey_west_t(train, max_lag)
    test_t, test_se = newey_west_t(test, max_lag)
    test_p = norm_sf_positive(test_t)

    return {
        "status": "ok",
        "n_train": len(train),
        "n_test": len(test),
        "train_ev": round(train_mean, 4),
        "test_ev": round(test_mean, 4),
        "train_t": round(train_t, 3),
        "test_t": round(test_t, 3),
        "test_p": round(test_p, 6),
    }


# ------------------------------------------------------------------
# Cumulative returns + drawdown
# ------------------------------------------------------------------


def cum_returns(daily_rets: list[float]) -> list[float]:
    """Cumulative return multipliers (starting at 1.0)."""
    cum = [1.0]
    for r in daily_rets:
        cum.append(cum[-1] * (1 + r))
    return cum


def max_drawdown(cum: list[float]) -> float:
    """Maximum drawdown as a fraction (0.0 = no drawdown)."""
    peak = cum[0]
    mdd = 0.0
    for v in cum:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > mdd:
            mdd = dd
    return mdd


# ------------------------------------------------------------------
# Main analysis for one MA variant
# ------------------------------------------------------------------


def analyze_timing(
    name: str,
    dates: list[str],
    closes: list[float],
    ma_n: int,
    rebalance_freq: int,
    cost_per_switch: float = ETF_ONE_WAY_COST,
) -> dict:
    """Full analysis for one MA timing variant."""
    print(f"\n{'=' * 70}")
    print(f"变体: {name} (MA{ma_n}, rebalance={rebalance_freq}d, cost={cost_per_switch * 100:.1f}%/switch)")
    print(f"{'=' * 70}")

    ma = compute_ma(closes, ma_n)
    positions = build_timing_positions(closes, ma, rebalance_freq)
    ret = compute_excess_returns(closes, positions, cost_per_switch)

    # Skip day 0 (no return)
    ret_dates = dates[1:]
    gross = [r * 100 for r in ret["gross_excess"][1:]]  # in %
    net = [r * 100 for r in ret["net_excess"][1:]]

    n_days = len(ret_dates)
    n_in = sum(1 for p in positions[1:] if p == 1)
    n_out = n_days - n_in
    n_switches = ret["n_switches"]

    print(f"\n  仓位统计: in-market={n_in}d ({n_in / n_days * 100:.1f}%), out-market={n_out}d ({n_out / n_days * 100:.1f}%)")
    print(f"  交易次数: {n_switches} switches (~{n_switches // 2} round-trips), total cost={ret['total_cost'] * 100:.2f}%")
    if n_switches > 0:
        avg_hold = n_in / max(n_switches // 2, 1)
        print(f"  平均持仓: {avg_hold:.1f} 天/trade")

    # ---- Gross excess (before cost) ----
    gross_s = ev_stats(gross)
    print(f"\n--- gross excess (before cost) ---")
    print(f"  n={gross_s['n']} mean_daily={gross_s['ev']}% std={gross_s['std']}% WR={gross_s['wr']}% simple_t={gross_s['t']}")

    # ---- Net excess (after cost) ----
    net_s = ev_stats(net)
    print(f"\n--- net excess (after {cost_per_switch * 100:.1f}%/switch cost) ---")
    print(f"  n={net_s['n']} mean_daily={net_s['ev']}% std={net_s['std']}% WR={net_s['wr']}% simple_t={net_s['t']}")

    # ---- Per-day t (simple, from helper) ----
    net_by_date = {d: [r] for d, r in zip(ret_dates, net)}
    net_dt = day_paired_t(net_by_date)
    print(f"  day-paired (simple): n_days={net_dt['n_days']} mean={net_dt['mean']}% t={net_dt['t']} p_one_sided={net_dt['p_one_sided']}")

    # ---- Newey-West HAC t (autocorrelation-adjusted, more honest) ----
    nw_t_net, nw_se_net = newey_west_t([r / 100 for r in net], max_lag=20)
    nw_p_net = norm_sf_positive(nw_t_net)
    nw_t_gross, _ = newey_west_t([r / 100 for r in gross], max_lag=20)
    nw_p_gross = norm_sf_positive(nw_t_gross)
    print(f"  Newey-West HAC t (lag=20): gross_t={nw_t_gross:.3f} (p={nw_p_gross:.6f}), net_t={nw_t_net:.3f} (p={nw_p_net:.6f})")

    # ---- Walk-forward OOS ----
    print(f"\n--- walk-forward OOS (temporal split, net excess) ---")
    wf = timing_walk_forward(ret_dates, [r / 100 for r in net], max_lag=20)
    if wf["status"] == "ok":
        print(f"  train: n={wf['n_train']} daily_ev={wf['train_ev']}% NW_t={wf['train_t']}")
        print(f"  test:  n={wf['n_test']} daily_ev={wf['test_ev']}% NW_t={wf['test_t']} p={wf['test_p']}")
    else:
        print(f"  {wf['status']}")

    # ---- Cumulative returns (BHAR) ----
    cum_idx = cum_returns(ret["index_ret"][1:])
    cum_strat = cum_returns(ret["strategy_ret"][1:])
    total_idx = (cum_idx[-1] - 1) * 100
    total_strat = (cum_strat[-1] - 1) * 100
    bhar = total_strat - total_idx
    mdd_idx = max_drawdown(cum_idx) * 100
    mdd_strat = max_drawdown(cum_strat) * 100

    # Annualized
    years = n_days / 250
    ann_idx = ((cum_idx[-1]) ** (1 / years) - 1) * 100 if years > 0 else 0
    ann_strat = ((cum_strat[-1]) ** (1 / years) - 1) * 100 if years > 0 else 0
    ann_excess = ann_strat - ann_idx

    # Sharpe (daily, annualized)
    idx_rets = [r for r in ret["index_ret"][1:] if r != 0]
    strat_rets = [r for r in ret["strategy_ret"][1:]]
    sr_idx = (statistics.mean(idx_rets) / statistics.pstdev(idx_rets) * sqrt(250)) if idx_rets else 0
    sr_strat = (statistics.mean(strat_rets) / statistics.pstdev(strat_rets) * sqrt(250)) if strat_rets else 0

    print(f"\n--- cumulative performance (BHAR) ---")
    print(f"  buy-and-hold: total={total_idx:.2f}% annual={ann_idx:.2f}% Sharpe={sr_idx:.3f} maxDD={mdd_idx:.1f}%")
    print(f"  MA timing:    total={total_strat:.2f}% annual={ann_strat:.2f}% Sharpe={sr_strat:.3f} maxDD={mdd_strat:.1f}%")
    print(f"  BHAR (excess): {bhar:.2f}% (annualized excess: {ann_excess:.2f}%)")
    print(f"  maxDD reduction: {mdd_idx - mdd_strat:.1f}% ({mdd_strat / mdd_idx * 100:.1f}% of B&H)")

    # ---- Verdict ----
    ev_gross = gross_s["ev"]  # mean daily gross excess %
    net_ev = net_s["ev"]  # mean daily net excess %

    # Use NW t for verdict (most honest, autocorrelation-adjusted)
    verdict = verdict_for(
        ev_gross=ev_gross,
        t_day=nw_t_net,
        p_raw=nw_p_net,
        wf_status=wf["status"],
        wf_train_ev=wf.get("train_ev", 0),
        wf_test_ev=wf.get("test_ev", 0),
        wf_test_p=wf.get("test_p", 1.0),
        n_days=n_days,
        net_ev=net_ev,
        subset_name=f"  {name} (net, NW-t)",
        n_cross_factor=N_CROSS_FACTOR,
    )

    # Also run verdict with simple t for comparison
    verdict_simple = verdict_for(
        ev_gross=ev_gross,
        t_day=net_dt["t"],
        p_raw=net_dt["p_one_sided"],
        wf_status=wf["status"],
        wf_train_ev=wf.get("train_ev", 0),
        wf_test_ev=wf.get("test_ev", 0),
        wf_test_p=wf.get("test_p", 1.0),
        n_days=n_days,
        net_ev=net_ev,
        subset_name=f"  {name} (net, simple-t)",
        n_cross_factor=N_CROSS_FACTOR,
    )

    return {
        "name": name,
        "ma_n": ma_n,
        "rebalance": rebalance_freq,
        "n_days": n_days,
        "n_in": n_in,
        "n_out": n_out,
        "n_switches": n_switches,
        "gross_ev": ev_gross,
        "net_ev": net_ev,
        "simple_t": net_dt["t"],
        "simple_p": net_dt["p_one_sided"],
        "nw_t": round(nw_t_net, 3),
        "nw_p": round(nw_p_net, 6),
        "net_std": net_s["std"],
        # Excess (alpha) Sharpe — NOT total strategy Sharpe (which includes beta).
        # Total strat SR is misleading for DSR: high because it holds index (market beta).
        # Excess SR = mean(net_excess) / std(net_excess) * sqrt(250) — alpha from timing only.
        "excess_sr": round((net_s["ev"] / net_s["std"] * sqrt(250)) if net_s["std"] > 0 else 0.0, 3),
        "bhar": round(bhar, 2),
        "ann_excess": round(ann_excess, 2),
        "total_idx": round(total_idx, 2),
        "total_strat": round(total_strat, 2),
        "mdd_idx": round(mdd_idx, 1),
        "mdd_strat": round(mdd_strat, 1),
        "sr_idx": round(sr_idx, 3),
        "sr_strat": round(sr_strat, 3),
        "wf": wf,
        "verdict_nw": verdict,
        "verdict_simple": verdict_simple,
    }


# ------------------------------------------------------------------
# DSR (simplified Deflated Sharpe Ratio)
# ------------------------------------------------------------------


def simplified_dsr(sr: float, n_trials: int, n_obs: int, skew: float, kurt: float) -> float:
    """Simplified DSR per Bailey & Lopez de Prado (2014).

    Tests if observed annualized Sharpe is inflated by multiple testing.
    Returns P(SR_true > 0 | observed SR, N trials, T obs).
    DSR > 0.95 → SR likely real; DSR < 0.5 → SR below random selection threshold.

    Key: uses EXCESS/alpha Sharpe (not total strat SR which includes beta).
    """
    if n_obs < 2 or sr <= 0:
        return 0.0

    # Variance of annualized SR estimator under null: 250/T
    sr_var_under_null = 250.0 / n_obs

    # Expected max annualized SR under null from N independent trials
    # = sqrt(Var) * E[max of N standard normals]
    e_max_z_map = {2: 0.564, 3: 0.846, 4: 1.029, 5: 1.163}
    if n_trials <= 1:
        e_max_z = 0.0
    elif n_trials in e_max_z_map:
        e_max_z = e_max_z_map[n_trials]
    else:
        e_max_z = sqrt(2 * log(n_trials))  # Gumbel approx for large N

    e_max_sr = sqrt(sr_var_under_null) * e_max_z

    # Variance of observed SR (with higher-moment adjustment)
    denom_var = sr_var_under_null * (1 - skew * sr + (kurt - 1) / 4 * sr**2)
    if denom_var <= 0:
        return 0.0

    z = (sr - e_max_sr) / sqrt(denom_var)

    # DSR = Φ(z) = P(SR_true > 0 | observed) — NOT 1-Φ(z)
    return 0.5 * (1 + erf(z / sqrt(2)))


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------


def main() -> None:
    print("=" * 70)
    print("市场择时 MA 策略 — 上证综指(sh.000001) close vs MA_N")
    print("5 变体: MA20/60/120/200 + MA20-weekly | vs buy-and-hold | §44 v3 过严口径")
    print("=" * 70)

    # Load data
    print("\n[1] 加载指数数据...")
    dates, closes, opens = load_index_data()
    if not dates:
        print("FATAL: no index data available")
        return

    # Filter to 2004+ (regime file starts 2004-02-11)
    # and ensure we have enough data for MA200
    print(f"  total bars: {len(dates)}, range: {dates[0]}~{dates[-1]}")

    # ---- Run 5 variants ----
    print(f"\n[2] 测试 5 MA 变体 (Bonferroni ×{N_CROSS_FACTOR})...")
    variants = [
        ("MA20-daily", 20, 1),
        ("MA60-daily", 60, 1),
        ("MA120-daily", 120, 1),
        ("MA200-daily", 200, 1),
        ("MA20-weekly", 20, 5),
    ]

    results = []
    for name, ma_n, rebal in variants:
        r = analyze_timing(name, dates, closes, ma_n, rebal)
        results.append(r)

    # ---- Summary table ----
    print(f"\n\n{'=' * 70}")
    print(f"[3] 5 变体汇总表 (Bonferroni ×{N_CROSS_FACTOR})")
    print(f"{'=' * 70}")
    print(
        f"{'Variant':<16} {'n_days':>7} {'switch':>7} {'gross_ev%':>10} {'net_ev%':>10} "
        f"{'NW_t':>8} {'NW_p':>10} {'Bonf_p':>10} {'BHAR%':>10} {'ann_ex%':>8} "
        f"{'MDD_idx':>8} {'MDD_str':>8} {'verdict':>14}"
    )
    print("-" * 140)
    for r in results:
        bonf_p = bonferroni_p(r["nw_p"], N_CROSS_FACTOR * 2)
        print(
            f"{r['name']:<16} {r['n_days']:>7} {r['n_switches']:>7} "
            f"{r['gross_ev']:>10.4f} {r['net_ev']:>10.4f} "
            f"{r['nw_t']:>8.3f} {r['nw_p']:>10.6f} {bonf_p:>10.6f} "
            f"{r['bhar']:>10.2f} {r['ann_excess']:>8.2f} "
            f"{r['mdd_idx']:>8.1f} {r['mdd_strat']:>8.1f} "
            f"{r['verdict_nw']:>14}"
        )

    # ---- DSR (simplified) ----
    print(f"\n--- Simplified DSR (Deflated Sharpe Ratio) on EXCESS/alpha Sharpe ---")
    print(f"  N_trials={N_CROSS_FACTOR}, testing if excess SR survives multiple-testing haircut")
    print(f"  NOTE: excess SR = alpha from timing only (NOT total strat SR which includes beta)")
    for r in results:
        # DSR must test alpha Sharpe (excess returns), not total strategy Sharpe (beta-contaminated).
        # Total strat SR ~0.5-0.6 is high because it holds the index — that's beta, not timing alpha.
        # Excess SR ~0.1-0.15 is the true timing alpha.
        skew_approx = 0.0  # daily excess returns are approximately symmetric
        kurt_approx = 8.0  # fat tails (excess has many 0s + occasional large moves)
        dsr = simplified_dsr(
            sr=r["excess_sr"],
            n_trials=N_CROSS_FACTOR,
            n_obs=r["n_days"],
            skew=skew_approx,
            kurt=kurt_approx,
        )
        print(f"  {r['name']}: excess_SR={r['excess_sr']:.3f} (total strat SR={r['sr_strat']:.3f} includes beta) → DSR P(timing alpha>0)={dsr:.4f}")

    # ---- Honest verdict summary ----
    print(f"\n{'=' * 70}")
    print(f"[4] 诚实判定 (NW-t + Bonferroni ×{N_CROSS_FACTOR})")
    print(f"{'=' * 70}")
    for r in results:
        bonf_p = bonferroni_p(r["nw_p"], N_CROSS_FACTOR * 2)
        wf = r["wf"]
        print(f"\n  {r['name']}:")
        print(f"    gross_daily_ev={r['gross_ev']}% net_daily_ev={r['net_ev']}% (after {r['n_switches']}×{ETF_ONE_WAY_COST * 100:.1f}% cost)")
        print(f"    NW_t={r['nw_t']} NW_p={r['nw_p']} Bonf_p(×{N_CROSS_FACTOR * 2})={bonf_p:.6f}")
        print(f"    simple_t={r['simple_t']} simple_p={r['simple_p']} (simple t OVERSTATES — daily excess autocorrelated)")
        if wf["status"] == "ok":
            print(f"    walk-forward: train_ev={wf['train_ev']}% test_ev={wf['test_ev']}% test_NW_t={wf['test_t']} test_p={wf['test_p']}")
        print(f"    BHAR={r['bhar']}% (ann_excess={r['ann_excess']}%) Sharpe: idx={r['sr_idx']} strat={r['sr_strat']}")
        print(f"    maxDD: B&H={r['mdd_idx']}% timing={r['mdd_strat']}% (reduced by {r['mdd_idx'] - r['mdd_strat']:.1f}%)")
        print(f"    → VERDICT (NW-t): {r['verdict_nw']}")
        print(f"    → VERDICT (simple-t): {r['verdict_simple']}")

    # ---- Key insight ----
    print(f"\n{'=' * 70}")
    print("[5] 机制解读 + 诚实声明")
    print(f"{'=' * 70}")
    n_tests_bonf = N_CROSS_FACTOR * 2
    print(f"""
  timing edge 机制: 弱市空仓避开跌幅.
  - in-market 日 (position=1): excess=0 (持有=基准, timing 无贡献).
  - out-market 日 (position=0): excess=-index_ret (避开的市场涨跌).
  - edge 正 = 弱市日市场净跌 (timing 逃跌成功); edge 负 = 弱市日市场涨 (miss 涨幅).

  A 股特殊性:
  - 无做空 → timing 只能"逃跌"不能"赚跌", alpha 上限被削.
  - MA 在 regime 转换期 whipsaw (频繁 false signal, 成本吃 edge).
  - 拥挤倒 U: 若人人用 MA, 信号自我实现后反转.

  统计诚实:
  - simple t OVERSTATES (连续 0 日 inflate N, 每日 excess 非独立).
  - Newey-West HAC t 更诚实 (autocorrelation-adjusted).
  - Bonferroni ×{N_CROSS_FACTOR}*2={n_tests_bonf} (5 变体共享 trend-following 哲学).
  - walk-forward temporal split (非随机, 避 regime 过拟合).
  - DSR 须用 excess/alpha Sharpe (非 total strat SR——后者含 beta, DSR=1.0 是假阳性).

  禁止外推: 本测 = MA timing 5 变体 ≠ "市场择时有/无 edge" 二元定论.
""")


if __name__ == "__main__":
    main()
