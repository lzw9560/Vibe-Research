# -*- coding: utf-8 -*-
"""combo statistical rigor — compute the MISSING stats (2026-11-07).

Q1 forking-paths: reproduce t_nw, then Bonferroni/D sensitivity at K=50..1000.
Q2 DSR/PBO: compute DSR (Bailey-LopezdePrado) at multiple N_trials on the
   day-clustered return series; PBO needs trials_matrix (note if absent).
Q3 verifier pipeline: selection_lift (day-paired winrate lift vs universe) +
   permutation p (within-day resample) + BH-FDR — the tests combo never ran.
Q4 orthogonalization: per-day cross-sectional OLS real_exec ~ size+momentum,
   residual alpha for picks (vs R12-style amt-decile matching, since no turn
   in cache -> R12 cap is non-reproducible).

Production口径: mode=filtered (skip today涨停), real-exec T+1 open->T+5 close,
P0 fixes (T+1 vol>0, T+1 open not涨停, not一字板). NO isST (absent in cache).
NO turn (absent -> size proxy = amt, NOT float cap).
"""
from __future__ import annotations
import json
import math
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vr_paths import resolve_data_dir
DB = resolve_data_dir() / "baostock_kline_cache.db"
COST = 0.004
TOP_N = 20


def board_limit(code: str) -> float:
    c = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    if c.startswith("30") or c.startswith("68"):
        return 0.20
    if c.startswith("8") or c.startswith("4"):
        return 0.30
    return 0.10


def build_by_date() -> dict:
    """Per day: list of {code, gap, tr, amt, real_exec, close_close}. Production filtered."""
    conn = sqlite3.connect(str(DB))
    by_date: dict = defaultdict(list)
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        if code.startswith("920"):
            continue
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        if len(bars) < 70:
            continue
        bl = board_limit(code)
        for i in range(60, len(bars) - 5):
            prev_c = float(bars[i - 1].get("close", 0) or 0)
            o = float(bars[i].get("open", 0) or 0)
            c = float(bars[i].get("close", 0) or 0)
            amt = float(bars[i].get("amount", 0) or 0)
            if not prev_c or not c or not o or not amt:
                continue
            today_ret = (c - prev_c) / prev_c
            gap = (o - prev_c) / prev_c
            if today_ret >= bl:           # mode=filtered: skip 涨停
                continue
            t1 = bars[i + 1]
            t1_open = float(t1.get("open", 0) or 0)
            t1_high = float(t1.get("high", 0) or 0)
            t1_low = float(t1.get("low", 0) or 0)
            t1_vol = float(t1.get("volume", 0) or 0)
            t5_close = float(bars[i + 5].get("close", 0) or 0)
            if not t1_open or not t5_close:
                continue
            if t1_vol <= 0:               # P0 fix: T+1 停牌
                continue
            t1_gap = (t1_open - c) / c
            if t1_gap >= bl:              # P0 fix: T+1 open 涨停
                continue
            if t1_open == t1_high == t1_low and t1_gap >= bl * 0.98:  # 一字板
                continue
            real_exec = (t5_close - t1_open) / t1_open
            close_close = (t5_close - c) / c
            by_date[bars[i].get("date", "")].append({
                "code": code, "gap": gap, "tr": today_ret, "amt": amt,
                "real_exec": real_exec, "close_close": close_close,
            })
    conn.close()
    return by_date


def rank_top(lst: list, n: int = TOP_N, use_gap=True):
    nn = len(lst)
    sg = sorted(range(nn), key=lambda k: lst[k]["gap"])
    st = sorted(range(nn), key=lambda k: lst[k]["tr"])
    sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
    rg = {o: r / nn for r, o in enumerate(sg)}
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    score = (lambda k: rg[k] + rt[k] + ra[k]) if use_gap else (lambda k: rt[k] + ra[k])
    return sorted(range(nn), key=score, reverse=True)[:n]


def nw_t(series, min_lag=5):
    n = len(series)
    if n < 5:
        return 0.0, float(n)
    m = statistics.mean(series)
    var = statistics.pvariance(series)
    if var <= 0:
        return 0.0, float(n)
    lag = min(max(min_lag, int(4 * (n / 100) ** (2 / 9))), n - 1)
    rho_sum = 0.0
    for k in range(1, lag + 1):
        if n - k <= 0:
            break
        cov_k = sum((series[t] - m) * (series[t + k] - m) for t in range(n - k)) / n
        rho_k = cov_k / var
        rho_sum += rho_k
    denom = 1 + 2 * rho_sum
    n_eff = n / denom if denom > 0 else float(n)
    se = math.sqrt(var / n_eff) if n_eff > 0 else math.sqrt(var / n)
    return (m / se if se > 0 else 0.0), n_eff


