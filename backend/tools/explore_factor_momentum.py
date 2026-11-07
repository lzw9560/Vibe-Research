# -*- coding: utf-8 -*-
"""横截面动量因子 (Fama-French long-short decile) — 方法论改变的核心验证.

原方法学 flaw: long-only 策略 EV>0 跟 beta 混淆 (假阳性/假阴性都可能).
新方法学: Fama-French 横截面因子收益:
  - 每再平衡日, 按 momentum_15d 横截面排序股票
  - long top decile (高动量) + short bottom decile (低动量) → 零投资组合 (市场中性)
  - 因子收益 = long leg 收益 - short leg 收益 (持有期)
  - t(factor return) = NW HAC t (因子是否显著非零)
  - CAPM 回归: factor_ret = alpha + beta*mkt + e, alpha = 风险调整后因子 alpha

过严口径 (保留):
  - realistic: formation T 收盘算因子, entry T+1 close (非 T 收盘, 避 lookahead)
  - per-rebalance-block t (每观测即一个再平衡期, 无同日相关夸大 N)
  - Bonferroni: within-momentum ×N_freq (搜多 holding freq) + cross-factor ×4 (4 因子 sweep)
  - walk-forward OOS (前半 train → 后半 test) + train_ev>0 (防 regime 过拟合)
  - CAPM alpha + HAC SE (Newey-West Bartlett kernel)
  - winsorize 1%/99% 横截面 (防极端动量股扭曲 decile 边界)

诚实约束:
  - 散户可行性: long-short 需做空 (A股融券受限), 统计 alpha ≠ 可交易
  - survivorship: 早期 (2018-2020) 横截面 ~264-766 来自非随机 backfill 子集
  - 禁止外推: 4 因子 ≠ 横截面有/无 edge ≠ 战法有/无 edge

学术先验: A 股动量"惨不忍睹" (Kang-Liu-Xia 2002, 王 2004), 呈短期反转非动量.
本脚本用横截面 Fama-French 方法重测, 不预判结论.
"""

from __future__ import annotations
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

# import shared helpers (DRY) — low-level reusable, not pick-based high-level
sys.path.insert(0, str(Path(__file__).parent))
from _factor_helpers import bonferroni_p, norm_sf_positive  # noqa: E402

# ---------- paths + constants ----------

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
FACTOR_ZOO = DATA / "factor_zoo_data.json"

FACTOR_IDX = 0  # momentum_15d is index 0 in [mom, rev, size, vol]
FACTOR_NAME = "momentum_15d"
N_CROSS_FACTOR = 4  # 4 factors in parallel sweep → cross-factor Bonferroni ×4
ALPHA = 0.05
# holding frequencies to search (in rebalance-date units; 1 rebal = 5 trading days)
FREQS = [("weekly", 1), ("biweekly", 2), ("monthly", 4)]


# ---------- data loading ----------


def load_factor_zoo() -> dict:
    return json.loads(FACTOR_ZOO.read_text())


def load_closes(needed_dates: set[str]) -> dict[str, dict[str, float]]:
    """code -> {date: close} filtered to needed_dates (entry/exit dates)."""
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
            if d in needed_dates and c is not None and c > 0:
                dmap[d] = float(c)
        if dmap:
            out[code] = dmap
    conn.close()
    return out


# ---------- period construction ----------


def build_periods(rebal_dates: list[str], calendar: list[str], step: int) -> list[tuple[str, str, str]]:
    """Return [(formation, entry, exit)] for given step (rebal-date units).

    step=1 weekly (5d holding), 2 biweekly (10d), 4 monthly (20d).
    formation = rebal_dates[i]; entry = calendar[idx+1] (T+1 close, no lookahead);
    exit = rebal_dates[i+step]."""
    cal_idx = {d: i for i, d in enumerate(calendar)}
    periods: list[tuple[str, str, str]] = []
    i = 0
    while i + step < len(rebal_dates):
        form = rebal_dates[i]
        fi = cal_idx.get(form)
        if fi is None or fi + 1 >= len(calendar):
            i += step
            continue
        entry = calendar[fi + 1]
        exit_d = rebal_dates[i + step]
        periods.append((form, entry, exit_d))
        i += step
    return periods


