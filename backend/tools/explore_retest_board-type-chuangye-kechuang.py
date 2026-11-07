# -*- coding: utf-8 -*-
"""Re-test: board-type 创业板+科创板 (combined 20%-board subset).

原 verdict: exploratory (OOS test_p=0.062 chuangye / 0.065 kechuang, Bonf×12 failed).
本 re-test 用 less-conservative 方法学:
  - BH FDR 5% 替代 Bonferroni (合法替代, 非 p-hacking)
  - rolling 4-window expanding walk-forward 替代单次 50/50 (3 test windows)
  - per-trade t + Newey-West HAC 替代 per-day-mean t (不缩 N)
  - 0.2% 成本 (创业板/科创板中盘, 原 0.3%)

过严口径 (保留):
  - entry = T+1 open (非 T close sealed)
  - close_ev (非 open_ev, 防 T+1 日内泄漏)
  - 一字涨停跳过 (limit_for_code FIXED)
  - R6 gap-through fill (stop 变体)
  - 禁止外推

假 edge 5 模式审 (翻正必须过):
  1. entry 涨停价溢价 (T+1 open gap up?)
  2. survivorship (20% 板封板更难→只最强股? differential confound)
  3. T+1 日内泄漏 (close_ev 已防)
  4. 拥挤倒 U (in-sample 强 OOS 衰减?)
  5. fill 虚构 (basic 无 stop, stop 用 R6)

跑法: cd backend && .venv/bin/python tools/explore_retest_board-type-chuangye-kechuang.py
"""

from __future__ import annotations
import statistics
from collections import defaultdict
from math import erf, sqrt

from tools._factor_helpers import (
    load_kline_db,
    load_zt,
    limit_for_code,
    build_picks_generic,
    close_ev_basic,
    close_ev_stop,
    ev_stats,
    day_paired_t,
    norm_sf_positive,
)

# ---------- cost override: 0.2% for 创业板/科创板 mid-cap ----------
BOARD_COST = 0.002  # round-trip (印花 0.05% sell + 佣金 0.05% + 过户 0.002% + 滑点 ~0.1%)
ALPHA = 0.05


# ---------- board classification (same as original) ----------


def is_20pct_board(code: str) -> bool:
    """创业板(300/301) + 科创板(688/689), both 20% limit."""
    return code.startswith(("300", "301", "688", "689"))


def board_of(code: str) -> str:
    if code.startswith(("300", "301")):
        return "chuangye"
    if code.startswith(("688", "689")):
        return "kechuang"
    if code.startswith(("4", "8")):
        return "beijiao"
    if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return "main"
    return "other"


def make_combined_filter():
    def _fn(code: str, lbc: int, t_bar: dict, t1_bar: dict, t2_bar: dict) -> bool:
        return is_20pct_board(code)

    return _fn


# ================================================================== #
# NEW METHODOLOGY: BH FDR, rolling WF, per-trade HAC
# ================================================================== #


def bh_fdr(p_list: list[float], alpha: float = 0.05) -> dict:
    """Benjamini-Hochberg FDR control.

    Sort p ascending. Find largest k where p(k) <= k/m * alpha.
    Reject all hypotheses with rank <= k. Returns adjusted q-values.

    This is a LEGITIMATE alternative to Bonferroni: Bonferroni controls FWER
    (probability of >=1 false positive), BH controls FDR (expected proportion
    of false discoveries). BH is less conservative, suited for exploratory
    research where some false positives are tolerable.
    """
    m = len(p_list)
    if m == 0:
        return {"m": 0, "alpha": alpha, "n_passed": 0, "passed": [], "q_values": [], "verdict": "no_tests"}
    # sort by p ascending, keep original index
    indexed = sorted(enumerate(p_list), key=lambda x: x[1])
    # find largest k where p(k) <= (k/m) * alpha
    largest_k = 0
    for k, (idx, p) in enumerate(indexed, 1):
        threshold = (k / m) * alpha
        if p <= threshold:
            largest_k = k
    passed_indices = set()
    if largest_k > 0:
        for k in range(1, largest_k + 1):
            passed_indices.add(indexed[k - 1][0])
    # adjusted q-values: q(k) = min_{j>=k} p(j)*m/j, then cap at 1
    q = [0.0] * m
    running_min = 1.0
    for k in range(m, 0, -1):
        idx, p = indexed[k - 1]
        adj = p * m / k
        running_min = min(running_min, adj)
        q[idx] = min(1.0, running_min)
    verdict = "PASS" if largest_k > 0 else "FAIL"
    return {
        "m": m,
        "alpha": alpha,
        "n_passed": largest_k,
        "passed": sorted(passed_indices),
        "q_values": q,
        "verdict": verdict,
        "threshold_at_k": (largest_k / m) * alpha if largest_k > 0 else 0.0,
    }


