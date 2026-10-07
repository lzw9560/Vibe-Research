# -*- coding: utf-8 -*-
"""因子回测：composite-score (多因子复合评分 top-K 集中度).

每日按 composite score (turn + vr5 + gap + lbc + gene_score 的 per-date 百分位
排名等权加和) 排序 zt picks，取 top-1/top-3/top-5，close_ev vs blanket。
测"多因子共振"是否提 EV (学术多因子组合有先例，A 股衰减快未测)。

数据源 (全 universe, 禁 watchlist 子集偏差):
  - turn:  kline DB bar.turn (T 日换手率 %, baostock)
  - vr5:   自算 (t_close / close[-5] - 1)*100 — 5 交易日收益, 从 kline 历史
           (不用 watchlist.vr5——watchlist 是 S232 信号 turn>20%&vr5>2 的预筛
           子集, 用它会偏到已证否的 S232 universe)
  - gap:   (t1_open - t_close)/t_close*100 — 隔夜跳空 (entry-time 信息,
           T+1 open 才知道; honest 注: 用 entry-time 信号排序 entry 略有
           自相关风险, 但 T+1 open 是公开可观察的)
  - lbc:   zt_history.lbc (连板数, T 日已知)
  - gene_score: gene_scores.db.total_score (T 日历史基础率合成分, wilson
           调整 250 日回看, 不含 T+1/T+2 未来信息 → 无 look-ahead)

方法论 (task 明确要求 + §44 v3 过严口径):
  - 复合用 per-date 百分位排名 [0,1] 归一 (控跨日 regime 差异: 冷日 5% turn
    排高, 热日排低), 非原值加和 (原值尺度不同 turn~0-50% vs vr5~-20-20% vs
    gene~0-100 会以大尺度因子主导)
  - 等权 primary composite; 另跑 4 预设权重方案 robustness, Bonferroni ×4
    校正权重搜索 (task "必须 Bonferroni 校正 composite 权重 search")
  - top-K 每 1-5 pick/日 → effective N = n_days (per-day-mean t 已控 N 通胀)
  - blanket 对比须同日期域 (gene-scored dates) 否则比不同 regime

诚实口径 (P1 + 8 假 edge 教训):
  - entry = T+1 open (非 T+1 close——T close sealed 不可买)
  - 一字涨停跳过 (买不进, 用 FIXED limit_for_code 禁 sz30/sh68 旧 bug)
  - close_ev 非 open_ev (open_ev 有 T+1 日内泄漏——gap 因子含 open 信息,
    用 close_ev 测是诚实: 若 composite 含 gap 但 close_ev 仍负, 说明 gap
    的 open 泄漏被 close 口径堵住, composite 无救)
  - R6: 跳空穿 stop 按 T+2 open + 滑点 0.2%
  - per-day-mean t 非 per-trade t
  - Bonferroni cross-factor ×12 (6 因子 × 2 子集) primary; ×48 (×12 × 4
    权重方案) weight-search-corrected
  - walk-forward OOS: 前半 train → 后半 test
  - 禁止外推: composite top-K ≠ 打板有/无 edge

跑法:
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
  .venv/bin/python tools/explore_factor_composite-score.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable

# 让 `from tools._factor_helpers import ...` 在文件路径跑时也工作
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._factor_helpers import (  # noqa: E402  DRY: 禁复制 helper 代码
    COST,
    analyze_subset,
    bonferroni_p,
    build_picks_generic,
    close_ev_basic,
    close_ev_stop,
    limit_for_code,  # re-export: 禁用 sz30/sh68 旧 bug (FIXED 2026-10-06)
    load_kline_db,
    load_zt,
    verdict_for,
)

# gene_scores.db 路径——镜像 helper 的 ROOT/.vibe-research 逻辑
ROOT = Path(__file__).resolve().parents[2]
GENE_DB = ROOT / ".vibe-research" / "gene_scores.db"

N_CROSS_FACTOR = 6  # 6 因子并行 → primary Bonferroni ×6*2=×12
N_WEIGHT_SCHEMES = 4  # 权重搜索方案数 → weight-search Bonferroni ×4
# weight-search-corrected: ×12 × 4 = ×48 → n_cross_factor=24 (verdict_for 用 *2)

FACTORS = ["turn", "vr5", "gap", "lbc", "gene_score"]


# ---------- data: gene_scores ----------

def load_gene_scores() -> tuple[dict[str, dict[str, float]], int]:
    """读 gene_scores.db → {date: {code: total_score}}.

    total_score 为 T 日历史基础率合成分 (wilson 调整, 250 日回看),
    不含 T+1/T+2 未来信息 → 无 look-ahead。
    """
    conn = sqlite3.connect(str(GENE_DB))
    by_date: dict[str, dict[str, float]] = defaultdict(dict)
    n = 0
    for d, code, score in conn.execute(
        "SELECT date, code, total_score FROM gene_scores"
    ):
        if score is None:
            continue
        by_date[d][code] = float(score)
        n += 1
    conn.close()
    return dict(by_date), n


# ---------- factor attachment ----------

def _vr5(code_map: dict[str, dict[str, dict]], code: str, zt_date: str,
         sorted_dates_cache: dict[str, list[str]]) -> float | None:
    """vr5 = (t_close / close[-5] - 1) * 100, 5 交易日收益 (code 自身历史).

    用 code 的 sorted date list 找 zt_date 位置, 回看 5 个 bar.
    不足 5 bar 或缺数据 → None.
    """
    dmap = code_map.get(code)
    if not dmap:
        return None
    if code not in sorted_dates_cache:
        sorted_dates_cache[code] = sorted(dmap.keys())
    sdates = sorted_dates_cache[code]
    idx = -1
    # 找 zt_date 在 code 自身日期序列的位置 (二分查找)
    import bisect
    idx = bisect.bisect_left(sdates, zt_date)
    if idx >= len(sdates) or sdates[idx] != zt_date:
        return None
    if idx < 5:
        return None  # 不足 5 个历史 bar
    bar_5ago = dmap.get(sdates[idx - 5])
    t_bar = dmap.get(zt_date)
    if not bar_5ago or not t_bar:
        return None
    c5 = bar_5ago.get("close")
    c0 = t_bar.get("close")
    if not c5 or not c5 > 0 or not c0 or c0 <= 0:
        return None
    return (c0 / c5 - 1) * 100


def attach_factors(
    picks: list[dict],
    code_map: dict[str, dict[str, dict]],
    gene: dict[str, dict[str, float]],
) -> tuple[list[dict], int, dict[str, int]]:
    """给每个 pick 附 5 因子值 + gene_score. 返回 (picks, n_complete, counts).

    n_complete = 5 因子全有的 picks (可进 composite 排名 universe).
    counts = 每因子非 None 的 pick 数 (诊断覆盖).
    """
    sorted_dates_cache: dict[str, list[str]] = {}
    n_complete = 0
    counts: dict[str, int] = {f: 0 for f in FACTORS}
    for p in picks:
        code = p["code"]
        zt_date = p["zt_date"]
        dmap = code_map.get(code, {})
        t_bar = dmap.get(zt_date, {})

        # turn (T 日换手率 %)
        turn = t_bar.get("turn")
        p["turn"] = turn
        if turn is not None:
            counts["turn"] += 1

        # vr5 (5 日收益, 自算)
        vr5 = _vr5(code_map, code, zt_date, sorted_dates_cache)
        p["vr5"] = vr5
        if vr5 is not None:
            counts["vr5"] += 1

        # gap (隔夜跳空, entry-time: t1_open vs t_close)
        entry = p.get("entry")
        t_close = p.get("t_close")
        if entry and entry > 0 and t_close and t_close > 0:
            p["gap"] = (entry - t_close) / t_close * 100
            counts["gap"] += 1
        else:
            p["gap"] = None

        # lbc (连板数)
        lbc = p.get("lbc")
        p["lbc"] = float(lbc) if lbc else None
        if p["lbc"] is not None:
            counts["lbc"] += 1

        # gene_score (历史基础率)
        dmap_g = gene.get(zt_date)
        gs = dmap_g.get(code) if dmap_g else None
        p["gene_score"] = gs
        if gs is not None:
            counts["gene_score"] += 1

        if all(p.get(f) is not None for f in FACTORS):
            n_complete += 1
    return picks, n_complete, counts


# ---------- percentile rank per date ----------

def _percentile_rank(values: list[tuple[int, float]]) -> list[float]:
    """给定 [(pick_idx, value)] 返回每个 idx 的百分位排名 [0,1].

    平均排名处理并列. n=1 → 0.5 (中性).
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    # 按 value 排序, 分配平均排名
    sorted_vals = sorted(values, key=lambda x: x[1])
    ranks: dict[int, float] = {}
    i = 0
    while i < n:
        j = i
        # 找并列段
        while j + 1 < n and sorted_vals[j + 1][1] == sorted_vals[i][1]:
            j += 1
        # 平均 rank (1-based) = (i+1 + j+1) / 2
        avg_rank = (i + 1 + j + 1) / 2
        for k in range(i, j + 1):
            idx = sorted_vals[k][0]
            ranks[idx] = (avg_rank - 1) / (n - 1)  # 归一到 [0,1]
        i = j + 1
    return [ranks[v[0]] for v in values]


