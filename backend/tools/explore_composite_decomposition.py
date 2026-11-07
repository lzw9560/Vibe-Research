# -*- coding: utf-8 -*-
"""composite-score 正交分解: 5 component 单独 + leave-one-out.

分解 composite-score top-5 的 driver:
  - 每个 component 单独 per-date percentile-rank top-5 → close_ev + per-day-t
    + Bonf×10 + walk-forward + verdict_for(n_cross_factor=5)
  - leave-one-out: composite 去掉一个 component → top-5 close_ev → delta
    (composite - loo, 正值=该 component 正向贡献)
  - driver = alone EV 最高 + leave-one-out delta 最大
  - 判定 driver 含义: entry-timing(gap)/inherited-falsified(lbc)/new-signal(gene/turn/vr5)

方法论:
  - 同 universe (all-5-present picks) 对比——alone/loo/composite 用同一样本,
    delta 纯粹反映 component 贡献非样本变化
  - alone: 单因子 weights={comp:1, others:0} → composite = pct[comp]
    (per-date 单因子百分位 = 单因子 raw value 排序, 百分位单调)
  - loo: 去掉一因子 weights={comp:0, others:1/4} → 4-factor composite

诚实约束 (P1 + 6 假 edge 教训):
  - gene_score 仅覆盖 2026-01-05+ (183 天), composite universe 受限该窗口
  - _collect_zt_history_batch 实际只回溯 29 天非 250 → gene_score 更
    regime-dependent 更噪
  - 全 2026 单 regime (174 天 Jan-Sep), 分解结果不外推 cross-regime
  - entry=T+1 open, 一字涨停跳过, close_ev 非 open_ev (R6 gap-through fill)
  - per-day-mean t 非 per-trade t
  - Bonferroni cross-component ×10 (5 component × 2: alone + loo)
  - 禁止外推: component driver ≠ 打板有/无 edge

跑法:
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
  .venv/bin/python tools/explore_composite_decomposition.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Setup sys.path for tools._factor_helpers import
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._factor_helpers import (  # noqa: E402  DRY: 禁复制 helper 代码
    COST,
    analyze_subset,
    bonferroni_p,
    close_ev_basic,
    close_ev_stop,
    build_picks_generic,
    load_kline_db,
    load_zt,
    verdict_for,
)

# ---- DRY: 复用 composite-score 模块函数 (hyphenated filename → importlib) ----
_cs_path = Path(__file__).resolve().parent / "explore_factor_composite-score.py"
_spec = importlib.util.spec_from_file_location("explore_composite_score", str(_cs_path))
_cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cs)

# Reuse composite-score functions (不复制 attach_factors/compute_composite)
FACTORS: list[str] = _cs.FACTORS  # ["turn", "vr5", "gap", "lbc", "gene_score"]
load_gene_scores = _cs.load_gene_scores
attach_factors = _cs.attach_factors
compute_composite = _cs.compute_composite
select_topk_by_composite = _cs.select_topk_by_composite

N_COMPONENTS = 5  # 5 component 并行 → cross-component Bonferroni ×5*2=×10

# Short names for structured output (gene_score → gene)
SHORT_NAME = {"gene_score": "gene"}


def _short(f: str) -> str:
    return SHORT_NAME.get(f, f)


# ---------- weight builders (immutable: return new dict) ----------


def _alone_weights(comp: str) -> dict[str, float]:
    """单因子权重: 1.0 for comp, 0 for others. → composite = pct[comp]."""
    return {f: (1.0 if f == comp else 0.0) for f in FACTORS}


def _loo_weights(comp: str) -> dict[str, float]:
    """leave-one-out 权重: 0 for removed comp, equal for others."""
    others = [f for f in FACTORS if f != comp]
    eq = 1.0 / len(others)
    return {f: (0.0 if f == comp else eq) for f in FACTORS}


# ---------- main ----------


def main() -> None:
    print("=" * 70)
    print("composite-score 正交分解 (5 component 单独 + leave-one-out)")
    print(f"  components: {', '.join(FACTORS)}")
    print(f"  cross-component Bonferroni: ×{N_COMPONENTS * 2} (5 component × 2)")
    print("=" * 70)

    # ---- load data ----
    print("\n[1] 加载 kline DB + zt_history + gene_scores ...")
    code_map, all_dates = load_kline_db()
    zt_rows = load_zt()
    gene, n_gene = load_gene_scores()
    calendar = sorted(all_dates)
    print(f"  kline codes={len(code_map)} calendar days={len(calendar)} zt_rows={len(zt_rows)}")
    print(f"  zt date range: {min(d for d, _, _ in zt_rows)} ~ {max(d for d, _, _ in zt_rows)}")
    print(
        f"  gene_scores: {n_gene} rows, {len(gene)} dates "
        f"({min(gene) if gene else 'N/A'} ~ {max(gene) if gene else 'N/A'})"
    )

    # ---- build blanket picks ----
    print("\n[2] 构建 blanket picks (entry=T+1 open, exit=T+2 close, 一字涨停跳过)…")
    blanket = build_picks_generic(code_map, calendar, zt_rows, filter_fn=None)
    print(f"  blanket picks: {len(blanket)}")

    # ---- attach 5 factors ----
    print("\n[3] 附 5 因子 (turn/vr5/gap/lbc/gene_score) ...")
    blanket, n_complete, counts = attach_factors(blanket, code_map, gene)
    print(
        f"  5 因子全有 (composite universe): {n_complete} ({n_complete / max(len(blanket), 1) * 100:.1f}% of blanket)"
    )
    print(f"  各因子覆盖:")
    for f in FACTORS:
        c = counts[f]
        print(f"    {f:<12}: {c:>5} ({c / max(len(blanket), 1) * 100:.1f}%)")

    if n_complete == 0:
        print("\n  → no-data: 无 pick 5 因子全有, 无法分解")
        return

    # all-5-present universe (same for ALL analyses — fair comparison)
    universe = [p for p in blanket if all(p.get(f) is not None for f in FACTORS)]
    comp_dates = sorted({p["zt_date"] for p in universe})
    print(f"  universe dates: {len(comp_dates)} ({comp_dates[0]} ~ {comp_dates[-1]})")

    # ---- [4] composite baseline (equal weight) ----
    print(f"\n{'=' * 70}")
    print("[4] composite baseline (equal-weight, top-5/day)")
    print(f"{'=' * 70}")
    equal_w = {f: 1.0 / len(FACTORS) for f in FACTORS}
    compute_composite(blanket, weights=equal_w)
    comp_top5 = select_topk_by_composite(blanket, 5)
    r_comp = analyze_subset(
        "composite-top5 (equal-weight)",
        comp_top5,
        ret_fn_basic=close_ev_basic,
        ret_fn_stop=close_ev_stop,
        ret_fn_label="close_ev",
    )
    comp_ev = r_comp.get("basic_ev", {}).get("ev", 0.0)
    comp_dt = r_comp.get("basic_day_t", {})
    comp_wf = r_comp.get("wf_basic", {})
    comp_wfs = comp_wf.get("status", "no_picks")
    comp_net = comp_ev - COST * 100
    print(f"\n  >>> composite top-5: gross_EV={comp_ev}% net_EV={comp_net}%")

    # ---- [5] each component ALONE (single-factor percentile rank top-5) ----
    print(f"\n{'=' * 70}")
    print(f"[5] 各 component 单独 (single-factor percentile-rank top-5/day)")
    print(f"    Bonferroni ×{N_COMPONENTS * 2} (5 component × 2)")
    print(f"{'=' * 70}")

    alone_results: dict[str, dict] = {}
    for comp in FACTORS:
        w = _alone_weights(comp)
        compute_composite(blanket, weights=w)
        top5 = select_topk_by_composite(blanket, 5)
        r = analyze_subset(
            f"alone-{_short(comp)}",
            top5,
            ret_fn_basic=close_ev_basic,
            ret_fn_stop=close_ev_stop,
            ret_fn_label="close_ev",
        )
        ev = r.get("basic_ev", {}).get("ev", 0.0)
        dt = r.get("basic_day_t", {})
        wf = r.get("wf_basic", {})
        wfs = wf.get("status", "no_picks")
        t_day = dt.get("t", 0.0)
        p_raw = dt.get("p_one_sided", 1.0)
        n_days = dt.get("n_days", 0)
        net_ev = ev - COST * 100
        bonf = bonferroni_p(p_raw, N_COMPONENTS * 2)
        wf_train_ev = wf.get("train_ev", {}).get("ev", 0.0) if wfs == "ok" else 0.0
        wf_test_ev = wf.get("test_ev", {}).get("ev", 0.0) if wfs == "ok" else 0.0
        wf_test_p = wf.get("test_day_t", {}).get("p_one_sided", 1.0) if wfs == "ok" else 1.0
        v = verdict_for(
            ev,
            t_day,
            p_raw,
            wfs,
            wf_train_ev,
            wf_test_ev,
            wf_test_p,
            n_days,
            net_ev,
            f"alone-{_short(comp)}",
            n_cross_factor=N_COMPONENTS,
        )
        alone_results[comp] = {
            "ev": ev,
            "net_ev": net_ev,
            "t_day": t_day,
            "p_raw": p_raw,
            "bonf": bonf,
            "n_days": n_days,
            "wf_status": wfs,
            "wf_train_ev": wf_train_ev,
            "wf_test_ev": wf_test_ev,
            "wf_test_p": wf_test_p,
            "verdict": v,
            "n_picks": len(top5),
        }

    # ---- [6] leave-one-out (composite minus each component) ----
    print(f"\n{'=' * 70}")
    print(f"[6] leave-one-out (composite 去掉每个 component, top-5/day)")
    print(f"    delta = composite - leave_one_out (正值=该 component 正向贡献)")
    print(f"{'=' * 70}")

    loo_results: dict[str, dict] = {}
    for comp in FACTORS:
        w = _loo_weights(comp)
        compute_composite(blanket, weights=w)
        top5 = select_topk_by_composite(blanket, 5)
        r = analyze_subset(
            f"loo-without-{_short(comp)}",
            top5,
            ret_fn_basic=close_ev_basic,
            ret_fn_stop=close_ev_stop,
            ret_fn_label="close_ev",
        )
        ev = r.get("basic_ev", {}).get("ev", 0.0)
        delta = comp_ev - ev
        loo_results[comp] = {
            "ev": ev,
            "delta": delta,
            "n_picks": len(top5),
        }
        sign = "+" if delta > 0 else ""
        tag = "(component helped)" if delta > 0 else "(component hurt)"
        print(f"  without {_short(comp):<6}: EV={ev:+.3f}%  delta={sign}{delta:.3f}%  {tag}")

    # ---- [7] driver identification ----
    print(f"\n{'=' * 70}")
    print("[7] driver 识别")
    print(f"{'=' * 70}")

    alone_ranked = sorted(FACTORS, key=lambda f: alone_results[f]["ev"], reverse=True)
    print(f"\n  alone top-5 EV ranking (高→低):")
    for f in alone_ranked:
        r = alone_results[f]
        print(
            f"    {_short(f):<6}: EV={r['ev']:+.3f}%  t={r['t_day']:.2f}  "
            f"Bonf×10={r['bonf']:.6f}  verdict={r['verdict']}"
        )

    loo_ranked = sorted(FACTORS, key=lambda f: loo_results[f]["delta"], reverse=True)
    print(f"\n  leave-one-out delta ranking (大正向贡献→负):")
    for f in loo_ranked:
        r = loo_results[f]
        print(f"    {_short(f):<6}: loo_EV={r['ev']:+.3f}%  delta={r['delta']:+.3f}%")

    best_alone = alone_ranked[0]
    best_loo = loo_ranked[0]
    agree = best_alone == best_loo
    print(f"\n  best alone EV:  {_short(best_alone)} (EV={alone_results[best_alone]['ev']:+.3f}%)")
    print(f"  best loo delta: {_short(best_loo)} (delta={loo_results[best_loo]['delta']:+.3f}%)")

    # driver = highest alone EV (standalone power); loo as supporting evidence
    driver = best_alone
    driver_map = {
        "gap": "entry-timing",
        "lbc": "inherited-falsified",
        "gene_score": "new-signal",
        "turn": "new-signal",
        "vr5": "new-signal",
    }
    implication = driver_map.get(driver, "unknown")

    print(f"\n  → driver: {_short(driver)} ({implication})")
    if agree:
        print(f"    (alone best == loo best → 一致, driver 清晰)")
    else:
        print(
            f"    (alone best={_short(best_alone)} ≠ loo best={_short(best_loo)} "
            f"— 不一致, 以 alone standalone EV 为主 driver; "
            f"loo delta 反映 composite 内冗余/独特性)"
        )

    # ---- [8] summary table ----
    print(f"\n{'=' * 70}")
    print("[8] 汇总 (close_ev %, per-day-mean t, Bonf×10, walk-forward, verdict)")
    print(f"{'=' * 70}")
    hdr = (
        f"  {'component':<10} {'mode':>6} {'n':>5} {'days':>5} "
        f"{'gross%':>8} {'net%':>7} {'day_t':>6} {'p_raw':>8} "
        f"{'Bonf×10':>9} {'wf_tr%':>7} {'wf_te%':>7} {'verdict':<16}"
    )
    print(hdr)
    print(f"  {'-' * 100}")
    # composite baseline
    wf_tr_c = comp_wf.get("train_ev", {}).get("ev", 0.0) if comp_wfs == "ok" else 0.0
    wf_te_c = comp_wf.get("test_ev", {}).get("ev", 0.0) if comp_wfs == "ok" else 0.0
    print(
        f"  {'composite':<10} {'base':>6} {len(comp_top5):>5} "
        f"{comp_dt.get('n_days', 0):>5} {comp_ev:>+8.3f} {comp_net:>+7.3f} "
        f"{comp_dt.get('t', 0):>6.2f} {comp_dt.get('p_one_sided', 1):>8.4f} "
        f"{'(baseline)':>9} {wf_tr_c:>+7.3f} {wf_te_c:>+7.3f} "
        f"{'(baseline)':<16}"
    )
    for comp in FACTORS:
        r = alone_results[comp]
        print(
            f"  {_short(comp):<10} {'alone':>6} {r['n_picks']:>5} "
            f"{r['n_days']:>5} {r['ev']:>+8.3f} {r['net_ev']:>+7.3f} "
            f"{r['t_day']:>6.2f} {r['p_raw']:>8.4f} {r['bonf']:>9.6f} "
            f"{r['wf_train_ev']:>+7.3f} {r['wf_test_ev']:>+7.3f} "
            f"{r['verdict']:<16}"
        )
    print(f"  {'-' * 100}")
    for comp in FACTORS:
        r = loo_results[comp]
        print(
            f"  {_short(comp):<10} {'loo':>6} {r['n_picks']:>5} {'-':>5} "
            f"{r['ev']:>+8.3f} {'-':>7} {'-':>6} {'-':>8} {'-':>9} "
            f"{'-':>7} {'-':>7} Δ={r['delta']:+.3f}%"
        )

    # ---- [9] honest notes ----
    _print_honest_notes(driver, implication, comp_ev, comp_net, alone_results, loo_results, best_alone, best_loo, agree)

    # ---- [EXTRACTION] machine-parseable key numbers ----
    print(f"\n{'=' * 70}")
    print("[EXTRACTION] key numbers (for structured output)")
    print(f"{'=' * 70}")
    print(f"composite_top5_ev={comp_ev}")
    print(f"composite_top5_net={round(comp_net, 3)}")
    for comp in FACTORS:
        ar = alone_results[comp]
        lr = loo_results[comp]
        print(
            f"component={_short(comp)} alone_ev={ar['ev']} "
            f"alone_t={ar['t_day']} alone_bonf={ar['bonf']} "
            f"alone_verdict={ar['verdict']} "
            f"loo_ev={lr['ev']} loo_delta={round(lr['delta'], 3)}"
        )
    print(f"driver={_short(driver)} implication={implication}")
    print(f"best_alone={_short(best_alone)} best_loo={_short(best_loo)} agree={agree}")


def _print_honest_notes(
    driver: str,
    implication: str,
    comp_ev: float,
    comp_net: float,
    alone_results: dict,
    loo_results: dict,
    best_alone: str,
    best_loo: str,
    agree: bool,
) -> None:
    print(f"\n{'=' * 70}")
    print("诚实注解")
    print(f"{'=' * 70}")
    print("1. 测了什么: composite-score 5 component (turn/vr5/gap/lbc/gene_score)")
    print("   的正交分解——每个 component 单独 top-5 + leave-one-out, 在同一")
    print("   universe (all-5-present picks) 上比较 close_ev。")
    print("2. 没测什么: component driver ≠ 打板有/无 edge; 未测 cross-regime;")
    print("   未测盘中可交易性细节; alone/loo 用同 universe (all-5-present) 非")
    print("   各自最大 universe——结果被条件化了 (只看 5 因子全有的 picks)。")
    print("3. 数据源诚实: gene_score 仅覆盖 2026-01-05+ (183 天);")
    print("   _collect_zt_history_batch 实际只回溯 29 天非 250 → gene_score 更")
    print("   regime-dependent 更噪; 全 2026 单 regime (174 天 Jan-Sep)。")
    print("   分解结果只说 2026 单 regime 内的 driver, 禁止外推 cross-regime。")
    print("4. driver 分类:")
    print("   gap=entry-timing (T+1 open 信息非 selection alpha, 用它排序 entry")
    print("   略有自相关风险, 但 close_ev 已堵 T+1 日内泄漏)")
    print("   lbc=inherited-falsified (consecutive_relay 已证否 -1.66% p=1.0)")
    print("   gene/turn/vr5=new-signal (待 cross-regime 复测)")
    print("5. leave-one-out delta 正值=该 component 正向贡献 (去掉它 EV 降);")
    print("   负值=该 component 负向 (去掉它 EV 升)。delta 受 4-因子重分配影响")
    print("   非纯独立贡献——component 间相关时 loo 有交互效应。")
    print("6. alone 单独排序 = per-date 单因子百分位 top-5 = 单因子 raw value")
    print("   top-5 (百分位单调); 与 composite 用同 universe 公平对比。")
    print("   注: lbc 多数=1 (首板), 单独排序 top-5=连板数最高的股=接力股,")
    print("   可能继承 consecutive_relay 证否信号。")
    print("7. Bonferroni ×10 (5 component × 2: alone + loo); alone verdict")
    print("   用 ×10 (n_cross_factor=5); loo 不出 verdict 只报 EV+delta")
    print("   (loo 是辅助诊断非独立假说)。")
    agree_str = "一致" if agree else "不一致 (以 alone standalone EV 为主)"
    print(
        f"8. driver={_short(driver)} ({implication}); alone best={_short(best_alone)} "
        f"loo best={_short(best_loo)} → {agree_str}"
    )
    print(f"\nOVERALL driver: {_short(driver)} ({implication})")


if __name__ == "__main__":
    main()
