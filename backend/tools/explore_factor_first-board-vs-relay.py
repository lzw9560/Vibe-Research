# -*- coding: utf-8 -*-
"""因子回测：首板 vs 接力分层 (first-board-vs-relay).

首板 (lbc=1, 今日首次涨停) vs 接力 (lbc>=2, 已连板再涨停) 分别测 close_ev。
首板=新题材启动，接力=趋势延续——机制不同，edge 可能不同。

诚实口径（P1 教训）：
- entry = T+1 open (非 T+1 close——T close 是涨停日 close, sealed, 不可买)
- 若 T+1 一字涨停 (open=low=limit-up), 跳过 (买不进)
- close_ev = (T+2 close - T+1 open) / T+1 open * 100
- stop 变体: -3% stop + R6 gap-through fill (跳空穿 stop 按 T+2 open + 滑点 0.2%)
- per-day-mean t (同日多笔聚合成 day-mean, 非 per-trade t——同日相关夸大 N)
- Bonferroni 校正 (2 subsets: first_board + relay)
- walk-forward OOS: 前半 train → 后半 test (非 in-sample 分段)

禁止外推：测了首板 vs 接力分层 ≠ 打板有/无 edge——只说这一维度。

跑法：cd backend && .venv/bin/python tools/explore_factor_first-board-vs-relay.py
"""
from __future__ import annotations
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / ".vibe-research"
KLINE_DB = DATA / "baostock_kline_cache.db"
ZT_DB = DATA / "zt_history.db"

SLIPPAGE = 0.002       # 0.2% 滑点
COST = 0.003           # round-trip cost (印花+佣金+滑点) for net EV
STOP_PCT = 0.03        # -3% stop for stop variant
ALPHA = 0.05


# ---------- data loading ----------

def load_kline_db() -> tuple[dict[str, dict[str, dict]], set[str]]:
    """从 SQLite 读 kline. 返回 (code -> {date: bar}, all_dates set)."""
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
            d = b.get("date")
            if d:
                dmap[d] = b
                all_dates.add(d)
        if dmap:
            code_map[code] = dmap
    conn.close()
    return code_map, all_dates


def load_zt() -> list[tuple[str, str, int]]:
    """返回 [(date, code, lbc)] 列表. lbc NULL/0 当 1."""
    conn = sqlite3.connect(str(ZT_DB))
    rows: list[tuple[str, str, int]] = []
    for d, code, lbc in conn.execute("SELECT date, code, lbc FROM zt_history"):
        rows.append((d, code, lbc if lbc else 1))
    conn.close()
    return rows


# ---------- helpers ----------

def limit_for_code(code: str, is_st: bool = False) -> float:
    """涨停幅度: ST 5%, 创业板(300/301)/科创板(688/689) 20%, 北交(4/8) 30%, 其他 10%.

    FIX 2026-10-06: 原用 code.startswith(("sz30","sh68")) 判 20%——但数据库 code 是
    6 位纯数字无交易所前缀 (如 "300650" 非 "sz300650"), 导致创业板+科创板全部被当
    10% limit → is_yizi_t1 用 *1.10 而非 *1.20 算涨停价 → 46 个 T+1 一字涨停 (20% 封死)
    没被跳过, 通胀 first_board EV +20%。正确: 按 6 位纯数字前缀判。
    """
    if is_st:
        return 0.05
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    if code.startswith(("4", "8")):
        return 0.30  # 北交
    return 0.10


def is_yizi_t1(t1_bar: dict, t_close: float, limit: float) -> bool:
    """T+1 一字涨停: open 和 low 都在涨停价附近 (locked, 买不进)."""
    lim_up = t_close * (1 + limit)
    o = t1_bar.get("open")
    l = t1_bar.get("low")
    if o is None or l is None or lim_up <= 0:
        return False
    return abs(o - lim_up) / lim_up < 0.005 and abs(l - lim_up) / lim_up < 0.005


# ---------- pick construction ----------

