# -*- coding: utf-8 -*-
"""standalone vr5 加 stop 变体最终测试.

测什么: vr5-alone 单因子 top-5/day 加 -3% stop (R6 gap-through fill) 的
        close_ev_stop, verdict_for 喂 stop 变体 EV (非 basic 无止损).

背景: composite-score 正交分解中, vr5 是 5 component 里唯一正向 loo 贡献者
      (loo delta +0.053%, 虽极小); vr5 alone basic +1.128% gross (Bonf×10=0.031
      exploratory). 但 composite/turn/gene 的 verdict 都用了 basic 无止损 EV,
      stop 变体没测. composite 教训: composite top-5 basic +0.731% 但 stop -0.084%
      → basic 无止损是乐观数, stop 变体才诚实. 本测试喂 stop 变体 EV 给 verdict_for.

关键差异 vs composite 分解的 alone-vr5:
  - universe: standalone 用 vr5 最大 universe (所有有 vr5 的 picks, 全样本 2024-06+),
    非全 5 因子都有的条件化 universe (composite 分解强制 all-5-present → 受
    gene_score 2026-01-05+ 限制). vr5 全样本可算 (kline history 足够 5 bar 回看),
    不受 gene_score 限制——这是 vr5 vs gene 的样本量优势.
  - vr5 自算: (t_close / close[-5] - 1) * 100, bisect_left 找 zt_date index 回看 5 bar
    (不用 watchlist.vr5——那是 S232 信号 turn>20%&vr5>2 的预筛子集, 偏已证否 universe)
  - verdict: 喂 close_ev_stop (非 close_ev_basic) — composite 教训
  - Bonferroni: ×6 (3 standalone component: turn+gene+vr5 × 2 variant basic+stop)
  - walk-forward: 用 stop 变体 ret_fn (非 basic)

诚实约束 (P1 + 8 假 edge 教训):
  - entry = T+1 open (非 T+1 close)
  - 一字涨停跳过 (limit_for_code FIXED 2026-10-06: 6 位纯数字, 非 sz30/sh68)
  - close_ev 非 open_ev (open_ev 有 T+1 日内泄漏)
  - R6: 跳空穿 stop 按 T+2 open + 滑点 0.2%; bug#5 已修 (T+1 triggered → T+2 open 卖
    非 t2_close leniency)
  - per-day-mean t 非 per-trade t
  - Bonferroni ×6 (3 standalone × 2 variant)
  - walk-forward OOS + train_ev>0 检查
  - verdict_for 喂 stop 变体 EV (close_ev_stop) 非 basic — 核心差异
  - 禁止外推: standalone vr5 ≠ 打板有/无 edge

跑法:
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
  .venv/bin/python tools/explore_standalone_vr5_stop.py
"""
from __future__ import annotations

import importlib.util
import sys
from collections import defaultdict
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
    walk_forward,
)

# ---- DRY: 复用 composite-score 模块函数 (hyphenated filename → importlib) ----
# _vr5 自算 (bisect_left 找 zt_date index, 回看 5 bar, (close[now]/close[-5]-1)*100)
# 通过 attach_factors 调用, 不复制 _vr5 代码.
_cs_path = Path(__file__).resolve().parent / "explore_factor_composite-score.py"
_spec = importlib.util.spec_from_file_location("explore_composite_score", str(_cs_path))
_cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cs)

attach_factors = _cs.attach_factors  # 内部调 _vr5 自算 vr5 (不用 watchlist.vr5)

