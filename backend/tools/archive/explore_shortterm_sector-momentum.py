# -*- coding: utf-8 -*-
"""短线策略探索: 行业动量 ETF 轮动 → ETF 数据 blocked → 降级股票级行业动量.

任务: 行业动量 ETF 轮动 (sector momentum ETF rotation, 2-3 周持有).
数据评估结论: ETF 级 BLOCKED — baostock 实测 0 行不能 fetch ETF (sh.510300/sz.159915/
  sh.510050/sh.512890 全 rows=0), akshare em 端点 IP 封 (RemoteDisconnected).
降级路径: 股票级行业动量 — gene_scores.db code_industry (5896 codes × 129 行业)
  + kline cache 922 codes ≥5yr (1218 bars 2018 起) 交叉 114 行业.
  按 N 周动量排序 top-K 行业, 2-3 周持有再平衡 (组合级, 非单笔).

§44 v3 过严口径适配组合级:
- realistic entry: R+1 open (非 R close; R close 信号已 seal 不可买)
- 一字涨停跳过 (T+1 locked 买不进, 用 limit_for_code + is_yizi_t1)
- close_ev 非 open_ev: entry=open exit=close (非 open→open 日内泄漏)
- R6: 跳空穿 stop — 组合级不适用 single-stock stop, 但 cost 含滑点
- per-rebalance-block t: 每 rebalance 一个样本, effective N=#rebalances 非 #stocks
- Bonferroni: cross-combo ×N (formation × holding × K), 非 within ×2
- walk-forward OOS: 前半 rebalances train → 后半 test, train_ev>0 检查
- regime 分层: index_ma20_regime.json strong/weak, 防 within-regime only 外推
- DSR: deflated Sharpe ratio (Bailey-López de Prado 2014), multiple-testing 纠正
- PBO: probability of backtest overfitting (combinatorial symmetric CV)
- 禁止外推: 股票级结果 ≠ ETF 级有/无 edge

诚实预期 (§44 v3 前置窗口 sanity):
- 学术美股行业动量 12-16% 年化, McLean-Pontiff 衰减后 5-10%
- A 股: 反转效应强于动量 (散户结构), 拥挤倒 U, 极性翻转风险
- 股票级成本高: 0.3% round-trip × ~26 次/年 (2 周 hold) = 7.8% 年化成本
- 预期: gross 可能正但 net 边际, OOS 可能衰减或转负
"""

from __future__ import annotations
import sys
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt, log, pi

# ---------- import shared helpers (DRY) ----------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import (  # type: ignore[import-not-found]
    bonferroni_p,
    norm_sf_positive,
    ALPHA,
    COST,
    limit_for_code,
    is_yizi_t1,
)

# ---------- paths ----------
# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
GENE_DB = DATA / "gene_scores.db"
REGIME_JSON = DATA / "index_ma20_regime.json"

MIN_BARS_5YR = 1218  # ~5 trading years


# =====================================================================
# 1. DATA LOADING
# =====================================================================


def load_industry_map() -> dict[str, str]:
    """code -> industry (申万分类, 6 位纯数字 code)."""
    conn = sqlite3.connect(str(GENE_DB))
    mp: dict[str, str] = {}
    for code, _name, industry in conn.execute("SELECT code, name, industry FROM code_industry"):
        mp[code] = industry
    conn.close()
    return mp


def load_kline_for_universe(industry_codes: set[str]) -> dict[str, dict[str, dict]]:
    """Load kline ONLY for codes in industry_map with >=5yr history.

    Returns code -> {date: bar_dict}.
    Each bar has: date, open, high, low, close, volume, amount, turn, pctChg, isST.
    """
    conn = sqlite3.connect(str(KLINE_DB))
    code_map: dict[str, dict[str, dict]] = {}
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        if code not in industry_codes:
            continue
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or len(bars) < MIN_BARS_5YR:
            continue
        dmap: dict[str, dict] = {}
        for b in bars:
            d = b.get("date")
            if d:
                dmap[d] = b
        if len(dmap) >= MIN_BARS_5YR:
            code_map[code] = dmap
    conn.close()
    return code_map


def load_regime() -> dict[str, str]:
    """date -> regime ('strong'|'weak') from index_ma20_regime.json."""
    with open(REGIME_JSON) as f:
        raw = json.load(f)
    return {d: v["regime"] for d, v in raw.items() if isinstance(v, dict)}


