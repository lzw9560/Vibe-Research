# -*- coding: utf-8 -*-
"""残差 alpha 多因子 OLS 归因 — combined-microcap-portfolio (size+low-vol 组合).

第 6 种方法学: residual-edge-analyzer (残差 alpha 多因子 OLS 归因)
  r_combo = alpha + beta_mkt*r_mkt + residual                               (primary, simplified)
  r_combo = alpha + beta_mkt*r_mkt + beta_smb*SMB + beta_umd*UMD + residual (sensitivity)

策略: combined-microcap-portfolio = 0.5*SMB + 0.5*lowvol (equal-weight blend)
  - SMB    = size factor (long small-cap, short large-cap) — from factor_baselines.json
  - lowvol = low-volatility factor (long low-vol, short high-vol) — built from kline cache
  - 若 size≈low-vol 非独立, 组合后控 mkt 后还有 alpha 吗?

为何新方法学: 之前 CAPM 只控市场单因子. 残差 alpha 分析同时控多 baseline
  (市场+SMB+UMD), 测策略收益减所有因子暴露后的残差 alpha. 能解
  "size≈low-vol 非独立" — 互相控制后还有独立 alpha 吗?

诚实约束 (禁止外推):
  1. long-short 需做空 (A股散户融券受限), 统计 alpha ≠ 可交易
  2. SMB proxy = log(20d 均成交额) 是流动性/换手代理, 非真市值
  3. HML 缺失 (3-factor baseline: mkt+SMB+UMD, 非 4-factor Carhart)
  4. SMB 与 UMD 强负相关 (-0.71, VIF~2.0), 多重共线性膨胀 SE
  5. 组合 alpha ≠ size/low-vol 各自有 edge ≠ 选股战法有 edge
  6. close-to-close 日收益 (非 open_ev, 防日内泄漏)

跑法:
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
  .venv/bin/python tools/explore_residual_combined-microcap-portfolio.py
"""

from __future__ import annotations
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import statsmodels.api as sm

# import shared infrastructure (DRY)
sys.path.insert(0, str(Path(__file__).parent))
from build_factor_baselines import (  # noqa: E402
    DATA,
    LIQ_AMT_FLOOR,
    MIN_DECILE_STOCKS,
    scan_kline_dates,
    load_calendar_and_index,
    load_panels,
    daily_returns,
    month_end_dates,
    form_decile_legs,
)
from _factor_helpers import bonferroni_p, norm_sf_positive  # noqa: E402

# ---------- constants ----------

FACTOR_BASELINES = DATA / "factor_baselines.json"
VOL_DAYS = 20
ROLLING_WINDOW = 60
ALPHA_LEVEL = 0.05
N_BONF = 4  # 4 strategies in parallel (cross-strategy Bonferroni)
REGIME_BULL = 0.03  # 60d cumulative market return > 3% = bull
REGIME_BEAR = -0.03  # < -3% = bear


# ---------- load factor baselines ----------


def load_baselines() -> dict:
    """Load mkt, SMB, UMD daily series from factor_baselines.json."""
    d = json.loads(FACTOR_BASELINES.read_text())
    return d["factor_series"]


# ---------- build low-vol daily factor series ----------


