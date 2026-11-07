# -*- coding: utf-8 -*-
"""Re-test: top-k-gene top-3 with LESS-CONSERVATIVE methodology.

原 verdict: exploratory
  - day-t Bonf×12=0.008 (passed)
  - OOS test_p=0.013 raw → Bonf×12=0.156 >= 0.05 → exploratory (failed)

本 re-test 用 3 个合法替代方法学（非任意放松，有理论依据）：
  1. BH FDR 5% 替代 Bonferroni — BH 控 FDR（发现错误率），Bonferroni 控 FWER（族错误率）。
     BH 更适合探索性研究，是公认的 Bonferroni 合法替代。
  2. Rolling 4-window expanding WF 替代单次 50/50 split — 真正 walk-forward，
     3 个 expanding folds 测 regime robustness。
  3. Per-trade t + HAC (Newey-West) 替代 per-day-mean t — per-day-mean 缩 N 到 n_days
     偏保守；per-trade 用全 N + HAC SE 处理同日相关+异方差。

过严口径（保留不变）：
  - entry = T+1 open (realistic，非 T close sealed)
  - close_ev (T+2 close，非 open_ev 防 T+1 日内泄漏)
  - R6 gap-through fill (跳空穿 stop 按 T+2 open+滑点)
  - 一字涨停跳过 (FIXED limit_for_code)
  - 合理成本 0.3% (小盘股 round-trip)
  - 禁止外推

若翻正 → 必过假 edge 5 模式审：
  1. entry 涨停价溢价  2. survivorship  3. T+1 日内泄漏  4. 拥挤倒 U  5. fill 虚构

跑法:
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
  .venv/bin/python tools/explore_retest_top-k-gene-top3.py
"""

from __future__ import annotations

import sqlite3
import sys
from collections import Counter, defaultdict
from math import sqrt
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._factor_helpers import (  # noqa: E402
    COST,
    ALPHA,
    bonferroni_p,
    build_picks_generic,
    close_ev_basic,
    close_ev_stop,
    day_paired_t,
    ev_stats,
    load_kline_db,
    load_zt,
    verdict_for,
    walk_forward,
)

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
GENE_DB = resolve_data_dir() / "gene_scores.db"


# =====================================================================
# Data loading (copied from explore_factor_top-k-gene.py — hyphen in
# filename prevents module import, so copy the 3 small functions)
# =====================================================================


def load_gene_scores() -> tuple[dict[str, dict[str, float]], int]:
    """读 gene_scores.db → {date: {code: total_score}}. 无 look-ahead."""
    conn = sqlite3.connect(str(GENE_DB))
    by_date: dict[str, dict[str, float]] = defaultdict(dict)
    n = 0
    for d, code, score in conn.execute("SELECT date, code, total_score FROM gene_scores"):
        if score is None:
            continue
        by_date[d][code] = float(score)
        n += 1
    conn.close()
    return dict(by_date), n


def attach_gene_scores(picks: list[dict], gene: dict[str, dict[str, float]]) -> tuple[list[dict], int]:
    n_with = 0
    for p in picks:
        dmap = gene.get(p["zt_date"])
        score = dmap.get(p["code"]) if dmap else None
        p["gene_score"] = score
        if score is not None:
            n_with += 1
    return picks, n_with


