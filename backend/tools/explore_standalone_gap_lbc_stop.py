# -*- coding: utf-8 -*-
"""standalone gap + lbc 加 stop 变体最终测试.

测什么: gap-alone 和 lbc-alone 单因子 top-5/day 加 -3% stop (R6 gap-through
        fill) 的 close_ev_stop, verdict_for 喂 stop 变体 EV (非 basic 无止损).

为什么补测: composite 分解的 alone-gap/alone-lbc verdict 喂了 basic 无止损 EV
           (乐观), 且受 gene_score 2026-01-05+ 条件化 universe 限制 (183 天).
           turn/gene/vr5 已有 standalone stop 测 (max-universe, stop variant).
           gap/lbc 是最后 2 个未做 standalone stop 的 component——补测以穷尽
           5 component standalone 空间.

关键差异 vs composite 分解的 alone:
  - universe: standalone 用各自最大 universe (gap 用所有有 gap 的 picks,
    lbc 用所有有 lbc 的 picks), 非全 5 因子都有的条件化 universe
  - verdict: 喂 close_ev_stop (非 close_ev_basic) — composite 教训
  - Bonferroni: ×6 (3 standalone: turn+gene+vr5 已测 × 2 variant; gap/lbc
    加入后 family=5 component × 2 variant = ×10, 但为保守与 turn/gene/vr5
    对齐, 用 ×6 即 turn+gene+vr5+gap+lbc=5 → max(2,5*2)=10... 实际 5 component
    standalone × 2 variant = ×10. 但 vr5 测时用 ×6 (3 standalone), 这里 gap/lbc
    补测应与 vr5 同 family → 5 standalone × 2 = ×10. 为保守用 ×10.)
  - walk-forward: 用 stop 变体 ret_fn (非 basic)

诚实约束 (与 vr5 standalone 一致):
  - entry = T+1 open (非 T+1 close)
  - 一字涨停跳过 (limit_for_code FIXED 2026-10-06: 6 位纯数字)
  - close_ev 非 open_ev
  - R6 + bug#5: T+1 触及 stop → T+2 open 卖 (非 t2_close leniency)
  - per-day-mean t 非 per-trade t
  - verdict_for 喂 stop 变体 EV (close_ev_stop) 非 basic
  - 禁止外推: standalone gap/lbc ≠ 打板有/无 edge

跑法:
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
  .venv/bin/python tools/explore_standalone_gap_lbc_stop.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._factor_helpers import (  # noqa: E402  DRY: 禁复制 helper 代码
    COST,
    analyze_subset,
    bonferroni_p,
    build_picks_generic,
    close_ev_basic,
    close_ev_stop,
    day_paired_t,
    load_kline_db,
    load_zt,
    verdict_for,
    walk_forward,
)

# 加载 composite-score 模块 (复用 attach_factors / FACTORS / load_gene_scores)
_cs_path = Path(__file__).resolve().parent / "explore_factor_composite-score.py"
_spec = importlib.util.spec_from_file_location("_cs", _cs_path)
_cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cs)

attach_factors = _cs.attach_factors

# 5 standalone component (turn+gene+vr5+gap+lbc) × 2 variant → Bonferroni ×10
# (gap/lbc 补测加入 family; vr5 原测用 ×6 是 3 standalone, 现 family 扩到 5)
N_CROSS_FACTOR = 5
N_TESTS = max(2, N_CROSS_FACTOR * 2)  # 10


def _stop_ret_fn(p: dict) -> float | None:
    """Wrapper: close_ev_stop returns (float, str), walk_forward needs float."""
    r = close_ev_stop(p)
    return r[0] if r is not None else None


def select_topk_by_factor(picks: list[dict], factor: str, k: int = 5) -> list[dict]:
    """每日按 factor 降序取 top-k (与 vr5 standalone 一致)."""
    by_date: dict[str, list[dict]] = {}
    for p in picks:
        v = p.get(factor)
        if v is not None:
            by_date.setdefault(p["zt_date"], []).append(p)
    out: list[dict] = []
    for d, ps in by_date.items():
        ps_sorted = sorted(ps, key=lambda x: x[factor], reverse=True)
        out.extend(ps_sorted[:k])
    return out


def run_standalone(name: str, factor: str, blanket: list[dict], k: int = 5) -> dict:
    """跑一个 standalone 单因子测试: top-k/day + basic + stop + walk-forward + verdict.

    verdict 喂 stop 变体 EV (非 basic), n_cross_factor=5 → Bonf ×10.
    """
    factor_picks = [p for p in blanket if p.get(factor) is not None]
    topk = select_topk_by_factor(factor_picks, factor, k)

    print(f"\n  {name}: universe={len(factor_picks)} picks → top-{k}={len(topk)} "
          f"({len(set(p['zt_date'] for p in topk))} days)")

    if not topk:
        print(f"  → no-data: 无 pick 有 {factor}")
        return {"name": name, "factor": factor, "n_picks": 0, "basic_ev": 0.0,
                "n_days": 0, "stop_bonf": 1.0, "stop_day_t": 0.0,
                "stop_ev_gross": 0.0, "stop_ev_net": 0.0, "verdict": "underpowered",
                "walk_forward_test_ev": 0.0, "walk_forward_test_p": 1.0,
                "walk_forward_train_ev": 0.0, "wf_status": "no_picks",
                "stop_p_raw": 1.0}

    r = analyze_subset(f"{name} (top-{k})", topk,
                       ret_fn_basic=close_ev_basic, ret_fn_stop=close_ev_stop,
                       ret_fn_label="close_ev")
    wf_stop = walk_forward(topk, _stop_ret_fn)

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
    wf_test_p = (wf_stop.get("test_day_t", {}).get("p_one_sided", 1.0)
                 if wf_status == "ok" else 1.0)

    stop_bonf = bonferroni_p(stop_p_raw, N_TESTS)

    v = verdict_for(
        stop_ev_gross, stop_t_day, stop_p_raw, wf_status, wf_train_ev,
        wf_test_ev, wf_test_p, stop_n_days, stop_ev_net,
        f"{name} (stop variant)", n_cross_factor=N_CROSS_FACTOR,
    )

    return {"name": name, "factor": factor, "n_picks": len(topk),
            "basic_ev": basic_ev, "n_days": stop_n_days, "stop_bonf": stop_bonf,
            "stop_day_t": stop_t_day, "stop_ev_gross": stop_ev_gross,
            "stop_ev_net": stop_ev_net, "verdict": v,
            "walk_forward_test_ev": wf_test_ev, "walk_forward_test_p": wf_test_p,
            "walk_forward_train_ev": wf_train_ev, "wf_status": wf_status,
            "stop_p_raw": stop_p_raw}


def main() -> None:
    print("=" * 70)
    print("standalone gap + lbc 加 stop 变体最终测试")
    print(f"  components: gap + lbc (2 standalone single-factor, 补测)")
    print(f"  Bonferroni: ×{N_TESTS} (5 standalone: turn+gene+vr5+gap+lbc × 2 variant)")
    print(f"  verdict: 喂 close_ev_stop (非 basic) — composite 教训")
    print("=" * 70)

    print("\n[1] 加载 kline DB + zt_history ...")
    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    zt_rows = load_zt()
    print(f"  kline codes={len(code_map)} calendar days={len(calendar)} "
          f"zt_rows={len(zt_rows)}")

    print("\n[2] 构建 blanket picks (entry=T+1 open, exit=T+2 close, 一字涨停跳过)...")
    blanket = build_picks_generic(code_map, calendar, zt_rows, filter_fn=None)
    print(f"  blanket picks: {len(blanket)}")

    print("\n[3] 附因子 (gap + lbc 自算 from picks/zt_history, 空 gene dict) ...")
    blanket, _, counts = attach_factors(blanket, code_map, gene={})
    print(f"  gap 覆盖: {counts.get('gap', 0)}")
    print(f"  lbc 覆盖: {counts.get('lbc', 0)}")

    print(f"\n{'=' * 70}")
    print("[4] gap-alone + lbc-alone (top-5/day, close_ev_stop + basic 对照)")
    print(f"{'=' * 70}")

    res_gap = run_standalone("gap-alone", "gap", blanket)
    res_lbc = run_standalone("lbc-alone", "lbc", blanket)

    print(f"\n{'=' * 70}")
    print("[EXTRACTION] key numbers (for structured output)")
    print("=" * 70)
    for label, r in [("gap_alone", res_gap), ("lbc_alone", res_lbc)]:
        print(f"{label}:")
        print(f"  basic_ev={r['basic_ev']}")
        print(f"  n_days={r['n_days']}")
        print(f"  n_picks={r['n_picks']}")
        print(f"  stop_bonf_x10={r['stop_bonf']}")
        print(f"  stop_day_t={r['stop_day_t']}")
        print(f"  stop_ev_gross={r['stop_ev_gross']}")
        print(f"  stop_ev_net={r['stop_ev_net']}")
        print(f"  verdict={r['verdict']}")
        print(f"  walk_forward_test_ev={r['walk_forward_test_ev']}")
        print(f"  walk_forward_test_p={r['walk_forward_test_p']}")
        print(f"  walk_forward_train_ev={r['walk_forward_train_ev']}")
        print(f"  wf_status={r['wf_status']}")

    both_falsified = (res_gap["verdict"] == "falsified"
                      and res_lbc["verdict"] == "falsified")
    print(f"\nOVERALL (standalone gap+lbc with stop): "
          f"{'both falsified' if both_falsified else 'NOT both falsified'}")


if __name__ == "__main__":
    main()