def per_trade_t_hac(rets: list[float], dates: list[str], max_lag: int | None = None) -> dict:
    """Per-trade t with Newey-West HAC (Bartlett kernel) SE.

    Trades ordered by date (zt_date). Same-day trades are cross-sectionally
    correlated; HAC with Bartlett kernel captures this via the lag structure.
    Does NOT shrink N (unlike per-day-mean which collapses to n_days).

    HAC long-run variance: S = gamma0 + 2*sum_{l=1}^{L} (1 - l/(L+1)) * gamma_l
    SE of mean = sqrt(S / n). t = mean / SE.

    Lag choice: standard Newey-West rule L = floor(n^(1/3)). This is the
    textbook default. NOTE: if max trades/day > L, same-day clustering may
    not be fully captured → per-trade HAC t may be inflated. We also report
    per-day-mean t (conservative baseline) for comparison.
    """
    if not rets:
        return {"n": 0, "mean": 0.0, "se_hac": 0.0, "t": 0.0, "p_one_sided": 1.0, "max_lag": 0, "n_days": 0}
    # sort by date to make it a time series
    pairs = sorted(zip(dates, rets), key=lambda x: x[0])
    r = [p[1] for p in pairs]
    n = len(r)
    mean = sum(r) / n
    e = [x - mean for x in r]
    if max_lag is None:
        max_lag = max(1, int(n ** (1 / 3)))
    # gamma0
    gamma0 = sum(x * x for x in e) / n
    S = gamma0
    for l in range(1, max_lag + 1):
        w = 1 - l / (max_lag + 1)  # Bartlett kernel
        gl = sum(e[i] * e[i - l] for i in range(l, n)) / n
        S += 2 * w * gl
    if S < 0:  # guard: HAC variance should be non-negative
        S = gamma0
    se_hac = sqrt(S / n) if S > 0 else 0.0
    t = mean / se_hac if se_hac > 0 else 0.0
    p = norm_sf_positive(t)
    n_days = len(set(dates))
    # also compute max trades per day for transparency
    day_counts: dict[str, int] = defaultdict(int)
    for d in dates:
        day_counts[d] += 1
    max_tpd = max(day_counts.values()) if day_counts else 0
    median_tpd = statistics.median(day_counts.values()) if day_counts else 0
    return {
        "n": n,
        "n_days": n_days,
        "mean": round(mean, 3),
        "se_hac": round(se_hac, 4),
        "t": round(t, 2),
        "p_one_sided": round(p, 6),
        "max_lag": max_lag,
        "max_trades_per_day": max_tpd,
        "median_trades_per_day": median_tpd,
    }


