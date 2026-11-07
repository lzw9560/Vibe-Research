# -*- coding: utf-8 -*-
"""因子回测：top-k-gene (Top-K 集中度 by 信号强度 gene_score).

每日按 gene_score (total_score) 排序 zt picks，取 top-1/top-3/top-5，
close_ev vs blanket。测"高确信集中"是否提 EV。

信号评分来源: gene_scores.db (limitup_screener, .vibe-research/gene_scores.db)
  表 gene_scores: date / code / total_score (历史基础率合成分: 次日溢价率+
  红盘率+封板率+炸板后溢价+涨停频次, 250 日回看 wilson 调整)。total_score 是
  T 日及之前历史统计合成, 不含 T+1/T+2 未来信息 → 无 look-ahead。

方法论诚实点 (task 明确要求):
  - explore_s232_risk 已示: 同日 regime 共享 effective N<<n_trades, concentration
    可能放大相关风险非提 alpha → 必须用 per-day-mean t (helper.day_paired_t),
    effective N = n_days 非 n_picks。
  - top-1 每 1 pick/日 → n_days = n_picks, day_paired_t = 单笔 t (诚实 effective N)。
  - blanket 对比须同日期域 (gene-scored dates) 否则比不同 regime。

诚实口径 (P1 + 6 假 edge 教训):
  - entry = T+1 open (非 T+1 close——T close sealed 不可买)
  - 一字涨停跳过 (买不进, 用 FIXED limit_for_code 禁 sz30/sh68 旧 bug)
  - close_ev 非 open_ev (open_ev 有 T+1 日内泄漏)
  - R6: 跳空穿 stop 按 T+2 open + 滑点 0.2%
  - per-day-mean t 非 per-trade t
  - Bonferroni cross-factor ×12 (6 因子 × 2 子集)
  - walk-forward OOS: 前半 train → 后半 test
  - 禁止外推: top-k 集中度 ≠ 打板有/无 edge

跑法:
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
  .venv/bin/python tools/explore_factor_top-k-gene.py
"""

from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

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

# gene_scores.db 路径——镜像 helper 的 ROOT/.vibe-research 逻辑 (helper 用
# parents[2]=repo root + ".vibe-research"; 同样路径, 不复制 helper 内部常量)
# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

ROOT = Path(__file__).resolve().parents[2]
GENE_DB = resolve_data_dir() / "gene_scores.db"


def load_gene_scores() -> dict[str, dict[str, float]]:
    """读 gene_scores.db → {date: {code: total_score}}.

    total_score 为 T 日历史基础率合成分 (wilson 调整, 250 日回看),
    不含 T+1/T+2 未来信息 → 无 look-ahead。
    """
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
    """给每个 pick 附 gene_score (按 zt_date+code 查). 返回 (picks, n_with_score).

    无 gene_score 的 pick 标 score=None——仍在 blanket, 但不进 top-k 排名。
    """
    n_with = 0
    for p in picks:
        dmap = gene.get(p["zt_date"])
        score = dmap.get(p["code"]) if dmap else None
        p["gene_score"] = score
        if score is not None:
            n_with += 1
    return picks, n_with


def select_topk_per_date(picks: list[dict], k: int) -> list[dict]:
    """每 zt_date 取 gene_score 最高的 top-k picks (只含有 score 的).

    同日不足 k 个则全取。返回 picks (浅拷贝引用, 不改原)。
    """
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


