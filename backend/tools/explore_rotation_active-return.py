# -*- coding: utf-8 -*-
"""Sector rotation — ACTIVE-RETURN method (alpha-isolated).

Methodology change (per workflow): the original long-only absolute-EV tests
conflated alpha with market beta — a positive strategy EV could just mean
"the market went up", not that sector-timing has skill. This script ISOLATES
alpha via ACTIVE RETURN:

    active_return[t] = strategy_holding_return[t] - benchmark_holding_return[t]

    strategy  = long top-3 industries by past-N-week momentum (equal weight)
    benchmark = equal-weight ALL eligible industries (sector-neutral passive)
               => both are long the market (~beta 1), so the DIFFERENCE removes
                  market beta, leaving pure SECTOR-TIMING alpha:
                  "does picking top-momentum sectors beat holding all sectors
                  equally?"

Beta-isolation honesty check: regress active returns on 上证 (SSE) holding
returns. active_beta should be ~0 (market beta cancelled). Residual momentum-
tilt beta (momentum industries may be higher-beta cyclicals) is flagged if
non-trivial; fully neutralizing it requires the CAPM method (#4), not here.

§44 v3 strict protocol (portfolio-level adaptation):
  - realistic / no look-ahead: formation uses close[t] (signal known at t's
    close); holding return = prod(1+r) over [t+1, t+H] = close[t]->close[t+H],
    which is fully FUTURE (realizable by buying at close[t]/open[t+1], selling
    at close[t+H]). Standard Jegadeesh-Titman convention.
  - per-rebalance-block t: one active return per rebalance => effective
    N = n_rebalances (each rebalance is one independent block; no within-block
    clustering needed since the holding return is a single portfolio number).
  - Bonferroni: ×3 (formation search 2/3/4 wk) × 4 (4 parallel alpha-isolated
    methods: long-short / active-return / factor-return / capm-alpha) = ×12 on
    the best formation's p.
  - walk-forward OOS: chrono split rebalances into train (first half) / test
    (second half); require train_ev>0 (else regime overfit) + test significant.
  - cost: actual turnover (industries entering/leaving top-3) × 0.3% round-trip
    (COST). benchmark is buy-and-hold (cost=0, conservative — passive cheaper
    than active, so this makes active_net HARDER to be positive = honest).

Data: .vibe-research/sector_rotation_data.json (built by build_sector_returns.py).
Window: 2018-01-03 .. 2024-06-03 (stable ~920-code long-history core across 25
well-covered industries, before the 2024-06-04 coverage jump to the recent-wave
4293-code population — a population shift makes post-jump non-comparable, so
excluded). Degenerate tail (2026-09, 21 codes) is also before the jump cutoff.

NO EXTRAPOLATION: this tests sector-rotation TIMING alpha (active return vs
equal-weight cross-section) over 2018-2024. It does NOT speak to long-short,
factor-return, or CAPM-alpha methods (other agents), nor to ETF-level or
short-term strategies. Retail-feasible: long-only top-3 (buyable via ETF or
stock basket); benchmark = all-equal-weight (buyable).
"""
from __future__ import annotations
import json
import sys
import statistics
from collections import defaultdict
from pathlib import Path
from math import sqrt

# ---------- shared helpers (DRY: stat functions from _factor_helpers) ----------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import (  # type: ignore[import-not-found]
    ev_stats, day_paired_t, bonferroni_p, norm_sf_positive, ALPHA, COST,
)

# ---------- paths + constants ----------
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / ".vibe-research"
SECTOR_JSON = DATA / "sector_rotation_data.json"

