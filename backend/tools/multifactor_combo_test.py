#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-factor combination test: Can a linear/nonlinear combination of factors
find selection power that individual factors cannot?

TARGET 1: premium (gap, D close -> D+1 open)  — the overnight gap for first-board stocks.
TARGET 2: continuation (path return D+1 open -> D+4, SL=-3/TP=+8/max_hold=3)

FACTORS (7, after dropping seal_amount which has 0% coverage for sample dates):
  gene_score, vol_surge, volatility, momentum, breakout, boards, PE

METHOD (walk-forward CV, honest OOS):
  - Leave-one-day-out (LODO): 14 folds, train on 13 days, predict 1 day.
  - Expanding window: train on days 1..k, predict day k+1.
  - Models: OLS, LASSO (alpha tuned via inner CV on train only), RandomForest (nonlinear).
  - Also: equal-weight composite baseline (mean of standardized factors).
  - Report: OOS R2 (pooled), OOS IC (Spearman, pooled), per-fold breakdown.
  - Bonferroni: K = 3 models x 2 targets = 6 comparisons; alpha_adj = 0.05/6 = 0.0083.
  - No feature-selection bias: all features used; LASSO alpha tuned on train only.

HONEST: OOS R2~0 / IC~0 -> report "no combination edge", do not p-hack.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import warnings
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import spearmanr, pearsonr
from sklearn.linear_model import LinearRegression, LassoCV, Lasso
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tools.kline_ta_validation import _compute_ta  # noqa: E402
from strategies.kline_returns import simulate_holding, _is_unbuyable_next_bar  # noqa: E402

VR = ROOT / ".vibe-research"
FB_BASELINE = VR / "first_board_premium_baseline.json"
KLINE_CACHE = VR / "baostock_kline_cache.json"
GENE_DB = VR / "gene_scores.db"
THS_LB = VR / "ths_lb_cache.json"
PROFIT_CACHE = VR / "profit_data_cache.json"

FEATURES = ["gene_score", "vol_surge", "volatility", "momentum", "breakout", "boards", "pe"]
# Bonferroni: 5 active models (ols, lasso, rf, lgbm_shallow, lgbm_medium) x 2 targets = 10
N_BONFERRONI = 10
ALPHA_ADJ = 0.05 / N_BONFERRONI


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Sample:
    date: str          # YYYY-MM-DD (D, the first-board day)
    date_ymd: str      # YYYYMMDD
    code: str
    name: str
    t_close: float
    t1_open: float
    premium: float     # gap = (t1_open - t_close) / t_close * 100
    zt_count: int
    market_condition: str


def load_samples() -> list[Sample]:
    fb = json.loads(FB_BASELINE.read_bytes())
    out = []
    for s in fb["samples"]:
        out.append(Sample(
            date=s["date"],
            date_ymd=s["date"].replace("-", ""),
            code=s["code"],
            name=s.get("name", ""),
            t_close=float(s["t_close"]),
            t1_open=float(s["t1_open"]),
            premium=float(s["premium"]),
            zt_count=int(s.get("zt_count", 0)),
            market_condition=s.get("market_condition", ""),
        ))
    return out


def load_kline_cache() -> dict:
    """Load baostock kline cache (153MB). Returns {code: [bars]}."""
    print("Loading kline cache (153MB)...", file=sys.stderr)
    return json.loads(KLINE_CACHE.read_bytes())


def load_gene_scores() -> dict[tuple[str, str], float]:
    """Returns {(date, code): total_score} for eastmoney_live."""
    conn = sqlite3.connect(str(GENE_DB), timeout=10)
    try:
        rows = conn.execute(
            "SELECT date, code, total_score FROM gene_scores WHERE data_source='eastmoney_live'"
        ).fetchall()
    finally:
        conn.close()
    return {(r[0], r[1]): float(r[2]) for r in rows if r[2] is not None}


def load_boards() -> dict[tuple[str, str], int]:
    """Returns {(date_ymd, code): boards}."""
    ths = json.loads(THS_LB.read_bytes())
    out = {}
    for d_ymd, pool in ths.items():
        for item in pool:
            out[(d_ymd, item["code"])] = int(item.get("boards", 1))
    return out