def build_lowvol_series(close: np.ndarray, amount: np.ndarray, ret: np.ndarray, calendar: list[str], rebal_idx: list[int]) -> dict[str, float]:
    """Low-vol daily returns: month-end rebalance, 20d return std signal.

    long = bottom decile (LOW volatility, low-volatility anomaly)
    short = top decile (HIGH volatility)
    Same FF methodology as build_smb_series but with return-std signal.
    No look-ahead: signal uses returns up to formation close; holding starts next day.
    """
    series: dict[str, float] = {}
    for k, ri in enumerate(rebal_idx):
        if ri - VOL_DAYS + 1 < 0:
            continue

        # 20d return std (no look-ahead: uses ret up to formation day ri inclusive)
        vol_window = ret[:, ri - VOL_DAYS + 1 : ri + 1]  # [nc, 20]
        n_valid = np.sum(np.isfinite(vol_window), axis=1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            vol = np.full(close.shape[0], np.nan)
            mask_vol = n_valid >= VOL_DAYS // 2  # at least 10/20 valid
            vol[mask_vol] = np.nanstd(vol_window[mask_vol], axis=1, ddof=1)

        # liquidity filter (same as SMB): 20d mean amount >= floor + formation amount > 0
        amt_window = amount[:, ri - VOL_DAYS + 1 : ri + 1]
        finite_mask = np.isfinite(amt_window)
        finite_cnt = finite_mask.sum(axis=1)
        finite_sum = np.where(finite_mask, amt_window, 0.0).sum(axis=1)
        mean_amt = np.where(finite_cnt > 0, finite_sum / np.maximum(finite_cnt, 1), np.nan)
        form_amt = amount[:, ri]
        elig = np.isfinite(vol) & (vol > 0) & np.isfinite(mean_amt) & (mean_amt >= LIQ_AMT_FLOOR) & np.isfinite(form_amt) & (form_amt > 0)

        signal = np.full(close.shape[0], np.nan)
        signal[elig] = vol[elig]

        # long = bottom decile (LOW vol), short = top decile (HIGH vol)
        long_idx, short_idx = form_decile_legs(signal, long_is_top=False)
        if long_idx.size == 0 or short_idx.size == 0:
            continue

        # holding period (ri, next_rebal]
        end = rebal_idx[k + 1] if k + 1 < len(rebal_idx) else len(calendar) - 1
        for d in range(ri + 1, end + 1):
            lr = ret[long_idx, d]
            sr = ret[short_idx, d]
            lr = lr[np.isfinite(lr)]
            sr = sr[np.isfinite(sr)]
            if lr.size < MIN_DECILE_STOCKS or sr.size < MIN_DECILE_STOCKS:
                continue
            series[calendar[d]] = float(lr.mean() - sr.mean())
    return series


# ---------- OLS with NW-HAC SE ----------


def ols_hac(y: np.ndarray, X: np.ndarray, maxlags: int | None = None):
    """OLS with Newey-West HAC SE (Bartlett kernel).

    y: (n,) strategy returns (decimal)
    X: (n, k) factor returns (decimal), NO constant
    Returns statsmodels RegressionResults.
    """
    n = len(y)
    if maxlags is None:
        maxlags = max(1, int(np.floor(4 * (n / 100) ** (2 / 9))))
    X_const = sm.add_constant(X, has_constant="add")
    model = sm.OLS(y, X_const)
    return model.fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})


def regression_report(y: np.ndarray, factors: np.ndarray, factor_names: list[str], label: str = "") -> dict:
    """Run OLS regression and report alpha + factor loadings."""
    # drop nan rows
    mask = np.isfinite(y) & np.all(np.isfinite(factors), axis=1)
    y_c = y[mask]
    X_c = factors[mask]
    n = len(y_c)
    if n < 20:
        print(f"  [{label}] n={n} < 20, underpowered")
        return {
            "label": label,
            "n": n,
            "alpha_pct": 0.0,
            "alpha_t": 0.0,
            "alpha_p_one_sided": 1.0,
            "verdict": "underpowered",
        }

    r = ols_hac(y_c, X_c)
    alpha = float(r.params[0])
    alpha_se = float(r.bse[0])
    alpha_t = float(r.tvalues[0])
    alpha_p_two = float(r.pvalues[0])
    p_one = norm_sf_positive(alpha_t)

    print(f"\n  [{label}] n={n}")
    print(f"    alpha = {alpha * 100:.4f}%/period  (SE {alpha_se * 100:.4f}%, NW t = {alpha_t:.3f})")
    print(f"    p_one_sided = {p_one:.6f}  p_two_sided = {alpha_p_two:.6f}")

    betas: dict[str, dict] = {}
    for i, name in enumerate(factor_names):
        b = float(r.params[i + 1])
        b_t = float(r.tvalues[i + 1])
        b_p = float(r.pvalues[i + 1])
        betas[name] = {"beta": round(b, 4), "t": round(b_t, 3), "p": round(b_p, 6)}
        print(f"    beta_{name} = {b:.4f}  (t = {b_t:.3f}, p = {b_p:.6f})")

    print(f"    R² = {r.rsquared:.4f}")

    return {
        "label": label,
        "n": n,
        "alpha_pct": round(alpha * 100, 4),
        "alpha_se_pct": round(alpha_se * 100, 4),
        "alpha_t": round(alpha_t, 3),
        "alpha_p_one_sided": round(p_one, 6),
        "alpha_p_two_sided": round(alpha_p_two, 6),
        "betas": betas,
        "r_squared": round(float(r.rsquared), 4),
    }