def bonf_threshold_z(K, alpha=0.05, two_sided=True):
    """Bonferroni z-threshold for K trials."""
    from scipy.stats import norm
    p_adj = alpha / K
    if two_sided:
        return norm.ppf(1 - p_adj / 2)
    return norm.ppf(1 - p_adj)


def main():
    from scipy.stats import norm
    import numpy as np
    sys.path.insert(0, str(ROOT / "s44_verifier"))
    from overfit import deflated_sharpe_ratio, sharpe_ratio, _skew_kurt

    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    print(f"=== combo rigor (production mode=filtered real-exec, {len(all_d)} 日 "
          f"{all_d[0]}~{all_d[-1]}) ===\n")

    # Daily portfolio means (real_exec) + universe per day
    daily_pick_mean = []      # mean real_exec of top-20 picks per day
    daily_pick_means_list = []  # full series
    daily_univ_mean = []     # mean real_exec of universe per day
    daily_pick_wr = []
    daily_univ_wr = []
    dates_kept = []
    # for OLS orthogonalization: per day store pick real_exec + amt_rank + tr_rank
    ols_pick_resid_daily = []   # daily mean of pick residuals
    # R12-style amt-decile matching alpha daily
    amt_decile_alpha_daily = []
    # permutation: store per-day universe real_exec lists + pick mean
    perm_days = []  # (univ_rets, pick_mean)

    for d in all_d:
        lst = by_date[d]
        if len(lst) < TOP_N * 10:
            continue
        top_idx = rank_top(lst)
        picks = [lst[k] for k in top_idx]
        preals = [p["real_exec"] for p in picks]
        ureals = [x["real_exec"] for x in lst]
        pm = statistics.mean(preals)
        um = statistics.mean(ureals)
        daily_pick_mean.append(pm)
        daily_univ_mean.append(um)
        daily_pick_means_list.append(pm)
        daily_pick_wr.append(sum(1 for x in preals if x > 0) / len(preals))
        daily_univ_wr.append(sum(1 for x in ureals if x > 0) / len(ureals))
        dates_kept.append(d)
        perm_days.append((ureals, pm))

        # --- cross-sectional OLS: real_exec ~ amt_rank + tr_rank (demeaned) ---
        nn = len(lst)
        amtr = [r / nn for r in sorted(range(nn), key=lambda k: lst[k]["amt"])]
        trr = [r / nn for r in sorted(range(nn), key=lambda k: lst[k]["tr"])]
        # build per-index rank maps
        sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
        st = sorted(range(nn), key=lambda k: lst[k]["tr"])
        amt_rank = {o: r / nn for r, o in enumerate(sa)}     # low amt -> low rank
        tr_rank = {o: r / nn for r, o in enumerate(st)}
        y = np.array([lst[k]["real_exec"] for k in range(nn)])
        x_amt = np.array([amt_rank[k] for k in range(nn)])
        x_tr = np.array([tr_rank[k] for k in range(nn)])
        X = np.column_stack([np.ones(nn), x_amt, x_tr])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ coef
        pick_resid = [resid[k] for k in top_idx]
        ols_pick_resid_daily.append(statistics.mean(pick_resid))

        # --- R12-style amt-decile matching (10 buckets by amt, low=small) ---
        dec = [0] * nn
        for rank_pos, orig in enumerate(sa):
            dec[orig] = min(9, rank_pos * 10 // nn)
        by_dec = defaultdict(list)
        for k in range(nn):
            by_dec[dec[k]].append(lst[k]["real_exec"])
        dec_avg = {dk: (statistics.mean(v) if v else 0.0) for dk, v in by_dec.items()}
        day_alpha = [lst[k]["real_exec"] - dec_avg[dec[k]] for k in top_idx]
        amt_decile_alpha_daily.append(statistics.mean(day_alpha))

    n_days = len(daily_pick_mean)
    pm_mean = statistics.mean(daily_pick_mean)
    um_mean = statistics.mean(daily_univ_mean)
    t_nw, n_eff = nw_t(daily_pick_mean)
    print(f"【重现 production real_exec】days={n_days} picks/day={TOP_N}")
    print(f"  pick mean={pm_mean*100:+.4f}% universe mean={um_mean*100:+.4f}% "
          f"lift(mean)={pm_mean/um_mean if um_mean else float('nan'):.3f}x")
    print(f"  pick WR={statistics.mean(daily_pick_wr)*100:.1f}% univ WR={statistics.mean(daily_univ_wr)*100:.1f}% "
          f"lift(WR)={statistics.mean(daily_pick_wr)/statistics.mean(daily_univ_wr):.3f}x")
    print(f"  net(pick-COST)={(pm_mean-COST)*100:+.4f}%  t_ols={pm_mean/(statistics.pstdev(daily_pick_mean)/n_days**0.5):.2f} "
          f"t_nw={t_nw:.2f}  n_eff={n_eff:.0f}")
    print(f"  universe net={(um_mean-COST)*100:+.4f}%  → edge over universe net={(pm_mean-um_mean)*100:+.4f}%/day")
    print()

    # ============ Q1: forking-paths / Bonferroni sensitivity ============
    print("【Q1 forking-paths Bonferroni sensitivity】t_nw 在多少 K 下还显著？")
    print(f"  observed t_nw={t_nw:.3f} (n_eff={n_eff:.0f})")
    print(f"  {'K(trials)':<12}{'Bonf z(2-side)':<16}{'verdict':<20}")
    for K in (3, 8, 50, 100, 200, 300, 500, 750, 1000, 2000):
        z = bonf_threshold_z(K)
        verdict = "PASS" if t_nw > z else "FAIL"
        print(f"  {K:<12}{z:<16.3f}{verdict}")
    # naive parameter-space product
    n_factors_combo = 7; n_hold = 3; n_topn = 8; n_entry = 3; n_stop = 5
    naive = n_factors_combo * n_hold * n_topn * n_entry * n_stop
    print(f"  naive param product (7combo×3hold×8topN×3entry×5stop)={naive} (×12 rounds if independent)")
    print()

    # ============ Q2: DSR ============
    print("【Q2 DSR (Deflated Sharpe) — Bailey & LopezdePrado】")
    rets = np.array(daily_pick_mean)
    sr = sharpe_ratio(rets)
    skew, kurt = _skew_kurt(rets)
    print(f"  per-day SR={sr:.4f}  skew={skew:.3f}  kurt(non-excess)={kurt:.3f}  n_obs={len(rets)}")
    # DSR at multiple N, using n_obs=nominal AND n_eff
    for n_obs in (len(rets), int(round(n_eff))):
        print(f"  --- n_obs={n_obs} ({'n_eff' if n_obs!=len(rets) else 'nominal days'}) ---")
        for Ntrials in (1, 8, 50, 100, 200, 500, 1000):
            res = deflated_sharpe_ratio(rets[:n_obs] if n_obs < len(rets) else rets, n_trials=Ntrials)
            print(f"    N_trials={Ntrials:<5} SR0(deflate bench)={res.deflated_benchmark_sr0*100:+.4f} "
                  f"PSR_vs_0={res.psr_vs_zero:.4f} DSR={res.deflated_sharpe_ratio:.4f} "
                  f"{'PASS' if res.passed else 'FAIL'}(>=0.95)")
    # MinTRL
    from overfit import minimum_track_record_length
    res1 = deflated_sharpe_ratio(rets, n_trials=100)
    mtrl = minimum_track_record_length(res1.observed_sharpe, res1.deflated_benchmark_sr0, skew, kurt)
    print(f"  MinTRL(N=100): need {mtrl:.0f} obs for significance (have {len(rets)})")
    print(f"  PBO/CSCV: requires trials_matrix (all strategy variants × folds). combo 不保留 → 不可算, 是 gap")
    print()

    # ============ Q3: verifier pipeline — selection lift + permutation ============
    print("【Q3 verifier pipeline: selection_lift + permutation p (combo 从未跑过)】")
    # day-paired winrate lift (non-pooled) — verifier's selection_lift
    wr_lifts = []
    mean_lifts = []
    for pw, uw in zip(daily_pick_wr, daily_univ_wr):
        if uw > 0:
            wr_lifts.append(pw / uw)
    for pm, um in zip(daily_pick_mean, daily_univ_mean):
        if um != 0:
            mean_lifts.append(pm / um)
    print(f"  day-paired WR lift (non-pooled avg)={statistics.mean(wr_lifts):.4f}x "
          f"(verifier robust_edge 需 >=2.0)")
    print(f"  day-paired mean lift={statistics.mean(mean_lifts):.4f}x")
    print(f"  → verifier robust_edge gate: lift>=2.0 AND p_bonf<0.05. lift={statistics.mean(wr_lifts):.3f}x "
          f"{'❌ 远低于2.0 → not robust_edge (exploratory/falsified)' if statistics.mean(wr_lifts)<2.0 else '✅'}")
    # permutation p: within-day resample 20 from universe, mean lift, 1000 perms
    import random
    rng = random.Random(42)
    n_perm = 1000
    observed_mean_lift = statistics.mean(mean_lifts)
    null_lifts = []
    for ureals, pm_obs in perm_days:
        pass
    # permutation on MEAN return: resample 20 from universe, compute mean, compare
    null_means = []
    for ureals, pm_obs in perm_days:
        if len(ureals) < TOP_N:
            continue
        day_nulls = []
        for _ in range(50):  # 50 per day × ~2000 days = enough
            samp = rng.sample(ureals, TOP_N)
            day_nulls.append(statistics.mean(samp))
        null_means.append((statistics.mean(day_nulls), pm_obs))
    # pooled permutation: fraction of perm-day-means >= observed pick mean
    ge = sum(1 for nm, pm_obs in null_means if nm >= pm_obs)
    p_perm_mean = (ge + 1) / (len(null_means) + 1)
    # also: mean of (null_mean - obs) how often >= 0 across days (day-level sign)
    days_beat = sum(1 for nm, pm_obs in null_means if nm >= pm_obs)
    print(f"  permutation p (mean return, within-day resample, {(len(null_means))} days×50): "
          f"P(null_day_mean >= pick_mean) day-level = {p_perm_mean:.4f}")
    print(f"  days where resample beat picks: {days_beat}/{len(null_means)} ({days_beat/len(null_means)*100:.1f}%)")
    print()

    # ============ Q4: orthogonalization ============
    print("【Q4 orthogonalization: OLS real_exec~size(amt)+momentum(tr) residual alpha】")
    # combo uses gap+tr+small. OLS controls linear size(amt)+momentum(tr). gap is NOT controlled.
    ols_t, ols_neff = nw_t(ols_pick_resid_daily)
    ols_mean = statistics.mean(ols_pick_resid_daily)
    print(f"  OLS residual alpha (pick fwd5 - linear[amt+tr] fit):")
    print(f"    daily mean residual={ols_mean*100:+.4f}%  t_nw={ols_t:.2f}  n_eff={ols_neff:.0f}")
    print(f"    {'✅ alpha 存活(超线性 size+momentum)' if ols_t>2.4 and ols_mean>0 else '❌ alpha 不存活=线性 size+momentum 解释掉'}")
    # R12-style amt decile matching (size only, 10 buckets)
    r12_t, r12_neff = nw_t(amt_decile_alpha_daily)
    r12_mean = statistics.mean(amt_decile_alpha_daily)
    print(f"  amt-decile matching alpha (R12-style, size-only, 10 buckets, NO turn/cap):")
    print(f"    daily mean alpha={r12_mean*100:+.4f}%  t_nw={r12_t:.2f}  n_eff={r12_neff:.0f}")
    print(f"    {'✅' if r12_t>2.4 and r12_mean>0 else '⚠️/❌'}  (note: R12 cap 用 turn 不在 cache→原 t6.85 不可复现)")
    print(f"  raw pick net={pm_mean*100:+.4f}%  vs  OLS-resid net={(ols_mean)*100:+.4f}%  vs  amt-decile alpha={(r12_mean)*100:+.4f}%")
    print(f"  → alpha_share(OLS)={ols_mean/pm_mean*100:.1f}%  alpha_share(amt-decile)={r12_mean/pm_mean*100:.1f}%")
    print(f"  注: OLS 只控 size+momentum 线性, 未控 industry(无数据)/gap(combo 自用未控)/style")
    print()

    # ============ live vs backtest gap ============
    print("【live-vs-backtest gap (memory: live -3.249% vs backtest +0.196%)】")
    print(f"  backtest net(pick-COST)={(pm_mean-COST)*100:+.4f}%  vs live overall -3.249%")
    print(f"  gap={((pm_mean-COST)-(-0.03249))*100:+.4f}% — 回测虚高方向确认")


if __name__ == "__main__":
    main()
