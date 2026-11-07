# -*- coding: utf-8 -*-
"""S1 解禁避险组合 filter — 组合级 BHAR 对比 (full vs avoidance universe).

§44 v3 + R11-R13 + 10 flaw + high-risk lens.

信号: 全市场等权宇宙 vs 剔除未来20交易日 free_ratio>20% 或 lift_mkt_cap>10亿 解禁的宇宙.
     避险逻辑=提前知道卖方要卖→提前躲开 (跟庄理论唯一诚实"提前布局").
     lift_mkt_cap 单位=万元 → 10亿=100000万元.

测法 (组合级 BHAR, 非 day_paired):
  1. 非重叠 20-交易日周期: full U vs avoidance V(=U\avoided) 等权 forward 收益.
     spread = avoidance_ret - full_ret. 正=避险有效.
  2. R12 size-matched: 按 trailing amount 分 10 decile, decile 内 avoidance vs full,
     跨 decile 等权 = size-matched spread (控 size, 非沪深300大盘).
  3. Fama-MacBeth 日面板: forward20d_ret ~ avoid + log(size), 日截面回归系数,
     Newey-West HAC(lag=20) t (控重叠自相关). n_days 充足.
  4. R13 survivorship 状态报.
  5. walk-forward 周期分半.
  6. Bonferroni (n_tests=6: 3 并行信号 × 2 方向).

避 flaw:
  - 解禁日期确定性无歧义 (announced, 无 look-ahead).
  - entry 不退化 OLS; forward ret 用 close[t+20]/close[t]-1 (delisted→last bar).
  - 成本按组合换手: avoided 分数 × 0.3% round-trip.
  - 不要求 median>0/WR>55% (high-risk lens 放松, 但报).
"""

from __future__ import annotations
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
LOCKUP = DATA / "lockup_events_cache.json"

COST_RT = 0.003  # 0.3% round-trip (avoided 分数 × 此)
HOLD = 20  # 20 交易日持有/避险窗口
FR_THRESH = 0.20  # free_ratio > 20%
LM_THRESH = 100000.0  # lift_mkt_cap > 10亿 (万元单位)
SIZE_LOOKBACK = 20  # trailing amount 窗口
ALPHA = 0.05
N_TESTS_BONF = 6  # 3 并行信号(S1/S2/S4) × 2 方向


def norm_sf(t: float) -> float:
    """two-sided -> one-sided positive p."""
    return 0.5 * (1 - erf(abs(t) / sqrt(2))) if t > 0 else 0.5 * (1 - erf(abs(t) / sqrt(2)))  # direction-agnostic here


def load_lockup() -> list[dict]:
    d = json.load(open(LOCKUP))
    # filter to big-unlock events only (the avoidance set)
    big = [
        e
        for e in d
        if (e.get("free_ratio") is not None and e["free_ratio"] > FR_THRESH)
        or (e.get("lift_mkt_cap") is not None and e["lift_mkt_cap"] > LM_THRESH)
    ]
    return big, d


def load_kline_overlap(start: str) -> tuple[dict[str, dict[str, dict]], set[str]]:
    """Load kline bars with date >= start. Returns (code -> {date: bar}, all_dates)."""
    conn = sqlite3.connect(str(KLINE_DB))
    code_map: dict[str, dict[str, dict]] = {}
    all_dates: set[str] = set()
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or not bars:
            continue
        dmap: dict[str, dict] = {}
        for b in bars:
            dt = b.get("date")
            if dt and dt >= start:
                dmap[dt] = b
                all_dates.add(dt)
        if dmap:
            code_map[code] = dmap
    conn.close()
    return code_map, all_dates