def build_calendar(code_map: dict[str, dict[str, dict]]) -> list[str]:
    """Union of all trading dates, sorted."""
    dates: set[str] = set()
    for dmap in code_map.values():
        dates.update(dmap.keys())
    return sorted(dates)


# =====================================================================
# 2. INDUSTRY MOMENTUM
# =====================================================================


def compute_industry_momentum(
    code_map: dict[str, dict[str, dict]],
    industry_map: dict[str, str],
    calendar: list[str],
    rebalance_idx: int,
    formation_days: int,
) -> dict[str, float]:
    """Compute equal-weight industry return over formation window.

    formation window: [calendar[rebalance_idx - formation_days], calendar[rebalance_idx]]
    industry momentum = mean over stocks of (close[end] / close[start] - 1)
    Returns {industry: momentum}, only industries with >=2 stocks.
    """
    if rebalance_idx - formation_days < 0:
        return {}
    start_date = calendar[rebalance_idx - formation_days]
    end_date = calendar[rebalance_idx]

    industry_rets: dict[str, list[float]] = defaultdict(list)
    for code, dmap in code_map.items():
        ind = industry_map.get(code)
        if ind is None:
            continue
        b_start = dmap.get(start_date)
        b_end = dmap.get(end_date)
        if b_start is None or b_end is None:
            continue
        c_start = b_start.get("close")
        c_end = b_end.get("close")
        if c_start is None or c_end is None or c_start <= 0:
            continue
        industry_rets[ind].append(c_end / c_start - 1.0)

    momentum: dict[str, float] = {}
    for ind, rets in industry_rets.items():
        if len(rets) >= 2:  # need at least 2 stocks for meaningful industry return
            momentum[ind] = sum(rets) / len(rets)
    return momentum


# =====================================================================
# 3. PORTFOLIO BACKTEST
# =====================================================================


def portfolio_return(
    code_map: dict[str, dict[str, dict]],
    selected_codes: set[str],
    entry_idx: int,
    exit_idx: int,
    calendar: list[str],
) -> tuple[float, int]:
    """Equal-weight portfolio return: entry=open[entry_date], exit=close[exit_date].

    Skip stocks where entry day is 一字涨停 (locked, can't buy).
    Skip ST stocks at entry.
    Returns (portfolio_return, n_stocks).
    """
    entry_date = calendar[entry_idx]
    exit_date = calendar[exit_idx]
    rets: list[float] = []
    for code in selected_codes:
        dmap = code_map.get(code)
        if dmap is None:
            continue
        b_entry = dmap.get(entry_date)
        b_exit = dmap.get(exit_date)
        if b_entry is None or b_exit is None:
            continue
        entry_open = b_entry.get("open")
        exit_close = b_exit.get("close")
        if entry_open is None or exit_close is None or entry_open <= 0:
            continue
        # skip ST
        is_st = b_entry.get("isST") == "1"
        if is_st:
            continue
        # skip 一字涨停 at entry (can't buy)
        # need T-1 close to compute limit price; use pctChg as proxy
        # if open == high and pctChg >= limit-0.5%, likely locked up
        limit = limit_for_code(code, is_st)
        # check against previous close if available
        if entry_idx > 0:
            prev_date = calendar[entry_idx - 1]
            b_prev = dmap.get(prev_date)
            if b_prev and b_prev.get("close"):
                prev_close = b_prev["close"]
                if is_yizi_t1(b_entry, prev_close, limit):
                    continue  # 一字涨停 locked, skip
        rets.append((exit_close - entry_open) / entry_open)

    if not rets:
        return 0.0, 0
    return sum(rets) / len(rets), len(rets)


def benchmark_return(
    code_map: dict[str, dict[str, dict]],
    all_codes: list[str],
    entry_idx: int,
    exit_idx: int,
    calendar: list[str],
) -> float:
    """Equal-weight benchmark: all stocks (same entry/exit)."""
    r, _ = portfolio_return(code_map, set(all_codes), entry_idx, exit_idx, calendar)
    return r


