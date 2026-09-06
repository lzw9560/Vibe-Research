#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-factor combination validation (§44 v2 strict).

Question: can multi-factor combinations (non-linear/interaction/tree/rule)
find selection power that single factors can't?

Target:
  PRIMARY  = premium (gap%, D收→D+1开)
  SECONDARY = continuation (simulate_holding D+1开→D+4 path return)

Factors (16 total, all no-look-ahead at D close):
  Original (8): gene_score, vol_surge, volatility, momentum, breakout,
                ma_align, boards(连板), PE
  New (8):    benefitPart(CYQ获利盘), chip_concentration(CYQ集中度),
              turnover_t1, log_amount_t1, pctChg_t1, amplitude_t1,
              vol_ratio_5_20, zt_count(market)

Methodology (§44 v2):
  - Walk-forward CV: leave-one-day-out (14 folds)
  - OOS R² + OOS IC (Spearman rank corr, per-fold averaged)
  - Bonferroni correction for M model comparisons
  - Anti feature-selection bias: all features in all folds, no full-sample selection
  - No p-hacking
  - Honest: R²≈0/IC≈0 → "no combo edge"

Usage:
  cd backend && .venv/bin/python tools/multifactor_combo_validation.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import warnings
from pathlib import Path
from collections import defaultdict

import numpy as np
from scipy.stats import spearmanr

warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tools.kline_ta_validation import _compute_ta  # noqa: E402
from strategies.kline_returns import simulate_holding, _is_unbuyable_next_bar  # noqa: E402

VR = ROOT / ".vibe-research"
BASELINE = VR / "first_board_premium_baseline.json"
KLINE = VR / "baostock_kline_cache.json"
GENE_DB = VR / "gene_scores.db"
THS_LB = VR / "ths_lb_cache.json"
PROFIT = VR / "profit_data_cache.json"

# --- Bonferroni ---
ALPHA = 0.05
N_MODELS = 4  # Ridge, LightGBM, RF, GBM
BONF_ALPHA = ALPHA / N_MODELS


def _norm_date(d: str) -> str:
    """20260728 → 2026-07-28."""
    if len(d) == 8 and "-" not in d:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d


def _pe_for_date(profit: dict, code: str, target_date: str) -> float | None:
    """Most recent epsTTM published before target_date → PE = close/epsTTM."""
    if code not in profit:
        return None
    quarters = profit[code]
    best_eps = None
    for _q, info in quarters.items():
        pd_str = info.get("pubDate", "")
        if pd_str and pd_str[:10] <= target_date:
            eps = info.get("epsTTM")
            if eps is not None and eps != 0:
                best_eps = eps  # keep updating; sorted by insertion, last = most recent
    return best_eps


def _cyq_features(bars: list[dict], t1_idx: int, lookback: int = 30) -> dict | None:
    """Approximate CYQ chip distribution from daily bars.

    benefitPart = fraction of volume-weighted price distribution below T-1 close.
    concentration = 1 - (price_range_90pct / total_range); higher = more concentrated.
    """
    if t1_idx < lookback:
        lookback = t1_idx
    if lookback < 5:
        return None
    t1_close = bars[t1_idx]["close"]
    if not t1_close or t1_close <= 0:
        return None
    # Build volume-weighted price distribution
    prices = []
    volumes = []
    for j in range(lookback):
        b = bars[t1_idx - j]
        v = b.get("volume") or 0
        c = b.get("close") or 0
        if v > 0 and c > 0:
            prices.append(c)
            volumes.append(v)
    if not prices:
        return None
    total_vol = sum(volumes)
    # benefitPart: fraction of volume at prices below t1_close
    below = sum(v for p, v in zip(prices, volumes) if p <= t1_close)
    benefit_part = below / total_vol if total_vol else 0.5
    # concentration: fraction of volume in central 50% price band
    sorted_pairs = sorted(zip(prices, volumes), key=lambda x: x[0])
    cum = 0
    p5_idx = p95_idx = 0
    for i, (_, v) in enumerate(sorted_pairs):
        cum += v
        if cum <= total_vol * 0.05:
            p5_idx = i
        if cum <= total_vol * 0.95:
            p95_idx = i
    price_range_90 = sorted_pairs[p95_idx][0] - sorted_pairs[p5_idx][0] if p95_idx > p5_idx else 0
    total_range = sorted_pairs[-1][0] - sorted_pairs[0][0] if len(sorted_pairs) > 1 else 1
    concentration = 1.0 - (price_range_90 / total_range) if total_range > 0 else 0.5
    return {"benefit_part": benefit_part, "chip_concentration": concentration}


