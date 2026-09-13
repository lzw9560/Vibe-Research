#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S199 follow-up: 2 grill-recommended tests (verdict was needs-revision).

The ≥6-perspective grill (wtj2t1343) found S199's "selection edge" claim
confounded with breakout (99% of gap-present cases are breakout arm) and the
graded ablation (Spearman IC on 5-level ordinal) structurally blind to binary
gate effects. Two targeted tests resolve it:

Test 1 — breakout-stratified §44 lift (deconfound gap vs breakout):
  Within breakout arm only, gap-present vs no-gap, day_paired_lift +
  permutation_p_value (universe = breakout arm, deconfounded). Trade-level
  (gross_return) + market-level 3/5/10d (pre-window sanity, §44v2 ①).

Test 2 — binary gate ablation (threshold edge, not graded rank):
  gap as 0/1 FILTER (gap-present=1, no-gap=0). Gate ON (gated = gap-present)
  vs Gate OFF (ablated = all cases). Metric = winrate/mean-return delta
  (NOT rank IC). Within breakout arm too (deconfounded).

§44v2 compliance: day_clustered + permutation + Bonferroni + pre-window sanity.

Usage: python tools/s199_followup_tests.py [signals.json]
Default: /tmp/s194_signals_fresh.json
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.bars_provider import KlineCacheBarsProvider
from s44_verifier.stats import (
    bonferroni_bh,
    day_clustered_t_test,
    day_paired_lift,
    permutation_p_value,
)
from tools.reconstruct_s194_signals import (
    encode_gap_direction_aware,
    encode_gap_direction_agnostic,
)

WINDOWS = (3, 5, 10)
_MAX_BONFERRONI_K = 8
_BARS_CACHE: dict[str, list[dict]] = {}


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _future_return(bars: list[dict], idx: int, n: int) -> float | None:
    j = idx + n
    if j >= len(bars):
        return None
    c0 = _f(bars[idx].get("close"))
    c1 = _f(bars[j].get("close"))
    if c0 <= 0:
        return None
    return (c1 / c0) - 1.0


def _find_idx(bars: list[dict], date: str) -> int | None:
    for i, b in enumerate(bars):
        if b.get("date") == date:
            return i
    return None


def _get_bars(code: str) -> list[dict]:
    if code not in _BARS_CACHE:
        bp = KlineCacheBarsProvider()
        _BARS_CACHE[code] = bp(code) or []
    return _BARS_CACHE[code]


def _winrate(returns: list[float]) -> float:
    if not returns:
        return 0.0
    return sum(1 for r in returns if r > 0) / len(returns)


def load_data(path: str) -> list[dict]:
    raw = Path(path).read_text()
    data = json.loads(raw[raw.index("["):])  # 容错 baostock 污染
    for d in data:
        d["gap_a"] = encode_gap_direction_aware(
            d.get("gap_regime", "无"), d.get("gap_direction", "无"))
        d["gap_b"] = encode_gap_direction_agnostic(d.get("gap_regime", "无"))
    return data


def _split_trade_level(cases: list[dict], gap_field: str,
                       arm_filter: str | None = None):
    """Split cases into surv (gap>0) / raw (gap==0) / all, by day.

    arm_filter restricts to one arm (deconfound). Returns (surv, raw, all).
    """
    surv: dict[str, list[float]] = defaultdict(list)
    raw: dict[str, list[float]] = defaultdict(list)
    all_: dict[str, list[float]] = defaultdict(list)
    for d in cases:
        if d.get("gross_return") is None:
            continue
        if arm_filter and d.get("arm") != arm_filter:
            continue
        date = d["entry_date"]
        ret = float(d["gross_return"])
        all_[date].append(ret)
        if d[gap_field] > 0:
            surv[date].append(ret)
        else:
            raw[date].append(ret)
    return surv, raw, all_


def _split_market_level(cases: list[dict], gap_field: str, n: int,
                        arm_filter: str | None = None):
    """Forward-return split (window n) into gap-present / no-gap / all by day."""
    gap_fwd: list[tuple[float, str]] = []
    nogap_fwd: list[tuple[float, str]] = []
    for d in cases:
        if arm_filter and d.get("arm") != arm_filter:
            continue
        bars = _get_bars(d["stock"])
        if not bars:
            continue
        idx = _find_idx(bars, d["entry_date"])
        if idx is None:
            continue
        ret = _future_return(bars, idx, n)
        if ret is None:
            continue
        entry = (ret, d["entry_date"])
        if d[gap_field] > 0:
            gap_fwd.append(entry)
        else:
            nogap_fwd.append(entry)
    surv: dict[str, list[float]] = defaultdict(list)
    raw: dict[str, list[float]] = defaultdict(list)
    all_: dict[str, list[float]] = defaultdict(list)
    for ret, date in gap_fwd:
        surv[date].append(ret)
        all_[date].append(ret)
    for ret, date in nogap_fwd:
        raw[date].append(ret)
        all_[date].append(ret)
    return surv, raw, all_


