# -*- coding: utf-8 -*-
"""指数调出 post-removal bounce 事件驱动回测 — A 股 OOS (§44 v3).

策略假设 (symmetric to index-addition reversal): 指数调出股 effective 后,
被动资金 forced selling 停止 → price 压低解除 → post-removal reversal bounce.
entry=effective+1 open, exit=T+5/T+10 close. BHAR vs matched index (同指数).
A 股散户可交易 (做多被剔除股博反弹, 不需做空).

调入 post-inclusion 负漂移 (T10 -0.655% Bonf×4 p=0.0147) → 调出 post-removal
应正 (对称假设: 调入 reversal 的 flip side = 调出 bounce).

诚实约束 (§44 v3 + 除权除息 BHAR 教训):
- anchor = EFFECTIVE date (baostock 无 announcement 日, 用 effective 避 look-ahead;
  非 Shleifer announcement→effective pre-effective run-up 窗口——后者须公告日, 无数据)
- entry = effective+1 open (realistic fill, 非 T close sealed)
- exit = effective+5 / effective+10 close
- BHAR = stock_ret - matched_index_ret (非 raw EV — 除权除息教训: raw EV 含 market beta,
  cascade flaw "gate raw EV 不 gate BHAR" 导致假 edge. 本脚本 cascade GATE BHAR:
  bhar_net + bhar_bonf + walk-forward test_BHAR, raw EV 仅 descriptive)
- per-day-mean t (cluster by effective date — 同 rebalance 多股同日相关, 夸大 N)
- Bonferroni ×4 (cross-strategy: index-removal × index-addition × basic+regime)
- walk-forward OOS (chronological split by effective date) + train_BHAR>0
- regime 分层 (strong/weak/range by entry_date regime)
- DSR 估算 (event-level, multiple-testing haircut)
- survivorship: 调出股是指数公司剔除 (selection by decline/ST/退市), 非 winner;
  被剔除后可能停牌/退市 → 缺 kline → 样本偏向存活交易者 (审)
- 禁止外推: 单事件策略 ≠ 事件驱动有/无 edge ≠ 短线有/无 edge
- 半年一次 rebalance → 8 年 ~13-16 distinct effective dates < 60 → 结构性 underpowered
"""

from __future__ import annotations
import json
import sqlite3
import statistics
import time
import calendar
import bisect
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from math import erf, sqrt

import baostock as bs

# import shared helpers (DRY) — reuse statistical functions
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools._factor_helpers import (  # noqa: E402
    ev_stats,
    day_paired_t,
    bonferroni_p,
    norm_sf_positive,
    ALPHA,
    COST,
)

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
DIFF_CACHE = DATA / "_idx_constituent_diff_cache.json"  # constituent diff (eff dates + add/remove)
FETCH_CACHE = DATA / "_idx_add_fetch_cache.json"  # reuse addition fetch cache (shared kline fetches)
REGIME_FILE = DATA / "index_ma20_regime.json"

# matched index per source index (the index the stock was REMOVED from)
INDEX_BENCH = {
    "hs300": "sh.000300",
    "sz50": "sh.000016",
    "zz500": "sh.000905",
}
INDEX_QUERY = {
    "hs300": "query_hs300_stocks",
    "sz50": "query_sz50_stocks",
    "zz500": "query_zz500_stocks",
}

# event windows (relative to effective date, in trading days)
WINDOWS = [
    ("T5", 5),  # entry=eff+1 open, exit=eff+5 close  (4 trading-day hold)
    ("T10", 10),  # entry=eff+1 open, exit=eff+10 close (9 trading-day hold)
]

CROSS_STRATEGY_N = 4  # Bonferroni ×4 (index-removal × index-addition × basic+regime)


# ---------- baostock constituent queries (with diff caching) ----------


def _login() -> None:
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_code} {lg.error_msg}")


def query_constituents(index_key: str, d: str) -> set[str]:
    fn = getattr(bs, INDEX_QUERY[index_key])
    rs = fn(date=d)
    if rs.error_code != "0":
        return set()
    rows: list[list[str]] = []
    while rs.next():
        rows.append(rs.get_row_data())
    return set(r[1] for r in rows if len(r) > 1)


def second_friday(year: int, month: int) -> str:
    c = calendar.Calendar()
    fridays = [d for d in c.itermonthdates(year, month) if d.weekday() == 4 and d.month == month]
    return fridays[1].isoformat()