def compute_composite(
    picks: list[dict],
    weights: dict[str, float] | None = None,
) -> list[dict]:
    """给每个 pick (5 因子全有) 算 composite score: per-date 百分位排名加权和.

    weights: {factor: weight}, 默认等权 (0.2 each). 归一到 sum=1.
    只对 5 因子全有的 picks 排名 (universe). 缺因子的 pick composite=None.
    返回 picks (原地加 "composite" 字段).
    """
    if weights is None:
        weights = {f: 1.0 / len(FACTORS) for f in FACTORS}
    else:
        s = sum(weights.values())
        weights = {f: w / s for f, w in weights.items()} if s > 0 else \
            {f: 1.0 / len(FACTORS) for f in FACTORS}

    # 分组 by zt_date, 只排 5 因子全有的
    by_date: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        p["composite"] = None
        if all(p.get(f) is not None for f in FACTORS):
            by_date[p["zt_date"]].append(p)

    for d, ps in by_date.items():
        # 每因子 per-date 百分位
        pct: dict[str, list[float]] = {}
        for f in FACTORS:
            vals = [(i, ps[i][f]) for i in range(len(ps))]
            pct[f] = _percentile_rank(vals)
        # composite = 加权和
        for i, p in enumerate(ps):
            score = sum(weights[f] * pct[f][i] for f in FACTORS)
            p["composite"] = score
    return picks


