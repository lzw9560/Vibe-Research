# -*- coding: utf-8 -*-
"""P2 实验：诚实重跑 gap(-3,-2] 浅恐慌子组 + cap=3/day 集中度.

验证 risk-path 专家报的 +0.843%/t=2.16 是否可复现。

实验设计：
1. S232 watchlist 信号股（turn>20%+vr5>2 未涨停）+ T+1 gap 在 [-3,-2) 的子组
2. entry = T+1 open（gap 已知后买）
3. exit = T+2 盘中 -3% stop（R6 realistic: 跳空穿 stop 按 t2_open+滑点0.2%）/ 否则 T+2 close
4. cap=3/day：同日多笔只取 shallowest gap 的前 3 只
5. per-day-mean t-test（同日多笔聚合成 day-mean，非 per-trade t）
6. day-clustering：同日 trades 共享 regime，effective N = n_days
7. Bonferroni 校正 gap-width × cap grid（9 组合）
8. walk-forward OOS：前半 train 选参 → 后半 test 验证
9. close_ev 诚实口径（entry=T+1 close → T+2 open，隔离 T+1 日内泄漏）

禁止：
- 禁止信任 risk-path +0.843%/t=2.16 数字——必须从 committed code 重跑
- 禁止 per-trade t（同日相关夸大 N），必须 per-day-mean t
- 禁止 stop_price 精确成交（R6：跳空穿 stop 按 t2_open）
- 禁止 in-sample 分段当 walk-forward

跑法：cd backend && .venv/bin/python -m tools.explore_gap_shallow_panic_cap3
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / ".vibe-research"
KLINE_DB = DATA / "baostock_kline_cache.db"
ZT_DB = DATA / "zt_history.db"

TURN_THRESHOLD = 20.0
VR5_THRESHOLD = 2.0
SLIPPAGE = 0.002  # 0.2% slippage for gap-through fills (R6)
STOP = -0.03  # -3% stop


# ---------------------------------------------------------------------------
# Data loading (复用 explore_s232_stop_verify 模式)
# ---------------------------------------------------------------------------

def load_kline_db() -> dict[str, list[dict]]:
    """从 SQLite 读 kline（code -> sorted bars）。"""
    conn = sqlite3.connect(str(KLINE_DB))
    out: dict[str, list[dict]] = {}
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(bars, list) and bars:
            out[code] = sorted(bars, key=lambda b: b.get("date", ""))
    conn.close()
    return out


def load_zt_by_date() -> dict[str, set[str]]:
    conn = sqlite3.connect(str(ZT_DB))
    zt: dict[str, set[str]] = {}
    for d, code in conn.execute("SELECT date, code FROM zt_history"):
        zt.setdefault(d, set()).add(code)
    conn.close()
    return zt


def vol_ratio_5(bars: list[dict], idx: int) -> float | None:
    """T 日 volume / mean(prev 5 days volume)。前置不足/含 0/无量 → None。"""
    if idx < 5:
        return None
    vol = bars[idx].get("volume")
    if not vol:
        return None
    pv = [b.get("volume") for b in bars[idx - 5:idx]]
    if any(v is None or v == 0 for v in pv):
        return None
    avg5 = sum(pv) / 5.0
    return vol / avg5 if avg5 else None


def gen_watchlist_codes(
    t: str, all_bars: dict[str, list[dict]], zt_t: set[str]
) -> list[str]:
    """S232 watchlist codes: turn>20% + vr5>2, not limit-up, not ST。"""
    out: list[str] = []
    for code, bars in all_bars.items():
        tbar = None
        tidx = -1
        for i, b in enumerate(bars):
            if b.get("date") == t:
                tbar = b
                tidx = i
                break
        if tbar is None:
            continue
        if code in zt_t:
            continue
        if tbar.get("isST") in ("1", 1, True):
            continue
        turn = tbar.get("turn")
        if turn is None or turn <= TURN_THRESHOLD:
            continue
        vr5 = vol_ratio_5(bars, tidx)
        if vr5 is None or vr5 <= VR5_THRESHOLD:
            continue
        out.append(code)
    return out


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------

def build_records(
    end_date: str = "2026-09-17",
    days: int = 560,
    gap_lo: float = -100.0,
    gap_hi: float = 100.0,
) -> tuple[list[dict[str, Any]], int]:
    """Build trade records for gap range [gap_lo, gap_hi).

    Wide range [-100, 100) captures ALL watchlist picks (for n_picks_total).
    Each record stores t1 date for day-clustering and t1_close for close_ev.

    Excludes T+1 one-word limit-up (V1 fake edge R1: can't buy).
    """
    all_bars = load_kline_db()
    zt = load_zt_by_date()
    cal = sorted(zt.keys())
    if end_date not in cal:
        return [], 0
    end_idx = cal.index(end_date)
    date_idx = {d: i for i, d in enumerate(cal)}
    pairs = [
        (cal[i], cal[i + 1])
        for i in range(max(0, end_idx - days), end_idx)
        if i + 1 < len(cal)
    ]

    records: list[dict[str, Any]] = []
    for t, t1 in pairs:
        zt_t = zt.get(t, set())
        t1_idx = date_idx.get(t1)
        if t1_idx is None or t1_idx + 1 >= len(cal):
            continue
        t2 = cal[t1_idx + 1]
        wl = gen_watchlist_codes(t, all_bars, zt_t)
        for code in wl:
            bars = all_bars.get(code, [])
            tbar = next((b for b in bars if b.get("date") == t), None)
            if not tbar or tbar.get("close") is None:
                continue
            t_close = tbar["close"]
            t1bar = next((b for b in bars if b.get("date") == t1), None)
            if not t1bar or t1bar.get("open") is None or t1bar["open"] == 0:
                continue
            t1_open = t1bar["open"]
            t1_close = t1bar.get("close")
            gap = (t1_open - t_close) / t_close * 100
            if not (gap_lo <= gap < gap_hi):
                continue
            # Exclude T+1 one-word limit-up (can't buy, V1 fake edge R1)
            zt_limit = 0.2 if code.startswith(("sz30", "sh68")) else 0.1
            if t1_open >= t_close * (1 + zt_limit) * 0.999:
                continue
            t2bar = next((b for b in bars if b.get("date") == t2), None)
            if not t2bar:
                continue
            if None in (
                t2bar.get("open"),
                t2bar.get("high"),
                t2bar.get("low"),
                t2bar.get("close"),
            ):
                continue
            records.append(
                {
                    "code": code,
                    "t": t,
                    "t1": t1,
                    "t2": t2,
                    "gap": round(gap, 4),
                    "t1_open": t1_open,
                    "t1_close": t1_close,
                    "t2_open": t2bar["open"],
                    "t2_high": t2bar["high"],
                    "t2_low": t2bar["low"],
                    "t2_close": t2bar["close"],
                }
            )
    return records, len(pairs)


# ---------------------------------------------------------------------------
# Cap per day (shallowest-gap-first)
# ---------------------------------------------------------------------------

def apply_cap(records: list[dict], cap: int | None) -> list[dict]:
    """Apply cap per day: sort by gap descending (shallowest first), take top cap.

    Shallowest gap = closest to 0 = highest gap value (e.g., -2.1% > -2.9%).
    """
    if cap is None:
        return list(records)
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_day[r["t1"]].append(r)
    out: list[dict] = []
    for _day, recs in by_day.items():
        recs_sorted = sorted(recs, key=lambda r: r["gap"], reverse=True)
        out.extend(recs_sorted[:cap])
    return out


# ---------------------------------------------------------------------------
# Return calculations
# ---------------------------------------------------------------------------

def realistic_stop_ret(r: dict, stop: float = STOP) -> float:
    """R6 realistic fill: gap-through → t2_open*(1-slip), else stop_price, else t2_close."""
    entry = r["t1_open"]
    sp = entry * (1 + stop)
    trig = r["t2_low"] <= sp
    if trig:
        if r["t2_open"] <= sp:
            # Gap through stop → market order at t2_open (worse) + slippage
            exit_p = r["t2_open"] * (1 - SLIPPAGE)
        else:
            # Touched during day → limit order at stop (approx)
            exit_p = sp
    else:
        exit_p = r["t2_close"]
    return (exit_p - entry) / entry * 100


def ideal_stop_ret(r: dict, stop: float = STOP) -> float:
    """Ideal (over-credit) fill: stop_price if triggered, else t2_close."""
    entry = r["t1_open"]
    sp = entry * (1 + stop)
    trig = r["t2_low"] <= sp
    exit_p = sp if trig else r["t2_close"]
    return (exit_p - entry) / entry * 100


def close_ev_ret(r: dict) -> float:
    """Honest close_ev: (t2_open - t1_close) / t1_close * 100.

    Overnight only — isolates T+1 intraday leakage (commit 33a93e7 caliber).
    """
    if not r.get("t1_close") or r["t1_close"] == 0:
        return 0.0
    return (r["t2_open"] - r["t1_close"]) / r["t1_close"] * 100


# ---------------------------------------------------------------------------
# Per-day-mean t-test (day-clustering)
# ---------------------------------------------------------------------------

def per_day_stats(
    records: list[dict], ret_fn: Callable[[dict], float]
) -> dict[str, Any]:
    """Group by t1 date → daily mean return → one-sample t-test on day-means.

    Effective N = n_days (not n_trades), accounting for same-day regime sharing.
    Uses sample stdev (Bessel's correction) for proper inference.
    """
    by_day: dict[str, list[float]] = defaultdict(list)
    for r in records:
        by_day[r["t1"]].append(ret_fn(r))

    sorted_days = sorted(by_day.keys())
    day_means = [sum(by_day[d]) / len(by_day[d]) for d in sorted_days]
    n = len(day_means)
    n_trades = sum(len(by_day[d]) for d in sorted_days)

    if n == 0:
        return {
            "n_days": 0,
            "n_trades": 0,
            "per_trade_ev": 0.0,
            "per_day_mean_ev": 0.0,
            "day_clustered_t": 0.0,
            "ci_lo": 0.0,
            "ci_hi": 0.0,
            "p_one_sided": 1.0,
            "day_means_chrono": [],
        }

    per_trade_rets = [ret_fn(r) for r in records]
    per_trade_ev = sum(per_trade_rets) / n_trades if n_trades else 0.0

    mean = sum(day_means) / n
    std = statistics.stdev(day_means) if n > 1 else 0.0
    se = std / math.sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    ci_lo = mean - 1.96 * se if se > 0 else mean
    ci_hi = mean + 1.96 * se if se > 0 else mean
    p_one = 0.5 * (1 - math.erf(abs(t) / math.sqrt(2)))

    return {
        "n_days": n,
        "n_trades": n_trades,
        "per_trade_ev": round(per_trade_ev, 4),
        "per_day_mean_ev": round(mean, 4),
        "day_clustered_t": round(t, 4),
        "ci_lo": round(ci_lo, 4),
        "ci_hi": round(ci_hi, 4),
        "p_one_sided": round(p_one, 6),
        "day_means_chrono": day_means,
    }


# ---------------------------------------------------------------------------
# Walk-forward OOS (split-half)
# ---------------------------------------------------------------------------

def walk_forward(
    records: list[dict], ret_fn: Callable[[dict], float]
) -> dict[str, Any]:
    """Split day-means chronologically: first half train, second half test.

    risk-path 专家 split-half: 前半 +0.92%/t=1.52 → 后半 -0.12%/t=-0.17 衰减.
    若复现这个衰减 → 证否（regime-dependent 非 robust edge）。
    """
    stats = per_day_stats(records, ret_fn)
    day_means = stats["day_means_chrono"]
    n = len(day_means)
    if n < 4:
        return {
            "train_ev": 0.0,
            "train_t": 0.0,
            "test_ev": 0.0,
            "test_t": 0.0,
            "n_train": 0,
            "n_test": 0,
            "decay_pct": None,
        }

    mid = n // 2
    train = day_means[:mid]
    test = day_means[mid:]

    def half_stats(half: list[float]) -> tuple[float, float, int]:
        nh = len(half)
        if nh == 0:
            return 0.0, 0.0, 0
        m = sum(half) / nh
        s = statistics.stdev(half) if nh > 1 else 0.0
        se = s / math.sqrt(nh) if nh > 0 else 0.0
        t_val = m / se if se > 0 else 0.0
        return round(m, 4), round(t_val, 4), nh

    train_ev, train_t, n_train = half_stats(train)
    test_ev, test_t, n_test = half_stats(test)
    decay = (
        round((test_ev - train_ev) / abs(train_ev) * 100, 1)
        if train_ev != 0
        else None
    )

    return {
        "train_ev": train_ev,
        "train_t": train_t,
        "n_train": n_train,
        "test_ev": test_ev,
        "test_t": test_t,
        "n_test": n_test,
        "decay_pct": decay,
    }


# ---------------------------------------------------------------------------
# Bonferroni grid (gap-width × cap)
# ---------------------------------------------------------------------------

def bonferroni_grid(all_records: list[dict]) -> dict[str, Any]:
    """3 gap-widths × 3 caps = 9 combos, Bonferroni p/9."""
    gap_widths = [
        ("[-3,-2)", -3.0, -2.0),
        ("[-2.5,-1.5)", -2.5, -1.5),
        ("[-5,-2)", -5.0, -2.0),
    ]
    caps = [("none", None), ("3", 3), ("5", 5)]

    combos: list[dict[str, Any]] = []
    for gw_name, gw_lo, gw_hi in gap_widths:
        for cap_name, cap_val in caps:
            sub = [r for r in all_records if gw_lo <= r["gap"] < gw_hi]
            capped = apply_cap(sub, cap_val)
            stats = per_day_stats(capped, realistic_stop_ret)
            combos.append(
                {
                    "gap_width": gw_name,
                    "cap": cap_name,
                    "n_trades": stats["n_trades"],
                    "n_days": stats["n_days"],
                    "per_trade_ev": stats["per_trade_ev"],
                    "per_day_mean_ev": stats["per_day_mean_ev"],
                    "day_clustered_t": stats["day_clustered_t"],
                    "p_one_sided": stats["p_one_sided"],
                }
            )

    n_combos = len(combos)
    bonf_alpha = 0.05 / n_combos

    main = next(
        c for c in combos if c["gap_width"] == "[-3,-2)" and c["cap"] == "3"
    )
    main_p = main["p_one_sided"]
    main_bonf_p = min(main_p * n_combos, 1.0)

    return {
        "n_combos": n_combos,
        "bonf_alpha": round(bonf_alpha, 6),
        "combos": combos,
        "main_combo": main,
        "main_bonf_pass": main_p < bonf_alpha,
        "main_bonf_p": round(main_bonf_p, 6),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 72)
    print("P2 实验：诚实重跑 gap(-3,-2] 浅恐慌子组 + cap=3/day 集中度")
    print("验证 risk-path 专家报的 +0.843%/t=2.16 是否可复现")
    print("=" * 72)

    print("\n加载数据…")
    # Wide gap range to capture ALL watchlist picks (for n_picks_total)
    all_records, npairs = build_records(
        end_date="2026-09-17", days=560, gap_lo=-100.0, gap_hi=100.0
    )
    if not all_records:
        print("ERR: no records")
        return
    n_picks_total = len(all_records)
    print(f"pairs={npairs} n_picks_total(all gaps)={n_picks_total}")

    # ---- Filter to gap(-3,-2] = [-3, -2) ----
    gap_neg3_neg2 = [r for r in all_records if -3.0 <= r["gap"] < -2.0]
    n_picks_gap = len(gap_neg3_neg2)
    active_days = sorted(set(r["t1"] for r in gap_neg3_neg2))
    n_days = len(active_days)
    print(f"gap(-3,-2] 子组（[-3,-2)）: n_picks={n_picks_gap} n_active_days={n_days}")

    # ---- Cap=3/day shallowest-gap-first ----
    capped3 = apply_cap(gap_neg3_neg2, 3)
    print(f"cap=3/day: n_picks={len(capped3)} (removed {n_picks_gap - len(capped3)})")

    # ==================================================================
    # 1. open_stop EV (entry=T+1 open, -3% stop R6 realistic / T+2 close)
    # ==================================================================
    print("\n" + "=" * 72)
    print("1. open_stop EV（entry=T+1 open, -3% stop R6 realistic / T+2 close）")
    print("=" * 72)

    # No cap
    s_nc = per_day_stats(gap_neg3_neg2, realistic_stop_ret)
    print(
        f"\n[no cap]  n_trades={s_nc['n_trades']} n_days={s_nc['n_days']}  "
        f"per_trade_EV={s_nc['per_trade_ev']:+.4f}%  "
        f"per_day_mean_EV={s_nc['per_day_mean_ev']:+.4f}%  "
        f"day_t={s_nc['day_clustered_t']:+.4f}  "
        f"CI[{s_nc['ci_lo']:+.4f},{s_nc['ci_hi']:+.4f}]  "
        f"p={s_nc['p_one_sided']:.6f}"
    )

    # Cap=3
    s_c3 = per_day_stats(capped3, realistic_stop_ret)
    print(
        f"[cap=3]  n_trades={s_c3['n_trades']} n_days={s_c3['n_days']}  "
        f"per_trade_EV={s_c3['per_trade_ev']:+.4f}%  "
        f"per_day_mean_EV={s_c3['per_day_mean_ev']:+.4f}%  "
        f"day_t={s_c3['day_clustered_t']:+.4f}  "
        f"CI[{s_c3['ci_lo']:+.4f},{s_c3['ci_hi']:+.4f}]  "
        f"p={s_c3['p_one_sided']:.6f}"
    )

    # ==================================================================
    # 2. close_ev honest caliber (entry=T+1 close → T+2 open)
    # ==================================================================
    print("\n" + "=" * 72)
    print("2. close_ev 诚实口径（entry=T+1 close → T+2 open, 隔离 T+1 日内泄漏）")
    print("=" * 72)

    # Filter records with valid t1_close for close_ev
    valid_close = [r for r in gap_neg3_neg2 if r.get("t1_close") and r["t1_close"] != 0]
    valid_close_c3 = [r for r in capped3 if r.get("t1_close") and r["t1_close"] != 0]

    c_nc = per_day_stats(valid_close, close_ev_ret)
    print(
        f"\n[no cap]  n_trades={c_nc['n_trades']} n_days={c_nc['n_days']}  "
        f"per_trade_EV={c_nc['per_trade_ev']:+.4f}%  "
        f"per_day_mean_EV={c_nc['per_day_mean_ev']:+.4f}%  "
        f"day_t={c_nc['day_clustered_t']:+.4f}  "
        f"CI[{c_nc['ci_lo']:+.4f},{c_nc['ci_hi']:+.4f}]  "
        f"p={c_nc['p_one_sided']:.6f}"
    )

    c_c3 = per_day_stats(valid_close_c3, close_ev_ret)
    print(
        f"[cap=3]  n_trades={c_c3['n_trades']} n_days={c_c3['n_days']}  "
        f"per_trade_EV={c_c3['per_trade_ev']:+.4f}%  "
        f"per_day_mean_EV={c_c3['per_day_mean_ev']:+.4f}%  "
        f"day_t={c_c3['day_clustered_t']:+.4f}  "
        f"CI[{c_c3['ci_lo']:+.4f},{c_c3['ci_hi']:+.4f}]  "
        f"p={c_c3['p_one_sided']:.6f}"
    )

    # ==================================================================
    # 3. R6 realistic vs ideal fill (over-credit quantification)
    # ==================================================================
    print("\n" + "=" * 72)
    print("3. R6 realistic vs ideal fill（over-credit 量化, cap=3）")
    print("=" * 72)

    ideal_s = per_day_stats(capped3, ideal_stop_ret)
    real_s = s_c3  # already computed
    over_credit = ideal_s["per_day_mean_ev"] - real_s["per_day_mean_ev"]
    print(
        f"\nideal   (over-credit): per_day_mean_EV={ideal_s['per_day_mean_ev']:+.4f}%  "
        f"day_t={ideal_s['day_clustered_t']:+.4f}"
    )
    print(
        f"realistic (R6):        per_day_mean_EV={real_s['per_day_mean_ev']:+.4f}%  "
        f"day_t={real_s['day_clustered_t']:+.4f}"
    )
    print(f"over-credit = {over_credit:+.4f}% (ideal - realistic)")

    # Gap-through stats
    sp_fn = lambda r: r["t1_open"] * (1 + STOP)
    trig_total = sum(1 for r in capped3 if r["t2_low"] <= sp_fn(r))
    gap_through = sum(
        1
        for r in capped3
        if r["t2_low"] <= sp_fn(r) and r["t2_open"] <= sp_fn(r)
    )
    print(
        f"stop triggered: {trig_total}/{len(capped3)} ({trig_total / len(capped3) * 100:.1f}%)"
    )
    if trig_total:
        print(
            f"  gap-through: {gap_through} ({gap_through / trig_total * 100:.1f}% of triggers)"
        )

    # ==================================================================
    # 4. cap=3 vs no cap comparison
    # ==================================================================
    print("\n" + "=" * 72)
    print("4. cap=3 vs no cap 对比（open_stop R6 realistic）")
    print("=" * 72)
    print(f"\n{'':12} {'n_trades':>8} {'n_days':>6} {'per_trade_EV':>12} {'per_day_mean_EV':>14} {'day_t':>8}")
    print("-" * 66)
    print(
        f"{'no cap':12} {s_nc['n_trades']:>8} {s_nc['n_days']:>6} "
        f"{s_nc['per_trade_ev']:>+11.4f}% {s_nc['per_day_mean_ev']:>+13.4f}% {s_nc['day_clustered_t']:>+8.4f}"
    )
    print(
        f"{'cap=3':12} {s_c3['n_trades']:>8} {s_c3['n_days']:>6} "
        f"{s_c3['per_trade_ev']:>+11.4f}% {s_c3['per_day_mean_ev']:>+13.4f}% {s_c3['day_clustered_t']:>+8.4f}"
    )

    # ==================================================================
    # 5. Bonferroni grid (3 gap-widths × 3 caps = 9 combos)
    # ==================================================================
    print("\n" + "=" * 72)
    print("5. Bonferroni grid（3 gap-widths × 3 caps = 9 combos）")
    print("=" * 72)

    bonf = bonferroni_grid(all_records)
    print(f"\nn_combos={bonf['n_combos']}  Bonferroni alpha={bonf['bonf_alpha']}")
    print(
        f"\n{'gap_width':<14} {'cap':<6} {'n_trades':>8} {'n_days':>6} "
        f"{'per_trade_EV':>12} {'per_day_mean_EV':>14} {'day_t':>8} {'p_one':>10}"
    )
    print("-" * 86)
    for c in bonf["combos"]:
        marker = " <- MAIN" if c["gap_width"] == "[-3,-2)" and c["cap"] == "3" else ""
        print(
            f"{c['gap_width']:<14} {c['cap']:<6} {c['n_trades']:>8} {c['n_days']:>6} "
            f"{c['per_trade_ev']:>+11.4f}% {c['per_day_mean_ev']:>+13.4f}% "
            f"{c['day_clustered_t']:>+8.4f} {c['p_one_sided']:>10.6f}{marker}"
        )

    print(f"\nmain combo (gap[-3,-2) + cap=3):")
    print(f"  p_one_sided   = {bonf['main_combo']['p_one_sided']:.6f}")
    print(f"  Bonferroni p  = {bonf['main_bonf_p']:.6f}")
    print(f"  Bonferroni pass (p < {bonf['bonf_alpha']}): {bonf['main_bonf_pass']}")

    # ==================================================================
    # 6. walk-forward OOS (split-half)
    # ==================================================================
    print("\n" + "=" * 72)
    print("6. walk-forward OOS（前半 train → 后半 test, day-means chronological split）")
    print("=" * 72)

    # open_stop walk-forward
    wf_open = walk_forward(capped3, realistic_stop_ret)
    print(f"\n[open_stop, cap=3]")
    print(
        f"  train: EV={wf_open['train_ev']:+.4f}%  t={wf_open['train_t']:+.4f}  "
        f"n_days={wf_open['n_train']}"
    )
    print(
        f"  test:  EV={wf_open['test_ev']:+.4f}%  t={wf_open['test_t']:+.4f}  "
        f"n_days={wf_open['n_test']}"
    )
    if wf_open["decay_pct"] is not None:
        print(f"  decay = {wf_open['decay_pct']:+.1f}% (test vs |train|)")

    # close_ev walk-forward
    wf_close = walk_forward(valid_close_c3, close_ev_ret)
    print(f"\n[close_ev, cap=3]")
    print(
        f"  train: EV={wf_close['train_ev']:+.4f}%  t={wf_close['train_t']:+.4f}  "
        f"n_days={wf_close['n_train']}"
    )
    print(
        f"  test:  EV={wf_close['test_ev']:+.4f}%  t={wf_close['test_t']:+.4f}  "
        f"n_days={wf_close['n_test']}"
    )
    if wf_close["decay_pct"] is not None:
        print(f"  decay = {wf_close['decay_pct']:+.1f}% (test vs |train|)")

    # Grid walk-forward: select best combo on train, verify on test
    print(f"\n--- Grid walk-forward: select best gap-width×cap on train → verify on test ---")
    gw_cfgs = [
        (-3.0, -2.0, "[-3,-2)"),
        (-2.5, -1.5, "[-2.5,-1.5)"),
        (-5.0, -2.0, "[-5,-2)"),
    ]
    cap_cfgs = [(None, "none"), (3, "3"), (5, "5")]

    best_train_ev = -1e9
    best_name = ""
    best_wf: dict[str, Any] = {}
    for gw_lo, gw_hi, gw_name in gw_cfgs:
        for cap_val, cap_name in cap_cfgs:
            sub = [r for r in all_records if gw_lo <= r["gap"] < gw_hi]
            capped = apply_cap(sub, cap_val)
            wf = walk_forward(capped, realistic_stop_ret)
            if wf["train_ev"] > best_train_ev:
                best_train_ev = wf["train_ev"]
                best_name = f"gap{gw_name}+cap{cap_name}"
                best_wf = wf

    print(f"best on train: {best_name}")
    print(
        f"  train: EV={best_wf['train_ev']:+.4f}%  t={best_wf['train_t']:+.4f}  "
        f"n_days={best_wf['n_train']}"
    )
    print(
        f"  test:  EV={best_wf['test_ev']:+.4f}%  t={best_wf['test_t']:+.4f}  "
        f"n_days={best_wf['n_test']}"
    )
    if best_wf.get("decay_pct") is not None:
        print(f"  decay = {best_wf['decay_pct']:+.1f}%")

    # ==================================================================
    # 7. risk-path reproduction check
    # ==================================================================
    print("\n" + "=" * 72)
    print("7. risk-path 复现检查")
    print("=" * 72)
    print(
        "\nrisk-path 报: gap(-3,-2] n=295 per-trade EV=+0.843% t=2.16, "
        "cap=3 per-day-mean EV=+1.273% t=2.34"
    )
    print(f"我们 (cap=3, open_stop R6 realistic):")
    print(f"  n_trades          = {s_c3['n_trades']}  (risk-path: n=295)")
    print(f"  per_trade_EV      = {s_c3['per_trade_ev']:+.4f}%  (risk-path: +0.843%)")
    print(f"  per_day_mean_EV   = {s_c3['per_day_mean_ev']:+.4f}%  (risk-path: +1.273%)")
    print(f"  day_clustered_t   = {s_c3['day_clustered_t']:+.4f}  (risk-path: t=2.34)")

    ev_close = abs(s_c3["per_trade_ev"] - 0.843) < 0.30
    t_close = abs(s_c3["day_clustered_t"] - 2.34) < 0.50
    reproduced = ev_close and t_close
    print(f"  per_trade EV within 0.30% of +0.843%: {ev_close}")
    print(f"  day t within 0.50 of 2.34:            {t_close}")
    print(f"  reproduced risk-path numbers:          {reproduced}")

    # ==================================================================
    # 8. Honest verdict
    # ==================================================================
    print("\n" + "=" * 72)
    print("8. 诚实判定")
    print("=" * 72)

    open_ev = s_c3["per_day_mean_ev"]
    open_t = s_c3["day_clustered_t"]
    close_ev = c_c3["per_day_mean_ev"]
    close_t = c_c3["day_clustered_t"]
    bonf_pass = bonf["main_bonf_pass"]
    wf_test_ev = wf_open["test_ev"]
    wf_test_t = wf_open["test_t"]
    wf_close_test_ev = wf_close["test_ev"]
    wf_close_train_ev = wf_close["train_ev"]

    print(f"\nopen_stop (cap=3, R6 realistic):")
    print(f"  per_day_mean_EV = {open_ev:+.4f}%")
    print(f"  day_clustered_t = {open_t:+.4f}")
    print(f"  Bonferroni pass = {bonf_pass} (p={bonf['main_bonf_p']:.6f})")
    print(f"  walk-forward train EV = {wf_open['train_ev']:+.4f}%  t={wf_open['train_t']:+.4f}")
    print(f"  walk-forward test  EV = {wf_test_ev:+.4f}%  t={wf_test_t:+.4f}")

    print(f"\nclose_ev (honest, cap=3):")
    print(f"  per_day_mean_EV = {close_ev:+.4f}%")
    print(f"  day_clustered_t = {close_t:+.4f}")
    print(f"  walk-forward train EV = {wf_close_train_ev:+.4f}%  t={wf_close['train_t']:+.4f}")
    print(f"  walk-forward test  EV = {wf_close_test_ev:+.4f}%  t={wf_close['test_t']:+.4f}")

    # Verdict logic (frozen before running, per §44 v2 decision rule)
    if n_days < 60:
        verdict = "underpowered"
        reason = f"n_days={n_days} < 60, insufficient power for definitive verdict"
    elif wf_open["train_ev"] > 0 and wf_test_ev <= 0:
        verdict = "edge-falsified"
        reason = (
            f"walk-forward decay: train {wf_open['train_ev']:+.4f}% → "
            f"test {wf_test_ev:+.4f}% (regime-dependent, not robust)"
        )
    elif close_ev <= 0 and open_ev > 0:
        verdict = "edge-falsified"
        reason = (
            f"close_ev honest caliber per-day-mean EV = {close_ev:+.4f}% ≤ 0 "
            f"(open_stop EV {open_ev:+.4f}% is intraday leakage fake edge)"
        )
    elif open_t < 2 or not bonf_pass:
        verdict = "exploratory"
        reason = (
            f"EV={open_ev:+.4f}% but t={open_t:.2f} < 2 or "
            f"Bonferroni fail (p={bonf['main_bonf_p']:.4f}), "
            f"not robust enough to confirm"
        )
    elif (
        open_ev > 0
        and open_t > 2
        and bonf_pass
        and wf_test_ev > 0
        and close_ev > 0
    ):
        verdict = "edge-confirmed"
        reason = "all checks pass: EV>0, t>2, Bonferroni pass, walk-forward test>0, close_ev>0"
    else:
        verdict = "exploratory"
        reason = "mixed signals, not enough evidence to confirm or definitively falsify"

    print(f"\n>>> 诚实判定: {verdict}")
    print(f">>> 原因: {reason}")

    # ==================================================================
    # SUMMARY
    # ==================================================================
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"n_picks_total (all gaps) : {n_picks_total}")
    print(f"n_picks_gap(-3,-2]       : {n_picks_gap}")
    print(f"n_days (active)          : {n_days}")
    print(f"cap=3 n_picks            : {len(capped3)}")
    print(f"open_stop per_trade_EV  : {s_c3['per_trade_ev']:+.4f}%")
    print(f"open_stop per_day_mean  : {s_c3['per_day_mean_ev']:+.4f}%")
    print(f"open_stop day_clustered_t: {s_c3['day_clustered_t']:+.4f}")
    print(f"close_ev per_trade_EV   : {c_c3['per_trade_ev']:+.4f}%")
    print(f"close_ev per_day_mean   : {c_c3['per_day_mean_ev']:+.4f}%")
    print(f"close_ev day_clustered_t : {c_c3['day_clustered_t']:+.4f}")
    print(f"Bonferroni p             : {bonf['main_bonf_p']:.6f} (pass={bonf_pass})")
    print(f"walk-forward train       : EV={wf_open['train_ev']:+.4f}% t={wf_open['train_t']:+.4f}")
    print(f"walk-forward test        : EV={wf_open['test_ev']:+.4f}% t={wf_open['test_t']:+.4f}")
    print(f"R6 over-credit          : {over_credit:+.4f}%")
    print(f"reproduced risk-path    : {reproduced}")
    print(f"verdict                 : {verdict}")


if __name__ == "__main__":
    main()
