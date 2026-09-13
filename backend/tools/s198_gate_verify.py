#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S198 gate 验证：衰竭翻转 needs-spec-first（S201c done 后重方法论验证）。

S193 R5 v3 用错测试（单样本全局基线非同日配对）+ permutation 未做 + regime-mix 未拆。
本脚本跑全 5 项 gate 验证（同 cache 174 天 ≥60 上重方法论）：
  1. day_paired_lift（衰竭 survivors vs 普通 raw 同日配对）
  2. permutation_p_value（within-day null）
  3. walk_forward_oos（时序稳定性）
  4. regime-stratified（bull/bear/range 拆分）
  5. 10 日窗口
+ R5 v3 重跑（candidate 模式，前视修复后）

flip 判定：day_paired survive + permutation p<0.05 + per-regime bull AND bear 均成立 → 翻
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from engine.bars_provider import _load_cache
from engine.gap_classifier import _classify_gap_from_bars
from s44_verifier.stats import (
    day_paired_lift, permutation_p_value, walk_forward_oos, day_clustered_t_test
)

WINDOWS = (3, 5, 10)
N_PERM = 500
PERM_SEED = 42


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def future_return(bars, idx, n):
    j = idx + n
    if j >= len(bars):
        return None
    c0 = _f(bars[idx].get("close"))
    c1 = _f(bars[j].get("close"))
    return (c1 / c0 - 1) if c0 > 0 else None


def continuation_hit(direction, ret):
    """后 N 日延续缺口 direction（向上→ret>0，向下→ret<0）。"""
    if ret is None:
        return None
    return (ret > 0) if direction == "向上" else (ret < 0)