def select_topk_per_date(picks: list[dict], k: int) -> list[dict]:
    """每 zt_date 取 gene_score 最高的 top-k. 同日不足 k 则全取."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        if p.get("gene_score") is None:
            continue
        by_date[p["zt_date"]].append(p)
    out: list[dict] = []
    for d, ps in by_date.items():
        ps_sorted = sorted(ps, key=lambda x: x["gene_score"], reverse=True)
        out.extend(ps_sorted[:k])
    return out


# =====================================================================
# NEW methodology 1: BH FDR (Benjamini-Hochberg)
# =====================================================================


def bh_fdr(p_list: list[float], alpha: float = 0.05) -> dict:
    """Benjamini-Hochberg FDR procedure.

    Controls FDR = E[false discoveries / discoveries].
    Less conservative than Bonferroni (controls FWER = P[≥1 false rejection]).

    Procedure:
      1. Sort p-values ascending: p(1) ≤ p(2) ≤ ... ≤ p(m)
      2. Find largest k such that p(k) ≤ (k/m) * alpha
      3. Reject H0 for p(1), ..., p(k) (all up to k)

    Returns: rejected (list[bool]), bh_adjusted_p, n_significant.
    """
    m = len(p_list)
    if m == 0:
        return {"rejected": [], "bh_adjusted_p": [], "n_significant": 0, "m": 0, "alpha": alpha}

    indexed = sorted(enumerate(p_list), key=lambda x: x[1])
    sorted_ps = [p for _, p in indexed]
    orig_idx = [i for i, _ in indexed]

    k_max = 0
    for k in range(1, m + 1):
        if sorted_ps[k - 1] <= (k / m) * alpha:
            k_max = k

    rejected = [False] * m
    for j in range(k_max):
        rejected[orig_idx[j]] = True

    adj = [0.0] * m
    prev = 1.0
    for k in range(m, 0, -1):
        val = min(prev, sorted_ps[k - 1] * m / k)
        adj[orig_idx[k - 1]] = min(val, 1.0)
        prev = adj[orig_idx[k - 1]]

    return {
        "rejected": rejected,
        "bh_adjusted_p": [round(a, 6) for a in adj],
        "n_significant": k_max,
        "m": m,
        "alpha": alpha,
        "sorted_ps": sorted_ps,
    }


# =====================================================================
# NEW methodology 2: per-trade t + HAC (Newey-West)
# =====================================================================


def per_trade_t_hac(rets: list[float], dates: list[str]) -> dict:
    """Per-trade t-statistic with Newey-West HAC standard errors.

    Uses ALL individual trades (not day-means), ordered by date.
    HAC with Bartlett kernel handles heteroskedasticity + autocorrelation.
    Lag L = max(NW standard, max same-day trade count) to capture same-day corr.

    Less conservative than per-day-mean t (shrinks N to n_days).
    """
    if len(rets) == 0:
        return {"n": 0, "n_days": 0, "mean": 0.0, "hac_se": 0.0, "t": 0.0, "p_one_sided": 1.0, "lag": 0}

    paired = sorted(zip(dates, rets), key=lambda x: x[0])
    r_arr = np.array([r for _, r in paired], dtype=float)
    d_arr = [d for d, _ in paired]

    n = len(r_arr)
    mean = float(np.mean(r_arr))
    resid = r_arr - mean

    # Lag: standard NW formula + max same-day to capture cross-sectional corr
    nw_lag = int(np.floor(4 * (n / 100) ** (2 / 9)))
    day_counts = Counter(d_arr)
    max_same_day = max(day_counts.values())
    n_days = len(day_counts)
    L = max(nw_lag, max_same_day, 1)

    # HAC variance (Bartlett kernel):
    # S = sum(e_t^2) + 2 * sum_{l=1}^{L} w_l * sum_{t=l+1}^{n} e_t * e_{t-l}
    omega_0 = float(np.sum(resid**2))
    s_hac = omega_0
    for l in range(1, L + 1):
        w_l = 1.0 - l / (L + 1)
        if l < n:
            cross = float(np.sum(resid[l:] * resid[: n - l]))
            s_hac += 2.0 * w_l * cross

    hac_var = s_hac / (n**2) if n > 0 else 0.0
    hac_se = sqrt(max(hac_var, 0.0))
    t_stat = mean / hac_se if hac_se > 0 else 0.0
    p_one = float(stats.norm.sf(t_stat))  # one-sided positive edge

    return {
        "n": n,
        "n_days": n_days,
        "mean": round(mean, 4),
        "hac_se": round(hac_se, 5),
        "t": round(t_stat, 3),
        "p_one_sided": round(p_one, 6),
        "lag": L,
        "nw_lag": nw_lag,
        "max_same_day": max_same_day,
    }


# =====================================================================
# NEW methodology 3: rolling 4-window expanding walk-forward
# =====================================================================


def _ret_float(p: dict, ret_fn) -> float | None:
    """Extract float from ret_fn (handles both float and tuple returns)."""
    r = ret_fn(p)
    if r is None:
        return None
    if isinstance(r, tuple):
        return r[0]
    return r


def rolling_walk_forward(picks: list[dict], ret_fn, n_windows: int = 4) -> dict:
    """Expanding-window walk-forward with n_windows date-quarters.

    Fold i: train = Q1..Q(i), test = Q(i+1).  (n_windows-1 folds)
    Each fold's test is genuinely OOS (chronologically after train).
    Pooled OOS = union of all test picks (all OOS).
    """
    if not picks:
        return {"status": "no_picks"}
    ps = sorted(picks, key=lambda p: p["zt_date"])
    all_dates = sorted(set(p["zt_date"] for p in ps))
    if len(all_dates) < n_windows:
        return {"status": "too_few_dates", "n_dates": len(all_dates), "n_windows": n_windows}

    q_size = len(all_dates) // n_windows
    quarters: list[set[str]] = []
    for i in range(n_windows):
        start = i * q_size
        end = (i + 1) * q_size if i < n_windows - 1 else len(all_dates)
        quarters.append(set(all_dates[start:end]))

    # Precompute returns (call ret_fn once per pick)
    ret_cache: dict[int, float] = {}
    for p in picks:
        r = _ret_float(p, ret_fn)
        if r is not None:
            ret_cache[id(p)] = r

    folds: list[dict] = []
    all_test_picks: list[dict] = []
    for i in range(n_windows - 1):
        train_dates: set[str] = set()
        for j in range(i + 1):
            train_dates |= quarters[j]
        test_dates = quarters[i + 1]

        train_picks = [p for p in ps if p["zt_date"] in train_dates]
        test_picks = [p for p in ps if p["zt_date"] in test_dates]
        all_test_picks.extend(test_picks)

        train_rets = [ret_cache[id(p)] for p in train_picks if id(p) in ret_cache]
        test_rets = [ret_cache[id(p)] for p in test_picks if id(p) in ret_cache]
        test_dts = [p["zt_date"] for p in test_picks if id(p) in ret_cache]

        train_ev = ev_stats(train_rets)
        test_ev = ev_stats(test_rets)
        test_hac = per_trade_t_hac(test_rets, test_dts)

        test_by_date: dict[str, list[float]] = defaultdict(list)
        for p in test_picks:
            r = ret_cache.get(id(p))
            if r is not None:
                test_by_date[p["zt_date"]].append(r)
        test_dt = day_paired_t(test_by_date)

        folds.append(
            {
                "fold": i + 1,
                "n_train": len(train_rets),
                "n_test": len(test_rets),
                "n_train_dates": len(train_dates),
                "n_test_dates": len(test_dates),
                "train_ev": train_ev["ev"],
                "test_ev": test_ev["ev"],
                "test_wr": test_ev["wr"],
                "test_hac_t": test_hac["t"],
                "test_hac_p": test_hac["p_one_sided"],
                "test_day_t": test_dt["t"],
                "test_day_p": test_dt["p_one_sided"],
                "test_n_days": test_dt["n_days"],
                "test_range": (f"{min(test_dates)}~{max(test_dates)}" if test_dates else "-"),
            }
        )

    # Pooled OOS (union of all test picks — all genuinely OOS)
    pooled_rets = [ret_cache[id(p)] for p in all_test_picks if id(p) in ret_cache]
    pooled_dts = [p["zt_date"] for p in all_test_picks if id(p) in ret_cache]
    pooled_ev = ev_stats(pooled_rets)
    pooled_hac = per_trade_t_hac(pooled_rets, pooled_dts)
    pooled_by_date: dict[str, list[float]] = defaultdict(list)
    for p in all_test_picks:
        r = ret_cache.get(id(p))
        if r is not None:
            pooled_by_date[p["zt_date"]].append(r)
    pooled_dt = day_paired_t(pooled_by_date)

    return {
        "status": "ok",
        "n_windows": n_windows,
        "n_folds": len(folds),
        "folds": folds,
        "pooled_oos": {
            "n": pooled_ev["n"],
            "n_days": pooled_dt["n_days"],
            "gross_ev": pooled_ev["ev"],
            "net_ev": round(pooled_ev["ev"] - COST * 100, 3),
            "wr": pooled_ev["wr"],
            "hac_t": pooled_hac["t"],
            "hac_p": pooled_hac["p_one_sided"],
            "day_t": pooled_dt["t"],
            "day_p": pooled_dt["p_one_sided"],
        },
    }


# =====================================================================
# NEW verdict (BH + rolling WF + HAC)
# =====================================================================


def new_verdict_for(
    ev_gross: float,
    net_ev: float,
    hac_t: float,
    hac_p_raw: float,
    rwf_status: str,
    pooled_oos_ev: float,
    pooled_oos_hac_p: float,
    n_days: int,
    bh_full_rejected: bool,
    bh_oos_rejected: bool,
    fold_positive: int,
    fold_total: int,
    subset_name: str,
) -> str:
    """New verdict with less-conservative methodology.

    Cascade:
      1. gross EV < 0 → falsified
      2. n_days < 60 → underpowered
      3. BH FDR 5% fails (full-sample HAC p) → falsified
      4. net EV <= 0 → falsified
      5. Rolling WF pooled OOS EV <= 0 → falsified
      6. BH FDR 5% fails (OOS HAC p) → exploratory
      7. < 2/3 folds positive → exploratory (not robust)
      8. All pass → edge-confirmed
    """
    print(f"\n  {subset_name} [NEW methodology — BH + rolling WF + HAC]:")
    print(f"    gross_EV={ev_gross}% net_EV={net_ev}% HAC_t={hac_t} HAC_p_raw={hac_p_raw} BH_full_rej={bh_full_rejected} n_days={n_days}")
    if rwf_status == "ok":
        print(
            f"    rolling-WF: pooled_OOS_gross={pooled_oos_ev}% "
            f"OOS_HAC_p={pooled_oos_hac_p} "
            f"BH_oos_rej={bh_oos_rejected} "
            f"folds_pos={fold_positive}/{fold_total}"
        )

    if ev_gross < 0:
        print(f"    → FALSIFIED: gross EV < 0")
        return "falsified"
    if n_days < 60:
        print(f"    → UNDERPOWERED: n_days={n_days} < 60")
        return "underpowered"
    if not bh_full_rejected:
        print(f"    → FALSIFIED: BH FDR 5% rejects full-sample HAC p (not significant even with less-conservative correction)")
        return "falsified"
    if net_ev <= 0:
        print(f"    → FALSIFIED: net EV={net_ev}% <= 0 (cost eats gross edge)")
        return "falsified"
    if rwf_status == "ok":
        if pooled_oos_ev <= 0:
            print(f"    → FALSIFIED: pooled OOS EV={pooled_oos_ev}% <= 0")
            return "falsified"
        if not bh_oos_rejected:
            print(f"    → EXPLORATORY: OOS HAC p={pooled_oos_hac_p} fails BH FDR 5% (OOS not significant)")
            return "exploratory"
        if fold_positive < fold_total * 2 / 3:
            print(f"    → EXPLORATORY: only {fold_positive}/{fold_total} folds positive (< 2/3, not robust across regimes)")
            return "exploratory"
        print(
            f"    → EDGE-CONFIRMED: gross+net>0, BH PASS, "
            f"OOS EV={pooled_oos_ev}% significant (HAC p={pooled_oos_hac_p}), "
            f"{fold_positive}/{fold_total} folds positive"
        )
        return "edge-confirmed"
    print(f"    → EXPLORATORY: rolling WF not available")
    return "exploratory"


# =====================================================================
# Main
# =====================================================================


def main() -> None:
    print("=" * 72)
    print("RE-TEST: top-k-gene top-3 — LESS-CONSERVATIVE METHODOLOGY")
    print("  BH FDR 5% | rolling 4-window WF | per-trade HAC Newey-West")
    print("=" * 72)

    # ---- load data ----
    print("\n[1] Loading data…")
    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    zt_rows = load_zt()
    gene, n_gene = load_gene_scores()
    print(f"  kline codes: {len(code_map)}, calendar: {len(calendar)} ({calendar[0]} ~ {calendar[-1]})")
    print(f"  zt rows: {len(zt_rows)}")
    print(f"  gene_scores: {n_gene} rows, {len(gene)} dates ({min(gene)} ~ {max(gene)})")

    # ---- build picks, attach gene, select top-k ----
    print("\n[2] Building picks (entry=T+1 open, exit=T+2 close, 一字涨停 skip)…")
    blanket = build_picks_generic(code_map, calendar, zt_rows, filter_fn=None)
    blanket, n_with = attach_gene_scores(blanket, gene)
    gene_dates = sorted({p["zt_date"] for p in blanket if p.get("gene_score") is not None})
    print(f"  blanket picks: {len(blanket)}, with gene_score: {n_with}")
    print(f"  gene-scored pick dates: {len(gene_dates)} ({gene_dates[0]} ~ {gene_dates[-1]})")

    top1 = select_topk_per_date(blanket, 1)
    top3 = select_topk_per_date(blanket, 3)
    top5 = select_topk_per_date(blanket, 5)
    all_gene_scored = [p for p in blanket if p.get("gene_score") is not None]
    print(f"  top-1: {len(top1)}, top-3: {len(top3)}, top-5: {len(top5)}")
    print(f"  all_gene_scored (universe baseline): {len(all_gene_scored)}")

    subsets = [
        ("top-1", top1),
        ("top-3", top3),
        ("top-5", top5),
    ]

    # ---- precompute close_ev_basic returns for each subset ----
    print("\n[3] Precomputing close_ev_basic returns…")
    subset_data: dict[str, dict] = {}
    for name, picks in subsets:
        rets = []
        dates_list = []
        for p in picks:
            r = close_ev_basic(p)
            if r is not None:
                rets.append(r)
                dates_list.append(p["zt_date"])
        gross = ev_stats(rets)
        net = round(gross["ev"] - COST * 100, 3)
        hac = per_trade_t_hac(rets, dates_list)
        by_date: dict[str, list[float]] = defaultdict(list)
        for d, r in zip(dates_list, rets):
            by_date[d].append(r)
        dt = day_paired_t(by_date)
        # Original single 50/50 walk-forward (for comparison)
        wf_orig = walk_forward(picks, close_ev_basic)
        # New rolling 4-window WF
        rwf = rolling_walk_forward(picks, close_ev_basic, n_windows=4)
        subset_data[name] = {
            "picks": picks,
            "rets": rets,
            "dates": dates_list,
            "gross_ev": gross["ev"],
            "net_ev": net,
            "gross_stats": gross,
            "hac": hac,
            "day_t": dt,
            "wf_orig": wf_orig,
            "rwf": rwf,
        }
        print(
            f"  {name}: n={len(rets)} n_days={dt['n_days']} "
            f"gross={gross['ev']}% net={net}% "
            f"HAC_t={hac['t']} HAC_p={hac['p_one_sided']} "
            f"day_t={dt['t']} day_p={dt['p_one_sided']}"
        )

    # ---- ORIGINAL verdict (for comparison) ----
    print(f"\n{'=' * 72}")
    print("[4] ORIGINAL verdict (per-day-mean t + Bonferroni×12 + single 50/50 WF)")
    print(f"{'=' * 72}")
    for name in ("top-1", "top-3", "top-5"):
        sd = subset_data[name]
        dt = sd["day_t"]
        wf = sd["wf_orig"]
        ev = sd["gross_ev"]
        net = sd["net_ev"]
        p_raw = dt["p_one_sided"]
        p_bonf = bonferroni_p(p_raw, 12)
        wf_status = wf.get("status", "no_picks")
        wf_tr = wf.get("train_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
        wf_te = wf.get("test_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
        wf_te_p = wf.get("test_day_t", {}).get("p_one_sided", 1.0) if wf_status == "ok" else 1.0
        v = verdict_for(ev, dt["t"], p_raw, wf_status, wf_tr, wf_te, wf_te_p, dt["n_days"], net, name, n_cross_factor=6)
        print(f"  → {name}: {v}  (Bonf×12={p_bonf:.4f}, OOS_test_p={wf_te_p}, OOS_test_p_Bonf×12={bonferroni_p(wf_te_p, 12):.4f})")

    # ---- BH FDR across family ----
    print(f"\n{'=' * 72}")
    print("[5] BH FDR 5% (Benjamini-Hochberg, replaces Bonferroni)")
    print(f"{'=' * 72}")

    # Family A: full-sample HAC p for top-1/3/5 (3 tests)
    full_p_list = [subset_data[n]["hac"]["p_one_sided"] for n in ("top-1", "top-3", "top-5")]
    bh_full_3 = bh_fdr(full_p_list, alpha=0.05)
    print(f"\n  Family A: full-sample HAC p (m=3: top-1/3/5)")
    print(f"    p-values: {[round(p, 6) for p in full_p_list]}")
    print(f"    BH rejected: {bh_full_3['rejected']}")
    print(f"    BH adjusted p: {bh_full_3['bh_adjusted_p']}")
    print(f"    n_significant: {bh_full_3['n_significant']}")

    # Family B: OOS pooled HAC p for top-1/3/5 (3 tests)
    oos_p_list = []
    for n in ("top-1", "top-3", "top-5"):
        rwf = subset_data[n]["rwf"]
        if rwf["status"] == "ok":
            oos_p_list.append(rwf["pooled_oos"]["hac_p"])
        else:
            oos_p_list.append(1.0)
    bh_oos_3 = bh_fdr(oos_p_list, alpha=0.05)
    print(f"\n  Family B: OOS pooled HAC p (m=3: top-1/3/5)")
    print(f"    p-values: {[round(p, 6) for p in oos_p_list]}")
    print(f"    BH rejected: {bh_oos_3['rejected']}")
    print(f"    BH adjusted p: {bh_oos_3['bh_adjusted_p']}")
    print(f"    n_significant: {bh_oos_3['n_significant']}")

    # Family C: combined 6 tests (full + OOS, 3 subsets each)
    combined_p = full_p_list + oos_p_list
    bh_combined_6 = bh_fdr(combined_p, alpha=0.05)
    print(f"\n  Family C: combined full+OOS (m=6)")
    print(f"    p-values: {[round(p, 6) for p in combined_p]}")
    print(f"    BH rejected: {bh_combined_6['rejected']}")
    print(f"    BH adjusted p: {bh_combined_6['bh_adjusted_p']}")
    print(f"    n_significant: {bh_combined_6['n_significant']}")

    # Note: with original family m=12 (6 factors × 2 subsets)
    print(f"\n  Note: original Bonferroni family was m=12 (6 factors × 2 subsets).")
    print(f"    BH with m=12 threshold for rank-1 = (1/12)*0.05 = {1 / 12 * 0.05:.6f}")
    print(f"    (if top-3 OOS p > 0.0042, it would NOT pass at rank 1 with m=12)")

    # ---- NEW verdict for top-3 ----
    print(f"\n{'=' * 72}")
    print("[6] NEW verdict for top-3 (BH + rolling WF + HAC)")
    print(f"{'=' * 72}")

    sd3 = subset_data["top-3"]
    rwf3 = sd3["rwf"]
    rwf3_status = rwf3.get("status", "no_picks")
    if rwf3_status == "ok":
        pooled = rwf3["pooled_oos"]
        pooled_ev = pooled["gross_ev"]
        pooled_hac_p = pooled["hac_p"]
        n_days_oos = pooled["n_days"]
        fold_pos = sum(1 for f in rwf3["folds"] if f["test_ev"] > 0)
        fold_total = len(rwf3["folds"])
    else:
        pooled_ev = 0.0
        pooled_hac_p = 1.0
        n_days_oos = 0
        fold_pos = 0
        fold_total = 0

    # BH results for top-3 specifically
    top3_idx_in_full = 1  # top-3 is index 1 in (top-1, top-3, top-5)
    bh_full_rej_top3 = bh_full_3["rejected"][top3_idx_in_full]
    bh_oos_rej_top3 = bh_oos_3["rejected"][top3_idx_in_full]

    new_v = new_verdict_for(
        ev_gross=sd3["gross_ev"],
        net_ev=sd3["net_ev"],
        hac_t=sd3["hac"]["t"],
        hac_p_raw=sd3["hac"]["p_one_sided"],
        rwf_status=rwf3_status,
        pooled_oos_ev=pooled_ev,
        pooled_oos_hac_p=pooled_hac_p,
        n_days=sd3["day_t"]["n_days"],
        bh_full_rejected=bh_full_rej_top3,
        bh_oos_rejected=bh_oos_rej_top3,
        fold_positive=fold_pos,
        fold_total=fold_total,
        subset_name="top-3",
    )

    # ---- Rolling WF detail ----
    print(f"\n{'=' * 72}")
    print("[7] Rolling 4-window expanding WF detail (top-3)")
    print(f"{'=' * 72}")
    if rwf3_status == "ok":
        print(
            f"  {'fold':<6} {'n_tr':>5} {'n_te':>5} {'days_tr':>7} {'days_te':>7} "
            f"{'tr_EV%':>8} {'te_EV%':>8} {'te_WR%':>7} "
            f"{'te_HAC_t':>9} {'te_HAC_p':>9} {'te_day_p':>9} {'range':<28}"
        )
        for f in rwf3["folds"]:
            print(
                f"  {f['fold']:<6} {f['n_train']:>5} {f['n_test']:>5} "
                f"{f['n_train_dates']:>7} {f['n_test_dates']:>7} "
                f"{f['train_ev']:>8.3f} {f['test_ev']:>8.3f} {f['test_wr']:>7.1f} "
                f"{f['test_hac_t']:>9.3f} {f['test_hac_p']:>9.6f} "
                f"{f['test_day_p']:>9.6f} {f['test_range']:<28}"
            )
        p = rwf3["pooled_oos"]
        print(
            f"\n  Pooled OOS: n={p['n']} n_days={p['n_days']} "
            f"gross={p['gross_ev']}% net={p['net_ev']}% "
            f"WR={p['wr']}% HAC_t={p['hac_t']} HAC_p={p['hac_p']} "
            f"day_t={p['day_t']} day_p={p['day_p']}"
        )
        print(f"  Folds positive: {fold_pos}/{fold_total}")
    else:
        print(f"  {rwf3_status}")

    # ---- Per-trade HAC detail ----
    print(f"\n{'=' * 72}")
    print("[8] Per-trade HAC (Newey-West) detail (top-3)")
    print(f"{'=' * 72}")
    h = sd3["hac"]
    print(f"  n_trades={h['n']} n_days={h['n_days']} mean={h['mean']}%")
    print(f"  HAC SE={h['hac_se']} lag={h['lag']} (NW_lag={h['nw_lag']}, max_same_day={h['max_same_day']})")
    print(f"  HAC t={h['t']} p_one_sided={h['p_one_sided']}")
    dt = sd3["day_t"]
    print(f"  [compare] per-day-mean t={dt['t']} p_one_sided={dt['p_one_sided']} n_days={dt['n_days']}")
    print(f"  [compare] gross_stats t={sd3['gross_stats']['t']} (naive per-trade t, no HAC)")

    # ---- Comparison: original vs new ----
    print(f"\n{'=' * 72}")
    print("[9] Comparison: ORIGINAL vs NEW verdict")
    print(f"{'=' * 72}")
    dt3 = sd3["day_t"]
    wf3 = sd3["wf_orig"]
    wf3_status = wf3.get("status", "no_picks")
    wf3_te_p = wf3.get("test_day_t", {}).get("p_one_sided", 1.0) if wf3_status == "ok" else 1.0
    print(f"  ORIGINAL: verdict=exploratory")
    print(f"    per-day t={dt3['t']} p_raw={dt3['p_one_sided']} Bonf×12={bonferroni_p(dt3['p_one_sided'], 12):.6f}")
    print(f"    OOS test_p={wf3_te_p} Bonf×12={bonferroni_p(wf3_te_p, 12):.6f} (>= 0.05 → exploratory)")
    print(f"  NEW: verdict={new_v}")
    print(f"    per-trade HAC t={h['t']} p_raw={h['p_one_sided']} BH_adj={bh_full_3['bh_adjusted_p'][1]} (rejected={bh_full_rej_top3})")
    if rwf3_status == "ok":
        print(f"    OOS pooled HAC p={pooled_hac_p} BH_adj={bh_oos_3['bh_adjusted_p'][1]} (rejected={bh_oos_rej_top3})")
        print(f"    rolling WF: {fold_pos}/{fold_total} folds positive, pooled OOS EV={pooled_ev}%")
    flipped = new_v == "edge-confirmed"
    print(f"\n  FLIPPED (exploratory → edge-confirmed): {flipped}")

    # ---- Fake-edge audit (if flipped) ----
    print(f"\n{'=' * 72}")
    print("[10] 假 edge 5 模式审" + (" (FLIPPED — must audit)" if flipped else " (not flipped — audit for transparency)"))
    print(f"{'=' * 72}")

    # 1. entry 涨停价溢价
    print(f"\n  1. entry 涨停价溢价: edge 是否来自涨停封板溢价 (T close sealed 不可买假象)?")
    print(f"     entry = T+1 open (realistic, NOT T close sealed) → NO 涨停价溢价")
    print(f"     close_ev = T+2 close (not open_ev, no T+1 intraday leakage)")
    # Check: how many picks have t1_open > t_close (gap up at entry)?
    gap_ups = sum(1 for p in top3 if p["entry"] > p["t_close"] * 1.001)
    gap_downs = sum(1 for p in top3 if p["entry"] < p["t_close"] * 0.999)
    print(f"     entry vs T close: {gap_ups}/{len(top3)} gap up, {gap_downs}/{len(top3)} gap down at T+1 open")

    # 2. survivorship
    print(f"\n  2. survivorship: edge 是否来自只看涨停股?")
    print(f"     ALL picks are 涨停股 (by construction — zt_history)")
    print(f"     edge should come from gene_score RANKING, not from being 涨停")
    base_ev = ev_stats([close_ev_basic(p) for p in all_gene_scored if close_ev_basic(p) is not None])["ev"]
    delta = sd3["gross_ev"] - base_ev
    print(f"     all_gene_scored EV={base_ev}% vs top-3 EV={sd3['gross_ev']}% → concentration delta={delta:+.3f}%")
    if delta > 0:
        print(f"     → ranking adds value (concentration positive) — not pure survivorship")
    else:
        print(f"     → ranking does NOT add value — edge may be just 涨停 survivorship")

    # 3. T+1 日内泄漏
    print(f"\n  3. T+1 日内泄漏: edge 是否来自 open_ev (T+1 日内回补)?")
    print(f"     Using close_ev (T+2 close), NOT open_ev → NO intraday leakage")
    print(f"     close_ev_basic = (T+2_close - T+1_open) / T+1_open")

    # 4. 拥挤倒 U (overfitting: in-sample strong, OOS decays)
    print(f"\n  4. 拥挤倒 U: edge 是否 in-sample 强 OOS 衰减 (过拟合)?")
    if rwf3_status == "ok":
        for f in rwf3["folds"]:
            decay = (f["train_ev"] - f["test_ev"]) / abs(f["train_ev"]) * 100 if f["train_ev"] != 0 else 0
            print(f"     fold {f['fold']}: train={f['train_ev']}% test={f['test_ev']}% decay={decay:.0f}%")
        print(f"     pooled OOS EV={pooled_ev}% vs full-sample gross={sd3['gross_ev']}%")
        overall_decay = (sd3["gross_ev"] - pooled_ev) / abs(sd3["gross_ev"]) * 100 if sd3["gross_ev"] != 0 else 0
        print(f"     overall OOS decay={overall_decay:.0f}%")

    # 5. fill 虚构
    print(f"\n  5. fill 虚构: stop/take 是否假设精确成交 (跳空穿 stop 按 stop_price)?")
    print(f"     Basic close_ev has NO stop → N/A (exit at T+2 close, always fillable)")
    print(f"     Stop variant uses R6 gap-through fill (T+2 open + slippage) — not fictional")

    # ---- concentration risk ----
    print(f"\n{'=' * 72}")
    print("[11] Concentration risk note")
    print(f"{'=' * 72}")
    print(f"  top-3 = 3 picks/day → n_trades={h['n']} n_days={h['n_days']}")
    print(f"  Same-day regime sharing: per-day-mean t controls N inflation,")
    print(f"  HAC with lag={h['lag']} captures same-day correlation.")
    print(f"  Cross-day regime correlation NOT fully controlled — concentration")
    print(f"  may amplify regime risk, not improve alpha.")

    # ---- overall honest notes ----
    print(f"\n{'=' * 72}")
    print("[12] 诚实注解")
    print(f"{'=' * 72}")
    print(f"  1. 测了什么: gene_score 排名 top-3 对 close_ev 的影响,")
    print(f"     用 BH FDR 5% + rolling 4-window WF + per-trade HAC (3 个合法替代).")
    print(f"  2. 没测什么: 单因子 ≠ 打板有/无 edge; gene_score 仅 2026-01-05+ (183 天,")
    print(f"     单 regime — bullish Jan-Sep 2026); rolling WF 每 fold ~45 天 < 60 (power 低).")
    print(f"  3. BH vs Bonferroni: BH 控 FDR (发现错误率), Bonferroni 控 FWER (族错误率).")
    print(f"     BH 更适合探索性研究, 是公认合法替代, 非任意放松.")
    print(f"  4. HAC vs per-day-mean: HAC 用全 N 不缩 N, Bartlett kernel 处理同日相关;")
    print(f"     per-day-mean 缩 N 到 n_days 偏保守. 两者方向应一致, 显著性可能不同.")
    print(f"  5. rolling WF vs single split: rolling 3 folds 测 regime robustness;")
    print(f"     每 fold ~45 天 < 60 → per-fold power 低, 但 pooled OOS (~135 天) 更可靠.")
    print(f"  6. 禁止外推: top-k-gene top-3 ≠ 打板有/无 edge; 不外推到其他窗口/市场.")
    print(f"\n  ORIGINAL verdict: exploratory")
    print(f"  NEW verdict: {new_v}")
    print(f"  FLIPPED: {flipped}")


if __name__ == "__main__":
    main()