def build_picks(code_map: dict[str, dict[str, dict]],
                calendar: list[str],
                zt_rows: list[tuple[str, str, int]],
                lbc_min: int, lbc_max: int) -> list[dict]:
    """构建 picks: lbc in [lbc_min, lbc_max] 的涨停股, entry=T+1 open, exit=T+2 close.

    跳过: 无 kline / T+1 一字涨停 / T+1 或 T+2 无 bar.
    """
    date_idx = {d: i for i, d in enumerate(calendar)}
    picks: list[dict] = []
    for zt_date, code, lbc in zt_rows:
        if lbc < lbc_min or lbc > lbc_max:
            continue
        d_idx = date_idx.get(zt_date)
        if d_idx is None or d_idx + 2 >= len(calendar):
            continue  # need T+1 and T+2
        dmap = code_map.get(code)
        if not dmap:
            continue

        t_bar = dmap.get(zt_date)
        if t_bar is None or t_bar.get("close") is None:
            continue
        t_close = t_bar["close"]
        if t_close <= 0:
            continue

        t1_date = calendar[d_idx + 1]
        t2_date = calendar[d_idx + 2]
        t1_bar = dmap.get(t1_date)
        t2_bar = dmap.get(t2_date)
        if t1_bar is None or t2_bar is None:
            continue
        t1_open = t1_bar.get("open")
        t2_close = t2_bar.get("close")
        if t1_open is None or t2_close is None:
            continue
        if t1_open <= 0 or t2_close <= 0:
            continue

        # 一字 check on T+1
        is_st = t_bar.get("isST") == "1"
        limit = limit_for_code(code, is_st)
        if is_yizi_t1(t1_bar, t_close, limit):
            continue  # T+1 一字涨停, 买不进, 跳过

        picks.append({
            "code": code,
            "zt_date": zt_date,   # limit-up day (=T)
            "t1_date": t1_date,   # entry day
            "t2_date": t2_date,   # exit day
            "entry": t1_open,     # T+1 open
            "t1_bar": t1_bar,
            "t2_bar": t2_bar,
            "t_close": t_close,
            "lbc": lbc,
        })
    return picks


# ---------- close_ev (basic, no stop) ----------

def close_ev_basic(p: dict) -> float | None:
    """T+1 open 买 → T+2 close 卖. 无 stop, R6 N/A."""
    return (p["t2_bar"]["close"] - p["entry"]) / p["entry"] * 100


# ---------- stop variant with R6 gap-through fill ----------

def close_ev_stop(p: dict, stop_pct: float = STOP_PCT,
                  realistic: bool = True) -> tuple[float, str] | None:
    """-3% stop + R6 gap-through fill.

    Entry = T+1 open. Stop = entry * (1 - stop_pct).
    T+1 (entry day): if low <= stop → intraday stop (open > stop, so no gap-through).
    T+2 (exit day): if low <= stop:
      - if T+2 open <= stop → gap-through, fill at T+2 open + slippage (R6)
      - else → intraday stop, fill at stop + slippage
    If no stop hit → exit at T+2 close.
    """
    entry = p["entry"]
    stop_px = entry * (1 - stop_pct)
    slip = SLIPPAGE if realistic else 0.0

    t1 = p["t1_bar"]
    t2 = p["t2_bar"]
    t1_low = t1.get("low")
    t2_open = t2.get("open")
    t2_low = t2.get("low")
    t2_close = t2.get("close")
    if None in (t1_low, t2_open, t2_low, t2_close):
        return None

    # T+1 (entry day): check stop after entry
    if t1_low is not None and t1_low <= stop_px:
        # open = entry > stop, so intraday stop
        return (stop_px * (1 - slip) - entry) / entry * 100, "t1_intraday_stop"

    # T+2 (exit day): check stop
    if t2_low <= stop_px:
        if t2_open <= stop_px:
            # R6: gap-through → fill at T+2 open + slippage
            return (t2_open * (1 - slip) - entry) / entry * 100, "t2_gap_stop"
        else:
            # intraday stop
            return (stop_px * (1 - slip) - entry) / entry * 100, "t2_intraday_stop"

    # no stop hit → exit at T+2 close
    return (t2_close - entry) / entry * 100, "t2_close"


# ---------- stats ----------

