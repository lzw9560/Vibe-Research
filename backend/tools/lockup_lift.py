#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""§44 v2 因子验证：限售解禁（lockup_expiry）负向 risk filter。

假设：解禁股 D+1 open 后系统性 underperform 同期 universe（负向 edge）。
验证：day_paired lift（解禁 vs universe，非池化）+ within-day permutation null + Bonferroni。

口径：
- D = 解禁日（FREE_DATE 对齐到最近交易日）
- 收益 = (D+2 close - D+1 open) / D+1 open * 100（策略口径标的收益，与 first_board_layer_lift 一致）
- 路径 winrate = simulate_holding(bars, D, stop=-3, take=+8, max_hold=3) → 解禁股附加指标
- day_paired_lift = 逐日（解禁 winrate / universe winrate）平均（非池化）
- 分层：ratio >5% / 1-5% / <1%（FREE_RATIO = 解禁股/流通股 比）

cost=0（risk filter 规避非入场，不产生交易成本）。
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tools.first_board_layer_lift import day_paired_lift, four_state, _winrate  # noqa: E402

KLINE_CACHE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
LOCKUP_CACHE = ROOT / ".vibe-research" / "lockup_events_cache.json"

STOP_PCT = -3.0
TAKE_PCT = 8.0
MAX_HOLD = 3
COST_PCT = 0.0
N_PERM = 2000
PERM_SEED = 42
ALPHA_ADJ = 0.05 / 4  # Bonferroni K=4
RATIO_HIGH = 0.05
RATIO_MID = 0.01