def backtest_combo(
    code_map: dict[str, dict[str, dict]],
    industry_map: dict[str, str],
    calendar: list[str],
    regime_map: dict[str, str],
    formation_days: int,
    holding_days: int,
    top_k: int,
) -> list[dict]:
    """Backtest one parameter combination.

    Rebalance every `holding_days` trading days.
    At each rebalance:
      1. Compute industry momentum over formation window
      2. Select top-K industries
      3. Build portfolio (all stocks in top-K industries)
      4. Entry = R+1 open, exit = R+H close
      5. Compute portfolio return + benchmark return + excess return
      6. Net excess = excess - cost (0.3% per rebalance, 100% turnover assumption)
    """
    results: list[dict] = []
    # need formation_days lookback + holding_days forward
    start_idx = formation_days
    end_idx = len(calendar) - holding_days - 1
    reb_idx = start_idx
    while reb_idx <= end_idx:
        momentum = compute_industry_momentum(code_map, industry_map, calendar, reb_idx, formation_days)
        if len(momentum) < top_k:
            reb_idx += holding_days
            continue

        # select top-K industries by momentum (descending)
        top_industries = sorted(momentum, key=momentum.get, reverse=True)[:top_k]
        top_set = set(top_industries)

        # select all stocks in top-K industries
        selected_codes = {code for code, ind in industry_map.items() if ind in top_set and code in code_map}
        if len(selected_codes) < 3:
            reb_idx += holding_days
            continue

        entry_idx = reb_idx + 1
        exit_idx = reb_idx + holding_days
        if exit_idx >= len(calendar):
            break

        port_ret, n_stocks = portfolio_return(code_map, selected_codes, entry_idx, exit_idx, calendar)
        bench_ret = benchmark_return(code_map, list(code_map.keys()), entry_idx, exit_idx, calendar)

        gross_excess = (port_ret - bench_ret) * 100  # in %
        net_excess = gross_excess - COST * 100  # 0.3% cost per rebalance

        reb_date = calendar[reb_idx]
        regime = regime_map.get(reb_date, "unknown")

        results.append(
            {
                "rebalance_date": reb_date,
                "rebalance_idx": reb_idx,
                "regime": regime,
                "formation_days": formation_days,
                "holding_days": holding_days,
                "top_k": top_k,
                "n_industries_selected": len(top_industries),
                "n_stocks_portfolio": n_stocks,
                "portfolio_return_pct": round(port_ret * 100, 4),
                "benchmark_return_pct": round(bench_ret * 100, 4),
                "gross_excess_pct": round(gross_excess, 4),
                "net_excess_pct": round(net_excess, 4),
            }
        )
        reb_idx += holding_days

    return results


# =====================================================================
# 4. STATISTICAL ANALYSIS (per-rebalance-block t-test + walk-forward)
# =====================================================================