TOP_K = 3                       # long top-3 momentum industries
HOLDING_DAYS = 10               # 2-week holding (10 trading days)
FORMATION_DAYS_LIST = [10, 15, 20]   # 2 / 3 / 4 week formation
MIN_STOCKS_PER_DATE = 5          # per-date eligibility floor for an industry
MIN_MEDIAN_STOCKS = 10           # candidate industry: median membership over window
COVERAGE_JUMP_THRESHOLD = 1500   # recent-wave onset (2024-06-04)
N_BONF_METHODS = 4               # 4 parallel alpha-isolated methods
N_BONF_FORMATIONS = 3            # 2/3/4 week formation search
N_BONF = N_BONF_METHODS * N_BONF_FORMATIONS   # = 12
REBALANCES_PER_YEAR = 26         # biweekly -> 26 rebalances/yr


# =====================================================================
# 1. DATA LOADING + WINDOW SELECTION
# =====================================================================

def load_window() -> tuple:
    """Load sector_rotation_data.json, cut to the stable long-history-core
    window (before the recent-wave coverage jump), and select candidate
    industries with stable membership.

    Returns:
        win_dates, win_bench, win_sec_rets, win_sec_memb, candidates
    """
    with open(SECTOR_JSON) as f:
        d = json.load(f)
    dates: list = d["dates"]
    bench: list = d["benchmark"]["returns"]
    sec_rets: dict = d["sector_returns"]
    sec_memb: dict = d["sector_membership"]
    cov: list = d["meta"]["coverage_per_date"]

    # cut window at the recent-wave coverage jump (population shift)
    end_idx = len(dates)
    for i, c in enumerate(cov):
        if c > COVERAGE_JUMP_THRESHOLD:
            end_idx = i
            break
    win_dates = dates[:end_idx]
    win_bench = bench[:end_idx]

    # candidate industries: median membership over window >= MIN_MEDIAN_STOCKS
    candidates: list[str] = []
    for ind in sec_rets:
        memb = sec_memb[ind][:end_idx]
        med = statistics.median(memb) if memb else 0
        if med >= MIN_MEDIAN_STOCKS:
            candidates.append(ind)
    candidates.sort()

    win_sec_rets = {ind: sec_rets[ind][:end_idx] for ind in candidates}
    win_sec_memb = {ind: sec_memb[ind][:end_idx] for ind in candidates}
    return win_dates, win_bench, win_sec_rets, win_sec_memb, candidates


# =====================================================================
# 2. CUMULATIVE RETURN (close-to-close, no look-ahead)
# =====================================================================

def cum_return(series: list, start_idx: int, end_idx: int,
               min_frac: float = 1.0) -> float | None:
    """prod(1+r) for r in series[start_idx+1 .. end_idx] => close[start] ->
    close[end]. Returns decimal or None if valid fraction < min_frac.

    start_idx: the signal/anchor date (close known).
    end_idx: the exit date (close).
    Holding return uses returns AFTER start_idx (future, no look-ahead).
    """
    if start_idx < 0 or end_idx >= len(series) or start_idx >= end_idx:
        return None
    vals = series[start_idx + 1:end_idx + 1]
    if not vals:
        return None
    n_valid = sum(1 for v in vals if v is not None)
    if n_valid / len(vals) < min_frac:
        return None
    prod = 1.0
    for v in vals:
        if v is not None:
            prod *= (1 + v)
    return prod - 1.0


# =====================================================================
# 3. BACKTEST (one formation period)
# =====================================================================