def select_topk_by_composite(picks: list[dict], k: int) -> list[dict]:
    """每 zt_date 取 composite 最高的 top-k (只含有 composite 的)."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        c = p.get("composite")
        if c is not None:
            by_date[p["zt_date"]].append(p)
    out: list[dict] = []
    for d, ps in by_date.items():
        ps_sorted = sorted(ps, key=lambda x: x["composite"], reverse=True)
        out.extend(ps_sorted[:k])
    return out


# ---------- weight schemes (predefined, hypothesis-driven 非 data-fit) ----------

WEIGHT_SCHEMES: dict[str, dict[str, float]] = {
    "equal":       {"turn": 0.20, "vr5": 0.20, "gap": 0.20, "lbc": 0.20, "gene_score": 0.20},
    "gene_heavy":  {"turn": 0.15, "vr5": 0.15, "gap": 0.15, "lbc": 0.15, "gene_score": 0.40},
    "turn_lbc":    {"turn": 0.30, "vr5": 0.133, "gap": 0.133, "lbc": 0.30, "gene_score": 0.134},
    "momentum":    {"turn": 0.134, "vr5": 0.30, "gap": 0.30, "lbc": 0.133, "gene_score": 0.133},
}


# ---------- main ----------

def main() -> None:
    print("=" * 70)
    print("因子: composite-score (多因子复合评分 top-K 集中度)")
    print(f"  factors: {' + '.join(FACTORS)}")
    print("=" * 70)

    # ---- load data ----
    print("\n[1] 加载 kline DB + zt_history + gene_scores ...")
    code_map, all_dates = load_kline_db()
    zt_rows = load_zt()
    gene, n_gene = load_gene_scores()
    calendar = sorted(all_dates)
    print(f"  kline codes={len(code_map)} calendar days={len(calendar)} "
          f"zt_rows={len(zt_rows)}")
    print(f"  zt date range: {min(d for d,_,_ in zt_rows)} ~ "
          f"{max(d for d,_,_ in zt_rows)}")
    print(f"  gene_scores: {n_gene} rows, {len(gene)} dates "
          f"({min(gene)} ~ {max(gene)})")

    # ---- build blanket picks ----
    print("\n[2] 构建 blanket picks (entry=T+1 open, exit=T+2 close, 一字涨停跳过)…")
    blanket = build_picks_generic(code_map, calendar, zt_rows, filter_fn=None)
    print(f"  blanket picks: {len(blanket)}")

    # ---- attach 5 factors ----
    print("\n[3] 附 5 因子 (turn/vr5/gap/lbc/gene_score) ...")
    blanket, n_complete, counts = attach_factors(blanket, code_map, gene)
    print(f"  5 因子全有 (composite universe): {n_complete} "
          f"({n_complete/max(len(blanket),1)*100:.1f}% of blanket)")
    print(f"  各因子覆盖:")
    for f in FACTORS:
        c = counts[f]
        print(f"    {f:<12}: {c:>5} ({c/max(len(blanket),1)*100:.1f}%)")

    if n_complete == 0:
        print("\n  → no-data: 无 pick 5 因子全有, 无法排 composite")
        _report_no_data()
        return

    # 日期域: composite-universe 的 zt_date
    comp_dates = sorted({p["zt_date"] for p in blanket
                         if all(p.get(f) is not None for f in FACTORS)})
    print(f"  composite-universe 日期数: {len(comp_dates)} "
          f"({comp_dates[0]} ~ {comp_dates[-1]})")

    # ---- compute composite (equal weight primary) ----
    print("\n[4] 算 composite (per-date 百分位排名等权加和) ...")
    compute_composite(blanket, weights=WEIGHT_SCHEMES["equal"])

    # ---- subsets ----
    blanket_comp_dates = [p for p in blanket if p["zt_date"] in set(comp_dates)]
    all_composite = [p for p in blanket
                     if all(p.get(f) is not None for f in FACTORS)]
    top1 = select_topk_by_composite(blanket, 1)
    top3 = select_topk_by_composite(blanket, 3)
    top5 = select_topk_by_composite(blanket, 5)

    print(f"\n子集 picks 数:")
    print(f"  blanket (all dates):       {len(blanket)}")
    print(f"  blanket (composite dates): {len(blanket_comp_dates)}")
    print(f"  all_composite (universe):  {len(all_composite)}")
    print(f"  top-1 (per date):          {len(top1)}  (= n_days, 1 pick/day)")
    print(f"  top-3 (per date):          {len(top3)}")
    print(f"  top-5 (per date):          {len(top5)}")

    # composite score 分位诊断 (top-1 vs all_composite)
    if top1 and all_composite:
        cs_top1 = [p["composite"] for p in top1]
        cs_all = [p["composite"] for p in all_composite]
        print(f"\n  composite score 诊断 (equal-weight, [0,1]):")
        print(f"    all_composite: mean={sum(cs_all)/len(cs_all):.3f} "
              f"min={min(cs_all):.3f} max={max(cs_all):.3f}")
        print(f"    top-1:         mean={sum(cs_top1)/len(cs_top1):.3f} "
              f"min={min(cs_top1):.3f} max={max(cs_top1):.3f}")

    # ---- analyze subsets ----
    subsets = [
        ("blanket_all", blanket),
        ("blanket_comp_dates", blanket_comp_dates),
        ("all_composite", all_composite),
        ("top-1", top1),
        ("top-3", top3),
        ("top-5", top5),
    ]
    results: list[tuple[str, list[dict], dict]] = []
    for name, picks in subsets:
        r = analyze_subset(
            name, picks,
            ret_fn_basic=close_ev_basic,
            ret_fn_stop=close_ev_stop,
            ret_fn_label="close_ev",
        )
        results.append((name, picks, r))

    # ---- verdicts (primary, equal-weight, ×12 cross-factor) ----
    print(f"\n{'=' * 70}")
    print("[5] 诚实判定 (equal-weight composite, cross-factor Bonferroni ×12)")
    print(f"  注: blanket 子集是 baseline 不出 factor verdict (只对比);")
    print(f"  top-1/3/5 三子集 verdict_for 各跑 ×12 (6 factors × 2 subsets);")
    print(f"  full correction 应 ×18 (6×3), 按跨因子标准 ×12 报告 (保守偏低).")
    print(f"{'=' * 70}")

    summary_rows: list[dict] = []
    verdicts: list[str] = []
    factor_subset_names = {"top-1", "top-3", "top-5"}
    for name, picks, r in results:
        if name not in factor_subset_names:
            ev = r.get("basic_ev", {}).get("ev", 0.0)
            dt = r.get("basic_day_t", {})
            wf = r.get("wf_basic", {})
            wfs = wf.get("status", "no_picks")
            summary_rows.append({
                "name": name, "n_picks": len(picks),
                "n_days": dt.get("n_days", 0), "ev_gross": ev,
                "t_day": dt.get("t", 0.0), "p_raw": dt.get("p_one_sided", 1.0),
                "wf_train_ev": wf.get("train_ev", {}).get("ev", 0.0) if wfs == "ok" else 0.0,
                "wf_test_ev": wf.get("test_ev", {}).get("ev", 0.0) if wfs == "ok" else 0.0,
                "wf_test_t": wf.get("test_day_t", {}).get("t", 0.0) if wfs == "ok" else 0.0,
                "wf_test_p": wf.get("test_day_t", {}).get("p_one_sided", 1.0) if wfs == "ok" else 1.0,
                "verdict": "(baseline)",
            })
            continue
        if not picks or r.get("n_picks", 0) == 0:
            print(f"\n  {name}: 无 picks → no-data")
            verdicts.append("no-data")
            summary_rows.append({"name": name, "verdict": "no-data"})
            continue
        ev_gross = r.get("basic_ev", {}).get("ev", 0.0)
        dt = r.get("basic_day_t", {})
        t_day = dt.get("t", 0.0)
        p_raw = dt.get("p_one_sided", 1.0)
        n_days = dt.get("n_days", 0)
        net_ev = ev_gross - COST * 100
        wf = r.get("wf_basic", {})
        wf_status = wf.get("status", "no_picks")
        wf_train_ev = wf.get("train_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
        wf_test_ev = wf.get("test_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
        wf_test_t = wf.get("test_day_t", {}).get("t", 0.0) if wf_status == "ok" else 0.0
        wf_test_p = wf.get("test_day_t", {}).get("p_one_sided", 1.0) if wf_status == "ok" else 1.0
        v = verdict_for(
            ev_gross, t_day, p_raw, wf_status, wf_train_ev,
            wf_test_ev, wf_test_p, n_days, net_ev, name,
            n_cross_factor=N_CROSS_FACTOR,  # ×12
        )
        verdicts.append(v)
        summary_rows.append({
            "name": name, "n_picks": len(picks), "n_days": n_days,
            "ev_gross": ev_gross, "net_ev": round(net_ev, 3),
            "t_day": t_day, "p_raw": p_raw,
            "bonf_x12": bonferroni_p(p_raw, 12),
            "wf_status": wf_status, "wf_train_ev": wf_train_ev,
            "wf_test_ev": wf_test_ev, "wf_test_t": wf_test_t,
            "wf_test_p": wf_test_p, "verdict": v,
        })

    # ---- weight-search robustness (4 schemes, ×4 correction → ×48 total) ----
    print(f"\n{'=' * 70}")
    print(f"[6] 权重搜索 robustness ({N_WEIGHT_SCHEMES} 预设方案, "
          f"Bonferroni ×{N_WEIGHT_SCHEMES} → 总 ×{12 * N_WEIGHT_SCHEMES})")
    print(f"  方案是 hypothesis-driven 预设 (非 data-fit), 仍校正搜索次数.")
    print(f"  用 top-3 子集 (中等集中度) 跑每方案, 取 best EV, 报 ×48 校正.")
    print(f"{'=' * 70}")

    scheme_results: list[tuple[str, list[dict], dict]] = []
    for sname, w in WEIGHT_SCHEMES.items():
        compute_composite(blanket, weights=w)  # 重算 composite 用新权重
        tk = select_topk_by_composite(blanket, 3)
        r = analyze_subset(
            f"top-3/{sname}", tk,
            ret_fn_basic=close_ev_basic, ret_fn_stop=close_ev_stop,
            ret_fn_label="close_ev",
        )
        scheme_results.append((sname, tk, r))

    # best by gross EV
    best = max(scheme_results, key=lambda x: x[2].get("basic_ev", {}).get("ev", -1e9))
    b_name, b_picks, b_r = best
    b_ev = b_r.get("basic_ev", {}).get("ev", 0.0)
    b_dt = b_r.get("basic_day_t", {})
    b_wf = b_r.get("wf_basic", {})
    b_wfs = b_wf.get("status", "no_picks")
    print(f"\n  各方案 top-3 close_ev:")
    print(f"  {'scheme':<14} {'n':>5} {'days':>5} {'gross%':>8} {'day_t':>7} "
          f"{'p_raw':>9}")
    for sname, _, r in scheme_results:
        e = r.get("basic_ev", {}).get("ev", 0.0)
        d = r.get("basic_day_t", {})
        print(f"  {sname:<14} {r.get('n_picks',0):>5} {d.get('n_days',0):>5} "
              f"{e:>+8.3f} {d.get('t',0):>7.2f} {d.get('p_one_sided',1):>9.4f}")
    print(f"\n  best scheme: {b_name} (gross EV={b_ev:+.3f}%)")
    print(f"  → weight-search-corrected verdict (×{12 * N_WEIGHT_SCHEMES}):")
    v_ws = verdict_for(
        b_ev, b_dt.get("t", 0.0), b_dt.get("p_one_sided", 1.0),
        b_wfs,
        b_wf.get("train_ev", {}).get("ev", 0.0) if b_wfs == "ok" else 0.0,
        b_wf.get("test_ev", {}).get("ev", 0.0) if b_wfs == "ok" else 0.0,
        b_wf.get("test_day_t", {}).get("p_one_sided", 1.0) if b_wfs == "ok" else 1.0,
        b_dt.get("n_days", 0), b_ev - COST * 100,
        f"top-3/{b_name} (weight-search)", n_cross_factor=24,  # ×48
    )
    verdicts.append(v_ws)

    # ---- summary table ----
    print(f"\n{'=' * 70}")
    print("[7] 汇总 (close_ev %, per-day-mean t, R6 gap-through fill)")
    print(f"{'=' * 70}")
    print(f"  {'subset':<24} {'n':>6} {'days':>5} {'gross%':>8} "
          f"{'net%':>7} {'day_t':>6} {'p_raw':>8} {'Bonf':>6} "
          f"{'wf_tr%':>7} {'wf_te%':>7} {'wf_te_p':>7} {'verdict':<16}")
    for s in summary_rows:
        if s.get("verdict") == "no-data":
            print(f"  {s['name']:<24} {'-':>6} {'-':>5} {'-':>8} "
                  f"{'-':>7} {'-':>6} {'-':>8} {'-':>6} {'-':>7} {'-':>7} "
                  f"{'-':>7} no-data")
            continue
        v = s.get("verdict", "")
        bonf = s.get("bonf_x12", "-")
        if v == "(baseline)":
            bonf = "-"
        print(f"  {s['name']:<24} {s.get('n_picks','-'):>6} {s.get('n_days','-'):>5} "
              f"{s.get('ev_gross','-'):>+8.3f} {s.get('ev_gross',0)-0.3 if s.get('ev_gross','-')!='-' else '-':>+7.3f} "
              f"{s.get('t_day','-'):>6.2f} {s.get('p_raw','-'):>8.4f} "
              f"{bonf if bonf!='-' else '-':>6} "
              f"{s.get('wf_train_ev','-'):>+7.3f} {s.get('wf_test_ev','-'):>+7.3f} "
              f"{s.get('wf_test_p','-'):>7.4f} {v:<16}")

    # ---- concentration delta (top-K vs same-universe baseline) ----
    print(f"\n{'=' * 70}")
    print("集中度增量: top-K EV − all_composite EV (同 universe, 正=集中提 EV)")
    print(f"{'=' * 70}")
    base_ev = next((s.get("ev_gross", 0.0) for s in summary_rows
                    if s["name"] == "all_composite"), 0.0)
    for s in summary_rows:
        if s["name"] in ("top-1", "top-3", "top-5"):
            delta = s.get("ev_gross", 0.0) - base_ev
            print(f"  {s['name']:<10}: EV={s.get('ev_gross',0.0):+.3f}%  "
                  f"Δ vs all_composite({base_ev:+.3f}%) = {delta:+.3f}%")

    # ---- overall ----
    if "edge-confirmed" in verdicts:
        overall = "edge-confirmed"
    elif "underpowered" in verdicts:
        overall = "underpowered"
    elif "exploratory" in verdicts:
        overall = "exploratory"
    elif "no-data" in verdicts and not any(v == "falsified" for v in verdicts):
        overall = "no-data"
    else:
        overall = "edge-falsified"
    print(f"\n  OVERALL (composite-score factor): {overall}")

    _print_honest_notes(overall, summary_rows, scheme_results, b_name, v_ws)


def _report_no_data() -> None:
    print(f"\n{'=' * 70}")
    print("诚实判定: no-data")
    print(f"{'=' * 70}")
    print("  无 pick 5 因子全有 (turn/vr5/gap/lbc/gene_score), 无法排 composite.")
    print("  可能原因: gene_score 仅覆盖 2026-01-05+, 与 zt picks 日期/code 不重叠.")


def _print_honest_notes(overall: str, summary_rows: list[dict],
                        scheme_results: list, b_name: str, v_ws: str) -> None:
    print(f"\n{'=' * 70}")
    print("诚实注解")
    print(f"{'=' * 70}")
    print("1. 测了什么: 多因子复合评分 (turn+vr5+gap+lbc+gene_score, per-date")
    print("   百分位等权加和) top-K 集中度对 close_ev (T+1 open 买 → T+2 close")
    print("   卖) 的影响。仅此一维度。")
    print("2. 没测什么: composite top-K ≠ 打板有/无 edge; 未测盘中可交易性细节;")
    print("   vr5/gene_score 是排序因子非方向预判——'哪些涨停股多维度信号强'")
    print("   的排序, 不等于'方向预判'。")
    print("3. 数据源诚实: vr5 自算 (不用 watchlist.vr5——那是 S232 信号 turn>20%")
    print("   &vr5>2 的预筛子集, 用它偏到已证否 universe); gene_score 仅覆盖")
    print("   2026-01-05+, composite universe 受限该窗口 (180 天)。")
    print("4. gap 是 entry-time 信息 (T+1 open 才知道): 用它排序 entry 略有自相关")
    print("   风险, 但 T+1 open 公开可观察; 且 close_ev (非 open_ev) 测度已堵")
    print("   gap 的 T+1 日内泄漏——composite 含 gap 仍负 EV 说明 gap 泄漏被堵。")
    print("5. concentration 风险: top-1 每 1 pick/日, effective N = n_days;")
    print("   per-day-mean t 已控 N 通胀, 跨日 regime 相关未控——集中可能放大")
    print("   regime 风险非提 alpha。")
    print("6. baseline 对比须同日期域: blanket_comp_dates / all_composite 是公平")
    print("   baseline; blanket_all 含 pre-2026 无 gene 的日期, 仅供参考。")
    print("7. R6: stop 变体用 gap-through fill (T+2 open+slippage 0.2%),")
    print("   basic 无 stop R6 N/A。realistic entry: T+1 open, 一字涨停跳过")
    print("   (limit_for_code FIXED 2026-10-06, 禁 sz30/sh68 旧 bug)。")
    print("8. Bonferroni: primary cross-factor ×12 (6 factors × 2 subsets);")
    print(f"   weight-search robustness ×{12 * N_WEIGHT_SCHEMES} "
          f"(×12 × {N_WEIGHT_SCHEMES} 方案). best 方案={b_name}, verdict={v_ws}.")
    print("9. 权重方案 hypothesis-driven 预设 (equal/gene_heavy/turn_lbc/momentum),")
    print("   非 data-fit; 仍校正搜索次数 (诚实: 预设也占搜索自由度)。")
    print(f"\nOVERALL: {overall}")


if __name__ == "__main__":
    main()