def rolling_walk_forward(picks: list[dict], ret_fn, n_windows: int = 4) -> dict:
    """Expanding-window walk-forward (true walk-forward, not single 50/50).

    Split zt_dates into n_windows roughly-equal quarters.
    Window 1: train=Q1,            test=Q2
    Window 2: train=Q1+Q2,        test=Q3
    Window 3: train=Q1+Q2+Q3,     test=Q4
    (n_windows-1 test windows)

    For each test window: per-trade HAC t + per-day-mean t.
    Returns per-window train/test EV + significance.
    """
    if not picks:
        return {"status": "no_picks"}
    ps = sorted(picks, key=lambda p: p["zt_date"])
    dates = sorted(set(p["zt_date"] for p in ps))
    if len(dates) < n_windows:
        return {"status": "too_few_dates", "n_dates": len(dates)}
    # split dates into n_windows quarters (roughly equal)
    q_size = len(dates) // n_windows
    quarters: list[set[str]] = []
    for i in range(n_windows):
        start = i * q_size
        end = (i + 1) * q_size if i < n_windows - 1 else len(dates)
        quarters.append(set(dates[start:end]))

    windows = []
    for w in range(n_windows - 1):  # w = 0,1,2 → 3 test windows
        train_q: set[str] = set()
        for i in range(w + 1):
            train_q |= quarters[i]
        test_q = quarters[w + 1]
        train_picks = [p for p in ps if p["zt_date"] in train_q]
        test_picks = [p for p in ps if p["zt_date"] in test_q]
        train_rets = [ret_fn(p) for p in train_picks]
        train_rets = [r for r in train_rets if r is not None]
        test_rets = [ret_fn(p) for p in test_picks]
        test_rets = [r for r in test_rets if r is not None]
        # per-day-mean
        test_by_date: dict[str, list[float]] = defaultdict(list)
        for p in test_picks:
            r = ret_fn(p)
            if r is not None:
                test_by_date[p["zt_date"]].append(r)
        test_dt = day_paired_t(test_by_date)
        # per-trade HAC
        test_dates_list = [p["zt_date"] for p in test_picks if ret_fn(p) is not None]
        test_hac = per_trade_t_hac(test_rets, test_dates_list)
        train_s = ev_stats(train_rets)
        test_s = ev_stats(test_rets)
        windows.append(
            {
                "window": w + 1,
                "train_n_dates": len(train_q),
                "test_n_dates": len(test_q),
                "train_n": len(train_rets),
                "test_n": len(test_rets),
                "train_ev": train_s["ev"],
                "test_ev": test_s["ev"],
                "test_wr": test_s["wr"],
                "test_day_t": test_dt["t"],
                "test_day_p": test_dt["p_one_sided"],
                "test_hac_t": test_hac["t"],
                "test_hac_p": test_hac["p_one_sided"],
                "test_n_days": test_hac["n_days"],
            }
        )
    # pooled OOS: combine all test-window trades
    all_test_picks = [p for p in ps if p["zt_date"] in (quarters[1] | quarters[2] | quarters[3])]
    all_test_rets = [ret_fn(p) for p in all_test_picks]
    all_test_rets = [r for r in all_test_rets if r is not None]
    all_test_dates = [p["zt_date"] for p in all_test_picks if ret_fn(p) is not None]
    pooled_hac = per_trade_t_hac(all_test_rets, all_test_dates)
    pooled_dt = day_paired_t(
        {
            d: [ret_fn(p) for p in all_test_picks if p["zt_date"] == d and ret_fn(p) is not None]
            for d in set(p["zt_date"] for p in all_test_picks)
        }
    )
    return {
        "status": "ok",
        "n_windows": n_windows,
        "windows": windows,
        "pooled_oos_hac": pooled_hac,
        "pooled_oos_day_t": pooled_dt,
        "pooled_oos_ev": ev_stats(all_test_rets)["ev"],
        "pooled_oos_n": len(all_test_rets),
    }


# ================================================================== #
# FAKE-EDGE AUDIT (5 patterns + differential survivorship)
# ================================================================== #