def backtest(win_dates: list, win_sec_rets: dict, win_sec_memb: dict,
             win_bench: list, formation_days: int, holding_days: int,
             top_k: int) -> list[dict]:
    """Run sector-rotation backtest for one (formation, holding, top_k) combo.

    At each rebalance date t (spaced `holding_days` apart):
      1. eligible industries = candidates with membership[t] >= MIN_STOCKS_PER_DATE
      2. formation momentum = cum_return over [t-formation_days, t]
      3. rank eligible by momentum descending; pick top_k
      4. strategy holding return = mean(top_k cum_return over [t, t+holding])
         benchmark holding return = mean(ALL eligible cum_return over [t, t+H])
      5. active_gross = strategy - benchmark
      6. turnover = n industries entering top_k / top_k (one-way traded frac)
         cost = turnover * COST (round-trip); active_net = active_gross - cost
    """
    results: list[dict] = []
    n = len(win_dates)
    t = formation_days                  # first rebalance needs formation lookback
    end_t = n - holding_days - 1        # need holding window forward
    prev_top: list[str] | None = None

    while t <= end_t:
        # 1. eligible industries at date t
        eligible: list[tuple[str, float]] = []
        for ind in win_sec_rets:
            if win_sec_memb[ind][t] < MIN_STOCKS_PER_DATE:
                continue
            f_ret = cum_return(win_sec_rets[ind], t - formation_days, t)
            if f_ret is None:
                continue
            eligible.append((ind, f_ret))
        if len(eligible) < top_k + 1:   # need top_k + benchmark breadth
            t += holding_days
            continue

        # 2. rank by formation momentum descending
        eligible.sort(key=lambda x: x[1], reverse=True)
        top_inds = [x[0] for x in eligible[:top_k]]
        all_inds = [x[0] for x in eligible]

        # 3. holding returns (close[t] -> close[t+H])
        strat_rs = [cum_return(win_sec_rets[ind], t, t + holding_days)
                    for ind in top_inds]
        bench_rs = [cum_return(win_sec_rets[ind], t, t + holding_days)
                    for ind in all_inds]
        strat_rs = [r for r in strat_rs if r is not None]
        bench_rs = [r for r in bench_rs if r is not None]
        if len(strat_rs) < top_k or len(bench_rs) < 2:
            t += holding_days
            continue

        strat_ret = sum(strat_rs) / len(strat_rs)
        bench_ret = sum(bench_rs) / len(bench_rs)
        active_gross = strat_ret - bench_ret

        # 4. turnover + cost
        if prev_top is not None:
            n_enter = len(set(top_inds) - set(prev_top))
            traded_frac = n_enter / top_k      # one-way traded fraction
        else:
            traded_frac = 1.0                   # initial buy
        cost = traded_frac * COST               # decimal round-trip cost on traded frac
        active_net = active_gross - cost

        mkt_ret = cum_return(win_bench, t, t + holding_days)

        results.append({
            "rebalance_date": win_dates[t],
            "rebalance_idx": t,
            "formation_days": formation_days,
            "holding_days": holding_days,
            "top_k": top_k,
            "strat_ret": strat_ret,
            "bench_ret": bench_ret,
            "active_gross": active_gross,
            "active_net": active_net,
            "mkt_ret": mkt_ret if mkt_ret is not None else 0.0,
            "top_inds": top_inds,
            "n_eligible": len(all_inds),
            "traded_frac": traded_frac,
        })
        prev_top = top_inds
        t += holding_days

    return results


# =====================================================================
# 4. STATISTICS (per-rebalance-block t + Bonferroni + walk-forward)
# =====================================================================

def _cov(x: list[float], y: list[float]) -> float:
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    mx, my = sum(x[:n]) / n, sum(y[:n]) / n
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / n


