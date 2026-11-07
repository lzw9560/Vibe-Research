# -*- coding: utf-8 -*-
"""因子回测：板块类型分层 (board-type).

主板(600/601/603/605/000/001/002/003, 10% limit) vs 创业板(300/301, 20%) vs
科创板(688/689, 20%) vs 北交(4/8, 30%) 分别测 close_ev。
20% board 涨停含金量更高(更难封板)，edge 可能不同。

诚实口径（P1 + 6 假 edge 教训，全过）：
- entry = T+1 open (非 T+1 close——T close sealed 不可买; 100% winner T+1 close==high)
- 若 T+1 一字涨停 (open=low=limit-up), 跳过 (买不进)
- close_ev = (T+2 close - T+1 open) / T+1 open * 100  (非 open_ev, 防 T+1 日内泄漏)
- stop 变体: -3% stop + R6 gap-through fill (跳空穿 stop 按 T+2 open + 滑点 0.2%)
- per-day-mean t (同日多笔聚成 day-mean, 非 per-trade t——同日相关夸大 N)
- Bonferroni cross-factor ×12 (6 因子 × 2 subsets)
- walk-forward OOS: 前半 train → 后半 test (非 in-sample 分段)
- 用 _factor_helpers.limit_for_code (FIXED 2026-10-06, 禁用 sz30/sh68 旧 bug)

禁止外推：测了板块类型分层 ≠ 打板有/无 edge——只说这一维度。

跑法：cd backend && .venv/bin/python -m tools.explore_factor_board-type
"""

from __future__ import annotations
from collections import defaultdict

from tools._factor_helpers import (
    load_kline_db,
    load_zt,
    limit_for_code,
    build_picks_generic,
    analyze_subset,
    verdict_for,
    close_ev_basic,
    close_ev_stop,
    ev_stats,
    day_paired_t,
    bonferroni_p,
    COST,
)


# ---------- board-type classification (matches limit_for_code prefixes) ----------


def board_of(code: str) -> str:
    """按 6 位纯数字 code 前缀判板块类型。前缀与 limit_for_code 一致。

    - main:      600/601/603/605 (SH主板) + 000/001/002/003 (SZ主板) → 10%
    - chuangye:  300/301 → 20%
    - kechuang:  688/689 → 20%
    - beijiao:   4/8 开头 → 30%
    - other:     其余 (920 新北交码 limit_for_code 当 10%, 302 罕见) — 排除

    注: 920xxx 是北交所新代码 (真实 30% limit)，但 limit_for_code 未特判 → 当 10%。
    zt_history 中 920 仅 21 行 / 302 仅 3 行，影响可忽略，归 other 排除。
    """
    if code.startswith(("300", "301")):
        return "chuangye"
    if code.startswith(("688", "689")):
        return "kechuang"
    if code.startswith(("4", "8")):
        return "beijiao"
    if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return "main"
    return "other"


def make_board_filter(board: str):
    """返回 filter_fn(code, lbc, t_bar, t1_bar, t2_bar) → bool, 只纳指定板块。"""

    def _fn(code: str, lbc: int, t_bar: dict, t1_bar: dict, t2_bar: dict) -> bool:
        return board_of(code) == board

    return _fn


# ---------- main ----------

SUBSETS = [
    ("main 主板(600/601/603/605/000/001/002/003 10%)", "main"),
    ("chuangye 创业板(300/301 20%)", "chuangye"),
    ("kechuang 科创板(688/689 20%)", "kechuang"),
    ("beijiao 北交(4/8 30%)", "beijiao"),
]