# 3 standalone component (turn+gene+vr5) × 2 variant (basic+stop) → Bonferroni ×6
N_CROSS_FACTOR = 3
N_TESTS = max(2, N_CROSS_FACTOR * 2)  # = 6


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

    verdict 喂 stop 变体 EV (非 basic), n_cross_factor=3 → Bonf ×6.
    返回结构化结果 dict.
    """
    # standalone universe: 所有有该 factor 的 picks (非全 5 因子条件化)
    factor_picks = [p for p in blanket if p.get(factor) is not None]
    topk = select_topk_by_factor(factor_picks, factor, k)

    print(f"\n  {name}: universe={len(factor_picks)} picks → top-{k}={len(topk)} "
          f"({len(set(p['zt_date'] for p in topk))} days)")

    if not topk:
        print(f"  → no-data: 无 pick 有 {factor}")
        return {
            "name": name, "factor": factor, "n_picks": 0,
            "basic_ev": 0.0, "n_days": 0, "stop_bonf_x6": 1.0,
            "stop_day_t": 0.0, "stop_ev_gross": 0.0, "stop_ev_net": 0.0,
            "verdict": "underpowered", "walk_forward_test_ev": 0.0,
            "walk_forward_test_p": 1.0, "walk_forward_train_ev": 0.0,
            "wf_status": "no_picks", "stop_p_raw": 1.0,
        }

    # analyze_subset (basic + stop + R6 + walk_forward_basic)
    r = analyze_subset(
        f"{name} (top-{k})", topk,
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
    wf_test_p = (wf_stop.get("test_day_t", {}).get("p_one_sided", 1.0)
                 if wf_status == "ok" else 1.0)

    stop_bonf_x6 = bonferroni_p(stop_p_raw, N_TESTS)

    # verdict: 喂 stop 变体 EV (非 basic!) — composite 教训
    v = verdict_for(
        stop_ev_gross,        # ev_gross = STOP variant
        stop_t_day,           # t_day = stop variant
        stop_p_raw,           # p_raw = stop variant
        wf_status,            # wf_status from stop walk_forward
        wf_train_ev,          # train_ev from stop walk_forward
        wf_test_ev,           # test_ev from stop walk_forward
        wf_test_p,            # test_p from stop walk_forward
        stop_n_days,          # n_days from stop variant
        stop_ev_net,          # net_ev = stop EV - cost
        f"{name} (stop variant)",
        n_cross_factor=N_CROSS_FACTOR,  # ×6
    )

    return {
        "name": name, "factor": factor, "n_picks": len(topk),
        "basic_ev": basic_ev,
        "n_days": stop_n_days,
        "stop_bonf_x6": stop_bonf_x6,
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
    print("standalone vr5 加 stop 变体最终测试")
    print(f"  component: vr5 (自算 5-trading-day return from kline history)")
    print(f"  Bonferroni: ×{N_TESTS} (3 standalone: turn+gene+vr5 × 2 variant)")
    print(f"  verdict: 喂 close_ev_stop (非 basic) — composite 教训")
    print(f"  vr5 universe: 全样本 (kline history 足够, 不受 gene_score 限制)")
    print("=" * 70)

    # ---- load data ----
    print("\n[1] 加载 kline DB + zt_history ...")
    code_map, all_dates = load_kline_db()
    zt_rows = load_zt()
    calendar = sorted(all_dates)
    print(f"  kline codes={len(code_map)} calendar days={len(calendar)} "
          f"zt_rows={len(zt_rows)}")
    print(f"  zt date range: {min(d for d,_,_ in zt_rows)} ~ "
          f"{max(d for d,_,_ in zt_rows)}")

    # ---- build blanket picks ----
    print("\n[2] 构建 blanket picks (entry=T+1 open, exit=T+2 close, 一字涨停跳过)…")
    blanket = build_picks_generic(code_map, calendar, zt_rows, filter_fn=None)
    print(f"  blanket picks: {len(blanket)}")

    # ---- attach factors (vr5 自算 via _vr5, 不需 gene_score) ----
    print("\n[3] 附因子 (vr5 自算 from kline history, 空 gene dict — vr5 不依赖 gene) ...")
    # 空 gene dict: gene_score=None for all, 但 vr5/turn/gap/lbc 仍附.
    # vr5 自算 = (t_close/close[-5]-1)*100, bisect_left 回看 5 bar.
    blanket, n_complete, counts = attach_factors(blanket, code_map, {})
    n_vr5 = counts["vr5"]
    print(f"  vr5 覆盖: {n_vr5} ({n_vr5/max(len(blanket),1)*100:.1f}% of blanket)")
    print(f"  注: vr5 全样本可算 (kline history 足够 5 bar), 不受 gene_score")
    print(f"      2026-01-05+ 限制——这是 vr5 vs gene 的样本量优势")

    vr5_dates = sorted({p["zt_date"] for p in blanket if p.get("vr5") is not None})
    if vr5_dates:
        print(f"  vr5 universe 日期: {len(vr5_dates)} "
              f"({vr5_dates[0]} ~ {vr5_dates[-1]})")

    # ---- [4] vr5-alone ----
    print(f"\n{'=' * 70}")
    print("[4] vr5-alone (top-5/day by vr5, close_ev_stop + basic 对照)")
    print(f"    verdict 喂 stop 变体 EV, Bonf ×{N_TESTS}")
    print(f"{'=' * 70}")

    r_vr5 = run_standalone("vr5-alone", "vr5", blanket, k=5)

    # ---- [5] summary table ----
    print(f"\n{'=' * 70}")
    print(f"[5] 汇总 (close_ev %, per-day-mean t, Bonf ×{N_TESTS}, "
          f"walk-forward stop, verdict)")
    print(f"{'=' * 70}")
    hdr = (f"  {'component':<12} {'n':>5} {'days':>5} "
           f"{'basic%':>8} {'stop_gr%':>8} {'stop_net%':>9} "
           f"{'stop_t':>6} {'Bonf×6':>9} "
           f"{'wf_tr%':>7} {'wf_te%':>7} {'wf_te_p':>8} {'verdict':<16}")
    print(hdr)
    print(f"  {'-'*108}")
    print(f"  {'vr5':<12} {r_vr5['n_picks']:>5} {r_vr5['n_days']:>5} "
          f"{r_vr5['basic_ev']:>+8.3f} {r_vr5['stop_ev_gross']:>+8.3f} "
          f"{r_vr5['stop_ev_net']:>+9.3f} "
          f"{r_vr5['stop_day_t']:>6.2f} {r_vr5['stop_bonf_x6']:>9.6f} "
          f"{r_vr5['walk_forward_train_ev']:>+7.3f} "
          f"{r_vr5['walk_forward_test_ev']:>+7.3f} "
          f"{r_vr5['walk_forward_test_p']:>8.4f} {r_vr5['verdict']:<16}")

    # ---- [6] honest notes ----
    _print_honest_notes(r_vr5)

    # ---- [EXTRACTION] machine-parseable key numbers ----
    print(f"\n{'=' * 70}")
    print("[EXTRACTION] key numbers (for structured output)")
    print(f"{'=' * 70}")
    print(f"vr5_alone:")
    print(f"  basic_ev={r_vr5['basic_ev']}")
    print(f"  n_days={r_vr5['n_days']}")
    print(f"  n_picks={r_vr5['n_picks']}")
    print(f"  stop_bonf_x6={r_vr5['stop_bonf_x6']}")
    print(f"  stop_day_t={r_vr5['stop_day_t']}")
    print(f"  stop_ev_gross={r_vr5['stop_ev_gross']}")
    print(f"  stop_ev_net={r_vr5['stop_ev_net']}")
    print(f"  verdict={r_vr5['verdict']}")
    print(f"  walk_forward_test_ev={r_vr5['walk_forward_test_ev']}")
    print(f"  walk_forward_test_p={r_vr5['walk_forward_test_p']}")
    print(f"  walk_forward_train_ev={r_vr5['walk_forward_train_ev']}")
    print(f"  wf_status={r_vr5.get('wf_status', 'unknown')}")
    print(f"  stop_p_raw={r_vr5.get('stop_p_raw', 1.0)}")

    print(f"\nOVERALL (standalone vr5 with stop): {r_vr5['verdict']}")


def _print_honest_notes(r_vr5: dict) -> None:
    print(f"\n{'=' * 70}")
    print("诚实注解")
    print(f"{'=' * 70}")
    print("1. 测了什么: vr5-alone 单因子 top-5/day 的 close_ev_stop")
    print("   (-3% stop + R6 gap-through fill), verdict_for 喂 stop 变体 EV.")
    print(f"   仅此 1 因子 × stop 变体, Bonferroni ×{N_TESTS} (3 standalone × 2 variant).")
    print("2. 没测什么: standalone vr5 ≠ 打板有/无 edge; 未测 cross-regime;")
    print("   未测盘中可交易性细节; vr5 是排序因子非方向预判——'哪些涨停股")
    print("   近 5 日涨幅强'的排序, 不等于'方向预判'.")
    print("3. 关键差异 vs composite 分解的 alone-vr5:")
    print("   - universe: 本测试用 vr5 最大 universe (所有有 vr5 的 picks),")
    print(f"     全样本 {r_vr5['n_days']}+ 天 (vr5 全样本可算), 非全 5 因子")
    print("     都有的条件化 universe (composite 分解强制 all-5-present → 受")
    print("     gene_score 2026-01-05+ 限制). vr5 样本量 > gene 样本量.")
    print("   - verdict: 喂 close_ev_stop (非 basic) — composite 教训:")
    print("     basic 无止损是乐观数 (composite basic +0.731% 但 stop -0.084%)")
    print(f"   - Bonferroni: ×{N_TESTS} (非 ×10), 因 3 standalone × 2 variant")
    print("4. vr5 自算: (t_close / close[-5] - 1) * 100, bisect_left 找 zt_date")
    print("   index 回看 5 bar (不用 watchlist.vr5——那是 S232 信号 turn>20%")
    print("   &vr5>2 的预筛子集, 偏已证否 universe). vr5 全样本可算 (kline history")
    print("   足够), 不受 gene_score 2026-01-05+ 限制.")
    print("5. R6 + bug#5 已修: T+1 触及 stop → T+2 open 卖 (非 t2_close leniency);")
    print("   跳空穿 stop 按 T+2 open + 滑点 0.2%.")
    print("6. verdict_for 级联: gross<0→falsified / n<60→underpowered /")
    print("   Bonf>=0.05→falsified / net<=0→falsified / wf_train<=0→exploratory /")
    print("   wf_test<=0→falsified / wf_test_p Bonf>=0.05→exploratory / all→confirmed")
    print("7. 禁止外推: vr5-alone standalone power ≠ 打板有/无 edge.")
    print("   即使 standalone edge-confirmed, 也只说明该因子排序提 EV,")
    print("   不等于打板工作流有可交易 alpha (需 composite + 可交易性 + cost).")


if __name__ == "__main__":
    main()