def analyze_combo(results: list[dict], combo_name: str) -> dict:
    """Statistical analysis for one parameter combination."""
    print(f"\n{'=' * 70}")
    print(f"组合: {combo_name} (n_rebalances={len(results)})")
    print(f"{'=' * 70}")

    if not results:
        print("  无 rebalances, 跳过")
        return {"name": combo_name, "n_rebalances": 0}

    gross = [r["gross_excess_pct"] for r in results]
    net = [r["net_excess_pct"] for r in results]
    n = len(results)

    # --- gross stats ---
    gross_mean = sum(gross) / n
    gross_std = statistics.pstdev(gross) if n > 1 else 0.0
    gross_se = gross_std / sqrt(n) if n > 0 else 0.0
    gross_t = gross_mean / gross_se if gross_se > 0 else 0.0
    gross_p = norm_sf_positive(gross_t)
    gross_wr = sum(1 for x in gross if x > 0) / n * 100

    print(f"\n--- gross excess (portfolio - benchmark) ---")
    print(
        f"  n_rebalances={n} mean={gross_mean:.3f}% std={gross_std:.3f}% "
        f"WR={gross_wr:.1f}% t={gross_t:.2f} p={gross_p:.6f}"
    )
    print(
        f"  portfolio avg={sum(r['portfolio_return_pct'] for r in results) / n:.3f}% "
        f"benchmark avg={sum(r['benchmark_return_pct'] for r in results) / n:.3f}%"
    )

    # --- net stats (after 0.3% cost) ---
    net_mean = sum(net) / n
    net_std = statistics.pstdev(net) if n > 1 else 0.0
    net_se = net_std / sqrt(n) if n > 0 else 0.0
    net_t = net_mean / net_se if net_se > 0 else 0.0
    net_p = norm_sf_positive(net_t)
    net_wr = sum(1 for x in net if x > 0) / n * 100

    print(f"\n--- net excess (after {COST * 100:.1f}% cost/rebalance) ---")
    print(f"  n_rebalances={n} mean={net_mean:.3f}% std={net_std:.3f}% WR={net_wr:.1f}% t={net_t:.2f} p={net_p:.6f}")

    # --- regime stratification ---
    by_regime: dict[str, list[float]] = defaultdict(list)
    for r in results:
        by_regime[r["regime"]].append(r["net_excess_pct"])
    print(f"\n--- regime stratification (net excess) ---")
    for reg in ["strong", "weak", "unknown"]:
        rs = by_regime.get(reg, [])
        if rs:
            rm = sum(rs) / len(rs)
            rsd = statistics.pstdev(rs) if len(rs) > 1 else 0.0
            rse = rsd / sqrt(len(rs)) if len(rs) > 0 else 0.0
            rt = rm / rse if rse > 0 else 0.0
            rp = norm_sf_positive(rt)
            print(f"  {reg}: n={len(rs)} mean={rm:.3f}% t={rt:.2f} p={rp:.6f}")

    # --- walk-forward OOS ---
    # split rebalances by date midpoint (chrono holdout)
    dates = [r["rebalance_date"] for r in results]
    mid_date = sorted(dates)[len(dates) // 2]
    train = [r for r in results if r["rebalance_date"] < mid_date]
    test = [r for r in results if r["rebalance_date"] >= mid_date]

    wf_status = "ok"
    wf_train_ev = 0.0
    wf_test_ev = 0.0
    wf_test_p = 1.0
    wf_train_t = 0.0
    wf_test_t = 0.0

    print(f"\n--- walk-forward OOS (chrono: train<{mid_date} | test>={mid_date}) ---")
    if len(train) < 10 or len(test) < 10:
        wf_status = "too_few"
        print(f"  too few rebalances: train={len(train)} test={len(test)}")
    else:
        train_nets = [r["net_excess_pct"] for r in train]
        test_nets = [r["net_excess_pct"] for r in test]

        wf_train_ev = sum(train_nets) / len(train_nets)
        wf_test_ev = sum(test_nets) / len(test_nets)

        tr_se = statistics.pstdev(train_nets) / sqrt(len(train_nets)) if len(train_nets) > 1 else 0
        te_se = statistics.pstdev(test_nets) / sqrt(len(test_nets)) if len(test_nets) > 1 else 0
        wf_train_t = wf_train_ev / tr_se if tr_se > 0 else 0
        wf_test_t = wf_test_ev / te_se if te_se > 0 else 0
        wf_test_p = norm_sf_positive(wf_test_t)

        decay = (wf_train_ev - wf_test_ev) / abs(wf_train_ev) * 100 if wf_train_ev != 0 else 0
        print(f"  train: n={len(train)} EV={wf_train_ev:.3f}% t={wf_train_t:.2f}")
        print(f"  test:  n={len(test)} EV={wf_test_ev:.3f}% t={wf_test_t:.2f} p={wf_test_p:.6f}")
        print(f"  decay: {decay:.0f}% (train→test)")

    return {
        "name": combo_name,
        "n_rebalances": n,
        "n_train": len(train),
        "n_test": len(test),
        "gross_ev": round(gross_mean, 3),
        "gross_t": round(gross_t, 2),
        "gross_p": gross_p,
        "net_ev": round(net_mean, 3),
        "net_t": round(net_t, 2),
        "net_p": net_p,
        "wf_status": wf_status,
        "wf_train_ev": round(wf_train_ev, 3),
        "wf_test_ev": round(wf_test_ev, 3),
        "wf_train_t": round(wf_train_t, 2),
        "wf_test_t": round(wf_test_t, 2),
        "wf_test_p": wf_test_p,
        "regime_strong_ev": (
            round(sum(by_regime["strong"]) / len(by_regime["strong"]), 3) if by_regime.get("strong") else None
        ),
        "regime_weak_ev": (
            round(sum(by_regime["weak"]) / len(by_regime["weak"]), 3) if by_regime.get("weak") else None
        ),
        "all_results": results,  # keep for DSR/PBO
    }


# =====================================================================
# 5. DSR (Deflated Sharpe Ratio) + PBO
# =====================================================================


def normal_cdf(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1 + erf(x / sqrt(2)))


def normal_inv_cdf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's approximation)."""
    if p <= 0:
        return -10.0
    if p >= 1:
        return 10.0
    # rational approximation
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518624690e02,
        -3.066479806617167e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609779177308e01,
        1.615858368580409e02,
        -1.555989798425870e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223161767989326e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982678786e00,
    ]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.484244904456136e00]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = sqrt(-2 * log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    elif p <= phigh:
        q = p - 0.5
        r = q * q
        x = (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        )
    else:
        q = sqrt(-2 * log(1 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    return x


def compute_dsr(returns: list[float], n_trials: int) -> dict:
    """Deflated Sharpe Ratio (Bailey-López de Prado 2014).

    Adjusts observed Sharpe for multiple testing, skew, and kurtosis.
    Returns {dsr, sr_hat, sr_0, p_dsr}.
    """
    n = len(returns)
    if n < 2:
        return {"dsr": 0.0, "sr_hat": 0.0, "sr_0": 0.0, "p_dsr": 0.5, "skew": 0.0, "kurt": 0.0, "n": n}

    mean = sum(returns) / n
    std = statistics.pstdev(returns)
    if std <= 0:
        return {"dsr": 0.0, "sr_hat": 0.0, "sr_0": 0.0, "p_dsr": 0.5, "skew": 0.0, "kurt": 0.0, "n": n}

    # per-rebalance Sharpe (non-annualized)
    sr = mean / std

    # skewness and excess kurtosis
    if n > 2:
        m3 = sum((x - mean) ** 3 for x in returns) / n
        m4 = sum((x - mean) ** 4 for x in returns) / n
        skew = m3 / (std**3)
        kurt = m4 / (std**4) - 3  # excess kurtosis
    else:
        skew = 0.0
        kurt = 0.0

    # Probabilistic Sharpe Ratio adjustment (non-annualized SR)
    # SR_0 = expected max Sharpe under N independent trials
    sr_0 = sqrt(2 * log(n_trials)) if n_trials > 1 else 0.0

    # Probabilistic Sharpe Ratio (PSR)
    # PSR = Phi( (SR - SR_0) * sqrt(T-1) / sqrt(1 - skew*SR + (kurt-1)/4 * SR^2) )
    denom = 1 - skew * sr + (kurt) / 4 * sr**2
    if denom <= 0:
        denom = 0.01  # guard against negative
    psr_arg = (sr - sr_0) * sqrt(n - 1) / sqrt(denom)
    psr = normal_cdf(psr_arg)

    return {
        "dsr": round(psr, 4),
        "sr_hat": round(sr, 4),
        "sr_0": round(sr_0, 4),
        "p_dsr": round(psr, 4),
        "skew": round(skew, 3),
        "kurt": round(kurt, 3),
        "n": n,
    }


def compute_pbo(all_combo_results: list[dict], n_bins: int = 4) -> dict:
    """Probability of Backtest Overfitting (combinatorial symmetric CV).

    Splits rebalances into n_bins, combinatorially chooses n_bins//2 for IS
    and rest for OOS. For each split, finds IS-best strategy and checks its
    OOS rank. PBO = fraction where IS-best is in bottom half OOS.

    Simplified: uses the best-combo's net excess returns per rebalance.
    """
    # Collect per-rebalance net excess for each combo (aligned by date)
    combo_names = [r["name"] for r in all_combo_results]
    # Build date -> {combo: net_excess} map
    date_combo_ret: dict[str, dict[str, float]] = defaultdict(dict)
    for cr in all_combo_results:
        for r in cr.get("all_results", []):
            date_combo_ret[r["rebalance_date"]][cr["name"]] = r["net_excess_pct"]

    all_dates = sorted(date_combo_ret.keys())
    n_total = len(all_dates)
    if n_total < n_bins * 2 or len(combo_names) < 2:
        return {"pbo": None, "reason": "too_few_data", "n_dates": n_total}

    # Split dates into n_bins roughly equal contiguous bins
    bin_size = n_total // n_bins
    bins = []
    for i in range(n_bins):
        start = i * bin_size
        end = (i + 1) * bin_size if i < n_bins - 1 else n_total
        bins.append(all_dates[start:end])

    # combinatorial: choose n_bins//2 bins for IS, rest for OOS
    from itertools import combinations

    n_is = n_bins // 2
    if n_is < 1:
        return {"pbo": None, "reason": "n_bins_too_small", "n_dates": n_total}

    is_oos_splits = list(combinations(range(n_bins), n_is))
    if not is_oos_splits:
        return {"pbo": None, "reason": "no_combinations", "n_dates": n_total}

    overfit_count = 0
    total_splits = 0

    for is_indices in is_oos_splits:
        is_dates = set()
        oos_dates = set()
        for i in range(n_bins):
            if i in is_indices:
                is_dates.update(bins[i])
            else:
                oos_dates.update(bins[i])

        if not is_dates or not oos_dates:
            continue

        # compute IS mean for each combo
        is_means: dict[str, float] = {}
        oos_means: dict[str, float] = {}
        for cn in combo_names:
            is_rets = [date_combo_ret[d][cn] for d in is_dates if cn in date_combo_ret[d]]
            oos_rets = [date_combo_ret[d][cn] for d in oos_dates if cn in date_combo_ret[d]]
            if is_rets:
                is_means[cn] = sum(is_rets) / len(is_rets)
            if oos_rets:
                oos_means[cn] = sum(oos_rets) / len(oos_rets)

        if not is_means or not oos_means:
            continue

        # find IS-best combo
        is_best = max(is_means, key=is_means.get)
        # check IS-best's OOS rank
        oos_sorted = sorted(oos_means.values(), reverse=True)
        oos_rank_of_best = oos_sorted.index(oos_means[is_best]) if oos_means[is_best] in oos_sorted else len(oos_sorted)
        # PBO: is IS-best in bottom half of OOS?
        median_rank = len(oos_sorted) // 2
        if oos_rank_of_best >= median_rank:
            overfit_count += 1
        total_splits += 1

    if total_splits == 0:
        return {"pbo": None, "reason": "no_valid_splits", "n_dates": n_total}

    pbo = overfit_count / total_splits
    return {
        "pbo": round(pbo, 4),
        "n_splits": total_splits,
        "n_combos": len(combo_names),
        "n_dates": n_total,
        "n_bins": n_bins,
    }


# =====================================================================
# 6. VERDICT
# =====================================================================


def verdict_for_combo(
    gross_ev: float,
    net_ev: float,
    net_t: float,
    net_p: float,
    wf_status: str,
    wf_train_ev: float,
    wf_test_ev: float,
    wf_test_p: float,
    n_rebalances: int,
    n_cross: int,
    combo_name: str,
) -> str:
    """Honest verdict for one combo (§44 v3 adapted for portfolio-level).

    n_cross = number of parameter combinations tested (cross-combo Bonferroni).
    """
    n_tests = max(2, n_cross)
    p_bonf = bonferroni_p(net_p, n_tests)

    print(f"\n  {combo_name}:")
    print(
        f"    gross_excess_EV={gross_ev}% net_excess_EV={net_ev}% "
        f"net_t={net_t} Bonf_p(×{n_tests})={p_bonf:.6f} "
        f"n_rebalances={n_rebalances}"
    )

    if wf_status == "ok":
        print(f"    walk-forward: train_EV={wf_train_ev}% test_EV={wf_test_ev}% test_p={wf_test_p}")

    # 1. gross < 0 → falsified (negative excess = worse than benchmark)
    if gross_ev < 0:
        print(f"    → FALSIFIED: gross excess < 0 (worse than equal-weight benchmark)")
        return "falsified"
    # 2. n too small → underpowered
    if n_rebalances < 60:
        print(f"    → UNDERPOWERED: n_rebalances={n_rebalances} < 60")
        return "underpowered"
    # 3. Bonferroni p not significant → falsified
    if p_bonf >= ALPHA:
        print(f"    → FALSIFIED: Bonferroni p={p_bonf:.6f} >= {ALPHA}")
        return "falsified"
    # 4. net <= 0 → falsified (edge eaten by cost)
    if net_ev <= 0:
        print(f"    → FALSIFIED: net excess EV={net_ev}% <= 0 (cost eats edge)")
        return "falsified"
    # 5. walk-forward
    if wf_status == "ok":
        if wf_train_ev <= 0:
            print(f"    → EXPLORATORY: train_EV={wf_train_ev}% <= 0 (edge not in train half)")
            return "exploratory"
        if wf_test_ev <= 0:
            print(f"    → FALSIFIED: walk-forward test_EV={wf_test_ev}% <= 0")
            return "falsified"
        wf_test_p_bonf = bonferroni_p(wf_test_p, n_tests)
        if wf_test_p_bonf >= ALPHA:
            print(
                f"    → EXPLORATORY: OOS test EV={wf_test_ev}% > 0 but "
                f"test p={wf_test_p} Bonf×{n_tests}={wf_test_p_bonf} >= {ALPHA}"
            )
            return "exploratory"
        print(f"    → EDGE-CONFIRMED: all checks pass")
        return "edge-confirmed"
    print(f"    → EXPLORATORY: walk-forward not available")
    return "exploratory"


# =====================================================================
# 7. MAIN
# =====================================================================


def main():
    print("=" * 70)
    print("短线策略探索: 行业动量 (sector momentum)")
    print("=" * 70)

    # ---- Step 0: verify ETF data (task requirement) ----
    print("\n[0] ETF 数据验证 (baostock fetch ETF)")
    import baostock as bs

    lg = bs.login()
    etf_ok = False
    for code in ["sh.510300", "sz.159915", "sh.510050", "sh.512890"]:
        rs = bs.query_history_k_data_plus(
            code, "date,close", start_date="2024-01-01", end_date="2024-01-31", frequency="d"
        )
        rows = []
        while (rs.error_code == "0") and rs.next():
            rows.append(rs.get_row_data())
        if rows:
            etf_ok = True
        print(f"  {code}: {len(rows)} rows (err={rs.error_code})")
    bs.logout()
    if etf_ok:
        print("  → ETF data AVAILABLE (unexpected — would proceed with ETF-level)")
    else:
        print("  → ETF data BLOCKED (baostock returns 0 rows for ETF)")
        print("  → 降级: 股票级行业动量 (code_industry 聚合, 非 ETF)")

    # ---- Step 1: load data ----
    print("\n[1] 加载数据 (股票级行业动量)")
    industry_map = load_industry_map()
    print(f"  code_industry: {len(industry_map)} codes, {len(set(industry_map.values()))} industries")

    code_map = load_kline_for_universe(set(industry_map.keys()))
    print(f"  kline (≥5yr + in industry_map): {len(code_map)} codes")

    calendar = build_calendar(code_map)
    print(f"  calendar: {calendar[0]} ~ {calendar[-1]}, {len(calendar)} days")

    regime_map = load_regime()
    r_in_cal = sum(1 for d in calendar if d in regime_map)
    print(f"  regime labels: {r_in_cal}/{len(calendar)} calendar dates labeled")

    # industry distribution
    ind_counts: dict[str, int] = defaultdict(int)
    for code in code_map:
        ind = industry_map.get(code)
        if ind:
            ind_counts[ind] += 1
    print(f"  industries with ≥5yr stocks: {len(ind_counts)}")
    top5 = sorted(ind_counts.items(), key=lambda x: -x[1])[:5]
    print(f"  top 5 by stock count: {top5}")

    # ---- Step 2: parameter grid ----
    # Focused grid to limit Bonferroni penalty
    formations = [10, 20]  # 2wk, 4wk formation
    holdings = [10, 15]  # 2wk, 3wk holding
    top_ks = [3, 5]  # top-3, top-5 industries
    combos = [(f, h, k) for f in formations for h in holdings for k in top_ks]
    n_cross = len(combos)
    print(f"\n[2] 参数网格: {n_cross} combinations")
    print(f"  formation={formations} days, holding={holdings} days, top_k={top_ks}")

    # ---- Step 3: backtest all combos ----
    print(f"\n[3] 回测 {n_cross} 组合...")
    all_results: list[dict] = []
    all_raw: list[list[dict]] = []
    for f, h, k in combos:
        name = f"F{f}_H{h}_K{k}"
        raw = backtest_combo(code_map, industry_map, calendar, regime_map, f, h, k)
        all_raw.append(raw)
        res = analyze_combo(raw, name)
        all_results.append(res)

    # ---- Step 4: verdicts with cross-combo Bonferroni ----
    print(f"\n{'=' * 70}")
    print(f"[4] Verdicts (cross-combo Bonferroni ×{n_cross})")
    print(f"{'=' * 70}")
    verdicts: dict[str, str] = {}
    for res in all_results:
        v = verdict_for_combo(
            res["gross_ev"],
            res["net_ev"],
            res["net_t"],
            res["net_p"],
            res["wf_status"],
            res["wf_train_ev"],
            res["wf_test_ev"],
            res["wf_test_p"],
            res["n_rebalances"],
            n_cross,
            res["name"],
        )
        verdicts[res["name"]] = v

    # ---- Step 5: DSR + PBO ----
    print(f"\n{'=' * 70}")
    print(f"[5] 过拟合检测 (DSR + PBO)")
    print(f"{'=' * 70}")

    # DSR for the best combo by net EV
    best_combo = max(all_results, key=lambda r: r["net_ev"])
    best_returns = [r["net_excess_pct"] for r in best_combo["all_results"]]
    dsr = compute_dsr(best_returns, n_cross)
    print(f"\n  DSR (best combo: {best_combo['name']}):")
    print(f"    SR_hat={dsr['sr_hat']} SR_0={dsr['sr_0']} skew={dsr['skew']} kurt={dsr['kurt']}")
    print(f"    DSR (p-value)={dsr['p_dsr']}")
    if dsr["p_dsr"] >= 0.95:
        print(f"    → DSR significant (p={dsr['p_dsr']} >= 0.95): Sharpe survives deflation")
    else:
        print(f"    → DSR NOT significant (p={dsr['p_dsr']} < 0.95): Sharke may be inflated by multiple testing")

    # DSR for all combos
    print(f"\n  DSR per combo:")
    for res in all_results:
        rets = [r["net_excess_pct"] for r in res["all_results"]]
        d = compute_dsr(rets, n_cross)
        print(f"    {res['name']}: SR={d['sr_hat']} DSR_p={d['p_dsr']} skew={d['skew']} kurt={d['kurt']}")

    # PBO
    pbo = compute_pbo(all_results, n_bins=4)
    print(f"\n  PBO (Probability of Backtest Overfitting):")
    if pbo.get("pbo") is not None:
        print(
            f"    PBO={pbo['pbo']} (n_splits={pbo['n_splits']}, n_combos={pbo['n_combos']}, n_dates={pbo['n_dates']})"
        )
        if pbo["pbo"] > 0.5:
            print(f"    → PBO > 0.5: likely overfit (IS-best underperforms OOS > 50%)")
        else:
            print(f"    → PBO <= 0.5: less likely overfit")
    else:
        print(f"    PBO not computable: {pbo.get('reason', 'unknown')}")

    # ---- Step 6: summary ----
    print(f"\n{'=' * 70}")
    print(f"[6] Summary")
    print(f"{'=' * 70}")

    # count verdicts
    from collections import Counter

    vc = Counter(verdicts.values())
    print(f"  verdicts: {dict(vc)}")
    print(f"  best combo: {best_combo['name']} (net_excess_EV={best_combo['net_ev']}%, t={best_combo['net_t']})")
    print(
        f"  best combo walk-forward: train={best_combo['wf_train_ev']}% "
        f"test={best_combo['wf_test_ev']}% test_p={best_combo['wf_test_p']}"
    )

    # overall verdict
    n_confirmed = vc.get("edge-confirmed", 0)
    n_falsified = vc.get("falsified", 0)
    n_underpowered = vc.get("underpowered", 0)
    n_exploratory = vc.get("exploratory", 0)

    if n_confirmed > 0 and dsr["p_dsr"] >= 0.95 and pbo.get("pbo", 1) <= 0.5:
        overall = "edge-confirmed"
    elif n_confirmed > 0:
        overall = "exploratory"  # confirmed but DSR/PBO not clean
    elif n_underpowered > 0 and n_falsified == 0 and n_confirmed == 0:
        overall = "underpowered"
    elif n_falsified > 0 and n_confirmed == 0:
        overall = "edge-falsified"
    else:
        overall = "exploratory"

    print(f"\n  overall verdict: {overall}")
    print(f"  (ETF-level BLOCKED, stock-level tested as proxy)")

    # ---- output JSON ----
    output = {
        "strategy": "sector-momentum",
        "etf_data": "BLOCKED (baostock 0 rows for all ETFs)",
        "fallback": "stock-level industry momentum (code_industry aggregation)",
        "n_codes": len(code_map),
        "n_industries": len(ind_counts),
        "calendar_range": f"{calendar[0]} ~ {calendar[-1]}",
        "n_calendar_days": len(calendar),
        "n_combos": n_cross,
        "verdicts": verdicts,
        "verdict_counts": dict(vc),
        "overall_verdict": overall,
        "best_combo": {
            "name": best_combo["name"],
            "net_ev": best_combo["net_ev"],
            "net_t": best_combo["net_t"],
            "wf_train_ev": best_combo["wf_train_ev"],
            "wf_test_ev": best_combo["wf_test_ev"],
            "wf_test_p": best_combo["wf_test_p"],
        },
        "dsr": dsr,
        "pbo": pbo,
    }
    print(f"\n{'=' * 70}")
    print("JSON output:")
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
