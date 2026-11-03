# -*- coding: utf-8 -*-
"""combo real-execution 去高 gap 版（2026-11-04，轮11 后续）。

rank 只用动量+小盘（不用 gap），测去 entry gap 右尾能否提升 real-exec edge。
memory 轮5: 去 gap 版 close-to-close OOS t=4.05 验过。本脚本测 real-exec 口径。
对比含 gap 版（轮11 real-exec net +0.311%）。
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _audit_combo_real_exec import build_by_date, TOP_N, COST  # noqa: E402


def rank_top_nogap(lst: list, n: int = TOP_N) -> list | None:
    """rank 动量+小盘（不用 gap）top-N。"""
    if len(lst) < n * 10:
        return None
    nn = len(lst)
    st = sorted(range(nn), key=lambda k: lst[k]["tr"])
    sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    score = lambda k: rt[k] + ra[k]  # 不用 gap
    top_idx = sorted(range(nn), key=score, reverse=True)[:n]
    return [lst[k] for k in top_idx]


def stats(dates: list, by_date: dict, field: str) -> dict | None:
    daily_mean, daily_median, all_picks = [], [], []
    for d in dates:
        top = rank_top_nogap(by_date[d])
        if not top:
            continue
        rets = [x[field] for x in top]
        daily_mean.append(statistics.mean(rets))
        daily_median.append(statistics.median(rets))
        all_picks.extend(rets)
    if not daily_mean:
        return None
    m = statistics.mean(daily_mean)
    med = statistics.mean(daily_median)
    wr = sum(1 for x in all_picks if x > 0) / len(all_picks)
    std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
    se = std / (len(daily_mean) ** 0.5) if daily_mean else 0
    t = m / se if se > 0 else 0
    return {"n_days": len(daily_mean), "n_picks": len(all_picks),
            "mean": m, "median": med, "wr": wr, "net": m - COST, "t": t}


def main() -> None:
    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    print(f"\n=== combo real-exec 去高 gap 版（rank 动量+小盘不用 gap，{len(all_d)} 日）===\n")
    for label, field in [("close-to-close", "close_close"), ("real-execution", "real_exec")]:
        r = stats(all_d, by_date, field)
        if r:
            print(f"【{label}】days={r['n_days']} picks={r['n_picks']} mean={r['mean']*100:+.3f}% median={r['median']*100:+.3f}% WR={r['wr']*100:.1f}% net={r['net']*100:+.3f}% t={r['t']:.2f}")
    re = stats(all_d, by_date, "real_exec")
    if re:
        if re["net"] > 0.003:
            verdict = "✅ >+0.3% 存活"
        elif re["net"] <= 0.0015:
            verdict = "⚠️ ≤+0.15% 幻觉"
        else:
            verdict = "🟡 0.15-0.3% 灰区"
        print(f"\n判定: net real-exec {re['net']*100:+.3f}% → {verdict}")
        print(f"对比含 gap 版(轮11): real-exec net +0.311% / median -0.141% → 去 gap 版 net {re['net']*100:+.3f}% / median {re['median']*100:+.3f}%")
        delta = re["net"] - 0.00311
        print(f"  去 gap vs 含 gap: net {'提升' if delta>0 else '降'} {delta*100:+.3f}%（去 entry gap 右尾是否提升 edge）")


if __name__ == "__main__":
    main()
