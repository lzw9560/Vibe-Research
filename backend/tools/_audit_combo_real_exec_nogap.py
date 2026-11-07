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
    n = len(daily_mean)
    std = statistics.pstdev(daily_mean) if n > 1 else 0
    se = std / (n**0.5) if daily_mean else 0
    t = m / se if se > 0 else 0
    # P0 修高危①(2026-11-06 backtest-guard)：重叠 5 日收益 t-stat 膨胀(ρ≈0.8 有效 n << 名义 n)
    # Newey-West 近似: n_eff = n / (1 + 2*sum(ρ_k)), L=5 覆盖 5 日持有重叠 4 天
    t_nw, n_eff = t, float(n)
    if n > 10 and std > 0:
        var = std * std
        rho_sum = 0.0
        for k in range(1, 6):  # L=5
            if n - k <= 0:
                break
            cov_k = sum((daily_mean[i] - m) * (daily_mean[i - k] - m) for i in range(k, n)) / n
            rho_k = cov_k / var if var > 0 else 0
            rho_sum += rho_k
        denom = 1 + 2 * rho_sum
        n_eff = n / denom if denom > 0 else float(n)
        se_nw = std / (n_eff**0.5) if n_eff > 0 else se
        t_nw = m / se_nw if se_nw > 0 else 0
    # P1 修高危⑤(2026-11-06 backtest-guard)：滑点敏感性——net @ 多 COST 看实盘容量
    # combo 小盘 top-20 滑点敏感，固定 0.4% 可能低估。看 net @ 0.6/0.8/1.0% 存活否
    net_sens = {f"COST={c * 100:.1f}%": (m - c) * 100 for c in (0.004, 0.006, 0.008, 0.010)}
    return {
        "n_days": n,
        "n_picks": len(all_picks),
        "mean": m,
        "median": med,
        "wr": wr,
        "net": m - COST,
        "t": t,
        "t_nw": t_nw,
        "n_eff": n_eff,
        "net_sens": net_sens,
    }


def main() -> None:
    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    print(f"\n=== combo real-exec 去高 gap 版（rank 动量+小盘不用 gap，{len(all_d)} 日）===\n")
    for label, field in [("close-to-close", "close_close"), ("real-execution", "real_exec")]:
        r = stats(all_d, by_date, field)
        if r:
            sens = r.get("net_sens", {})
            sens_str = " ".join(f"{k}={v:+.2f}%" for k, v in sens.items())
            print(
                f"【{label}】days={r['n_days']} picks={r['n_picks']} mean={r['mean'] * 100:+.3f}% median={r['median'] * 100:+.3f}% WR={r['wr'] * 100:.1f}% net={r['net'] * 100:+.3f}% t={r['t']:.2f} t_nw={r.get('t_nw', 0):.2f}(n_eff={r.get('n_eff', 0):.0f}) | 滑点敏感: {sens_str}"
            )
    re = stats(all_d, by_date, "real_exec")
    if re:
        if re["net"] > 0.003:
            verdict = "✅ >+0.3% 存活"
        elif re["net"] <= 0.0015:
            verdict = "⚠️ ≤+0.15% 幻觉"
        else:
            verdict = "🟡 0.15-0.3% 灰区"
        print(f"\n判定: net real-exec {re['net'] * 100:+.3f}% → {verdict}")
        print(
            f"对比含 gap 版(轮11): real-exec net +0.311% / median -0.141% → 去 gap 版 net {re['net'] * 100:+.3f}% / median {re['median'] * 100:+.3f}%"
        )
        delta = re["net"] - 0.00311
        print(
            f"  去 gap vs 含 gap: net {'提升' if delta > 0 else '降'} {delta * 100:+.3f}%（去 entry gap 右尾是否提升 edge）"
        )


if __name__ == "__main__":
    main()
