# -*- coding: utf-8 -*-
"""跌停打开承接 Round 2 深挖——反人性最高先验 long-only 博反弹策略。

机制：跌停=硬地板+被迫平仓耗竭+磁吸效应。板打开(close>low)=恐慌抛压枯竭→承接博反弹。
检测：low≈prev_close*(1-limit%) 且 close>low（跌停板打开，非一字跌停）。
entry=T+1 open, exit=T+2/T+5 close。long-only 散户可做（做多博反弹，不需做空）。

§44 v3 全套（过严口径）：
- realistic entry T+1 open（非 T 收盘——T 收盘 sealed，散户 T+1 才能买）
- close_ev 非 open_ev（T+1 open 买→T+k close 卖，防 T+1 日内泄漏）
- BHAR gate（vs 上证综指同期 T+1 open→T+k close，隔离 stock-specific 反弹 vs market beta）
  非除权除息教训：raw EV 正可能仅 market beta，BHAR 揭真 stock-specific edge
- per-day-mean t（同日 picks 聚 day-mean，effective N=n_days 非 n_trades）
- Bonferroni ×3（Round 2 三策略并行：ETF折溢价/大股东增持/跌停打开）
- walk-forward OOS + train_ev>0（前半 train→后半 test，非 in-sample 分段）
- is_yizi 跌停适配（T+1 一字跌停 CAN buy 非 skip——跌停=有卖无买，买单即成；
  但 tag 为维度：一字跌停=反弹失败 falling knife vs normal=反弹可能）
- R6 gap-through fill（T+1 triggered→T+2 open + 滑点；多日 stop T+2~T+5 逐日检查）
- DSR 估算（多重检验 haircut）
- 禁止外推：跌停打开单策略 ≠ 事件驱动有/无 edge ≠ 短线有/无 edge

深挖维度：
1. BHAR gate（raw EV vs market-adjusted BHAR——反弹是 stock-specific 还是 beta？）
2. 窗口对比（T+2 短反弹 vs T+5 长持有——反弹是否短命？）
3. 打开程度分桶（微开/半开/全开——恢复程度↔反弹力度？）
4. regime 分层（bull/bear/range/crisis——恐慌越深反弹越强？A 股隔夜负漂移逆风）
5. 结构断点/era（pre-2020/2020-2022/2023-2026——edge 衰减？）
6. T+1 状态（一字跌停=falling knife vs normal=反弹可能）
7. 板块类型（主板/中小/创业板/科创板——不同涨跌停幅度+散户结构）
8. 2023-2026 子条件 sweep（ANY 子条件存活 §44 v3？）
"""

from __future__ import annotations
import json
import sys
import math
import statistics
from collections import defaultdict
from functools import partial
from pathlib import Path
from math import sqrt, erf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._factor_helpers import (  # noqa: E402
    ev_stats,
    day_paired_t,
    bonferroni_p,
    walk_forward,
    verdict_for,
    norm_sf_positive,
    ALPHA,
    COST,
    SLIPPAGE,
    STOP_PCT,
    limit_for_code,
    load_kline_db,
)

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
INDEX_CACHE = DATA / "index_ohlc_cache.json"

N_CROSS_STRATEGY = 3  # Round 2 三策略并行 cross-strategy Bonferroni

# 危机窗口（透明固定，非事后调参）——同 ETF 深挖
CRISIS_WINDOWS = [
    ("2018-贸易战", "2018-03-01", "2019-01-31"),
    ("2020-COVID", "2020-02-01", "2020-04-30"),
    ("2024-1月崩盘", "2024-01-01", "2024-03-31"),
]


# ---------- data loading ----------


def load_index() -> tuple[dict[str, dict], list[str]]:
    """sh.000001 → {date: bar} + sorted calendar. 用于 BHAR benchmark + regime."""
    with open(INDEX_CACHE) as f:
        raw = json.load(f)
    bars = raw.get("sh.000001", [])
    idx_map: dict[str, dict] = {b["date"]: b for b in bars if "date" in b}
    calendar = sorted(idx_map.keys())
    return idx_map, calendar


# ---------- event detection + pick construction ----------


def board_type(code: str) -> str:
    """板块类型：main(主板)/sme(中小板)/chuangye(创业板)/kechuang(科创板)."""
    if code.startswith(("300", "301")):
        return "chuangye"
    if code.startswith(("688", "689")):
        return "kechuang"
    if code.startswith(("002", "003")):
        return "sme"
    return "main"


def is_yizi_dt(bar: dict, prev_close: float, limit: float) -> bool:
    """一字跌停：open≈high≈low≈close 在跌停价附近（locked at floor all day）.

    与 is_yizi_t1(涨停) 不同：一字跌停 CAN buy（有卖无买，买单即成），
    但表示 T+1 继续封死跌停=反弹失败 falling knife。
    """
    lim_down = prev_close * (1 - limit)
    if lim_down <= 0:
        return False
    o = bar.get("open")
    h = bar.get("high")
    l = bar.get("low")
    c = bar.get("close")
    if None in (o, h, l, c):
        return False
    tol = 0.005
    return (
        abs(o - lim_down) / lim_down < tol
        and abs(h - lim_down) / lim_down < tol
        and abs(l - lim_down) / lim_down < tol
        and abs(c - lim_down) / lim_down < tol
    )