def ev_stats(rets: list[float]) -> dict:
    n = len(rets)
    if n == 0:
        return {"n": 0, "ev": 0.0, "std": 0.0, "t": 0.0,
                "ci_lo": 0.0, "ci_hi": 0.0, "wr": 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    ci_lo = mean - 1.96 * se if se > 0 else mean
    ci_hi = mean + 1.96 * se if se > 0 else mean
    wr = sum(1 for x in rets if x > 0) / n
    return {"n": n, "ev": round(mean, 3), "std": round(std, 3),
            "t": round(t, 2), "ci_lo": round(ci_lo, 3), "ci_hi": round(ci_hi, 3),
            "wr": round(wr * 100, 1)}


def norm_sf_positive(t: float) -> float:
    """One-sided p for POSITIVE edge test: P(Z > t).
    For t<0 (negative mean) returns ~1.0 (no positive edge).
    NB: does NOT use abs(t) — direction matters for one-sided test."""
    return 0.5 * (1 - erf(t / sqrt(2)))


def day_paired_t(rets_by_date: dict[str, list[float]]) -> dict:
    """Per-day-mean t-test: 同日多笔聚合成 day-mean, t on day-means."""
    day_means: list[float] = []
    for d, rs in rets_by_date.items():
        if rs:
            day_means.append(sum(rs) / len(rs))
    n = len(day_means)
    if n == 0:
        return {"n_days": 0, "mean": 0.0, "std": 0.0, "t": 0.0, "p_one_sided": 1.0}
    mean = sum(day_means) / n
    std = statistics.pstdev(day_means) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = norm_sf_positive(t)
    return {"n_days": n, "mean": round(mean, 3), "std": round(std, 3),
            "t": round(t, 2), "p_one_sided": round(p, 6)}


def bonferroni_p(p_raw: float, n_tests: int) -> float:
    return min(1.0, p_raw * n_tests)


# ---------- walk-forward ----------

def walk_forward(picks: list[dict], ret_fn) -> dict:
    """前半 train → 后半 test. 用 zt_date 排序分半."""
    if not picks:
        return {"status": "no_picks"}
    ps = sorted(picks, key=lambda p: p["zt_date"])
    dates = sorted(set(p["zt_date"] for p in ps))
    if len(dates) < 4:
        return {"status": "too_few_dates", "n_dates": len(dates)}
    mid = len(dates) // 2
    train_dates = set(dates[:mid])
    test_dates = set(dates[mid:])

    train_picks = [p for p in ps if p["zt_date"] in train_dates]
    test_picks = [p for p in ps if p["zt_date"] in test_dates]

    train_rets = [ret_fn(p) for p in train_picks]
    train_rets = [r for r in train_rets if r is not None]
    test_rets = [ret_fn(p) for p in test_picks]
    test_rets = [r for r in test_rets if r is not None]

    train_by_date: dict[str, list[float]] = defaultdict(list)
    for p in train_picks:
        r = ret_fn(p)
        if r is not None:
            train_by_date[p["zt_date"]].append(r)
    test_by_date: dict[str, list[float]] = defaultdict(list)
    for p in test_picks:
        r = ret_fn(p)
        if r is not None:
            test_by_date[p["zt_date"]].append(r)

    return {
        "status": "ok",
        "n_train": len(train_rets), "n_test": len(test_rets),
        "n_train_dates": len(train_dates), "n_test_dates": len(test_dates),
        "train_ev": ev_stats(train_rets),
        "test_ev": ev_stats(test_rets),
        "train_day_t": day_paired_t(train_by_date),
        "test_day_t": day_paired_t(test_by_date),
    }


# ---------- per-subset analysis ----------

def analyze_subset(name: str, picks: list[dict]) -> dict:
    """对一个子集跑全部分析: basic close_ev + stop variant + R6 + walk-forward."""
    print(f"\n{'=' * 70}")
    print(f"子集: {name} (n_picks={len(picks)})")
    print(f"{'=' * 70}")

    if not picks:
        print("  无 picks, 跳过")
        return {"name": name, "n_picks": 0}

    # ---- basic close_ev ----
    print(f"\n--- basic close_ev (T+1 open → T+2 close, no stop) ---")
    basic_rets = [close_ev_basic(p) for p in picks]
    basic_rets = [r for r in basic_rets if r is not None]
    basic_s = ev_stats(basic_rets)
    print(f"  n={basic_s['n']} gross_EV={basic_s['ev']}% std={basic_s['std']}% "
          f"WR={basic_s['wr']}% t={basic_s['t']} CI[{basic_s['ci_lo']},{basic_s['ci_hi']}]")
    net_basic = basic_s['ev'] - COST * 100
    print(f"  net EV (after {COST*100:.1f}% cost): {net_basic:.3f}%")

    basic_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        r = close_ev_basic(p)
        if r is not None:
            basic_by_date[p["zt_date"]].append(r)
    basic_dt = day_paired_t(basic_by_date)
    print(f"  day-paired: n_days={basic_dt['n_days']} mean={basic_dt['mean']}% "
          f"t={basic_dt['t']} p_one_sided={basic_dt['p_one_sided']}")

    # ---- stop variant with R6 ----
    print(f"\n--- stop variant (-{STOP_PCT*100:.0f}% stop + R6 gap-through fill) ---")
    stop_rets = [close_ev_stop(p) for p in picks]
    stop_rets_clean = [r[0] for r in stop_rets if r is not None]
    stop_s = ev_stats(stop_rets_clean)
    print(f"  n={stop_s['n']} gross_EV={stop_s['ev']}% std={stop_s['std']}% "
          f"WR={stop_s['wr']}% t={stop_s['t']} CI[{stop_s['ci_lo']},{stop_s['ci_hi']}]")
    net_stop = stop_s['ev'] - COST * 100
    print(f"  net EV (after cost): {net_stop:.3f}%")

    stop_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        r = close_ev_stop(p)
        if r is not None:
            stop_by_date[p["zt_date"]].append(r[0])
    stop_dt = day_paired_t(stop_by_date)
    print(f"  day-paired: n_days={stop_dt['n_days']} mean={stop_dt['mean']}% "
          f"t={stop_dt['t']} p_one_sided={stop_dt['p_one_sided']}")

    # exit reason breakdown
    reasons: dict[str, int] = defaultdict(int)
    for p in picks:
        r = close_ev_stop(p)
        if r is not None:
            reasons[r[1]] += 1
    total_r = sum(reasons.values())
    print(f"  exit reasons:")
    for rsn, cnt in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"    {rsn}: {cnt} ({cnt/max(total_r,1)*100:.1f}%)")

    # ---- R6 impact: ideal vs realistic stop ----
    print(f"\n--- R6 fill impact (ideal vs realistic stop) ---")
    ideal_rets = [close_ev_stop(p, realistic=False) for p in picks]
    ideal_rets_clean = [r[0] for r in ideal_rets if r is not None]
    si = ev_stats(ideal_rets_clean)
    sr = stop_s
    gap_count = reasons.get("t2_gap_stop", 0)
    stop_count = sum(v for k, v in reasons.items() if "stop" in k)
    print(f"  ideal EV={si['ev']}% | realistic EV={sr['ev']}% | "
          f"diff={round(si['ev']-sr['ev'],3)}% | "
          f"stops={stop_count}({stop_count/max(len(stop_rets_clean),1)*100:.1f}%) "
          f"gap_through={gap_count}({gap_count/max(stop_count,1)*100:.1f}% of stops)")

    # ---- walk-forward OOS ----
    print(f"\n--- walk-forward OOS (basic close_ev, 前半 train → 后半 test) ---")
    wf_basic = walk_forward(picks, close_ev_basic)
    if wf_basic["status"] == "ok":
        tr = wf_basic["train_ev"]
        te = wf_basic["test_ev"]
        tr_dt = wf_basic["train_day_t"]
        te_dt = wf_basic["test_day_t"]
        print(f"  train: n={tr['n']} n_dates={wf_basic['n_train_dates']} "
              f"EV={tr['ev']}% t={tr['t']} day_t={tr_dt['t']}")
        print(f"  test:  n={te['n']} n_dates={wf_basic['n_test_dates']} "
              f"EV={te['ev']}% t={te['t']} day_t={te_dt['t']} "
              f"p={te_dt['p_one_sided']}")
        decay = ((tr['ev'] - te['ev']) / abs(tr['ev']) * 100
                 if tr['ev'] != 0 else 0)
        print(f"  decay: {decay:.0f}% (train→test)")
    else:
        print(f"  {wf_basic['status']} (n_dates={wf_basic.get('n_dates', 0)})")

    print(f"\n--- walk-forward OOS (stop variant, 前半 train → 后半 test) ---")
    wf_stop = walk_forward(picks, lambda p: close_ev_stop(p)[0]
                           if close_ev_stop(p) is not None else None)
    if wf_stop["status"] == "ok":
        tr = wf_stop["train_ev"]
        te = wf_stop["test_ev"]
        tr_dt = wf_stop["train_day_t"]
        te_dt = wf_stop["test_day_t"]
        print(f"  train: n={tr['n']} n_dates={wf_basic['n_train_dates']} "
              f"EV={tr['ev']}% t={tr['t']} day_t={tr_dt['t']}")
        print(f"  test:  n={te['n']} n_dates={wf_stop['n_test_dates']} "
              f"EV={te['ev']}% t={te['t']} day_t={te_dt['t']} "
              f"p={te_dt['p_one_sided']}")
        decay = ((tr['ev'] - te['ev']) / abs(tr['ev']) * 100
                 if tr['ev'] != 0 else 0)
        print(f"  decay: {decay:.0f}% (train→test)")
    else:
        print(f"  {wf_stop['status']}")

    # ---- month distribution ----
    print(f"\n--- 月度 pick 分布 ---")
    mc: dict[str, int] = defaultdict(int)
    for p in picks:
        mc[p["zt_date"][:7]] += 1
    for mth in sorted(mc):
        print(f"  {mth}: {mc[mth]} picks")

    return {
        "name": name,
        "n_picks": len(picks),
        "basic_ev": basic_s,
        "basic_day_t": basic_dt,
        "stop_ev": stop_s,
        "stop_day_t": stop_dt,
        "r6_impact": {"ideal_ev": si['ev'], "realistic_ev": sr['ev'],
                      "diff": round(si['ev']-sr['ev'], 3),
                      "gap_through": gap_count},
        "wf_basic": wf_basic,
        "wf_stop": wf_stop,
    }