def load_profit_data() -> dict[str, dict]:
    """Returns {code: {quarter: {epsTTM, pubDate}}}."""
    return json.loads(PROFIT_CACHE.read_bytes())


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------

def compute_pe(profit_data: dict, code: str, date: str, t_close: float) -> tuple[float | None, bool]:
    """Find latest quarter with pubDate <= date, compute PE = t_close / epsTTM.
    Returns (pe_value, has_data)."""
    quarters = profit_data.get(code)
    if not quarters:
        return None, False
    valid = [(q, v) for q, v in quarters.items()
            if v.get("pubDate", "") <= date and v.get("epsTTM", 0) > 0]
    if not valid:
        return None, False
    valid.sort(key=lambda x: x[1]["pubDate"], reverse=True)
    eps_ttm = valid[0][1]["epsTTM"]
    if eps_ttm <= 0 or t_close <= 0:
        return None, False
    return t_close / eps_ttm, True


def build_feature_matrix(
    samples: list[Sample],
    kline_cache: dict,
    gene_scores: dict,
    boards_map: dict,
    profit_data: dict,
) -> list[dict]:
    """Join all data sources into a list of observation dicts.
    Each dict has: date, code, premium (target1), path_return (target2 or None),
    and all 7 features. Missing features are imputed later.
    """
    # Group samples by date for TA computation efficiency
    out = []
    ta_fail = 0
    for s in samples:
        bars = kline_cache.get(s.code, [])
        # Compute TA features on D-1 (pre-signal, no look-ahead)
        ta = _compute_ta(bars, s.date) if bars else None
        if ta is None:
            ta_fail += 1
            # Impute TA with zeros (will be standardized later)
            ta = {"momentum": 0.0, "vol_surge": 0.0, "ma_align": 0,
                  "breakout": 0, "volatility": 0.0}

        # gene_score
        gs = gene_scores.get((s.date, s.code), None)

        # boards
        bd = boards_map.get((s.date_ymd, s.code), 1)

        # PE
        pe_val, pe_has = compute_pe(profit_data, s.code, s.date, s.t_close)

        # Continuation target: path return D+1 open -> D+4
        path_ret = None
        path_won = None
        if bars:
            idx = next((i for i, b in enumerate(bars)
                        if str(b.get("date", ""))[:10] == s.date), None)
            if idx is not None and idx + 1 < len(bars):
                nb = bars[idx + 1]
                if not _is_unbuyable_next_bar(nb):
                    sim = simulate_holding(
                        bars, s.date,
                        stop_pct=-3.0, take_profit_pct=8.0, max_hold_days=3,
                    )
                    if sim is not None:
                        path_ret = sim["return_pct"]
                        path_won = sim["won"]

        out.append({
            "date": s.date,
            "code": s.code,
            "premium": s.premium,
            "path_return": path_ret,
            "path_won": path_won,
            # Features
            "gene_score": gs if gs is not None else np.nan,
            "vol_surge": ta["vol_surge"],
            "volatility": ta["volatility"],
            "momentum": ta["momentum"],
            "breakout": ta["breakout"],
            "boards": bd,
            "pe": pe_val if pe_val is not None else np.nan,
            "pe_has": pe_has,
        })

    print(f"  TA computation failed for {ta_fail}/{len(samples)} (imputed with 0)", file=sys.stderr)
    return out


# ---------------------------------------------------------------------------
# Imputation (within CV fold — no look-ahead)
# ---------------------------------------------------------------------------