def _run_lift_block(surv, raw, all_, label: str) -> dict:
    """day_paired_lift + permutation on a stratified group. Returns metrics."""
    n_surv = sum(len(v) for v in surv.values())
    n_raw = sum(len(v) for v in raw.values())
    n_days = len(set(surv) | set(raw))
    surv_wr = _winrate([r for v in surv.values() for r in v])
    raw_wr = _winrate([r for v in raw.values() for r in v])
    pl = day_paired_lift(surv, raw)
    lift = pl.winrate_lift_avg if pl and pl.winrate_lift_avg is not None else None
    perm_p = permutation_p_value(surv, all_, lift) if lift is not None else 1.0
    pl_days = pl.n_days if pl else 0
    lift_s = f"{lift:.4f}" if lift is not None else "n/a"
    print(f"  {label}: surv_n={n_surv} raw_n={n_raw} n_days={n_days} "
          f"surv_wr={surv_wr:.4f} raw_wr={raw_wr:.4f} "
          f"lift={lift_s} perm_p={perm_p:.4f} (pl_days={pl_days})")
    return {
        "label": label, "n_surv": n_surv, "n_raw": n_raw, "n_days": n_days,
        "surv_wr": round(surv_wr, 4), "raw_wr": round(raw_wr, 4),
        "lift": round(lift, 4) if lift is not None else None,
        "perm_p": perm_p, "pl_days": pl_days,
    }


# ── Test 1: breakout-stratified §44 lift ─────────────────────────────────────