def _f(v) -> float | None:
    """Fast float conversion."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s or s in ("-", "--", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def simulate_path(bars: list[dict], idx: int, entry: float) -> dict | None:
    """Path sim from known index. Entry=idx+1 open, check from idx+2.
    Uses fast_bars keys: d/o/c/h/l."""
    if idx + 2 >= len(bars) or not entry or entry <= 0:
        return None
    for j in range(idx + 2, min(idx + 2 + MAX_HOLD, len(bars))):
        low = bars[j].get("l")
        high = bars[j].get("h")
        if low is not None and low <= entry * (1 + STOP_PCT / 100):
            return {"won": False, "return_pct": STOP_PCT}
        if high is not None and high >= entry * (1 + TAKE_PCT / 100):
            return {"won": True, "return_pct": TAKE_PCT}
    exit_idx = min(idx + 1 + MAX_HOLD, len(bars) - 1)
    exit_price = bars[exit_idx].get("c")
    if exit_price is None or exit_price <= 0:
        return None
    ret = round((exit_price - entry) / entry * 100, 4)
    return {"won": ret > 0, "return_pct": ret}


def day_cluster_permutation_fast(surv_by_day, raw_stats_by_day,
                                 n_perm=N_PERM, seed=PERM_SEED):
    """Within-day survivor resampling null (optimized).

    Pre-computes raw winrate per day once; per-perm only computes sampled subset winrate.
    Returns list of null winrate_lift_avg values.
    """
    rng = random.Random(seed)
    nulls = []
    surv_dates = list(surv_by_day.keys())
    for _ in range(n_perm):
        day_lifts = []
        for date in surv_dates:
            surv_rets = surv_by_day[date]
            rs = raw_stats_by_day.get(date)
            if not surv_rets or rs is None:
                continue
            raw_rets = rs["list"]
            if len(raw_rets) < len(surv_rets):
                continue
            r_wr = rs["winrate"]
            if r_wr <= 0:
                continue
            sampled = rng.sample(raw_rets, len(surv_rets))
            s_wr = sum(1 for x in sampled if x > 0) / len(sampled)
            day_lifts.append(s_wr / r_wr)
        if day_lifts:
            nulls.append(round(statistics.mean(day_lifts), 4))
    return nulls


def main() -> int:
    print("=== §44 v2 限售解禁因子验证 ===", flush=True)

    # ── Load data ──
    print("loading kline cache...", flush=True)
    cache = json.loads(KLINE_CACHE.read_bytes())
    events = json.loads(LOCKUP_CACHE.read_bytes())
    print(f"kline cache: {len(cache)} stocks", flush=True)
    print(f"lockup events: {len(events)}", flush=True)

    # Pre-convert bars: extract date, open, close, high, low as floats for speed
    print("pre-converting bars...", flush=True)
    fast_bars: dict[str, list[dict]] = {}
    all_dates_set: set[str] = set()
    for code, bars in cache.items():
        fb = []
        for b in bars:
            d = b.get("date", "")
            all_dates_set.add(d)
            fb.append({
                "d": d,
                "o": _f(b.get("open")),
                "c": _f(b.get("close")),
                "h": _f(b.get("high")),
                "l": _f(b.get("low")),
            })
        fast_bars[code] = fb
    all_dates = sorted(all_dates_set)
    print(f"trading dates: {len(all_dates)} ({all_dates[0]}→{all_dates[-1]})", flush=True)

    # date->index map per stock
    date_idx: dict[str, dict[str, int]] = {}
    for code, bars in fast_bars.items():
        date_idx[code] = {b["d"]: i for i, b in enumerate(bars)}

    # ── Build universe: simple target_return for ALL stocks on ALL days ──
    # target_return = (D+2 close - D+1 open) / D+1 open * 100
    # This is O(n_stocks × n_bars) but each op is just 2 float lookups
    print("computing universe returns (simple D+1 open → D+2 close)...", flush=True)
    raw_by_day: dict[str, list[float]] = defaultdict(list)
    n_universe = 0
    for code, bars in fast_bars.items():
        for i in range(len(bars) - 2):
            d1_open = bars[i + 1].get("o")
            d2_close = bars[i + 2].get("c")
            if d1_open is None or d1_open <= 0 or d2_close is None:
                continue
            ret = round((d2_close - d1_open) / d1_open * 100, 4)
            raw_by_day[bars[i]["d"]].append(ret)
            n_universe += 1
    print(f"universe: {n_universe} obs, {len(raw_by_day)} days", flush=True)

    # Pre-compute raw winrate per day (constant across permutations)
    raw_stats_by_day: dict[str, dict] = {}
    for date, rets in raw_by_day.items():
        if rets:
            raw_stats_by_day[date] = {
                "winrate": _winrate(rets),
                "mean": statistics.mean(rets),
                "list": rets,
            }

    # ── Map lockup events to trading days + compute returns ──
    # For unlock stocks: use BOTH simple return and path-winrate
    def align_to_trading(event_date: str) -> str | None:
        if event_date in all_dates_set:
            return event_date
        for d in all_dates:
            if d >= event_date:
                return d
        return None

    unlock_by_day: dict[str, list[float]] = defaultdict(list)
    unlock_by_day_high: dict[str, list[float]] = defaultdict(list)
    unlock_by_day_mid: dict[str, list[float]] = defaultdict(list)
    unlock_by_day_low: dict[str, list[float]] = defaultdict(list)
    unlock_path_by_day: dict[str, list[float]] = defaultdict(list)  # path-winrate
    n_matched = 0
    n_sim_ok = 0
    unlock_returns_all: list[float] = []
    unlock_path_wins = 0
    unlock_path_total = 0

    for ev in events:
        code = ev["code"]
        ev_date = ev["date"]
        ratio = ev["free_ratio"]
        bars = fast_bars.get(code)
        if not bars:
            continue
        signal_date = align_to_trading(ev_date)
        if signal_date is None:
            continue
        idx = date_idx[code].get(signal_date)
        if idx is None:
            continue
        if idx + 2 >= len(bars):
            continue
        d1_open = bars[idx + 1].get("o")
        d2_close = bars[idx + 2].get("c") if idx + 2 < len(bars) else None
        if d1_open is None or d1_open <= 0 or d2_close is None:
            continue
        ret = round((d2_close - d1_open) / d1_open * 100, 4)
        n_matched += 1
        unlock_by_day[signal_date].append(ret)
        unlock_returns_all.append(ret)
        if ratio > RATIO_HIGH:
            unlock_by_day_high[signal_date].append(ret)
        elif ratio > RATIO_MID:
            unlock_by_day_mid[signal_date].append(ret)
        else:
            unlock_by_day_low[signal_date].append(ret)

        # Path-winrate for unlock stocks (secondary metric)
        sim = simulate_path(bars, idx, d1_open)
        if sim is not None:
            n_sim_ok += 1
            unlock_path_by_day[signal_date].append(sim["return_pct"])
            unlock_path_total += 1
            if sim["won"]:
                unlock_path_wins += 1

    print(f"unlock matched: {n_matched}, path sim OK: {n_sim_ok}", flush=True)
    print(f"unlock days: {len(unlock_by_day)}", flush=True)
    print(f"  high(>5%): {sum(len(v) for v in unlock_by_day_high.values())} events, "
          f"{len(unlock_by_day_high)} days", flush=True)
    print(f"  mid(1-5%): {sum(len(v) for v in unlock_by_day_mid.values())} events, "
          f"{len(unlock_by_day_mid)} days", flush=True)
    print(f"  low(<1%):  {sum(len(v) for v in unlock_by_day_low.values())} events, "
          f"{len(unlock_by_day_low)} days", flush=True)

    # ── §44 v2 Step ①: Front window sanity ──
    all_universe_returns = [r for rs in raw_by_day.values() for r in rs]

    print("\n── 前置窗口 sanity ──", flush=True)
    u_mean = statistics.mean(unlock_returns_all) if unlock_returns_all else 0
    u_wr = _winrate(unlock_returns_all)
    x_mean = statistics.mean(all_universe_returns) if all_universe_returns else 0
    x_wr = _winrate(all_universe_returns)
    print(f"unlock:   n={len(unlock_returns_all)} mean={u_mean:.4f}% winrate={u_wr:.4f}")
    print(f"universe: n={len(all_universe_returns)} mean={x_mean:.4f}% winrate={x_wr:.4f}")
    path_wr = unlock_path_wins / unlock_path_total if unlock_path_total else 0
    print(f"unlock path-winrate (-3/+8/3): {unlock_path_wins}/{unlock_path_total} = {path_wr:.4f}")

    # Split into early/late halves for stability
    mid_date = all_dates[len(all_dates) // 2]
    early_u = [r for d, rs in unlock_by_day.items() if d < mid_date for r in rs]
    late_u = [r for d, rs in unlock_by_day.items() if d >= mid_date for r in rs]
    early_x = [r for d, rs in raw_by_day.items() if d < mid_date for r in rs]
    late_x = [r for d, rs in raw_by_day.items() if d >= mid_date for r in rs]
    print(f"\nearly (< {mid_date}):", flush=True)
    if early_u:
        print(f"  unlock:   n={len(early_u)} mean={statistics.mean(early_u):.4f}% wr={_winrate(early_u):.4f}")
    if early_x:
        print(f"  universe: n={len(early_x)} mean={statistics.mean(early_x):.4f}% wr={_winrate(early_x):.4f}")
    print(f"late (>= {mid_date}):", flush=True)
    if late_u:
        print(f"  unlock:   n={len(late_u)} mean={statistics.mean(late_u):.4f}% wr={_winrate(late_u):.4f}")
    if late_x:
        print(f"  universe: n={len(late_x)} mean={statistics.mean(late_x):.4f}% wr={_winrate(late_x):.4f}")

    # ── §44 v2 Step ②: day_paired lift + permutation + Bonferroni ──
    print("\n── day_paired lift + within-day permutation null ──", flush=True)
    print(f"Bonferroni K=4, alpha_adj={ALPHA_ADJ}", flush=True)

    strata = [
        ("overall", unlock_by_day),
        ("high(>5%)", unlock_by_day_high),
        ("mid(1-5%)", unlock_by_day_mid),
        ("low(<1%)", unlock_by_day_low),
    ]

    results = {}
    for name, surv_by_day in strata:
        obs = day_paired_lift(surv_by_day, raw_by_day)
        obs_lift = obs["winrate_lift_avg"]
        n = obs["surv_n_pooled"]

        print(f"\n  {name}: computing permutation null ({N_PERM} perms)...", flush=True)
        nulls = day_cluster_permutation_fast(surv_by_day, raw_stats_by_day)
        if nulls and obs_lift is not None:
            p_neg = sum(1 for x in nulls if x <= obs_lift) / len(nulls)
            null_mean = statistics.mean(nulls)
            null_std = statistics.stdev(nulls) if len(nulls) > 1 else 0
            z_score = (obs_lift - null_mean) / null_std if null_std else 0
        else:
            p_neg = 1.0
            null_mean = None
            null_std = None
            z_score = None

        obs_mean_lift = obs.get("mean_lift_avg")

        if n < 30:
            neg_verdict = "探索性(underpowered)"
        elif obs_lift is None:
            neg_verdict = "探索性"
        elif p_neg < ALPHA_ADJ and obs_lift < 1.0:
            neg_verdict = "负向 edge validated"
        elif obs_lift < 1.0:
            neg_verdict = "负向趋势(未达显著)"
        elif obs_lift >= 1.0:
            neg_verdict = "无负向 edge(lift>=1)"
        else:
            neg_verdict = "未validated"

        results[name] = {
            "n": n, "n_days": obs["n_days"],
            "winrate_lift": obs_lift,
            "mean_lift": obs_mean_lift,
            "p_value_neg": round(p_neg, 4),
            "alpha_adj": ALPHA_ADJ,
            "null_mean": round(null_mean, 4) if null_mean is not None else None,
            "null_std": round(null_std, 4) if null_std is not None else None,
            "z_score": round(z_score, 4) if z_score is not None else None,
            "verdict": neg_verdict,
        }
        print(f"    n={n}, days={obs['n_days']}, lift={obs_lift}, mean_lift={obs_mean_lift}")
        print(f"    null_mean={null_mean}, p(neg)={p_neg:.4f}, z={z_score}")
        print(f"    verdict: {neg_verdict}")

    # ── IC (information coefficient, effect size proxy) ──
    unlock_mean = statistics.mean(unlock_returns_all) if unlock_returns_all else 0
    universe_mean = statistics.mean(all_universe_returns) if all_universe_returns else 0
    universe_std = statistics.stdev(all_universe_returns) if len(all_universe_returns) > 1 else 1
    ic = (unlock_mean - universe_mean) / universe_std if universe_std else 0

    # ── Save matrix ──
    out_dir = ROOT / "backend" / ".scratch" / "s44-lockup-lift"
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix = {
        "factor": "lockup_expiry",
        "direction": "negative (risk filter)",
        "params": {
            "return_metric": "(D+2 close - D+1 open) / D+1 open * 100 (simple, consistent)",
            "path_metric": "simulate_holding(-3/+8/3) for unlock stocks only",
            "cost_pct": COST_PCT,
            "n_perm": N_PERM,
            "alpha_adj": ALPHA_ADJ,
            "bonferroni_K": 4,
            "null_model": "within-day survivor resampling",
        },
        "n_events": len(events),
        "n_matched": n_matched,
        "n_universe": n_universe,
        "n_trading_days": len(all_dates),
        "date_range": [all_dates[0], all_dates[-1]],
        "sanity": {
            "unlock_mean": round(unlock_mean, 4),
            "unlock_winrate": round(u_wr, 4),
            "universe_mean": round(universe_mean, 4),
            "universe_winrate": round(x_wr, 4),
            "unlock_path_winrate": round(path_wr, 4),
            "unlock_path_n": unlock_path_total,
            "ic_effect_size": round(ic, 4),
        },
        "results": results,
        "note": ("§44 v2: day_paired non-pooled + within-day permutation null + Bonferroni K=4. "
                 "Negative edge = lift < 1 (unlock stocks underperform universe). "
                 "Cost=0 (risk filter avoids, not entry). "
                 "Simple return used for both groups (apples-to-apples); "
                 "path-winrate computed for unlock stocks only as secondary."),
    }
    out_path = out_dir / "matrix.json"
    out_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n矩阵已存: {out_path}", flush=True)

    # ── Summary ──
    print("\n═══ SUMMARY ═══", flush=True)
    print(f"factor: lockup_expiry (negative risk filter)", flush=True)
    print(f"window: {all_dates[0]}→{all_dates[-1]} ({len(all_dates)} trading days)", flush=True)
    print(f"n_unlock: {n_matched}, n_universe: {n_universe}", flush=True)
    print(f"unlock mean: {unlock_mean:.4f}% vs universe mean: {universe_mean:.4f}%", flush=True)
    print(f"unlock winrate: {u_wr:.4f} vs universe winrate: {x_wr:.4f}", flush=True)
    print(f"IC (effect size): {ic:.4f}", flush=True)
    for name, r in results.items():
        print(f"  {name}: lift={r['winrate_lift']} p={r['p_value_neg']} "
              f"verdict={r['verdict']}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