def collect_needed_dates(rebal_dates: list[str], calendar: list[str]) -> set[str]:
    needed: set[str] = set()
    for _, step in FREQS:
        for form, entry, exit_d in build_periods(rebal_dates, calendar, step):
            needed.add(entry)
            needed.add(exit_d)
    return needed


# ---------- cross-sectional portfolio ----------


def winsorize(vals: np.ndarray, lo: float = 0.01, hi: float = 0.99) -> np.ndarray:
    qlo, qhi = np.quantile(vals, [lo, hi])
    return np.clip(vals, qlo, qhi)


def cross_sectional_deciles(snaps: dict, factor_idx: int) -> tuple[list[str], list[str]]:
    """Given {code: [factors]} for one rebalance date, return (long_codes, short_codes).

    Long = top decile (high factor value), short = bottom decile. Winsorize 1%/99% first
    (a few extreme-momentum stocks e.g. 688585 +919% would distort decile boundary).
    Equal-weight within decile (no shares-outstanding → value-weight not possible)."""
    codes = list(snaps.keys())
    n = len(codes)
    if n < 10:
        return [], []
    vals = np.array([snaps[c][factor_idx] for c in codes], float)
    vals_w = winsorize(vals)
    order = np.argsort(vals_w)  # ascending
    n_decile = max(1, n // 10)
    short_codes = [codes[order[j]] for j in range(n_decile)]  # bottom (low momentum)
    long_codes = [codes[order[j]] for j in range(n - n_decile, n)]  # top (high momentum)
    return long_codes, short_codes


def ew_close_return(codes: list[str], entry_date: str, exit_date: str, closes: dict[str, dict[str, float]]) -> tuple[float | None, int]:
    """Equal-weight close-to-close holding return for a code list."""
    rets: list[float] = []
    for c in codes:
        cm = closes.get(c)
        if not cm:
            continue
        ce = cm.get(entry_date)
        cx = cm.get(exit_date)
        if ce is None or cx is None or ce <= 0:
            continue
        rets.append(cx / ce - 1.0)
    if not rets:
        return None, 0
    return sum(rets) / len(rets), len(rets)


def market_period_return(mkt_daily: dict[str, float], entry_date: str, exit_date: str, calendar: list[str]) -> float | None:
    """Cumulative market return over [entry, exit] from daily pctChg (percent → decimal)."""
    try:
        ei = calendar.index(entry_date)
        xi = calendar.index(exit_date)
    except ValueError:
        return None
    if xi <= ei:
        return None
    cum = 1.0
    for d in calendar[ei : xi + 1]:
        p = mkt_daily.get(d)
        if p is None:
            continue
        cum *= 1.0 + p / 100.0
    return cum - 1.0


# ---------- Newey-West HAC (statsmodels unavailable) ----------


def newey_west(y: np.ndarray, x: np.ndarray, max_lag: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """OLS with Newey-West HAC SE (Bartlett kernel).

    Returns (beta, se, t) — arrays of length k.
    V_hat = (1/n) * Q^{-1} @ Omega @ Q^{-1}, Q = X'X/n, Omega = sum_j w(j)*Gamma_j,
    Gamma_j = (1/n) sum_t x_t x_{t-j}' e_t e_{t-j} (Gamma_0 = (1/n) sum x_t x_t' e_t^2).
    max_lag default = floor(4*(n/100)^(2/9)) (Newey-West 1994 rule)."""
    y = np.asarray(y, float)
    x = np.asarray(x, float)
    n, k = x.shape
    if n <= k + 1:
        return None
    Q = x.T @ x / n
    try:
        Qinv = np.linalg.inv(Q)
    except np.linalg.LinAlgError:
        return None
    beta = Qinv @ (x.T @ y / n)
    resid = y - x @ beta
    if max_lag is None:
        max_lag = max(1, int(np.floor(4 * (n / 100) ** (2 / 9))))
    max_lag = min(max_lag, n - 1)
    Omega = np.zeros((k, k))
    for j in range(max_lag + 1):
        w = 1.0 - j / (max_lag + 1)  # Bartlett kernel
        if j == 0:
            G = (x * resid[:, None] ** 2).T @ x / n
        else:
            xc = x[j:]
            xl = x[:-j]
            ec = resid[j:]
            el = resid[:-j]
            G = (xc * (ec * el)[:, None]).T @ xl / n
            G = G + G.T
        Omega += w * G
    Var = (1.0 / n) * Qinv @ Omega @ Qinv
    se = np.sqrt(np.maximum(np.diag(Var), 1e-30))
    t = beta / se
    return beta, se, t


def mean_nw_t(returns: list[float]) -> tuple[float, float, float]:
    """NW HAC t for mean (one-vector x). Returns (mean, se, t)."""
    y = np.array(returns, float)
    n = len(y)
    if n < 10:
        m = float(y.mean()) if n else 0.0
        return m, 0.0, 0.0
    x = np.ones((n, 1))
    r = newey_west(y, x)
    if r is None:
        return float(y.mean()), 0.0, 0.0
    beta, se, t = r
    return float(beta[0]), float(se[0]), float(t[0])


def capm_nw(returns: list[float], market: list[float]) -> tuple[float, float, float, float] | None:
    """CAPM: factor_ret = alpha + beta*mkt + e. NW HAC SE.
    Returns (alpha, alpha_se, alpha_t, beta_mkt)."""
    y = np.array(returns, float)
    m = np.array(market, float)
    n = len(y)
    if n < 10 or len(m) != n:
        return None
    x = np.column_stack([np.ones(n), m])
    r = newey_west(y, x)
    if r is None:
        return None
    beta, se, t = r
    return float(beta[0]), float(se[0]), float(t[0]), float(beta[1])


# ---------- per-frequency analysis ----------


def analyze_frequency(zoo: dict, closes: dict, step: int, label: str) -> dict:
    fs = zoo["factor_snapshots"]
    rd = zoo["rebalance_dates"]
    cal = zoo["trading_dates"]
    mkt = zoo["market_returns"]["sh.000001"]

    periods = build_periods(rd, cal, step)
    n_periods = len(periods)
    factor_rets: list[float] = []
    mkt_rets: list[float] = []
    dates_used: list[str] = []
    n_long_total = 0
    n_short_total = 0
    skipped_no_factor = 0
    skipped_no_ret = 0

    for form, entry, exit_d in periods:
        snaps = fs.get(form)
        if not snaps:
            skipped_no_factor += 1
            continue
        long_codes, short_codes = cross_sectional_deciles(snaps, FACTOR_IDX)
        if not long_codes or not short_codes:
            skipped_no_ret += 1
            continue
        long_ret, nl = ew_close_return(long_codes, entry, exit_d, closes)
        short_ret, ns = ew_close_return(short_codes, entry, exit_d, closes)
        if long_ret is None or short_ret is None:
            skipped_no_ret += 1
            continue
        fr = long_ret - short_ret  # zero-investment long-short return
        mr = market_period_return(mkt, entry, exit_d, cal)
        if mr is None:
            skipped_no_ret += 1
            continue
        factor_rets.append(fr)
        mkt_rets.append(mr)
        dates_used.append(form)
        n_long_total += nl
        n_short_total += ns

    n = len(factor_rets)
    print(f"\n{'=' * 72}")
    print(
        f"动量因子 long-short decile | freq={label} (holding {step * 5}d) | "
        f"n_periods={n} (built {n_periods}, skipped factor/ret "
        f"{skipped_no_factor}/{skipped_no_ret})"
    )
    print(f"{'=' * 72}")
    if n < 10:
        print(f"  n={n} < 10, underpowered")
        return {"label": label, "step": step, "n": n, "verdict": "underpowered"}

    mean, se, t = mean_nw_t(factor_rets)
    p_one = norm_sf_positive(t)
    std = float(np.std(factor_rets, ddof=1))
    wr = float(np.mean(np.array(factor_rets) > 0) * 100)
    sharpe = mean / std if std > 0 else 0.0

    print(f"  factor_return mean = {mean * 100:.4f}%/period  std = {std * 100:.4f}%  WR(>0) = {wr:.1f}%")
    print(f"  NW HAC t = {t:.3f}  one-sided p(>0) = {p_one:.6f}  (n={n}, maxlag auto)")
    print(f"  per-period Sharpe = {sharpe:.4f}")

    # CAPM alpha
    capm = capm_nw(factor_rets, mkt_rets)
    if capm is not None:
        alpha, a_se, a_t, beta_mkt = capm
        print(f"  CAPM: alpha = {alpha * 100:.4f}%  (se {a_se * 100:.4f}%, NW t = {a_t:.3f})  beta_mkt = {beta_mkt:.4f}")
    else:
        alpha, a_t, beta_mkt = 0.0, 0.0, 0.0

    # Bonferroni: within-momentum (×N_FREQS) AND cross-factor (×N_CROSS_FACTOR)
    n_tests = len(FREQS) * N_CROSS_FACTOR
    p_bonf = bonferroni_p(p_one, n_tests)
    print(f"  Bonferroni: raw p={p_one:.6f} × {len(FREQS)}(freqs)×{N_CROSS_FACTOR}(factors) = ×{n_tests} → p_bonf = {p_bonf:.6f}")

    # walk-forward: chronological split
    mid = n // 2
    train = factor_rets[:mid]
    test = factor_rets[mid:]
    train_m = train and (sum(train) / len(train))
    test_m = test and (sum(test) / len(test))
    train_t = mean_nw_t(train)[2] if len(train) >= 10 else 0.0
    test_mean, _, test_t = mean_nw_t(test) if len(test) >= 10 else (0.0, 0.0, 0.0)
    test_p = norm_sf_positive(test_t)
    # CAPM on train/test alpha
    tr_capm = capm_nw(train, mkt_rets[:mid]) if len(train) >= 10 else None
    te_capm = capm_nw(test, mkt_rets[mid:]) if len(test) >= 10 else None
    tr_alpha = tr_capm[0] if tr_capm else 0.0
    te_alpha = te_capm[0] if te_capm else 0.0
    print(f"  walk-forward: train n={len(train)} mean={train_m * 100:.4f}% NWt={train_t:.3f} alpha={tr_alpha * 100:.4f}%")
    print(f"               test  n={len(test)} mean={test_mean * 100:.4f}% NWt={test_t:.3f} alpha={te_alpha * 100:.4f}% p_one={test_p:.6f}")

    # ---- honest verdict ----
    verdict = verdict_factor(mean, t, p_bonf, alpha, a_t, len(test) >= 60, train_m, test_mean, test_t, test_p, n, label)
    print(f"  >>> VERDICT: {verdict}")

    return {
        "label": label,
        "step": step,
        "n": n,
        "factor_return_mean_pct": round(mean * 100, 4),
        "factor_return_std_pct": round(std * 100, 4),
        "factor_return_t": round(t, 3),
        "factor_return_p": round(p_one, 6),
        "bonferroni_p": round(p_bonf, 6),
        "capm_alpha_pct": round(alpha * 100, 4),
        "capm_alpha_t": round(a_t, 3),
        "capm_beta": round(beta_mkt, 4),
        "sharpe": round(sharpe, 4),
        "wr_pct": round(wr, 1),
        "wf_train_mean_pct": round(train_m * 100, 4),
        "wf_test_mean_pct": round(test_mean * 100, 4),
        "wf_train_t": round(train_t, 3),
        "wf_test_t": round(test_t, 3),
        "wf_test_p": round(test_p, 6),
        "wf_train_alpha_pct": round(tr_alpha * 100, 4),
        "wf_test_alpha_pct": round(te_alpha * 100, 4),
        "verdict": verdict,
        "n_long_avg": round(n_long_total / max(n, 1), 1),
        "n_short_avg": round(n_short_total / max(n, 1), 1),
    }


def verdict_factor(
    mean: float,
    t: float,
    p_bonf: float,
    alpha: float,
    a_t: float,
    test_n_ge_60: bool,
    train_mean: float,
    test_mean: float,
    test_t: float,
    test_p: float,
    n: int,
    label: str,
) -> str:
    """Honest verdict for cross-sectional long-short factor (NOT long-only EV).

    Cascade (过严口径):
    1. n < 60 → underpowered
    2. mean < 0 (long-high-momentum underperforms) → falsified (momentum 方向无 edge)
    3. Bonferroni p >= 0.05 → falsified (not significant after multiple-testing)
    4. CAPM alpha <= 0 → falsified (no risk-adjusted edge)
    5. walk-forward test mean <= 0 OR train_mean <= 0 → falsified/exploratory
    6. OOS test not significant → exploratory
    7. all pass → edge-confirmed"""
    if n < 60:
        return "underpowered"
    if mean < 0:
        return "edge-falsified"
    if p_bonf >= ALPHA:
        return "edge-falsified"
    if alpha <= 0:
        return "edge-falsified"
    if not test_n_ge_60:
        return "underpowered"
    if train_mean <= 0:
        return "exploratory"
    if test_mean <= 0:
        return "edge-falsified"
    te_p_bonf = bonferroni_p(test_p, len(FREQS) * N_CROSS_FACTOR)
    if te_p_bonf >= ALPHA:
        return "exploratory"
    return "edge-confirmed"


# ---------- main ----------


def main() -> int:
    print("==> loading factor_zoo_data.json ...", flush=True)
    zoo = load_factor_zoo()
    rd = zoo["rebalance_dates"]
    cal = zoo["trading_dates"]
    meta = zoo["metadata"]
    print(f"    factors: {list(meta['factors'].keys())}")
    print(
        f"    range: {meta['date_range']}  n_dates={meta['n_dates']}  n_rebal={len(rd)}  cross-sec avg={meta['cross_section_size']['avg_codes_per_rebalance']}",
        flush=True,
    )

    print("==> collecting needed dates + loading closes ...", flush=True)
    needed = collect_needed_dates(rd, cal)
    print(f"    needed entry/exit dates: {len(needed)}", flush=True)
    closes = load_closes(needed)
    print(f"    codes with usable closes: {len(closes)}", flush=True)

    results: list[dict] = []
    for label, step in FREQS:
        r = analyze_frequency(zoo, closes, step, label)
        results.append(r)

    # ---- summary: pick best (lowest p) for primary report, but honest about search ----
    valid = [r for r in results if r.get("n", 0) >= 10]
    if valid:
        best = min(valid, key=lambda r: r.get("factor_return_p", 1.0))
        print(f"\n{'#' * 72}")
        print(f"PRIMARY (best p across {len(FREQS)} freqs, search-corrected): freq={best['label']}")
        print(f"  factor_return_mean = {best['factor_return_mean_pct']}%/period  NW t = {best['factor_return_t']}  p = {best['factor_return_p']}")
        print(f"  Bonferroni p (×{len(FREQS) * N_CROSS_FACTOR}) = {best['bonferroni_p']}")
        print(f"  CAPM alpha = {best['capm_alpha_pct']}%  (NW t = {best['capm_alpha_t']}, beta = {best['capm_beta']})")
        print(
            f"  walk-forward: train {best['wf_train_mean_pct']}% (alpha "
            f"{best['wf_train_alpha_pct']}%) | test {best['wf_test_mean_pct']}% "
            f"(alpha {best['wf_test_alpha_pct']}%, t {best['wf_test_t']}, "
            f"p {best['wf_test_p']})"
        )
        print(f"  VERDICT: {best['verdict']}")
        print(f"{'#' * 72}")
    else:
        print("\n  no valid frequencies (all <10 periods)")

    # ---- honest caveats ----
    print("\n--- 诚实标注 (禁止外推) ---")
    print("1. 本脚本测的是横截面 momentum_15d 因子 (long-short decile), 非 long-only EV, 非其他因子.")
    print("2. long-short 需做空 bottom decile — A股散户融券极度受限, 统计 alpha ≠ 可交易 (仅机构/融券标的可用).")
    print("3. survivorship: 早期 (2018-2020) 横截面 ~264-766 来自非随机 backfill 子集, 晚期 (2025-2026) 横截面大但天数少.")
    print("4. 4 因子 (本脚本仅动量) ≠ 横截面有/无 edge ≠ 选股战法有/无 edge.")
    print("5. 学术先验: A股呈短期反转非动量 (Kang 2002) — 若 long-high-momentum 为负, 是反转现象, 由 reversal 子代理测.")

    # dump machine-readable
    out_path = Path(__file__).parent / "_momentum_result.json"
    out_path.write_text(
        json.dumps(
            {
                "factor": FACTOR_NAME,
                "factor_definition": meta["factors"]["momentum_15d"],
                "methodology": "Fama-French cross-sectional long-short decile (zero-investment, market-neutral)",
                "n_cross_factor_bonferroni": N_CROSS_FACTOR,
                "n_freqs_searched": len(FREQS),
                "market_benchmark": "sh.000001 (上证综指, price index excl. dividends)",
                "results_by_freq": results,
                "primary_best_p": best if valid else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\n==> written {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