def main():
    print("=" * 78)
    print("S1 解禁避险组合 filter — 组合级 BHAR (full vs avoidance)")
    print("=" * 78)

    big_events, all_events = load_lockup()
    print(f"\nlockup events total={len(all_events)} big-unlock(avoid-set)={len(big_events)}")
    print(f"  thresholds: free_ratio>{FR_THRESH} OR lift_mkt_cap>{LM_THRESH}万元(=10亿)")

    # 解禁日 -> set of codes with big unlock on that date
    big_by_date: dict[str, set[str]] = defaultdict(set)
    for e in big_events:
        big_by_date[e["date"]].add(e["code"])
    big_dates_sorted = sorted(big_by_date.keys())
    print(f"  big-unlock event dates: {len(big_dates_sorted)} ({big_dates_sorted[0]} -> {big_dates_sorted[-1]})")

    # load kline restricted to overlap window (need trailing lookback too)
    # lockup starts 2025-12-01; need 20d lookback before -> load from 2025-11-01
    code_map, kline_dates = load_kline_overlap("2025-11-01")
    calendar = sorted(d for d in kline_dates if d >= "2025-11-01")
    cal_idx = {d: i for i, d in enumerate(calendar)}
    print(
        f"\nkline overlap window: {calendar[0]} -> {calendar[-1]} ({len(calendar)} trading days, codes={len(code_map)})"
    )

    # testable window: rebalance t needs t+HOLD within calendar AND lockup events cover (t, t+HOLD]
    # lockup events end 2026-09-30; kline ends 2026-09-23. forward 20d must be <= last kline date.
    last_kline = calendar[-1]
    testable = [d for d in calendar if cal_idx[d] + HOLD < len(calendar) and d >= "2025-12-01"]
    print(f"testable rebalance dates (t, t+{HOLD} within kline, lockup-covered): {len(testable)}")
    if testable:
        print(f"  {testable[0]} -> {testable[-1]}")

    # ---------- per-stock forward-return + avoid flag + size proxy ----------
    # For each testable date t and each code in universe:
    #   forward_ret = close[t+HOLD]/close[t] - 1  (delisted -> last bar in (t, t+HOLD])
    #   avoid = any big unlock event date in (t, t+HOLD] for this code
    #   size  = mean amount over trailing SIZE_LOOKBACK days before t
    # Build a panel: list of (t, code, forward_ret, avoid(0/1), log_size, decile)
    # Only include code if has bar at t (close>0) and some forward bar exists.

    # helper: avoid codes in window (t, t+HOLD]
    def avoid_codes_in_window(t: str, t_end: str) -> set[str]:
        """codes with big unlock event date in (t, t_end]."""
        acc: set[str] = set()
        # events sorted by date; iterate window
        for ed in big_dates_sorted:
            if ed <= t:
                continue
            if ed > t_end:
                break
            acc |= big_by_date[ed]
        return acc

    # ---- non-overlapping periods (headline portfolio BHAR) ----
    # build non-overlapping 20-day blocks from first testable date
    periods: list[tuple[str, str]] = []
    if testable:
        i = cal_idx[testable[0]]
        while i + HOLD < len(calendar):
            t = calendar[i]
            if t > testable[-1]:
                break
            t_end = calendar[i + HOLD]
            periods.append((t, t_end))
            i += HOLD
    print(f"\nnon-overlapping {HOLD}-day periods: {len(periods)}")
    for t, te in periods:
        print(f"  {t} -> {te}")

    def stock_forward_ret(dmap: dict[str, dict], t_idx: int, t: str) -> float | None:
        """close[t+HOLD or last avail]/close[t]-1. None if no forward bar."""
        bar_t = dmap.get(t)
        if bar_t is None or (bar_t.get("close") is None) or bar_t["close"] <= 0:
            return None
        # find last bar in (t, t+HOLD]
        end_idx = min(t_idx + HOLD, len(calendar) - 1)
        last_bar = None
        for j in range(t_idx + 1, end_idx + 1):
            b = dmap.get(calendar[j])
            if b is not None and b.get("close") is not None and b["close"] > 0:
                last_bar = b
        if last_bar is None:
            return None
        return last_bar["close"] / bar_t["close"] - 1.0

    def stock_size(dmap: dict[str, dict], t_idx: int) -> float | None:
        """mean amount over trailing SIZE_LOOKBACK days (in 元)."""
        start_idx = max(0, t_idx - SIZE_LOOKBACK)
        amts = []
        for j in range(start_idx, t_idx):
            b = dmap.get(calendar[j])
            if b is not None and b.get("amount") is not None and b["amount"] > 0:
                amts.append(b["amount"])
        if len(amts) < 5:  # need >=5 valid days
            return None
        return sum(amts) / len(amts)

    # ---- compute per-period portfolio returns + size deciles ----
    period_results: list[dict] = []
    for t, t_end in periods:
        ti = cal_idx[t]
        avoided_set = avoid_codes_in_window(t, t_end)
        # universe = codes with bar at t
        rows: list[tuple[str, float, float, int]] = []  # (code, fwd_ret, size, avoid)
        for code, dmap in code_map.items():
            fr = stock_forward_ret(dmap, ti, t)
            sz = stock_size(dmap, ti)
            if fr is None or sz is None:
                continue
            av = 1 if code in avoided_set else 0
            rows.append((code, fr, sz, av))
        if not rows:
            continue
        # size deciles on full universe
        rows_by_size = sorted(rows, key=lambda r: r[2])
        n = len(rows_by_size)
        decile_labels = [min(9, int(i * 10 / n)) for i in range(n)]  # 0..9
        # portfolio returns
        full_rets = [r[1] for r in rows]
        avoid_rets = [r[1] for r in rows if r[3] == 0]  # non-avoided = avoidance universe
        avoided_rets = [r[1] for r in rows if r[3] == 1]  # the removed stocks
        full_ret = sum(full_rets) / len(full_rets)
        avoid_ret = sum(avoid_rets) / len(avoid_rets) if avoid_rets else full_ret
        avoided_ret = sum(avoided_rets) / len(avoided_rets) if avoided_rets else None
        spread = avoid_ret - full_ret
        # size-matched: within each decile, avoid_ret - full_ret
        decile_spreads: list[float] = []
        for d in range(10):
            idxs = [i for i, lb in enumerate(decile_labels) if lb == d]
            if not idxs:
                continue
            dec_full = [rows_by_size[i][1] for i in idxs]
            dec_avoid = [rows_by_size[i][1] for i in idxs if rows_by_size[i][3] == 0]
            if not dec_avoid:
                continue
            df = sum(dec_full) / len(dec_full)
            da = sum(dec_avoid) / len(dec_avoid)
            decile_spreads.append(da - df)
        size_matched_spread = sum(decile_spreads) / len(decile_spreads) if decile_spreads else None
        frac_avoided = len(avoided_rets) / len(rows) if rows else 0
        period_results.append(
            {
                "t": t,
                "t_end": t_end,
                "n_universe": len(rows),
                "n_avoided": len(avoided_rets),
                "frac_avoided": frac_avoided,
                "full_ret": full_ret,
                "avoid_ret": avoid_ret,
                "avoided_ret": avoided_ret,
                "spread": spread,
                "size_matched_spread": size_matched_spread,
                "n_deciles": len(decile_spreads),
            }
        )

    # ---- aggregate headline ----
    print("\n" + "=" * 78)
    print("HEADLINE: 非重叠 20-day 周期组合级对比")
    print("=" * 78)
    if not period_results:
        print("  无周期数据")
    else:
        print(
            f"\n{'t':<12}{'n_uni':>7}{'n_avd':>7}{'frac':>7}"
            f"{'full%':>9}{'avoid%':>9}{'avoided%':>10}"
            f"{'spread%':>9}{'sizeM%':>9}"
        )
        cum_full = 1.0
        cum_avoid = 1.0
        for p in period_results:
            cum_full *= 1 + p["full_ret"]
            cum_avoid *= 1 + p["avoid_ret"]
            sm = p["size_matched_spread"]
            print(
                f"{p['t']:<12}{p['n_universe']:>7}{p['n_avoided']:>7}"
                f"{p['frac_avoided'] * 100:>6.1f}%"
                f"{p['full_ret'] * 100:>8.3f}{p['avoid_ret'] * 100:>8.3f}"
                f"{(p['avoided_ret'] or 0) * 100:>9.3f}"
                f"{p['spread'] * 100:>8.3f}"
                f"{(sm or 0) * 100:>8.3f}"
            )
        print(f"\n  cumulative full  BHAR = {(cum_full - 1) * 100:+.3f}%")
        print(f"  cumulative avoid BHAR = {(cum_avoid - 1) * 100:+.3f}%")
        print(f"  cumulative spread    = {(cum_avoid - cum_full) * 100:+.3f}%")

        spreads = [p["spread"] for p in period_results]
        sm_spreads = [p["size_matched_spread"] for p in period_results if p["size_matched_spread"] is not None]
        n_per = len(spreads)
        mean_sp = sum(spreads) / n_per
        std_sp = statistics.pstdev(spreads) if n_per > 1 else 0.0
        se_sp = std_sp / sqrt(n_per) if n_per > 0 else 0.0
        t_sp = mean_sp / se_sp if se_sp > 0 else 0.0
        med_sp = statistics.median(spreads)
        wr_sp = sum(1 for s in spreads if s > 0) / n_per
        # size-matched stats
        mean_sm = sum(sm_spreads) / len(sm_spreads) if sm_spreads else 0.0
        std_sm = statistics.pstdev(sm_spreads) if len(sm_spreads) > 1 else 0.0
        se_sm = std_sm / sqrt(len(sm_spreads)) if sm_spreads else 0.0
        t_sm = mean_sm / se_sm if se_sm > 0 else 0.0

        # cost: avoided fraction × round-trip cost per period
        avg_frac_avd = sum(p["frac_avoided"] for p in period_results) / n_per
        cost_per_period = avg_frac_avd * COST_RT
        net_sp = mean_sp - cost_per_period

        # two-sided p on per-period spread
        p_raw_sp = (1 - erf(abs(t_sp) / sqrt(2))) if True else 1.0
        p_bonf_sp = min(1.0, p_raw_sp * N_TESTS_BONF)

        print(f"\n  per-period spread (avoidance - full):")
        print(
            f"    n_periods={n_per} mean={mean_sp * 100:+.4f}% median={med_sp * 100:+.4f}% "
            f"WR(spread>0)={wr_sp * 100:.1f}% std={std_sp * 100:.4f}%"
        )
        print(f"    t={t_sp:.3f} p_two_sided={p_raw_sp:.4f} Bonf(×{N_TESTS_BONF})={p_bonf_sp:.4f}")
        print(
            f"    gross spread mean={mean_sp * 100:+.4f}% | cost/period={cost_per_period * 100:.4f}% "
            f"(frac_avd={avg_frac_avd * 100:.1f}%) | net={net_sp * 100:+.4f}%"
        )
        print(f"\n  R12 size-matched spread (decile-内, 跨decile等权):")
        print(f"    n_periods={len(sm_spreads)} mean={mean_sm * 100:+.4f}% std={std_sm * 100:.4f}% t={t_sm:.3f}")
        sm_pos = sum(1 for s in sm_spreads if s > 0)
        print(f"    positive periods: {sm_pos}/{len(sm_spreads)}")

        # walk-forward: split periods in half
        wf_train = spreads[: n_per // 2]
        wf_test = spreads[n_per // 2 :]
        wf_train_ev = sum(wf_train) / len(wf_train) if wf_train else 0.0
        wf_test_ev = sum(wf_test) / len(wf_test) if wf_test else 0.0
        print(f"\n  walk-forward (周期分半):")
        print(f"    train({len(wf_train)}p)={wf_train_ev * 100:+.4f}%  test({len(wf_test)}p)={wf_test_ev * 100:+.4f}%")

        # save headline for daily-panel section
        headline = {
            "n_periods": n_per,
            "mean_spread": mean_sp,
            "median_spread": med_sp,
            "wr_spread": wr_sp,
            "t_spread": t_sp,
            "p_raw": p_raw_sp,
            "p_bonf": p_bonf_sp,
            "net_spread": net_sp,
            "cost_per_period": cost_per_period,
            "cum_full": cum_full - 1,
            "cum_avoid": cum_avoid - 1,
            "cum_spread": cum_avoid - cum_full,
            "size_matched_mean": mean_sm,
            "size_matched_t": t_sm,
            "wf_train_ev": wf_train_ev,
            "wf_test_ev": wf_test_ev,
            "n_testable_days": len(testable),
        }

    # ---- DAILY PANEL Fama-MacBeth (R12 size-controlled inference, more power) ----
    print("\n" + "=" * 78)
    print(f"DAILY PANEL Fama-MacBeth: forward20d_ret ~ avoid + log(size)")
    print(f"(控 size, HAC t, n_days 充足 — R12 强化版)")
    print("=" * 78)
    # for each testable date t: cross-section regression fwd_ret = a + b*avoid + c*log(size)
    # collect daily b (avoid coefficient). Then NW-HAC t on the b series.
    import math

    daily_b: list[tuple[str, float, float, float, int, int]] = []  # (t, b_avoid, b_size, intercept, n, n_avd)
    for t in testable:
        ti = cal_idx[t]
        t_end = calendar[ti + HOLD]
        avoided_set = avoid_codes_in_window(t, t_end)
        xs_avoid: list[int] = []
        xs_logsz: list[float] = []
        ys: list[float] = []
        for code, dmap in code_map.items():
            fr = stock_forward_ret(dmap, ti, t)
            sz = stock_size(dmap, ti)
            if fr is None or sz is None or sz <= 0:
                continue
            xs_avoid.append(1 if code in avoided_set else 0)
            xs_logsz.append(math.log(sz))
            ys.append(fr)
        n = len(ys)
        n_avd = sum(xs_avoid)
        if n < 20 or n_avd < 2:
            continue
        # demean avoid & logsz (within-day), then b = sum(d_avoid*d_y)/sum(d_avoid^2) [partial]
        # use OLS with intercept on [avoid, logsz]
        my = sum(ys) / n
        ma = sum(xs_avoid) / n
        ms = sum(xs_logsz) / n
        # regress y on (avoid - ma, logsz - ms): solve normal equations 2x2
        da = [a - ma for a in xs_avoid]
        ds = [s - ms for s in xs_logsz]
        dy = [y - my for y in ys]
        s_aa = sum(a * a for a in da)
        s_ss = sum(s * s for s in ds)
        s_as = sum(a * s for a, s in zip(da, ds))
        s_ay = sum(a * y for a, y in zip(da, dy))
        s_sy = sum(s * y for s, y in zip(ds, dy))
        det = s_aa * s_ss - s_as * s_as
        if abs(det) < 1e-20:
            continue
        b_avoid = (s_ss * s_ay - s_as * s_sy) / det
        b_size = (s_aa * s_sy - s_as * s_ay) / det
        intercept = my - b_avoid * ma - b_size * ms
        daily_b.append((t, b_avoid, b_size, intercept, n, n_avd))

    if daily_b:
        bs = [r[1] for r in daily_b]
        n_days = len(bs)
        mean_b = sum(bs) / n_days
        # Newey-West HAC with lag = HOLD (overlap window)
        lag = min(HOLD, n_days - 1)
        var0 = sum((b - mean_b) ** 2 for b in bs) / n_days
        nw_var = var0
        for l in range(1, lag + 1):
            w = 1 - l / (lag + 1)
            cov_l = sum((bs[i] - mean_b) * (bs[i + l] - mean_b) for i in range(n_days - l)) / n_days
            nw_var += 2 * w * cov_l
        nw_se = sqrt(max(nw_var, 1e-30) / n_days) if n_days > 0 else 0.0
        nw_t = mean_b / nw_se if nw_se > 0 else 0.0
        p_raw_panel = 1 - erf(abs(nw_t) / sqrt(2))
        p_bonf_panel = min(1.0, p_raw_panel * N_TESTS_BONF)
        med_b = statistics.median(bs)
        wr_b = sum(1 for b in bs if b < 0) / n_days  # avoid coef NEGATIVE = avoided underperform = good
        avg_n = sum(r[4] for r in daily_b) / n_days
        avg_avd = sum(r[5] for r in daily_b) / n_days

        print(f"\n  daily Fama-MacBeth avoid coefficient (negative=避险有效):")
        print(f"    n_days={n_days} mean_b={mean_b * 100:+.4f}% median_b={med_b * 100:+.4f}%")
        print(f"    WR(b<0)={wr_b * 100:.1f}% std={statistics.pstdev(bs) * 100:.4f}%")
        print(
            f"    NW-HAC t(lag={lag})={nw_t:.3f} p_two_sided={p_raw_panel:.4f} Bonf(×{N_TESTS_BONF})={p_bonf_panel:.4f}"
        )
        print(f"    avg cross-section n={avg_n:.0f} avg avoided={avg_avd:.1f}")
        # size coef summary
        bsz = [r[2] for r in daily_b]
        print(f"    (size coef mean={sum(bsz) / n_days * 100:+.4f}% — size effect present if neg)")

        # walk-forward on daily panel: first/second half
        half = n_days // 2
        b_train = bs[:half]
        b_test = bs[half:]
        tr_ev = sum(b_train) / len(b_train) if b_train else 0.0
        te_ev = sum(b_test) / len(b_test) if b_test else 0.0
        print(f"    walk-forward: train({len(b_train)}d)={tr_ev * 100:+.4f}%  test({len(b_test)}d)={te_ev * 100:+.4f}%")
        panel = {
            "n_days": n_days,
            "mean_b": mean_b,
            "median_b": med_b,
            "wr_b_neg": wr_b,
            "nw_t": nw_t,
            "p_raw": p_raw_panel,
            "p_bonf": p_bonf_panel,
            "wf_train": tr_ev,
            "wf_test": te_ev,
        }
    else:
        panel = None
        print("  无面板数据")

    # ---------- R13 survivorship ----------
    print("\n" + "=" * 78)
    print("R13 SURVIVORSHIP 状态")
    print("=" * 78)
    # how many codes have full window vs partial; how many big-unlock codes missing from kline
    big_codes = set()
    for e in big_events:
        big_codes.add(e["code"])
    big_in_kline = sum(1 for c in big_codes if c in code_map)
    print(f"  big-unlock codes (event data): {len(big_codes)}")
    print(f"  big-unlock codes present in kline cache: {big_in_kline}")
    print(f"  big-unlock codes MISSING from kline: {len(big_codes) - big_in_kline}")
    # coverage of testable window by typical code
    cov_counts = []
    for dmap in code_map.values():
        cov = sum(1 for d in testable if d in dmap)
        cov_counts.append(cov)
    print(
        f"  per-code coverage of {len(testable)} testable days: "
        f"median={statistics.median(cov_counts):.0f} min={min(cov_counts)} max={max(cov_counts)}"
    )
    print(f"  -> kline 多数仅 2025-12 起 (~180 bars), 退市股缺失 (cache 偏现存股).")
    print(f"  -> 退市股缺失方向: big-unlock 后退市的股若不在 cache, full universe 偏高,")
    print(f"     使避险组对比的基准偏高 → 偏向不利信号 (conservative).")
    print(f"  -> 但若退市股集中在 big-unlock 组, 它们缺失 = avoided 组收益偏高 → 偏有利信号 (需警惕).")

    # ---------- VERDICT ----------
    print("\n" + "=" * 78)
    print("VERDICT (high-risk lens: mean>0 + Bonf PASS + R12 size-matched; median/WR 放松但报)")
    print("=" * 78)

    # Use daily panel as primary inference (n_days adequate), portfolio BHAR as headline.
    if panel and period_results:
        # primary metric: daily-panel avoid coefficient (negative=good)
        # for high-risk lens, "gross_ev" = -mean_b (avoidance edge in %), net = gross - cost
        gross_ev = -panel["mean_b"] * 100 if panel["mean_b"] < 0 else -panel["mean_b"] * 100
        # cost: fraction avoided × round-trip, scaled to the 20-day horizon (panel is 20d forward)
        avg_frac = avg_avd / avg_n if avg_n else 0
        cost = avg_frac * COST_RT * 100
        net_ev = gross_ev - cost
        median_ev = -panel["median_b"] * 100
        wr = panel["wr_b_neg"] * 100  # WR that avoid coef < 0
        day_t = panel["nw_t"]
        p_bonf = panel["p_bonf"]
        wf_test_ev = -panel["wf_test"] * 100
        n_days_v = panel["n_days"]
        n_picks_v = n_days_v  # daily cross-sections
        r12 = (
            f"size-matched (decile内): portfolio mean={headline['size_matched_mean'] * 100:+.4f}% "
            f"t={headline['size_matched_t']:.3f}; "
            f"daily-FM size-controlled NW_t={day_t:.3f} (控 log size). "
            f"非沪深300大盘. size coef mean={sum(bsz) / n_days * 100:+.4f}%"
        )

        print(f"\n  primary (daily Fama-MacBeth, size-controlled, HAC):")
        print(f"    gross_EV(avoid edge)={gross_ev:+.4f}% net_EV={net_ev:+.4f}% (cost={cost:.4f}%)")
        print(
            f"    median={median_ev:+.4f}% WR(avoid_coef<0)={wr:.1f}% "
            f"n_days={n_days_v} day_t(NW-HAC)={day_t:.3f} Bonf={p_bonf:.4f}"
        )
        print(f"    wf test_ev={wf_test_ev:+.4f}%")
        print(
            f"  portfolio BHAR headline: n_periods={headline['n_periods']} "
            f"cum_spread={headline['cum_spread'] * 100:+.3f}% "
            f"per-period mean={headline['mean_spread'] * 100:+.4f}%"
        )

        # verdict cascade (high-risk lens)
        v = "edge-confirmed"
        reasons = []
        # mean edge positive?
        if gross_ev <= 0:
            v = "falsified"
            reasons.append(f"gross_EV={gross_ev:.4f}% <= 0 (避险无收益, big-unlock股不跑输)")
        if n_days_v < 60:
            if v != "falsified":
                v = "underpowered"
                reasons.append(f"n_days={n_days_v} < 60 (但实际 {n_days_v} 充足)")
        if p_bonf >= ALPHA and v != "falsified":
            v = "falsified"
            reasons.append(f"Bonf p={p_bonf:.4f} >= {ALPHA} (不显著)")
        if net_ev <= 0 and v not in ("falsified",):
            v = "falsified"
            reasons.append(f"net_EV={net_ev:.4f}% <= 0 (cost 吃掉 gross)")
        # walk-forward
        if panel["wf_test"] >= 0 and v not in ("falsified",):
            if panel["wf_train"] < 0:  # train half had avoid<0 (good), test half lost it
                v = "exploratory"
                reasons.append(
                    f"wf: train={-panel['wf_train'] * 100:+.4f}% test={-panel['wf_test'] * 100:+.4f}% (test半消失)"
                )
            else:
                v = "exploratory"
                reasons.append(f"wf test_ev={wf_test_ev:+.4f}% <= 0")
        if v == "edge-confirmed":
            reasons.append(f"all gates pass: gross+net>0, Bonf<{ALPHA}, wf test retains edge")

        print(f"\n  -> VERDICT: {v}")
        for r in reasons:
            print(f"     - {r}")
        verdict = v
        key_finding = (
            f"解禁避险组合: daily-FM avoid系数 mean={panel['mean_b'] * 100:+.4f}% "
            f"(负=避险有效) NW-HAC t={day_t:.3f} Bonf p={p_bonf:.4f} n_days={n_days_v}; "
            f"组合级 BHAR cum_spread={headline['cum_spread'] * 100:+.3f}% over {headline['n_periods']} 非重叠周期; "
            f"R12 size-matched portfolio t={headline['size_matched_t']:.3f}; "
            f"verdict={v}. "
            f"窗口=2025-12~2026-09 (~9月, lockup数据仅此期, 非2024-2026)."
        )
    else:
        verdict = "underpowered"
        gross_ev = net_ev = median_ev = wr = day_t = p_bonf = wf_test_ev = 0.0
        n_days_v = n_picks_v = 0
        r12 = "no data"
        key_finding = "无足够数据"

    print("\n" + "=" * 78)
    print("SUMMARY (machine-readable below)")
    print("=" * 78)
    print(
        json.dumps(
            {
                "verdict": verdict,
                "headline": headline if "headline" in dir() else None,
                "panel": panel,
                "key_finding": key_finding,
                "r12": r12 if "r12" in dir() else None,
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
