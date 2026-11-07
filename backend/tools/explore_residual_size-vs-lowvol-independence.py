# -*- coding: utf-8 -*-
"""size vs low-vol 独立性残差 alpha——多因子 OLS 互相控制归因（第 6 种方法学）.

核心问题（解非独立核心）: size 和 low-vol 是同一笔交易吗？还是互相控制后还有独立 alpha？

  回归 A: r_size   = alpha + beta_mkt*mkt + beta_lowvol*r_lowvol + residual
  回归 B: r_lowvol = alpha + beta_mkt*mkt + beta_size*r_size    + residual

  alpha (截距) = 控市场 + 另一因子后的残差 alpha (因子 spanning 检验).
    - alpha≈0 且被控因子大 beta 显著 → 同一交易 (collinear, 因子非独立)
    - alpha 显著 → 该因子有独立 alpha 超越另一因子 (独立)

为何新方法学: 因子动物园 (Hou-Xue-Zhang 等) 发现 size≈low-vol 非独立.
之前 CAPM 只控市场单因子, 本脚本互相控制 (size 控 low-vol, low-vol 控 size) 测
独立 alpha 是否存活——这是 residual-edge-analyzer 的因子正交化应用.

数据:
- mkt/smb(size)/umd 日频 (factor_baselines.json, 月末再平衡横截面 decile long-short,
  由 build_factor_baselines.py 产出)
- low-vol 日频 (本脚本自建, 同 Fama-French 方法: 月末再平衡, 20d 日收益 std signal,
  long=bottom decile 低波动 + short=top decile 高波动, 日持有收益, 等权腿内)
- 对齐窗口: mkt∩smb∩umd∩lowvol = 2019-02-01~2026-09-21 (1852 日)

诚实口径 (§44 v3 + residual-edge-analyzer):
- NW-HAC SE (Bartlett kernel, Newey-West optimal lag)
- Bonferroni ×4 (4 策略并行: etf-premium/composite-top5/size/low-vol) + BH FDR
- rolling 60 日窗口 alpha 稳定性
- alternate baseline (mkt / mkt+other / mkt+other+umd 组合)
- regime 分层 (sh.000001 60d SMA + 2% band)
- 禁外推: 仅测 size↔lowvol 互相控制, ≠ 全因子独立, ≠ 可交易 edge

诚实约束:
- SMB=size 代理 log(20d 均成交额) 是流动性/换手代理非真市值 (需流通股本).
  高成交额股 ≠ 大市值 (可能是高换手投机股). 本 SMB 实为 '低换手-高换手' 近似.
- low-vol=20d 日收益 std, 标准低波动率异常因子 (Baker-Haug-Wurgler/Frazzini-Pedersen).
- long-short 需做空 (A股散户融券受限), 统计 alpha ≠ 可交易 (仅机构/融券标的可用).
- survivorship: 早期 (2018-2020) 横截面 ~264-766 来自非随机 backfill 子集;
  小盘/低波动腿退市/ST 概率高 → unbalanced panel survivorship bias.
- size↔lowvol 独立性 ≠ size/lowvol 各自有 edge (各自 verdict 见
  _size_result.json / _low_volatility_result.json: 两者 standalone 均 'exploratory').
- HML 缺失 (无历史 PB), 3-factor Carhart-minus-HML baseline; UMD 与 SMB corr=-0.71
  ( multicollinearity, VIF~2.0), 对 size/lowvol 互相控制回归无影响 (那俩才是核心).

跑法: cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
      .venv/bin/python tools/explore_residual_size-vs-lowvol-independence.py
"""

from __future__ import annotations
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.linear_model import OLS
from scipy.stats import norm

# import shared helpers (DRY) + baseline builder helpers (exact methodological consistency)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import bonferroni_p, norm_sf_positive  # noqa: E402
import build_factor_baselines as bfb  # reuse panel loaders + decile helpers  # noqa: E402

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
FACTOR_JSON = DATA / "factor_baselines.json"
INDEX_CACHE = DATA / "index_ohlc_cache.json"

N_STRATEGIES_PARALLEL = 4  # Bonferroni ×4 (etf-premium/composite-top5/size/low-vol)
ALPHA = 0.05
ROLLING_WINDOW = 60  # 60 交易日滚动 alpha
LIQ_AMT_FLOOR = bfb.LIQ_AMT_FLOOR  # 5000 万元 — 与 baseline 一致 (同 cross-section)
MIN_DECILE_STOCKS = bfb.MIN_DECILE_STOCKS  # 5
MIN_CROSS_SECTION = bfb.MIN_CROSS_SECTION  # 20
VOL_DAYS = 20  # 20d 波动率 signal 回看窗 (20 日收益 → 21 closes)