def find_effective_date(index_key: str, year: int, month: int) -> tuple[str, set[str]] | None:
    """Probe around 2nd Friday to find first date constituents change (= effective date).
    Returns (effective_date, old_constituents) or None if no change (baostock gap)."""
    fri = second_friday(year, month)
    y, m, d = int(fri[:4]), int(fri[5:7]), int(fri[8:10])
    fdate = date(y, m, d)
    probes = [(fdate + timedelta(days=i)).isoformat() for i in range(0, 10)]
    base = query_constituents(index_key, probes[0])
    time.sleep(0.3)
    if not base:
        return None
    for p in probes[1:]:
        s = query_constituents(index_key, p)
        time.sleep(0.3)
        if s and s != base:
            return p, base
    return None


def load_diff_cache() -> dict:
    if DIFF_CACHE.exists():
        try:
            with open(DIFF_CACHE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_diff_cache(dc: dict) -> None:
    with open(DIFF_CACHE, "w") as f:
        json.dump(dc, f)


def get_removals(index_key: str, do_probe: bool = True) -> list[dict]:
    """For each semiannual rebalance, find effective date + removals (in old, not in new).
    Cached in DIFF_CACHE. Returns list of {code, code6, effective_date, index_key, direction:'remove'}."""
    dc = load_diff_cache()
    cached = dc.get(index_key)
    if cached is not None:
        removals: list[dict] = []
        for ev in cached:
            for c in ev["removed"]:
                removals.append(
                    {
                        "code": c,
                        "code6": c.split(".")[1],
                        "effective_date": ev["effective_date"],
                        "index_key": index_key,
                        "direction": "remove",
                    }
                )
        return removals

    if not do_probe:
        return []

    events_meta: list[dict] = []
    for year in range(2018, 2027):
        for month in (6, 12):
            if year == 2026 and month == 12:
                break
            res = find_effective_date(index_key, year, month)
            if res is None:
                print(f"  [{index_key} {year}-{month:02d}] no effective date (baostock gap), skip")
                continue
            eff, old = res
            new = query_constituents(index_key, eff)
            time.sleep(0.3)
            added = sorted(new - old)
            removed = sorted(old - new)
            events_meta.append(
                {
                    "effective_date": eff,
                    "year": year,
                    "month": month,
                    "added": added,
                    "removed": removed,
                }
            )
            print(f"  [{index_key} {year}-{month:02d}] eff={eff} added={len(added)} removed={len(removed)}")
    dc[index_key] = events_meta
    save_diff_cache(dc)
    return get_removals(index_key, do_probe=False)


# ---------- kline (cache + baostock fetch) ----------


def load_kline_cache() -> dict[str, dict[str, dict]]:
    conn = sqlite3.connect(str(KLINE_DB))
    code_map: dict[str, dict[str, dict]] = {}
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        dmap = {b["date"]: b for b in bars if b.get("date")}
        if dmap:
            code_map[code] = dmap
    conn.close()
    return code_map


def load_fetch_cache() -> dict:
    if FETCH_CACHE.exists():
        try:
            with open(FETCH_CACHE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_fetch_cache(fc: dict) -> None:
    with open(FETCH_CACHE, "w") as f:
        json.dump(fc, f)


def fetch_kline_baostock(code: str, start: str, end: str) -> dict[str, dict]:
    """Fetch daily kline for one code from baostock. Returns {date: bar}."""
    rs = bs.query_history_k_data_plus(
        code,
        "date,open,high,low,close,volume,amount,turn,pctChg",
        start_date=start,
        end_date=end,
        frequency="d",
        adjustflag="3",
    )
    if rs.error_code != "0":
        return {}
    dmap: dict[str, dict] = {}
    while rs.next():
        r = rs.get_row_data()
        if len(r) < 9:
            continue
        try:
            dmap[r[0]] = {
                "date": r[0],
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]) if r[5] else 0.0,
                "turn": float(r[7]) if r[7] else 0.0,
                "pctChg": float(r[8]) if r[8] else 0.0,
            }
        except (ValueError, IndexError):
            continue
    return dmap


def get_kline_for_removal(
    rem: dict, code_map: dict, fetch_cache: dict, do_fetch: bool = True
) -> dict[str, dict] | None:
    """Get kline bars around effective date. Cache first, then baostock fetch if gap.
    Returns {date: bar} covering effective-3 .. effective+15, or None."""
    code6 = rem["code6"]
    eff = rem["effective_date"]
    eff_d = date(int(eff[:4]), int(eff[5:7]), int(eff[8:10]))
    start = (eff_d - timedelta(days=25)).isoformat()
    end = (eff_d + timedelta(days=30)).isoformat()

    # 1. kline cache (6-digit code)
    dmap = code_map.get(code6)
    if dmap:
        near = [b for d, b in dmap.items() if start <= d <= end]
        if len(near) >= 10:
            return {b["date"]: b for b in near}

    # 2. fetch cache (local JSON, keyed by full code)
    fc_key = f"{rem['code']}#{start}#{end}"
    if fc_key in fetch_cache:
        return fetch_cache[fc_key]

    # 3. baostock fetch
    if not do_fetch:
        return None
    bars = fetch_kline_baostock(rem["code"], start, end)
    time.sleep(0.35)  # rate limit
    if bars:
        fetch_cache[fc_key] = bars
        return bars
    return None


