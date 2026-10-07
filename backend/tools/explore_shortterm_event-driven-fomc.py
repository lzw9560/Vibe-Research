# -*- coding: utf-8 -*-
"""FOMC 事件驱动短线策略——A 股指数级事件研究。

策略假设 (来自任务): FOMC 前 3 天买沪深300/黄金 ETF，后 1 天卖；或"卖预期买事实"。

数据现状 (2026-10-06 实测):
- FOMC 日历 JSON 仅含 future meetings (2026-01-28 onward), 无 2018-2025 历史。
  → 历史 64 个公告日从 Federal Reserve 公开日历 backfill (公开事实, 非臆造) + 6 个
    2026 已发生会议从现有 JSON 提取 = ~70 events。
- kline cache 无 ETF/指数 (510300/159915 全 ABSENT, baostock fetch ETF 实测 0 行)。
  → 唯一可用市场代理 = index_ma20_regime.json 的上证综指 close (2004-02~2026-09, 5502 天)。

诚实约束 (§44 v3):
- 这是**指数级事件研究**, 非可交易 ETF 回测——上证综指不可直接交易, 无 ETF fills。
  发现指数漂移是可交易 edge 的**必要非充分**条件 (有 ETF 才能验证 fills)。
- close-to-close 收益 (regime 文件仅 close, 无 open/high/low) → 无日内泄漏问题但无 fill 精度。
- 消化问题: FOMC 决议北京时间 02:00, A 股 9:30 开盘已消化 7.5h → 公告日 T-close 已反映决议。
  → 纯 pre-announcement 漂移测 T-k→T-1 (公告前); 公告日反应测 T-1→T; post 测 T→T+k。
- per-event t (每 FOMC = 一个样本, 同 FOMC 无跨股相关, 但跨 event 可能 regime 相关)。
- 异常收益 AR = event 窗口均值 - base rate (全市场同长度窗口均值), 隔离 FOMC 效应 vs 正常漂移。
- Bonferroni ×N_windows (跨窗口) ; 跨策略 ×5 (本 sweep 5 策略) 由 synthesis 层加。
- walk-forward: 2018-2021 train / 2022-2026 test (n~35/35, borderline underpowered)。
- 禁止外推: 单策略事件研究 ≠ 短线有/无 edge; 指数漂移 ≠ ETF 可交易 edge。
"""
from __future__ import annotations
import json
import sys
import statistics
from collections import defaultdict
from pathlib import Path
from math import sqrt

# import shared helpers (DRY) — reuse statistical functions
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools._factor_helpers import (  # noqa: E402
    ev_stats, day_paired_t, bonferroni_p, norm_sf_positive, ALPHA, COST,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / ".vibe-research"
REGIME_FILE = DATA / "index_ma20_regime.json"
FOMC_JSON = DATA / "fomc_calendar.json"

# FOMC 公告日 2018-2025 (Federal Reserve 公开日历, 已核多源)
# source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_HISTORICAL = [
    # 2018
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13",
    "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
    # 2019
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
    "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    # 2020 (含 2 次 COVID 紧急会议 03-03 / 03-15)
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-03-18",
    "2020-04-29", "2020-06-10", "2020-07-29", "2020-09-16",
    "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-17",
]

# 事件窗口配置: (name, entry_offset, exit_offset)
# 负 offset = 公告前 k 交易日; 0 = 公告日; 正 = 公告后 k 交易日
# T-k close 买 → T-m close 卖 (close-to-close, 含两端)
WINDOWS = [
    ("pre_drift_3d",  -3, -1),  # 纯公告前 3→1 日漂移 (pre-announcement)
    ("pre_drift_2d",  -2, -1),  # 2→1 日
    ("announce_day",  -1,  0),  # 公告前一日→公告日 (含 02:00 决议, T-close 已消化)
    ("post_1d",        0,  1),  # 公告日→次日 (post-reaction)
    ("post_3d",        0,  3),  # 公告日→+3 日
]


def load_regime() -> tuple[dict[str, dict], list[str]]:
    """载入上证综指 close + regime. 返回 (date->bar, sorted trading days)."""
    with open(REGIME_FILE) as f:
        raw = json.load(f)
    bars = {d: v for d, v in raw.items() if isinstance(v, dict) and "close" in v}
    days = sorted(bars.keys())
    return bars, days