def _extra_kline_features(bars: list[dict], t1_idx: int) -> dict | None:
    """Additional kline-derived features (turnover, amount, pctChg, amplitude, vol ratio)."""
    if t1_idx < 20:
        return None
    t1 = bars[t1_idx]
    close = t1.get("close") or 0
    if not close or close <= 0:
        return None
    turnover = t1.get("turn") or 0
    amount = t1.get("amount") or 0
    pctchg = t1.get("pctChg") or 0
    high = t1.get("high") or 0
    low = t1.get("low") or 0
    amplitude = (high - low) / close if close else 0
    # vol ratio 5d / 20d
    vol_5 = np.mean([bars[t1_idx - j].get("volume") or 0 for j in range(5)])
    vol_20 = np.mean([bars[t1_idx - j].get("volume") or 0 for j in range(20)])
    vol_ratio = vol_5 / vol_20 if vol_20 else 1.0
    return {
        "turnover_t1": turnover,
        "log_amount_t1": np.log1p(amount),
        "pctchg_t1": pctchg,
        "amplitude_t1": amplitude,
        "vol_ratio_5_20": vol_ratio,
    }


def build_feature_matrix() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], list[str]]:
    """Build (X, y_premium, y_continuation, feature_names, dates).

    Returns X (n_samples x n_features), y_premium (gap%), y_cont (path return%),
    feature_names, sample_dates.
    """
    print("Loading data...")
    baseline = json.loads(BASELINE.read_bytes())
    samples = baseline["samples"]
    kline = json.loads(KLINE.read_bytes())
    lb = json.loads(THS_LB.read_text())
    profit = json.loads(PROFIT.read_text())
    conn = sqlite3.connect(str(GENE_DB), timeout=10)
    cur = conn.cursor()

    # Build ths_lb lookup: date(compact) → {code: boards}
    lb_lookup: dict[str, dict[str, int]] = {}
    for dt, items in lb.items():
        dt_norm = _norm_date(dt)
        lb_lookup[dt_norm] = {it["code"]: it.get("boards", 1) for it in items}

    feature_names = [
        "gene_score", "vol_surge", "volatility", "momentum", "breakout", "ma_align",
        "boards", "pe", "benefit_part", "chip_concentration",
        "turnover_t1", "log_amount_t1", "pctchg_t1", "amplitude_t1",
        "vol_ratio_5_20", "zt_count",
    ]

    X_rows = []
    y_premium = []
    y_cont = []
    dates = []
    n_skip = 0

    for s in samples:
        dt = s["date"]
        code = s["code"]
        t_close = s["t_close"]
        premium = s["premium"]
        zt_count = s.get("zt_count", 0)

        # --- gene_score ---
        r = cur.execute(
            "SELECT total_score FROM gene_scores WHERE date=? AND code=? AND data_source='eastmoney_live'",
            (dt, code),
        ).fetchone()
        gene_score = r[0] if r else 0.0

        # --- kline TA features ---
        bars = kline.get(code, [])
        ta = _compute_ta(bars, dt)
        if ta is None:
            n_skip += 1
            continue

        # Find t1_idx for extra features
        t1_idx = None
        for i, b in enumerate(bars):
            if b["date"] >= dt:
                break
            t1_idx = i
        if t1_idx is None or t1_idx < 20:
            n_skip += 1
            continue

        # --- CYQ features ---
        cyq = _cyq_features(bars, t1_idx)
        if cyq is None:
            cyq = {"benefit_part": 0.5, "chip_concentration": 0.5}

        # --- extra kline features ---
        extra = _extra_kline_features(bars, t1_idx)
        if extra is None:
            extra = {"turnover_t1": 0, "log_amount_t1": 0, "pctchg_t1": 0,
                     "amplitude_t1": 0, "vol_ratio_5_20": 1.0}

        # --- boards ---
        boards = lb_lookup.get(dt, {}).get(code, 1)

        # --- PE ---
        eps = _pe_for_date(profit, code, dt)
        pe = t_close / eps if eps and eps != 0 else np.nan

        # --- continuation target ---
        # simulate_holding: signal_date=dt, D+1 open → D+4 close
        cont = simulate_holding(bars, dt, stop_pct=-3.0, take_profit_pct=8.0, max_hold_days=3)
        if cont is not None:
            # Check unbuyable D+1
            idx = next((i for i, b in enumerate(bars) if b["date"] >= dt), None)
            if idx is not None and idx + 1 < len(bars):
                if _is_unbuyable_next_bar(bars[idx + 1]):
                    cont = None  # can't buy at D+1 open
        y_cont_val = cont["return_pct"] if cont else np.nan

        row = [
            gene_score, ta["vol_surge"], ta["volatility"], ta["momentum"],
            ta["breakout"], ta["ma_align"], boards, pe,
            cyq["benefit_part"], cyq["chip_concentration"],
            extra["turnover_t1"], extra["log_amount_t1"], extra["pctchg_t1"],
            extra["amplitude_t1"], extra["vol_ratio_5_20"], zt_count,
        ]
        X_rows.append(row)
        y_premium.append(premium)
        y_cont.append(y_cont_val)
        dates.append(dt)

    conn.close()

    X = np.array(X_rows, dtype=float)
    y_p = np.array(y_premium, dtype=float)
    y_c = np.array(y_cont, dtype=float)

    print(f"Built matrix: {X.shape[0]} samples x {X.shape[1]} features, skipped {n_skip}")
    print(f"Premium target: mean={y_p.mean():.3f}%, std={y_p.std():.3f}%, range=[{y_p.min():.1f}, {y_p.max():.1f}]")
    cont_valid = y_c[~np.isnan(y_c)]
    if len(cont_valid) > 0:
        print(f"Continuation target: n={len(cont_valid)}, mean={cont_valid.mean():.3f}%, std={cont_valid.std():.3f}%")
    print(f"Features: {feature_names}")
    return X, y_p, y_c, feature_names, dates