def _var(x: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mx = sum(x) / n
    return sum((v - mx) ** 2 for v in x) / n


def analyze(results: list[dict], formation_label: str) -> dict:
    """Statistical analysis for one formation period."""
    n = len(results)
    label = f"formation={formation_label}"
    print(f"\n{'=' * 70}")
    print(f"组合: {label}  (n_rebalances={n})")
    print(f"{'=' * 70}")

    if n == 0:
        print("  无 rebalances, 跳过")
        return {"label": label, "n_rebalances": 0}

    # --- in % for display ---
    active_gross_pct = [r["active_gross"] * 100 for r in results]
    active_net_pct = [r["active_net"] * 100 for r in results]
    strat_pct = [r["strat_ret"] * 100 for r in results]
    bench_pct = [r["bench_ret"] * 100 for r in results]

    # --- descriptive stats (reuse helper ev_stats) ---
    gs = ev_stats(active_gross_pct)        # mean/std/t/ci/wr of active gross
    ns = ev_stats(active_net_pct)          # active net
    strat_s = ev_stats(strat_pct)
    bench_s = ev_stats(bench_pct)

    # --- per-rebalance-block t (reuse helper day_paired_t; one obs/date) ---
    by_date = {r["rebalance_date"]: [r["active_gross"] * 100] for r in results}
    gdt = day_paired_t(by_date)             # {n_days, mean, std, t, p_one_sided}
    p_gross = gdt["p_one_sided"]
    t_gross = gdt["t"]

    by_date_net = {r["rebalance_date"]: [r["active_net"] * 100] for r in results}
    ndt = day_paired_t(by_date_net)
    p_net = ndt["p_one_sided"]

    print(f"\n--- active gross (strategy - equal-weight benchmark, pre-cost) ---")
    print(f"  n_rebalances={n} mean={gs['ev']:.4f}% std={gs['std']:.4f}% "
          f"WR={gs['wr']:.1f}% t={t_gross:.2f} p_one_sided={p_gross:.6f}")
    print(f"  CI[{gs['ci_lo']:.4f}, {gs['ci_hi']:.4f}]")
    print(f"  strategy avg={strat_s['ev']:.4f}%  benchmark avg={bench_s['ev']:.4f}%")

    print(f"\n--- active net (after turnover cost) ---")
    print(f"  mean={ns['ev']:.4f}% std={ns['std']:.4f}% WR={ns['wr']:.1f}% "
          f"t={ndt['t']:.2f} p_one_sided={p_net:.6f}")

    # --- Sharpe (annualized, biweekly) ---
    sharpe_per = gs["ev"] / gs["std"] if gs["std"] > 0 else 0.0
    sharpe_ann = sharpe_per * sqrt(REBALANCES_PER_YEAR)
    strat_sharpe_ann = (strat_s["ev"] / strat_s["std"]
                        if strat_s["std"] > 0 else 0.0) * sqrt(REBALANCES_PER_YEAR)
    print(f"\n--- Sharpe (annualized, ×sqrt(26)) ---")
    print(f"  active Sharpe={sharpe_ann:.3f}  strategy Sharpe={strat_sharpe_ann:.3f}")

    # --- beta vs market (alpha-isolation check) ---
    mkt_dec = [r["mkt_ret"] for r in results]
    active_dec = [r["active_gross"] for r in results]
    strat_dec = [r["strat_ret"] for r in results]
    var_mkt = _var(mkt_dec)
    beta_strat = _cov(strat_dec, mkt_dec) / var_mkt if var_mkt > 0 else 0.0
    beta_active = _cov(active_dec, mkt_dec) / var_mkt if var_mkt > 0 else 0.0
    print(f"\n--- beta vs 上证 (alpha-isolation check) ---")
    print(f"  strategy beta={beta_strat:.3f}  active beta={beta_active:.3f} "
          f"(active~0 => market beta cancelled)")

    # --- turnover / cost ---
    avg_turnover = sum(r["traded_frac"] for r in results) / n
    avg_cost_pct = avg_turnover * COST * 100
    print(f"\n--- turnover + cost ---")
    print(f"  avg one-way traded fraction={avg_turnover:.3f} "
          f"=> avg cost={avg_cost_pct:.4f}%/rebalance")

    # --- walk-forward OOS (chrono split) ---
    reb_dates = sorted(set(r["rebalance_date"] for r in results))
    mid_date = reb_dates[len(reb_dates) // 2]
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
        train_g = [r["active_gross"] * 100 for r in train]
        test_g = [r["active_gross"] * 100 for r in test]
        wf_train_ev = sum(train_g) / len(train_g)
        wf_test_ev = sum(test_g) / len(test_g)
        tr_se = (statistics.pstdev(train_g) / sqrt(len(train_g))
                 if len(train_g) > 1 else 0.0)
        te_se = (statistics.pstdev(test_g) / sqrt(len(test_g))
                 if len(test_g) > 1 else 0.0)
        wf_train_t = wf_train_ev / tr_se if tr_se > 0 else 0.0
        wf_test_t = wf_test_ev / te_se if te_se > 0 else 0.0
        wf_test_p = norm_sf_positive(wf_test_t)
        decay = ((wf_train_ev - wf_test_ev) / abs(wf_train_ev) * 100
                 if wf_train_ev != 0 else 0)
        print(f"  train: n={len(train)} active_gross_EV={wf_train_ev:.4f}% "
              f"t={wf_train_t:.2f}")
        print(f"  test:  n={len(test)} active_gross_EV={wf_test_ev:.4f}% "
              f"t={wf_test_t:.2f} p={wf_test_p:.6f}")
        print(f"  decay: {decay:.0f}% (train->test)")

    return {
        "label": label,
        "formation_days": results[0]["formation_days"] if results else 0,
        "n_rebalances": n,
        "active_gross_ev": gs["ev"],
        "active_gross_t": round(t_gross, 2),
        "active_gross_p": p_gross,
        "active_net_ev": ns["ev"],
        "active_net_t": round(ndt["t"], 2),
        "active_net_p": p_net,
        "strat_ev": strat_s["ev"],
        "bench_ev": bench_s["ev"],
        "wr_gross": gs["wr"],
        "sharpe_active_ann": round(sharpe_ann, 3),
        "sharpe_strategy_ann": round(strat_sharpe_ann, 3),
        "beta_strategy": round(beta_strat, 3),
        "beta_active": round(beta_active, 3),
        "avg_turnover": round(avg_turnover, 3),
        "avg_cost_pct": round(avg_cost_pct, 4),
        "wf_status": wf_status,
        "wf_train_ev": round(wf_train_ev, 4),
        "wf_test_ev": round(wf_test_ev, 4),
        "wf_train_t": round(wf_train_t, 2),
        "wf_test_t": round(wf_test_t, 2),
        "wf_test_p": wf_test_p,
        "mid_date": mid_date,
        "n_train": len(train),
        "n_test": len(test),
    }


# =====================================================================
# 5. VERDICT (alpha-isolated, active-return)
# =====================================================================

def verdict_for(a: dict, n_bonf: int) -> str:
    """Honest verdict for one formation period.

    Cascade (alpha-isolated active return):
      1. active_gross < 0  -> falsified (negative sector-timing alpha)
      2. n_rebalances < 60 -> underpowered
      3. Bonferroni(active_gross_p) × n_bonf >= 0.05 -> falsified (not sig)
      4. active_net <= 0   -> falsified (alpha eaten by cost, not tradeable)
      5. walk-forward train active_gross <= 0 -> exploratory (no alpha in train)
      6. walk-forward test active_gross <= 0  -> falsified (no alpha OOS)
      7. walk-forward test_p Bonferroni >= 0.05 -> exploratory (OOS not sig)
      8. all pass -> edge-confirmed
    """
    p_bonf = bonferroni_p(a["active_gross_p"], n_bonf)
    wf_test_p_bonf = bonferroni_p(a["wf_test_p"], n_bonf)

    print(f"\n  {a['label']}:")
    print(f"    active_gross_EV={a['active_gross_ev']}% net_EV={a['active_net_ev']}% "
          f"t={a['active_gross_t']} Bonf_p(×{n_bonf})={p_bonf:.6f} "
          f"n_rebal={a['n_rebalances']}")
    print(f"    beta_active={a['beta_active']} (vs 上证; ~0 => beta isolated)")
    if a["wf_status"] == "ok":
        print(f"    walk-forward: train={a['wf_train_ev']}% test={a['wf_test_ev']}% "
              f"test_p={a['wf_test_p']} Bonf_test_p(×{n_bonf})={wf_test_p_bonf:.6f}")

    if a["active_gross_ev"] < 0:
        print(f"    -> FALSIFIED: active gross < 0 (worse than equal-weight benchmark)")
        return "falsified"
    if a["n_rebalances"] < 60:
        print(f"    -> UNDERPOWERED: n_rebalances={a['n_rebalances']} < 60")
        return "underpowered"
    if p_bonf >= ALPHA:
        print(f"    -> FALSIFIED: Bonferroni p={p_bonf:.6f} >= {ALPHA} "
              f"(alpha not significant after ×{n_bonf} correction)")
        return "falsified"
    if a["active_net_ev"] <= 0:
        print(f"    -> FALSIFIED: active_net={a['active_net_ev']}% <= 0 "
              f"(alpha eaten by turnover cost, not tradeable)")
        return "falsified"
    if a["wf_status"] == "ok":
        if a["wf_train_ev"] <= 0:
            print(f"    -> EXPLORATORY: train_EV={a['wf_train_ev']}% <= 0 "
                  f"(no alpha in train half; test alpha may be regime overfit)")
            return "exploratory"
        if a["wf_test_ev"] <= 0:
            print(f"    -> FALSIFIED: walk-forward test_EV={a['wf_test_ev']}% <= 0 "
                  f"(no alpha OOS)")
            return "falsified"
        if wf_test_p_bonf >= ALPHA:
            print(f"    -> EXPLORATORY: OOS test EV={a['wf_test_ev']}% > 0 but "
                  f"test_p={a['wf_test_p']} Bonf×{n_bonf}={wf_test_p_bonf:.6f} "
                  f">= {ALPHA} (OOS not significant)")
            return "exploratory"
        print(f"    -> EDGE-CONFIRMED: active gross+net > 0, Bonferroni PASS, "
              f"OOS test EV={a['wf_test_ev']}% significant "
              f"(test_p={a['wf_test_p']}, Bonf={wf_test_p_bonf:.6f})")
        return "edge-confirmed"
    print(f"    -> EXPLORATORY: walk-forward not available")
    return "exploratory"


# =====================================================================
# 6. MAIN
# =====================================================================

def main():
    print("=" * 70)
    print("行业轮动 — ACTIVE-RETURN method (alpha-isolated)")
    print("  active_return = strategy(top-3 momentum) - equal-weight benchmark")
    print("=" * 70)

    # ---- Step 1: load + window ----
    print("\n[1] 加载数据 + 窗口选择")
    win_dates, win_bench, win_sec_rets, win_sec_memb, candidates = load_window()
    print(f"  window: {win_dates[0]} ~ {win_dates[-1]} ({len(win_dates)} days)")
    print(f"  candidate industries (median membership >= {MIN_MEDIAN_STOCKS}): "
          f"{len(candidates)}")
    print(f"  benchmark: 上证指数 (SSE), {sum(1 for r in win_bench if r is not None)} "
          f"non-null returns")
    print(f"  Bonferroni: ×{N_BONF} ({N_BONF_METHODS} methods × {N_BONF_FORMATIONS} "
          f"formations)")

    # ---- Step 2: backtest all formation periods ----
    print(f"\n[2] 回测 {len(FORMATION_DAYS_LIST)} formation periods "
          f"(holding={HOLDING_DAYS}d, top_k={TOP_K})")
    all_analyses: list[dict] = []
    for fd in FORMATION_DAYS_LIST:
        label = f"{fd}d ({fd//5}wk)"
        results = backtest(win_dates, win_sec_rets, win_sec_memb, win_bench,
                           fd, HOLDING_DAYS, TOP_K)
        a = analyze(results, label)
        all_analyses.append(a)

    # ---- Step 3: verdicts with ×12 Bonferroni ----
    print(f"\n{'=' * 70}")
    print(f"[3] Verdicts (Bonferroni ×{N_BONF})")
    print(f"{'=' * 70}")
    verdicts: dict[str, str] = {}
    for a in all_analyses:
        v = verdict_for(a, N_BONF)
        verdicts[a["label"]] = v

    # ---- Step 4: best formation (lowest p) ----
    best = max(all_analyses, key=lambda x: x["active_gross_ev"]
               if x["n_rebalances"] > 0 else -999)
    print(f"\n{'=' * 70}")
    print(f"[4] Best formation (by active_gross_EV)")
    print(f"{'=' * 70}")
    print(f"  best: {best['label']}  active_gross_EV={best['active_gross_ev']}% "
          f"t={best['active_gross_t']} p={best['active_gross_p']}")
    print(f"  Bonferroni p (×{N_BONF}) = "
          f"{bonferroni_p(best['active_gross_p'], N_BONF):.6f}")
    print(f"  active_net_EV={best['active_net_ev']}%  "
          f"beta_active={best['beta_active']}  "
          f"sharpe_active_ann={best['sharpe_active_ann']}")
    print(f"  walk-forward: train={best['wf_train_ev']}% "
          f"test={best['wf_test_ev']}% test_p={best['wf_test_p']}")
    print(f"  verdict: {verdicts[best['label']]}")

    # ---- Step 5: verdict tally + overall ----
    from collections import Counter
    vc = Counter(verdicts.values())
    print(f"\n{'=' * 70}")
    print(f"[5] Summary")
    print(f"{'=' * 70}")
    print(f"  verdicts: {dict(vc)}")
    n_conf = vc.get("edge-confirmed", 0)
    n_false = vc.get("falsified", 0)
    n_under = vc.get("underpowered", 0)
    n_expl = vc.get("exploratory", 0)
    if n_conf > 0:
        overall = "edge-confirmed"
    elif n_expl > 0 and n_false == 0:
        overall = "exploratory"
    elif n_under > 0 and n_false == 0 and n_conf == 0:
        overall = "underpowered"
    elif n_false > 0 and n_conf == 0:
        overall = "edge-falsified"
    else:
        overall = "exploratory"

    print(f"  overall verdict: {overall}")
    print(f"  (long-only active-return; alpha = strategy - equal-weight benchmark)")
    print(f"  (NO EXTRAPOLATION: sector-rotation timing only, 2018-2024 window)")

    # ---- JSON output ----
    output = {
        "strategy": "sector-rotation-active-return",
        "method": "active-return (strategy - equal-weight benchmark)",
        "alpha_isolation": "active return removes market beta by construction "
                           "(both long market); beta_active reported (~0 = isolated)",
        "window": f"{win_dates[0]} ~ {win_dates[-1]} ({len(win_dates)} days)",
        "n_candidate_industries": len(candidates),
        "top_k": TOP_K,
        "holding_days": HOLDING_DAYS,
        "bonferroni_n": N_BONF,
        "verdicts": verdicts,
        "verdict_counts": dict(vc),
        "overall_verdict": overall,
        "best_formation": {
            "label": best["label"],
            "formation_days": best["formation_days"],
            "n_rebalances": best["n_rebalances"],
            "active_gross_ev": best["active_gross_ev"],
            "active_gross_t": best["active_gross_t"],
            "active_gross_p": best["active_gross_p"],
            "bonferroni_p": bonferroni_p(best["active_gross_p"], N_BONF),
            "active_net_ev": best["active_net_ev"],
            "active_net_p": best["active_net_p"],
            "strat_ev": best["strat_ev"],
            "bench_ev": best["bench_ev"],
            "wr_gross": best["wr_gross"],
            "sharpe_active_ann": best["sharpe_active_ann"],
            "sharpe_strategy_ann": best["sharpe_strategy_ann"],
            "beta_strategy": best["beta_strategy"],
            "beta_active": best["beta_active"],
            "avg_turnover": best["avg_turnover"],
            "avg_cost_pct": best["avg_cost_pct"],
            "wf_status": best["wf_status"],
            "wf_train_ev": best["wf_train_ev"],
            "wf_test_ev": best["wf_test_ev"],
            "wf_test_t": best["wf_test_t"],
            "wf_test_p": best["wf_test_p"],
            "n_train": best["n_train"],
            "n_test": best["n_test"],
            "verdict": verdicts[best["label"]],
        },
    }
    print(f"\n{'=' * 70}")
    print("JSON output:")
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
