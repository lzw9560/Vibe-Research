# -*- coding: utf-8 -*-
"""因子回测：short-term-reversal (短期反转因子, Jegadeesh-Lehmann)

方法论改变 (核心): long-only 绝对 EV (跟 beta 混淆) → 横截面 Fama-French long-short
  - 每再平衡日, 按过去 N 日累计收益横截面排序全市场股票
  - long bottom decile D1 (最低收益=超跌) + short top decile D10 (最高收益=超涨)
  - 零投资组合 (zero-investment), 市场中性 → 剥离 market beta
  - factor return = mean(D1 returns) - mean(D10 returns) 时间序列
  - CAPM: factor_return = alpha + beta*MKT + e, alpha = 风险调整后因子 alpha
  - Newey-West HAC SE (非 OLS SE, 抗异方差+自相关)

学术背景:
  - Jegadeesh-Lehmann (1990): 短期反转 (1 周), 买过去输家卖赢家
  - A 股散户追涨杀跌 → 短期反转可能强 (跟动量弱互补)
  - 与已测 RSI 超跌不同: 这是横截面 long-short (剥离 beta) 非 long-only

数据:
  - factor_zoo_data.json: reversal_5d (idx=1) + momentum_15d (idx=0) 快照
    已过流动性过滤 (20d 均成交额 >= 5000 万) + 数据质量 guard (排除停牌复牌假收益)
  - kline cache: 前向收益 (entry close → exit close)
  - market: sh.000001 (上证综指) 日 pctChg

过严口径:
  - no look-ahead: 因子 t 日收盘算, t+1 入场 (非 t 收盘)
  - 非重叠持有期: rebal 间隔 = 持有期 (无重叠收益, 统计干净)
  - winsorize 1%/99% 横截面 (去除极端值, 非删——保留合法极端股)
  - Bonferroni ×4 (cross-factor: momentum/reversal/size/vol) × 4 (within-reversal search) = ×16
  - BH FDR 作 sensitivity (less conservative)
  - walk-forward OOS: 前半 train → 后半 test, train_ev>0 检查
  - CAPM alpha + HAC SE (非 raw mean t)

4 variants (formation × rebalance freq search):
  1. reversal_5d, weekly (stride=1) — 主测 (canonical Jegadeesh-Lehmann)
  2. reversal_5d, biweekly (stride=2)
  3. reversal_5d, monthly (stride=4)
  4. reversal_15d, weekly (stride=1, idx=0 — 15 日反转, 非 momentum)

诚实约束:
  - A 股做空: 散户不可做空, long-short 是学术构念非散户可交易
  - survivorship: 非平衡面板, 早期 (2018-2020) 横截面 ~264-766 非随机回补子集
  - 交易成本: long-short 2 round-trip/rebalance, 周度年成本 ~30% (吃掉 edge)
  - 禁止外推: 4 因子 ≠ 横截面有/无 edge ≠ 选股战法有/无 edge

跑法:
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
  .venv/bin/python tools/explore_factor_short-term-reversal.py
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

# 让 from tools._factor_helpers import 在文件路径跑时也工作
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._factor_helpers import bonferroni_p, norm_sf_positive  # noqa: E402  DRY

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / ".vibe-research"
FACTOR_ZOO = DATA / "factor_zoo_data.json"
KLINE_DB = DATA / "baostock_kline_cache.db"

N_DECILES = 10
WINSOR_LOW = 1.0     # 1st percentile
WINSOR_HIGH = 99.0   # 99th percentile
CROSS_FACTOR_N = 4   # 4 factors in the sweep (momentum, reversal, size, vol)
COST_PER_ROUNDTRIP = 0.003  # 0.3% per round-trip (from helper COST)
# long-short = 2 round-trips per rebalance (long buy+sell, short sell+buy)
COST_LONG_SHORT = 2 * COST_PER_ROUNDTRIP  # 0.6% per rebalance


# ===================== data loading =====================

def load_factor_zoo() -> dict:
    """Load factor_zoo_data.json (factor snapshots + market returns + calendar)."""
    return json.loads(FACTOR_ZOO.read_text())


def load_kline_closes() -> dict[str, dict[str, float]]:
    """Load close prices: code -> {date: close}.

    Only keeps real-trading bars (volume > 0) to exclude suspension
    (suspended bars have stale close = previous, creating fake returns).
    Compact (date+close only) for memory efficiency (~5235 codes).
    """
    conn = sqlite3.connect(str(KLINE_DB))
    out: dict[str, dict[str, float]] = {}
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list):
            continue
        dmap: dict[str, float] = {}
        for b in bars:
            if not isinstance(b, dict):
                continue
            d = b.get("date")
            c = b.get("close")
            v = b.get("volume")
            if d is None or c is None or c <= 0:
                continue
            if v is not None and v <= 0:
                continue  # skip suspension (vol=0, stale close)
            dmap[d] = float(c)
        if dmap:
            out[code] = dmap
    conn.close()
    return out


# ===================== cross-sectional portfolio =====================

def winsorize(values: np.ndarray, low_pct: float = WINSOR_LOW,
              high_pct: float = WINSOR_HIGH) -> np.ndarray:
    """Winsorize at low_pct / high_pct percentiles (clip, not drop)."""
    if len(values) == 0:
        return values
    lo = np.percentile(values, low_pct)
    hi = np.percentile(values, high_pct)
    return np.clip(values, lo, hi)


def build_deciles(factor_values: dict[str, float],
                  n_deciles: int = N_DECILES) -> dict[int, list[str]]:
    """Sort by factor value ascending, assign to n_deciles equal-sized groups.

    D1 = lowest factor values (for reversal: most oversold = LONG)
    DN = highest factor values (for reversal: most overbought = SHORT)

    Winsorizes factor values at 1%/99% before sorting (removes extreme outliers
    that distort decile boundaries, but keeps the stocks — just clips their value).
    """
    if len(factor_values) < n_deciles * 2:
        return {}  # need at least 2 stocks per decile
    codes = list(factor_values.keys())
    vals = np.array([factor_values[c] for c in codes], dtype=float)
    vals_w = winsorize(vals)
    order = np.argsort(vals_w, kind="stable")
    n = len(codes)
    decile_size = n // n_deciles
    if decile_size == 0:
        return {}
    assignments: dict[int, list[str]] = {}
    for d in range(n_deciles):
        start = d * decile_size
        end = start + decile_size if d < n_deciles - 1 else n
        assignments[d + 1] = [codes[order[i]] for i in range(start, end)]
    return assignments


def stock_return(kline_closes: dict[str, dict[str, float]],
                 code: str,
                 calendar: list[str],
                 entry_idx: int, exit_idx: int) -> float | None:
    """Close-to-close return from entry_date to exit_date.

    If exit_date close is missing (suspended), uses nearest available close
    before exit_date (simulates selling when trading resumes — avoids
    survivorship bias from dropping suspended stocks).

    entry_date = calendar[entry_idx], exit_date = calendar[exit_idx].
    """
    dmap = kline_closes.get(code)
    if not dmap:
        return None
    entry_date = calendar[entry_idx]
    c_entry = dmap.get(entry_date)
    if c_entry is None or c_entry <= 0:
        return None
    exit_date = calendar[exit_idx]
    c_exit = dmap.get(exit_date)
    if c_exit is None or c_exit <= 0:
        # Find nearest available close before exit_date (after entry)
        c_exit = None
        for i in range(exit_idx - 1, entry_idx, -1):
            c = dmap.get(calendar[i])
            if c is not None and c > 0:
                c_exit = c
                break
    if c_exit is None or c_exit <= 0:
        return None
    return c_exit / c_entry - 1.0


def market_return(mkt_pctchg: dict[str, float],
                  calendar: list[str],
                  entry_idx: int, exit_idx: int) -> float | None:
    """Compound daily market returns from entry_idx+1 to exit_idx (close-to-close).

    market_return = product(1 + pctChg[d]/100 for d in [entry+1 .. exit]) - 1
    This equals close[exit] / close[entry] - 1 (close-to-close, consistent
    with stock_return).
    """
    ret = 1.0
    found = False
    for i in range(entry_idx + 1, exit_idx + 1):
        pchg = mkt_pctchg.get(calendar[i])
        if pchg is None:
            continue
        ret *= (1.0 + pchg / 100.0)
        found = True
    if not found:
        return None
    return ret - 1.0


# ===================== factor return series =====================

def build_series(factor_zoo: dict,
                 kline_closes: dict[str, dict[str, float]],
                 factor_idx: int,
                 stride: int) -> dict:
    """Build the cross-sectional factor return time series.

    For each rebalance date (selected by stride):
    1. Get factor values for all codes (from factor_zoo snapshots)
    2. Winsorize, sort ascending, assign to 10 deciles
    3. Long D1 (lowest = oversold), short D10 (highest = overbought)
    4. Compute forward returns: entry at t+1 close, exit at next rebal close
    5. factor_return = mean(D1 returns) - mean(D10 returns)

    No look-ahead: factor at t close, enter at t+1.
    Non-overlapping: each holding period = stride × 5 trading days.
    """
    calendar = factor_zoo["trading_dates"]
    cal_idx = {d: i for i, d in enumerate(calendar)}
    rebal_all = factor_zoo["rebalance_dates"]
    mkt_pctchg = factor_zoo["market_returns"]["sh.000001"]
    factor_snaps = factor_zoo["factor_snapshots"]

    # Select rebalance dates by stride
    rebal_dates = rebal_all[::stride]
    if len(rebal_dates) < 2:
        return {"status": "too_few_rebal", "n_rebal": len(rebal_dates)}

    factor_returns: list[float] = []
    market_returns: list[float] = []
    dates_used: list[str] = []
    n_codes_list: list[int] = []
    long_rets: list[float] = []
    short_rets: list[float] = []
    skipped_no_factor = 0
    skipped_few_stocks = 0

    for i in range(len(rebal_dates) - 1):
        form_date = rebal_dates[i]
        exit_date = rebal_dates[i + 1]

        form_idx = cal_idx.get(form_date)
        exit_idx = cal_idx.get(exit_date)
        if form_idx is None or exit_idx is None:
            continue
        entry_idx = form_idx + 1
        if entry_idx >= len(calendar) or entry_idx >= exit_idx:
            continue
        # entry_date = calendar[entry_idx] (t+1, no look-ahead)

        # Get factor values at formation date
        snap_raw = factor_snaps.get(form_date, {})
        snap = {}
        for code, vals in snap_raw.items():
            if isinstance(vals, list) and len(vals) > factor_idx:
                v = vals[factor_idx]
                if v is not None and not (isinstance(v, float) and
                                          (math.isnan(v) or math.isinf(v))):
                    snap[code] = float(v)

        if not snap:
            skipped_no_factor += 1
            continue
        if len(snap) < N_DECILES * 5:
            skipped_few_stocks += 1
            continue

        # Build decile portfolios (sort ascending, D1=lowest, D10=highest)
        deciles = build_deciles(snap, N_DECILES)
        if 1 not in deciles or N_DECILES not in deciles:
            skipped_few_stocks += 1
            continue

        # Compute forward returns for long (D1) and short (D10) legs
        d1_codes = deciles[1]
        d10_codes = deciles[N_DECILES]

        d1_rets = []
        for c in d1_codes:
            r = stock_return(kline_closes, c, calendar, entry_idx, exit_idx)
            if r is not None:
                d1_rets.append(r)
        d10_rets = []
        for c in d10_codes:
            r = stock_return(kline_closes, c, calendar, entry_idx, exit_idx)
            if r is not None:
                d10_rets.append(r)

        if not d1_rets or not d10_rets:
            continue

        long_ret = sum(d1_rets) / len(d1_rets)
        short_ret = sum(d10_rets) / len(d10_rets)
        factor_ret = long_ret - short_ret  # zero-investment long-short

        mkt_ret = market_return(mkt_pctchg, calendar, entry_idx, exit_idx)
        if mkt_ret is None:
            continue

        factor_returns.append(factor_ret)
        market_returns.append(mkt_ret)
        dates_used.append(form_date)
        n_codes_list.append(len(snap))
        long_rets.append(long_ret)
        short_rets.append(short_ret)

    return {
        "status": "ok" if factor_returns else "no_valid_periods",
        "factor_returns": factor_returns,
        "market_returns": market_returns,
        "rebal_dates": dates_used,
        "n_codes_per_period": n_codes_list,
        "long_returns": long_rets,
        "short_returns": short_rets,
        "skipped_no_factor": skipped_no_factor,
        "skipped_few_stocks": skipped_few_stocks,
    }


# ===================== CAPM regression (Newey-West HAC SE) =====================

def newey_west(y: np.ndarray, X: np.ndarray,
               max_lag: int | None = None) -> dict:
    """OLS regression with Newey-West HAC standard errors.

    y: (n,) dependent variable
    X: (n, k) regressors (including constant column)
    Returns: beta, se (HAC), t, p (two-sided) for each coefficient.
    """
    n, k = X.shape
    if n < k + 1:
        return {"status": "insufficient_obs"}
    if max_lag is None:
        # Newey (1994) automatic bandwidth: L = floor(4*(n/100)^(2/9))
        max_lag = max(1, int(4 * (n / 100) ** (2 / 9)))
    max_lag = min(max_lag, n - 1)

    # OLS: beta = (X'X)^{-1} X'y
    XtX = X.T @ X
    try:
        XtX_inv = np.linalg.inv(XtX)
    except np.linalg.LinAlgError:
        XtX_inv = np.linalg.pinv(XtX)
    beta = XtX_inv @ (X.T @ y)
    residuals = y - X @ beta

    # Newey-West S matrix (Bartlett kernel)
    # S = sum_t e_t^2 x_t x_t' + sum_{l=1}^{L} w_l sum_t e_t e_{t-l} (x_t x_{t-l}' + x_{t-l} x_t')
    S = np.zeros((k, k))
    for t in range(n):
        xt = X[t].reshape(-1, 1)
        S += residuals[t] ** 2 * (xt @ xt.T)

    for lag in range(1, max_lag + 1):
        w = 1.0 - lag / (max_lag + 1)  # Bartlett kernel
        for t in range(lag, n):
            xt = X[t].reshape(-1, 1)
            xt_l = X[t - lag].reshape(-1, 1)
            cross = (xt @ xt_l.T + xt_l @ xt.T)
            S += w * residuals[t] * residuals[t - lag] * cross

    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.maximum(np.diag(cov), 1e-20))
    t_stats = beta / se
    # two-sided p from normal (large n, NW SE → normal approximation)
    p_two = 2 * (1 - stats.norm.cdf(np.abs(t_stats)))

    return {
        "status": "ok",
        "beta": beta,
        "se": se,
        "t": t_stats,
        "p_two_sided": p_two,
        "max_lag": max_lag,
    }


def capm_regression(factor_returns: list[float],
                    market_returns: list[float]) -> dict:
    """CAPM time-series regression: factor_return = alpha + beta*MKT + e.

    alpha = risk-adjusted factor return (Jensen's alpha for zero-investment portfolio).
    HAC (Newey-West) SE for inference.

    Returns alpha (%), beta, alpha_t, alpha_p (one-sided: H0 alpha<=0).
    """
    y = np.array(factor_returns, dtype=float)
    mkt = np.array(market_returns, dtype=float)
    n = len(y)
    if n < 10:
        return {"status": "insufficient_obs", "n": n}

    X = np.column_stack([np.ones(n), mkt])
    nw = newey_west(y, X)
    if nw["status"] != "ok":
        return {"status": nw["status"]}

    alpha = float(nw["beta"][0])
    beta = float(nw["beta"][1])
    alpha_se = float(nw["se"][0])
    alpha_t = float(nw["t"][0])
    beta_t = float(nw["t"][1])
    # one-sided p for alpha > 0 (positive edge test)
    alpha_p_one = norm_sf_positive(alpha_t)
    max_lag = nw["max_lag"]

    return {
        "status": "ok",
        "n": n,
        "alpha": alpha,
        "alpha_pct": alpha * 100,
        "beta": beta,
        "alpha_se": alpha_se,
        "alpha_t": alpha_t,
        "beta_t": beta_t,
        "alpha_p_one_sided": alpha_p_one,
        "max_lag": max_lag,
    }


# ===================== series statistics =====================

def series_stats(returns: list[float], freq_per_year: float = 50.0) -> dict:
    """Basic stats for factor return series.

    returns: list of per-rebalance factor returns (decimal).
    freq_per_year: ~50 for weekly (250 trading days / 5).
    """
    n = len(returns)
    if n == 0:
        return {"status": "no_data", "n": 0}
    arr = np.array(returns, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if n > 1 else 0.0
    se = std / math.sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p_one = norm_sf_positive(t)
    # Sharpe for zero-investment portfolio = mean / std (no risk-free, zero cost)
    sharpe_period = mean / std if std > 0 else 0.0
    sharpe_annual = sharpe_period * math.sqrt(freq_per_year)
    # WR = fraction of periods with positive factor return
    wr = float(np.mean(arr > 0)) * 100

    return {
        "status": "ok",
        "n": n,
        "mean": mean,
        "mean_pct": mean * 100,
        "std": std,
        "std_pct": std * 100,
        "se": se,
        "t": t,
        "p_one_sided": p_one,
        "sharpe_period": sharpe_period,
        "sharpe_annual": sharpe_annual,
        "wr": wr,
    }


# ===================== walk-forward OOS =====================

def walk_forward(factor_returns: list[float],
                 market_returns: list[float]) -> dict:
    """Walk-forward: first half train → second half test.

    For each half: CAPM alpha + basic stats.
    train_ev > 0 check (edge must exist in train half, not just test).
    """
    n = len(factor_returns)
    if n < 20:
        return {"status": "too_few", "n": n}
    mid = n // 2

    fr_train = factor_returns[:mid]
    fr_test = factor_returns[mid:]
    mr_train = market_returns[:mid]
    mr_test = market_returns[mid:]

    train_capm = capm_regression(fr_train, mr_train)
    test_capm = capm_regression(fr_test, mr_test)
    train_stats = series_stats(fr_train)
    test_stats = series_stats(fr_test)

    return {
        "status": "ok",
        "n_train": mid,
        "n_test": n - mid,
        "train_stats": train_stats,
        "test_stats": test_stats,
        "train_capm": train_capm,
        "test_capm": test_capm,
        "train_alpha_pct": (train_capm.get("alpha_pct", 0.0)
                            if train_capm["status"] == "ok" else 0.0),
        "test_alpha_pct": (test_capm.get("alpha_pct", 0.0)
                           if test_capm["status"] == "ok" else 0.0),
        "test_alpha_t": (test_capm.get("alpha_t", 0.0)
                         if test_capm["status"] == "ok" else 0.0),
        "test_alpha_p_one_sided": (test_capm.get("alpha_p_one_sided", 1.0)
                                   if test_capm["status"] == "ok" else 1.0),
        "train_mean_pct": (train_stats.get("mean_pct", 0.0)
                           if train_stats["status"] == "ok" else 0.0),
        "test_mean_pct": (test_stats.get("mean_pct", 0.0)
                          if test_stats["status"] == "ok" else 0.0),
        "test_p_one_sided": (test_stats.get("p_one_sided", 1.0)
                             if test_stats["status"] == "ok" else 1.0),
    }


# ===================== Benjamini-Hochberg FDR =====================

def benjamini_hochberg(p_values: list[float]) -> list[float]:
    """BH FDR-adjusted p-values (less conservative than Bonferroni).

    Sort p-values, adjust: p_adj(k) = min(p(k) * n / rank(k), 1),
    enforce monotonicity from largest to smallest.
    """
    n = len(p_values)
    if n == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adj = [0.0] * n
    prev = 1.0
    for rank, (orig_idx, p) in enumerate(reversed(indexed), 1):
        actual_rank = n - rank + 1  # 1-indexed from smallest
        bh = p * n / actual_rank
        bh = min(bh, prev)  # enforce monotonicity
        adj[orig_idx] = min(bh, 1.0)
        prev = bh
    return adj


# ===================== verdict =====================

def compute_verdict(stats_basic: dict, capm: dict, wf: dict,
                    n_total_tests: int, n_rebalances: int,
                    cost_per_rebal: float) -> str:
    """Honest verdict cascade for cross-sectional factor return.

    1. factor_return_mean < 0 → falsified (negative factor return, reversal doesn't work)
    2. n_rebalances < 60 → underpowered
    3. Bonferroni p (raw mean t) >= 0.05 → falsified (not significant)
    4. CAPM alpha < 0 → falsified (no risk-adjusted edge)
    5. CAPM alpha Bonferroni p >= 0.05 → falsified (alpha not significant)
    6. walk-forward train alpha <= 0 → exploratory (edge not in train half)
    7. walk-forward test alpha <= 0 → falsified (no OOS edge)
    8. walk-forward test alpha Bonferroni p >= 0.05 → exploratory (OOS not significant)
    9. all pass → edge-confirmed
    """
    alpha = 0.05

    if stats_basic["status"] != "ok":
        return "underpowered"

    mean_pct = stats_basic["mean_pct"]
    p_raw = stats_basic["p_one_sided"]
    p_bonf = bonferroni_p(p_raw, n_total_tests)
    net_per_rebal = stats_basic["mean"] - cost_per_rebal

    print(f"\n  Verdict cascade (Bonferroni ×{n_total_tests}):")
    print(f"    factor_return_mean = {mean_pct:.4f}%/rebalance")
    print(f"    net (after {cost_per_rebal*100:.1f}% cost) = {net_per_rebal*100:.4f}%/rebalance")
    print(f"    raw t = {stats_basic['t']:.2f}, raw p_one_sided = {p_raw:.6f}")
    print(f"    Bonferroni p = {p_bonf:.6f}")

    if mean_pct < 0:
        print(f"    → FALSIFIED: factor_return_mean = {mean_pct:.4f}% < 0")
        return "falsified"
    if n_rebalances < 60:
        print(f"    → UNDERPOWERED: n_rebalances = {n_rebalances} < 60")
        return "underpowered"
    if p_bonf >= alpha:
        print(f"    → FALSIFIED: Bonferroni p = {p_bonf:.6f} >= {alpha}")
        return "falsified"

    if capm["status"] == "ok":
        alpha_pct = capm["alpha_pct"]
        alpha_t = capm["alpha_t"]
        alpha_p = capm["alpha_p_one_sided"]
        alpha_bonf = bonferroni_p(alpha_p, n_total_tests)
        print(f"    CAPM alpha = {alpha_pct:.4f}%, alpha_t = {alpha_t:.2f}, "
              f"alpha_p_one_sided = {alpha_p:.6f}, Bonf = {alpha_bonf:.6f}")
        if alpha_pct < 0:
            print(f"    → FALSIFIED: CAPM alpha = {alpha_pct:.4f}% < 0")
            return "falsified"
        if alpha_bonf >= alpha:
            print(f"    → FALSIFIED: CAPM alpha Bonferroni p = {alpha_bonf:.6f} >= {alpha}")
            return "falsified"
    else:
        print(f"    → UNDERPOWERED: CAPM regression failed ({capm['status']})")
        return "underpowered"

    if wf["status"] == "ok":
        tr_alpha = wf["train_alpha_pct"]
        te_alpha = wf["test_alpha_pct"]
        te_p = wf["test_alpha_p_one_sided"]
        te_bonf = bonferroni_p(te_p, n_total_tests)
        print(f"    walk-forward: train_alpha = {tr_alpha:.4f}%, "
              f"test_alpha = {te_alpha:.4f}%, test_p = {te_p:.6f}, "
              f"test_Bonf = {te_bonf:.6f}")
        if tr_alpha <= 0:
            print(f"    → EXPLORATORY: train alpha = {tr_alpha:.4f}% <= 0 "
                  f"(edge not in train half, test may be regime overfitting)")
            return "exploratory"
        if te_alpha <= 0:
            print(f"    → FALSIFIED: walk-forward test alpha = {te_alpha:.4f}% <= 0")
            return "falsified"
        if te_bonf >= alpha:
            print(f"    → EXPLORATORY: OOS test alpha > 0 but "
                  f"Bonf p = {te_bonf:.6f} >= {alpha} (not significant OOS)")
            return "exploratory"
    else:
        print(f"    → EXPLORATORY: walk-forward not available ({wf['status']})")
        return "exploratory"

    print(f"    → EDGE-CONFIRMED: factor mean > 0, CAPM alpha > 0, "
          f"Bonferroni PASS, walk-forward OOS significant")
    return "edge-confirmed"


# ===================== main =====================

def main() -> None:
    print("=" * 70)
    print("因子: short-term-reversal (短期反转, Jegadeesh-Lehmann)")
    print("方法论: Fama-French 横截面 long-short (非 long-only EV)")
    print("=" * 70)

    # ---- 1. Load data ----
    print("\n==> loading factor_zoo_data.json ...", flush=True)
    fz = load_factor_zoo()
    meta = fz["metadata"]
    calendar = fz["trading_dates"]
    rebal_all = fz["rebalance_dates"]
    print(f"    codes_total={meta['n_stocks_total']} dates={meta['n_dates']} "
          f"range={meta['date_range']}")
    print(f"    rebalance_dates={len(rebal_all)} "
          f"(every {fz.get('rebalance_freq', '5d')})")
    print(f"    cross_section: avg={meta['cross_section_size']['avg_codes_per_rebalance']} "
          f"min={meta['cross_section_size']['min']} "
          f"max={meta['cross_section_size']['max']}")
    print(f"    market benchmark: sh.000001 ({len(fz['market_returns']['sh.000001'])} dates)")

    print("\n==> loading kline closes (compact, vol>0 only) ...", flush=True)
    kline_closes = load_kline_closes()
    print(f"    loaded {len(kline_closes)} codes", flush=True)

    # ---- 2. Define variants ----
    variants = [
        {"name": "reversal_5d_weekly",
         "factor_idx": 1, "stride": 1,
         "label": "5d lookback, weekly rebalance (canonical Jegadeesh-Lehmann)",
         "freq_label": "weekly"},
        {"name": "reversal_5d_biweekly",
         "factor_idx": 1, "stride": 2,
         "label": "5d lookback, biweekly rebalance",
         "freq_label": "biweekly"},
        {"name": "reversal_5d_monthly",
         "factor_idx": 1, "stride": 4,
         "label": "5d lookback, monthly rebalance",
         "freq_label": "monthly"},
        {"name": "reversal_15d_weekly",
         "factor_idx": 0, "stride": 1,
         "label": "15d lookback, weekly rebalance (longer reversal horizon)",
         "freq_label": "weekly"},
    ]

    n_within = len(variants)
    n_total_tests = CROSS_FACTOR_N * n_within  # ×16
    print(f"\n==> Bonferroni: cross_factor×{CROSS_FACTOR_N} × within_reversal×{n_within} "
          f"= ×{n_total_tests}")

    # ---- 3. Build factor return series for each variant ----
    results: list[dict] = []
    for v in variants:
        print(f"\n{'=' * 70}")
        print(f"Building series: {v['name']} ({v['label']})", flush=True)
        series = build_series(fz, kline_closes, v["factor_idx"], v["stride"])
        if series["status"] != "ok":
            print(f"  status: {series['status']}")
            results.append({"name": v["name"], "status": series["status"], "variant": v})
            continue

        fr = series["factor_returns"]
        mr = series["market_returns"]
        freq_per_year = {"weekly": 50.0, "biweekly": 25.0, "monthly": 12.0}[v["freq_label"]]

        s_basic = series_stats(fr, freq_per_year)
        capm = capm_regression(fr, mr)
        wf = walk_forward(fr, mr)

        # Cost analysis
        cost_per_rebal = COST_LONG_SHORT  # 0.6% per rebalance for long-short
        gross_mean_pct = s_basic["mean_pct"]
        net_mean_pct = gross_mean_pct - cost_per_rebal * 100

        print(f"  n_rebalances: {len(fr)}")
        print(f"  avg stocks/period: {sum(series['n_codes_per_period'])/len(series['n_codes_per_period']):.0f}")
        print(f"  period: {series['rebal_dates'][0]} ~ {series['rebal_dates'][-1]}")
        print(f"  factor_return_mean: {gross_mean_pct:.4f}%/rebalance  "
              f"std: {s_basic['std_pct']:.4f}%  WR: {s_basic['wr']:.1f}%")
        print(f"  raw t: {s_basic['t']:.2f}  raw p_one_sided: {s_basic['p_one_sided']:.6f}")
        print(f"  Sharpe (annualized): {s_basic['sharpe_annual']:.2f}")
        print(f"  net (after {cost_per_rebal*100:.1f}% long-short cost): "
              f"{net_mean_pct:.4f}%/rebalance")
        p_bonf = bonferroni_p(s_basic["p_one_sided"], n_total_tests)
        print(f"  Bonferroni p (×{n_total_tests}): {p_bonf:.6f}")

        if capm["status"] == "ok":
            print(f"  CAPM: alpha={capm['alpha_pct']:.4f}%  beta={capm['beta']:.3f}  "
                  f"alpha_t={capm['alpha_t']:.2f} (HAC lag={capm['max_lag']})")
            print(f"  CAPM alpha p_one_sided: {capm['alpha_p_one_sided']:.6f}  "
                  f"Bonf: {bonferroni_p(capm['alpha_p_one_sided'], n_total_tests):.6f}")

        if wf["status"] == "ok":
            print(f"  walk-forward: n_train={wf['n_train']} n_test={wf['n_test']}")
            print(f"    train: mean={wf['train_mean_pct']:.4f}% alpha={wf['train_alpha_pct']:.4f}%")
            print(f"    test:  mean={wf['test_mean_pct']:.4f}% alpha={wf['test_alpha_pct']:.4f}% "
                  f"alpha_t={wf['test_alpha_t']:.2f} alpha_p={wf['test_alpha_p_one_sided']:.6f}")

        results.append({
            "name": v["name"],
            "status": "ok",
            "variant": v,
            "n_rebalances": len(fr),
            "stats": s_basic,
            "capm": capm,
            "walk_forward": wf,
            "factor_returns": fr,
            "market_returns": mr,
            "rebal_dates": series["rebal_dates"],
            "long_returns": series["long_returns"],
            "short_returns": series["short_returns"],
            "gross_mean_pct": gross_mean_pct,
            "net_mean_pct": net_mean_pct,
            "cost_per_rebal_pct": cost_per_rebal * 100,
            "p_bonf_mean": p_bonf,
        })

    # ---- 4. Summary table ----
    print(f"\n{'=' * 70}")
    print(f"汇总表 (cross-sectional long-short, CAPM alpha, Newey-West HAC SE)")
    print(f"{'=' * 70}")
    print(f"  {'variant':<26} {'n':>5} {'mean%':>8} {'std%':>7} {'t':>6} "
          f"{'p_raw':>8} {'Bonf×16':>9} {'alpha%':>8} {'a_t':>6} "
          f"{'sharpe':>7} {'verdict':<14}")
    print(f"  {'-'*26} {'-'*5} {'-'*8} {'-'*7} {'-'*6} {'-'*8} {'-'*9} "
          f"{'-'*8} {'-'*6} {'-'*7} {'-'*14}")

    verdicts: list[str] = []
    for r in results:
        if r["status"] != "ok":
            print(f"  {r['name']:<26} {'-':>5} ... {r['status']}")
            verdicts.append("underpowered")
            continue
        s = r["stats"]
        c = r["capm"]
        v = compute_verdict(s, c, r["walk_forward"], n_total_tests,
                            r["n_rebalances"], COST_LONG_SHORT)
        verdicts.append(v)
        alpha_pct = c.get("alpha_pct", 0) if c["status"] == "ok" else 0
        alpha_t = c.get("alpha_t", 0) if c["status"] == "ok" else 0
        print(f"  {r['name']:<26} {r['n_rebalances']:>5} {s['mean_pct']:>8.4f} "
              f"{s['std_pct']:>7.4f} {s['t']:>6.2f} {s['p_one_sided']:>8.6f} "
              f"{r['p_bonf_mean']:>9.6f} {alpha_pct:>8.4f} {alpha_t:>6.2f} "
              f"{s['sharpe_annual']:>7.2f} {v:<14}")

    # ---- 5. BH FDR sensitivity ----
    print(f"\n{'=' * 70}")
    print(f"BH FDR sensitivity (less conservative than Bonferroni)")
    print(f"{'=' * 70}")
    p_vals = []
    for r in results:
        if r["status"] == "ok":
            p_vals.append(r["stats"]["p_one_sided"])
        else:
            p_vals.append(1.0)
    bh_adj = benjamini_hochberg(p_vals)
    # Also apply BH across the cross-factor correction: BH on 16 tests
    # (4 cross-factor × 4 within = 16 hypothetical tests; we only have 4 within)
    # Simplified: BH on our 4 variants, then note cross-factor would increase
    for r, pa in zip(results, bh_adj):
        if r["status"] == "ok":
            print(f"  {r['name']:<26} raw_p={r['stats']['p_one_sided']:.6f}  "
                  f"BH_adj={pa:.6f}  "
                  f"{'PASS' if pa < 0.05 else 'FAIL'} at 0.05")
        else:
            print(f"  {r['name']:<26} (no data)")

    # ---- 6. Main variant deep dive ----
    main_r = results[0]  # reversal_5d_weekly
    print(f"\n{'=' * 70}")
    print(f"主测 deep dive: {main_r['name']}")
    print(f"{'=' * 70}")
    if main_r["status"] == "ok":
        fr = main_r["factor_returns"]
        lr = main_r["long_returns"]
        sr = main_r["short_returns"]
        print(f"  long leg (D1 oversold): mean={sum(lr)/len(lr)*100:.4f}%/rebalance")
        print(f"  short leg (D10 overbought): mean={sum(sr)/len(sr)*100:.4f}%/rebalance")
        print(f"  long-short spread: {main_r['gross_mean_pct']:.4f}%/rebalance")
        print(f"  cost (2 round-trips): {main_r['cost_per_rebal_pct']:.1f}%/rebalance")
        print(f"  net: {main_r['net_mean_pct']:.4f}%/rebalance")
        # Year split
        n = len(fr)
        q1, q2, q3 = n // 4, n // 2, 3 * n // 4
        for label, lo, hi in [("Q1(early)", 0, q1), ("Q2", q1, q2),
                              ("Q3", q2, q3), ("Q4(late)", q3, n)]:
            seg = fr[lo:hi]
            if seg:
                m = sum(seg) / len(seg) * 100
                print(f"  {label}: mean={m:.4f}%/rebalance (n={len(seg)})")

    # ---- 7. Overall verdict ----
    if "edge-confirmed" in verdicts:
        overall = "edge-confirmed"
    elif "underpowered" in verdicts:
        overall = "underpowered"
    elif "exploratory" in verdicts:
        overall = "exploratory"
    else:
        overall = "edge-falsified"
    print(f"\n  OVERALL (short-term-reversal factor): {overall}")

    _print_honest_notes(overall, main_r, n_total_tests)


def _print_honest_notes(overall: str, main_r: dict, n_tests: int) -> None:
    print(f"\n{'=' * 70}")
    print("诚实注解")
    print(f"{'=' * 70}")
    print("1. 测了什么: 横截面 long-short 因子收益 (Fama-French 学术标准).")
    print("   long D1 (超跌, 过去 5 日最低收益) + short D10 (超涨, 最高收益).")
    print("   剥离 market beta (零投资组合). CAPM alpha = 风险调整后因子 alpha.")
    print("   Newey-West HAC SE (非 OLS SE, 抗异方差+自相关).")
    print("2. 方法论改变: 原 long-only EV 跟 beta 混淆 → 横截面 long-short 剥离 beta.")
    print("   这是选股战法最底层的因子测试——所有选股战法底层都是因子.")
    print("3. 没测什么: 4 因子 ≠ 横截面有/无 edge ≠ 选股战法有/无 edge.")
    print("   未测价值/质量因子 (需基本面, blocked). 未测盘中可交易性.")
    print("4. A 股做空: 散户不可做空 → long-short 是学术构念非散户可交易.")
    print("   这是根本性约束——即使 alpha 显著, 散户无法直接交易 long-short.")
    print("   可行替代: long-only D1 (超跌反弹) 但放弃 market-neutral + 引入 beta.")
    print("5. 交易成本: long-short 2 round-trip/rebalance = 0.6%/rebalance.")
    print("   周度年成本 ~30% (50×0.6%), 吃掉几乎所有 edge.")
    print("   月度年成本 ~7.2% (12×0.6%), 更可行但仍显著.")
    print(f"6. Bonferroni: cross_factor×{CROSS_FACTOR_N} × within_reversal×4 = ×{n_tests}.")
    print("   BH FDR 作 sensitivity (less conservative).")
    print("7. survivorship: 非平衡面板, 2018-2020 横截面 ~264-766 非随机回补子集.")
    print("   早期结果可能 biased. 近期 (2025+) 横截面 4000+ 但天数 <60.")
    print("8. reversal_15d (variant 4): 本质是 -1 × momentum_15d. A 股动量弱→")
    print("   15d reversal 可能正 alpha 仅因动量负, 非'反转 edge'.")
    print(f"\nOVERALL: {overall}")


if __name__ == "__main__":
    main()