def main():
    print("加载数据…")
    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    zt_rows = load_zt()
    print(f"  kline codes: {len(code_map)}")
    print(f"  calendar days: {len(calendar)} ({calendar[0]} ~ {calendar[-1]})")
    print(f"  zt rows: {len(zt_rows)}")

    # 板块分布预览
    board_counts: dict[str, int] = defaultdict(int)
    for _, code, _ in zt_rows:
        board_counts[board_of(code)] += 1
    print(f"\n  ZT rows 板块分布:")
    for b, c in sorted(board_counts.items(), key=lambda x: -x[1]):
        print(f"    {b}: {c}")

    # 构建各板块子集 (entry=T+1 open, 一字涨停跳过, limit_for_code FIXED)
    print(f"\n构建 picks (entry=T+1 open, 一字涨停跳过, limit_for_code FIXED):")
    built = []
    for label, board in SUBSETS:
        picks = build_picks_generic(code_map, calendar, zt_rows, filter_fn=make_board_filter(board))
        print(f"  {label}: {len(picks)} picks")
        built.append((label, board, picks))

    # 分析各子集
    analyses = []
    for label, board, picks in built:
        a = analyze_subset(
            label, picks, ret_fn_basic=close_ev_basic, ret_fn_stop=close_ev_stop, ret_fn_label="close_ev"
        )
        analyses.append((label, board, picks, a))

    # ---- honest verdict per subset (cross-factor Bonferroni ×12) ----
    print(f"\n{'=' * 70}")
    print("诚实判定 (cross-factor Bonferroni ×12 = 6 factors × 2 subsets)")
    print(f"{'=' * 70}")

    verdicts = []
    for label, board, picks, a in analyses:
        be = a.get("basic_ev", {})
        bdt = a.get("basic_day_t", {})
        wf = a.get("wf_basic", {})
        ev_gross = be.get("ev", 0.0)
        n_days = bdt.get("n_days", 0)
        t_day = bdt.get("t", 0.0)
        p_raw = bdt.get("p_one_sided", 1.0)
        net_ev = ev_gross - COST * 100
        wf_status = wf.get("status", "no_picks")
        wf_train = wf.get("train_ev", {}).get("ev", 0.0)
        wf_test = wf.get("test_ev", {}).get("ev", 0.0)
        wf_test_t = wf.get("test_day_t", {}).get("t", 0.0)
        wf_test_p = wf.get("test_day_t", {}).get("p_one_sided", 1.0)
        v = verdict_for(
            ev_gross, t_day, p_raw, wf_status, wf_train, wf_test, wf_test_p, n_days, net_ev, label, n_cross_factor=6
        )
        verdicts.append(
            {
                "label": label,
                "board": board,
                "verdict": v,
                "n_picks": len(picks),
                "ev_gross": ev_gross,
                "t_day": t_day,
                "p_raw": p_raw,
                "n_days": n_days,
                "net_ev": net_ev,
                "wf_status": wf_status,
                "wf_train": wf_train,
                "wf_test": wf_test,
                "wf_test_t": wf_test_t,
                "wf_test_p": wf_test_p,
            }
        )

    # ---- overall factor verdict ----
    print(f"\n{'=' * 70}")
    print("OVERALL 板块类型分层判定")
    print(f"{'=' * 70}")
    v_list = [r["verdict"] for r in verdicts]
    if "edge-confirmed" in v_list:
        overall = "edge-confirmed"
    elif "underpowered" in v_list:
        overall = "underpowered"
    elif "exploratory" in v_list:
        overall = "exploratory"
    else:
        overall = "edge-falsified"
    print(f"\n  OVERALL: {overall}")

    # 汇总表
    print(f"\n{'=' * 70}")
    print("汇总表")
    print(f"{'=' * 70}")
    print(f"{'subset':<44} {'n':>5} {'EV%':>8} {'net%':>8} {'t_day':>7} {'n_days':>6} {'Bonf×12':>9} {'verdict':<14}")
    for r in verdicts:
        bonf = bonferroni_p(r["p_raw"], 12)
        short = r["label"].split("(")[0].strip()
        print(
            f"{short:<44} {r['n_picks']:>5} {r['ev_gross']:>8.3f} "
            f"{r['net_ev']:>8.3f} {r['t_day']:>7.2f} {r['n_days']:>6} "
            f"{bonf:>9.6f} {r['verdict']:<14}"
        )

    # walk-forward 汇总
    print(f"\nwalk-forward OOS 汇总:")
    print(f"{'subset':<44} {'train%':>8} {'test%':>8} {'test_t':>7} {'test_p':>8}")
    for r in verdicts:
        if r["wf_status"] == "ok":
            print(
                f"{r['label'].split('(')[0].strip():<44} "
                f"{r['wf_train']:>8.3f} {r['wf_test']:>8.3f} "
                f"{r['wf_test_t']:>7.2f} {r['wf_test_p']:>8.6f}"
            )
        else:
            print(f"{r['label'].split('(')[0].strip():<44} {r['wf_status']}")

    print(f"\n注: 本实验只测板块类型分层维度, 禁止外推成'打板有/无 edge'。")
    print(f"R6: stop 变体用 gap-through fill (T+2 open+slippage), basic 无 stop。")
    print(f"realistic entry: T+1 open (非 T+1 close), 一字涨停跳过 (limit_for_code FIXED)。")
    print(f"Bonferroni: cross-factor ×12 (6 factors × 2 subsets)。board-type 有 4 subsets,")
    print(f"  若按 within-board 4 subsets × 6 factors = ×24 更严, 但此处按统一 ×12 标准。")
    print(f"beijiao (4/8) zt_history 中 0 行; 920 新北交码 21 行被 limit_for_code 当 10%, 归 other 排除。")


if __name__ == "__main__":
    main()