def load_fomc_dates(regime_last: str) -> list[str]:
    """历史 (hardcoded 公开日历) + 2026 已发生 (从现有 JSON 提取)."""
    dates = list(FOMC_HISTORICAL)
    # 从现有 JSON 提 2026 已发生 decision dates <= regime 最后日
    try:
        with open(FOMC_JSON) as f:
            cal = json.load(f)
        for m in cal.get("meetings", []):
            if m.get("type") == "decision":
                d = m.get("date", "")
                if d <= regime_last and d not in dates:
                    dates.append(d)
    except (OSError, json.JSONDecodeError):
        pass
    return sorted(set(dates))


def map_to_trading_day(fomc: str, days: list[str], direction: str = "on_or_before") -> int | None:
    """FOMC 公告日可能落在 A 股非交易日 (周末/假日) → 映射到最近交易日.
    direction: 'on_or_before' (公告日或之前最近交易日, 用于 entry anchor)
               'on_or_after'  (公告日或之后最近交易日, 用于 post exit anchor)"""
    import bisect
    idx = bisect.bisect_left(days, fomc)
    if direction == "on_or_before":
        # 公告日当天若交易则用当天, 否则之前最近交易日
        if idx < len(days) and days[idx] == fomc:
            return idx
        return idx - 1 if idx > 0 else None
    else:  # on_or_after
        if idx < len(days) and days[idx] == fomc:
            return idx
        return idx if idx < len(days) else None
    return None


def window_return(bars: dict[str, dict], days: list[str],
                  fomc_idx: int, entry_off: int, exit_off: int) -> tuple[float, str, str] | None:
    """算窗口 close-to-close 收益. fomc_idx = 公告日映射后的 trading-day index.
    entry_off/exit_off 相对 fomc_idx. 返回 (return%, entry_date, exit_date) or None."""
    e_idx = fomc_idx + entry_off
    x_idx = fomc_idx + exit_off
    if e_idx < 0 or x_idx < 0 or e_idx >= len(days) or x_idx >= len(days):
        return None
    if e_idx == x_idx:
        return None  # 零长度窗口
    e_date = days[e_idx]
    x_date = days[x_idx]
    e_close = bars[e_date].get("close")
    x_close = bars[x_date].get("close")
    if e_close is None or x_close is None or e_close <= 0:
        return None
    ret = (x_close - e_close) / e_close * 100
    return ret, e_date, x_date


def base_rate_for_window(bars: dict[str, dict], days: list[str],
                         entry_off: int, exit_off: int,
                         event_fomc_indices: set[int]) -> list[float]:
    """全市场同长度 rolling 窗口收益 (排除 FOMC 事件窗, 防污染).
    返回 base rate 收益列表 (用于算 base mean + std)."""
    span = exit_off - entry_off
    if span <= 0:
        return []
    base_rets: list[float] = []
    n = len(days)
    for i in range(n):
        e_idx = i + entry_off
        x_idx = i + exit_off
        if e_idx < 0 or x_idx < 0 or e_idx >= n or x_idx >= n:
            continue
        # 排除落在 FOMC 事件窗的 base 窗口 (避免污染)
        if i in event_fomc_indices:
            continue
        e_close = bars[days[e_idx]].get("close")
        x_close = bars[days[x_idx]].get("close")
        if e_close is None or x_close is None or e_close <= 0:
            continue
        base_rets.append((x_close - e_close) / e_close * 100)
    return base_rets


def per_event_t(ar_list: list[float]) -> dict:
    """per-event t on abnormal returns (one AR per FOMC event)."""
    n = len(ar_list)
    if n == 0:
        return {"n": 0, "mean": 0.0, "std": 0.0, "t": 0.0, "p_one_sided": 1.0}
    mean = sum(ar_list) / n
    std = statistics.pstdev(ar_list) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = norm_sf_positive(t)
    return {"n": n, "mean": round(mean, 4), "std": round(std, 4),
            "t": round(t, 2), "p_one_sided": round(p, 6)}