def fetch_index_kline(index_code: str) -> tuple[dict[str, dict], list[str]]:
    """Full-period index kline (2018-01 to 2026-09). Returns (date->bar, sorted trading days)."""
    rs = bs.query_history_k_data_plus(
        index_code,
        "date,open,high,low,close,volume,amount,turn,pctChg",
        start_date="2018-01-01",
        end_date="2026-09-30",
        frequency="d",
        adjustflag="3",
    )
    dmap: dict[str, dict] = {}
    while rs.error_code == "0" and rs.next():
        r = rs.get_row_data()
        try:
            dmap[r[0]] = {
                "date": r[0],
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
            }
        except (ValueError, IndexError):
            continue
    return dmap, sorted(dmap.keys())


# ---------- BHAR computation ----------


def compute_bhar(
    rem: dict, bars: dict[str, dict], idx_bars: dict[str, dict], idx_dates: list[str], window_n: int
) -> dict | None:
    """BHAR for one removal.
    entry = effective+1 open, exit = effective+N close (N=window_n).
    stock_ret = (close_N - open_1) / open_1
    index_ret = (idx_close_N - idx_open_1) / idx_open_1
    BHAR = stock_ret - index_ret (in %).
    Returns {bhar, stock_ret, index_ret, entry_date, exit_date, ...} or None if data gap.
    """
    eff = rem["effective_date"]
    di = {d: i for i, d in enumerate(idx_dates)}
    eff_idx = di.get(eff)
    if eff_idx is None:
        i = bisect.bisect_left(idx_dates, eff)
        eff_idx = i if i < len(idx_dates) else None
    if eff_idx is None:
        return None
    entry_i = eff_idx + 1
    exit_i = eff_idx + window_n
    if exit_i >= len(idx_dates):
        return None
    entry_date = idx_dates[entry_i]
    exit_date = idx_dates[exit_i]

    s_entry = bars.get(entry_date)
    s_exit = bars.get(exit_date)
    if s_entry is None or s_exit is None:
        return None
    s_open = s_entry.get("open")
    s_close = s_exit.get("close")
    if s_open is None or s_close is None or s_open <= 0:
        return None
    stock_ret = (s_close - s_open) / s_open * 100

    i_entry = idx_bars.get(entry_date)
    i_exit = idx_bars.get(exit_date)
    if i_entry is None or i_exit is None:
        return None
    i_open = i_entry.get("open")
    i_close = i_exit.get("close")
    if i_open is None or i_close is None or i_open <= 0:
        return None
    index_ret = (i_close - i_open) / i_open * 100

    bhar = stock_ret - index_ret
    return {
        "bhar": round(bhar, 4),
        "stock_ret": round(stock_ret, 4),
        "index_ret": round(index_ret, 4),
        "entry_date": entry_date,
        "exit_date": exit_date,
        "effective_date": eff,
        "code": rem["code"],
        "code6": rem["code6"],
        "index_key": rem["index_key"],
    }


# ---------- build_picks: diff + kline + BHAR (per window) ----------


