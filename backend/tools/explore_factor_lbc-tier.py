# -*- coding: utf-8 -*-
"""因子回测：lbc 连板 tier 细分 (lbc-tier).

接力段细分: lbc=2 (二连) vs lbc=3 (三连) vs lbc>=4 (高连) 分别测 close_ev。
first-board-vs-relay 已测 lbc=1 vs lbc>=2 (合并口径), 本因子细分接力段:
lbc=2/3/>=4 各自 close_ev + R6 + walk-forward。高连 (lbc>=4) 从未单独测过
(V2 用 lbc>=2 合并稀释, 高连样本少被稀释掉)。

诚实口径（P1 + 6 假 edge 教训）：
- entry = T+1 open (非 T+1 close——T close sealed 不可买; 100% winner T+1 close==high)
- 一字涨停跳过 (买不进, 用 FIXED limit_for_code 禁 sz30/sh68 旧 bug)
- close_ev 非 open_ev (open_ev 有 T+1 日内泄漏)
- R6: 跳空穿 stop 按 T+2 open + 滑点 0.2% (非 stop_price)
- per-day-mean t 非 per-trade t (同日 regime 共享 effective N<<n_trades)
- Bonferroni cross-factor ×12 (6 因子 × 2 子集), 非 within-factor ×2
- walk-forward OOS: 前半 train → 后半 test (非 in-sample 分段)

禁止外推：测了 lbc tier 细分 ≠ 打板有/无 edge——只说这一维度。

跑法：
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
  .venv/bin/python tools/explore_factor_lbc-tier.py
  (或 .venv/bin/python -m tools.explore_factor_lbc-tier ——注意 hyphen 模块名
   runpy 可能拒, 用文件路径跑最稳)
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

# 让 `from tools._factor_helpers import ...` 在文件路径跑时也工作
# (python tools/foo.py 把 tools/ 而非 backend/ 放 sys.path, 需补 backend/)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._factor_helpers import (  # noqa: E402  DRY: 禁复制 helper 代码
    COST,
    analyze_subset,
    bonferroni_p,
    build_picks_generic,
    close_ev_basic,
    close_ev_stop,
    day_paired_t,
    ev_stats,
    limit_for_code,  # re-export: 禁用 sz30/sh68 旧 bug (FIXED 2026-10-06)
    load_kline_db,
    load_zt,
    verdict_for,
    walk_forward,
)


def main() -> None:
    print("=" * 70)
    print("因子: lbc-tier (lbc 连板 tier 细分: lbc=2 / lbc=3 / lbc>=4)")
    print("=" * 70)

    print("\n加载数据…")
    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    zt_rows = load_zt()
    print(f"  kline codes: {len(code_map)}")
    print(f"  calendar days: {len(calendar)} ({calendar[0]} ~ {calendar[-1]})")
    print(f"  zt rows: {len(zt_rows)}")

    # lbc 分布概览 (证不臆造: 实测 zt_history)
    lbc_dist = Counter(lbc for _, _, lbc in zt_rows)
    print(f"\n  lbc 分布 (zt_history, lbc NULL/0 当 1):")
    for lb in sorted(lbc_dist):
        marker = " ← 本因子子集" if lb in (2, 3) or lb >= 4 else ""
        print(f"    lbc={lb}: {lbc_dist[lb]} rows{marker}")
    print(f"    (本因子: lbc=2 + lbc=3 + lbc>=4 接力段细分)")

    # 三个 disjoint 子集: lbc=2 (二连) / lbc=3 (三连) / lbc>=4 (高连)
    # filter_fn 签名: (code, lbc, t_bar, t1_bar, t2_bar) -> bool
    subsets_spec = [
        ("lbc=2 (二连)", lambda code, lbc, t_bar, t1_bar, t2_bar: lbc == 2),
        ("lbc=3 (三连)", lambda code, lbc, t_bar, t1_bar, t2_bar: lbc == 3),
        ("lbc>=4 (高连)", lambda code, lbc, t_bar, t1_bar, t2_bar: lbc >= 4),
    ]

    print(f"\n构建 picks (entry=T+1 open, exit=T+2 close, 一字涨停跳过):")
    results: list[tuple[str, list[dict], dict]] = []
    for name, fn in subsets_spec:
        picks = build_picks_generic(code_map, calendar, zt_rows, filter_fn=fn)
        print(f"  {name}: {len(picks)} picks")
        r = analyze_subset(
            name,
            picks,
            ret_fn_basic=close_ev_basic,
            ret_fn_stop=close_ev_stop,
            ret_fn_label="close_ev",
        )
        results.append((name, picks, r))

    # ---- honest verdict (cross-factor Bonferroni ×12, n_cross_factor=6) ----
    print(f"\n{'=' * 70}")
    print("诚实判定 (cross-factor Bonferroni ×12 = 6 factors × 2 subsets)")
    print(f"  注: 本因子 3 子集 (lbc=2/3/>=4), verdict_for 各跑一次 ×12;")
    print(f"  full correction 应 ×18 (6×3), 这里按跨因子标准 ×12 报告 (保守偏低).")
    print(f"{'=' * 70}")

    summary_rows: list[dict] = []
    verdicts: list[str] = []
    for name, picks, r in results:
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

    # ---- summary table ----
    print(f"\n{'=' * 70}")
    print("汇总表 (lbc-tier 三子集)")
    print(f"{'=' * 70}")
    print(
        f"  {'subset':<18} {'n':>6} {'days':>5} {'gross%':>8} {'net%':>7} "
        f"{'day_t':>6} {'p_raw':>8} {'Bonf×12':>8} {'wf_tr%':>7} "
        f"{'wf_te%':>7} {'verdict':<14}"
    )
    for s in summary_rows:
        if s.get("verdict") == "no-data":
            print(f"  {s['name']:<18} {'-':>6} {'-':>5} {'-':>8} {'-':>7} {'-':>6} {'-':>8} {'-':>8} {'-':>7} {'-':>7} no-data")
            continue
        print(
            f"  {s['name']:<18} {s['n_picks']:>6} {s['n_days']:>5} "
            f"{s['ev_gross']:>8} {s['net_ev']:>7} {s['t_day']:>6} "
            f"{s['p_raw']:>8} {s['bonf_x12']:>8} {s['wf_train_ev']:>7} "
            f"{s['wf_test_ev']:>7} {s['verdict']:<14}"
        )

    # overall
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
    print(f"\n  OVERALL (lbc-tier factor): {overall}")

    print(f"\n注: 本实验只测 lbc tier 细分 (lbc=2/3/>=4 接力段), 禁止外推成'打板有/无 edge'。")
    print(f"R6: stop 变体用 gap-through fill (T+2 open+slippage 0.2%), basic 无 stop R6 N/A。")
    print(f"realistic entry: T+1 open (非 T+1 close), 一字涨停跳过 (limit_for_code FIXED 2026-10-06)。")
    print(f"Bonferroni: cross-factor ×12 (6 factors × 2 subsets); 本因子 3 子集 full correction 应 ×18, 按跨因子标准 ×12 报告。")


if __name__ == "__main__":
    main()
