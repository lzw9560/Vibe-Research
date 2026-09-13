#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S199 R3: §44 验证（§44v2 应用规约 S159）——方向感知 gap 信号 lift。

复用 s44_verifier/stats.py 已有方法：
- day_clustered_t_test（per-date cluster，§44v2 非 pooled）
- permutation_p_value（within-day resampling null）
- bonferroni_bh（K≤8，§44v2 不 over-correct）

§44v2 规约：
① 前置窗口 sanity——多窗口（3/5/10 日 + trade outcome）对比定位优势在哪
② 重方法论只在对窗口+n 够时上（n_days≥60 robust 层才判）
④ 回溯模块主场（此脚本即回溯验证）

两种口径并行：
A. Trade-level：gross_return（交易结算收益）作 outcome，gap-present vs no-gap lift
B. Market-level：bars 前向收益 3/5/10 日，gap-present vs no-gap lift（多窗口 sanity）

用法：python tools/s199_s44_verify.py [signals.json]
默认读 /tmp/s194_signals_fresh.json
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.bars_provider import KlineCacheBarsProvider
from s44_verifier.stats import (
    bonferroni_bh,
    day_clustered_t_test,
    day_paired_lift,
    permutation_p_value,
)
from tools.reconstruct_s194_signals import (
    encode_gap_direction_aware,
    encode_gap_direction_agnostic,
)

WINDOWS = (3, 5, 10)
_MAX_BONFERRONI_K = 8


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _future_return(bars: list[dict], idx: int, n: int) -> float | None:
    """后 n 日收益（close[n] / close[0] - 1）。"""
    j = idx + n
    if j >= len(bars):
        return None
    c0 = _f(bars[idx].get("close"))
    c1 = _f(bars[j].get("close"))
    if c0 <= 0:
        return None
    return (c1 / c0) - 1.0


def _find_idx(bars: list[dict], date: str) -> int | None:
    for i, b in enumerate(bars):
        if b.get("date") == date:
            return i
    return None