def build_picks(
    removals: list[dict],
    code_map: dict[str, dict[str, dict]],
    fetch_cache: dict,
    idx_kline: dict[str, tuple[dict[str, dict], list[str]]],
    do_fetch: bool = True,
) -> dict[str, list[dict]]:
    """Build picks per window: match removals to kline (cache+fetch) + compute BHAR.

    Returns {window_name: [pick, ...]} where each pick has bhar/stock_ret/index_ret/
    entry_date/exit_date/effective_date/code/index_key.

    Skips: no kline / kline gap / BHAR uncomputable (suspended/delisted → missing bar).
    """
    # kline lookup (per removal code, window-independent)
    bars_by_rem: dict[int, dict[str, dict]] = {}
    n_cached = n_fetched = n_missing = 0
    for i, rem in enumerate(removals):
        bars = get_kline_for_removal(rem, code_map, fetch_cache, do_fetch=do_fetch)
        if bars is None or len(bars) < 5:
            n_missing += 1
            continue
        bars_by_rem[i] = bars
        fc_key = f"{rem['code']}#{(date(int(rem['effective_date'][:4]), int(rem['effective_date'][5:7]), int(rem['effective_date'][8:10])) - timedelta(days=25)).isoformat()}#{(date(int(rem['effective_date'][:4]), int(rem['effective_date'][5:7]), int(rem['effective_date'][8:10])) + timedelta(days=30)).isoformat()}"
        if fc_key in fetch_cache:
            n_fetched += 1
        else:
            n_cached += 1
    print(
        f"  kline usable: {len(bars_by_rem)}/{len(removals)} "
        f"(cached={n_cached} fetched={n_fetched} missing={n_missing})"
    )

    picks_by_window: dict[str, list[dict]] = {}
    for wname, wn in WINDOWS:
        picks: list[dict] = []
        for i, rem in enumerate(removals):
            bars = bars_by_rem.get(i)
            if bars is None:
                continue
            ik = rem["index_key"]
            idx_bars, idx_dates = idx_kline[ik]
            r = compute_bhar(rem, bars, idx_bars, idx_dates, wn)
            if r is None:
                continue
            picks.append(r)
        picks_by_window[wname] = picks
    return picks_by_window


# ---------- regime ----------


def load_regime() -> dict[str, str]:
    """date -> regime ('strong'/'weak'/'range')."""
    if not REGIME_FILE.exists():
        return {}
    with open(REGIME_FILE) as f:
        raw = json.load(f)
    out: dict[str, str] = {}
    for d, v in raw.items():
        if isinstance(v, dict):
            r = v.get("regime")
            if r:
                out[d] = r
    return out


# ---------- per-event t (descriptive) ----------