# ---------- rolling 60-day alpha stability ----------


def rolling_alpha(y: np.ndarray, mkt: np.ndarray, dates: list[str], window: int = ROLLING_WINDOW) -> dict:
    """60-day rolling alpha from mkt-only OLS (simple OLS for speed, no HAC per window)."""
    alphas: list[float] = []
    alpha_ts: list[float] = []
    roll_dates: list[str] = []
    n = len(y)
    for i in range(window, n + 1):
        y_w = y[i - window : i]
        m_w = mkt[i - window : i]
        # simple OLS: y = a + b*m + e
        X = np.column_stack([np.ones(window), m_w])
        try:
            beta = np.linalg.lstsq(X, y_w, rcond=None)[0]
            resid = y_w - X @ beta
            df = window - 2
            if df <= 0:
                continue
            sigma2 = float(np.sum(resid**2) / df)
            XtX_inv = np.linalg.inv(X.T @ X)
            se_a = float(np.sqrt(sigma2 * XtX_inv[0, 0]))
            a = float(beta[0])
            t_a = a / se_a if se_a > 0 else 0.0
            alphas.append(a)
            alpha_ts.append(t_a)
            roll_dates.append(dates[i - 1])
        except Exception:
            continue

    if not alphas:
        return {"n_windows": 0}

    arr = np.array(alphas)
    ts = np.array(alpha_ts)
    pct_pos = float((arr > 0).mean() * 100)
    pct_sig = float((ts > 2).mean() * 100)

    print(f"\n  rolling {window}d alpha stability:")
    print(f"    n_windows = {len(arr)}")
    print(f"    mean alpha = {arr.mean() * 100:.4f}%  std = {arr.std() * 100:.4f}%")
    print(f"    % positive = {pct_pos:.1f}%  % significant(t>2) = {pct_sig:.1f}%")
    print(f"    range: [{arr.min() * 100:.4f}%, {arr.max() * 100:.4f}%]")

    return {
        "n_windows": len(arr),
        "mean_alpha_pct": round(float(arr.mean()) * 100, 4),
        "std_alpha_pct": round(float(arr.std()) * 100, 4),
        "pct_positive": round(pct_pos, 1),
        "pct_significant": round(pct_sig, 1),
        "min_alpha_pct": round(float(arr.min()) * 100, 4),
        "max_alpha_pct": round(float(arr.max()) * 100, 4),
    }


# ---------- regime breakdown ----------


def classify_regimes(mkt_returns: np.ndarray, dates: list[str], window: int = ROLLING_WINDOW) -> dict[str, str]:
    """Classify each date as bull/bear/range based on 60d cumulative market return."""
    n = len(mkt_returns)
    regimes: dict[str, str] = {}
    for i in range(n):
        start = max(0, i - window + 1)
        chunk = mkt_returns[start : i + 1]
        chunk = chunk[np.isfinite(chunk)]
        cum = float(np.prod(1.0 + chunk) - 1.0) if len(chunk) > 0 else 0.0
        if cum > REGIME_BULL:
            regimes[dates[i]] = "bull"
        elif cum < REGIME_BEAR:
            regimes[dates[i]] = "bear"
        else:
            regimes[dates[i]] = "range"
    return regimes


def regime_breakdown_analysis(y: np.ndarray, mkt: np.ndarray, dates: list[str], regimes: dict[str, str]) -> dict:
    """Run mkt-only regression within each regime."""
    results: dict[str, dict] = {}
    for regime in ["bull", "bear", "range"]:
        mask = np.array([regimes.get(d) == regime for d in dates])
        n_r = int(mask.sum())
        if n_r < 20:
            print(f"\n  [{regime}] n={n_r} < 20, underpowered")
            results[regime] = {"n": n_r, "verdict": "underpowered"}
            continue
        y_r = y[mask]
        m_r = mkt[mask]
        r = ols_hac(y_r, m_r.reshape(-1, 1))
        a = float(r.params[0])
        a_t = float(r.tvalues[0])
        p_one = norm_sf_positive(a_t)
        print(f"\n  [{regime}] n={n_r}")
        print(f"    alpha = {a * 100:.4f}%  (NW t = {a_t:.3f}, p_one = {p_one:.6f})")
        print(f"    beta_mkt = {float(r.params[1]):.4f}")
        results[regime] = {
            "n": n_r,
            "alpha_pct": round(a * 100, 4),
            "alpha_t": round(a_t, 3),
            "alpha_p_one": round(p_one, 6),
            "beta_mkt": round(float(r.params[1]), 4),
        }
    return results