def main() -> None:
    signals_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/s194_signals_fresh.json"
    raw = Path(signals_path).read_text()
    data = json.loads(raw[raw.index("["):])  # 容错 baostock 污染

    # 用方向感知编码区分 gap-present vs no-gap
    for d in data:
        d["gap_a"] = encode_gap_direction_aware(d.get("gap_regime", "无"), d.get("gap_direction", "无"))
        d["gap_b"] = encode_gap_direction_agnostic(d.get("gap_regime", "无"))

    n_total = len(data)
    n_gap_a = sum(1 for d in data if d["gap_a"] > 0)
    n_gap_b = sum(1 for d in data if d["gap_b"] > 0)
    n_ret = sum(1 for d in data if d.get("gross_return") is not None)
    n_days = len(set(d["entry_date"] for d in data if d.get("gross_return") is not None))
    print(f"# S199 §44 验证: n_total={n_total} n_gap_a(方向感知)={n_gap_a} "
          f"n_gap_b(方向无关)={n_gap_b} n_ret={n_ret} n_days={n_days}")

    # ════════════════════════════════════════════════════════════════════════
    # A. Trade-level: gross_return 作 outcome
    # ════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("A. Trade-level（gross_return 作 outcome）")
    print(f"{'='*70}")

    # A1. day_clustered_t_test: gap-present 收益 mean > 0?
    gap_returns = [float(d["gross_return"]) for d in data
                   if d.get("gross_return") is not None and d["gap_a"] > 0]
    gap_dates = [d["entry_date"] for d in data
                 if d.get("gross_return") is not None and d["gap_a"] > 0]
    no_gap_returns = [float(d["gross_return"]) for d in data
                      if d.get("gross_return") is not None and d["gap_a"] == 0]
    no_gap_dates = [d["entry_date"] for d in data
                    if d.get("gross_return") is not None and d["gap_a"] == 0]

    print(f"\n  gap-present (A): n={len(gap_returns)} n_days={len(set(gap_dates))}")
    print(f"  no-gap:          n={len(no_gap_returns)} n_days={len(set(no_gap_dates))}")

    # day_clustered_t_test on gap-present returns (is mean > 0?)
    t_gap = day_clustered_t_test(gap_returns, gap_dates)
    t_no_gap = day_clustered_t_test(no_gap_returns, no_gap_dates)
    if t_gap:
        print(f"\n  gap-present day_clustered_t_test: t={t_gap.t_stat:+.3f} "
              f"p={t_gap.p_one_sided:.4f} day_mean={t_gap.day_mean:+.6f} "
              f"n_days={t_gap.n_days}")
    else:
        print(f"\n  gap-present day_clustered_t_test: insufficient (n_days<2)")
    if t_no_gap:
        print(f"  no-gap      day_clustered_t_test: t={t_no_gap.t_stat:+.3f} "
              f"p={t_no_gap.p_one_sided:.4f} day_mean={t_no_gap.day_mean:+.6f} "
              f"n_days={t_no_gap.n_days}")

    # A2. day_paired_lift + permutation: gap-present vs no-gap
    surv_by_day: dict[str, list[float]] = defaultdict(list)
    raw_by_day: dict[str, list[float]] = defaultdict(list)
    for d in data:
        if d.get("gross_return") is None:
            continue
        date = d["entry_date"]
        ret = float(d["gross_return"])
        if d["gap_a"] > 0:
            surv_by_day[date].append(ret)
        else:
            raw_by_day[date].append(ret)

    # Also build universe (all cases) for permutation baseline
    all_by_day: dict[str, list[float]] = defaultdict(list)
    for d in data:
        if d.get("gross_return") is None:
            continue
        all_by_day[d["entry_date"]].append(float(d["gross_return"]))

    paired = day_paired_lift(surv_by_day, raw_by_day)
    if paired and paired.winrate_lift_avg is not None:
        print(f"\n  day_paired_lift (gap vs no-gap): "
              f"winrate_lift={paired.winrate_lift_avg:.4f} "
              f"mean_lift={paired.mean_lift_avg} "
              f"n_days={paired.n_days} "
              f"surv_n={paired.surv_n_pooled} raw_n={paired.raw_n_pooled}")
        perm_p = permutation_p_value(surv_by_day, all_by_day, paired.winrate_lift_avg)
        print(f"  permutation_p_value: p={perm_p:.4f} (within-day resampling null)")
    else:
        print(f"\n  day_paired_lift: no pairable days (surv or raw empty per day)")
        perm_p = 1.0

    # ════════════════════════════════════════════════════════════════════════
    # B. Market-level: bars 前向收益 3/5/10 日（多窗口 sanity, §44v2 规约①）
    # ════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("B. Market-level（bars 前向收益 3/5/10 日，多窗口 sanity）")
    print(f"{'='*70}")

    bp = KlineCacheBarsProvider()
    bars_cache: dict[str, list[dict]] = {}

    def get_bars(code: str) -> list[dict]:
        if code not in bars_cache:
            bars_cache[code] = bp(code)
        return bars_cache[code]

    # Compute forward returns for each case at each window
    # gap_present[window] = list of (return, date) for gap_a > 0 cases
    # no_gap[window] = list of (return, date) for gap_a == 0 cases
    gap_fwd: dict[int, list[tuple[float, str]]] = {n: [] for n in WINDOWS}
    nogap_fwd: dict[int, list[tuple[float, str]]] = {n: [] for n in WINDOWS}

    for d in data:
        bars = get_bars(d["stock"])
        if not bars:
            continue
        idx = _find_idx(bars, d["entry_date"])
        if idx is None:
            continue
        for n in WINDOWS:
            ret = _future_return(bars, idx, n)
            if ret is None:
                continue
            entry = (ret, d["entry_date"])
            if d["gap_a"] > 0:
                gap_fwd[n].append(entry)
            else:
                nogap_fwd[n].append(entry)

    print(f"\n  | 窗口 | gap-present n | gap n_days | no-gap n | no-gap n_days |")
    print(f"  |---|---|---|---|---|")
    for n in WINDOWS:
        g = gap_fwd[n]
        ng = nogap_fwd[n]
        print(f"  | {n}日 | {len(g)} | {len(set(d for _,d in g))} | {len(ng)} | {len(set(d for _,d in ng))} |")

    # B1. day_clustered_t_test per window
    print(f"\n  day_clustered_t_test per window (gap-present mean > 0?):")
    print(f"  | 窗口 | gap t | gap p | gap day_mean | gap n_days | no_gap t | no_gap p | no_gap day_mean |")
    print(f"  |---|---|---|---|---|---|---|---|")
    p_list, p_keys = [], []
    for n in WINDOWS:
        g_rets = [r for r, _ in gap_fwd[n]]
        g_dts = [d for _, d in gap_fwd[n]]
        ng_rets = [r for r, _ in nogap_fwd[n]]
        ng_dts = [d for _, d in nogap_fwd[n]]
        tg = day_clustered_t_test(g_rets, g_dts)
        tng = day_clustered_t_test(ng_rets, ng_dts)
        tg_s = f"{tg.t_stat:+.3f}" if tg else "-"
        tg_p = f"{tg.p_one_sided:.4f}" if tg else "-"
        tg_m = f"{tg.day_mean:+.6f}" if tg else "-"
        tg_n = str(tg.n_days) if tg else "-"
        tng_s = f"{tng.t_stat:+.3f}" if tng else "-"
        tng_p = f"{tng.p_one_sided:.4f}" if tng else "-"
        tng_m = f"{tng.day_mean:+.6f}" if tng else "-"
        print(f"  | {n}日 | {tg_s} | {tg_p} | {tg_m} | {tg_n} | {tng_s} | {tng_p} | {tng_m} |")
        if tg:
            p_list.append(tg.p_one_sided)
            p_keys.append(f"gap_{n}d")

    # B2. day_paired_lift + permutation per window
    print(f"\n  day_paired_lift + permutation per window (gap vs no-gap):")
    print(f"  | 窗口 | lift | mean_lift | perm_p | n_days | surv_n | raw_n |")
    print(f"  |---|---|---|---|---|---|---|")
    for n in WINDOWS:
        g = gap_fwd[n]
        ng = nogap_fwd[n]
        surv_day: dict[str, list[float]] = defaultdict(list)
        raw_day: dict[str, list[float]] = defaultdict(list)
        all_day: dict[str, list[float]] = defaultdict(list)
        for ret, date in g:
            surv_day[date].append(ret)
            all_day[date].append(ret)
        for ret, date in ng:
            raw_day[date].append(ret)
            all_day[date].append(ret)
        pl = day_paired_lift(surv_day, raw_day)
        if pl and pl.winrate_lift_avg is not None:
            pp = permutation_p_value(surv_day, all_day, pl.winrate_lift_avg)
            print(f"  | {n}日 | {pl.winrate_lift_avg:.4f} | {pl.mean_lift_avg} | "
                  f"{pp:.4f} | {pl.n_days} | {pl.surv_n_pooled} | {pl.raw_n_pooled} |")
            p_list.append(pp)
            p_keys.append(f"perm_{n}d")
        else:
            print(f"  | {n}日 | n/a | n/a | n/a | - | - | - |")

    # B3. Bonferroni-BH correction (K≤8, §44v2)
    print(f"\n  Bonferroni-BH correction (K={len(p_list)}, cap≤{_MAX_BONFERRONI_K}):")
    if p_list:
        adj_bonf = bonferroni_bh(p_list, method="bonferroni")
        adj_bh = bonferroni_bh(p_list, method="BH")
        print(f"  | test | raw_p | Bonferroni | BH |")
        print(f"  |---|---|---|---|")
        for i, key in enumerate(p_keys):
            sig_b = "✗" if adj_bonf[i] >= 0.05 else "✓"
            sig_bh = "✗" if adj_bh[i] >= 0.05 else "✓"
            print(f"  | {key} | {p_list[i]:.4f} | {adj_bonf[i]:.4f} {sig_b} | {adj_bh[i]:.4f} {sig_bh} |")

    # ════════════════════════════════════════════════════════════════════════
    # C. Version A vs B comparison (direction-aware vs direction-agnostic)
    # ════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("C. A vs B 对照（方向感知 vs 方向无关，多窗口）")
    print(f"{'='*70}")
    print(f"\n  | 窗口 | A lift | A perm_p | B lift | B perm_p | A-B lift |")
    print(f"  |---|---|---|---|---|---|")
    for n in WINDOWS:
        # Version A (direction-aware)
        g_a = [(r, d) for r, d in gap_fwd[n]]
        # Version B: also include downward gaps
        gap_b_fwd: list[tuple[float, str]] = []
        for d in data:
            bars = get_bars(d["stock"])
            if not bars:
                continue
            idx = _find_idx(bars, d["entry_date"])
            if idx is None:
                continue
            ret = _future_return(bars, idx, n)
            if ret is None:
                continue
            if d["gap_b"] > 0:
                gap_b_fwd.append((ret, d["entry_date"]))
        # A lift
        surv_a: dict[str, list[float]] = defaultdict(list)
        for ret, date in g_a:
            surv_a[date].append(ret)
        raw_a: dict[str, list[float]] = defaultdict(list)
        for ret, date in nogap_fwd[n]:
            raw_a[date].append(ret)
        all_a: dict[str, list[float]] = defaultdict(list)
        for ret, date in g_a:
            all_a[date].append(ret)
        for ret, date in nogap_fwd[n]:
            all_a[date].append(ret)
        pl_a = day_paired_lift(surv_a, raw_a)
        lift_a = pl_a.winrate_lift_avg if pl_a and pl_a.winrate_lift_avg else None
        pp_a = permutation_p_value(surv_a, all_a, lift_a) if lift_a else 1.0
        # B lift
        surv_b: dict[str, list[float]] = defaultdict(list)
        for ret, date in gap_b_fwd:
            surv_b[date].append(ret)
        raw_b = raw_a  # same no-gap set
        all_b = all_a  # same universe
        pl_b = day_paired_lift(surv_b, raw_b)
        lift_b = pl_b.winrate_lift_avg if pl_b and pl_b.winrate_lift_avg else None
        pp_b = permutation_p_value(surv_b, all_b, lift_b) if lift_b else 1.0
        diff = (lift_a - lift_b) if (lift_a and lift_b) else None
        la = f"{lift_a:.4f}" if lift_a else "n/a"
        lb = f"{lift_b:.4f}" if lift_b else "n/a"
        diff_s = f"{diff:+.4f}" if diff is not None else "n/a"
        print(f"  | {n}日 | {la} | {pp_a:.4f} | {lb} | {pp_b:.4f} | {diff_s} |")

    # ════════════════════════════════════════════════════════════════════════
    # D. 结论（诚实，不外推）
    # ════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("D. 结论（§44v2 诚实判定，不外推）")
    print(f"{'='*70}")
    print(f"""
  测了什么：
  1. 融合分消融 delta_ic A vs B（方向感知 vs 方向无关）—— gap 信号对融合分预测力的贡献增量
  2. §44 day_clustered_t_test + permutation_p_value（trade-level + market-level 多窗口）
  3. Bonferroni-BH 多重比较校正

  没测什么：
  - 未测 gap 信号单独（非融合分）的选股力 IC
  - 未测 gap 信号在非 breakout arm（如 floor）的预测力
  - 未测盘中信号（OFI/fund_flow）与 gap 的交互效应
  - 未测 regime-stratified（牛月/熊月拆分）的 gap 信号力

  结论方向（跑完数据后填入上方结果）：
  - 若 A delta_ic 正 + p<0.05 → gap 有 edge（翻 S194 no_contribution）
  - 若 A delta_ic ~0 + p≥0.05 → 确认 no_contribution（gap 不进融合权重）
  - A vs B 无显著差异 → 方向感知编码未改变 gap 信号预测力
  """)


if __name__ == "__main__":
    main()