def per_event_t(rets: list[float]) -> dict:
    n = len(rets)
    if n == 0:
        return {"n": 0, "mean": 0.0, "std": 0.0, "t": 0.0, "p_one_sided": 1.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = norm_sf_positive(t)
    return {"n": n, "mean": round(mean, 4), "std": round(std, 4), "t": round(t, 2), "p_one_sided": round(p, 6)}


# ---------- DSR estimation ----------


def estimate_dsr(ev_mean: float, ev_std: float, n_events: int, n_trials: int) -> dict:
    """Approximate Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).
    Multiple-testing haircut: ann Sharpe must exceed expected max SR under H0
    = sqrt(2*ln(N_trials)) to survive."""
    if ev_std <= 0 or n_events <= 0:
        return {"event_sharpe": 0, "ann_sharpe": 0, "dsr_approx": 0, "expected_max_sr": 0, "n_trials": n_trials}
    event_sharpe = ev_mean / ev_std
    # semiannual rebalance: ~2 events/yr per index, ~6 indices-of-events/yr spread →
    # use n_events/8yr as events-per-year proxy
    events_per_year = max(n_events / 8, 1)
    ann_sharpe = event_sharpe * sqrt(events_per_year)
    expected_max_sr = sqrt(2 * statistics.log(n_trials)) if n_trials > 1 else 0.0
    dsr = ann_sharpe - expected_max_sr
    return {
        "event_sharpe": round(event_sharpe, 3),
        "ann_sharpe": round(ann_sharpe, 3),
        "expected_max_sr": round(expected_max_sr, 4),
        "dsr_approx": round(dsr, 3),
        "n_trials": n_trials,
    }


# ---------- per-window BHAR analysis (PRIMARY, gated) ----------


def analyze_window_bhar(name: str, picks: list[dict]) -> dict:
    """Full BHAR analysis on one window: stats + day-paired t + walk-forward + regime.
    BHAR is PRIMARY (raw stock_ret only descriptive)."""
    print(f"\n{'=' * 60}")
    print(f"窗口: {name} (n_picks={len(picks)})  [BHAR-gated]")
    print(f"{'=' * 60}")
    if not picks:
        print("  无 picks → no-data")
        return {"name": name, "n_picks": 0}

    bhars = [p["bhar"] for p in picks]
    raw_rets = [p["stock_ret"] for p in picks]

    # descriptive raw EV (NOT gated — for transparency only)
    raw_s = ev_stats(raw_rets)
    print(f"\n  [descriptive raw stock_ret — NOT gated, market beta included]")
    print(f"    n={raw_s['n']} mean={raw_s['ev']}% WR={raw_s['wr']}% t={raw_s['t']}")

    # PRIMARY: BHAR stats
    ev = ev_stats(bhars)
    net_bhar = ev["ev"] - COST * 100
    print(f"\n  [PRIMARY: BHAR = stock_ret - matched_index_ret]")
    print(
        f"    n={ev['n']} BHAR_gross={ev['ev']}% std={ev['std']}% "
        f"WR={ev['wr']}% t={ev['t']} CI[{ev['ci_lo']},{ev['ci_hi']}]"
    )
    print(f"    BHAR_net (after {COST * 100:.1f}% cost): {net_bhar:.3f}%")

    # per-event t (descriptive)
    pet = per_event_t(bhars)
    print(f"    per-event t: mean={pet['mean']}% t={pet['t']} p={pet['p_one_sided']}")

    # per-day-mean t (PRIMARY inferential, clustered by effective date)
    by_date: dict[str, list[float]] = defaultdict(list)
    by_index: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        by_date[p["effective_date"]].append(p["bhar"])
        by_index[p["index_key"]].append(p["bhar"])
    dt = day_paired_t(by_date)
    p_raw = dt["p_one_sided"]
    p_bonf = bonferroni_p(p_raw, CROSS_STRATEGY_N)
    print(f"\n  [per-day-mean t (PRIMARY, cluster by effective date)]")
    print(f"    n_days={dt['n_days']} mean={dt['mean']}% std={dt['std']}% t={dt['t']} p_one_sided={p_raw}")
    print(f"    Bonferroni ×{CROSS_STRATEGY_N}: p={p_bonf:.6f} ({'PASS' if p_bonf < ALPHA else 'FAIL'} @ α={ALPHA})")

    # per-index breakdown
    print(f"\n  per-index BHAR:")
    for ik, rs in by_index.items():
        s = ev_stats(rs)
        print(f"    {ik}: n={s['n']} mean={s['ev']}% WR={s['wr']}% t={s['t']}")

    # regime stratification
    regime_map = load_regime()
    print(f"\n  --- regime stratification (by entry_date regime) ---")
    regime_rets: dict[str, list[float]] = {}
    for rname in ("strong", "weak", "range"):
        rr = [p["bhar"] for p in picks if regime_map.get(p["entry_date"]) == rname]
        if not rr:
            continue
        regime_rets[rname] = rr
        s = ev_stats(rr)
        print(f"    {rname}: n={s['n']} mean={s['ev']}% WR={s['wr']}% t={s['t']}")

    # walk-forward (chronological by effective date)
    print(f"\n  --- walk-forward OOS (chronological split by effective date) ---")
    eff_d_sorted = sorted(by_date.keys())
    wf_status = "too_few_dates"
    wf_train_bhar = wf_test_bhar = wf_test_p = 0.0
    wf_n_test_dates = 0
    if len(eff_d_sorted) >= 4:
        mid = len(eff_d_sorted) // 2
        train_dates = set(eff_d_sorted[:mid])
        test_dates = set(eff_d_sorted[mid:])
        train_rets = [v for d in train_dates for v in by_date[d]]
        test_rets = [v for d in test_dates for v in by_date[d]]
        tr_ev = ev_stats(train_rets)
        te_ev = ev_stats(test_rets)
        tr_dt = day_paired_t({d: by_date[d] for d in train_dates})
        te_dt = day_paired_t({d: by_date[d] for d in test_dates})
        print(f"    train: n_dates={len(train_dates)} n={tr_ev['n']} BHAR={tr_ev['ev']}% t={tr_dt['t']} (day-paired)")
        print(
            f"    test:  n_dates={len(test_dates)} n={te_ev['n']} "
            f"BHAR={te_ev['ev']}% t={te_dt['t']} p={te_dt['p_one_sided']}"
        )
        decay = (tr_ev["ev"] - te_ev["ev"]) / abs(tr_ev["ev"]) * 100 if tr_ev["ev"] != 0 else 0
        print(f"    decay: {decay:.0f}% (train→test)")
        wf_status = "ok"
        wf_train_bhar = tr_ev["ev"]
        wf_test_bhar = te_ev["ev"]
        wf_test_p = te_dt["p_one_sided"]
        wf_n_test_dates = len(test_dates)
    else:
        print(f"    too few effective dates ({len(eff_d_sorted)}) for walk-forward")

    return {
        "name": name,
        "n_picks": len(picks),
        "n_events": ev["n"],
        "n_dates": dt["n_days"],
        "bhar_gross": ev["ev"],
        "bhar_net": net_bhar,
        "bhar_std": ev["std"],
        "wr": ev["wr"],
        "t_trade": ev["t"],
        "day_t": dt["t"],
        "p_raw": p_raw,
        "p_bonf": p_bonf,
        "raw_stock_ret_mean": raw_s["ev"],
        "wf_status": wf_status,
        "wf_train_bhar": wf_train_bhar,
        "wf_test_bhar": wf_test_bhar,
        "wf_test_p": wf_test_p,
        "wf_n_test_dates": wf_n_test_dates,
        "regime_rets": {k: ev_stats(v) for k, v in regime_rets.items()},
        "picks": picks,
    }


# ---------- verdict cascade: GATE BHAR (not raw EV) ----------


def verdict_bhar_gated(r: dict) -> str:
    """§44 v3 verdict cascade — gates on BHAR (除权除息教训: raw EV 含 beta).
    Cascade:
      1. bhar_gross < 0 → falsified (no post-removal bounce, loser signal)
      2. n_dates < 60 → underpowered
      3. bhar_bonf >= 0.05 → falsified (not significant)
      4. bhar_net <= 0 → falsified (gross edge eaten by cost)
      5. wf_train_bhar <= 0 → exploratory (edge not in train, regime overfit)
      6. wf_test_bhar <= 0 → falsified
      7. wf_test_p Bonf >= 0.05 → exploratory (OOS not significant)
      8. all pass → edge-confirmed
    """
    g = r["bhar_gross"]
    net = r["bhar_net"]
    n_dates = r["n_dates"]
    t_day = r["day_t"]
    p_bonf = r["p_bonf"]
    print(f"\n  --- verdict cascade (BHAR-gated, §44 v3) ---")
    print(
        f"    bhar_gross={g}% bhar_net={net:.3f}% day_t={t_day} Bonf×{CROSS_STRATEGY_N}={p_bonf:.6f} n_dates={n_dates}"
    )
    print(
        f"    [descriptive raw stock_ret={r['raw_stock_ret_mean']}% — NOT gated, "
        f"market beta; if raw>0 but BHAR<0 → fake edge = market drift]"
    )
    if r["wf_status"] == "ok":
        print(
            f"    walk-forward: train_BHAR={r['wf_train_bhar']}% "
            f"test_BHAR={r['wf_test_bhar']}% test_p={r['wf_test_p']} "
            f"(n_test_dates={r['wf_n_test_dates']})"
        )

    if g < 0:
        # §44 v2: 小n不判劣于随机 — gross<0 with n_dates<30 = underpowered not falsified
        # (3 dates could be regime artifact; need ≥30 to definitively falsify a loser)
        if n_dates >= 30:
            print(
                f"    → FALSIFIED: bhar_gross={g}% < 0 (no post-removal bounce; "
                f"n_dates={n_dates}≥30; if raw_ret>0 it was market beta not abnormal)"
            )
            return "edge-falsified"
        print(
            f"    → UNDERPOWERED: bhar_gross={g}% < 0 BUT n_dates={n_dates} < 30 "
            f"(suggestive negative — no bounce support, but can't definitively "
            f"falsify from {n_dates} dates; §44 v2 小n不判劣于随机)"
        )
        return "underpowered"
    if n_dates < 60:
        print(f"    → UNDERPOWERED: n_dates={n_dates} < 60 (结构性: 半年 rebalance, 8 年 ~13-16 event dates)")
        return "underpowered"
    if p_bonf >= ALPHA:
        print(f"    → FALSIFIED: Bonferroni p={p_bonf} >= {ALPHA} (not significant)")
        return "edge-falsified"
    if net <= 0:
        print(f"    → FALSIFIED: bhar_net={net}% <= 0 (gross edge eaten by cost)")
        return "edge-falsified"
    if r["wf_status"] == "ok":
        if r["wf_train_bhar"] <= 0:
            print(
                f"    → EXPLORATORY: train_BHAR={r['wf_train_bhar']}% <= 0 "
                f"(edge not in train half, test may be regime overfit)"
            )
            return "exploratory"
        if r["wf_test_bhar"] <= 0:
            print(f"    → FALSIFIED: walk-forward test_BHAR={r['wf_test_bhar']}% <= 0")
            return "edge-falsified"
        wf_p_bonf = bonferroni_p(r["wf_test_p"], CROSS_STRATEGY_N)
        if wf_p_bonf >= ALPHA:
            print(
                f"    → EXPLORATORY: OOS BHAR>0 but test p={r['wf_test_p']} "
                f"Bonf×{CROSS_STRATEGY_N}={wf_p_bonf} >= {ALPHA} (not significant OOS)"
            )
            return "exploratory"
        print(f"    → EDGE-CONFIRMED: BHAR>0, Bonf PASS, OOS significant")
        return "edge-confirmed"
    print(f"    → EXPLORATORY: walk-forward not available")
    return "exploratory"


# ---------- main ----------


def main() -> None:
    _login()
    print("=" * 72)
    print("指数调出 post-removal bounce 事件驱动回测 (§44 v3, BHAR-gated)")
    print("=" * 72)
    print("anchor = effective date (no look-ahead; baostock 无 announcement 日)")
    print("entry = effective+1 open, exit = effective+N close, BHAR vs matched index")
    print("verdict cascade GATE BHAR (bhar_net + bhar_bonf) — 除权除息教训: raw EV 含 beta")
    print(f"Bonferroni ×{CROSS_STRATEGY_N} (cross-strategy: idx-removal × idx-addition × basic+regime)")
    print()

    # ---- 1. index kline (benchmark + calendar) ----
    print("[1/5] fetching matched index kline (sh.000300/sh.000016/sh.000905)...")
    idx_kline: dict[str, tuple[dict[str, dict], list[str]]] = {}
    for ik, ic in INDEX_BENCH.items():
        dmap, dates = fetch_index_kline(ic)
        idx_kline[ik] = (dmap, dates)
        print(f"  {ik} ({ic}): {len(dates)} trading days ({dates[0]}~{dates[-1]})")
        time.sleep(0.4)

    # ---- 2. removals (constituent diff, cached) ----
    print("\n[2/5] detecting removals across semiannual rebalances (hs300/sz50/zz500)...")
    all_removals: list[dict] = []
    for ik in INDEX_QUERY:
        print(f"  --- {ik} ---")
        rems = get_removals(ik)
        all_removals.extend(rems)
    print(f"\n  TOTAL removals (all indices, all rebalances): {len(all_removals)}")
    eff_dates_all = sorted(set(r["effective_date"] for r in all_removals))
    if eff_dates_all:
        print(f"  distinct effective dates: {len(eff_dates_all)} ({eff_dates_all[0]}~{eff_dates_all[-1]})")
        print(
            f"  ⚠ 结构性限制: 半年一次 rebalance → per-day-mean t N_days={len(eff_dates_all)} "
            f"< 60 → 预期 underpowered (诚实标注)"
        )
    else:
        print("  无 removals 检出 → no-data")
        _final_summary(0, 0, 0.0, 0.0, 0.0, "no-data", "No removals detected from constituent diff")
        bs.logout()
        return

    # ---- 3. kline for removals (cache + fetch) ----
    print("\n[3/5] loading kline cache + fetching missing bars (effective-3..effective+15)...")
    code_map = load_kline_cache()
    print(f"  cache: {len(code_map)} codes")
    fetch_cache = load_fetch_cache()
    picks_by_window = build_picks(all_removals, code_map, fetch_cache, idx_kline, do_fetch=True)
    save_fetch_cache(fetch_cache)

    # ---- 4. BHAR analysis per window ----
    print("\n[4/5] computing BHAR (T5 / T10) + verdict cascade...")
    results: dict[str, dict] = {}
    for wname, _wn in WINDOWS:
        r = analyze_window_bhar(wname, picks_by_window.get(wname, []))
        results[wname] = r
        if r.get("n_picks", 0) == 0:
            continue
        verdict = verdict_bhar_gated(r)
        r["verdict"] = verdict
        print(f"\n  >>> HONEST VERDICT ({wname}): {verdict}")
        print(f"  >>> scope 注: 测 post-removal bounce (effective 后), 非 Shleifer")
        print(f"      announcement→effective pre-effective run-up (无 announcement 日数据).")
        print(f"      单事件策略 ≠ 事件驱动/短线有/无 edge (禁止外推).")

    # ---- 5. DSR + summary ----
    print(f"\n{'=' * 72}\n[5/5] overfitting check + summary")
    print(f"{'=' * 72}")
    primary = results.get("T5")
    if primary and primary.get("n_picks", 0) > 0:
        print(f"\n  primary window: T5")
        print(
            f"    n_events={primary['n_events']} n_dates={primary['n_dates']} "
            f"BHAR_gross={primary['bhar_gross']}% BHAR_net={primary['bhar_net']:.3f}%"
        )
        print(f"    day_t={primary['day_t']} p_raw={primary['p_raw']} Bonf×{CROSS_STRATEGY_N}={primary['p_bonf']}")
        print(f"    [descriptive raw stock_ret={primary['raw_stock_ret_mean']}% — market beta, NOT gated]")
        if primary["wf_status"] == "ok":
            print(
                f"    walk-forward: train={primary['wf_train_bhar']}% "
                f"test={primary['wf_test_bhar']}% test_p={primary['wf_test_p']} "
                f"(n_test_dates={primary['wf_n_test_dates']})"
            )
        print(f"    verdict: {primary.get('verdict', '?')}")

    print(f"\n  --- DSR/PBO 适用性 ---")
    if primary and primary.get("bhar_std", 0) > 0:
        n_trials = CROSS_STRATEGY_N * len(WINDOWS)  # ×4 strategies-variants ×2 windows
        dsr = estimate_dsr(primary["bhar_gross"], primary["bhar_std"], primary["n_events"], n_trials)
        print(f"  DSR estimate (event-level Sharpe, haircut):")
        print(
            f"    event Sharpe={dsr['event_sharpe']} ann Sharpe={dsr['ann_sharpe']} "
            f"expected_max_sr(n_trials={n_trials})={dsr['expected_max_sr']} "
            f"DSR_approx={dsr['dsr_approx']}"
        )
        if dsr["dsr_approx"] < 0:
            print(f"    → DSR<0: 多重检验校正后 Sharpe 不显著 (overfitting 风险)")
        else:
            print(f"    → DSR>0: 校正后仍正 (但须 walk-forward + n_dates≥60 确认)")
    print(f"  PBO (Probability of Backtest Overfitting) 需 combinatorial CV n>=1000 trades;")
    print(f"  本设计 n_events~{primary['n_events'] if primary else 0}, walk-forward 半 ~6 dates → PBO 不可行。")
    print(f"  → 多重检验校正已通过 Bonferroni ×{CROSS_STRATEGY_N} 体现。")

    # final summary
    if primary and primary.get("n_picks", 0) > 0:
        v = primary.get("verdict", "exploratory")
        _final_summary(
            primary["n_events"],
            primary["n_dates"],
            primary["bhar_gross"],
            primary["bhar_net"],
            primary["p_bonf"],
            v,
            f"primary T5: BHAR_gross={primary['bhar_gross']}% (raw stock_ret="
            f"{primary['raw_stock_ret_mean']}% market-beta-ungated) "
            f"net={primary['bhar_net']:.3f}% day_t={primary['day_t']} "
            f"Bonf×{CROSS_STRATEGY_N}={primary['p_bonf']:.4f} "
            f"n_dates={primary['n_dates']}(<60 underpowered) "
            f"wf[test_BHAR={primary['wf_test_bhar']}% p={primary['wf_test_p']}] "
            f"| 调入 T10 -0.655% reversal → 调出 bounce 对称假设 "
            f"| verdict GATE BHAR 非 raw EV (除权除息教训) "
            f"| survivorship: 调出股=decline/ST 剔除非winner, 缺bar偏存活 "
            f"| 禁止外推: 单事件≠事件驱动/短线有/无edge",
        )
    else:
        _final_summary(0, 0, 0.0, 0.0, 0.0, "no-data", "No valid BHAR picks after matching removals to kline")

    bs.logout()


def _final_summary(
    n_events: int, n_dates: int, bhar_gross: float, bhar_net: float, p_bonf: float, verdict: str, key_finding: str
) -> None:
    print(f"\n{'=' * 72}")
    print(f"[FINAL SUMMARY]")
    print(f"{'=' * 72}")
    print(f"策略: 指数调出 post-removal bounce (hs300/sz50/zz500 removals)")
    print(
        f"数据: baostock 历史成份股 diff (2018-2026, 3 rebalance baostock gap) + "
        f"kline cache + baostock 补缺 fetch + matched index kline"
    )
    print(f"  entry=effective+1 open, exit=effective+5/+10 close, BHAR vs 同指数")
    print(f"  verdict cascade GATE BHAR (非 raw EV — 除权除息 cascade flaw 教训)")
    print(
        f"  n_events={n_events} n_dates={n_dates} BHAR_gross={bhar_gross}% "
        f"BHAR_net={bhar_net:.3f}% Bonf×{CROSS_STRATEGY_N}={p_bonf:.4f}"
    )
    print(f"verdict: {verdict}")
    print(f"key: {key_finding}")
    print(f"诚实约束: post-removal 口径 (非 announcement pre-effective); n_dates<60 结构性 underpowered;")
    print(f"          调出含 selection (指数公司剔除 decline/ST/退市, 非 winner; 缺 bar 偏存活) — 已审。")
    print(f"禁止外推: 单事件策略 ≠ 事件驱动有/无 edge ≠ 短线有/无 edge。")


if __name__ == "__main__":
    main()