# ---------- main ----------

def main():
    print("加载数据…")
    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    zt_rows = load_zt()
    print(f"  kline codes: {len(code_map)}")
    print(f"  calendar days: {len(calendar)} ({calendar[0]} ~ {calendar[-1]})")
    print(f"  zt rows: {len(zt_rows)}")

    # 构建子集
    first_board_picks = build_picks(code_map, calendar, zt_rows, 1, 1)
    relay_picks = build_picks(code_map, calendar, zt_rows, 2, 999)
    print(f"\n构建 picks:")
    print(f"  first_board (lbc=1): {len(first_board_picks)} picks")
    print(f"  relay (lbc>=2):      {len(relay_picks)} picks")

    # 分析各子集
    fb = analyze_subset("first_board (lbc=1 首板)", first_board_picks)
    rl = analyze_subset("relay (lbc>=2 接力)", relay_picks)

    # ---- Bonferroni (2 subsets × 2 variants = 4 tests within factor) ----
    print(f"\n{'=' * 70}")
    print("Bonferroni 校正")
    print(f"{'=' * 70}")

    # Basic: 2 tests (first_board + relay)
    n_tests_basic = 2
    p_fb_basic = fb.get("basic_day_t", {}).get("p_one_sided", 1.0)
    p_rl_basic = rl.get("basic_day_t", {}).get("p_one_sided", 1.0)
    best_p_basic = min(p_fb_basic, p_rl_basic)
    bonf_basic = bonferroni_p(best_p_basic, n_tests_basic)
    best_subset_basic = ("first_board" if p_fb_basic <= p_rl_basic
                         else "relay")
    print(f"\n  basic close_ev (n_tests={n_tests_basic}):")
    print(f"    first_board: p={p_fb_basic:.6f}")
    print(f"    relay:       p={p_rl_basic:.6f}")
    print(f"    best: {best_subset_basic} raw p={best_p_basic:.6f}")
    print(f"    Bonferroni p (×{n_tests_basic}): {bonf_basic:.6f}")
    print(f"    threshold: {ALPHA / n_tests_basic:.6f}")
    print(f"    {'PASS' if bonf_basic < ALPHA else 'FAIL (not significant)'}")

    # Stop: 2 tests (first_board + relay)
    n_tests_stop = 2
    p_fb_stop = fb.get("stop_day_t", {}).get("p_one_sided", 1.0)
    p_rl_stop = rl.get("stop_day_t", {}).get("p_one_sided", 1.0)
    best_p_stop = min(p_fb_stop, p_rl_stop)
    bonf_stop = bonferroni_p(best_p_stop, n_tests_stop)
    best_subset_stop = ("first_board" if p_fb_stop <= p_rl_stop
                        else "relay")
    print(f"\n  stop variant (n_tests={n_tests_stop}):")
    print(f"    first_board: p={p_fb_stop:.6f}")
    print(f"    relay:       p={p_rl_stop:.6f}")
    print(f"    best: {best_subset_stop} raw p={best_p_stop:.6f}")
    print(f"    Bonferroni p (×{n_tests_stop}): {bonf_stop:.6f}")
    print(f"    {'PASS' if bonf_stop < ALPHA else 'FAIL (not significant)'}")

    # Cross-factor Bonferroni (7 parallel factors)
    n_cross = 7
    bonf_cross = bonferroni_p(best_p_basic, n_cross * 2)
    print(f"\n  cross-factor (×{n_cross*2} for 7 factors × 2 subsets):")
    print(f"    best raw p={best_p_basic:.6f} → Bonferroni p={bonf_cross:.6f}")
    print(f"    {'PASS' if bonf_cross < ALPHA else 'FAIL'}")

    # ---- honest verdict ----
    print(f"\n{'=' * 70}")
    print("诚实判定")
    print(f"{'=' * 70}")

    fb_ev = fb.get("basic_ev", {}).get("ev", 0)
    rl_ev = rl.get("basic_ev", {}).get("ev", 0)
    fb_t = fb.get("basic_day_t", {}).get("t", 0)
    rl_t = rl.get("basic_day_t", {}).get("t", 0)
    fb_n = fb.get("n_picks", 0)
    rl_n = rl.get("n_picks", 0)
    fb_ndays = fb.get("basic_day_t", {}).get("n_days", 0)
    rl_ndays = rl.get("basic_day_t", {}).get("n_days", 0)

    print(f"\n[first_board lbc=1 首板]")
    print(f"  n_picks={fb_n} n_days={fb_ndays}")
    print(f"  basic close_ev: EV={fb_ev}% net={fb_ev - COST*100:.3f}% "
          f"day_t={fb_t} p={p_fb_basic:.6f}")
    print(f"  Bonferroni p (×2): {bonferroni_p(p_fb_basic, 2):.6f}")
    fb_wf = fb.get("wf_basic", {})
    if fb_wf.get("status") == "ok":
        print(f"  walk-forward: train EV={fb_wf['train_ev']['ev']}% "
              f"test EV={fb_wf['test_ev']['ev']}%")

    print(f"\n[relay lbc>=2 接力]")
    print(f"  n_picks={rl_n} n_days={rl_ndays}")
    print(f"  basic close_ev: EV={rl_ev}% net={rl_ev - COST*100:.3f}% "
          f"day_t={rl_t} p={p_rl_basic:.6f}")
    print(f"  Bonferroni p (×2): {bonferroni_p(p_rl_basic, 2):.6f}")
    rl_wf = rl.get("wf_basic", {})
    if rl_wf.get("status") == "ok":
        print(f"  walk-forward: train EV={rl_wf['train_ev']['ev']}% "
              f"test EV={rl_wf['test_ev']['ev']}%")

    # 判定逻辑
    print(f"\n[判定]")

    def verdict_for(ev_gross, t_day, p_bonf, wf_status,
                    wf_train_ev, wf_test_ev, wf_test_p, n_days, net_ev, subset_name):
        """诚实判定: edge-confirmed / falsified / underpowered / exploratory."""
        print(f"\n  {subset_name}:")
        print(f"    gross_EV={ev_gross}% net_EV={net_ev}% day_t={t_day} "
              f"Bonf_p={p_bonf} n_days={n_days}")
        if wf_status == "ok":
            print(f"    walk-forward: train_EV={wf_train_ev}% test_EV={wf_test_ev}% "
                  f"test_p={wf_test_p}")

        # Falsified: negative gross EV (signal is a loser)
        if ev_gross < 0:
            print(f"    → FALSIFIED: gross EV < 0 (negative edge, loser signal)")
            return "falsified"
        # Underpowered: not enough days
        if n_days < 60:
            print(f"    → UNDERPOWERED: n_days={n_days} < 60")
            return "underpowered"
        # Not significant after Bonferroni
        if p_bonf >= ALPHA:
            print(f"    → FALSIFIED: Bonferroni p={p_bonf} >= {ALPHA} (not significant)")
            return "falsified"
        # Net EV negative (can't beat cost)
        if net_ev <= 0:
            print(f"    → FALSIFIED: net EV={net_ev}% <= 0 (gross edge eaten by cost)")
            return "falsified"
        # Walk-forward check
        if wf_status == "ok":
            if wf_test_ev <= 0:
                print(f"    → FALSIFIED: walk-forward test_EV={wf_test_ev}% <= 0")
                return "falsified"
            if wf_test_p >= ALPHA:
                print(f"    → EXPLORATORY: OOS test EV={wf_test_ev}% > 0 but "
                      f"test p={wf_test_p} >= {ALPHA} (not significant OOS)")
                return "exploratory"
            print(f"    → EDGE-CONFIRMED: gross+net EV > 0, Bonferroni PASS, "
                  f"OOS test EV={wf_test_ev}% significant (p={wf_test_p})")
            return "edge-confirmed"
        print(f"    → EXPLORATORY: walk-forward not available")
        return "exploratory"

    fb_net = fb_ev - COST * 100
    rl_net = rl_ev - COST * 100
    fb_wf_test_p = fb_wf.get("test_day_t", {}).get("p_one_sided", 1.0)
    rl_wf_test_p = rl_wf.get("test_day_t", {}).get("p_one_sided", 1.0)

    v_fb = verdict_for(fb_ev, fb_t, bonferroni_p(p_fb_basic, 2),
                       fb_wf.get("status"),
                       fb_wf.get("train_ev", {}).get("ev", 0),
                       fb_wf.get("test_ev", {}).get("ev", 0),
                       fb_wf_test_p, fb_ndays, fb_net, "first_board (lbc=1)")
    v_rl = verdict_for(rl_ev, rl_t, bonferroni_p(p_rl_basic, 2),
                       rl_wf.get("status"),
                       rl_wf.get("train_ev", {}).get("ev", 0),
                       rl_wf.get("test_ev", {}).get("ev", 0),
                       rl_wf_test_p, rl_ndays, rl_net, "relay (lbc>=2)")

    # overall
    if v_fb == "edge-confirmed" or v_rl == "edge-confirmed":
        overall = "edge-confirmed"
    elif v_fb == "underpowered" or v_rl == "underpowered":
        overall = "underpowered"
    elif v_fb == "exploratory" or v_rl == "exploratory":
        overall = "exploratory"
    else:
        overall = "edge-falsified"
    print(f"\n  OVERALL: {overall}")

    print(f"\n注: 本实验只测首板 vs 接力分层维度, "
          f"禁止外推成'打板有/无 edge'。")
    print(f"R6: stop 变体用 gap-through fill (T+2 open+slippage), "
          f"basic 无 stop R6 N/A。")
    print(f"realistic entry: T+1 open (非 T+1 close), 一字涨停跳过。")


if __name__ == "__main__":
    main()