def impute_features(train_data: list[dict], test_data: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Impute missing features using training-set medians.
    Returns (X_train, y_train_premium, X_test, y_test_premium).
    Also returns path_return arrays separately.
    """
    # Compute medians from training set only
    medians = {}
    for feat in FEATURES:
        vals = [d[feat] for d in train_data if not np.isnan(d[feat])]
        medians[feat] = float(np.median(vals)) if vals else 0.0

    def to_matrix(data: list[dict]) -> np.ndarray:
        mat = np.zeros((len(data), len(FEATURES)))
        for i, d in enumerate(data):
            for j, feat in enumerate(FEATURES):
                v = d[feat]
                mat[i, j] = medians[feat] if np.isnan(v) else v
        return mat

    X_train = to_matrix(train_data)
    X_test = to_matrix(test_data)
    y_train_prem = np.array([d["premium"] for d in train_data])
    y_test_prem = np.array([d["premium"] for d in test_data])
    return X_train, X_test, y_train_prem, y_test_prem


def get_path_targets(data: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Extract path_return target, filtering None (unbuyable)."""
    y = np.array([d["path_return"] for d in data if d["path_return"] is not None])
    mask = np.array([d["path_return"] is not None for d in data])
    return y, mask


# ---------------------------------------------------------------------------
# Walk-forward CV
# ---------------------------------------------------------------------------

@dataclass
class CVResult:
    model_name: str
    target_name: str
    cv_type: str
    oos_r2: float
    oos_ic: float
    oos_ic_pval: float
    n_oos: int
    per_fold: list[dict] = field(default_factory=list)
    is_r2: float = 0.0  # in-sample R2 (for overfit detection)


def lodo_cv(
    observations: list[dict],
    model_name: str,
    target_name: str,
    dates: list[str],
) -> CVResult:
    """Leave-one-day-out CV. Train on 13 days, predict 1 day."""
    all_preds = []
    all_actuals = []
    per_fold = []
    is_preds = []
    is_actuals = []

    for held_date in dates:
        train_data = [o for o in observations if o["date"] != held_date]
        test_data = [o for o in observations if o["date"] == held_date]

        if target_name == "path_return":
            # Filter out None path returns from train
            train_data = [o for o in train_data if o["path_return"] is not None]
            if len(train_data) < 20:
                continue

        X_train, X_test, y_train, y_test = impute_features(
            train_data if target_name == "premium" else [o for o in train_data],
            test_data,
        )

        if target_name == "path_return":
            y_train = np.array([o["path_return"] for o in train_data])
            y_test = np.array([o["path_return"] for o in test_data if o["path_return"] is not None])
            # Need to re-extract X_test for buyable only
            buyable_test = [o for o in test_data if o["path_return"] is not None]
            if not buyable_test:
                continue
            _, X_test, _, _ = impute_features(train_data, buyable_test)

        # Standardize (fit on train only)
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        # Fit model
        if model_name == "ols":
            model = LinearRegression()
        elif model_name == "lasso":
            # Tune alpha via inner 5-fold CV on train only
            model = LassoCV(cv=min(5, len(train_data)), max_iter=10000, random_state=42)
        elif model_name == "rf":
            model = RandomForestRegressor(n_estimators=100, max_depth=5,
                                          random_state=42, n_jobs=-1)
        elif model_name == "lgbm_shallow":
            model = lgb.LGBMRegressor(max_depth=3, n_estimators=100, learning_rate=0.05,
                                     reg_lambda=1.0, min_child_samples=20, subsample=0.8,
                                     colsample_bytree=0.8, random_state=42, verbose=-1)
        elif model_name == "lgbm_medium":
            model = lgb.LGBMRegressor(max_depth=5, n_estimators=200, learning_rate=0.05,
                                     reg_lambda=0.5, min_child_samples=10, subsample=0.8,
                                     colsample_bytree=0.8, random_state=42, verbose=-1)
        elif model_name == "composite":
            # Equal-weight composite: mean of standardized features
            preds_test = np.mean(X_test_s, axis=1)
            preds_train = np.mean(X_train_s, axis=1)
            all_preds.extend(preds_test.tolist())
            all_actuals.extend(y_test.tolist())
            is_preds.extend(preds_train.tolist())
            is_actuals.extend(y_train.tolist())
            r2_fold = 1 - np.sum((y_test - preds_test) ** 2) / max(np.sum((y_test - np.mean(y_test)) ** 2), 1e-10)
            ic_fold, _ = spearmanr(preds_test, y_test)
            per_fold.append({"date": held_date, "r2": r2_fold, "ic": ic_fold if not np.isnan(ic_fold) else 0.0, "n": len(y_test)})
            continue
        else:
            raise ValueError(f"Unknown model: {model_name}")

        model.fit(X_train_s, y_train)
        preds_test = model.predict(X_test_s)
        preds_train = model.predict(X_train_s)

        all_preds.extend(preds_test.tolist())
        all_actuals.extend(y_test.tolist())
        is_preds.extend(preds_train.tolist())
        is_actuals.extend(y_train.tolist())

        # Per-fold metrics
        if len(y_test) > 1:
            ss_res = np.sum((y_test - preds_test) ** 2)
            ss_tot = np.sum((y_test - np.mean(y_test)) ** 2)
            r2_fold = 1 - ss_res / max(ss_tot, 1e-10)
            ic_fold, _ = spearmanr(preds_test, y_test)
            per_fold.append({
                "date": held_date, "r2": r2_fold,
                "ic": ic_fold if not np.isnan(ic_fold) else 0.0,
                "n": len(y_test),
            })

    # Pooled OOS metrics
    all_preds = np.array(all_preds)
    all_actuals = np.array(all_actuals)
    n = len(all_actuals)
    if n < 2:
        return CVResult(model_name, target_name, "LODO", 0.0, 0.0, 1.0, n)

    ss_res = np.sum((all_actuals - all_preds) ** 2)
    ss_tot = np.sum((all_actuals - np.mean(all_actuals)) ** 2)
    oos_r2 = 1 - ss_res / max(ss_tot, 1e-10)
    oos_ic, oos_pval = spearmanr(all_preds, all_actuals)

    # In-sample R2 (for overfit detection)
    is_preds = np.array(is_preds)
    is_actuals = np.array(is_actuals)
    is_ss_res = np.sum((is_actuals - is_preds) ** 2)
    is_ss_tot = np.sum((is_actuals - np.mean(is_actuals)) ** 2)
    is_r2 = 1 - is_ss_res / max(is_ss_tot, 1e-10)

    return CVResult(
        model_name=model_name, target_name=target_name, cv_type="LODO",
        oos_r2=oos_r2, oos_ic=oos_ic if not np.isnan(oos_ic) else 0.0,
        oos_ic_pval=oos_pval if not np.isnan(oos_pval) else 1.0,
        n_oos=n, per_fold=per_fold, is_r2=is_r2,
    )


def expanding_window_cv(
    observations: list[dict],
    model_name: str,
    target_name: str,
    dates: list[str],
) -> CVResult:
    """Expanding window: train on days 1..k, predict day k+1."""
    all_preds = []
    all_actuals = []
    per_fold = []

    for i in range(2, len(dates)):  # Need at least 2 days to train
        train_dates = dates[:i]
        test_date = dates[i]
        train_data = [o for o in observations if o["date"] in train_dates]
        test_data = [o for o in observations if o["date"] == test_date]

        if target_name == "path_return":
            train_data = [o for o in train_data if o["path_return"] is not None]
            if len(train_data) < 20:
                continue

        buyable_test = [o for o in test_data if o["path_return"] is not None] if target_name == "path_return" else test_data
        if not buyable_test:
            continue

        X_train, X_test, y_train, y_test = impute_features(train_data, buyable_test)

        if target_name == "path_return":
            y_train = np.array([o["path_return"] for o in train_data])
            y_test = np.array([o["path_return"] for o in buyable_test])

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        if model_name == "composite":
            preds_test = np.mean(X_test_s, axis=1)
        else:
            if model_name == "ols":
                model = LinearRegression()
            elif model_name == "lasso":
                model = LassoCV(cv=min(5, len(train_data)), max_iter=10000, random_state=42)
            elif model_name == "rf":
                model = RandomForestRegressor(n_estimators=100, max_depth=5,
                                              random_state=42, n_jobs=-1)
            elif model_name == "lgbm_shallow":
                model = lgb.LGBMRegressor(max_depth=3, n_estimators=100, learning_rate=0.05,
                                         reg_lambda=1.0, min_child_samples=20, subsample=0.8,
                                         colsample_bytree=0.8, random_state=42, verbose=-1)
            elif model_name == "lgbm_medium":
                model = lgb.LGBMRegressor(max_depth=5, n_estimators=200, learning_rate=0.05,
                                         reg_lambda=0.5, min_child_samples=10, subsample=0.8,
                                         colsample_bytree=0.8, random_state=42, verbose=-1)
            else:
                raise ValueError(f"Unknown model: {model_name}")
            model.fit(X_train_s, y_train)
            preds_test = model.predict(X_test_s)

        all_preds.extend(preds_test.tolist())
        all_actuals.extend(y_test.tolist())

        if len(y_test) > 1:
            ss_res = np.sum((y_test - preds_test) ** 2)
            ss_tot = np.sum((y_test - np.mean(y_test)) ** 2)
            r2_fold = 1 - ss_res / max(ss_tot, 1e-10)
            ic_fold, _ = spearmanr(preds_test, y_test)
            per_fold.append({"date": test_date, "r2": r2_fold,
                             "ic": ic_fold if not np.isnan(ic_fold) else 0.0, "n": len(y_test)})

    all_preds = np.array(all_preds)
    all_actuals = np.array(all_actuals)
    n = len(all_actuals)
    if n < 2:
        return CVResult(model_name, target_name, "expanding", 0.0, 0.0, 1.0, n)

    ss_res = np.sum((all_actuals - all_preds) ** 2)
    ss_tot = np.sum((all_actuals - np.mean(all_actuals)) ** 2)
    oos_r2 = 1 - ss_res / max(ss_tot, 1e-10)
    oos_ic, oos_pval = spearmanr(all_preds, all_actuals)

    return CVResult(
        model_name=model_name, target_name=target_name, cv_type="expanding",
        oos_r2=oos_r2, oos_ic=oos_ic if not np.isnan(oos_ic) else 0.0,
        oos_ic_pval=oos_pval if not np.isnan(oos_pval) else 1.0,
        n_oos=n, per_fold=per_fold,
    )


# ---------------------------------------------------------------------------
# Full-sample coefficient analysis (for interpretation only, not for OOS)
# ---------------------------------------------------------------------------

def full_sample_coefs(observations: list[dict], target: str) -> dict:
    """Fit OLS and LASSO on full sample for coefficient interpretation.
    NOTE: This is NOT the OOS result — it's for understanding feature directions."""
    data = observations
    if target == "path_return":
        data = [o for o in observations if o["path_return"] is not None]
    if len(data) < 20:
        return {}

    # Impute with full-sample medians
    medians = {}
    for feat in FEATURES:
        vals = [d[feat] for d in data if not np.isnan(d[feat])]
        medians[feat] = float(np.median(vals)) if vals else 0.0

    X = np.zeros((len(data), len(FEATURES)))
    for i, d in enumerate(data):
        for j, feat in enumerate(FEATURES):
            v = d[feat]
            X[i, j] = medians[feat] if np.isnan(v) else v
    y = np.array([d["premium"] if target == "premium" else d["path_return"] for d in data])

    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)

    ols = LinearRegression().fit(X_s, y)
    lasso = Lasso(alpha=0.01, max_iter=10000).fit(X_s, y)

    # Spearman IC of each individual factor
    individual_ics = {}
    for j, feat in enumerate(FEATURES):
        ic, p = spearmanr(X_s[:, j], y)
        individual_ics[feat] = {"ic": ic if not np.isnan(ic) else 0.0,
                                "pval": p if not np.isnan(p) else 1.0}

    return {
        "features": FEATURES,
        "ols_coefs": dict(zip(FEATURES, [round(c, 4) for c in ols.coef_])),
        "ols_intercept": round(float(ols.intercept_), 4),
        "lasso_coefs": dict(zip(FEATURES, [round(c, 4) for c in lasso.coef_])),
        "lasso_intercept": round(float(lasso.intercept_), 4),
        "individual_ics": {k: {"ic": round(v["ic"], 4), "pval": round(v["pval"], 4)}
                            for k, v in individual_ics.items()},
        "n": len(data),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 72)
    print("Multi-Factor Combination Test (§44 v2)")
    print("Can a linear/nonlinear combination find edge that single factors cannot?")
    print("=" * 72)

    # Load data
    samples = load_samples()
    print(f"\nSamples: {len(samples)} across {len(set(s.date for s in samples))} days")
    print(f"Date range: {min(s.date for s in samples)} -> {max(s.date for s in samples)}")
    premiums = [s.premium for s in samples]
    print(f"Premium stats: mean={np.mean(premiums):.4f}%, median={np.median(premiums):.4f}%, "
          f"std={np.std(premiums):.4f}%, min={np.min(premiums):.2f}%, max={np.max(premiums):.2f}%")

    kline_cache = load_kline_cache()
    gene_scores = load_gene_scores()
    boards_map = load_boards()
    profit_data = load_profit_data()

    # Build feature matrix
    print("\nBuilding feature matrix...", file=sys.stderr)
    obs = build_feature_matrix(samples, kline_cache, gene_scores, boards_map, profit_data)
    dates = sorted(set(o["date"] for o in obs))
    print(f"Observations: {len(obs)} across {len(dates)} days")

    # Check feature coverage
    print("\nFeature coverage:")
    for feat in FEATURES:
        n_valid = sum(1 for o in obs if not np.isnan(o[feat]))
        vals = [o[feat] for o in obs if not np.isnan(o[feat])]
        if vals:
            print(f"  {feat:12s}: {n_valid}/{len(obs)} ({100*n_valid/len(obs):.0f}%)  "
                  f"median={np.median(vals):.4f}  IQR=[{np.percentile(vals,25):.4f}, {np.percentile(vals,75):.4f}]")
        else:
            print(f"  {feat:12s}: 0/{len(obs)} (DROPPED)")

    # Path return coverage
    n_path = sum(1 for o in obs if o["path_return"] is not None)
    path_rets = [o["path_return"] for o in obs if o["path_return"] is not None]
    print(f"\nPath return (continuation): {n_path}/{len(obs)} buyable "
          f"({100*n_path/len(obs):.0f}%)")
    if path_rets:
        print(f"  mean={np.mean(path_rets):.4f}%, median={np.median(path_rets):.4f}%, "
              f"win_rate={sum(1 for r in path_rets if r > 0)/len(path_rets)*100:.1f}%")

    # Drop seal_amount note
    print("\nNOTE: seal_amount DROPPED (0% coverage — zt_pool data starts 2026-08-17, "
          "after all 14 sample dates 07-28..08-14).")

    # --- Run CV ---
    print("\n" + "=" * 72)
    print("WALK-FORWARD CV RESULTS (LODO = Leave-One-Day-Out)")
    print("=" * 72)

    models = ["composite", "ols", "lasso", "rf", "lgbm_shallow", "lgbm_medium"]
    targets = ["premium", "path_return"]
    results: list[CVResult] = []

    for target in targets:
        print(f"\n--- Target: {target} ---")
        for model in models:
            res = lodo_cv(obs, model, target, dates)
            results.append(res)
            bonf_pval = min(res.oos_ic_pval * N_BONFERRONI, 1.0)
            sig = "***" if bonf_pval < ALPHA_ADJ else ("**" if res.oos_ic_pval < 0.05 else "")
            print(f"  {model:10s} | OOS R2={res.oos_r2:+.4f} | OOS IC={res.oos_ic:+.4f} "
                  f"(p={res.oos_ic_pval:.4f}, Bonf={bonf_pval:.4f}) {sig} | "
                  f"IS R2={res.is_r2:+.4f} | n={res.n_oos}")

    # Expanding window (supplementary)
    print("\n" + "=" * 72)
    print("EXPANDING WINDOW CV (supplementary)")
    print("=" * 72)
    for target in targets:
        print(f"\n--- Target: {target} ---")
        for model in models:
            res = expanding_window_cv(obs, model, target, dates)
            bonf_pval = min(res.oos_ic_pval * N_BONFERRONI, 1.0)
            print(f"  {model:10s} | OOS R2={res.oos_r2:+.4f} | OOS IC={res.oos_ic:+.4f} "
                  f"(p={res.oos_ic_pval:.4f}, Bonf={bonf_pval:.4f}) | n={res.n_oos}")

    # --- Full-sample coefficients (interpretation only) ---
    print("\n" + "=" * 72)
    print("FULL-SAMPLE COEFFICIENTS (interpretation only, NOT OOS)")
    print("=" * 72)
    for target in targets:
        print(f"\n--- Target: {target} ---")
        coefs = full_sample_coefs(obs, target)
        if not coefs:
            print("  (insufficient data)")
            continue
        print(f"  N={coefs['n']}")
        print(f"\n  OLS coefficients (standardized):")
        for feat, c in coefs["ols_coefs"].items():
            print(f"    {feat:12s}: {c:+.4f}")
        print(f"  intercept: {coefs['ols_intercept']:.4f}")
        print(f"\n  LASSO coefficients (alpha=0.01, standardized):")
        for feat, c in coefs["lasso_coefs"].items():
            print(f"    {feat:12s}: {c:+.4f}")
        print(f"  intercept: {coefs['lasso_intercept']:.4f}")
        print(f"\n  Individual factor IC (Spearman, single-factor):")
        for feat, v in coefs["individual_ics"].items():
            print(f"    {feat:12s}: IC={v['ic']:+.4f} (p={v['pval']:.4f})")

    # --- Per-fold breakdown (LODO, OLS, premium) ---
    print("\n" + "=" * 72)
    print("PER-FOLD BREAKDOWN (LODO, OLS, premium)")
    print("=" * 72)
    for r in results:
        if r.model_name == "ols" and r.target_name == "premium" and r.cv_type == "LODO":
            print(f"\n  {'Date':12s} {'R2':>8s} {'IC':>8s} {'N':>4s}")
            for f in r.per_fold:
                print(f"  {f['date']:12s} {f['r2']:+8.4f} {f['ic']:+8.4f} {f['n']:4d}")

    # --- LightGBM feature importance (LODO-averaged, premium target) ---
    print("\n" + "=" * 72)
    print("LIGHTGBM FEATURE IMPORTANCE (LODO-averaged, premium target)")
    print("=" * 72)
    fi_vals = {f: [] for f in FEATURES}
    daily_ics_lgbm = []
    for held_date in dates:
        train_data = [o for o in obs if o["date"] != held_date]
        test_data = [o for o in obs if o["date"] == held_date]
        if len(train_data) < 20 or len(test_data) < 3:
            continue
        X_tr, X_te, y_tr, _ = impute_features(train_data, test_data)
        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)
        m = lgb.LGBMRegressor(max_depth=3, n_estimators=100, learning_rate=0.05,
                              reg_lambda=1.0, min_child_samples=20, subsample=0.8,
                              colsample_bytree=0.8, random_state=42, verbose=-1)
        m.fit(X_tr_s, y_tr)
        for i, f in enumerate(FEATURES):
            fi_vals[f].append(m.feature_importances_[i])
        # daily IC
        preds = m.predict(X_te_s)
        y_te = np.array([o["premium"] for o in test_data])
        ic_dy, _ = spearmanr(preds, y_te)
        if not np.isnan(ic_dy):
            daily_ics_lgbm.append(ic_dy)

    print(f"\n  {'Feature':14s} {'MeanImp':>10s} {'StdImp':>10s} {'%Share':>8s}")
    print("  " + "-" * 44)
    fi_means = {f: np.mean(v) for f, v in fi_vals.items() if v}
    total_imp = sum(fi_means.values()) or 1
    for f, v in sorted(fi_means.items(), key=lambda x: -x[1]):
        print(f"  {f:14s} {v:10.1f} {np.std(fi_vals[f]):10.1f} {v/total_imp*100:7.1f}%")

    # Daily IC stats for LGBM-shallow
    if daily_ics_lgbm:
        dics = np.array(daily_ics_lgbm)
        mean_ic = dics.mean()
        std_ic = dics.std(ddof=1)
        icir = mean_ic / std_ic if std_ic > 0 else 0
        t_stat = mean_ic / (std_ic / np.sqrt(len(dics))) if std_ic > 0 else 0
        p_val = 2 * __import__("scipy").stats.t.sf(abs(t_stat), df=len(dics) - 1)
        print(f"\n  Daily IC (LGBM-shallow, LODO):")
        print(f"    mean={mean_ic:+.4f} std={std_ic:.4f} ICIR={icir:+.3f} "
              f"t={t_stat:+.2f} p={p_val:.4f} n_days={len(dics)}")
        print(f"    Bonferroni p={min(p_val * N_BONFERRONI, 1.0):.4f} "
              f"(sig if < {ALPHA_ADJ:.4f})")

    # --- Lift analysis (LGBM-shallow, premium, pooled OOS) ---
    print("\n" + "=" * 72)
    print("LIFT ANALYSIS (LGBM-shallow, premium, pooled OOS predictions)")
    print("=" * 72)
    all_lgbm_preds = []
    all_lgbm_actuals = []
    for held_date in dates:
        train_data = [o for o in obs if o["date"] != held_date]
        test_data = [o for o in obs if o["date"] == held_date]
        if len(train_data) < 20 or len(test_data) < 1:
            continue
        X_tr, X_te, y_tr, y_te = impute_features(train_data, test_data)
        scaler = StandardScaler()
        m = lgb.LGBMRegressor(max_depth=3, n_estimators=100, learning_rate=0.05,
                              reg_lambda=1.0, min_child_samples=20, subsample=0.8,
                              colsample_bytree=0.8, random_state=42, verbose=-1)
        m.fit(scaler.fit_transform(X_tr), y_tr)
        preds = m.predict(scaler.transform(X_te))
        all_lgbm_preds.extend(preds.tolist())
        all_lgbm_actuals.extend(y_te.tolist())

    all_lgbm_preds = np.array(all_lgbm_preds)
    all_lgbm_actuals = np.array(all_lgbm_actuals)
    order = np.argsort(all_lgbm_preds)
    q = max(1, len(order) // 5)
    for label, idx_slice in [("Q1(bottom)", order[:q]), ("Q2", order[q:2*q]),
                              ("Q3(mid)", order[2*q:3*q]), ("Q4", order[3*q:4*q]),
                              ("Q5(top)", order[-q:])]:
        actuals = all_lgbm_actuals[idx_slice]
        print(f"  {label:14s}: n={len(actuals):3d}  mean_premium={np.mean(actuals):+.3f}%  "
              f"median={np.median(actuals):+.3f}%")
    top_mean = np.mean(all_lgbm_actuals[order[-q:]])
    bot_mean = np.mean(all_lgbm_actuals[order[:q]])
    print(f"\n  Top - Bottom spread = {top_mean - bot_mean:+.3f}%")
    print(f"  Top / Bottom ratio = {top_mean/bot_mean:.3f}x" if abs(bot_mean) > 1e-8 else "  Bottom≈0")

    # --- Verdict ---
    print("\n" + "=" * 72)
    print("VERDICT")
    print("=" * 72)

    # Check if any model/target achieves significant OOS IC after Bonferroni
    best_ic = 0.0
    best_r2 = -999.0
    best_desc = ""
    for r in results:
        if r.cv_type != "LODO":
            continue
        bonf_pval = min(r.oos_ic_pval * N_BONFERRONI, 1.0)
        if abs(r.oos_ic) > abs(best_ic):
            best_ic = r.oos_ic
            best_desc = f"{r.model_name}/{r.target_name}"
        if r.oos_r2 > best_r2:
            best_r2 = r.oos_r2

    any_sig = any(
        min(r.oos_ic_pval * N_BONFERRONI, 1.0) < ALPHA_ADJ and r.oos_ic > 0
        for r in results if r.cv_type == "LODO"
    )

    print(f"\n  Best OOS IC: {best_ic:+.4f} ({best_desc})")
    print(f"  Best OOS R2: {best_r2:+.4f}")
    print(f"  Bonferroni threshold: {ALPHA_ADJ:.4f} (K={N_BONFERRONI})")
    print(f"  Any significant after Bonferroni: {any_sig}")

    if any_sig and best_r2 > 0:
        print("\n  >>> EDGE DETECTED: Multi-factor combination shows significant OOS IC.")
    elif abs(best_ic) < 0.05 and best_r2 < 0.02:
        print("\n  >>> NO COMBINATION EDGE: OOS IC~0, R2~0 across all models/targets.")
        print("      Multi-factor combination does not find edge that single factors lack.")
    elif best_r2 < 0:
        print("\n  >>> NO EDGE (negative R2): Model predictions are worse than mean.")
    else:
        print("\n  >>> INCONCLUSIVE: Some signal but not significant after Bonferroni.")

    # Overfit detection
    for r in results:
        if r.cv_type == "LODO" and r.is_r2 > 0.05 and r.oos_r2 < 0:
            print(f"  OVERFIT SUSPECT: {r.model_name}/{r.target_name} "
                  f"IS R2={r.is_r2:.4f} >> OOS R2={r.oos_r2:.4f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