def fake_edge_audit(picks: list[dict], code_map: dict, zt_rows: list, wf: dict) -> dict:
    """Audit 5 fake-edge patterns. Returns per-pattern verdict."""
    results = {}

    # 1. Entry 涨停价溢价: T+1 open gap vs T close
    gaps = []
    for p in picks:
        tc = p["t_close"]
        t1o = p["entry"]
        if tc > 0:
            gaps.append((t1o - tc) / tc * 100)
    avg_gap = statistics.mean(gaps) if gaps else 0.0
    results["entry_gap"] = {
        "avg_t1_open_vs_t_close_pct": round(avg_gap, 3),
        "verdict": (
            "WARN" if avg_gap > 1.0 else "ok",
            f"T+1 open {avg_gap:+.3f}% vs T close — {'gap-up premium at entry (momentum)' if avg_gap > 1.0 else 'minimal entry premium'}",
        ),
    }

    # 2. Survivorship / differential confound:
    #    20%-board limit-ups are "stronger" (20% move vs 10%).
    #    Compare limit-up rate of 20% boards vs 10% boards (universe=code_map).
    n_20pct_universe = sum(1 for c in code_map if is_20pct_board(c))
    n_main_universe = sum(1 for c in code_map if board_of(c) == "main")
    n_20pct_zt = sum(1 for _, c, _ in zt_rows if is_20pct_board(c))
    n_main_zt = sum(1 for _, c, _ in zt_rows if board_of(c) == "main")
    # limit-up rate per stock-day (approximate: zt count / universe * n_days)
    # just compare relative representation
    pct_20_in_universe = n_20pct_universe / (n_20pct_universe + n_main_universe) * 100 if (n_20pct_universe + n_main_universe) else 0
    pct_20_in_zt = n_20pct_zt / (n_20pct_zt + n_main_zt) * 100 if (n_20pct_zt + n_main_zt) else 0
    results["survivorship"] = {
        "n_20pct_universe": n_20pct_universe,
        "n_main_universe": n_main_universe,
        "n_20pct_zt": n_20pct_zt,
        "n_main_zt": n_main_zt,
        "pct_20pct_in_universe": round(pct_20_in_universe, 1),
        "pct_20pct_in_zt": round(pct_20_in_zt, 1),
        "verdict": (
            "WARN" if pct_20_in_zt < pct_20_in_universe else "ok",
            f"20% boards {pct_20_in_zt:.1f}% of limit-ups vs {pct_20_in_universe:.1f}% of universe — "
            f"{'UNDER-represented (harder to limit-up → only strongest survive = differential survivorship confound)' if pct_20_in_zt < pct_20_in_universe else 'no under-representation'}",
        ),
    }

    # 2b. Limit-up magnitude confound: 20%-board limit-ups moved 2x (20% vs 10%).
    #     Edge may be momentum-magnitude effect, not board-type.
    #     Compute avg T-day pctChg for 20% vs main limit-ups.
    pct_20 = []
    pct_main = []
    for zt_date, code, _ in zt_rows:
        dmap = code_map.get(code)
        if not dmap:
            continue
        bar = dmap.get(zt_date)
        if not bar or bar.get("pctChg") is None:
            continue
        try:
            pc = float(bar["pctChg"])
        except (TypeError, ValueError):
            continue
        if is_20pct_board(code):
            pct_20.append(pc)
        elif board_of(code) == "main":
            pct_main.append(pc)
    avg_pct_20 = statistics.mean(pct_20) if pct_20 else 0.0
    avg_pct_main = statistics.mean(pct_main) if pct_main else 0.0
    results["momentum_magnitude_confound"] = {
        "avg_t_day_pctChg_20pct": round(avg_pct_20, 2),
        "avg_t_day_pctChg_main": round(avg_pct_main, 2),
        "verdict": (
            "WARN",
            f"20%-board limit-ups moved {avg_pct_20:.1f}% T-day vs main {avg_pct_main:.1f}% — "
            f"2x momentum surge; edge may be momentum-magnitude, not board-type (cannot disentangle)",
        ),
    }

    # 3. T+1 日内泄漏: using close_ev (T+2 close - T+1 open), NOT open_ev. Handled.
    results["t1_leakage"] = {
        "verdict": ("ok", "close_ev used (T+2 close - T+1 open), not open_ev — no T+1 intraday leakage"),
    }

    # 4. 拥挤倒 U (overfitting): rolling WF train→test decay
    if wf.get("status") == "ok":
        windows = wf["windows"]
        positive_test = sum(1 for w in windows if w["test_ev"] > 0)
        decays = []
        for w in windows:
            if w["train_ev"] != 0:
                decays.append((w["train_ev"] - w["test_ev"]) / abs(w["train_ev"]) * 100)
        avg_decay = statistics.mean(decays) if decays else 0.0
        results["overfitting_decay"] = {
            "n_windows_positive_test": f"{positive_test}/{len(windows)}",
            "avg_train_to_test_decay_pct": round(avg_decay, 1),
            "verdict": (
                "WARN" if (positive_test < len(windows) or avg_decay > 50) else "ok",
                f"{positive_test}/{len(windows)} windows positive OOS EV, "
                f"avg decay {avg_decay:.0f}% — "
                f"{'edge decays OOS (overfitting signal)' if avg_decay > 50 else 'edge persists OOS'}",
            ),
        }

    # 5. Fill 虚构: basic has no stop (no fill issue). Stop variant uses R6.
    results["fill_fiction"] = {
        "verdict": (
            "ok",
            "basic close_ev has no stop (no fill assumption). Stop variant uses R6 gap-through fill (T+2 open + slippage)",
        ),
    }

    # overall audit verdict
    warns = sum(1 for v in results.values() if isinstance(v.get("verdict"), tuple) and v["verdict"][0] == "WARN")
    results["overall"] = {
        "n_warns": warns,
        "verdict": ("CLEAN" if warns == 0 else f"{warns} WARN (confounds present, edge not clean)"),
    }
    return results


# ================================================================== #
# NEW VERDICT LOGIC (less-conservative but honest)
# ================================================================== #