def _oos_r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return 1 - ss_res / ss_tot if ss_tot > 0 else 0.0


def _oos_ic(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 3 or np.std(y_true) == 0 or np.std(y_pred) == 0:
        return 0.0
    rho, _ = spearmanr(y_pred, y_true)
    return rho if not np.isnan(rho) else 0.0


def _oos_lift(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Top-quintile mean / bottom-quintile mean (lift)."""
    n = len(y_true)
    if n < 10:
        return 1.0
    q = max(1, n // 5)
    order = np.argsort(y_pred)
    bottom = y_true[order[:q]]
    top = y_true[order[-q:]]
    b_mean = np.mean(bottom)
    t_mean = np.mean(top)
    return t_mean / b_mean if abs(b_mean) > 1e-8 else 0.0


def walk_forward_cv(
    X: np.ndarray, y: np.ndarray, dates: list[str],
    feature_names: list[str], target_name: str,
) -> dict:
    """Leave-one-day-out walk-forward CV. Returns per-model OOS metrics."""
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
    import lightgbm as lgb
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer

    unique_dates = sorted(set(dates))
    n_folds = len(unique_dates)
    print(f"\n=== Walk-forward CV: {n_folds} folds (leave-one-day-out) ===")
    print(f"Target: {target_name}")
    print(f"Bonferroni alpha = {BONF_ALPHA:.4f} ({ALPHA}/{N_MODELS})")

    models = {
        "Ridge(Linear)": Ridge(alpha=1.0, random_state=42),
        "LightGBM": lgb.LGBMRegressor(
            n_estimators=100, max_depth=4, num_leaves=15,
            learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
            reg_alpha=0.1, reg_lambda=1.0, random_state=42, verbose=-1,
        ),
        "RandomForest": RandomForestRegressor(
            n_estimators=100, max_depth=5, min_samples_leaf=5,
            random_state=42, n_jobs=-1,
        ),
        "GradientBoosting": GradientBoostingRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.05,
            subsample=0.8, random_state=42,
        ),
    }

    # Per-fold results
    fold_r2 = {m: [] for m in models}
    fold_ic = {m: [] for m in models}
    fold_lift = {m: [] for m in models}
    # Aggregate OOS predictions
    oos_preds = {m: np.full(len(y), np.nan) for m in models}

    for fold_idx, test_date in enumerate(unique_dates):
        train_mask = np.array([d != test_date for d in dates])
        test_mask = ~train_mask
        n_train = train_mask.sum()
        n_test = test_mask.sum()
        if n_test == 0 or n_train < 50:
            continue

        X_train, X_test = X[train_mask], X[test_mask]
        y_train, y_test = y[train_mask], y[test_mask]

        # Impute + scale WITHIN fold (no leakage)
        imputer = SimpleImputer(strategy="median")
        X_train_imp = imputer.fit_transform(X_train)
        X_test_imp = imputer.transform(X_test)

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train_imp)
        X_test_s = scaler.transform(X_test_imp)

        for mname, model in models.items():
            # Clone model for fresh fit
            from sklearn.base import clone
            m = clone(model)
            try:
                m.fit(X_train_s, y_train)
                pred = m.predict(X_test_s)
            except Exception as e:
                print(f"  Fold {fold_idx} {mname}: ERROR {e}")
                continue
            # Per-fold metrics
            r2 = _oos_r2(y_test, pred)
            ic = _oos_ic(y_test, pred)
            lift = _oos_lift(y_test, pred)
            fold_r2[mname].append(r2)
            fold_ic[mname].append(ic)
            fold_lift[mname].append(lift)
            # Store predictions
            test_indices = np.where(test_mask)[0]
            oos_preds[mname][test_indices] = pred

    # Aggregate
    results = {}
    print(f"\n--- {target_name} OOS Results ---")
    print(f"{'Model':<20s} {'R²(mean±std)':<20s} {'IC(mean±std)':<20s} {'Lift(mean±std)':<20s} {'p(IC>0)':<10s}")
    for mname in models:
        r2s = np.array(fold_r2[mname])
        ics = np.array(fold_ic[mname])
        lifts = np.array(fold_lift[mname])
        # Permutation test for IC
        ic_pval = _permutation_pval(ics)
        r2_mean = np.mean(r2s) if len(r2s) else 0
        r2_std = np.std(r2s) if len(r2s) else 0
        ic_mean = np.mean(ics) if len(ics) else 0
        ic_std = np.std(ics) if len(ics) else 0
        lift_mean = np.mean(lifts) if len(lifts) else 1
        lift_std = np.std(lifts) if len(lifts) else 0
        sig = "**" if ic_pval < BONF_ALPHA else ("*" if ic_pval < ALPHA else "")
        print(f"{mname:<20s} {r2_mean:+.4f}±{r2_std:.4f}   {ic_mean:+.4f}±{ic_std:.4f}   {lift_mean:.3f}±{lift_std:.3f}   {ic_pval:.4f}{sig}")
        results[mname] = {
            "r2_mean": r2_mean, "r2_std": r2_std,
            "ic_mean": ic_mean, "ic_std": ic_std,
            "lift_mean": lift_mean, "lift_std": lift_std,
            "ic_pval": ic_pval,
            "n_folds": len(r2s),
            "per_fold_r2": r2s.tolist(),
            "per_fold_ic": ics.tolist(),
        }

    # Aggregate OOS IC (all predictions pooled)
    print(f"\n--- {target_name} Pooled OOS IC ---")
    for mname in models:
        preds = oos_preds[mname]
        valid = ~np.isnan(preds)
        if valid.sum() < 10:
            continue
        pooled_ic, _ = spearmanr(preds[valid], y[valid])
        pooled_r2 = _oos_r2(y[valid], preds[valid])
        pooled_lift = _oos_lift(y[valid], preds[valid])
        top_q = y[valid][np.argsort(preds[valid])[-max(1, valid.sum() // 5):]]
        bot_q = y[valid][np.argsort(preds[valid])[:max(1, valid.sum() // 5):]]
        print(f"  {mname}: pooled_IC={pooled_ic:+.4f}, pooled_R²={pooled_r2:+.4f}, "
              f"pooled_lift={pooled_lift:.3f}, top_q_mean={np.mean(top_q):.3f}%, bot_q_mean={np.mean(bot_q):.3f}%")
        results[mname]["pooled_ic"] = pooled_ic
        results[mname]["pooled_r2"] = pooled_r2
        results[mname]["pooled_lift"] = pooled_lift
        results[mname]["top_quintile_mean"] = float(np.mean(top_q))
        results[mname]["bottom_quintile_mean"] = float(np.mean(bot_q))

    return results


def _permutation_pval(ics: np.ndarray, n_perm: int = 10000) -> float:
    """One-sided permutation test: P(mean(IC) >= observed | H0: no signal).

    Under H0, IC signs are random → flip each fold's IC sign with p=0.5.
    """
    if len(ics) == 0:
        return 1.0
    observed = np.mean(ics)
    count = 0
    rng = np.random.RandomState(42)
    for _ in range(n_perm):
        signs = rng.choice([-1, 1], size=len(ics))
        if np.mean(ics * signs) >= observed:
            count += 1
    return (count + 1) / (n_perm + 1)


def feature_importance_lgb(X: np.ndarray, y: np.ndarray, dates: list[str],
                           feature_names: list[str], target_name: str) -> None:
    """LightGBM feature importance (per-fold averaged, no full-sample fit)."""
    import lightgbm as lgb
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer

    unique_dates = sorted(set(dates))
    importances = np.zeros(X.shape[1])
    n_folds = 0

    for test_date in unique_dates:
        train_mask = np.array([d != test_date for d in dates])
        if train_mask.sum() < 50:
            continue
        X_train = X[train_mask]
        y_train = y[train_mask]
        imputer = SimpleImputer(strategy="median")
        X_train_imp = imputer.fit_transform(X_train)
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train_imp)
        m = lgb.LGBMRegressor(
            n_estimators=100, max_depth=4, num_leaves=15,
            learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
            reg_alpha=0.1, reg_lambda=1.0, random_state=42, verbose=-1,
        )
        m.fit(X_train_s, y_train)
        importances += m.feature_importances_
        n_folds += 1

    if n_folds > 0:
        importances /= n_folds
    print(f"\n--- {target_name} LightGBM Feature Importance (avg across {n_folds} folds) ---")
    idx_sorted = np.argsort(importances)[::-1]
    for i in idx_sorted:
        print(f"  {feature_names[i]:<22s} {importances[i]:.1f}")


def main() -> int:
    X, y_premium, y_cont, feat_names, dates = build_feature_matrix()

    # --- PRIMARY: premium (gap) ---
    print("\n" + "=" * 70)
    print("TARGET 1: PREMIUM (gap%, D收→D+1开)")
    print("=" * 70)
    results_premium = walk_forward_cv(X, y_premium, dates, feat_names, "premium(gap)")
    feature_importance_lgb(X, y_premium, dates, feat_names, "premium(gap)")

    # --- SECONDARY: continuation (D+1→D+4 path return) ---
    valid_cont = ~np.isnan(y_cont)
    if valid_cont.sum() > 50:
        print("\n" + "=" * 70)
        print("TARGET 2: CONTINUATION (D+1开→D+4 path return%)")
        print("=" * 70)
        X_c = X[valid_cont]
        y_c = y_cont[valid_cont]
        dates_c = [d for d, v in zip(dates, valid_cont) if v]
        results_cont = walk_forward_cv(X_c, y_c, dates_c, feat_names, "continuation")
        feature_importance_lgb(X_c, y_c, dates_c, feat_names, "continuation")
    else:
        print(f"\nContinuation target: only {valid_cont.sum()} valid samples, skipping")

    # --- SUMMARY ---
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\nPremium (gap) — best model OOS metrics:")
    for mname, r in results_premium.items():
        verdict = "EDGE" if r["ic_pval"] < BONF_ALPHA else ("suggestive" if r["ic_pval"] < ALPHA else "no_edge")
        print(f"  {mname}: IC={r['ic_mean']:+.4f} (p={r['ic_pval']:.4f}), R²={r['r2_mean']:+.4f}, "
              f"lift={r['lift_mean']:.3f}, pooled_IC={r.get('pooled_ic', 0):+.4f} → {verdict}")

    print(f"\nBonferroni threshold: p < {BONF_ALPHA:.4f} (alpha={ALPHA}/{N_MODELS})")
    print(f"\nHonest verdict:")
    best_ic = max(r["ic_mean"] for r in results_premium.values())
    best_pval = min(r["ic_pval"] for r in results_premium.values())
    if best_pval < BONF_ALPHA:
        print(f"  MULTI-FACTOR EDGE FOUND: best IC={best_ic:+.4f}, p={best_pval:.4f} < {BONF_ALPHA:.4f}")
    elif best_pval < ALPHA:
        print(f"  SUGGESTIVE (pre-Bonferroni): best IC={best_ic:+.4f}, p={best_pval:.4f} < {ALPHA} but >= {BONF_ALPHA:.4f}")
    else:
        print(f"  NO COMBO EDGE: best IC={best_ic:+.4f}, p={best_pval:.4f} >= {ALPHA}")
        print(f"  Multi-factor combination does not find selection power beyond single factors.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