# ---------- BH FDR ----------


def bh_fdr_adjust(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR adjusted p-values."""
    n = len(pvals)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: pvals[i])
    adj = [0.0] * n
    running_min = 1.0
    for rank in range(n - 1, -1, -1):
        idx = order[rank]
        adj[idx] = min(running_min, pvals[idx] * n / (rank + 1))
        running_min = adj[idx]
    return [min(a, 1.0) for a in adj]


# ---------- main ----------


def main() -> int:
    # 1. Load factor baselines
    print("==> loading factor_baselines.json ...", flush=True)
    baselines = load_baselines()
    mkt_s = baselines["mkt"]
    smb_s = baselines["smb"]
    umd_s = baselines["umd"]
    print(f"    mkt: {len(mkt_s)}d, SMB: {len(smb_s)}d, UMD: {len(umd_s)}d", flush=True)

    # 2. Load kline panels + build low-vol daily series
    print("==> loading kline panels (close + amount) ...", flush=True)
    kline_dates = scan_kline_dates()
    calendar, _ = load_calendar_and_index(kline_dates)
    close, amount, codes = load_panels(calendar)
    ret = daily_returns(close)
    rebal_idx = month_end_dates(calendar)
    print(f"    codes={len(codes)} shape={close.shape} rebal={len(rebal_idx)}", flush=True)

    print("==> building low-vol daily series ...", flush=True)
    lowvol_s = build_lowvol_series(close, amount, ret, calendar, rebal_idx)
    print(f"    lowvol: {len(lowvol_s)}d  range {min(lowvol_s)}~{max(lowvol_s)}", flush=True)

    # 3. Align all series on common dates
    common = sorted(set(mkt_s) & set(smb_s) & set(umd_s) & set(lowvol_s))
    print(f"\n==> aligned (mkt ∩ SMB ∩ UMD ∩ lowvol): {len(common)}d  {common[0]}~{common[-1]}")

    mkt = np.array([mkt_s[d] for d in common])
    smb = np.array([smb_s[d] for d in common])
    umd = np.array([umd_s[d] for d in common])
    lowvol = np.array([lowvol_s[d] for d in common])

    # 4. Build combined portfolio: r_combo = 0.5*SMB + 0.5*lowvol
    r_combo = 0.5 * smb + 0.5 * lowvol
    n_days = len(common)

    mean_c = float(r_combo.mean())
    std_c = float(r_combo.std(ddof=1))
    sharpe_c = mean_c / std_c * (252**0.5) if std_c > 0 else 0.0
    wr_c = float((r_combo > 0).mean() * 100)
    corr_sl = float(np.corrcoef(smb, lowvol)[0, 1])

    print(f"\n{'=' * 72}")
    print(f"combined-microcap-portfolio = 0.5*SMB + 0.5*lowvol")
    print(f"{'=' * 72}")
    print(f"  n_days = {n_days}")
    print(f"  mean = {mean_c * 100:.4f}%/d  std = {std_c * 100:.4f}%/d  Sharpe = {sharpe_c:.4f}  WR = {wr_c:.1f}%")
    print(f"  SMB mean = {smb.mean() * 100:.4f}%/d  lowvol mean = {lowvol.mean() * 100:.4f}%/d")
    print(f"  corr(SMB, lowvol) = {corr_sl:.4f}")
    if abs(corr_sl) > 0.5:
        print(f"  [!] SMB 与 lowvol 强相关 (|r|>0.5) -> 非独立, 组合可能无增量 alpha")
    elif abs(corr_sl) > 0.3:
        print(f"  [!] SMB 与 lowvol 中等相关 (0.3<|r|<0.5) -> 部分非独立")
    else:
        print(f"  SMB 与 lowvol 弱相关 (|r|<0.3) -> 较独立, 组合可能有增量 alpha")

    # 5. Primary regression: r_combo ~ mkt (simplified, per task)
    print(f"\n{'=' * 72}")
    print(f"PRIMARY: r_combo = alpha + beta_mkt*r_mkt + residual")
    print(f"{'=' * 72}")
    primary = regression_report(r_combo, mkt.reshape(-1, 1), ["mkt"], "mkt-only")

    # 6. Multi-factor regression: r_combo ~ mkt + SMB + UMD
    print(f"\n{'=' * 72}")
    print(f"MULTI-FACTOR: r_combo = alpha + beta_mkt*mkt + beta_smb*SMB + beta_umd*UMD + residual")
    print(f"{'=' * 72}")
    X_multi = np.column_stack([mkt, smb, umd])
    multi = regression_report(r_combo, X_multi, ["mkt", "smb", "umd"], "3-factor")

    # 7. Alternate baseline sensitivity
    print(f"\n{'=' * 72}")
    print(f"ALTERNATE BASELINE SENSITIVITY")
    print(f"{'=' * 72}")
    sens_a = regression_report(r_combo, np.column_stack([mkt, smb]), ["mkt", "smb"], "mkt+SMB")
    sens_b = regression_report(r_combo, np.column_stack([mkt, umd]), ["mkt", "umd"], "mkt+UMD")

    sens_summary = {
        "mkt_only": {"alpha_pct": primary["alpha_pct"], "alpha_t": primary["alpha_t"]},
        "mkt_smb": {"alpha_pct": sens_a["alpha_pct"], "alpha_t": sens_a["alpha_t"]},
        "mkt_umd": {"alpha_pct": sens_b["alpha_pct"], "alpha_t": sens_b["alpha_t"]},
        "mkt_smb_umd": {"alpha_pct": multi["alpha_pct"], "alpha_t": multi["alpha_t"]},
    }

    # 8. Rolling 60-day alpha stability (mkt-only)
    print(f"\n{'=' * 72}")
    print(f"ROLLING {ROLLING_WINDOW}-DAY ALPHA STABILITY (mkt-only)")
    print(f"{'=' * 72}")
    rolling = rolling_alpha(r_combo, mkt, common, ROLLING_WINDOW)

    # 9. Regime breakdown
    print(f"\n{'=' * 72}")
    print(f"REGIME BREAKDOWN (60d cum mkt: bull>{REGIME_BULL * 100}%, bear<{REGIME_BEAR * 100}%)")
    print(f"{'=' * 72}")
    regimes = classify_regimes(mkt, common, ROLLING_WINDOW)
    rdist = {}
    for d in common:
        r = regimes.get(d, "range")
        rdist[r] = rdist.get(r, 0) + 1
    print(f"  distribution: {rdist}")
    regime_res = regime_breakdown_analysis(r_combo, mkt, common, regimes)

    # 10. Bonferroni + BH FDR
    print(f"\n{'=' * 72}")
    print(f"MULTIPLE TESTING CORRECTION")
    print(f"{'=' * 72}")
    p_raw = primary["alpha_p_one_sided"]
    p_bonf = bonferroni_p(p_raw, N_BONF)
    print(f"  primary (mkt-only) alpha: p_one = {p_raw:.6f}")
    print(f"  Bonferroni x{N_BONF} = {p_bonf:.6f}  ({'PASS' if p_bonf < ALPHA_LEVEL else 'FAIL'} at a={ALPHA_LEVEL})")

    p_list = [
        primary["alpha_p_one_sided"],
        sens_a["alpha_p_one_sided"],
        sens_b["alpha_p_one_sided"],
        multi["alpha_p_one_sided"],
    ]
    bh_adj = bh_fdr_adjust(p_list)
    bh_labels = ["mkt_only", "mkt_smb", "mkt_umd", "mkt_smb_umd"]
    print(f"  BH FDR sensitivity (across {len(p_list)} baseline combos):")
    for i, lab in enumerate(bh_labels):
        print(f"    {lab}: raw p = {p_list[i]:.6f} -> BH-adj = {bh_adj[i]:.6f} ({'PASS' if bh_adj[i] < ALPHA_LEVEL else 'FAIL'} FDR<0.05)")

    # 11. Verdict
    print(f"\n{'=' * 72}")
    print(f"HONEST VERDICT")
    print(f"{'=' * 72}")

    alpha_pct = primary["alpha_pct"]
    alpha_t = primary["alpha_t"]
    verdict = "exploratory"

    print(f"  primary alpha (mkt-only): {alpha_pct}%/period  t = {alpha_t}")
    print(f"  Bonferroni p (x{N_BONF}): {p_bonf}")

    if alpha_pct <= 0:
        print(f"  -> FALSIFIED: residual alpha <= 0 (no edge after controlling for market)")
        verdict = "edge-falsified"
    elif n_days < 60:
        print(f"  -> UNDERPOWERED: n_days = {n_days} < 60")
        verdict = "underpowered"
    elif p_bonf >= ALPHA_LEVEL:
        print(f"  -> FALSIFIED: Bonferroni p = {p_bonf} >= {ALPHA_LEVEL} (not significant)")
        verdict = "edge-falsified"
    elif rolling.get("pct_positive", 0) < 60:
        print(f"  -> EXPLORATORY: rolling alpha positive only {rolling.get('pct_positive', 0)}% of windows")
        verdict = "exploratory"
    else:
        regime_alphas = [v.get("alpha_pct", 0) for v in regime_res.values() if isinstance(v, dict) and "alpha_pct" in v]
        if len(regime_alphas) >= 2 and all(a > 0 for a in regime_alphas):
            print(f"  -> EDGE-CONFIRMED: alpha positive + significant + stable + regime-robust")
            verdict = "edge-confirmed"
        else:
            print(f"  -> EXPLORATORY: alpha not robust across all regimes")
            verdict = "exploratory"

    # 12. Honest caveats
    print(f"\n--- honest caveats (no extrapolation) ---")
    print("1. combined = 0.5*SMB + 0.5*lowvol (equal-weight blend of size + low-vol factor)")
    print("2. long-short requires shorting (A股散户融券受限); statistical alpha != tradeable")
    print("3. SMB proxy = log(20d mean amount) is liquidity/turnover proxy, NOT true market cap")
    print("4. HML omitted (3-factor baseline: mkt+SMB+UMD, not 4-factor Carhart)")
    print(f"5. SMB & UMD strongly negatively correlated (-0.71, VIF~2.0 multicollinearity)")
    print(f"6. corr(SMB, lowvol) = {corr_sl:.4f} -> {'non-independent' if abs(corr_sl) > 0.3 else 'relatively independent'}")
    print("7. combined alpha != size/low-vol each has edge != selection strategy has edge")
    print("8. close-to-close daily returns (not open_ev, no intraday leakage)")
    print("9. month-end close formation (standard FF convention, mildly unrealistic)")

    # 13. Dump machine-readable result
    out = {
        "strategy": "combined-microcap-portfolio",
        "description": "0.5*SMB + 0.5*lowvol (equal-weight blend of size + low-vol factor returns)",
        "n_days": n_days,
        "date_range": f"{common[0]}~{common[-1]}",
        "corr_smb_lowvol": round(corr_sl, 4),
        "combined_stats": {
            "mean_pct": round(mean_c * 100, 4),
            "std_pct": round(std_c * 100, 4),
            "sharpe": round(sharpe_c, 4),
            "wr_pct": round(wr_c, 1),
        },
        "primary_regression_mkt_only": primary,
        "multi_factor_regression": multi,
        "alternate_baseline_sensitivity": sens_summary,
        "rolling_alpha_stability": rolling,
        "regime_breakdown": regime_res,
        "bonferroni_p": round(p_bonf, 6),
        "bh_fdr": {bh_labels[i]: round(bh_adj[i], 6) for i in range(len(bh_labels))},
        "verdict": verdict,
        "caveats": [
            "long-short requires shorting (A股散户融券受限); statistical alpha != tradeable",
            "SMB proxy = log(20d mean amount) is liquidity/turnover proxy, NOT true market cap",
            "HML omitted (3-factor baseline: mkt+SMB+UMD, not 4-factor Carhart)",
            "SMB and UMD strongly negatively correlated (-0.71, VIF~2.0 multicollinearity)",
            f"corr(SMB, lowvol) = {corr_sl:.4f}",
            "combined alpha != size/low-vol each has edge != selection strategy has edge",
            "close-to-close daily returns (not open_ev, no intraday leakage)",
        ],
    }
    out_path = Path(__file__).parent / "_residual_combined-microcap-portfolio_result.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n==> written {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
