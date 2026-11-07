# -*- coding: utf-8 -*-
"""standalone turn + gene 加 stop 变体最终测试.

测什么: turn-alone 和 gene-alone 单因子 top-5/day 加 -3% stop (R6 gap-through
        fill) 的 close_ev_stop, verdict_for 喂 stop 变体 EV (非 basic 无止损).

composite 教训: composite top-5 basic +0.731% 但 stop -0.084% → basic 无止损
是乐观数, stop 变体才诚实. turn/gene alone 在 composite 分解中 standalone power
真实 (turn +1.542% t=4.02 / gene +1.313% t=3.51), 但 verdict 用了 basic 无止损.
本测试喂 stop 变体 EV 给 verdict_for.

关键差异 vs composite 分解的 alone:
  - universe: standalone 用各自最大 universe (turn-alone 用所有有 turn 的 picks,
    gene-alone 用所有有 gene_score 的 picks), 非全 5 因子都有的条件化 universe
  - verdict: 喂 close_ev_stop (非 close_ev_basic) — composite 教训
  - Bonferroni: ×4 (2 component × 2 variant basic+stop), 非全 composite 的 ×10
  - walk-forward: 用 stop 变体 ret_fn (非 basic)

诚实约束 (P1 + 8 假 edge 教训):
  - entry = T+1 open (非 T+1 close)
  - 一字涨停跳过 (limit_for_code FIXED 2026-10-06: 6 位纯数字, 非 sz30/sh68)
  - close_ev 非 open_ev (open_ev 有 T+1 日内泄漏)
  - R6: 跳空穿 stop 按 T+2 open + 滑点 0.2% (T+1 intraday stop 不卖, A股T+1)
  - per-day-mean t 非 per-trade t
  - Bonferroni ×4 (2 component × 2 variant basic+stop)
  - walk-forward OOS + train_ev>0 检查
  - verdict_for 喂 stop 变体 EV (close_ev_stop) 非 basic — 核心差异
  - 禁止外推: standalone component ≠ 打板有/无 edge
  - gene_score 仅 2026-01-05+ (183 天), gene-alone 受限于单 regime

跑法:
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
  .venv/bin/python tools/explore_standalone_turn_gene_stop.py
"""

from __future__ import annotations

import importlib.util
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable

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
    walk_forward,
)

# ---- DRY: 复用 composite-score 模块函数 (hyphenated filename → importlib) ----
_cs_path = Path(__file__).resolve().parent / "explore_factor_composite-score.py"
_spec = importlib.util.spec_from_file_location("explore_composite_score", str(_cs_path))
_cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cs)

load_gene_scores = _cs.load_gene_scores
attach_factors = _cs.attach_factors

# 2 component (turn + gene) × 2 variant (basic + stop) → Bonferroni ×4
N_CROSS_FACTOR = 2
N_TESTS = max(2, N_CROSS_FACTOR * 2)  # = 4


# ---------- helpers ----------


def _stop_ret_fn(p: dict) -> float | None:
    """Wrapper: close_ev_stop returns (float, str), walk_forward needs float."""
    r = close_ev_stop(p)
    return r[0] if r is not None else None


def select_topk_by_factor(picks: list[dict], factor: str, k: int) -> list[dict]:
    """每 zt_date 取 factor 值最高的 top-k (只含有该 factor 的 picks).

    per-date percentile rank 等价于 per-date raw value 降序 (单调变换),
    所以直接按 raw value 降序取 top-k = 按 percentile rank 取 top-k.
    """
    by_date: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        v = p.get(factor)
        if v is not None:
            by_date[p["zt_date"]].append(p)
    out: list[dict] = []
    for d, ps in by_date.items():
        ps_sorted = sorted(ps, key=lambda x: x[factor], reverse=True)
        out.extend(ps_sorted[:k])
    return out