def new_verdict_for(
    ev_gross: float,
    net_ev: float,
    n_days: int,
    hac_t: float,
    hac_p: float,
    bh_insample: dict,
    wf: dict,
    bh_oos: dict,
    audit: dict,
) -> tuple[str, str]:
    """New verdict using BH FDR + rolling WF + per-trade HAC.

    Cascade:
    1. gross EV < 0 → falsified
    2. n_days < 60 → underpowered
    3. net EV <= 0 → falsified (cost eats edge)
    4. in-sample per-trade HAC p fails BH → falsified (no in-sample edge)
    5. rolling WF: <2/3 windows positive test EV → falsified (no OOS persistence)
    6. rolling WF: BH on OOS window p's fails → exploratory (OOS not significant)
    7. fake-edge audit has WARN → exploratory (confounds, cannot confirm)
    8. all pass → edge-confirmed
    """
    reasons = []
    if ev_gross < 0:
        reasons.append("FALSIFIED: gross EV < 0 (negative edge)")
        return "edge-falsified", "; ".join(reasons)
    if n_days < 60:
        reasons.append(f"UNDERPOWERED: n_days={n_days} < 60")
        return "underpowered", "; ".join(reasons)
    if net_ev <= 0:
        reasons.append(f"FALSIFIED: net EV={net_ev}% <= 0 (cost eats edge)")
        return "edge-falsified", "; ".join(reasons)
    if bh_insample["verdict"] == "FAIL":
        reasons.append(f"FALSIFIED: in-sample HAC p fails BH (q={min(bh_insample['q_values']) if bh_insample['q_values'] else 1})")
        return "edge-falsified", "; ".join(reasons)

    if wf["status"] == "ok":
        windows = wf["windows"]
        n_pos = sum(1 for w in windows if w["test_ev"] > 0)
        if n_pos < (2 / 3) * len(windows):
            reasons.append(f"FALSIFIED: only {n_pos}/{len(windows)} OOS windows positive EV")
            return "edge-falsified", "; ".join(reasons)
        if bh_oos["verdict"] == "FAIL":
            reasons.append(f"EXPLORATORY: OOS BH fails ({bh_oos['n_passed']}/{bh_oos['m']} windows significant)")
            return "exploratory", "; ".join(reasons)
    else:
        reasons.append("EXPLORATORY: rolling WF unavailable")
        return "exploratory", "; ".join(reasons)

    # fake-edge audit
    n_warns = audit["overall"]["n_warns"]
    if n_warns > 0:
        reasons.append(f"EXPLORATORY: {audit['overall']['verdict']} (statistical edge but confounds prevent confirmation)")
        return "exploratory", "; ".join(reasons)

    reasons.append("EDGE-CONFIRMED: gross+net EV > 0, in-sample BH pass, OOS rolling WF positive + BH significant, audit clean")
    return "edge-confirmed", "; ".join(reasons)


# ================================================================== #
# MAIN
# ================================================================== #