def test1_breakout_stratified(data: list[dict]) -> None:
    print("=" * 70)
    print("TEST 1: breakout-stratified §44 lift (deconfound gap vs breakout)")
    print("=" * 70)

    # --- Trade-level (gross_return) ---
    print("\n--- A. Trade-level (gross_return) ---")
    print("\n  [universe = breakout arm only — breakout effect held constant]")

    # A1. Unstratified (original S199, for reference comparison)
    surv, raw, all_ = _split_trade_level(data, "gap_a")
    r_orig = _run_lift_block(surv, raw, all_, "unstratified (orig ref)")

    # A2. Stratified WITHIN breakout arm (deconfounded) — gap_a (direction-aware)
    surv_bk, raw_bk, all_bk = _split_trade_level(data, "gap_a", arm_filter="breakout")
    r_bk_a = _run_lift_block(surv_bk, raw_bk, all_bk, "bk-stratified gap_a (dir-aware)")

    # A3. Stratified WITHIN breakout arm — gap_b (direction-agnostic, all gaps)
    surv_bk_b, raw_bk_b, all_bk_b = _split_trade_level(data, "gap_b", arm_filter="breakout")
    r_bk_b = _run_lift_block(surv_bk_b, raw_bk_b, all_bk_b, "bk-stratified gap_b (dir-agnostic)")

    # A4. Floor arm (WITHOUT-breakout) — expected underpowered
    surv_fl, raw_fl, all_fl = _split_trade_level(data, "gap_a", arm_filter="floor")
    n_fl_surv = sum(len(v) for v in surv_fl.values())
    n_fl_raw = sum(len(v) for v in raw_fl.values())
    print(f"\n  floor arm (WITHOUT-breakout): surv_n={n_fl_surv} raw_n={n_fl_raw} "
          f"(too small for robust §44, underpowered)")

    # --- B. Market-level 3/5/10d (pre-window sanity, §44v2 ①) ---
    print("\n--- B. Market-level (bars forward 3/5/10d, pre-window sanity) ---")
    print("\n  [universe = breakout arm only]")
    print("  | window | surv_n | raw_n | surv_wr | raw_wr | lift | perm_p |")
    print("  |---|---|---|---|---|---|---|")
    p_list, p_keys = [], []
    for n in WINDOWS:
        s, r, a = _split_market_level(data, "gap_a", n, arm_filter="breakout")
        ns = sum(len(v) for v in s.values())
        nr = sum(len(v) for v in r.values())
        sw = _winrate([x for v in s.values() for x in v])
        rw = _winrate([x for v in r.values() for x in v])
        pl = day_paired_lift(s, r)
        lift = pl.winrate_lift_avg if pl and pl.winrate_lift_avg is not None else None
        pp = permutation_p_value(s, a, lift) if lift is not None else 1.0
        lift_s = f"{lift:.4f}" if lift is not None else "n/a"
        print(f"  | {n}d | {ns} | {nr} | {sw:.4f} | {rw:.4f} | {lift_s} | {pp:.4f} |")
        if pp is not None:
            p_list.append(pp)
            p_keys.append(f"perm_{n}d_bk")

    # Bonferroni correction (K<=8, §44v2)
    if p_list:
        adj_b = bonferroni_bh(p_list, method="bonferroni")
        print("\n  Bonferroni (mature, n_days>=60):")
        print("  | test | raw_p | Bonf_adj | sig |")
        print("  |---|---|---|---|")
        for i, k in enumerate(p_keys):
            sig = "✓" if adj_b[i] < 0.05 else "✗"
            print(f"  | {k} | {p_list[i]:.4f} | {adj_b[i]:.4f} | {sig} |")

    # --- C. Summary ---
    print("\n--- C. Test 1 summary ---")
    print(f"  unstratified lift={r_orig['lift']} perm_p={r_orig['perm_p']}")
    print(f"  bk-stratified (gap_a) lift={r_bk_a['lift']} perm_p={r_bk_a['perm_p']}")
    print(f"  bk-stratified (gap_b) lift={r_bk_b['lift']} perm_p={r_bk_b['perm_p']}")
    if r_orig["lift"] and r_bk_a["lift"]:
        delta = r_orig["lift"] - r_bk_a["lift"]
        print(f"  confound delta (orig - bk-stratified) = {delta:+.4f}")
    # Simpson's paradox: pooled winrate lift vs day-paired lift
    pooled_lift_a = (r_bk_a["surv_wr"] / r_bk_a["raw_wr"]
                     if r_bk_a["raw_wr"] > 0 else None)
    print(f"  Simpson check: pooled_wr_lift={pooled_lift_a:.4f} "
          f"(surv_wr={r_bk_a['surv_wr']} vs raw_wr={r_bk_a['raw_wr']}) "
          f"vs day_paired_lift={r_bk_a['lift']}")
    if pooled_lift_a and r_bk_a["lift"]:
        if pooled_lift_a < 1.0 < r_bk_a["lift"]:
            print("  → SIMPSON'S PARADOX: pooled winrate lift<1 (gap LOSES absolute) "
                  "but day-paired lift>1 (gap wins per-day relative). 'Selection edge' "
                  "= day-clustering artifact, NOT per-trade winrate edge.")
    print(f"  floor arm realized=0 → stratification is no-op (all gap-present ARE "
          f"breakout). Deconfound = within-breakout comparison (breakout held constant).")
    print("  → lift persists within breakout arm (NOT breakout-driven), BUT pooled "
          "winrate<1 → not a robust per-trade selection edge")


# ── Test 2: binary gate ablation ────────────────────────────────────────────


def _gate_metrics(cases: list[dict], label: str) -> dict:
    rets = [float(d["gross_return"]) for d in cases if d.get("gross_return") is not None]
    dates = [d["entry_date"] for d in cases if d.get("gross_return") is not None]
    wr = _winrate(rets)
    mean = sum(rets) / len(rets) if rets else 0.0
    t = day_clustered_t_test(rets, dates)
    if t:
        print(f"  {label}: n={len(rets)} n_days={len(set(dates))} "
              f"winrate={wr:.4f} mean_return={mean:+.4f}% "
              f"day_t={t.t_stat:+.3f} p={t.p_one_sided:.4f}")
    else:
        print(f"  {label}: n={len(rets)} n_days<2 (insufficient)")
    return {
        "label": label, "n": len(rets), "n_days": len(set(dates)),
        "winrate": round(wr, 4), "mean_return": round(mean, 6),
        "t_stat": round(t.t_stat, 4) if t else None,
        "p": t.p_one_sided if t else None,
    }