# ---------- data loading ----------


def load_factors() -> tuple[dict[str, dict[str, float]], dict]:
    """Load mkt/smb/umd daily decimal returns + metadata from factor_baselines.json."""
    d = json.loads(FACTOR_JSON.read_text())
    fs = d["factor_series"]
    factors = {k: dict(v) for k, v in fs.items()}  # {name: {date: decimal}}
    return factors, d


def load_index_levels() -> dict[str, float]:
    """Load sh.000001 close levels keyed by date (for regime classification)."""
    idx = json.loads(INDEX_CACHE.read_text())["sh.000001"]
    return {r["date"]: float(r["close"]) for r in idx if r.get("date") and r.get("close")}


# ---------- low-vol daily factor series (self-built, mirrors SMB builder) ----------


def build_lowvol_series(close: np.ndarray, amount: np.ndarray, ret: np.ndarray, calendar: list[str], rebal_idx: list[int]) -> dict[str, float]:
    """Low-vol daily returns: month-end rebalance, 20d return-std signal.

    long = bottom decile (LOW volatility), short = top decile (HIGH volatility).
    Same Fama-French convention as build_factor_baselines.build_smb_series:
      - liquidity filter: 20d mean amount >= floor + formation amount>0
      - winsorize 1%/99% cross-section, decile = bottom/top 10%, equal-weight within leg
      - holding (ri, next_rebal], constituents fixed during holding
      - look-ahead guard: signal at formation close; returns start next day
    """
    series: dict[str, float] = {}
    nc, nd = close.shape
    for k, ri in enumerate(rebal_idx):
        if ri - VOL_DAYS < 0:  # need 21 closes for 20 returns (close[ri-20..ri])
            continue
        # 20d volatility = std of last 20 daily returns (ret[ri-19..ri])
        ret_window = ret[:, ri - VOL_DAYS + 1 : ri + 1]  # [nc, 20]
        # eligibility: all 20 returns finite (i.e. 21 closes present) + liquidity filter
        finite_ret = np.isfinite(ret_window).all(axis=1)
        amt_window = amount[:, ri - VOL_DAYS + 1 : ri + 1]
        famt = np.isfinite(amt_window)
        fcnt = famt.sum(axis=1)
        fsum = np.where(famt, amt_window, 0.0).sum(axis=1)
        mean_amt = np.where(fcnt > 0, fsum / np.maximum(fcnt, 1), np.nan)
        form_amt = amount[:, ri]
        elig = finite_ret & np.isfinite(mean_amt) & (mean_amt >= LIQ_AMT_FLOOR) & np.isfinite(form_amt) & (form_amt > 0)
        if not elig.any():
            continue
        # 20d vol signal (ddof=1 sample std)
        vol = np.full(nc, np.nan)
        rw = ret_window[elig]
        vol[elig] = np.std(rw, axis=1, ddof=1)
        long_idx, short_idx = bfb.form_decile_legs(vol, long_is_top=False)  # long=bottom (low vol)
        if long_idx.size == 0 or short_idx.size == 0:
            continue
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


# ---------- regime classification ----------


def classify_regimes(factor_dates: list[str], index_levels: dict[str, float]) -> pd.Series:
    """bull/bear/range via 60-day SMA + 2% band (same as etf-premium residual script)."""
    closes = np.array([index_levels.get(d, np.nan) for d in factor_dates])
    n = len(closes)
    regimes = ["range"] * n
    for i in range(n):
        lo = max(0, i - 59)
        window = closes[lo : i + 1]
        w = window[~np.isnan(window)]
        if len(w) < 30:
            regimes[i] = "range"
            continue
        sma = w.mean()
        c = closes[i]
        if np.isnan(c) or sma <= 0:
            regimes[i] = "range"
            continue
        ratio = c / sma
        if ratio > 1.02:
            regimes[i] = "bull"
        elif ratio < 0.98:
            regimes[i] = "bear"
        else:
            regimes[i] = "range"
    return pd.Series(regimes, index=factor_dates, name="regime")


# ---------- OLS + NW-HAC ----------


def nw_lag(n: int) -> int:
    """Newey-West optimal lag: floor(4 * (n/100)^(2/9))."""
    return max(1, int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0))))