def build_picks_limit_down_open(
    code_map: dict[str, dict[str, dict]],
    calendar: list[str],
    index_map: dict[str, dict],
    date_lo: str | None = None,
    date_hi: str | None = None,
) -> list[dict]:
    """跌停打开事件 picks. entry=T+1 open, exit=T+2/T+5 close.

    事件检测：T 日 low≈prev_close*(1-limit) 且 close>low（跌停板打开）。
    跳过：无 T+1~T+5 bar / entry<=0 / 无 prev_close。
    不跳 T+1 一字跌停（CAN buy，但 tag 为维度）。
    """
    date_idx = {d: i for i, d in enumerate(calendar)}
    picks: list[dict] = []

    for code, dmap in code_map.items():
        bars_sorted = sorted(dmap.values(), key=lambda b: b.get("date", ""))
        if len(bars_sorted) < 2:
            continue
        for i in range(1, len(bars_sorted)):
            b = bars_sorted[i]
            prev = bars_sorted[i - 1]
            prev_close = prev.get("close")
            if prev_close is None or prev_close <= 0:
                continue
            event_date = b.get("date")
            if event_date is None:
                continue
            if date_lo and event_date < date_lo:
                continue
            if date_hi and event_date > date_hi:
                continue
            low = b.get("low")
            close = b.get("close")
            if low is None or close is None or low <= 0:
                continue
            is_st = b.get("isST") == "1"
            limit = limit_for_code(code, is_st)
            lim_down = prev_close * (1 - limit)
            if lim_down <= 0:
                continue
            # 跌停板触及：low 在跌停价附近（0.5% 容差，处理复权+四舍五入）
            if abs(low - lim_down) / lim_down >= 0.005:
                continue
            # 板打开：close > low（非一字跌停）
            if close <= low:
                continue

            # 查 T+1~T+5
            di = date_idx.get(event_date)
            if di is None or di + 5 >= len(calendar):
                continue
            t1_date = calendar[di + 1]
            t2_date = calendar[di + 2]
            t3_date = calendar[di + 3]
            t4_date = calendar[di + 4]
            t5_date = calendar[di + 5]
            t1_bar = dmap.get(t1_date)
            t2_bar = dmap.get(t2_date)
            t3_bar = dmap.get(t3_date)
            t4_bar = dmap.get(t4_date)
            t5_bar = dmap.get(t5_date)
            if None in (t1_bar, t2_bar, t3_bar, t4_bar, t5_bar):
                continue
            entry = t1_bar.get("open")
            t2_close = t2_bar.get("close")
            t5_close = t5_bar.get("close")
            t1_close = t1_bar.get("close")
            if None in (entry, t2_close, t5_close, t1_close):
                continue
            if entry <= 0 or t2_close <= 0 or t5_close <= 0:
                continue

            # BHAR benchmark bars
            i_t1 = index_map.get(t1_date)
            i_t2 = index_map.get(t2_date)
            i_t5 = index_map.get(t5_date)
            if None in (i_t1, i_t2, i_t5):
                continue
            i_t1_open = i_t1.get("open")
            i_t2_close = i_t2.get("close")
            i_t5_close = i_t5.get("close")
            if None in (i_t1_open, i_t2_close, i_t5_close) or i_t1_open <= 0:
                continue

            open_degree = (close - low) / low  # 打开程度
            t1_yizi_dt = is_yizi_dt(t1_bar, close, limit)  # T+1 一字跌停

            picks.append(
                {
                    "code": code,
                    "event_date": event_date,
                    "zt_date": event_date,  # walk_forward 兼容
                    "t1_date": t1_date,
                    "t2_date": t2_date,
                    "t3_date": t3_date,
                    "t4_date": t4_date,
                    "t5_date": t5_date,
                    "prev_close": prev_close,
                    "entry": entry,
                    "t1_close": t1_close,
                    "t2_close": t2_close,
                    "t5_close": t5_close,
                    "t1_bar": t1_bar,
                    "t2_bar": t2_bar,
                    "t3_bar": t3_bar,
                    "t4_bar": t4_bar,
                    "t5_bar": t5_bar,
                    "event_close": close,
                    "event_low": low,
                    "event_high": b.get("high"),
                    "event_open": b.get("open"),
                    "open_degree": open_degree,
                    "t1_yizi_dt": t1_yizi_dt,
                    "limit": limit,
                    "is_st": is_st,
                    "board": board_type(code),
                    "i_t1_open": i_t1_open,
                    "i_t2_close": i_t2_close,
                    "i_t5_close": i_t5_close,
                }
            )
    return picks


# ---------- return functions ----------


def raw_ev_t2(p: dict) -> float:
    """散户实际 P&L% T+1 open→T+2 close（含 market beta）."""
    return (p["t2_close"] - p["entry"]) / p["entry"] * 100


def raw_ev_t5(p: dict) -> float:
    return (p["t5_close"] - p["entry"]) / p["entry"] * 100