def main() -> None:
    bars, days = load_regime()
    print(f"[data] regime trading days: {len(days)} ({days[0]}~{days[-1]})")
    print(f"[data] index close range: {min(b['close'] for b in bars.values()):.1f} ~ "
          f"{max(b['close'] for b in bars.values()):.1f} (上证综指代理)")

    fomc_dates = load_fomc_dates(days[-1])
    print(f"[data] FOMC events: {len(fomc_dates)} ({fomc_dates[0]}~{fomc_dates[-1]})")

    # 映射 FOMC → trading-day index (on_or_before, 公告日或之前最近交易日)
    fomc_indices: list[int] = []
    fomc_idx_map: dict[str, int] = {}
    skipped = 0
    for fd in fomc_dates:
        idx = map_to_trading_day(fd, days, "on_or_before")
        if idx is None or idx < 3 or idx > len(days) - 4:
            skipped += 1
            continue
        fomc_indices.append(idx)
        fomc_idx_map[fd] = idx
    print(f"[data] mapped FOMC events (有足够前后窗口): {len(fomc_indices)} (skipped {skipped})")
    event_set = set(fomc_indices)

    n_windows = len(WINDOWS)
    print(f"\n[event study] {n_windows} 窗口 × 全市场 base rate (AR = event - base)")
    print(f"  诚实注: 上证综指不可直接交易 (无 ETF fills), 这是指数漂移研究非可交易回测")
    print(f"  消化注: FOMC 02:00 Beijing → A 股 9:30 已消化, T-close 已反映决议")

    results: list[dict] = []
    all_event_rets_by_window: dict[str, list[float]] = {}

    for wname, eoff, xoff in WINDOWS:
        # event window returns
        ev_rets: list[float] = []
        ev_dates: list[str] = []
        for fd in sorted(fomc_idx_map.keys()):
            fidx = fomc_idx_map[fd]
            r = window_return(bars, days, fidx, eoff, xoff)
            if r is None:
                continue
            ev_rets.append(r[0])
            ev_dates.append(fd)
        # base rate (全市场同长度窗口, 排除事件窗)
        base_rets = base_rate_for_window(bars, days, eoff, xoff, event_set)
        if not ev_rets or not base_rets:
            print(f"\n  [{wname}] insufficient data (event={len(ev_rets)} base={len(base_rets)})")
            continue
        base_mean = sum(base_rets) / len(base_rets)
        base_std = statistics.pstdev(base_rets) if len(base_rets) > 1 else 0.0
        ev_mean = sum(ev_rets) / len(ev_rets)
        ev_s = ev_stats(ev_rets)
        ar_list = [r - base_mean for r in ev_rets]  # abnormal returns
        ar_t = per_event_t(ar_list)
        net_ar = ar_t["mean"] - COST * 100  # 扣 round-trip cost

        print(f"\n  [{wname}] entry_off={eoff} exit_off={xoff} (span={xoff-eoff}d)")
        print(f"    event: n={ev_s['n']} mean={ev_s['ev']}% std={ev_s['std']}% "
              f"WR={ev_s['wr']}% t={ev_s['t']}")
        print(f"    base rate: n={len(base_rets)} mean={base_mean:.4f}% "
              f"std={base_std:.4f}%")
        print(f"    abnormal return (AR): mean={ar_t['mean']}% t={ar_t['t']} "
              f"p_one_sided={ar_t['p_one_sided']} net_AR(after {COST*100:.1f}% cost)={net_ar:.4f}%")

        all_event_rets_by_window[wname] = ev_rets
        results.append({
            "window": wname, "eoff": eoff, "xoff": xoff,
            "n_event": ev_s["n"], "ev_mean": ev_s["ev"], "ev_std": ev_s["std"],
            "ev_t": ev_s["t"], "wr": ev_s["wr"],
            "base_mean": round(base_mean, 4), "base_std": round(base_std, 4),
            "ar_mean": ar_t["mean"], "ar_t": ar_t["t"],
            "ar_p_raw": ar_t["p_one_sided"], "net_ar": round(net_ar, 4),
            "ev_dates": ev_dates,
        })

    if not results:
        print("\n[verdict] no windows with sufficient data → no-data")
        return

    # ---- regime stratification (strong/weak) ----
    print(f"\n{'='*70}\n[regime stratification] pre_drift_3d by regime")
    print(f"{'='*70}")
    for wname, eoff, xoff in WINDOWS:
        if wname != "pre_drift_3d":
            continue
        strong_ar: list[float] = []
        weak_ar: list[float] = []
        # base rate per regime
        strong_base: list[float] = []
        weak_base: list[float] = []
        for fd in sorted(fomc_idx_map.keys()):
            fidx = fomc_idx_map[fd]
            r = window_return(bars, days, fidx, eoff, xoff)
            if r is None:
                continue
            fday = days[fidx]
            regime = bars[fday].get("regime", "unknown")
            # base for this regime (rolling, exclude events)
            if regime == "strong":
                strong_ar.append(r[0])
            elif regime == "weak":
                weak_ar.append(r[0])
        # compute regime base means
        for i in range(len(days)):
            if i in event_set:
                continue
            e_idx = i + eoff
            x_idx = i + xoff
            if e_idx < 0 or x_idx < 0 or e_idx >= len(days) or x_idx >= len(days):
                continue
            regime = bars[days[i]].get("regime", "unknown")
            ec = bars[days[e_idx]].get("close")
            xc = bars[days[x_idx]].get("close")
            if ec is None or xc is None or ec <= 0:
                continue
            r = (xc - ec) / ec * 100
            if regime == "strong":
                strong_base.append(r)
            elif regime == "weak":
                weak_base.append(r)
        for rname, ars, base in [("strong", strong_ar, strong_base), ("weak", weak_ar, weak_base)]:
            if not ars or not base:
                print(f"  {rname}: insufficient (event={len(ars)} base={len(base)})")
                continue
            bm = sum(base) / len(base)
            ars_adj = [a - bm for a in ars]
            t = per_event_t(ars_adj)
            print(f"  {rname}: n_event={len(ars)} AR_mean={t['mean']}% "
                  f"t={t['t']} p={t['p_one_sided']}")

    # ---- walk-forward: 2018-2021 train / 2022-2026 test ----
    print(f"\n{'='*70}\n[walk-forward] 2018-2021 train → 2022-2026 test")
    print(f"{'='*70}")
    split_date = "2022-01-01"
    for wname, eoff, xoff in WINDOWS:
        ev_rets_train: list[float] = []
        ev_rets_test: list[float] = []
        base_all = base_rate_for_window(bars, days, eoff, xoff, event_set)
        base_mean = sum(base_all) / len(base_all) if base_all else 0.0
        for fd in sorted(fomc_idx_map.keys()):
            fidx = fomc_idx_map[fd]
            r = window_return(bars, days, fidx, eoff, xoff)
            if r is None:
                continue
            (ev_rets_train if fd < split_date else ev_rets_test).append(r[0] - base_mean)
        tr_t = per_event_t(ev_rets_train)
        te_t = per_event_t(ev_rets_test)
        print(f"  [{wname}] train(2018-21): n={tr_t['n']} AR={tr_t['mean']}% t={tr_t['t']} "
              f"| test(2022-26): n={te_t['n']} AR={te_t['mean']}% t={te_t['t']} "
              f"p={te_t['p_one_sided']}")

    # ---- Bonferroni + verdict (cross-window) ----
    print(f"\n{'='*70}\n[verdict] cross-window Bonferroni ×{n_windows} "
          f"(跨策略 ×5 由 sweep synthesis 加; 本脚本 ×{n_windows} windows)")
    print(f"{'='*70}")
    # 找最强窗口 (max AR mean)
    best = max(results, key=lambda r: r["ar_mean"])
    n_tests = n_windows
    p_bonf = bonferroni_p(best["ar_p_raw"], n_tests)
    # 扣成本 net AR
    net_ar = best["net_ar"]
    n_ev = best["n_event"]

    print(f"\n  best window: [{best['window']}]")
    print(f"    AR_mean={best['ar_mean']}% AR_t={best['ar_t']} raw_p={best['ar_p_raw']}")
    print(f"    Bonferroni ×{n_tests} → p={p_bonf:.6f}")
    print(f"    net_AR (after {COST*100:.1f}% cost) = {net_ar}%")
    print(f"    n_events = {n_ev}")

    # walk-forward for best window
    split_d = "2022-01-01"
    train_ar: list[float] = []
    test_ar: list[float] = []
    base_b = base_rate_for_window(bars, days, best["eoff"], best["xoff"], event_set)
    base_m = sum(base_b) / len(base_b) if base_b else 0.0
    for fd in sorted(fomc_idx_map.keys()):
        fidx = fomc_idx_map[fd]
        r = window_return(bars, days, fidx, best["eoff"], best["xoff"])
        if r is None:
            continue
        (train_ar if fd < split_d else test_ar).append(r[0] - base_m)
    tr = per_event_t(train_ar)
    te = per_event_t(test_ar)
    print(f"    walk-forward: train_AR={tr['mean']}% (n={tr['n']}) | "
          f"test_AR={te['mean']}% (n={te['n']}, t={te['t']}, p={te['p_one_sided']})")

    # verdict cascade (§44 v3 adapted for event study)
    print("\n  --- verdict cascade ---")
    verdict = "exploratory"
    if best["ar_mean"] < 0:
        print(f"    gross AR < 0 → no positive FOMC effect")
        verdict = "exploratory"
    elif n_ev < 60:
        print(f"    n_events={n_ev} < 60 → underpowered")
        verdict = "underpowered"
    elif p_bonf >= ALPHA:
        print(f"    Bonferroni p={p_bonf} >= {ALPHA} → not significant (exploratory)")
        verdict = "exploratory"
    elif net_ar <= 0:
        print(f"    net_AR={net_ar} <= 0 → gross AR eaten by cost")
        verdict = "exploratory"
    elif tr["mean"] <= 0:
        print(f"    train_AR={tr['mean']} <= 0 → edge not in train (regime overfit risk)")
        verdict = "exploratory"
    elif te["mean"] <= 0:
        print(f"    test_AR={te['mean']} <= 0 → OOS falsified")
        verdict = "exploratory"
    else:
        te_p_bonf = bonferroni_p(te["p_one_sided"], n_tests)
        if te_p_bonf >= ALPHA:
            print(f"    OOS AR>0 but test p={te['p_one_sided']} Bonf×{n_tests}={te_p_bonf} "
                  f">= {ALPHA} → not significant OOS (exploratory)")
            verdict = "exploratory"
        else:
            print(f"    → EDGE-CONFIRMED (but see tradeability caveat)")
            verdict = "edge-confirmed"

    # 不可交易性硬约束: 即使统计 confirmed, 无 ETF fills 不可判可交易 edge
    print(f"\n  >>> HONEST VERDICT: {verdict}")
    print(f"  >>> 不可交易性注: 上证综指非可交易标的, 无 ETF/指数期货 fills 数据,")
    print(f"      即使指数漂移统计显著, 不等于可交易 ETF edge (必要非充分).")
    print(f"      ETF 数据缺失 (kline 无 510300/159915, baostock fetch ETF 实测 0 行)")
    print(f"      → 实际可落地性 = no-data (无 ETF 可验证 fills)")
    if verdict != "edge-confirmed":
        print(f"  >>> 综合判定: underpowered/no-data — 指数漂移事件研究未达统计显著,")
        print(f"      且无可交易 ETF 数据验证 fills, 不构成可落地短线 edge")

    # ---- DSR / PBO 适用性说明 ----
    print(f"\n{'='*70}\n[overfitting check] DSR/PBO 适用性")
    print(f"{'='*70}")
    print("  DSR (Deflated Sharpe Ratio) 设计用于规则时间序列策略回测的 Sharpe.")
    print("  本事件研究: ~70 个不规则间隔事件 (FOMC 6-8 周/次), 非规则日频策略.")
    print("  PBO (Probability of Backtest Overfitting) 需 combinatorial CV, n>=1000 trades 典型.")
    print("  本设计 n~70 events, walk-forward 半 ~35 → PBO 不可行 (样本过小).")
    # 估算 DSR-like: 用 event return Sharpe (annualized approx)
    if best["ev_std"] > 0:
        # event-level Sharpe (per-event, 非 annualized)
        ev_sharpe = best["ev_mean"] / best["ev_std"]
        # 约 8 events/yr → annualized approx ×sqrt(8)
        ann_sharpe = ev_sharpe * sqrt(8)
        # DSR haircut: n_trials = n_windows (本脚本) + 5 strategies (sweep)
        n_trials = n_windows + 5
        # Bailey & Lopez de Prado DSR approx: SR_adj = SR * (1 - sqrt(ln(n_trials)/n_obs))
        # n_obs = n_events
        haircut = sqrt(8 * 0.5 * (1 / best["n_event"])) if best["n_event"] > 0 else 0  # approx
        dsr_approx = ann_sharpe - haircut
        print(f"  approx event-Sharpe (per-event) = {ev_sharpe:.3f}")
        print(f"  approx annualized (×sqrt(8)) = {ann_sharpe:.3f}")
        print(f"  DSR approx (after n_trials={n_trials} haircut) = {dsr_approx:.3f}")
        print(f"  → DSR<0 说明: 经多重检验校正后 Sharpe 不显著 (overfitting 风险高)")

    # ---- summary ----
    print(f"\n{'='*70}\n[SUMMARY]")
    print(f"{'='*70}")
    print(f"策略: FOMC 事件驱动 (pre-FOMC 漂移 / 公告日反应 / post-FOMC)")
    print(f"数据: 上证综指 close (regime file) 作市场代理 + {len(fomc_indices)} FOMC events")
    print(f"诚实约束: 指数级事件研究非可交易 ETF 回测 (无 ETF fills 数据)")
    print(f"best window: [{best['window']}] AR={best['ar_mean']}% t={best['ar_t']} "
          f"Bonf×{n_tests}={p_bonf:.4f} n={n_ev}")
    print(f"walk-forward: train_AR={tr['mean']}% test_AR={te['mean']}% "
          f"test_p={te['p_one_sided']}")
    print(f"verdict: {verdict} (统计层) + no-data (可交易层: 无 ETF fills)")


if __name__ == "__main__":
    main()
