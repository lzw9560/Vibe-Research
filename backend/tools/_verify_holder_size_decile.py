# -*- coding: utf-8 -*-
"""验证股东户数减少 edge 是否 73% 是 size premium 误标。
对 holder picks 按 60bar 中位成交额分 10 decile，看 edge 是否集中在小盘 decile。
若小盘 decile edge 高、大盘 decile edge 低/负 → size premium 误标（标的习惯专家 claim 成立）。
若各 decile edge 均匀 → 真 accumulation alpha。
"""

from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from math import sqrt
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir  # 数据路径统一走 vr_paths（S037 收口）
from tools._factor_helpers import limit_for_code, is_yizi_t1
from tools.explore_main_force_holder_test import (
    load_holder,
    load_kline,
    build_picks,
    raw_ev,
    HOLD_DAYS,
    COST,
    THRESHOLDS,
)

KLINE_DB = resolve_data_dir() / "baostock_kline_cache.db"


def median_amount_60bar(dmap, notice_date, window=60):
    """stock 在 notice_date 前 60 个有 bar 的交易日的中位 amount（size proxy）."""
    dates_sorted = sorted(d for d in dmap if d <= notice_date)
    if len(dates_sorted) < window:
        window = len(dates_sorted)
    if window < 5:
        return None
    recent = dates_sorted[-window:]
    amts = [dmap[d].get("amount", 0) for d in recent if dmap[d].get("amount")]
    if not amts:
        return None
    return statistics.median(amts)


def main():
    print("=" * 70)
    print("股东户数减少 edge · size-decile 分层验证（73% size premium claim）")
    print("=" * 70)
    holder = load_holder()
    kline_map, all_dates = load_kline()
    calendar = sorted(all_dates)
    # 用最宽松阈值 <-3% 拿最多 picks
    thr = -3.0
    picks = build_picks(holder, kline_map, calendar, thr, HOLD_DAYS)
    print(f"\n[数据] threshold change_ratio<{thr}%: n_picks={len(picks)}")

    # 给每个 pick 加 median_amount_60bar
    enriched = []
    for p in picks:
        amt = median_amount_60bar(kline_map.get(p["code"], {}), p["notice_date"])
        if amt is not None and amt > 0:
            p["size_amt"] = amt
            p["ret"] = raw_ev(p)
            enriched.append(p)
    print(f"有 size 信息的 picks: {len(enriched)}")

    if len(enriched) < 100:
        print("样本不足")
        return

    # 分 10 decile by size_amt
    amts = sorted(p["size_amt"] for p in enriched)
    n = len(amts)
    decile_cutoffs = [amts[min(int(n * d / 10), n - 1)] for d in range(11)]
    print(f"\nsize(amount) decile cutoffs (亿元): {[round(c / 1e8, 3) for c in decile_cutoffs]}")

    print(f"\n{'decile':>6} {'size范围(亿)':>22} {'n':>7} {'mean%':>9} {'net%':>9} {'median%':>9} {'WR%':>6}")
    print("-" * 70)
    decile_stats = []
    for d in range(10):
        lo = decile_cutoffs[d]
        hi = decile_cutoffs[d + 1]
        sub = [p for p in enriched if (lo <= p["size_amt"] < hi) or (d == 9 and p["size_amt"] >= lo)]
        if not sub:
            continue
        rets = [p["ret"] for p in sub]
        mean = statistics.mean(rets)
        med = statistics.median(rets)
        wr = sum(1 for r in rets if r > 0) / len(rets) * 100
        net = mean - COST
        lo_yi = lo / 1e8
        hi_yi = hi / 1e8
        decile_stats.append((d + 1, lo_yi, hi_yi, len(sub), mean, net, med, wr))
        print(
            f"{d + 1:>6} {f'{lo_yi:.3f}~{hi_yi:.3f}':>22} {len(sub):>7} "
            f"{mean:>+8.4f} {net:>+8.4f} {med:>+8.4f} {wr:>5.1f}"
        )

    # 判定
    print("\n" + "=" * 70)
    print("[判定]")
    if not decile_stats:
        print("无 decile 数据")
        return
    small = decile_stats[0]
    large = decile_stats[-1]
    overall_mean = statistics.mean(p["ret"] for p in enriched)
    small_mean = small[4]
    large_mean = large[4]
    size_share = small_mean / overall_mean * 100 if overall_mean != 0 else 0
    print(f"overall mean: {overall_mean:+.4f}%")
    print(f"最小盘 decile(1): mean={small_mean:+.4f}% (占总 mean 的 {size_share:.0f}%)")
    print(f"最大盘 decile(10): mean={large_mean:+.4f}%")
    spread = small_mean - large_mean
    print(f"small-large spread: {spread:+.4f}%")
    if spread > 2.0 and large_mean < 0.5:
        print(f"→ CONFIRMED 标的习惯专家 claim: edge 集中小盘, 大盘弱/负 = size premium 误标")
    elif spread > 1.0:
        print(f"→ PARTIAL: edge 部分集中在小盘, 但大盘也正 = 混合 (size premium + 部分 alpha)")
    else:
        print(f"→ REJECTED: edge 各 decile 均匀 = 非 size premium, 可能真 alpha")

    # 也按 size decile 算 BHAR vs decile-内部均值（粗略 size-matched）
    print(f"\n[粗略 size-matched BHAR] 每个 pick 减去其 decile 内均值")
    decile_means = {d[0]: d[4] for d in decile_stats}
    bhar_vals = []
    for p in enriched:
        # 找该 pick 属于哪个 decile
        for d in range(10):
            lo = decile_cutoffs[d]
            hi = decile_cutoffs[d + 1]
            if (lo <= p["size_amt"] < hi) or (d == 9 and p["size_amt"] >= lo):
                bhar_vals.append(p["ret"] - decile_means[d + 1])
                break
    if bhar_vals:
        sm_mean = statistics.mean(bhar_vals)
        sm_med = statistics.median(bhar_vals)
        sm_wr = sum(1 for r in bhar_vals if r > 0) / len(bhar_vals) * 100
        print(
            f"  size-decile-matched BHAR: mean={sm_mean:+.4f}% net={sm_mean - COST:+.4f}% "
            f"median={sm_med:+.4f}% WR={sm_wr:.1f}% n={len(bhar_vals)}"
        )
        print(f"  (vs 标的习惯专家 claim: +0.36% net, WR 43.4%)")


if __name__ == "__main__":
    main()