def main() -> None:
    print("=" * 70)
    print("因子: top-k-gene (Top-K 集中度 by gene_score 信号强度)")
    print("=" * 70)

    print("\n加载数据…")
    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    zt_rows = load_zt()
    gene, n_gene = load_gene_scores()
    print(f"  kline codes: {len(code_map)}, calendar: {len(calendar)} ({calendar[0]} ~ {calendar[-1]})")
    print(f"  zt rows: {len(zt_rows)}")
    print(f"  gene_scores: {n_gene} rows, {len(gene)} dates ({min(gene)} ~ {max(gene)})")
    print(f"  gene_scores.db: {GENE_DB}")

    # ---- 构建 blanket picks (no filter) ----
    print("\n构建 blanket picks (entry=T+1 open, exit=T+2 close, 一字涨停跳过)…")
    blanket = build_picks_generic(code_map, calendar, zt_rows, filter_fn=None)
    blanket, n_with = attach_gene_scores(blanket, gene)
    print(f"  blanket picks: {len(blanket)}")
    print(f"  其中有 gene_score: {n_with} ({n_with / max(len(blanket), 1) * 100:.1f}%)")

    # 日期域: 有 ≥1 gene-scored pick 的 zt_date (top-k 子集的日期域)
    gene_dates_with_picks = sorted({p["zt_date"] for p in blanket if p.get("gene_score") is not None})
    print(
        f"  gene-scored pick 日期数: {len(gene_dates_with_picks)} "
        f"({gene_dates_with_picks[0]} ~ {gene_dates_with_picks[-1]})"
        if gene_dates_with_picks
        else "  无 gene-scored pick 日期"
    )

    if not gene_dates_with_picks:
        print("\n  → no-data: 无 zt pick 能匹配 gene_score (日期/code 不重叠)")
        _report_no_data()
        return

    # ---- 子集定义 ----
    # blanket 全集 (所有日期) — 上下文参考
    # blanket_gene_dates: 同日期域 baseline (gene-scored dates) — 公平对比
    # all_gene_scored: 所有有 gene_score 的 picks (可排名 universe) — 同 universe 无集中
    # top-1 / top-3 / top-5: 按日 gene_score 排名取 top-k
    blanket_gene_dates = [p for p in blanket if p["zt_date"] in set(gene_dates_with_picks)]
    all_gene_scored = [p for p in blanket if p.get("gene_score") is not None]
    top1 = select_topk_per_date(blanket, 1)
    top3 = select_topk_per_date(blanket, 3)
    top5 = select_topk_per_date(blanket, 5)

    print(f"\n子集 picks 数:")
    print(f"  blanket (all dates):      {len(blanket)}")
    print(f"  blanket (gene dates):     {len(blanket_gene_dates)}")
    print(f"  all gene-scored picks:    {len(all_gene_scored)}")
    print(f"  top-1 (per date):         {len(top1)}  (= n_days, 1 pick/day)")
    print(f"  top-3 (per date):         {len(top3)}")
    print(f"  top-5 (per date):         {len(top5)}")

    # ---- 分析各子集 ----
    subsets = [
        ("blanket_all", blanket),
        ("blanket_gene_dates", blanket_gene_dates),
        ("all_gene_scored", all_gene_scored),
        ("top-1", top1),
        ("top-3", top3),
        ("top-5", top5),
    ]
    results: list[tuple[str, list[dict], dict]] = []
    for name, picks in subsets:
        r = analyze_subset(
            name,
            picks,
            ret_fn_basic=close_ev_basic,
            ret_fn_stop=close_ev_stop,
            ret_fn_label="close_ev",
        )
        results.append((name, picks, r))

    # ---- 诚实判定 (top-1/3/5 三个因子子集, cross-factor Bonferroni ×12) ----
    print(f"\n{'=' * 70}")
    print("诚实判定 (top-k 子集, cross-factor Bonferroni ×12 = 6 factors × 2 subsets)")
    print(f"  注: blanket 子集是 baseline 不出 factor verdict (只作对比);")
    print(f"  top-1/3/5 三子集 verdict_for 各跑 ×12;")
    print(f"  full correction 应 ×18 (6×3), 按跨因子标准 ×12 报告 (保守偏低).")
    print(f"{'=' * 70}")

    summary_rows: list[dict] = []
    verdicts: list[str] = []
    factor_subset_names = {"top-1", "top-3", "top-5"}
    for name, picks, r in results:
        if name not in factor_subset_names:
            # baseline 只汇总, 不出 factor verdict
            ev = r.get("basic_ev", {}).get("ev", 0.0)
            dt = r.get("basic_day_t", {})
            summary_rows.append(
                {
                    "name": name,
                    "n_picks": len(picks),
                    "n_days": dt.get("n_days", 0),
                    "ev_gross": ev,
                    "t_day": dt.get("t", 0.0),
                    "p_raw": dt.get("p_one_sided", 1.0),
                    "wf_train_ev": (
                        r.get("wf_basic", {}).get("train_ev", {}).get("ev", 0.0)
                        if r.get("wf_basic", {}).get("status") == "ok"
                        else 0.0
                    ),
                    "wf_test_ev": (
                        r.get("wf_basic", {}).get("test_ev", {}).get("ev", 0.0)
                        if r.get("wf_basic", {}).get("status") == "ok"
                        else 0.0
                    ),
                    "wf_test_t": (
                        r.get("wf_basic", {}).get("test_day_t", {}).get("t", 0.0)
                        if r.get("wf_basic", {}).get("status") == "ok"
                        else 0.0
                    ),
                    "wf_test_p": (
                        r.get("wf_basic", {}).get("test_day_t", {}).get("p_one_sided", 1.0)
                        if r.get("wf_basic", {}).get("status") == "ok"
                        else 1.0
                    ),
                    "verdict": "(baseline)",
                }
            )
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
            ev_gross,
            t_day,
            p_raw,
            wf_status,
            wf_train_ev,
            wf_test_ev,
            wf_test_p,
            n_days,
            net_ev,
            name,
            n_cross_factor=6,  # ×12 = 6 factors × 2 subsets
        )
        verdicts.append(v)
        summary_rows.append(
            {
                "name": name,
                "n_picks": len(picks),
                "n_days": n_days,
                "ev_gross": ev_gross,
                "net_ev": round(net_ev, 3),
                "t_day": t_day,
                "p_raw": p_raw,
                "bonf_x12": bonferroni_p(p_raw, 12),
                "wf_status": wf_status,
                "wf_train_ev": wf_train_ev,
                "wf_test_ev": wf_test_ev,
                "wf_test_t": wf_test_t,
                "wf_test_p": wf_test_p,
                "verdict": v,
            }
        )

    # ---- 汇总表 ----
    print(f"\n{'=' * 70}")
    print("汇总表 (close_ev %, per-day-mean t, R6 gap-through fill)")
    print(f"{'=' * 70}")
    print(
        f"  {'subset':<22} {'n':>6} {'days':>5} {'gross%':>8} "
        f"{'day_t':>6} {'p_raw':>8} {'Bonf×12':>8} {'wf_tr%':>7} "
        f"{'wf_te%':>7} {'wf_te_p':>7} {'verdict':<14}"
    )
    for s in summary_rows:
        if s.get("verdict") == "no-data":
            print(
                f"  {s['name']:<22} {'-':>6} {'-':>5} {'-':>8} "
                f"{'-':>6} {'-':>8} {'-':>8} {'-':>7} {'-':>7} {'-':>7} no-data"
            )
            continue
        v = s.get("verdict", "")
        bonf = s.get("bonf_x12", "-")
        if v == "(baseline)":
            bonf = "-"
        print(
            f"  {s['name']:<22} {s.get('n_picks', '-'):>6} {s.get('n_days', '-'):>5} "
            f"{s.get('ev_gross', '-'):>8} {s.get('t_day', '-'):>6} "
            f"{s.get('p_raw', '-'):>8} {bonf if bonf != '-' else '-':>8} "
            f"{s.get('wf_train_ev', '-'):>7} {s.get('wf_test_ev', '-'):>7} "
            f"{s.get('wf_test_p', '-'):>7} {v:<14}"
        )

    # ---- concentration 增量对比 (top-k vs 同 universe baseline) ----
    print(f"\n{'=' * 70}")
    print("集中度增量: top-k EV − all_gene_scored EV (同 universe, 正=集中提 EV)")
    print(f"{'=' * 70}")
    base_ev = next((s.get("ev_gross", 0.0) for s in summary_rows if s["name"] == "all_gene_scored"), 0.0)
    for s in summary_rows:
        if s["name"] in ("top-1", "top-3", "top-5"):
            delta = s.get("ev_gross", 0.0) - base_ev
            print(
                f"  {s['name']:<10}: EV={s.get('ev_gross', '-'):+.3f}%  "
                f"Δ vs all_gene_scored({base_ev:+.3f}%) = {delta:+.3f}%"
            )

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
    print(f"\n  OVERALL (top-k-gene factor): {overall}")

    _print_honest_notes(overall, summary_rows)


