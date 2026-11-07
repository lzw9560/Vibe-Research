# -*- coding: utf-8 -*-
"""因子 turn-tier —— 换手率 tier 分层: 10-20% / 20-30% / 30-50% / >50%.

假设: S232 用 turn>20% blanket 信号 lift 5.28x 但交易 EV -0.87% 负。
>50% 可能是出货 (极值反转) 非吸筹。本脚本按 turn tier 分层测 close_ev。

数据源: kline DB bar.turn 字段 (baostock 换手率 %, median 2.38%, 已确认是百分比)。
无需 join S232 watchlist (kline 有 turn 直接用, 覆盖 2024-06-03~2026-09-30)。

过严口径 (§44 v3, 必过):
- entry = T+1 open (非 T+1 close, 一字涨停跳过)
- close_ev 非 open_ev (防 T+1 日内泄漏)
- R6 gap-through fill (跳空穿 stop 按 t2_open + 滑点)
- per-day-mean t (非 per-trade t)
- Bonferroni cross-factor ×12 (6 因子 × 2 子集)
- walk-forward OOS (前半 train → 后半 test)
- 禁止外推: 单因子 ≠ 打板有/无 edge
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from tools._factor_helpers import (
    analyze_subset,
    build_picks_generic,
    close_ev_basic,
    close_ev_stop,
    load_kline_db,
    load_zt,
    verdict_for,
    ALPHA,
)

# ---------- tier definitions (turn % on zt-day = t_bar) ----------

TIERS: list[tuple[str, float, float]] = [
    # (name, lo_inclusive, hi_exclusive)  hi=float("inf") = unbounded
    ("turn_10-20", 10.0, 20.0),
    ("turn_20-30", 20.0, 30.0),
    ("turn_30-50", 30.0, 50.0),
    ("turn_gt50", 50.0, float("inf")),
]

N_CROSS_FACTOR = 6  # 6 因子并行测试 → Bonferroni ×6*2=×12


def make_turn_filter(lo: float, hi: float) -> Callable[[str, int, dict, dict, dict], bool]:
    """filter_fn: t_bar.turn in [lo, hi). None/缺失 turn → False (跳过)."""

    def _f(code: str, lbc: int, t_bar: dict, t1_bar: dict, t2_bar: dict) -> bool:
        t = t_bar.get("turn")
        if t is None:
            return False
        return lo <= t < hi

    return _f


def make_all_valid_turn_filter() -> Callable[[str, int, dict, dict, dict], bool]:
    """baseline: 任意 turn (但必须有 turn 数据, 非 None)."""

    def _f(code: str, lbc: int, t_bar: dict, t1_bar: dict, t2_bar: dict) -> bool:
        return t_bar.get("turn") is not None

    return _f


def main() -> None:
    print("=" * 70)
    print("因子 turn-tier —— 换手率 tier 分层 close_ev 分析")
    print("=" * 70)

    # ---- load data ----
    print("\n[1] 加载 kline DB + zt_history ...")
    code_map, all_dates = load_kline_db()
    zt_rows = load_zt()
    calendar = sorted(all_dates)
    print(f"  kline codes={len(code_map)} calendar days={len(calendar)} zt_rows={len(zt_rows)}")
    print(f"  zt date range: {min(d for d, _, _ in zt_rows)} ~ {max(d for d, _, _ in zt_rows)}")

    # ---- baseline: all picks with valid turn (no tier filter) ----
    print("\n[2] baseline: 全部 zt picks (有 turn 数据, 无 tier 过滤)")
    baseline_picks = build_picks_generic(code_map, calendar, zt_rows, filter_fn=make_all_valid_turn_filter())
    baseline_res = analyze_subset(
        "baseline_all_valid_turn",
        baseline_picks,
        ret_fn_basic=close_ev_basic,
        ret_fn_stop=close_ev_stop,
        ret_fn_label="close_ev",
    )

    # ---- per-tier analysis ----
    print("\n\n[3] per-tier close_ev 分析 (4 tiers)")
    tier_results: list[dict] = []
    for name, lo, hi in TIERS:
        label = f"{name}({lo:.0f}-{hi:.0f}%)" if hi != float("inf") else f"{name}(>={lo:.0f}%)"
        print(f"\n\n>>> tier: {label}")
        picks = build_picks_generic(code_map, calendar, zt_rows, filter_fn=make_turn_filter(lo, hi))
        res = analyze_subset(
            name,
            picks,
            ret_fn_basic=close_ev_basic,
            ret_fn_stop=close_ev_stop,
            ret_fn_label="close_ev",
        )
        tier_results.append(res)

    # ---- verdicts per tier ----
    print("\n\n" + "=" * 70)
    print("[4] 诚实判定 (verdict_for, Bonferroni cross-factor ×12)")
    print("=" * 70)

    verdicts: list[tuple[str, str]] = []
    for res in tier_results:
        name = res["name"]
        n_picks = res.get("n_picks", 0)
        if n_picks == 0:
            print(f"\n  {name}: 无 picks → no-data")
            verdicts.append((name, "no-data"))
            continue

        basic = res["basic_ev"]
        basic_dt = res["basic_day_t"]
        wf = res.get("wf_basic", {})

        net_ev = basic["ev"] - 0.3  # COST=0.003 → 0.3%

        v = verdict_for(
            ev_gross=basic["ev"],
            t_day=basic_dt["t"],
            p_raw=basic_dt["p_one_sided"],
            wf_status=wf.get("status", "no_picks"),
            wf_train_ev=wf.get("train_ev", {}).get("ev", 0.0) if wf.get("status") == "ok" else 0.0,
            wf_test_ev=wf.get("test_ev", {}).get("ev", 0.0) if wf.get("status") == "ok" else 0.0,
            wf_test_p=wf.get("test_day_t", {}).get("p_one_sided", 1.0) if wf.get("status") == "ok" else 1.0,
            n_days=basic_dt["n_days"],
            net_ev=net_ev,
            subset_name=name,
            n_cross_factor=N_CROSS_FACTOR,
        )
        verdicts.append((name, v))

    # ---- summary ----
    print("\n\n" + "=" * 70)
    print("[5] 汇总")
    print("=" * 70)
    print(
        f"\n{'tier':<20} {'n_picks':>8} {'n_days':>7} {'gross_ev%':>10} "
        f"{'net_ev%':>9} {'day_t':>7} {'p_raw':>9} {'verdict':<16}"
    )
    print("-" * 90)

    # baseline row
    b = baseline_res
    if b.get("n_picks", 0) > 0:
        be = b["basic_ev"]
        bdt = b["basic_day_t"]
        print(
            f"{'baseline(all turn)':<20} {b['n_picks']:>8} {bdt['n_days']:>7} "
            f"{be['ev']:>10.3f} {be['ev'] - 0.3:>9.3f} {bdt['t']:>7.2f} "
            f"{bdt['p_one_sided']:>9.4f} {'(reference)':<16}"
        )

    for res, (name, v) in zip(tier_results, verdicts):
        np_ = res.get("n_picks", 0)
        if np_ == 0:
            print(f"{name:<20} {0:>8} {0:>7} {'N/A':>10} {'N/A':>9} {'N/A':>7} {'N/A':>9} {v:<16}")
            continue
        be = res["basic_ev"]
        bdt = res["basic_day_t"]
        print(
            f"{name:<20} {np_:>8} {bdt['n_days']:>7} {be['ev']:>10.3f} "
            f"{be['ev'] - 0.3:>9.3f} {bdt['t']:>7.2f} {bdt['p_one_sided']:>9.4f} "
            f"{v:<16}"
        )

    # ---- factor-level honest verdict ----
    print("\n" + "=" * 70)
    print("[6] 因子级诚实判定 (综合 4 tiers)")
    print("=" * 70)
    non_no_data = [v for _, v in verdicts if v != "no-data"]
    if not non_no_data:
        factor_verdict = "no-data"
        print("  所有 tier 无数据 → no-data")
    elif any(v == "edge-confirmed" for v in non_no_data):
        factor_verdict = "edge-confirmed"
        confirmed = [n for n, v in verdicts if v == "edge-confirmed"]
        print(f"  edge-confirmed tiers: {confirmed}")
    elif any(v == "exploratory" for v in non_no_data):
        factor_verdict = "exploratory"
        expl = [n for n, v in verdicts if v == "exploratory"]
        print(f"  exploratory tiers (OOS EV>0 但未显著): {expl}")
    elif any(v == "underpowered" for v in non_no_data):
        factor_verdict = "underpowered"
        under = [n for n, v in verdicts if v == "underpowered"]
        print(f"  underpowered tiers (n_days<60): {under}")
        falsified = [n for n, v in verdicts if v == "falsified"]
        if falsified:
            print(f"  falsified tiers: {falsified}")
    else:
        factor_verdict = "edge-falsified"
        print(f"  所有 tier falsified (gross EV<0 或 Bonferroni NS 或 net<=0 或 OOS test<=0)")

    print(f"\n  >>> 因子级 verdict: {factor_verdict}")

    # ---- R6 + realistic entry note ----
    print("\n[7] R6 + realistic entry 说明:")
    print("  - entry = T+1 open (非 T+1 close, 一字涨停已跳过) → realistic_entry_used=True")
    print("  - close_ev (T+1 open 买 → T+2 close 卖), 非 open_ev (防日内泄漏)")
    print("  - R6 gap-through fill 已在 stop variant 应用 (跳空穿 stop 按 t2_open + 0.2% 滑点)")
    print("  - stop variant 仅作 robustness check, 主判定用 basic close_ev (无 stop)")


if __name__ == "__main__":
    main()