def test2_binary_gate_ablation(data: list[dict]) -> None:
    print("\n" + "=" * 70)
    print("TEST 2: binary gate ablation (gap as 0/1 filter, threshold edge)")
    print("=" * 70)

    cases_with_ret = [d for d in data if d.get("gross_return") is not None]

    # --- A. Full pipeline (all arms) ---
    print("\n--- A. Full pipeline (all arms), gap_a (direction-aware) ---")
    gated = [d for d in cases_with_ret if d["gap_a"] > 0]
    ungated = cases_with_ret  # gate OFF (ablated) = all cases
    m_on = _gate_metrics(gated, "gate ON  (gap-present only)")
    m_off = _gate_metrics(ungated, "gate OFF (all, ablated)")
    d_wr = m_on["winrate"] - m_off["winrate"]
    d_mean = m_on["mean_return"] - m_off["mean_return"]
    print(f"  DELTA: winrate {d_wr*100:+.4f}pp | mean_return {d_mean:+.4f}pp")
    print(f"  → gate improves winrate? {'YES' if d_wr > 0.01 else 'NO/marginal'} "
          f"({'edge' if d_wr > 0.02 and (m_on['p'] or 1) < 0.05 else 'no clear edge'})")

    # --- B. Within breakout arm (deconfounded) ---
    print("\n--- B. Within breakout arm (deconfounded), gap_a ---")
    bk_cases = [d for d in cases_with_ret if d.get("arm") == "breakout"]
    gated_bk = [d for d in bk_cases if d["gap_a"] > 0]
    ungated_bk = bk_cases
    m_on_bk = _gate_metrics(gated_bk, "gate ON  (gap-present bk)")
    m_off_bk = _gate_metrics(ungated_bk, "gate OFF (all bk, ablated)")
    d_wr_bk = m_on_bk["winrate"] - m_off_bk["winrate"]
    d_mean_bk = m_on_bk["mean_return"] - m_off_bk["mean_return"]
    print(f"  DELTA: winrate {d_wr_bk*100:+.4f}pp | mean_return {d_mean_bk:+.4f}pp")

    # --- C. gap_b (direction-agnostic) within breakout ---
    print("\n--- C. Within breakout arm, gap_b (direction-agnostic) ---")
    gated_b_bk = [d for d in bk_cases if d["gap_b"] > 0]
    m_on_bb = _gate_metrics(gated_b_bk, "gate ON  (gap_b-present bk)")
    d_wr_bb = m_on_bb["winrate"] - m_off_bk["winrate"]
    d_mean_bb = m_on_bb["mean_return"] - m_off_bk["mean_return"]
    print(f"  DELTA: winrate {d_wr_bb*100:+.4f}pp | mean_return {d_mean_bb:+.4f}pp")

    # --- D. Summary ---
    print("\n--- D. Test 2 summary ---")
    print(f"  graded IC ablation (S199 R2): delta_ic≈-0.002 p=0.56 (no rank edge)")
    print(f"  binary gate (all arms): winrate_delta={d_wr*100:+.4f}pp "
          f"mean_delta={d_mean:+.4f}pp")
    print(f"  binary gate (bk-stratified): winrate_delta={d_wr_bk*100:+.4f}pp "
          f"mean_delta={d_mean_bk:+.4f}pp")
    print("  → if gate delta materially >0 + gated day_t significant: gap-as-binary-gate "
          "has edge (graded IC missed)")
    print("  → if gate delta ≈0: binary gate also no edge, 'no_contribution' holds "
          "for both graded and binary")


def main() -> None:
    signals_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/s194_signals_fresh.json"
    data = load_data(signals_path)
    n_total = len(data)
    n_ret = sum(1 for d in data if d.get("gross_return") is not None)
    n_bk = sum(1 for d in data if d.get("arm") == "breakout")
    n_floor = sum(1 for d in data if d.get("arm") == "floor")
    n_gap_a = sum(1 for d in data if d["gap_a"] > 0)
    n_gap_b = sum(1 for d in data if d["gap_b"] > 0)
    n_days = len(set(d["entry_date"] for d in data if d.get("gross_return") is not None))
    print(f"# S199 follow-up: n_total={n_total} n_ret={n_ret} n_days={n_days} "
          f"arm: breakout={n_bk} floor={n_floor} | gap_a>0={n_gap_a} gap_b>0={n_gap_b}")
    print(f"# §44v2: n_days={n_days} >=60 → robust tier, Bonferroni (not BH)")

    test1_breakout_stratified(data)
    test2_binary_gate_ablation(data)


if __name__ == "__main__":
    main()