def main():
    cache = _load_cache()
    print(f"# cache: {len(cache)} 只股票", file=sys.stderr)

    # 收集衰竭 + 普通 case（candidate 模式，S201c done 后无前视）
    # per-day：衰竭 continuation returns + 普通 continuation returns
    surv_by_day: dict[str, list[float]] = defaultdict(list)  # 衰竭 continuation（ret 延续 direction）
    raw_by_day: dict[str, list[float]] = defaultdict(list)   # 普通 continuation
    # 也收集 per-type continuation for R5 重跑
    type_cont: dict[str, dict[int, dict]] = defaultdict(lambda: {n: {"hit": 0, "total": 0} for n in WINDOWS})
    # regime-stratified 需要 dates——先用 per-day 衰竭 + 普通 continuation
    # 10 日窗口
    surv_by_day_10: dict[str, list[float]] = defaultdict(list)
    raw_by_day_10: dict[str, list[float]] = defaultdict(list)

    n_gap = 0
    for code, bars in cache.items():
        if len(bars) < max(WINDOWS) + 2:
            continue
        for idx in range(1, len(bars) - max(WINDOWS)):
            gap = _classify_gap_from_bars(bars, idx, mode="candidate")
            gtype = gap.get("type")
            if gtype == "无缺口" or gtype not in ("衰竭", "普通", "突破", "持续"):
                continue
            n_gap += 1
            direction = gap.get("direction")
            bar_date = str(bars[idx].get("date", ""))[:10]
            for n in WINDOWS:
                ret = future_return(bars, idx, n)
                hit = continuation_hit(direction, ret)
                if hit is None:
                    continue
                # continuation metric: 1.0 if 延续, 0.0 if 反转
                cont_val = 1.0 if hit else 0.0
                type_cont[gtype][n]["total"] += 1
                if hit:
                    type_cont[gtype][n]["hit"] += 1
                # 衰竭 vs 普通 同日配对（5 日窗口主测 + 10 日辅助）
                if gtype == "衰竭" and n == 5:
                    surv_by_day[bar_date].append(cont_val)
                elif gtype == "普通" and n == 5:
                    raw_by_day[bar_date].append(cont_val)
                if gtype == "衰竭" and n == 10:
                    surv_by_day_10[bar_date].append(cont_val)
                elif gtype == "普通" and n == 10:
                    raw_by_day_10[bar_date].append(cont_val)

    print(f"# gap case: {n_gap}（candidate 模式）", file=sys.stderr)

    # ── 1. day_paired_lift（5 日，衰竭 vs 普通 同日配对）──
    print("\n## 1. day_paired_lift（5 日，衰竭 survivors vs 普通 raw 同日配对）")
    dp = day_paired_lift(dict(surv_by_day), dict(raw_by_day))
    print(f"  n_days={dp.n_days}, winrate_lift_avg={dp.winrate_lift_avg}, "
          f"mean_lift_avg={dp.mean_lift_avg}")
    print(f"  surv_n_pooled={dp.surv_n_pooled}, raw_n_pooled={dp.raw_n_pooled}")
    dp_survive = (dp.winrate_lift_avg is not None and dp.winrate_lift_avg > 1.0)
    print(f"  gate: {'PASS' if dp_survive else 'FAIL'}（winrate_lift>1.0）")

    # ── 2. permutation_p_value（within-day null）──
    print("\n## 2. permutation_p_value（within-day null, N=500 seed=42）")
    observed_lift = dp.winrate_lift_avg
    p_perm = permutation_p_value(dict(surv_by_day), dict(raw_by_day), observed_lift,
                                  n_perm=N_PERM, seed=PERM_SEED)
    print(f"  observed_lift={observed_lift}, p_permutation={p_perm}")
    perm_survive = p_perm < 0.05
    print(f"  gate: {'PASS' if perm_survive else 'FAIL'}（p<0.05）")

    # ── 3. walk_forward_oos（时序稳定性）──
    print("\n## 3. walk_forward_oos（train=100 test=20 step=20）")
    wf = walk_forward_oos(dict(surv_by_day), dict(raw_by_day))
    print(f"  n_windows={wf.n_windows}, status={wf.status}")
    if wf.mean_test_lift is not None:
        print(f"  mean_test_lift={wf.mean_test_lift:.4f}")
    wf_stable = wf.status == "oos_stable"
    print(f"  gate: {'PASS (加分项)' if wf_stable else 'FAIL (加分项非 gate)'}")

    # ── 4. regime-stratified（bull/bear/range）──
    # 复用 gap_regime_stratified 的 compute_regime_labels
    print("\n## 4. regime-stratified（bull/bear/range 拆分）")
    try:
        sys.path.insert(0, str(ROOT / "backend" / "tools"))
        from gap_regime_stratified import compute_regime_labels
        regime_map = compute_regime_labels()
        if regime_map:
            surv_by_regime: dict[str, dict[str, list[float]]] = {"bull": {}, "bear": {}, "range": {}}
            for d, vals in surv_by_day.items():
                tag = regime_map.get(d)
                if tag:
                    surv_by_regime[tag].setdefault(d, []).extend(vals)
            print(f"  衰竭 per-regime day 分布:")
            regime_survive = {}
            for tag in ("bull", "bear", "range"):
                by_day = surv_by_regime[tag]
                n_days = len(by_day)
                total = sum(len(v) for v in by_day.values())
                if n_days > 1:
                    day_means = [sum(v)/len(v) for v in by_day.values()]
                    import statistics
                    mean_cont = statistics.mean(day_means)
                    print(f"    {tag}: {n_days} 日, {total} case, continuation rate={mean_cont:.3f}")
                    regime_survive[tag] = mean_cont > 0.5  # continuation > 50%
                else:
                    print(f"    {tag}: {n_days} 日 (insufficient), {total} case")
                    regime_survive[tag] = None
            bull_ok = regime_survive.get("bull")
            bear_ok = regime_survive.get("bear")
            regime_pass = (bull_ok is True and bear_ok is True)
            print(f"  gate: {'PASS' if regime_pass else 'FAIL'}（bull AND bear 均 continuation>50%）")
        else:
            print("  regime_map 空（index_ma20_regime.json 缺）")
            regime_pass = False
    except Exception as e:
        print(f"  regime-stratified 失败: {e}")
        regime_pass = False

    # ── 5. 10 日窗口（非窗口依赖）──
    print("\n## 5. 10 日窗口（非窗口依赖检查）")
    dp10 = day_paired_lift(dict(surv_by_day_10), dict(raw_by_day_10))
    print(f"  n_days={dp10.n_days}, winrate_lift_avg={dp10.winrate_lift_avg}")
    win10_pass = (dp10.winrate_lift_avg is not None and dp10.winrate_lift_avg > 1.0)
    print(f"  gate: {'PASS' if win10_pass else 'FAIL'}（10 日 winrate_lift>1.0）")

    # ── 6. R5 v3 重跑（candidate 模式，前视修复后）──
    print("\n## 6. R5 v3 重跑（candidate 模式，S201c 前视修复后）")
    print("  per-type continuation rate（candidate 无前视）：")
    for gtype in ("衰竭", "突破", "持续", "普通"):
        for n in (3, 5, 10):
            s = type_cont[gtype][n]
            if s["total"] == 0:
                continue
            rate = s["hit"] / s["total"]
            print(f"    {gtype} {n}日: {s['hit']}/{s['total']} = {rate:.3f}")

    # ── 7. flip 判定 ──
    print("\n## 7. flip 判定")
    print(f"  day_paired: {'PASS' if dp_survive else 'FAIL'}")
    print(f"  permutation: {'PASS' if perm_survive else 'FAIL'} (p={p_perm})")
    print(f"  regime bull+bear: {'PASS' if regime_pass else 'FAIL'}")
    print(f"  10 日: {'PASS' if win10_pass else 'FAIL'}")
    all_pass = dp_survive and perm_survive and regime_pass
    if all_pass:
        print("\n  *** FLIP: 翻衰竭 label（反转→动能延续）***")
        print("  gap_classifier.py:185 regime='反转' → '动能延续'")
    else:
        print("\n  *** NO FLIP: 保留反转 label + gap_scan caveat ***")
        failed = []
        if not dp_survive: failed.append("day_paired")
        if not perm_survive: failed.append(f"permutation(p={p_perm})")
        if not regime_pass: failed.append("regime bull+bear")
        print(f"  failed gates: {', '.join(failed)}")


if __name__ == "__main__":
    main()