def run_ols_hac(y: pd.Series, X: pd.DataFrame, label: str = "") -> dict:
    """OLS with Newey-West HAC SE. Returns alpha + factor loadings + t + p.

    y, X must be aligned (same index). X should NOT have a constant (added here).
    """
    Xc = sm.add_constant(X, has_constant="add")
    df = pd.concat([y, Xc], axis=1).dropna()
    if len(df) < Xc.shape[1] + 5:
        return {"label": label, "n": len(df), "status": "too_few_obs"}
    yv = df[y.name]
    Xv = df.drop(columns=[y.name])
    lag = nw_lag(len(df))
    model = OLS(yv, Xv).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    const = model.params["const"]
    se_const = model.bse["const"]
    t_const = model.tvalues["const"]
    p_two = 2 * (1 - norm.cdf(abs(t_const)))
    p_one = norm_sf_positive(t_const)
    loadings = {}
    for col in Xv.columns:
        loadings[col] = {
            "beta": float(model.params[col]),
            "t": float(model.tvalues[col]),
            "p_two": float(2 * (1 - norm.cdf(abs(model.tvalues[col])))),
        }
    return {
        "label": label,
        "n": int(len(df)),
        "nlag": lag,
        "alpha_decimal": float(const),
        "alpha_pct": float(const * 100),
        "alpha_se": float(se_const),
        "alpha_t": float(t_const),
        "alpha_p_two": float(p_two),
        "alpha_p_one": float(p_one),
        "r_squared": float(model.rsquared),
        "loadings": loadings,
        "resid_std_pct": float(np.std(model.resid) * 100),
    }


# ---------- rolling 60-day alpha ----------


def rolling_alpha(y: pd.Series, X: pd.DataFrame, window: int = ROLLING_WINDOW) -> dict:
    """Rolling-window OLS (60-day). Report alpha stability: %pos, mean, std, %sig."""
    Xc = sm.add_constant(X, has_constant="add")
    df = pd.concat([y, Xc], axis=1).dropna()
    yv = df[y.name]
    Xv = df.drop(columns=[y.name])
    n = len(df)
    alphas: list[float] = []
    sig_count = 0
    valid = 0
    for i in range(window, n + 1):
        yw = yv.iloc[i - window : i]
        Xw = Xv.iloc[i - window : i]
        if len(yw) < Xw.shape[1] + 2:
            continue
        try:
            m = OLS(yw, Xw).fit()
            a = m.params["const"]
            se = m.bse["const"]
            t = a / se if se > 0 else 0
            alphas.append(float(a))
            valid += 1
            if abs(t) > 1.96:
                sig_count += 1
        except Exception:
            continue
    if not alphas:
        return {"status": "no_windows", "valid": 0}
    arr = np.array(alphas)
    return {
        "status": "ok",
        "n_windows": valid,
        "mean_alpha_pct": float(arr.mean() * 100),
        "std_alpha_pct": float(arr.std() * 100),
        "min_pct": float(arr.min() * 100),
        "max_pct": float(arr.max() * 100),
        "pct_positive": float((arr > 0).mean() * 100),
        "pct_sig_t2": float(sig_count / max(1, valid) * 100),
    }


# ---------- regime breakdown ----------


def regime_breakdown(y: pd.Series, X: pd.DataFrame, regimes: pd.Series) -> dict:
    """Per-regime: mean factor return (descriptive) + OLS alpha (factor-controlled)."""
    out = {}
    for reg in ["bull", "bear", "range"]:
        mask = regimes == reg
        n_days = int(mask.sum())
        if n_days < 20:
            out[reg] = {"n_days": n_days, "status": "too_few"}
            continue
        y_r = y[mask]
        X_r = X[mask]
        day_mean = float(y_r.mean() * 100)
        day_std = float(y_r.std() * 100)
        t_mean = y_r.mean() / (y_r.std() / math.sqrt(n_days)) if n_days > 1 and y_r.std() > 0 else 0.0
        ols = run_ols_hac(y_r, X_r, label=f"{reg} (n={n_days})") if n_days >= 20 else {"status": "too_few"}
        out[reg] = {
            "n_days": n_days,
            "day_mean_pct": round(day_mean, 4),
            "day_std_pct": round(day_std, 4),
            "t_mean": round(float(t_mean), 2),
            "ols": ols,
        }
    return out


# ---------- BH FDR ----------


def bh_fdr(pvals: list[float], q: float = 0.05) -> dict:
    """Benjamini-Hochberg FDR (sensitivity to Bonferroni)."""
    n = len(pvals)
    if n == 0:
        return {"n": 0}
    order = sorted(range(n), key=lambda i: pvals[i])
    crit = 0.0
    n_rej = 0
    for rank, i in enumerate(order, start=1):
        thresh = (rank / n) * q
        if pvals[i] <= thresh:
            crit = pvals[i]
            n_rej = rank
    return {"n": n, "q": q, "n_rejected": n_rej, "max_p_rejected": crit}


# ---------- VIF ----------