def _report_no_data() -> None:
    print(f"\n{'=' * 70}")
    print("诚实判定: no-data")
    print(f"{'=' * 70}")
    print("  gene_scores.db 有数据但与 zt picks 日期/code 无重叠 → 无法排名。")
    print("  可能原因: zt 日期全在 gene_scores 范围外, 或 code 池完全不交。")


def _print_honest_notes(overall: str, summary_rows: list[dict]) -> None:
    print(f"\n{'=' * 70}")
    print("诚实注解")
    print(f"{'=' * 70}")
    print("1. 测了什么: gene_score (历史基础率合成分) 排名 top-k 集中度对")
    print("   close_ev (T+1 open 买 → T+2 close 卖) 的影响。仅此一维度。")
    print("2. 没测什么: 单因子 ≠ 打板有/无 edge; 未测盘中可交易性细节;")
    print("   gene_score 用历史 250 日基础率, 非当日盘口 alpha——是'哪些涨停股")
    print("   历史溢价率高'的排序, 非方向预判。")
    print("3. concentration 风险: top-1 每 1 pick/日, effective N = n_days;")
    print("   同日 regime 共享 → per-day-mean t 已控 N 通胀, 但跨日 regime")
    print("   相关未控——集中可能放大 regime 风险非提 alpha (task 明示)。")
    print("4. baseline 对比须同日期域: blanket_gene_dates / all_gene_scored 是")
    print("   公平 baseline; blanket_all 含 pre-2026 无 gene 的日期, 仅供参考。")
    print("5. R6: stop 变体用 gap-through fill (T+2 open+slippage 0.2%),")
    print("   basic 无 stop R6 N/A。realistic entry: T+1 open, 一字涨停跳过")
    print("   (limit_for_code FIXED 2026-10-06, 禁 sz30/sh68 旧 bug)。")
    print("6. Bonferroni: cross-factor ×12 (6 factors × 2 subsets); 本因子")
    print("   3 子集 full correction 应 ×18, 按跨因子标准 ×12 报告 (保守偏低)。")
    print(f"\nOVERALL: {overall}")


if __name__ == "__main__":
    main()
