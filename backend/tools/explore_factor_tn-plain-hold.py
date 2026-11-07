# -*- coding: utf-8 -*-
"""因子回测：T+N plain hold (无 stop 无 trailing, 就是不卖继续拿).

P1 测过 trailing stop 更差, 但 plain hold 到 T+2/T+3/T+4 close 未测.
本因子: 对非一字 T+1 winners, entry=T+1 open, exit=T+N close (N=2/3/4).
- N=2 = baseline (= close_ev_basic, T+1 open → T+2 close, 所有其他因子的标准口径)
- N=3 = 多持一天 (T+1 open → T+3 close)
- N=4 = 多持两天 (T+1 open → T+4 close)

问题: 持仓更久是否改善 EV? 还是时间越长 winner 衰减越快 (mean reversion)?

诚实口径（P1 + 6 假 edge 教训）：
- entry = T+1 open (非 T+1 close——T close sealed 不可买)
- 一字涨停跳过 (买不进, 用 FIXED limit_for_code 禁 sz30/sh68 旧 bug)
- close_ev 非 open_ev (open_ev 有 T+1 日内泄漏)
- 无 stop 无 trailing → R6 gap-through fill N/A (r6_fill_applied=False)
- per-day-mean t 非 per-trade t (同日 regime 共享 effective N<<n_trades)
- Bonferroni cross-factor ×12 (6 因子 × 2 子集), 非 within-factor ×3
- walk-forward OOS: 前半 train → 后半 test (非 in-sample 分段)

禁止外推：测了 plain hold holding-period 维度 ≠ 打板有/无 edge——只说这一维度。

DRY: import tools._factor_helpers (禁复制 helper 代码).
build_picks_generic 只载 T+1/T+2, 本脚本 enrich T+3/T+4 bar.

跑法：
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
  .venv/bin/python tools/explore_factor_tn-plain-hold.py
  (hyphen 文件名不可 -m, 用文件路径跑)
"""

from __future__ import annotations

import sys
from collections import defaultdict
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
    day_paired_t,
    ev_stats,
    limit_for_code,  # re-export: 禁用 sz30/sh68 旧 bug (FIXED 2026-10-06)
    load_kline_db,
    load_zt,
    verdict_for,
    walk_forward,
)


# ---------- T+3/T+4 enrichment (build_picks_generic 只载 T+1/T+2) ----------


def enrich_tn(picks: list[dict], code_map: dict[str, dict[str, dict]], calendar: list[str]) -> list[dict]:
    """给每个 pick 加 t3_bar / t4_bar (T+3 / T+4 bars).

    build_picks_generic 只载 T+1/T+2 (d_idx+2 < len 检查).
    本函数补 T+3/T+4: 从 t2_date 索引 +1/+2 取 calendar, 查 code_map.
    跳过缺 T+3/T+4 bar 的 picks (保证 N=2/3/4 同一 pick 集, apples-to-apples).

    返回新 pick list (immutable: 新 dict, 不改原 pick).
    """
    date_idx = {d: i for i, d in enumerate(calendar)}
    enriched: list[dict] = []
    n_dropped = 0
    for p in picks:
        t2_i = date_idx.get(p["t2_date"])
        if t2_i is None or t2_i + 2 >= len(calendar):
            n_dropped += 1
            continue  # need T+3 and T+4
        t3_date = calendar[t2_i + 1]
        t4_date = calendar[t2_i + 2]
        dmap = code_map.get(p["code"])
        if not dmap:
            n_dropped += 1
            continue
        t3_bar = dmap.get(t3_date)
        t4_bar = dmap.get(t4_date)
        if t3_bar is None or t4_bar is None:
            n_dropped += 1
            continue
        t3_close = t3_bar.get("close")
        t4_close = t4_bar.get("close")
        if t3_close is None or t4_close is None:
            n_dropped += 1
            continue
        if t3_close <= 0 or t4_close <= 0:
            n_dropped += 1
            continue
        # immutable: 新 dict 不改原 p
        p2 = {**p, "t3_date": t3_date, "t4_date": t4_date, "t3_bar": t3_bar, "t4_bar": t4_bar}
        enriched.append(p2)
    print(f"  enrich: {len(picks)} → {len(enriched)} picks (dropped {n_dropped} 缺 T+3/T+4 bar)")
    return enriched


# ---------- close_ev_tn (factor-specific ret_fn) ----------


def close_ev_tn(p: dict, n: int) -> float | None:
    """T+1 open 买 → T+N close 卖 (N=2/3/4). 无 stop 无 trailing.

    N=2 = baseline (= close_ev_basic).
    """
    entry = p["entry"]
    if entry <= 0:
        return None
    if n == 2:
        close = p["t2_bar"].get("close")
    elif n == 3:
        close = p["t3_bar"].get("close")
    elif n == 4:
        close = p["t4_bar"].get("close")
    else:
        return None
    if close is None or close <= 0:
        return None
    return (close - entry) / entry * 100


def make_ret_fn(n: int):
    """闭包绑定 n (避免 lambda late-binding)."""
    return lambda p: close_ev_tn(p, n)


# ---------- main ----------