def run_standalone(
    name: str,
    factor: str,
    blanket: list[dict],
    k: int = 5,
) -> dict:
    """跑一个 standalone 单因子测试: top-k/day + basic + stop + walk-forward + verdict.

    verdict 喂 stop 变体 EV (非 basic), n_cross_factor=2 → Bonf ×4.
    返回结构化结果 dict.
    """
    # standalone universe: 所有有该 factor 的 picks (非全 5 因子条件化)
    factor_picks = [p for p in blanket if p.get(factor) is not None]
    topk = select_topk_by_factor(factor_picks, factor, k)

    print(
        f"\n  {name}: universe={len(factor_picks)} picks → top-{k}={len(topk)} "
        f"({len(set(p['zt_date'] for p in topk))} days)"
    )

    if not topk:
        print(f"  → no-data: 无 pick 有 {factor}")
        return {
            "name": name,
            "factor": factor,
            "n_picks": 0,
            "basic_ev": 0.0,
            "n_days": 0,
            "stop_bonf_x4": 1.0,
            "stop_day_t": 0.0,
            "stop_ev_gross": 0.0,
            "stop_ev_net": 0.0,
            "verdict": "underpowered",
            "walk_forward_test_ev": 0.0,
            "walk_forward_test_p": 1.0,
            "walk_forward_train_ev": 0.0,
        }

    # analyze_subset (basic + stop + R6 + walk_forward_basic)
    r = analyze_subset(
        f"{name} (top-{k})",
        topk,
        ret_fn_basic=close_ev_basic,
        ret_fn_stop=close_ev_stop,
        ret_fn_label="close_ev",
    )

    # walk-forward with STOP ret_fn (非 basic — verdict 喂 stop 变体)
    wf_stop = walk_forward(topk, _stop_ret_fn)

    # extract stop variant stats
    stop_s = r.get("stop_ev", {})
    stop_dt = r.get("stop_day_t", {})
    basic_s = r.get("basic_ev", {})

    stop_ev_gross = stop_s.get("ev", 0.0)
    stop_ev_net = stop_ev_gross - COST * 100
    stop_t_day = stop_dt.get("t", 0.0)
    stop_p_raw = stop_dt.get("p_one_sided", 1.0)
    stop_n_days = stop_dt.get("n_days", 0)
    basic_ev = basic_s.get("ev", 0.0)

    wf_status = wf_stop.get("status", "no_picks")
    wf_train_ev = wf_stop.get("train_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
    wf_test_ev = wf_stop.get("test_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
    wf_test_p = wf_stop.get("test_day_t", {}).get("p_one_sided", 1.0) if wf_status == "ok" else 1.0

    stop_bonf_x4 = bonferroni_p(stop_p_raw, N_TESTS)

    # verdict: 喂 stop 变体 EV (非 basic!) — composite 教训
    v = verdict_for(
        stop_ev_gross,  # ev_gross = STOP variant
        stop_t_day,  # t_day = stop variant
        stop_p_raw,  # p_raw = stop variant
        wf_status,  # wf_status from stop walk_forward
        wf_train_ev,  # train_ev from stop walk_forward
        wf_test_ev,  # test_ev from stop walk_forward
        wf_test_p,  # test_p from stop walk_forward
        stop_n_days,  # n_days from stop variant
        stop_ev_net,  # net_ev = stop EV - cost
        f"{name} (stop variant)",
        n_cross_factor=N_CROSS_FACTOR,  # ×4
    )

    return {
        "name": name,
        "factor": factor,
        "n_picks": len(topk),
        "basic_ev": basic_ev,
        "n_days": stop_n_days,
        "stop_bonf_x4": stop_bonf_x4,
        "stop_day_t": stop_t_day,
        "stop_ev_gross": stop_ev_gross,
        "stop_ev_net": stop_ev_net,
        "verdict": v,
        "walk_forward_test_ev": wf_test_ev,
        "walk_forward_test_p": wf_test_p,
        "walk_forward_train_ev": wf_train_ev,
        "wf_status": wf_status,
        "stop_p_raw": stop_p_raw,
    }


# ---------- main ----------


def main() -> None:
    print("=" * 70)
    print("standalone turn + gene 加 stop 变体最终测试")
    print(f"  components: turn + gene_score (2 standalone single-factor)")
    print(f"  Bonferroni: ×{N_TESTS} (2 component × 2 variant basic+stop)")
    print(f"  verdict: 喂 close_ev_stop (非 basic) — composite 教训")
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

    # ---- attach factors (turn + gene_score 等 5 因子) ----
    print("\n[3] 附因子 (turn + gene_score 等 5 因子) ...")
    blanket, n_complete, counts = attach_factors(blanket, code_map, gene)
    print(f"  turn 覆盖: {counts['turn']} ({counts['turn'] / max(len(blanket), 1) * 100:.1f}%)")
    print(f"  gene_score 覆盖: {counts['gene_score']} ({counts['gene_score'] / max(len(blanket), 1) * 100:.1f}%)")
    print(f"  注: turn 全样本 (2024-06+), gene_score 仅 2026-01-05+ (183 天)")

    # ---- [4] turn-alone ----
    print(f"\n{'=' * 70}")
    print("[4] turn-alone (top-5/day by turn, close_ev_stop + basic 对照)")
    print(f"    verdict 喂 stop 变体 EV, Bonf ×{N_TESTS}")
    print(f"{'=' * 70}")

    r_turn = run_standalone("turn-alone", "turn", blanket, k=5)

    # ---- [5] gene-alone ----
    print(f"\n{'=' * 70}")
    print("[5] gene-alone (top-5/day by gene_score, close_ev_stop + basic 对照)")
    print(f"    verdict 喂 stop 变体 EV, Bonf ×{N_TESTS}")
    print(f"{'=' * 70}")

    r_gene = run_standalone("gene-alone", "gene_score", blanket, k=5)

    # ---- [6] summary table ----
    print(f"\n{'=' * 70}")
    print(f"[6] 汇总 (close_ev %, per-day-mean t, Bonf ×{N_TESTS}, walk-forward stop, verdict)")
    print(f"{'=' * 70}")
    hdr = (
        f"  {'component':<12} {'n':>5} {'days':>5} "
        f"{'basic%':>8} {'stop_gr%':>8} {'stop_net%':>9} "
        f"{'stop_t':>6} {'Bonf×4':>9} "
        f"{'wf_tr%':>7} {'wf_te%':>7} {'wf_te_p':>8} {'verdict':<16}"
    )
    print(hdr)
    print(f"  {'-' * 108}")
    for r, label in [(r_turn, "turn"), (r_gene, "gene")]:
        print(
            f"  {label:<12} {r['n_picks']:>5} {r['n_days']:>5} "
            f"{r['basic_ev']:>+8.3f} {r['stop_ev_gross']:>+8.3f} "
            f"{r['stop_ev_net']:>+9.3f} "
            f"{r['stop_day_t']:>6.2f} {r['stop_bonf_x4']:>9.6f} "
            f"{r['walk_forward_train_ev']:>+7.3f} "
            f"{r['walk_forward_test_ev']:>+7.3f} "
            f"{r['walk_forward_test_p']:>8.4f} {r['verdict']:<16}"
        )

    # ---- [7] honest notes ----
    _print_honest_notes(r_turn, r_gene)

    # ---- [EXTRACTION] machine-parseable key numbers ----
    print(f"\n{'=' * 70}")
    print("[EXTRACTION] key numbers (for structured output)")
    print(f"{'=' * 70}")
    for label, r in [("turn_alone", r_turn), ("gene_alone", r_gene)]:
        print(f"{label}:")
        print(f"  basic_ev={r['basic_ev']}")
        print(f"  n_days={r['n_days']}")
        print(f"  n_picks={r['n_picks']}")
        print(f"  stop_bonf_x4={r['stop_bonf_x4']}")
        print(f"  stop_day_t={r['stop_day_t']}")
        print(f"  stop_ev_gross={r['stop_ev_gross']}")
        print(f"  stop_ev_net={r['stop_ev_net']}")
        print(f"  verdict={r['verdict']}")
        print(f"  walk_forward_test_ev={r['walk_forward_test_ev']}")
        print(f"  walk_forward_test_p={r['walk_forward_test_p']}")
        print(f"  walk_forward_train_ev={r['walk_forward_train_ev']}")
        print(f"  wf_status={r.get('wf_status', 'unknown')}")
        print(f"  stop_p_raw={r.get('stop_p_raw', 1.0)}")

    # overall
    verdicts = [r_turn["verdict"], r_gene["verdict"]]
    if "edge-confirmed" in verdicts:
        overall = "edge-confirmed"
    elif "underpowered" in verdicts:
        overall = "underpowered"
    elif "exploratory" in verdicts:
        overall = "exploratory"
    else:
        overall = "edge-falsified"
    print(f"\nOVERALL (standalone turn+gene with stop): {overall}")


def _print_honest_notes(r_turn: dict, r_gene: dict) -> None:
    print(f"\n{'=' * 70}")
    print("诚实注解")
    print(f"{'=' * 70}")
    print("1. 测了什么: turn-alone 和 gene-alone 单因子 top-5/day 的 close_ev_stop")
    print("   (-3% stop + R6 gap-through fill), verdict_for 喂 stop 变体 EV.")
    print("   仅此 2 因子 × stop 变体, Bonferroni ×4 (2 component × 2 variant).")
    print("2. 没测什么: standalone component ≠ 打板有/无 edge; 未测 cross-regime;")
    print("   未测盘中可交易性细节; turn/gene 是排序因子非方向预判.")
    print("3. 关键差异 vs composite 分解的 alone:")
    print("   - universe: 本测试用各自最大 universe (turn-alone 用所有有 turn 的")
    print("     picks, gene-alone 用所有有 gene_score 的 picks), 非全 5 因子")
    print("     都有的条件化 universe → 更多样本, 更少条件化偏差")
    print("   - verdict: 喂 close_ev_stop (非 basic) — composite 教训:")
    print(f"     basic +0.731% 但 stop -0.084%, basic 无止损是乐观数")
    print("   - Bonferroni: ×4 (非 ×10), 因只测 2 component × 2 variant")
    print("4. 数据源诚实:")
    print("   - turn: kline bar.turn (baostock 换手率%), 全样本 2024-06+")
    print("   - gene_score: gene_scores.db.total_score, 仅 2026-01-05+ (183 天)")
    print("   - gene-alone 受限于 2026 单 regime, 禁止外推 cross-regime")
    print("5. R6: stop 变体用 gap-through fill (T+2 open + 滑点 0.2%),")
    print("   T+1 intraday stop 不卖 (A股 T+1, 2026-10-06 修).")
    print("6. verdict_for 级联: gross<0→falsified / n<60→underpowered /")
    print("   Bonf>=0.05→falsified / net<=0→falsified / wf_train<=0→exploratory /")
    print("   wf_test<=0→falsified / wf_test_p Bonf>=0.05→exploratory / all→confirmed")
    print("7. 禁止外推: turn-alone/gene-alone standalone power ≠ 打板有/无 edge.")
    print("   即使 standalone edge-confirmed, 也只说明该因子排序提 EV,")
    print("   不等于打板工作流有可交易 alpha (需 composite + 可交易性 + cost).")


if __name__ == "__main__":
    main()