def vif(x1: np.ndarray, x2: np.ndarray, label: str) -> float:
    """Variance Inflation Factor for 2 regressors: VIF = 1/(1-R²), R² from x1~x2."""
    df = pd.DataFrame({"x1": x1, "x2": x2}).dropna()
    if len(df) < 5:
        return float("nan")
    Xc = sm.add_constant(df["x2"])
    try:
        m = OLS(df["x1"], Xc).fit()
        r2 = m.rsquared
        return float(1.0 / (1.0 - r2)) if r2 < 1.0 else float("inf")
    except Exception:
        return float("nan")


# ---------- main ----------


def main() -> int:
    print("=" * 76)
    print("size vs low-vol 独立性残差 alpha (第6种方法学: 互相控制 OLS)")
    print("回归A: r_size   = alpha + beta_mkt*mkt + beta_lowvol*r_lowvol + residual")
    print("回归B: r_lowvol = alpha + beta_mkt*mkt + beta_size*r_size    + residual")
    print("=" * 76)

    # ---- load factor baselines ----
    print("\n[1] 载入 factor_baselines.json (mkt/smb=size/umd) ...", flush=True)
    factors, fb_meta = load_factors()
    mkt = factors["mkt"]
    smb = factors["smb"]  # size (Small Minus Big, log 20d amount signal)
    umd = factors["umd"]
    print(f"  mkt: {len(mkt)} days | smb(size): {len(smb)} days | umd: {len(umd)} days", flush=True)
    print(f"  HML: BLOCKED (no historical PB) -> 3-factor Carhart-minus-HML baseline", flush=True)

    # ---- build low-vol daily series (self-built, same FF methodology) ----
    print("\n[2] 自建 low-vol 日频因子序列 (月末再平衡, 20d 波动率 decile) ...", flush=True)
    # calendar = mkt dates (sorted) — matches baseline builder's calendar (index ∩ kline)
    calendar = sorted(mkt.keys())
    print(f"  calendar: {calendar[0]}~{calendar[-1]} ({len(calendar)} dates)", flush=True)
    print("  loading kline panels (close+amount, ~5248 codes) ...", flush=True)
    close, amount, codes = bfb.load_panels(calendar)
    print(f"  panels: close{close.shape} finite_close={int(np.isfinite(close).sum())}", flush=True)
    ret = bfb.daily_returns(close)
    rebal_idx = bfb.month_end_dates(calendar)
    print(
        f"  month-end rebalance dates: {len(rebal_idx)} first={calendar[rebal_idx[0]]} last={calendar[rebal_idx[-1]]}",
        flush=True,
    )
    lowvol = build_lowvol_series(close, amount, ret, calendar, rebal_idx)
    print(
        f"  low-vol days built: {len(lowvol)} range {min(lowvol)}~{max(lowvol)}" if lowvol else "  low-vol empty",
        flush=True,
    )
    lowvol_stat = bfb.series_stats(lowvol, "lowvol")
    print(
        f"  low-vol stat: mean={lowvol_stat.get('mean_pct')}%/d "
        f"std={lowvol_stat.get('std_pct')}%/d ann_sharpe={lowvol_stat.get('annualized_sharpe')} "
        f"wr={lowvol_stat.get('wr_pct')}%",
        flush=True,
    )

    # ---- align all series on common dates (mkt ∩ smb ∩ umd ∩ lowvol) ----
    print("\n[3] 对齐 mkt/smb/lowvol/umd 到共同窗口 ...", flush=True)
    common = sorted(set(mkt) & set(smb) & set(lowvol) & set(umd))
    print(f"  aligned window: {common[0]}~{common[-1]} ({len(common)} dates)", flush=True)
    if len(common) < 100:
        print("  ERROR: aligned window too small (<100 days), cannot regress")
        return 1

    r_size = pd.Series([smb[d] for d in common], index=common, name="r_size")
    r_lowvol = pd.Series([lowvol[d] for d in common], index=common, name="r_lowvol")
    r_mkt = pd.Series([mkt[d] for d in common], index=common, name="mkt")
    r_umd = pd.Series([umd[d] for d in common], index=common, name="umd")

    # ---- descriptive: correlation + VIF (the "same trade?" diagnostic) ----
    print("\n[4] 描述性诊断: size↔lowvol 相关性 + VIF (同一笔交易?) ...", flush=True)
    corr_sz_lv = float(np.corrcoef(r_size.values, r_lowvol.values)[0, 1])
    corr_sz_mkt = float(np.corrcoef(r_size.values, r_mkt.values)[0, 1])
    corr_lv_mkt = float(np.corrcoef(r_lowvol.values, r_mkt.values)[0, 1])
    vif_sz_lv = vif(r_size.values, r_lowvol.values, "size~lowvol")
    # R² of size ~ lowvol (how much variance shared, ignoring mkt)
    df2 = pd.DataFrame({"y": r_size.values, "x": r_lowvol.values}).dropna()
    r2_sz_lv = float(OLS(df2["y"], sm.add_constant(df2["x"])).fit().rsquared)
    print(f"  corr(size, lowvol) = {corr_sz_lv:+.4f}  (|r|>0.5 = 高共线; >0.7 = 同一交易迹象)")
    print(f"  corr(size, mkt)    = {corr_sz_mkt:+.4f}")
    print(f"  corr(lowvol, mkt)  = {corr_lv_mkt:+.4f}")
    print(f"  VIF(size, lowvol)  = {vif_sz_lv:.3f}  (>5 = 多重共线严重; >10 = 系数不可信)")
    print(f"  R²(size ~ lowvol)  = {r2_sz_lv:.4f}  (低波动率解释规模因子收益的比例)")
    print(f"  -> {'高共线/同一笔交易迹象' if abs(corr_sz_lv) > 0.5 else '低共线, 可能独立'} (corr={corr_sz_lv:+.4f}, R²={r2_sz_lv:.3f})")

    # ---- regime classification ----
    print("\n[5] Regime 分类 (sh.000001 60d SMA + 2% band) ...", flush=True)
    idx_levels = load_index_levels()
    regimes = classify_regimes(common, idx_levels)
    for r in ["bull", "bear", "range"]:
        n = int((regimes == r).sum())
        print(f"  {r}: {n} days ({n / len(regimes) * 100:.1f}%)")

    # ============ PRIMARY REGRESSION A: r_size ~ mkt + r_lowvol ============
    print(f"\n{'=' * 76}")
    print("回归A: r_size = alpha + beta_mkt*mkt + beta_lowvol*r_lowvol + residual")
    print(f"  (size 控 low-vol 后残差 alpha 还显著吗? size 是否被 low-vol span?)")
    print(f"{'=' * 76}")
    X_A = pd.DataFrame({"mkt": r_mkt.values, "r_lowvol": r_lowvol.values}, index=common)
    res_A = run_ols_hac(r_size, X_A, label="size ~ mkt + lowvol")
    print(f"  n={res_A['n']}, NW lag={res_A['nlag']}")
    print(f"  alpha (size | mkt+lowvol) = {res_A['alpha_pct']:.5f}%/day (annualized {res_A['alpha_pct'] * 252:.3f}%/yr)")
    print(f"  t (NW-HAC) = {res_A['alpha_t']:.3f}  p_two={res_A['alpha_p_two']:.4f}  p_one={res_A['alpha_p_one']:.4f}")
    print(f"  R² = {res_A['r_squared']:.4f}  resid_std = {res_A['resid_std_pct']:.4f}%/day")
    for k, v in res_A["loadings"].items():
        print(f"    beta_{k} = {v['beta']:.4f}  (t={v['t']:.3f}, p={v['p_two']:.4f})")
    beta_lv_on_size = res_A["loadings"].get("r_lowvol", {}).get("beta", 0)
    t_lv_on_size = res_A["loadings"].get("r_lowvol", {}).get("t", 0)
    print(
        f"  解读: beta_lowvol={beta_lv_on_size:.3f} (t={t_lv_on_size:.2f}) "
        f"{'-> low-vol 显著解释 size (spanning)' if abs(t_lv_on_size) > 1.96 else '-> low-vol 不显著解释 size'}"
    )

    # ============ PRIMARY REGRESSION B: r_lowvol ~ mkt + r_size ============
    print(f"\n{'=' * 76}")
    print("回归B: r_lowvol = alpha + beta_mkt*mkt + beta_size*r_size + residual")
    print(f"  (low-vol 控 size 后残差 alpha 还显著吗? low-vol 是否被 size span?)")
    print(f"{'=' * 76}")
    X_B = pd.DataFrame({"mkt": r_mkt.values, "r_size": r_size.values}, index=common)
    res_B = run_ols_hac(r_lowvol, X_B, label="lowvol ~ mkt + size")
    print(f"  n={res_B['n']}, NW lag={res_B['nlag']}")
    print(f"  alpha (lowvol | mkt+size) = {res_B['alpha_pct']:.5f}%/day (annualized {res_B['alpha_pct'] * 252:.3f}%/yr)")
    print(f"  t (NW-HAC) = {res_B['alpha_t']:.3f}  p_two={res_B['alpha_p_two']:.4f}  p_one={res_B['alpha_p_one']:.4f}")
    print(f"  R² = {res_B['r_squared']:.4f}  resid_std = {res_B['resid_std_pct']:.4f}%/day")
    for k, v in res_B["loadings"].items():
        print(f"    beta_{k} = {v['beta']:.4f}  (t={v['t']:.3f}, p={v['p_two']:.4f})")
    beta_sz_on_lv = res_B["loadings"].get("r_size", {}).get("beta", 0)
    t_sz_on_lv = res_B["loadings"].get("r_size", {}).get("t", 0)
    print(
        f"  解读: beta_size={beta_sz_on_lv:.3f} (t={t_sz_on_lv:.2f}) "
        f"{'-> size 显著解释 low-vol (spanning)' if abs(t_sz_on_lv) > 1.96 else '-> size 不显著解释 low-vol'}"
    )

    # ---- Bonferroni ×4 + BH FDR (both directions) ----
    print(f"\n[6] 多重检验校正 (Bonferroni ×{N_STRATEGIES_PARALLEL} 策略并行 + BH FDR) ...")
    p_A_raw = res_A["alpha_p_one"]
    p_B_raw = res_B["alpha_p_one"]
    p_A_bonf = bonferroni_p(p_A_raw, N_STRATEGIES_PARALLEL)
    p_B_bonf = bonferroni_p(p_B_raw, N_STRATEGIES_PARALLEL)
    print(f"  回归A (size|lowvol): raw p_one={p_A_raw:.4f} -> Bonf×{N_STRATEGIES_PARALLEL}={p_A_bonf:.4f} ({'PASS' if p_A_bonf < ALPHA else 'FAIL'} @ {ALPHA})")
    print(f"  回归B (lowvol|size): raw p_one={p_B_raw:.4f} -> Bonf×{N_STRATEGIES_PARALLEL}={p_B_bonf:.4f} ({'PASS' if p_B_bonf < ALPHA else 'FAIL'} @ {ALPHA})")
    # within-script ×2 sensitivity (2 directions tested)
    p_A_bonf8 = bonferroni_p(p_A_raw, N_STRATEGIES_PARALLEL * 2)
    p_B_bonf8 = bonferroni_p(p_B_raw, N_STRATEGIES_PARALLEL * 2)
    print(f"  within-script ×2 sensitivity (×{N_STRATEGIES_PARALLEL * 2}): A={p_A_bonf8:.4f} B={p_B_bonf8:.4f}")
    # BH FDR across the 2 directions (conservative: other 2 strategies unknown=0.5)
    bh_A = bh_fdr([p_A_raw, 0.5, 0.5, 0.5], q=0.05)
    bh_B = bh_fdr([p_B_raw, 0.5, 0.5, 0.5], q=0.05)
    print(f"  BH FDR (q=0.05, conservative others=0.5): A n_rej={bh_A['n_rejected']} B n_rej={bh_B['n_rejected']}")

    # ---- alternate baseline sensitivity (both directions) ----
    print(f"\n[7] Alternate baseline sensitivity (alpha 稳健性, 换 baseline 组合) ...")
    fact_map = {"mkt": r_mkt, "r_lowvol": r_lowvol, "r_size": r_size, "umd": r_umd}
    # Direction A: size controlled by various baselines
    combos_A = [
        ("mkt only (CAPM)", ["mkt"]),
        ("mkt + lowvol (primary)", ["mkt", "r_lowvol"]),
        ("mkt + lowvol + umd", ["mkt", "r_lowvol", "umd"]),
    ]
    alt_A: dict = {}
    for name, cols in combos_A:
        Xc = pd.DataFrame({c: fact_map[c].values for c in cols}, index=common)
        r = run_ols_hac(r_size, Xc, label=name)
        alt_A[name] = r
        if r.get("status") == "too_few_obs":
            print(f"  A | {name}: too few obs")
            continue
        print(f"  A | {name}: alpha={r['alpha_pct']:.5f}%/d (t={r['alpha_t']:.3f}, p_one={r['alpha_p_one']:.4f}, R²={r['r_squared']:.4f})")
    # Direction B: lowvol controlled by various baselines
    combos_B = [
        ("mkt only (CAPM)", ["mkt"]),
        ("mkt + size (primary)", ["mkt", "r_size"]),
        ("mkt + size + umd", ["mkt", "r_size", "umd"]),
    ]
    alt_B: dict = {}
    for name, cols in combos_B:
        Xc = pd.DataFrame({c: fact_map[c].values for c in cols}, index=common)
        r = run_ols_hac(r_lowvol, Xc, label=name)
        alt_B[name] = r
        if r.get("status") == "too_few_obs":
            print(f"  B | {name}: too few obs")
            continue
        print(f"  B | {name}: alpha={r['alpha_pct']:.5f}%/d (t={r['alpha_t']:.3f}, p_one={r['alpha_p_one']:.4f}, R²={r['r_squared']:.4f})")
    sig_A = sum(1 for v in alt_A.values() if v.get("alpha_p_one", 1) < ALPHA)
    sig_B = sum(1 for v in alt_B.values() if v.get("alpha_p_one", 1) < ALPHA)
    print(f"  -> A: {sig_A}/{len(combos_A)} baselines significant | B: {sig_B}/{len(combos_B)} baselines significant")

    # ---- rolling 60-day alpha stability (both directions) ----
    print(f"\n[8] Rolling {ROLLING_WINDOW}-day alpha 稳定性 (两个方向) ...")
    roll_A = rolling_alpha(r_size, X_A, window=ROLLING_WINDOW)
    roll_B = rolling_alpha(r_lowvol, X_B, window=ROLLING_WINDOW)
    for label, roll in [("A (size|mkt+lowvol)", roll_A), ("B (lowvol|mkt+size)", roll_B)]:
        if roll["status"] == "ok":
            print(
                f"  {label}: n_win={roll['n_windows']} mean={roll['mean_alpha_pct']:.5f}%/d "
                f"std={roll['std_alpha_pct']:.5f} %pos={roll['pct_positive']:.1f}% "
                f"%sig|t|>1.96={roll['pct_sig_t2']:.1f}%"
            )
        else:
            print(f"  {label}: {roll['status']}")

    # ---- regime breakdown (both directions) ----
    print(f"\n[9] Regime breakdown (bull/bear/range 分层, 两个方向) ...")
    rb_A = regime_breakdown(r_size, X_A, regimes)
    rb_B = regime_breakdown(r_lowvol, X_B, regimes)
    for label, rb in [("A (size|mkt+lowvol)", rb_A), ("B (lowvol|mkt+size)", rb_B)]:
        print(f"  {label}:")
        for reg in ["bull", "bear", "range"]:
            r = rb[reg]
            if r.get("status") == "too_few":
                print(f"    {reg}: n={r['n_days']} too_few")
                continue
            ols = r.get("ols", {})
            ap = ols.get("alpha_pct", "n/a")
            at = ols.get("alpha_t", "n/a")
            print(f"    {reg}: n={r['n_days']} day_mean={r['day_mean_pct']}% (t={r['t_mean']}) | OLS alpha={ap}% (t={at})")

    # ============ HONEST VERDICT ============
    print(f"\n{'=' * 76}")
    print("诚实判定: size/lowvol 互相控制后还有独立 alpha 吗? (因子独立性)")
    print(f"{'=' * 76}")
    # significance check: Bonf PASS + alt-baseline robust + rolling stable
    a_sig = p_A_bonf < ALPHA and res_A["alpha_t"] > 1.96
    b_sig = p_B_bonf < ALPHA and res_B["alpha_t"] > 1.96
    a_robust = sig_A >= 2 and roll_A.get("pct_positive", 0) >= 50
    b_robust = sig_B >= 2 and roll_B.get("pct_positive", 0) >= 50

    print(
        f"  回归A (size|lowvol): alpha={res_A['alpha_pct']:.5f}%/d t={res_A['alpha_t']:.3f} "
        f"Bonf={p_A_bonf:.4f} {'PASS' if a_sig else 'FAIL'} | "
        f"alt-robust={'Y' if a_robust else 'N'} (%pos={roll_A.get('pct_positive', 0):.0f}%)"
    )
    print(
        f"  回归B (lowvol|size): alpha={res_B['alpha_pct']:.5f}%/d t={res_B['alpha_t']:.3f} "
        f"Bonf={p_B_bonf:.4f} {'PASS' if b_sig else 'FAIL'} | "
        f"alt-robust={'Y' if b_robust else 'N'} (%pos={roll_B.get('pct_positive', 0):.0f}%)"
    )
    print(f"  corr(size,lowvol)={corr_sz_lv:+.4f} R²(size~lowvol)={r2_sz_lv:.4f} VIF={vif_sz_lv:.2f}")

    print(f"\n  判定级联 (独立性 verdict):")
    if len(common) < 60:
        verdict = "underpowered"
        print(f"    [1] aligned n={len(common)} < 60 -> underpowered")
    elif a_sig and b_sig and a_robust and b_robust:
        verdict = "edge-confirmed"
        print(f"    [both] 两方向残差 alpha 均 Bonf-PASS + alt-robust + rolling %pos>=50%")
        print(f"           -> size 与 low-vol 互相独立 (各自有超越对方的独立 alpha)")
    elif (a_sig and a_robust) or (b_sig and b_robust):
        verdict = "exploratory"
        side = "size 独立于 lowvol" if (a_sig and a_robust) else "lowvol 独立于 size"
        print(f"    [partial] 仅一侧残差 alpha robust ({side}); 另一侧被 span")
        print(f"              -> 部分独立 (一因子吸收另一因子), 非对称 spanning")
    elif a_sig or b_sig:
        verdict = "exploratory"
        print(f"    [fragile] 残差 alpha 显著但非 robust (alt-baseline 脆弱/rolling 不稳)")
        print(f"              -> 探索性 (独立 alpha 迹象但不稳健)")
    else:
        verdict = "edge-falsified"
        print(f"    [none] 两方向残差 alpha 均 Bonf-FAIL (t={res_A['alpha_t']:.2f}/{res_B['alpha_t']:.2f})")
        if abs(corr_sz_lv) > 0.5:
            print(f"           + corr={corr_sz_lv:+.4f} 高共线 -> size≈lowvol 同一交易 (因子非独立)")
        else:
            print(f"           + corr={corr_sz_lv:+.4f} 低共线 -> 两因子 alpha 均不显著 (各自无 edge)")

    print(f"\n  -> verdict: {verdict}")

    # honest caveats (do NOT downgrade verdict, but must be reported)
    print(f"\n  诚实 caveat (不降级 verdict, 但必须标注):")
    print(f"    - SMB=size=log(20d 均成交额) 是流动性/换手代理非真市值; low-vol=20d 收益 std. 'size≈lowvol' 非独立结论受 size 代理选择影响")
    print(f"    - standalone size/lowvol 各自 verdict='exploratory' (非 edge-confirmed); 互相控制后残差 alpha 通常更弱 (因子衰减+共享方差)")
    print(f"    - long-short 需做空 (A股散户融券受限), 统计 alpha ≠ 可交易")
    print(f"    - HML 缺失 (无历史 PB), 3-factor baseline; UMD 与 SMB corr=-0.71 (VIF~2.0)")
    print(f"    - survivorship: 早期 (2018-2020) 横截面 ~264-766 来自非随机 backfill")
    print(f"    - rolling %sig|t|>1.96 低可能是 60d 窗口对 ~0.05%/d alpha 的 power 不足, %pos 才是真稳定性指标")

    print(f"\n禁外推声明:")
    print(f"  - 仅测 size↔lowvol 互相控制, 在对齐窗口 ({common[0]}~{common[-1]}, {len(common)} 日)")
    print(f"  - ≠ 全因子独立 ≠ size/lowvol 可交易 edge ≠ 选股战法有/无 edge")
    print(f"  - '因子非独立' (alpha≈0) 是因子动物园 (factor zoo) 的预期结果, 非 bug")
    print(f"  - '独立 alpha' (alpha 显著) 不等于该因子 standalone 有 edge")

    # ---- dump JSON ----
    out = {
        "strategy": "size-vs-lowvol-independence",
        "methodology": "residual alpha multi-factor OLS + NW-HAC (mutual orthogonalization)",
        "formula_A": "r_size = alpha + beta_mkt*mkt + beta_lowvol*r_lowvol + residual",
        "formula_B": "r_lowvol = alpha + beta_mkt*mkt + beta_size*r_size + residual",
        "strategy_return_series": "r_size (SMB from factor_baselines.json) + r_lowvol (self-built)",
        "lowvol_series_meta": lowvol_stat,
        "factor_window": {"start": common[0], "end": common[-1], "n_dates": len(common)},
        "descriptive": {
            "corr_size_lowvol": round(corr_sz_lv, 4),
            "corr_size_mkt": round(corr_sz_mkt, 4),
            "corr_lowvol_mkt": round(corr_lv_mkt, 4),
            "vif_size_lowvol": round(vif_sz_lv, 3) if not math.isnan(vif_sz_lv) and not math.isinf(vif_sz_lv) else None,
            "r2_size_on_lowvol": round(r2_sz_lv, 4),
        },
        "regression_A_size_on_mkt_lowvol": res_A,
        "regression_B_lowvol_on_mkt_size": res_B,
        "bonferroni": {
            "n_strategies_parallel": N_STRATEGIES_PARALLEL,
            "A_p_one_raw": p_A_raw,
            "A_p_bonf": p_A_bonf,
            "B_p_one_raw": p_B_raw,
            "B_p_bonf": p_B_bonf,
            "within_script_x2_A": p_A_bonf8,
            "within_script_x2_B": p_B_bonf8,
        },
        "bh_fdr_conservative": {"A": bh_A, "B": bh_B},
        "alternate_baseline_sensitivity": {"A_size": alt_A, "B_lowvol": alt_B},
        "rolling_alpha_stability": {"A_size": roll_A, "B_lowvol": roll_B},
        "regime_breakdown": {"A_size": rb_A, "B_lowvol": rb_B},
        "hml_blocker": fb_meta.get("hml_blocker", "")[:120],
        "verdict": verdict,
    }
    out_path = Path(__file__).parent / "_residual_size-vs-lowvol_result.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(f"\n[JSON] -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
