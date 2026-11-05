# -*- coding: utf-8 -*-
"""combo real-exec 限 T 日 gap（2026-11-05，优化空间测试，用户"持续推进"）。

entry_gap 是 T+1 open（次日）——选股时（T 收盘）不知道，直接限 = look-ahead bias。
但限 **T 日 gap**（T 开盘 vs T-1 收盘，选股时已知）间接降 entry_gap（T 日高开的票 T+1 可能继续高开）。
对比不限 gap（轮11 real-exec net +0.336%）vs 限 T 日 gap < 3%/2%/1%/0.5%。
去 gap rank（动量+小盘），mode=filtered。
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _audit_combo_real_exec import build_by_date, TOP_N, COST  # noqa: E402


def rank_top_nogap(lst: list, n: int = TOP_N) -> list | None:
    if len(lst) < n * 10:
        return None
    nn = len(lst)
    st = sorted(range(nn), key=lambda k: lst[k]["tr"])
    sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    score = lambda k: rt[k] + ra[k]
    return [lst[k] for k in sorted(range(nn), key=score, reverse=True)[:n]]


def stats(dates: list, by_date: dict, gap_limit: float | None = None) -> dict | None:
    daily_mean, daily_median, all_picks = [], [], []
    for d in dates:
        lst = by_date[d]
        if gap_limit is not None:
            lst = [x for x in lst if x["gap"] < gap_limit]  # 限 T 日 gap（选股时已知）
        top = rank_top_nogap(lst)
        if not top:
            continue
        rets = [x["real_exec"] for x in top]
        daily_mean.append(statistics.mean(rets))
        daily_median.append(statistics.median(rets))
        all_picks.extend(top)  # 存 dict 用于 entry_gap 查询
    if not daily_mean:
        return None
    m = statistics.mean(daily_mean)
    med = statistics.mean(daily_median)
    wr = sum(1 for x in all_picks if x["real_exec"] > 0) / len(all_picks)
    std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
    se = std / (len(daily_mean) ** 0.5) if daily_mean else 0
    t = m / se if se > 0 else 0
    eg = [x["entry_gap"] for x in all_picks]
    eg_mean = statistics.mean(eg) if eg else 0
    return {"n_days": len(daily_mean), "n_picks": len(all_picks), "mean": m,
            "median": med, "wr": wr, "net": m - COST, "t": t, "eg_mean": eg_mean}


def main() -> None:
    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    print(f"\n=== combo real-exec 限 T 日 gap（去 gap rank mode=filtered，{len(all_d)} 日）===\n")
    print(f"{'口径':<14}{'days':>6}{'picks':>7}{'net':>10}{'mean':>10}{'median':>10}{'WR':>7}{'t':>7}{'entry_gap':>11}")
    print("-" * 82)
    for label, lim in [("不限(轮11)", None), ("限gap<3%", 0.03), ("限gap<2%", 0.02),
                       ("限gap<1%", 0.01), ("限gap<0.5%", 0.005)]:
        r = stats(all_d, by_date, gap_limit=lim)
        if r:
            print(f"{label:<14}{r['n_days']:>6}{r['n_picks']:>7}{r['net']*100:>+9.3f}%{r['mean']*100:>+9.3f}%{r['median']*100:>+9.3f}%{r['wr']*100:>6.1f}%{r['t']:>6.2f}{r['eg_mean']*100:>+10.3f}%")
    print()
    # 最佳 gap_limit 的 regime 分层 + walk-forward（如果限 gap 提升）
    base = stats(all_d, by_date, gap_limit=None)
    best_lim = None
    best_net = base["net"] if base else 0
    for lim in [0.03, 0.02, 0.01, 0.005]:
        r = stats(all_d, by_date, gap_limit=lim)
        if r and r["net"] > best_net:
            best_net = r["net"]
            best_lim = lim
    if best_lim is not None:
        print(f"最佳 gap_limit = {best_lim}（net {best_net*100:+.3f}% vs 不限 {base['net']*100:+.3f}%，提升 {(best_net-base['net'])*100:+.3f}%）")
    else:
        print(f"限 gap 未提升（不限 net {base['net']*100:+.3f}% 最高）→ entry gap 优化空间不在限 T 日 gap")


if __name__ == "__main__":
    main()
