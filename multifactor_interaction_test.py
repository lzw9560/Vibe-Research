#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-factor interaction test: can 2-3 factor combinations find selection edge
that single factors cannot? TARGET=premium(gap, D收→D+1开) + continuation(D+1开→D+4 path).

§44 v2 methodology: walk-forward LODO CV + OOS R²/IC + Bonferroni + no feature-selection bias.
Pre-registered interactions (no post-hoc adjustment):
  1. vol_surge × volatility  (量价齐高)
  2. boards × breakout       (连板+突破; substitute for boards×seal_amount — seal_amount unavailable for baseline dates)
  3. gene_score × volatility (高分股+波动)
  4. boards × vol_surge      (连板+量能)
Secondary: boards × seal_amount on extended sample (08-17+, where seal_amount exists).
"""
from __future__ import annotations
import json, sqlite3, sys, warnings
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np
from scipy.stats import spearmanr, pearsonr, mannwhitneyu
from sklearn.linear_model import LinearRegression

warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path("/Users/lizhiwei/project/code/stock/Vibe-Research")
sys.path.insert(0, str(ROOT / "backend"))
from strategies.kline_returns import simulate_holding  # noqa: E402

DATA = ROOT / ".vibe-research"

# ───────────────── helpers ─────────────────

def compute_d_features(bars: list[dict], d_idx: int) -> dict | None:
    """Compute D-day features (known at D close) from bars[d_idx] and prior bars.
    No look-ahead: only uses bars[0..d_idx]."""
    if d_idx < 20:
        return None
    d_bar = bars[d_idx]
    close_d = d_bar["close"]
    if not close_d or close_d <= 0:
        return None
    # momentum 5d: (D close - D-5 close) / D-5 close
    close_d5 = bars[d_idx - 5]["close"]
    momentum = (close_d - close_d5) / close_d5 if close_d5 else 0.0
    # vol_surge: D volume / mean(D-1..D-5 volume)
    vol_d = d_bar["volume"] or 0
    vols_prev = [bars[d_idx - j]["volume"] or 0 for j in range(1, 6)]
    avg_vol = sum(vols_prev) / 5 if vols_prev else 1
    vol_surge = vol_d / avg_vol if avg_vol else 0.0
    # volatility 5d: (max(D-4..D high) - min(D-4..D low)) / D close
    highs5 = [bars[d_idx - j]["high"] or 0 for j in range(5)]
    lows5 = [bars[d_idx - j]["low"] or 0 for j in range(5)]
    volat = (max(highs5) - min(lows5)) / close_d if close_d else 0.0
    # breakout 20d: 1 if D close >= 0.95 * max(D-20..D-1 high)
    highs_prev20 = [bars[d_idx - j]["high"] or 0 for j in range(1, 21)]
    max_high20 = max(highs_prev20) if highs_prev20 else 0
    breakout = 1 if (close_d >= 0.95 * max_high20 and max_high20) else 0
    # ma_align: 1 if ma5 > ma10 > ma20 (using D and prior)
    closes20 = [bars[d_idx - j]["close"] for j in range(20)]
    ma5 = sum(closes20[:5]) / 5
    ma10 = sum(closes20[:10]) / 10
    ma20 = sum(closes20) / 20
    ma_align = 1 if ma5 > ma10 > ma20 else 0
    return {"momentum": momentum, "vol_surge": vol_surge, "volatility": volat,
            "breakout": breakout, "ma_align": ma_align}


def compute_pe(code: str, d_close: float, d_date: str, pd_cache: dict) -> float | None:
    """PE = D close / epsTTM (most recent quarter published before D)."""
    quarters = pd_cache.get(code)
    if not quarters or not d_close or d_close <= 0:
        return None
    best_eps = None
    best_pub = ""
    for q, info in quarters.items():
        pub = info.get("pubDate", "")
        eps = info.get("epsTTM")
        if eps and pub and pub <= d_date and pub > best_pub:
            best_pub = pub
            best_eps = eps
    if best_eps and best_eps > 0:
        return d_close / best_eps
    return None


def rank_normalize(arr: np.ndarray) -> np.ndarray:
    """Rank-normalize to [0,1] — robust to outliers, no distributional assumption."""
    from scipy.stats import rankdata
    r = rankdata(arr, method="average")
    return (r - 1) / max(len(r) - 1, 1)


def lodo_cv_lift(df: list[dict], f1: str, f2: str, target: str,
                 n_tercile: int = 3) -> dict:
    """Leave-one-day-out CV: interaction lift (top-tercile-both vs all).

    On each train fold (13 days), compute tercile thresholds for f1 and f2.
    Top interaction group = top tercile of BOTH. Apply to test fold (1 day).
    Returns pooled OOS metrics.
    """
    dates = sorted(set(r["date"] for r in df))
    all_test_preds = []  # (predicted_group, actual_target) pooled
    daily_lifts = []
    daily_ic_simple = []  # simple interaction score IC
    daily_ic_ols = []
    daily_r2_ols = []
    n_top_total = 0
    n_test_total = 0

    for test_date in dates:
        train = [r for r in df if r["date"] != test_date]
        test = [r for r in df if r["date"] == test_date]
        if len(test) < 5:
            continue

        # Tercile thresholds from TRAIN (no leakage)
        f1_train = np.array([r[f1] for r in train if r[f1] is not None])
        f2_train = np.array([r[f2] for r in train if r[f2] is not None])
        if len(f1_train) < 10 or len(f2_train) < 10:
            continue
        f1_thr = np.percentile(f1_train, 66.67)
        f2_thr = np.percentile(f2_train, 66.67)

        # Apply to TEST
        test_targets = []
        test_groups = []  # 1 = top interaction, 0 = rest
        test_scores_simple = []  # rank(f1)*rank(f2)
        test_scores_ols_pred = []
        for r in test:
            v1, v2 = r.get(f1), r.get(f2)
            if v1 is None or v2 is None:
                continue
            tgt = r.get(target)
            if tgt is None:
                continue
            test_targets.append(tgt)
            is_top = 1 if (v1 >= f1_thr and v2 >= f2_thr) else 0
            test_groups.append(is_top)
            n_top_total += is_top
            n_test_total += 1

        if not test_targets:
            continue

        test_targets = np.array(test_targets)
        test_groups = np.array(test_groups)

        # Lift: mean premium of top group / mean premium of all test
        all_mean = np.mean(test_targets)
        top_mask = test_groups == 1
        if top_mask.sum() > 0 and all_mean != 0:
            top_mean = np.mean(test_targets[top_mask])
            lift = top_mean / all_mean if all_mean != 0 else 0
            daily_lifts.append(lift)
        else:
            daily_lifts.append(1.0)  # no top group → neutral

        # Simple interaction IC: score = rank(f1)*rank(f2) on test
        f1_test = np.array([r[f1] for r in test if r.get(f1) is not None and r.get(target) is not None])
        f2_test = np.array([r[f2] for r in test if r.get(f2) is not None and r.get(target) is not None])
        # Align with test_targets
        valid = [(r[f1], r[f2], r[target]) for r in test if r.get(f1) is not None and r.get(f2) is not None and r.get(target) is not None]
        if len(valid) >= 5:
            v1_arr = np.array([x[0] for x in valid])
            v2_arr = np.array([x[1] for x in valid])
            tgt_arr = np.array([x[2] for x in valid])
            r1 = rank_normalize(v1_arr)
            r2 = rank_normalize(v2_arr)
            simple_score = r1 * r2
            if np.std(simple_score) > 0 and np.std(tgt_arr) > 0:
                ic_s, p_s = spearmanr(simple_score, tgt_arr)
                daily_ic_simple.append(ic_s)

            # OLS with interaction: fit on train, predict test
            train_valid = [(rr[f1], rr[f2], rr[target]) for rr in train
                           if rr.get(f1) is not None and rr.get(f2) is not None and rr.get(target) is not None]
            if len(train_valid) >= 10:
                X_train = np.column_stack([
                    np.array([x[0] for x in train_valid]),
                    np.array([x[1] for x in train_valid]),
                    np.array([x[0] * x[1] for x in train_valid]),  # interaction
                ])
                y_train = np.array([x[2] for x in train_valid])
                X_test = np.column_stack([v1_arr, v2_arr, v1_arr * v2_arr])
                try:
                    reg = LinearRegression().fit(X_train, y_train)
                    pred_test = reg.predict(X_test)
                    if np.std(pred_test) > 0 and np.std(tgt_arr) > 0:
                        ic_o, _ = spearmanr(pred_test, tgt_arr)
                        daily_ic_ols.append(ic_o)
                        ss_res = np.sum((tgt_arr - pred_test) ** 2)
                        ss_tot = np.sum((tgt_arr - np.mean(tgt_arr)) ** 2)
                        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                        daily_r2_ols.append(r2)
                except Exception:
                    pass

        # Pool for OOS
        for i, (grp, tgt) in enumerate(zip(test_groups, test_targets)):
            all_test_preds.append((grp, tgt))

    # Aggregate
    all_arr = np.array([(g, t) for g, t in all_test_preds])
    if len(all_arr) == 0:
        return {"n": 0}

    # Pooled lift
    pooled_all_mean = np.mean(all_arr[:, 1].astype(float))
    top_mask = all_arr[:, 0].astype(int) == 1
    pooled_top_mean = np.mean(all_arr[top_mask, 1].astype(float)) if top_mask.sum() > 0 else 0
    pooled_lift = pooled_top_mean / pooled_all_mean if pooled_all_mean != 0 else 0
    pooled_net_lift = pooled_lift - 1

    # Permutation test for pooled lift (1000 shuffles)
    rng = np.random.default_rng(42)
    n_perms = 1000
    perm_lifts = []
    targets = all_arr[:, 1].astype(float)
    groups = all_arr[:, 0].astype(int)
    for _ in range(n_perms):
        perm_groups = rng.permutation(groups)
        pm = perm_groups == 1
        if pm.sum() > 0 and pooled_all_mean != 0:
            perm_lifts.append(np.mean(targets[pm]) / pooled_all_mean)
    perm_lifts = np.array(perm_lifts)
    p_value = (perm_lifts >= pooled_lift).sum() / n_perms if pooled_lift > 1 else (perm_lifts <= pooled_lift).sum() / n_perms

    return {
        "n": n_test_total,
        "n_top": n_top_total,
        "pct_top": n_top_total / max(n_test_total, 1),
        "pooled_lift": pooled_lift,
        "pooled_net_lift": pooled_net_lift,
        "perm_p_value": p_value,
        "perm_lift_mean": float(np.mean(perm_lifts)) if len(perm_lifts) else 0,
        "perm_lift_p95": float(np.percentile(perm_lifts, 95)) if len(perm_lifts) else 0,
        "daily_lift_mean": float(np.mean(daily_lifts)) if daily_lifts else 0,
        "daily_lift_std": float(np.std(daily_lifts)) if daily_lifts else 0,
        "daily_ic_simple_mean": float(np.mean(daily_ic_simple)) if daily_ic_simple else 0,
        "daily_ic_simple_std": float(np.std(daily_ic_simple)) if daily_ic_simple else 0,
        "daily_ic_ols_mean": float(np.mean(daily_ic_ols)) if daily_ic_ols else 0,
        "daily_ic_ols_std": float(np.std(daily_ic_ols)) if daily_ic_ols else 0,
        "daily_r2_ols_mean": float(np.mean(daily_r2_ols)) if daily_r2_ols else 0,
        "daily_r2_ols_std": float(np.std(daily_r2_ols)) if daily_r2_ols else 0,
        "n_ic_days": len(daily_ic_simple),
    }


def single_factor_ic(df: list[dict], factor: str, target: str) -> dict:
    """Single-factor OOS IC via LODO CV (for comparison baseline)."""
    dates = sorted(set(r["date"] for r in df))
    ics = []
    for test_date in dates:
        test = [r for r in df if r["date"] == test_date]
        valid = [(r[factor], r[target]) for r in test if r.get(factor) is not None and r.get(target) is not None]
        if len(valid) < 5:
            continue
        arr_f = np.array([x[0] for x in valid])
        arr_t = np.array([x[1] for x in valid])
        if np.std(arr_f) > 0 and np.std(arr_t) > 0:
            ic, _ = spearmanr(arr_f, arr_t)
            ics.append(ic)
    return {
        "factor": factor,
        "ic_mean": float(np.mean(ics)) if ics else 0,
        "ic_std": float(np.std(ics)) if ics else 0,
        "n_days": len(ics),
    }


# ───────────────── build feature matrix ─────────────────

def build_matrix() -> list[dict]:
    print("Loading data...")
    with open(DATA / "first_board_premium_baseline.json") as f:
        bl = json.load(f)
    samples = bl["samples"]

    with open(DATA / "baostock_kline_cache.json") as f:
        kline = json.load(f)

    with open(DATA / "ths_lb_cache.json") as f:
        lb = json.load(f)
    boards_map = {}
    for d, lst in lb.items():
        for x in lst:
            boards_map[(d, x["code"])] = x.get("boards", 1)

    with open(DATA / "profit_data_cache.json") as f:
        pd_cache = json.load(f)

    conn = sqlite3.connect(str(DATA / "gene_scores.db"), timeout=10)
    gs_lookup = {}
    for r in conn.execute(
        "SELECT date, code, total_score FROM gene_scores WHERE data_source='eastmoney_live'"
    ).fetchall():
        gs_lookup[(r[0], r[1])] = r[2]
    conn.close()

    print("Building feature matrix...")
    matrix = []
    n_cont = 0
    for s in samples:
        code = s["code"]
        d_date = s["date"]
        d_close = float(s["t_close"])
        premium = float(s["premium"])

        # D-day features from kline
        bars = kline.get(code, [])
        d_idx = None
        for i, b in enumerate(bars):
            if b["date"] == d_date:
                d_idx = i
                break
        if d_idx is None or d_idx < 20:
            continue
        feats = compute_d_features(bars, d_idx)
        if feats is None:
            continue

        # gene_score (known at D: uses涨停 data up to D-1)
        gene_score = gs_lookup.get((d_date, code), 0.0)

        # boards
        d_nodash = d_date.replace("-", "")
        boards = boards_map.get((d_nodash, code), 1)

        # PE
        pe = compute_pe(code, d_close, d_date, pd_cache)

        # continuation: simulate_holding D+1 open → D+4
        sim = simulate_holding(bars, d_date, -3.0, 8.0, 3)
        cont = sim["return_pct"] if sim else None
        if cont is not None:
            n_cont += 1

        matrix.append({
            "date": d_date,
            "code": code,
            "premium": premium,
            "continuation": cont,
            "gene_score": float(gene_score),
            "vol_surge": feats["vol_surge"],
            "volatility": feats["volatility"],
            "momentum": feats["momentum"],
            "breakout": float(feats["breakout"]),
            "ma_align": float(feats["ma_align"]),
            "boards": float(boards),
            "pe": pe,
        })

    print(f"Matrix: N={len(matrix)}, continuation available: {n_cont}")
    return matrix


# ───────────────── main ─────────────────

def main() -> int:
    matrix = build_matrix()

    # Filter for premium analysis (all have premium)
    df_prem = [r for r in matrix if r["premium"] is not None]
    # Filter for continuation analysis
    df_cont = [r for r in matrix if r["continuation"] is not None]

    # Pre-registered interactions
    interactions = [
        ("vol_surge", "volatility", "量价齐高"),
        ("boards", "breakout", "连板+突破(substitute for boards×seal_amount)"),
        ("gene_score", "volatility", "高分股+波动"),
        ("boards", "vol_surge", "连板+量能"),
    ]

    K = len(interactions)
    alpha_bonf = 0.05 / K

    print("\n" + "=" * 80)
    print("TARGET 1: PREMIUM (gap, D收→D+1开)")
    print(f"N={len(df_prem)}, 14 days, LODO CV, Bonferroni α={alpha_bonf:.4f} (K={K})")
    print("=" * 80)

    # Premium stats
    prem_arr = np.array([r["premium"] for r in df_prem])
    print(f"Premium: mean={np.mean(prem_arr):.4f}% median={np.median(prem_arr):.4f}% "
          f"std={np.std(prem_arr):.4f}% win_rate={np.mean(prem_arr > 0)*100:.1f}%")

    # Single-factor IC baseline
    print("\n--- Single-factor IC (premiu) baseline ---")
    for f in ["gene_score", "vol_surge", "volatility", "momentum", "breakout", "boards", "pe"]:
        df_f = [r for r in df_prem if r.get(f) is not None]
        if len(df_f) < 100:
            print(f"  {f:12s}: N={len(df_f)} (insufficient)")
            continue
        sf = single_factor_ic(df_f, f, "premium")
        print(f"  {f:12s}: IC={sf['ic_mean']:+.4f} ± {sf['ic_std']:.4f} (n_days={sf['n_days']})")

    # Interaction tests
    print("\n--- Pre-registered interaction tests (premium) ---")
    print(f"{'Interaction':<45s} {'Lift':>7s} {'NetLift':>8s} {'PermP':>7s} {'ICsimp':>8s} {'ICols':>8s} {'R²ols':>8s} {'Verdict':>10s}")
    print("-" * 110)
    results_prem = []
    for f1, f2, label in interactions:
        df_i = [r for r in df_prem if r.get(f1) is not None and r.get(f2) is not None]
        if len(df_i) < 100:
            print(f"  {label}: N={len(df_i)} (insufficient)")
            continue
        res = lodo_cv_lift(df_i, f1, f2, "premium")
        results_prem.append((label, f1, f2, res))
        sig = "***" if res["perm_p_value"] < alpha_bonf else ("*" if res["perm_p_value"] < 0.05 else "ns")
        verdict = "EDGE" if (res["perm_p_value"] < alpha_bonf and res["pooled_net_lift"] > 0.1) else "no_edge"
        print(f"  {label:<43s} {res['pooled_lift']:7.3f} {res['pooled_net_lift']:+8.4f} "
              f"{res['perm_p_value']:7.3f}{sig} {res['daily_ic_simple_mean']:+8.4f} "
              f"{res['daily_ic_ols_mean']:+8.4f} {res['daily_r2_ols_mean']:+8.4f} {verdict:>10s}")
        print(f"    n={res['n']} n_top={res['n_top']} ({res['pct_top']*100:.1f}%) "
              f"perm_lift_mean={res['perm_lift_mean']:.3f} perm_p95={res['perm_lift_p95']:.3f} "
              f"n_ic_days={res['n_ic_days']}")

    # ── TARGET 2: CONTINUATION ──
    print("\n" + "=" * 80)
    print("TARGET 2: CONTINUATION (simulate_holding D+1开→D+4, SL=-3% TP=+8% max_hold=3d)")
    print(f"N={len(df_cont)}, LODO CV")
    print("=" * 80)

    cont_arr = np.array([r["continuation"] for r in df_cont])
    print(f"Continuation: mean={np.mean(cont_arr):.4f}% median={np.median(cont_arr):.4f}% "
          f"std={np.std(cont_arr):.4f}% win_rate={np.mean(cont_arr > 0)*100:.1f}%")

    print("\n--- Single-factor IC (continuation) baseline ---")
    for f in ["gene_score", "vol_surge", "volatility", "momentum", "breakout", "boards", "pe"]:
        df_f = [r for r in df_cont if r.get(f) is not None]
        if len(df_f) < 100:
            continue
        sf = single_factor_ic(df_f, f, "continuation")
        print(f"  {f:12s}: IC={sf['ic_mean']:+.4f} ± {sf['ic_std']:.4f} (n_days={sf['n_days']})")

    print("\n--- Pre-registered interaction tests (continuation) ---")
    print(f"{'Interaction':<45s} {'Lift':>7s} {'NetLift':>8s} {'PermP':>7s} {'ICsimp':>8s} {'ICols':>8s} {'R²ols':>8s} {'Verdict':>10s}")
    print("-" * 110)
    for f1, f2, label in interactions:
        df_i = [r for r in df_cont if r.get(f1) is not None and r.get(f2) is not None]
        if len(df_i) < 100:
            continue
        res = lodo_cv_lift(df_i, f1, f2, "continuation")
        sig = "***" if res["perm_p_value"] < alpha_bonf else ("*" if res["perm_p_value"] < 0.05 else "ns")
        verdict = "EDGE" if (res["perm_p_value"] < alpha_bonf and res["pooled_net_lift"] > 0.1) else "no_edge"
        print(f"  {label:<43s} {res['pooled_lift']:7.3f} {res['pooled_net_lift']:+8.4f} "
              f"{res['perm_p_value']:7.3f}{sig} {res['daily_ic_simple_mean']:+8.4f} "
              f"{res['daily_ic_ols_mean']:+8.4f} {res['daily_r2_ols_mean']:+8.4f} {verdict:>10s}")

    # ── SECONDARY: boards × seal_amount on extended sample ──
    print("\n" + "=" * 80)
    print("SECONDARY: boards × seal_amount (extended sample, 08-17+ where seal_amount exists)")
    print("=" * 80)
    try:
        secondary_seal_amount(matrix)
    except Exception as e:
        print(f"  Secondary analysis failed: {e}")
        import traceback; traceback.print_exc()

    return 0


def secondary_seal_amount(matrix):
    """Test boards×seal_amount on extended dates (08-17+) where seal_amount is available."""
    with open(DATA / "zt_pool_hist_cache.json") as f:
        zt_hist = json.load(f)
    with open(DATA / "ths_lb_cache.json") as f:
        lb = json.load(f)
    with open(DATA / "baostock_kline_cache.json") as f:
        kline = json.load(f)

    # Build extended sample: dates where seal_amount exists (08-17+)
    # AND kline has D+1 bar (D+1 <= 09-04, so D <= ~08-31)
    seal_dates = sorted([d for d, v in zt_hist.items() if len(v) > 0])
    # Only dates where we can compute D+1 premium (kline goes to 09-04)
    # D+1 must be in kline, so D <= 09-03
    extended = []
    for d_nodash in seal_dates:
        # Convert to date string
        d_date = f"{d_nodash[:4]}-{d_nodash[4:6]}-{d_nodash[6:]}"
        zt_list = zt_hist[d_nodash]
        lb_codes = {x["code"]: x.get("boards", 1) for x in lb.get(d_nodash, [])}
        for z in zt_list:
            code = z["code"]
            seal = z.get("seal_amount")
            if seal is None:
                continue
            bars = kline.get(code, [])
            d_idx = None
            for i, b in enumerate(bars):
                if b["date"] == d_date:
                    d_idx = i
                    break
            if d_idx is None or d_idx < 20 or d_idx + 1 >= len(bars):
                continue
            d_close = bars[d_idx]["close"]
            d1_open = bars[d_idx + 1]["open"]
            if not d_close or not d1_open or d_close <= 0:
                continue
            premium = (d1_open - d_close) / d_close * 100
            boards = lb_codes.get(code, 1)
            feats = compute_d_features(bars, d_idx)
            if feats is None:
                continue
            extended.append({
                "date": d_date,
                "code": code,
                "premium": premium,
                "seal_amount": float(seal),
                "boards": float(boards),
                "vol_surge": feats["vol_surge"],
                "volatility": feats["volatility"],
            })

    print(f"  Extended sample: N={len(extended)}, dates={sorted(set(r['date'] for r in extended))}")
    if len(extended) < 50:
        print("  Insufficient for analysis")
        return

    prem_arr = np.array([r["premium"] for r in extended])
    print(f"  Premium: mean={np.mean(prem_arr):.4f}% median={np.median(prem_arr):.4f}% "
          f"win_rate={np.mean(prem_arr > 0)*100:.1f}%")
    print(f"  seal_amount: mean={np.mean([r['seal_amount'] for r in extended])/1e8:.2f}亿 "
          f"median={np.median([r['seal_amount'] for r in extended])/1e8:.2f}亿")

    # boards × seal_amount interaction
    res = lodo_cv_lift(extended, "boards", "seal_amount", "premium")
    sig = "***" if res["perm_p_value"] < alpha_bonf else ("*" if res["perm_p_value"] < 0.05 else "ns")
    verdict = "EDGE" if (res["perm_p_value"] < alpha_bonf and res["pooled_net_lift"] > 0.1) else "no_edge"
    print(f"  boards×seal_amount: Lift={res['pooled_lift']:.3f} NetLift={res['pooled_net_lift']:+.4f} "
          f"PermP={res['perm_p_value']:.3f}{sig} ICsimp={res['daily_ic_simple_mean']:+.4f} "
          f"ICols={res['daily_ic_ols_mean']:+.4f} R²ols={res['daily_r2_ols_mean']:+.4f} {verdict}")
    print(f"    n={res['n']} n_top={res['n_top']} ({res['pct_top']*100:.1f}%) "
          f"perm_lift_mean={res['perm_lift_mean']:.3f}")

    # Also single-factor for comparison
    sf_seal = single_factor_ic(extended, "seal_amount", "premium")
    sf_boards = single_factor_ic(extended, "boards", "premium")
    print(f"  single seal_amount IC={sf_seal['ic_mean']:+.4f} ± {sf_seal['ic_std']:.4f}")
    print(f"  single boards     IC={sf_boards['ic_mean']:+.4f} ± {sf_boards['ic_std']:.4f}")


K = 4
alpha_bonf = 0.05 / K

if __name__ == "__main__":
    raise SystemExit(main())