def main() -> None:
    print("=" * 70)
    print("因子: tn-plain-hold (T+N plain hold, 无 stop 无 trailing)")
    print("  N=2 (baseline) / N=3 (多持一天) / N=4 (多持两天)")
    print("=" * 70)

    print("\n加载数据…")
    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    zt_rows = load_zt()
    print(f"  kline codes: {len(code_map)}")
    print(f"  calendar days: {len(calendar)} ({calendar[0]} ~ {calendar[-1]})")
    print(f"  zt rows: {len(zt_rows)}")

    # 构建 picks: filter_fn=None → 全部非一字 T+1 winners (不分 lbc tier)
    # build_picks_generic 已处理: yizi skip + limit_for_code (FIXED) + entry=T+1 open
    print(f"\n构建 picks (entry=T+1 open, 一字涨停跳过, 全 lbc):")
    base_picks = build_picks_generic(code_map, calendar, zt_rows, filter_fn=None)
    print(f"  base picks (T+1/T+2): {len(base_picks)}")

    # enrich T+3/T+4 (同一 pick 集跑 N=2/3/4, apples-to-apples)
    picks = enrich_tn(base_picks, code_map, calendar)
    print(f"  final picks (有 T+2/T+3/T+4): {len(picks)}")

    # 三个 holding-period 子集, 同一 pick 集
    ns = [2, 3, 4]
    results: list[tuple[int, list[dict], dict]] = []
    for n in ns:
        name = f"N={n} (T+{n} close)"
        r = analyze_subset(
            name,
            picks,
            ret_fn_basic=make_ret_fn(n),
            ret_fn_stop=None,  # plain hold 无 stop → 无 stop variant
            ret_fn_label=f"close_ev_t+{n}",
        )
        results.append((n, picks, r))

    # ---- honest verdict (cross-factor Bonferroni ×12, n_cross_factor=6) ----
    print(f"\n{'=' * 70}")
    print("诚实判定 (cross-factor Bonferroni ×12 = 6 factors × 2 subsets)")
    print(f"  注: 本因子 3 子集 (N=2/3/4), verdict_for 各跑一次 ×12;")
    print(f"  full correction 应 ×18 (6×3), 按跨因子标准 ×12 报告 (保守偏低).")
    print(f"{'=' * 70}")

    summary_rows: list[dict] = []
    verdicts: list[str] = []
    for n, _, r in results:
        name = f"N={n} (T+{n} close)"
        if not picks or r.get("n_picks", 0) == 0:
            print(f"\n  {name}: 无 picks → no-data")
            verdicts.append("no-data")
            summary_rows.append({"name": name, "n": n, "verdict": "no-data"})
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
                "n": n,
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
    print("汇总表 (tn-plain-hold 三 holding-period 子集, 同一 pick 集)")
    print(f"{'=' * 70}")
    print(
        f"  {'subset':<16} {'n':>6} {'days':>5} {'gross%':>8} {'net%':>7} {'day_t':>6} {'p_raw':>8} {'Bonf×12':>8} {'wf_tr%':>7} {'wf_te%':>7} {'verdict':<14}"
    )
    for s in summary_rows:
        if s.get("verdict") == "no-data":
            print(f"  {s['name']:<16} {'-':>6} {'-':>5} {'-':>8} {'-':>7} {'-':>6} {'-':>8} {'-':>8} {'-':>7} {'-':>7} no-data")
            continue
        print(
            f"  {s['name']:<16} {s['n_picks']:>6} {s['n_days']:>5} "
            f"{s['ev_gross']:>8} {s['net_ev']:>7} {s['t_day']:>6} "
            f"{s['p_raw']:>8} {s['bonf_x12']:>8} {s['wf_train_ev']:>7} "
            f"{s['wf_test_ev']:>7} {s['verdict']:<14}"
        )

    # trend analysis: N=2 → N=3 → N=4 EV trajectory
    print(f"\n--- holding-period 趋势 (N=2 → N=3 → N=4) ---")
    evs = {s["n"]: s.get("ev_gross") for s in summary_rows if s.get("verdict") != "no-data"}
    if len(evs) >= 2:
        n2, n3, n4 = evs.get(2), evs.get(3), evs.get(4)
        print(f"  N=2: {n2}%  →  N=3: {n3}%  →  N=4: {n4}%")
        if n2 is not None and n4 is not None:
            delta_24 = n4 - n2
            print(f"  N=4 - N=2 = {delta_24:+.3f}% (持仓多两天 EV 变化)")
            if n4 < n2:
                print(f"  → 持仓越久 EV 越低 (winner 衰减, mean reversion)")
            elif n4 > n2:
                print(f"  → 持仓越久 EV 越高 (trend continuation)")
            else:
                print(f"  → 持仓长短无差异")
        if n3 is not None and n2 is not None:
            print(f"  N=3 - N=2 = {n3 - n2:+.3f}%")

    # overall verdict
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
    print(f"\n  OVERALL (tn-plain-hold factor): {overall}")

    print(f"\n注: 本实验只测 plain hold holding-period 维度 (N=2/3/4), 禁止外推成'打板有/无 edge'。")
    print(f"R6: plain hold 无 stop → R6 gap-through fill N/A (r6_fill_applied=False)。")
    print(f"realistic entry: T+1 open (非 T+1 close), 一字涨停跳过 (limit_for_code FIXED 2026-10-06)。")
    print(f"Bonferroni: cross-factor ×12 (6 factors × 2 subsets); 本因子 3 子集 full correction 应 ×18, 按跨因子标准 ×12 报告。")
    print(f"同一 pick 集跑 N=2/3/4 (apples-to-apples, 不因缺 T+3/T+4 偏差).")


if __name__ == "__main__":
    main()