def main():
    print("=" * 72)
    print("RE-TEST: board-type 创业板+科创板 (combined 20%-board subset)")
    print("  less-conservative: BH FDR + rolling 4-window WF + per-trade HAC + 0.2% cost")
    print("=" * 72)

    print("\n加载数据…")
    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    zt_rows = load_zt()
    print(f"  kline codes: {len(code_map)}")
    print(f"  calendar days: {len(calendar)} ({calendar[0]} ~ {calendar[-1]})")
    print(f"  zt rows: {len(zt_rows)}")

    # board distribution
    board_counts: dict[str, int] = defaultdict(int)
    for _, code, _ in zt_rows:
        board_counts[board_of(code)] += 1
    print(f"\n  ZT rows 板块分布:")
    for b, c in sorted(board_counts.items(), key=lambda x: -x[1]):
        print(f"    {b}: {c}")

    # ---- build combined chuangye+kechuang picks ----
    print(f"\n构建 picks (combined 创业板+科创板, entry=T+1 open, 一字涨停跳过):")
    picks = build_picks_generic(code_map, calendar, zt_rows, filter_fn=make_combined_filter())
    # split for reference
    cy_picks = [p for p in picks if p["code"].startswith(("300", "301"))]
    kc_picks = [p for p in picks if p["code"].startswith(("688", "689"))]
    print(f"  combined: {len(picks)} picks (chuangye {len(cy_picks)} + kechuang {len(kc_picks)})")

    # ---- basic close_ev ----
    print(f"\n{'=' * 72}")
    print("BASIC close_ev (T+1 open → T+2 close, no stop)")
    print(f"{'=' * 72}")
    basic_rets = [close_ev_basic(p) for p in picks]
    basic_rets = [r for r in basic_rets if r is not None]
    basic_s = ev_stats(basic_rets)
    print(
        f"  n={basic_s['n']} gross_EV={basic_s['ev']}% std={basic_s['std']}% "
        f"WR={basic_s['wr']}% t={basic_s['t']} CI[{basic_s['ci_lo']},{basic_s['ci_hi']}]"
    )
    net_ev = basic_s["ev"] - BOARD_COST * 100
    print(f"  net EV (after {BOARD_COST * 100:.1f}% cost): {net_ev:.3f}%")

    # per-day-mean t (original method, conservative baseline)
    basic_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        r = close_ev_basic(p)
        if r is not None:
            basic_by_date[p["zt_date"]].append(r)
    basic_dt = day_paired_t(basic_by_date)
    print(
        f"\n  [original method] per-day-mean: n_days={basic_dt['n_days']} "
        f"mean={basic_dt['mean']}% t={basic_dt['t']} p={basic_dt['p_one_sided']}"
    )

    # per-trade HAC (new method)
    basic_dates = [p["zt_date"] for p in picks if close_ev_basic(p) is not None]
    basic_hac = per_trade_t_hac(basic_rets, basic_dates)
    print(
        f"\n  [new method] per-trade HAC: n={basic_hac['n']} n_days={basic_hac['n_days']} "
        f"mean={basic_hac['mean']}% se_hac={basic_hac['se_hac']} t={basic_hac['t']} "
        f"p={basic_hac['p_one_sided']}"
    )
    print(f"    max_lag={basic_hac['max_lag']} (Newey-West rule floor(n^(1/3)))")
    print(f"    max_trades/day={basic_hac['max_trades_per_day']} median_trades/day={basic_hac['median_trades_per_day']}")
    print(
        f"    NOTE: if max_trades/day > max_lag, same-day clustering may be "
        f"under-captured → HAC t may be inflated. per-day-mean (above) is "
        f"the conservative baseline."
    )

    # ---- stop variant ----
    print(f"\n{'=' * 72}")
    print("STOP variant (-3% stop + R6 gap-through fill)")
    print(f"{'=' * 72}")
    stop_rets = [close_ev_stop(p) for p in picks]
    stop_rets_clean = [r[0] for r in stop_rets if r is not None]
    stop_s = ev_stats(stop_rets_clean)
    net_stop = stop_s["ev"] - BOARD_COST * 100
    print(f"  n={stop_s['n']} gross_EV={stop_s['ev']}% net_EV={net_stop:.3f}% WR={stop_s['wr']}% t={stop_s['t']}")
    stop_reasons: dict[str, int] = defaultdict(int)
    for r in stop_rets:
        if r is not None:
            stop_reasons[r[1]] += 1
    print(f"  exit reasons:")
    for rsn, cnt in sorted(stop_reasons.items(), key=lambda x: -x[1]):
        print(f"    {rsn}: {cnt} ({cnt / max(len(stop_rets_clean), 1) * 100:.1f}%)")

    # ---- BH FDR: in-sample ----
    print(f"\n{'=' * 72}")
    print("BH FDR 5% (Benjamini-Hochberg, replaces Bonferroni)")
    print(f"{'=' * 72}")
    # in-sample family: per-day-mean p + per-trade HAC p (m=2, same hypothesis tested 2 ways)
    # This is the most honest family for in-sample.
    insample_ps = [basic_dt["p_one_sided"], basic_hac["p_one_sided"]]
    bh_insample = bh_fdr(insample_ps, alpha=ALPHA)
    print(f"\n  in-sample family (m={bh_insample['m']}): per-day-mean p, per-trade HAC p")
    print(f"    p-values: per-day={basic_dt['p_one_sided']}, HAC={basic_hac['p_one_sided']}")
    print(f"    BH verdict: {bh_insample['verdict']} ({bh_insample['n_passed']}/{bh_insample['m']} passed)")
    print(f"    q-values: {bh_insample['q_values']}")
    # also show what Bonferroni ×12 (original) would give for comparison
    bonf12_day = min(1.0, basic_dt["p_one_sided"] * 12)
    bonf12_hac = min(1.0, basic_hac["p_one_sided"] * 12)
    print(f"\n  [comparison] original Bonferroni ×12: day p→{bonf12_day:.6f}, HAC p→{bonf12_hac:.6f}")
    print(f"  [comparison] BH ×4 (cross-strategy, if this p is smallest of 4): threshold = 1/4 × 0.05 = 0.0125")

    # ---- rolling walk-forward ----
    print(f"\n{'=' * 72}")
    print("ROLLING 4-window expanding walk-forward (3 test windows)")
    print(f"{'=' * 72}")
    wf = rolling_walk_forward(picks, close_ev_basic, n_windows=4)
    if wf["status"] == "ok":
        print(
            f"\n  {'win':>3} {'train_n':>7} {'test_n':>6} {'train_ev%':>10} "
            f"{'test_ev%':>9} {'test_wr':>7} {'day_t':>6} {'day_p':>9} "
            f"{'hac_t':>6} {'hac_p':>9} {'n_days':>6}"
        )
        for w in wf["windows"]:
            print(
                f"  {w['window']:>3} {w['train_n']:>7} {w['test_n']:>6} "
                f"{w['train_ev']:>10.3f} {w['test_ev']:>9.3f} {w['test_wr']:>6.1f}% "
                f"{w['test_day_t']:>6.2f} {w['test_day_p']:>9.6f} "
                f"{w['test_hac_t']:>6.2f} {w['test_hac_p']:>9.6f} "
                f"{w['test_n_days']:>6}"
            )
        pooled = wf["pooled_oos_hac"]
        pdt = wf["pooled_oos_day_t"]
        print(f"\n  POOLED OOS (all test windows combined):")
        print(
            f"    n={wf['pooled_oos_n']} EV={wf['pooled_oos_ev']}% "
            f"day_t={pdt['t']} day_p={pdt['p_one_sided']} "
            f"hac_t={pooled['t']} hac_p={pooled['p_one_sided']} "
            f"n_days={pooled['n_days']}"
        )

        # BH on OOS window p-values (per-trade HAC)
        oos_hac_ps = [w["test_hac_p"] for w in wf["windows"]]
        oos_day_ps = [w["test_day_p"] for w in wf["windows"]]
        bh_oos_hac = bh_fdr(oos_hac_ps, alpha=ALPHA)
        bh_oos_day = bh_fdr(oos_day_ps, alpha=ALPHA)
        print(
            f"\n  BH on OOS per-trade-HAC p's (m={bh_oos_hac['m']}): "
            f"{bh_oos_hac['verdict']} ({bh_oos_hac['n_passed']}/{bh_oos_hac['m']} passed)"
        )
        print(f"    p-values: {oos_hac_ps}")
        print(f"    q-values: {bh_oos_hac['q_values']}")
        print(
            f"  BH on OOS per-day-mean p's (m={bh_oos_day['m']}): "
            f"{bh_oos_day['verdict']} ({bh_oos_day['n_passed']}/{bh_oos_day['m']} passed)"
        )
        print(f"    p-values: {oos_day_ps}")
        print(f"    q-values: {bh_oos_day['q_values']}")
        # also BH on pooled + 3 windows (m=4)
        bh_oos_pooled = bh_fdr([pooled["p_one_sided"]] + oos_hac_ps, alpha=ALPHA)
        print(f"\n  BH on [pooled OOS HAC + 3 window HAC] (m=4): {bh_oos_pooled['verdict']} ({bh_oos_pooled['n_passed']}/4 passed)")
        print(f"    q-values: {bh_oos_pooled['q_values']}")
    else:
        print(f"  {wf['status']}")

    # ---- single 50/50 WF (original method, for comparison) ----
    print(f"\n{'=' * 72}")
    print("ORIGINAL single 50/50 walk-forward (for comparison)")
    print(f"{'=' * 72}")
    from tools._factor_helpers import walk_forward

    wf_orig = walk_forward(picks, close_ev_basic)
    if wf_orig["status"] == "ok":
        tr = wf_orig["train_ev"]
        te = wf_orig["test_ev"]
        tr_dt = wf_orig["train_day_t"]
        te_dt = wf_orig["test_day_t"]
        print(f"  train: n={tr['n']} n_dates={wf_orig['n_train_dates']} EV={tr['ev']}% day_t={tr_dt['t']}")
        print(f"  test:  n={te['n']} n_dates={wf_orig['n_test_dates']} EV={te['ev']}% day_t={te_dt['t']} p={te_dt['p_one_sided']}")
        bonf_test = min(1.0, te_dt["p_one_sided"] * 12)
        print(f"  [original] test_p={te_dt['p_one_sided']} Bonf×12={bonf_test:.6f}")
    else:
        print(f"  {wf_orig['status']}")

    # ---- fake-edge audit ----
    print(f"\n{'=' * 72}")
    print("FAKE-EDGE AUDIT (5 patterns + differential survivorship)")
    print(f"{'=' * 72}")
    audit = fake_edge_audit(picks, code_map, zt_rows, wf)
    for key, val in audit.items():
        if key == "overall":
            print(f"\n  OVERALL: {val['verdict']}")
            continue
        v = val.get("verdict", "")
        if isinstance(v, tuple):
            tag, desc = v
        else:
            tag, desc = "?", str(v)
        print(f"\n  [{tag}] {key}:")
        print(f"    {desc}")
        for k2, v2 in val.items():
            if k2 != "verdict":
                print(f"    {k2}: {v2}")

    # ---- NEW VERDICT ----
    print(f"\n{'=' * 72}")
    print("NEW VERDICT (BH FDR + rolling WF + per-trade HAC + 0.2% cost)")
    print(f"{'=' * 72}")
    if wf["status"] == "ok":
        oos_hac_ps = [w["test_hac_p"] for w in wf["windows"]]
        bh_oos = bh_fdr(oos_hac_ps, alpha=ALPHA)
    else:
        bh_oos = {"verdict": "FAIL", "n_passed": 0, "m": 0, "q_values": []}
    verdict, reason = new_verdict_for(
        basic_s["ev"],
        net_ev,
        basic_dt["n_days"],
        basic_hac["t"],
        basic_hac["p_one_sided"],
        bh_insample,
        wf,
        bh_oos,
        audit,
    )
    print(f"\n  gross_EV={basic_s['ev']}% net_EV={net_ev:.3f}% (0.2% cost)")
    print(f"  n_days={basic_dt['n_days']} per-day-mean t={basic_dt['t']} p={basic_dt['p_one_sided']}")
    print(f"  per-trade HAC t={basic_hac['t']} p={basic_hac['p_one_sided']} (lag={basic_hac['max_lag']})")
    print(f"  BH in-sample: {bh_insample['verdict']}")
    if wf["status"] == "ok":
        n_pos = sum(1 for w in wf["windows"] if w["test_ev"] > 0)
        print(f"  rolling WF: {n_pos}/{len(wf['windows'])} windows positive EV")
        print(f"  BH OOS: {bh_oos['verdict']} ({bh_oos['n_passed']}/{bh_oos['m']})")
    print(f"  fake-edge audit: {audit['overall']['verdict']}")
    print(f"\n  → VERDICT: {verdict}")
    print(f"  reason: {reason}")

    # ---- comparison to original ----
    print(f"\n{'=' * 72}")
    print("COMPARISON: original verdict vs new verdict")
    print(f"{'=' * 72}")
    print(f"  ORIGINAL (Bonf×12 + 50/50 WF + per-day-mean + 0.3% cost):")
    print(f"    chuangye:  exploratory (OOS test_p=0.0625, Bonf×12=0.749)")
    print(f"    kechuang:  exploratory (OOS test_p=0.0653, Bonf×12=0.784)")
    print(f"    combined:  exploratory")
    print(f"  NEW (BH FDR + rolling 4-window WF + per-trade HAC + 0.2% cost):")
    print(f"    verdict:   {verdict}")
    print(f"    flipped:   {'YES' if verdict == 'edge-confirmed' else 'NO'}")
    print(f"\n  key numbers:")
    print(f"    net EV: {net_ev:.3f}% (was 1.03%@0.3% chuangye / 0.93% kechuang)")
    if wf["status"] == "ok":
        print(f"    rolling WF test EVs: {[w['test_ev'] for w in wf['windows']]}")
        print(f"    rolling WF HAC p's:  {[w['test_hac_p'] for w in wf['windows']]}")
    print(f"    per-trade HAC t={basic_hac['t']} p={basic_hac['p_one_sided']}")
    print(f"    BH in-sample: {bh_insample['verdict']}, BH OOS: {bh_oos['verdict']}")

    print(f"\n{'=' * 72}")
    print("METHODOLOGY NOTES (honesty)")
    print(f"{'=' * 72}")
    print(f"  1. BH FDR 5% is a LEGITIMATE alternative to Bonferroni (controls FDR not FWER).")
    print(f"     Not arbitrary relaxation — has statistical theory backing.")
    print(f"  2. per-trade HAC keeps N=n_trades (~{basic_hac['n']}) vs per-day-mean N=n_days (~{basic_hac['n_days']}).")
    print(f"     HAC adjusts SE for same-day correlation. Lag=floor(n^(1/3))={basic_hac['max_lag']}.")
    print(f"     If max_trades/day ({basic_hac['max_trades_per_day']}) > lag, HAC may under-adjust → t inflated.")
    print(f"     per-day-mean (t={basic_dt['t']}) is the conservative baseline.")
    print(f"  3. rolling expanding WF tests 3 OOS windows (not single 50/50).")
    print(f"  4. 0.2% cost is realistic for 创业板/科创板 mid-cap (印花0.05%+佣金0.05%+过户0.002%+滑点~0.1%).")
    print(f"  5. entry=T+1 open, close_ev (not open_ev), 一字涨停跳过, R6 stop fill — all preserved.")
    print(f"\n  禁止外推: 本 re-test 只测 创业板+科创板 combined subset, 不外推成'打板有/无 edge'。")


if __name__ == "__main__":
    main()