def bhar_t2(p: dict) -> float:
    """BHAR T+2：stock T+1open→T+2close 减 market T+1open→T+2close.

    隔离 stock-specific 反弹 vs market beta。raw EV 正可能仅市场涨。
    """
    stock_ret = (p["t2_close"] - p["entry"]) / p["entry"] * 100
    mkt_ret = (p["i_t2_close"] - p["i_t1_open"]) / p["i_t1_open"] * 100
    return stock_ret - mkt_ret


def bhar_t5(p: dict) -> float:
    stock_ret = (p["t5_close"] - p["entry"]) / p["entry"] * 100
    mkt_ret = (p["i_t5_close"] - p["i_t1_open"]) / p["i_t1_open"] * 100
    return stock_ret - mkt_ret


def close_ev_stop_t2(p: dict, stop_pct: float = STOP_PCT, realistic: bool = True) -> tuple[float, str] | None:
    """T+2 -3% stop + R6 gap-through fill（与 helper 一致，适配 limit-down pick）.

    Entry=T+1 open. Stop=entry*(1-stop_pct).
    T+1 触及 stop → T+2 open 卖（T+1 不能卖）.
    T+2 触及 stop → gap-through(T+2 open<=stop) 或 intraday(T+2 open>stop).
    无 stop → T+2 close.
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
    t1_triggered = t1_low <= stop_px
    if t1_triggered:
        return (t2_open * (1 - slip) - entry) / entry * 100, "t1_trig_t2_open"
    if t2_low <= stop_px:
        if t2_open <= stop_px:
            return (t2_open * (1 - slip) - entry) / entry * 100, "t2_gap_stop"
        return (stop_px * (1 - slip) - entry) / entry * 100, "t2_intraday_stop"
    return (t2_close - entry) / entry * 100, "t2_close"


def close_ev_stop_t5(p: dict, stop_pct: float = STOP_PCT, realistic: bool = True) -> tuple[float, str] | None:
    """T+5 多日 -3% stop + R6 gap-through fill.

    逐日检查 T+1~T+5 stop。T+1 触及→T+2 open 卖（T+1 制度）。
    T+2~T+5 触及→当日 gap/intraday stop。无 stop→T+5 close。
    """
    entry = p["entry"]
    stop_px = entry * (1 - stop_pct)
    slip = SLIPPAGE if realistic else 0.0
    t1_low = p["t1_bar"].get("low")
    if t1_low is not None and t1_low <= stop_px:
        t2_open = p["t2_bar"].get("open")
        if t2_open is None:
            return None
        return (t2_open * (1 - slip) - entry) / entry * 100, "t1_trig_t2_open"
    for day_tag in ("t2", "t3", "t4", "t5"):
        bar = p[f"{day_tag}_bar"]
        d_open = bar.get("open")
        d_low = bar.get("low")
        d_close = bar.get("close")
        if None in (d_open, d_low, d_close):
            continue
        if d_low <= stop_px:
            if d_open <= stop_px:
                return (d_open * (1 - slip) - entry) / entry * 100, f"{day_tag}_gap_stop"
            return (stop_px * (1 - slip) - entry) / entry * 100, f"{day_tag}_intraday_stop"
    t5_close = p["t5_bar"].get("close")
    if t5_close is None:
        return None
    return (t5_close - entry) / entry * 100, "t5_close"


# ---------- walk-forward (event-adapted, supports index-aware ret_fn) ----------


def walk_forward_event(picks: list[dict], ret_fn) -> dict:
    """前半 train→后半 test by event_date. ret_fn: (p)->float|None."""
    if not picks:
        return {"status": "no_picks"}
    ps = sorted(picks, key=lambda p: p["event_date"])
    dates = sorted(set(p["event_date"] for p in ps))
    if len(dates) < 4:
        return {"status": "too_few_dates", "n_dates": len(dates)}
    mid = len(dates) // 2
    train_dates = set(dates[:mid])
    test_dates = set(dates[mid:])
    tr_by_date: dict[str, list[float]] = defaultdict(list)
    te_by_date: dict[str, list[float]] = defaultdict(list)
    for p in ps:
        r = ret_fn(p)
        if r is None:
            continue
        if p["event_date"] in train_dates:
            tr_by_date[p["event_date"]].append(r)
        else:
            te_by_date[p["event_date"]].append(r)
    tr_rets = [r for rs in tr_by_date.values() for r in rs]
    te_rets = [r for rs in te_by_date.values() for r in rs]
    return {
        "status": "ok",
        "n_train": len(tr_rets),
        "n_test": len(te_rets),
        "n_train_dates": len(train_dates),
        "n_test_dates": len(test_dates),
        "train_ev": ev_stats(tr_rets),
        "test_ev": ev_stats(te_rets),
        "train_day_t": day_paired_t(tr_by_date),
        "test_day_t": day_paired_t(te_by_date),
    }


# ---------- analysis (per subset: raw EV + BHAR + stop + walk-forward) ----------


def analyze_subset(
    name: str, picks: list[dict], ret_fn_raw, ret_fn_bhar, ret_fn_stop, window_label: str = "T+2", verbose: bool = True
) -> dict:
    """对一个子集跑全分析：raw EV + BHAR + stop + walk-forward."""
    if not picks:
        if verbose:
            print(f"  {name}: 无 picks")
        return {"name": name, "n": 0, "window": window_label}

    # raw EV
    raw_rets = [ret_fn_raw(p) for p in picks]
    raw_s = ev_stats(raw_rets)
    raw_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        raw_by_date[p["event_date"]].append(ret_fn_raw(p))
    raw_dt = day_paired_t(raw_by_date)

    # BHAR
    bhar_rets = [ret_fn_bhar(p) for p in picks]
    bhar_s = ev_stats(bhar_rets)
    bhar_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        bhar_by_date[p["event_date"]].append(ret_fn_bhar(p))
    bhar_dt = day_paired_t(bhar_by_date)

    # stop variant (raw EV based — stop is a risk control, not alpha isolation)
    stop_rets = [ret_fn_stop(p) for p in picks]
    stop_clean = [r[0] for r in stop_rets if r is not None]
    stop_s = ev_stats(stop_clean)
    stop_by_date: dict[str, list[float]] = defaultdict(list)
    stop_reasons: dict[str, int] = defaultdict(int)
    for p in picks:
        r = ret_fn_stop(p)
        if r is not None:
            stop_by_date[p["event_date"]].append(r[0])
            stop_reasons[r[1]] += 1
    stop_dt = day_paired_t(stop_by_date)

    # walk-forward on BHAR (主口径)
    wf_bhar = walk_forward_event(picks, ret_fn_bhar)
    # walk-forward on raw EV (参考)
    wf_raw = walk_forward_event(picks, ret_fn_raw)

    if verbose:
        print(f"\n  {name} [{window_label}]: n={len(picks)} n_days={bhar_dt['n_days']}")
        print(
            f"    raw EV:  gross={raw_s['ev']:+.3f}% net={raw_s['ev'] - COST * 100:+.3f}% "
            f"day_t={raw_dt['t']} p={raw_dt['p_one_sided']} WR={raw_s['wr']}%"
        )
        print(
            f"    BHAR:    gross={bhar_s['ev']:+.3f}% net={bhar_s['ev'] - COST * 100:+.3f}% "
            f"day_t={bhar_dt['t']} p={bhar_dt['p_one_sided']} WR={bhar_s['wr']}%"
        )
        print(
            f"    beta 泄漏 = raw - BHAR = {raw_s['ev'] - bhar_s['ev']:+.3f}% "
            f"({'raw 通胀(beta 泄漏)' if raw_s['ev'] > bhar_s['ev'] else 'raw 通缩'})"
        )
        print(f"    stop:    gross={stop_s['ev']:+.3f}% net={stop_s['ev'] - COST * 100:+.3f}% WR={stop_s['wr']}% day_t={stop_dt['t']}")
        tot_r = sum(stop_reasons.values()) or 1
        stop_pct_str = ", ".join(f"{k}:{v}({v / tot_r * 100:.0f}%)" for k, v in sorted(stop_reasons.items(), key=lambda x: -x[1]))
        print(f"    exit reasons: {stop_pct_str}")
        if wf_bhar["status"] == "ok":
            tr = wf_bhar["train_ev"]
            te = wf_bhar["test_ev"]
            print(
                f"    WF(BHAR): train={tr['ev']:+.3f}% test={te['ev']:+.3f}% "
                f"test_p={wf_bhar['test_day_t']['p_one_sided']} "
                f"n_tr_dates={wf_bhar['n_train_dates']} n_te_dates={wf_bhar['n_test_dates']}"
            )

    return {
        "name": name,
        "n": len(picks),
        "n_days": bhar_dt["n_days"],
        "window": window_label,
        "raw": raw_s,
        "raw_dt": raw_dt,
        "raw_net": raw_s["ev"] - COST * 100,
        "bhar": bhar_s,
        "bhar_dt": bhar_dt,
        "bhar_net": bhar_s["ev"] - COST * 100,
        "stop": stop_s,
        "stop_dt": stop_dt,
        "stop_net": stop_s["ev"] - COST * 100,
        "wf_bhar": wf_bhar,
        "wf_raw": wf_raw,
        "beta_leak": round(raw_s["ev"] - bhar_s["ev"], 3),
    }


# ---------- regime classification ----------


def classify_regime(date: str, index_map: dict[str, dict], idx_dates_sorted: list[str]) -> str:
    """bull/bear/range via 60-day index momentum; crisis via fixed windows."""
    for _label, lo, hi in CRISIS_WINDOWS:
        if lo <= date <= hi:
            return "crisis"
    di = None
    lo_i, hi_i = 0, len(idx_dates_sorted)
    while lo_i < hi_i:
        mid = (lo_i + hi_i) // 2
        if idx_dates_sorted[mid] <= date:
            di = mid
            lo_i = mid + 1
        else:
            hi_i = mid
    if di is None or di < 60:
        return "range"
    s = index_map.get(idx_dates_sorted[di - 60], {}).get("close")
    e = index_map.get(idx_dates_sorted[di], {}).get("close")
    if s is None or e is None or s <= 0:
        return "range"
    ret60 = (e - s) / s
    if ret60 > 0.05:
        return "bull"
    if ret60 < -0.05:
        return "bear"
    return "range"


def tag_regime(picks: list[dict], index_map: dict[str, dict]) -> None:
    idx_dates_sorted = sorted(index_map.keys())
    for p in picks:
        p["regime"] = classify_regime(p["event_date"], index_map, idx_dates_sorted)


# ---------- DSR estimation ----------


def estimate_dsr(ev_mean: float, ev_std: float, n_events: int, n_trials: int, events_per_year: float) -> dict:
    if ev_std <= 0 or n_events <= 0:
        return {"event_sharpe": 0, "ann_sharpe": 0, "dsr_approx": 0, "expected_max_sr": 0, "n_trials": n_trials}
    event_sharpe = ev_mean / ev_std
    ann_sharpe = event_sharpe * sqrt(events_per_year)
    expected_max_sr = sqrt(2 * math.log(n_trials)) if n_trials > 1 else 0
    dsr = ann_sharpe - expected_max_sr
    return {
        "event_sharpe": round(event_sharpe, 3),
        "ann_sharpe": round(ann_sharpe, 3),
        "expected_max_sr": round(expected_max_sr, 4),
        "dsr_approx": round(dsr, 3),
        "n_trials": n_trials,
    }


# ---------- verdict (BHAR-based, §44 v3 cascade) ----------


def bhar_verdict(subset: dict, n_cross: int = N_CROSS_STRATEGY, label: str = "") -> str:
    """对 BHAR 出正式 verdict（Bonferroni = cross×2_subsets）."""
    bhar = subset["bhar"]
    bhar_dt = subset["bhar_dt"]
    wf = subset.get("wf_bhar", {})
    wf_status = wf.get("status", "no_picks")
    wf_train_ev = wf.get("train_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
    wf_test_ev = wf.get("test_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
    wf_test_p = wf.get("test_day_t", {}).get("p_one_sided", 1.0) if wf_status == "ok" else 1.0
    v = verdict_for(
        ev_gross=bhar["ev"],
        t_day=bhar_dt["t"],
        p_raw=bhar_dt["p_one_sided"],
        wf_status=wf_status,
        wf_train_ev=wf_train_ev,
        wf_test_ev=wf_test_ev,
        wf_test_p=wf_test_p,
        n_days=bhar_dt["n_days"],
        net_ev=subset["bhar_net"],
        subset_name=label or subset["name"],
        n_cross_factor=n_cross,
    )
    n_tests = max(2, n_cross * 2)
    subset["bonf_p"] = bonferroni_p(bhar_dt["p_one_sided"], n_tests)
    subset["n_tests_bonf"] = n_tests
    subset["verdict"] = v
    return v


# ---------- main ----------


def main() -> None:
    print("=" * 78)
    print("跌停打开承接 Round 2 深挖（反人性 long-only 博反弹）")
    print("=" * 78)

    code_map, _ = load_kline_db()
    index_map, calendar = load_index()
    print(f"[数据] kline: {len(code_map)} codes | index sh.000001: {len(calendar)} days")
    print(f"[数据] calendar: {calendar[0]} ~ {calendar[-1]}")

    picks = build_picks_limit_down_open(code_map, calendar, index_map)
    n_dates = len(set(p["event_date"] for p in picks))
    ev_dates = sorted(set(p["event_date"] for p in picks))
    print(f"\n[build] 跌停打开 events: {len(picks)} across {n_dates} days ({ev_dates[0]} ~ {ev_dates[-1]})")
    if not picks:
        print("[verdict] no picks → no-data")
        return

    tag_regime(picks, index_map)

    # regime + board distribution
    regime_dist = defaultdict(int)
    board_dist = defaultdict(int)
    yizi_dist = defaultdict(int)
    for p in picks:
        regime_dist[p["regime"]] += 1
        board_dist[p["board"]] += 1
        yizi_dist["t1_yizi_dt" if p["t1_yizi_dt"] else "t1_normal"] += 1
    print(f"[build] regime: {dict(regime_dist)}")
    print(f"[build] board: {dict(board_dist)}")
    print(f"[build] t1 state: {dict(yizi_dist)}")

    # ret_fn closures
    rf_raw_t2 = raw_ev_t2
    rf_raw_t5 = raw_ev_t5
    rf_bhar_t2 = bhar_t2
    rf_bhar_t5 = bhar_t5
    rf_stop_t2 = close_ev_stop_t2
    rf_stop_t5 = close_ev_stop_t5

    # ================================================================
    # 维度 1+2: BHAR gate + 窗口对比（T+2 vs T+5）
    # ================================================================
    print("\n" + "=" * 78)
    print("维度 1+2: BHAR gate + 窗口对比（raw EV vs market-adjusted BHAR）")
    print("=" * 78)
    print("BHAR = stock(T+1open→T+kclose) - market(T+1open→T+kclose)")
    print("若 raw EV 正但 BHAR 负→反弹仅 market beta 非 stock-specific edge")

    sub_t2 = analyze_subset("全样本 T+2", picks, rf_raw_t2, rf_bhar_t2, rf_stop_t2, "T+2")
    sub_t5 = analyze_subset("全样本 T+5", picks, rf_raw_t5, rf_bhar_t5, rf_stop_t5, "T+5")

    # ================================================================
    # 维度 3: 打开程度分桶（微开/半开/全开）
    # ================================================================
    print("\n" + "=" * 78)
    print("维度 3: 打开程度分桶——恢复程度↔反弹力度？")
    print("=" * 78)
    print("open_degree = (close - low) / low on event day T")
    print("微开(<1%): 板刚打开, 抛压仍重 | 半开(1~3%): 部分恢复 | 全开(>=3%): 强承接")

    open_buckets = {
        "微开(<1%)": [p for p in picks if p["open_degree"] < 0.01],
        "半开(1~3%)": [p for p in picks if 0.01 <= p["open_degree"] < 0.03],
        "全开(>=3%)": [p for p in picks if p["open_degree"] >= 0.03],
    }
    open_results = {}
    for bname, bp in open_buckets.items():
        open_results[bname] = analyze_subset(f"open={bname}", bp, rf_raw_t2, rf_bhar_t2, rf_stop_t2, "T+2")

    # ================================================================
    # 维度 4: regime 分层（bull/bear/range/crisis）
    # ================================================================
    print("\n" + "=" * 78)
    print("维度 4: regime 分层——恐慌越深反弹越强？A 股隔夜负漂移逆风")
    print("=" * 78)
    regime_picks: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        regime_picks[p["regime"]].append(p)
    regime_results = {}
    for rname in ("bull", "bear", "range", "crisis"):
        rp = regime_picks.get(rname, [])
        if rp:
            regime_results[rname] = analyze_subset(f"regime={rname}", rp, rf_raw_t2, rf_bhar_t2, rf_stop_t2, "T+2")

    # ================================================================
    # 维度 5: 结构断点 / era
    # ================================================================
    print("\n" + "=" * 78)
    print("维度 5: 结构断点——edge 衰减？（pre-2020 / 2020-2022 / 2023-2026）")
    print("=" * 78)
    eras = [
        ("pre-2020", "2018-01-01", "2019-12-31"),
        ("2020-2022", "2020-01-01", "2022-12-31"),
        ("2023-2026", "2023-01-01", "2026-12-31"),
    ]
    era_results = {}
    for label, lo, hi in eras:
        ep = [p for p in picks if lo <= p["event_date"] <= hi]
        if ep:
            era_results[label] = analyze_subset(f"era={label}", ep, rf_raw_t2, rf_bhar_t2, rf_stop_t2, "T+2")

    # 年度趋势
    print(f"\n--- 年度 BHAR 趋势（T+2）---")
    print(f"{'year':<6} {'n':>6} {'n_days':>7} {'raw%':>8} {'BHAR%':>8} {'net%':>7} {'day_t':>7} {'p':>9}")
    yearly = []
    for yr in range(2018, 2027):
        lo = f"{yr}-01-01"
        hi = f"{yr}-12-31"
        yp = [p for p in picks if lo <= p["event_date"] <= hi]
        if not yp:
            continue
        yr_sub = analyze_subset(str(yr), yp, rf_raw_t2, rf_bhar_t2, rf_stop_t2, "T+2", verbose=False)
        yearly.append((yr, yr_sub))
        print(
            f"{yr:<6} {yr_sub['n']:>6} {yr_sub['n_days']:>7} "
            f"{yr_sub['raw']['ev']:>+8} {yr_sub['bhar']['ev']:>+8} "
            f"{yr_sub['bhar_net']:>+7} {yr_sub['bhar_dt']['t']:>7} "
            f"{yr_sub['bhar_dt']['p_one_sided']:>9}"
        )

    # ================================================================
    # 维度 6: T+1 状态（一字跌停 vs normal）
    # ================================================================
    print("\n" + "=" * 78)
    print("维度 6: T+1 状态——一字跌停(falling knife) vs normal(反弹可能)")
    print("=" * 78)
    yizi_picks = [p for p in picks if p["t1_yizi_dt"]]
    normal_picks = [p for p in picks if not p["t1_yizi_dt"]]
    print(f"  T+1 一字跌停: {len(yizi_picks)} ({len(yizi_picks) / len(picks) * 100:.1f}%)")
    print(f"  T+1 normal:   {len(normal_picks)} ({len(normal_picks) / len(picks) * 100:.1f}%)")
    if yizi_picks:
        analyze_subset("T+1 一字跌停", yizi_picks, rf_raw_t2, rf_bhar_t2, rf_stop_t2, "T+2")
    if normal_picks:
        analyze_subset("T+1 normal", normal_picks, rf_raw_t2, rf_bhar_t2, rf_stop_t2, "T+2")

    # ================================================================
    # 维度 7: 板块类型分层
    # ================================================================
    print("\n" + "=" * 78)
    print("维度 7: 板块类型——主板/中小/创业板/科创板（不同 limit+散户结构）")
    print("=" * 78)
    board_picks: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        board_picks[p["board"]].append(p)
    board_results = {}
    for bname in ("main", "sme", "chuangye", "kechuang"):
        bp = board_picks.get(bname, [])
        if bp:
            board_results[bname] = analyze_subset(f"board={bname}", bp, rf_raw_t2, rf_bhar_t2, rf_stop_t2, "T+2")

    # ================================================================
    # 维度 8: 2023-2026 子条件 sweep（ANY 存活？）
    # ================================================================
    print("\n" + "=" * 78)
    print("维度 8: 2023-2026 子条件 sweep——近期数据 ANY 子条件存活 §44 v3？")
    print("=" * 78)
    print("sweep: 窗口(T2/T5) × 打开程度(微/半/全) × regime(全/bear/crisis) × T1状态(全/normal)")

    RECENT_LO, RECENT_HI = "2023-01-01", "2026-12-31"
    recent = [p for p in picks if RECENT_LO <= p["event_date"] <= RECENT_HI]
    print(f"  近期 events: {len(recent)}")

    sub_conds = []
    for wname, rf_r, rf_b, rf_s in (
        ("T2", rf_raw_t2, rf_bhar_t2, rf_stop_t2),
        ("T5", rf_raw_t5, rf_bhar_t5, rf_stop_t5),
    ):
        for oname, ofilt in (("all", None), ("micro", "<0.01"), ("half", "0.01-0.03"), ("full", ">=0.03")):
            for rname, rset in (("all", None),):
                for tname, tfilt in (("all", None), ("normal", "normal")):
                    subset_picks = recent
                    if ofilt == "<0.01":
                        subset_picks = [p for p in subset_picks if p["open_degree"] < 0.01]
                    elif ofilt == "0.01-0.03":
                        subset_picks = [p for p in subset_picks if 0.01 <= p["open_degree"] < 0.03]
                    elif ofilt == ">=0.03":
                        subset_picks = [p for p in subset_picks if p["open_degree"] >= 0.03]
                    if tfilt == "normal":
                        subset_picks = [p for p in subset_picks if not p["t1_yizi_dt"]]
                    if not subset_picks:
                        continue
                    sc = analyze_subset(f"23-26 {wname} open={oname} t1={tname}", subset_picks, rf_r, rf_b, rf_s, wname, verbose=False)
                    sub_conds.append(sc)
                    # bear/crisis splits
                    for crname in ("bear", "crisis"):
                        cp = [p for p in subset_picks if p["regime"] == crname]
                        if cp:
                            cr_sc = analyze_subset(
                                f"23-26 {wname} open={oname} t1={tname} {crname}",
                                cp,
                                rf_r,
                                rf_b,
                                rf_s,
                                wname,
                                verbose=False,
                            )
                            sub_conds.append(cr_sc)

    n_sub = len(sub_conds)
    n_bonf_sub = max(2, n_sub * N_CROSS_STRATEGY * 2)
    print(f"\n  测试 {n_sub} 个子条件，within-script Bonferroni ×{n_bonf_sub}")

    survivors = []
    print(f"\n{'子条件':<46} {'n':>5} {'BHAR%':>8} {'net%':>7} {'p_raw':>9} {'p_bonf':>9} {'verdict':<14}")
    for sc in sub_conds:
        p_bonf = bonferroni_p(sc["bhar_dt"]["p_one_sided"], n_bonf_sub)
        sc["p_bonf_sub"] = p_bonf
        if sc["n_days"] < 60:
            v = "underpowered"
        elif sc["bhar"]["ev"] < 0:
            v = "falsified"
        elif p_bonf >= ALPHA:
            v = "falsified"
        elif sc["bhar_net"] <= 0:
            v = "falsified"
        else:
            v = "survives-bonf"
        sc["sub_verdict"] = v
        flag = " <== survives" if v == "survives-bonf" else ""
        print(
            f"{sc['name']:<46} {sc['n']:>5} {sc['bhar']['ev']:>+8} "
            f"{sc['bhar_net']:>+7} {sc['bhar_dt']['p_one_sided']:>9} "
            f"{p_bonf:>9} {v:<14}{flag}"
        )
        if v == "survives-bonf":
            survivors.append(sc)

    # ================================================================
    # DSR estimation
    # ================================================================
    print("\n" + "=" * 78)
    print("DSR 估算（多重检验 haircut）")
    print("=" * 78)
    # T+2 BHAR 是主口径
    dsr = estimate_dsr(
        sub_t2["bhar"]["ev"],
        sub_t2["bhar"]["std"],
        sub_t2["n"],
        n_trials=N_CROSS_STRATEGY * 4,  # 3 strategies × ~4 variants
        events_per_year=len(picks) / max(1, (2026 - 2018 + 1)),
    )
    print(
        f"  T+2 BHAR: event Sharpe={dsr['event_sharpe']} "
        f"ann Sharpe={dsr['ann_sharpe']} "
        f"expected max SR(n_trials={dsr['n_trials']})={dsr['expected_max_sr']} "
        f"DSR≈{dsr['dsr_approx']}"
    )
    if dsr["dsr_approx"] < 0:
        print(f"  → DSR<0: 多重检验校正后 Sharpe 不显著（overfitting 风险）")
    else:
        print(f"  → DSR>0: 校正后仍正（需 walk-forward 确认）")

    # ================================================================
    # 正式 verdict（全样本 T+2 BHAR + T+5 BHAR，Bonf×3）
    # ================================================================
    print("\n" + "=" * 78)
    print("正式 verdict（BHAR 口径，Bonferroni ×3 cross-strategy）")
    print("=" * 78)
    v_t2 = bhar_verdict(sub_t2, n_cross=N_CROSS_STRATEGY, label="全样本 T+2 BHAR")
    v_t5 = bhar_verdict(sub_t5, n_cross=N_CROSS_STRATEGY, label="全样本 T+5 BHAR")

    # ================================================================
    # 诚实总结
    # ================================================================
    print("\n" + "=" * 78)
    print("诚实总结")
    print("=" * 78)

    print(f"\n[BHAR gate] T+2 raw={sub_t2['raw']['ev']:+.3f}% vs BHAR={sub_t2['bhar']['ev']:+.3f}% → beta 泄漏={sub_t2['beta_leak']:+.3f}%")
    print(f"  → {'raw 通胀了 edge（反弹含 market beta 非 stock-specific）' if sub_t2['beta_leak'] > 0 else 'raw 通缩了 edge'}")
    print(f"  T+5 raw={sub_t5['raw']['ev']:+.3f}% vs BHAR={sub_t5['bhar']['ev']:+.3f}% → beta 泄漏={sub_t5['beta_leak']:+.3f}%")

    print(
        f"\n[窗口] T+2 BHAR={sub_t2['bhar']['ev']:+.3f}% net={sub_t2['bhar_net']:+.3f}% | "
        f"T+5 BHAR={sub_t5['bhar']['ev']:+.3f}% net={sub_t5['bhar_net']:+.3f}%"
    )
    print(f"  stop: T+2 net={sub_t2['stop_net']:+.3f}% | T+5 stop net={sub_t5['stop_net']:+.3f}%")

    # 打开程度单调性
    print(f"\n[打开程度] ", end="")
    for bname in ("微开(<1%)", "半开(1~3%)", "全开(>=3%)"):
        if bname in open_results:
            r = open_results[bname]
            print(f"{bname}→BHAR={r['bhar']['ev']:+.3f}%  ", end="")
    print()

    # regime
    print(f"\n[regime] ", end="")
    for rname in ("bull", "bear", "range", "crisis"):
        if rname in regime_results:
            r = regime_results[rname]
            print(f"{rname}→BHAR={r['bhar']['ev']:+.3f}%  ", end="")
    print()

    # era
    print(f"\n[era] ", end="")
    for label in ("pre-2020", "2020-2022", "2023-2026"):
        if label in era_results:
            r = era_results[label]
            print(f"{label}→BHAR={r['bhar']['ev']:+.3f}%  ", end="")
    print()

    # board
    print(f"\n[board] ", end="")
    for bname in ("main", "sme", "chuangye", "kechuang"):
        if bname in board_results:
            r = board_results[bname]
            print(f"{bname}→BHAR={r['bhar']['ev']:+.3f}%  ", end="")
    print()

    print(f"\n[2023-2026 子条件] {n_sub} 测试，Bonf×{n_bonf_sub}，存活 {len(survivors)} 个")
    if survivors:
        for s in survivors:
            print(f"    {s['name']}: BHAR={s['bhar']['ev']:+.3f}% n={s['n']} n_days={s['n_days']} p_bonf={s['p_bonf_sub']:.6f}")

    print(f"\n[DSR] T+2 BHAR DSR≈{dsr['dsr_approx']} (ann Sharpe={dsr['ann_sharpe']} vs expected max={dsr['expected_max_sr']})")

    print(f"\n[正式 verdict]")
    print(f"  全样本 T+2 BHAR: {v_t2}")
    print(f"  全样本 T+5 BHAR: {v_t5}")

    print(f"\n[stop 保护] T+2 stop net={sub_t2['stop_net']:+.3f}% | T+5 stop net={sub_t5['stop_net']:+.3f}%")
    print(f"  → {'stop 改善 EV（控制尾部风险有效）' if sub_t2['stop_net'] > sub_t2['bhar_net'] else 'stop 恶化 EV（反弹太快 stop 误杀）'}")

    print("\n禁外推声明：本测仅跌停打开承接单策略。ETF折溢价/大股东增持是独立策略，")
    print("不因跌停打开 edge 结果外推'事件驱动有/无 edge'。")
    print("isST 仅 42.5% 填充→ST 股(5% limit)部分漏检（保守低估 events）。")
    print("前复权 cache limit-down 检测：连续日间复权因子一致(无除权)→ratio 正确；")
    print("除权日 limit-down 价经调整→可能微小偏差(罕见，不实质影响)。")


if __name__ == "__main__":
    main()
