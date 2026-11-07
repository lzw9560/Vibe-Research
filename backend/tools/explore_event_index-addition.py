# -*- coding: utf-8 -*-
"""指数成份股调整（调入效应）事件驱动回测——A 股 OOS。

策略假设 (来自任务): 指数调入股公告/生效后, 被动资金 forced buying → price pressure,
调入股 T+1/T+5/T+10 BHAR vs 同期 matched index 异常收益为正, 可交易。

数据现状 (2026-10-06 实测):
- baostock query_hs300/sz50/zz500_stocks(date) 返历史成份股 (2018 vs 2024 hs300: 216 重叠,
  168 变动 → 真 historical)。格式 ['updateDate','code(sh.600000)','code_name']。
- baostock 历史成份股有 GAP: 2021-06 / 2021-12 / 2022-12 三个 rebalance 全 probe 0 变动
  (baostock 返 stale snapshot) → 这 3 个 rebalance 不可用, 有效 event dates 更少。
- kline cache (baostock_kline_cache.db, 5248 codes): 调入股覆盖率低——cache 按 constituent
  snapshot 增量构建, 调入股常仅从更晚的 snapshot 起有数据。实测 hs300 249 additions 仅 63
  在 anchor 日有 bar → 须 baostock fetch 补缺 (effective-3~effective+15 窗口)。
- index kline (sh.000300/sh.000016/sh.000905) baostock 可取 (open+close), 作 BHAR benchmark。

诚实约束 (§44 v3):
- anchor = EFFECTIVE date (非 announcement date——baostock 无 announcement 日, 用 effective
  避 look-ahead; announcement 日 T+1 open 须外部日历, 不臆造)。
- entry = effective+1 open (T+1 open, 非收盘, realistic fill)。
- exit = effective+5 / effective+10 close (close_ev 口径)。
- BHAR = stock_ret - matched_index_ret (同窗口), 非 raw return (隔离市场漂移)。
- per-day-mean t (按 effective date 聚类——同 rebalance 多股同日相关)。结构性 N_days 限制:
  半年一次 rebalance, 8 年 ~13-16 个 event dates < 60 → per-day t underpowered (诚实标注)。
- Bonferroni ×4 (cross-strategy: index-addition × dividend, ×2 variants basic+regime)。
- walk-forward OOS (按 effective date 时序分半) + train_ev>0。
- survivorship: 调入股是指数公司选定 (selection by index provider), 非散户选股 winner,
  但调入本身是 selection (审: 调入股常已大涨才被纳入→可能含 momentum/survivorship)。
- 禁止外推: 单事件策略 ≠ 事件驱动有/无 edge ≠ 短线有/无 edge。
- post-inclusion 测的是 effective 后漂移, 非 Shleifer announcement→effective run-up
  (后者须 announcement 日, 无数据)。若 post-inclusion 漂移为负 (reversal), 仍是有意义发现。
"""

from __future__ import annotations
import json
import sqlite3
import statistics
import time
import calendar
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from math import erf, sqrt

import baostock as bs

# import shared helpers (DRY)
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
FETCH_CACHE = DATA / "_idx_add_fetch_cache.json"  # 本地缓存 baostock 补缺 kline
REGIME_FILE = DATA / "index_ma20_regime.json"

# matched index per source index
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

# 事件窗口 (relative to effective date, in trading days)
WINDOWS = [
    ("T5", 5),  # entry=eff+1 open, exit=eff+5 close  (4 trading-day hold)
    ("T10", 10),  # entry=eff+1 open, exit=eff+10 close (9 trading-day hold)
]

CROSS_STRATEGY_N = 4  # Bonferroni ×4 (index-addition × dividend × basic+regime)


# ---------- baostock constituent queries ----------


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
    Returns (effective_date, old_constituents) or None if no change found (baostock gap)."""
    fri = second_friday(year, month)
    y, m, d = int(fri[:4]), int(fri[5:7]), int(fri[8:10])
    fdate = date(y, m, d)
    # probe Friday, then +1..+9 days (Monday after 2nd Friday = day +3; wider for safety)
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


def get_additions(index_key: str, do_fetch_missing: bool = True) -> list[dict]:
    """For each semiannual rebalance, find effective date + additions (in new, not in old).
    Returns list of {code, code6, effective_date, index_key, direction:'add'}."""
    additions: list[dict] = []
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
            added = new - old
            removed = old - new
            for c in added:
                additions.append(
                    {
                        "code": c,
                        "code6": c.split(".")[1],
                        "effective_date": eff,
                        "index_key": index_key,
                        "direction": "add",
                    }
                )
            print(f"  [{index_key} {year}-{month:02d}] eff={eff} added={len(added)} removed={len(removed)}")
    return additions


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


def get_kline_for_addition(
    add: dict, code_map: dict, fetch_cache: dict, do_fetch: bool = True
) -> dict[str, dict] | None:
    """Get kline bars around effective date. Cache first, then baostock fetch if gap.
    Returns {date: bar} covering effective-3 .. effective+15, or None."""
    code6 = add["code6"]
    eff = add["effective_date"]
    # window: need effective-3 to effective+15 trading days (calendar +/- 25 days safe)
    eff_d = date(int(eff[:4]), int(eff[5:7]), int(eff[8:10]))
    start = (eff_d - timedelta(days=25)).isoformat()
    end = (eff_d + timedelta(days=30)).isoformat()

    # 1. cache
    dmap = code_map.get(code6)
    if dmap:
        # check coverage: need a bar at eff (or nearest) AND eff+15ish
        has_eff = any(d >= eff and d <= end for d in dmap)
        if has_eff and any(d >= start for d in dmap):
            # cache covers the window (rough check)
            # verify we actually have bars near eff
            near = [b for d, b in dmap.items() if start <= d <= end]
            if len(near) >= 10:
                return {b["date"]: b for b in near}

    # 2. fetch cache (local JSON)
    fc_key = f"{add['code']}#{start}#{end}"
    if fc_key in fetch_cache:
        return fetch_cache[fc_key]

    # 3. baostock fetch
    if not do_fetch:
        return None
    bars = fetch_kline_baostock(add["code"], start, end)
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


def trading_day_index(dates: list[str]) -> dict[str, int]:
    return {d: i for i, d in enumerate(dates)}


def compute_bhar(
    add: dict, bars: dict[str, dict], idx_bars: dict[str, dict], idx_dates: list[str], window_n: int
) -> dict | None:
    """BHAR for one addition.
    entry = effective+1 open, exit = effective+N close (N=window_n).
    stock_ret = (close_N - open_1) / open_1
    index_ret = (idx_close_N - idx_open_1) / idx_open_1
    BHAR = stock_ret - index_ret (in %).
    Returns {bhar, stock_ret, index_ret, entry_date, exit_date} or None if data gap.
    """
    eff = add["effective_date"]
    di = trading_day_index(idx_dates)
    eff_idx = di.get(eff)
    if eff_idx is None:
        # map to nearest trading day on_or_after eff
        import bisect

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

    # stock bars
    s_entry = bars.get(entry_date)
    s_exit = bars.get(exit_date)
    if s_entry is None or s_exit is None:
        return None
    s_open = s_entry.get("open")
    s_close = s_exit.get("close")
    if s_open is None or s_close is None or s_open <= 0:
        return None
    stock_ret = (s_close - s_open) / s_open * 100

    # index bars (matched)
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
        "code": add["code"],
        "code6": add["code6"],
        "index_key": add["index_key"],
    }


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


# ---------- per-event t (secondary, descriptive) ----------


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


# ---------- main ----------


def main() -> None:
    _login()
    print("=" * 72)
    print("指数成份股调整（调入效应）事件驱动回测")
    print("=" * 72)
    print("anchor = effective date (no look-ahead; baostock 无 announcement 日)")
    print("entry = effective+1 open, exit = effective+N close, BHAR vs matched index")
    print(f"Bonferroni ×{CROSS_STRATEGY_N} (cross-strategy: idx-add × dividend × basic+regime)")
    print()

    # ---- 1. index kline (benchmark + calendar) ----
    print("[1/5] fetching matched index kline (sh.000300/sh.000016/sh.000905)...")
    idx_kline: dict[str, tuple[dict[str, dict], list[str]]] = {}
    for ik, ic in INDEX_BENCH.items():
        dmap, dates = fetch_index_kline(ic)
        idx_kline[ik] = (dmap, dates)
        print(f"  {ik} ({ic}): {len(dates)} trading days ({dates[0]}~{dates[-1]})")
        time.sleep(0.4)

    # ---- 2. additions (constituent diff) ----
    print("\n[2/5] detecting additions across semiannual rebalances (hs300/sz50/zz500)...")
    all_additions: list[dict] = []
    for ik in INDEX_QUERY:
        print(f"  --- {ik} ---")
        adds = get_additions(ik)
        all_additions.extend(adds)
    print(f"\n  TOTAL additions (all indices, all rebalances): {len(all_additions)}")
    eff_dates_all = sorted(set(a["effective_date"] for a in all_additions))
    print(
        f"  distinct effective dates: {len(eff_dates_all)} "
        f"({eff_dates_all[0] if eff_dates_all else '-'}~{eff_dates_all[-1] if eff_dates_all else '-'})"
    )
    print(
        f"  ⚠ 结构性限制: 半年一次 rebalance → per-day-mean t N_days={len(eff_dates_all)} "
        f"< 60 → 预期 underpowered (诚实标注)"
    )

    # ---- 3. kline for additions (cache + fetch) ----
    print("\n[3/5] loading kline cache + fetching missing bars (effective-3..effective+15)...")
    code_map = load_kline_cache()
    print(f"  cache: {len(code_map)} codes")
    fetch_cache = load_fetch_cache()
    n_cached = n_fetched = n_missing = 0
    addition_bars: dict[int, dict[str, dict]] = {}  # idx into all_additions -> bars
    for i, add in enumerate(all_additions):
        bars = get_kline_for_addition(add, code_map, fetch_cache, do_fetch=True)
        if bars is None or len(bars) < 5:
            n_missing += 1
            continue
        addition_bars[i] = bars
        if any(add["code"] + "#" in k for k in fetch_cache):
            n_fetched += 1
        else:
            n_cached += 1
    save_fetch_cache(fetch_cache)
    print(
        f"  usable additions: {len(addition_bars)}/{len(all_additions)} "
        f"(cached={n_cached} fetched={n_fetched} missing={n_missing})"
    )

    # ---- 4. BHAR per window ----
    print("\n[4/5] computing BHAR (T+5 / T+10)...")
    for wname, wn in WINDOWS:
        print(f"\n{'=' * 60}")
        print(f"窗口: {wname} (entry=eff+1 open, exit=eff+{wn} close)")
        print(f"{'=' * 60}")
        bhars: list[float] = []
        picks: list[dict] = []
        by_date: dict[str, list[float]] = defaultdict(list)
        by_index: dict[str, list[float]] = defaultdict(list)
        for i, add in enumerate(all_additions):
            bars = addition_bars.get(i)
            if bars is None:
                continue
            ik = add["index_key"]
            idx_bars, idx_dates = idx_kline[ik]
            r = compute_bhar(add, bars, idx_bars, idx_dates, wn)
            if r is None:
                continue
            bhars.append(r["bhar"])
            picks.append(r)
            by_date[r["effective_date"]].append(r["bhar"])
            by_index[ik].append(r["bhar"])

        if not picks:
            print("  无可计算 BHAR → no-data")
            continue

        # per-event stats (descriptive)
        ev = ev_stats(bhars)
        pet = per_event_t(bhars)
        net_ev = ev["ev"] - COST * 100
        print(
            f"\n  per-event: n={ev['n']} BHAR_mean={ev['ev']}% std={ev['std']}% "
            f"WR={ev['wr']}% t={ev['t']} CI[{ev['ci_lo']},{ev['ci_hi']}]"
        )
        print(f"  per-event t: mean={pet['mean']}% t={pet['t']} p_one_sided={pet['p_one_sided']}")
        print(f"  net BHAR (after {COST * 100:.1f}% cost): {net_ev:.3f}%")

        # per-day-mean t (PRIMARY inferential, clustered by effective date)
        dt = day_paired_t(by_date)
        print(f"\n  per-day-mean t (PRIMARY, cluster by effective date):")
        print(
            f"    n_days={dt['n_days']} mean={dt['mean']}% std={dt['std']}% t={dt['t']} p_one_sided={dt['p_one_sided']}"
        )
        p_raw = dt["p_one_sided"]
        p_bonf = bonferroni_p(p_raw, CROSS_STRATEGY_N)
        print(
            f"    Bonferroni ×{CROSS_STRATEGY_N}: p={p_bonf:.6f} ({'PASS' if p_bonf < ALPHA else 'FAIL'} @ α={ALPHA})"
        )

        # per-index breakdown
        print(f"\n  per-index BHAR:")
        for ik, rs in by_index.items():
            s = ev_stats(rs)
            print(f"    {ik}: n={s['n']} mean={s['ev']}% WR={s['wr']}% t={s['t']}")

        # regime stratification
        regime_map = load_regime()
        print(f"\n  --- regime stratification (by entry_date regime) ---")
        for rname in ("strong", "weak", "range"):
            r_rets = [p["bhar"] for p in picks if regime_map.get(p["entry_date"]) == rname]
            if not r_rets:
                continue
            s = ev_stats(r_rets)
            print(f"    {rname}: n={s['n']} mean={s['ev']}% WR={s['wr']}% t={s['t']}")

        # walk-forward (chronological by effective date)
        print(f"\n  --- walk-forward OOS (chronological split by effective date) ---")
        eff_d_sorted = sorted(by_date.keys())
        if len(eff_d_sorted) >= 4:
            mid = len(eff_d_sorted) // 2
            train_dates = set(eff_d_sorted[:mid])
            test_dates = set(eff_d_sorted[mid:])
            train_rets = [v for d in train_dates for v in by_date[d]]
            test_rets = [v for d in test_dates for v in by_date[d]]
            tr_by_d = {d: by_date[d] for d in train_dates}
            te_by_d = {d: by_date[d] for d in test_dates}
            tr_ev = ev_stats(train_rets)
            te_ev = ev_stats(test_rets)
            tr_dt = day_paired_t(tr_by_d)
            te_dt = day_paired_t(te_by_d)
            print(
                f"    train: n_dates={len(train_dates)} n={tr_ev['n']} BHAR={tr_ev['ev']}% t={tr_dt['t']} (day-paired)"
            )
            print(
                f"    test:  n_dates={len(test_dates)} n={te_ev['n']} "
                f"BHAR={te_ev['ev']}% t={te_dt['t']} p={te_dt['p_one_sided']}"
            )
            decay = (tr_ev["ev"] - te_ev["ev"]) / abs(tr_ev["ev"]) * 100 if tr_ev["ev"] != 0 else 0
            print(f"    decay: {decay:.0f}% (train→test)")
            wf_status = "ok"
            wf_train_ev = tr_ev["ev"]
            wf_test_ev = te_ev["ev"]
            wf_test_p = te_dt["p_one_sided"]
            wf_n_test_dates = len(test_dates)
        else:
            print(f"    too few effective dates ({len(eff_d_sorted)}) for walk-forward")
            wf_status = "too_few_dates"
            wf_train_ev = wf_test_ev = wf_test_p = 0.0
            wf_n_test_dates = 0

        # ---- verdict cascade (§44 v3) ----
        print(f"\n  --- verdict cascade ({wname}) ---")
        verdict = "exploratory"
        if ev["ev"] < 0:
            print(f"    gross BHAR={ev['ev']}% < 0 → no positive post-inclusion effect")
            verdict = "edge-falsified" if dt["n_days"] >= 30 else "underpowered"
        elif dt["n_days"] < 60:
            print(f"    n_days={dt['n_days']} < 60 → UNDERPOWERED (结构性: 半年 rebalance, 8 年仅 ~13-16 event dates)")
            verdict = "underpowered"
        elif p_bonf >= ALPHA:
            print(f"    Bonferroni p={p_bonf} >= {ALPHA} → not significant")
            verdict = "edge-falsified"
        elif net_ev <= 0:
            print(f"    net BHAR={net_ev}% <= 0 → gross edge eaten by cost")
            verdict = "edge-falsified"
        elif wf_status == "ok":
            if wf_train_ev <= 0:
                print(f"    train_BHAR={wf_train_ev}% <= 0 → edge not in train (regime overfit)")
                verdict = "exploratory"
            elif wf_test_ev <= 0:
                print(f"    walk-forward test_BHAR={wf_test_ev}% <= 0 → falsified")
                verdict = "edge-falsified"
            else:
                wf_p_bonf = bonferroni_p(wf_test_p, CROSS_STRATEGY_N)
                if wf_p_bonf >= ALPHA:
                    print(
                        f"    OOS BHAR>0 but test p={wf_test_p} Bonf×{CROSS_STRATEGY_N}"
                        f"={wf_p_bonf} >= {ALPHA} → not significant OOS"
                    )
                    verdict = "exploratory"
                else:
                    print(f"    → EDGE-CONFIRMED: BHAR>0, Bonf PASS, OOS significant")
                    verdict = "edge-confirmed"
        print(f"\n  >>> HONEST VERDICT ({wname}): {verdict}")
        print(f"  >>> scope 注: 测的是 post-inclusion 漂移 (effective 后), 非 Shleifer")
        print(f"      announcement→effective run-up (无 announcement 日数据). 单事件策略")
        print(f"      ≠ 事件驱动/短线有/无 edge (禁止外推).")

        # store for final summary
        globals()[f"_last_{wname}"] = {
            "n_events": ev["n"],
            "n_dates": dt["n_days"],
            "bhar": ev["ev"],
            "net_ev": net_ev,
            "p_raw": p_raw,
            "p_bonf": p_bonf,
            "wf_status": wf_status,
            "wf_train_ev": wf_train_ev,
            "wf_test_ev": wf_test_ev,
            "wf_test_p": wf_test_p,
            "wf_n_test_dates": wf_n_test_dates,
            "verdict": verdict,
            "day_t": dt["t"],
        }

    # ---- 5. DSR/PBO + summary ----
    print(f"\n{'=' * 72}\n[5/5] overfitting check + summary")
    print(f"{'=' * 72}")
    # use T5 as primary
    primary = globals().get("_last_T5")
    if primary:
        print(f"\n  primary window: T5")
        print(
            f"    n_events={primary['n_events']} n_dates={primary['n_dates']} "
            f"BHAR={primary['bhar']}% net={primary['net_ev']}%"
        )
        print(f"    day_t={primary['day_t']} p_raw={primary['p_raw']} Bonf×{CROSS_STRATEGY_N}={primary['p_bonf']}")
        if primary["wf_status"] == "ok":
            print(
                f"    walk-forward: train={primary['wf_train_ev']}% "
                f"test={primary['wf_test_ev']}% test_p={primary['wf_test_p']} "
                f"(n_test_dates={primary['wf_n_test_dates']})"
            )
        print(f"    verdict: {primary['verdict']}")

    print(f"\n  --- DSR/PBO 适用性 ---")
    print(f"  DSR (Deflated Sharpe) 设计用于规则时间序列策略 Sharpe; 本事件研究 n_dates~13-16")
    print(f"  (半年度 rebalance), 非规则日频 → DSR 不直接适用。")
    print(f"  PBO (Probability of Backtest Overfitting) 需 combinatorial CV n>=1000 trades 典型;")
    print(f"  本设计 n_events~{primary['n_events'] if primary else 0}, walk-forward 半 ~6 dates → PBO 不可行。")
    print(f"  → 多重检验校正已通过 Bonferroni ×{CROSS_STRATEGY_N} 体现 (覆盖 2 策略 × 2 变体)。")

    print(f"\n{'=' * 72}\n[FINAL SUMMARY]")
    print(f"{'=' * 72}")
    print(f"策略: 指数调入 post-inclusion 漂移 (hs300/sz50/zz500 additions)")
    print(f"数据: baostock 历史成份股 (2018-2026, 3 个 rebalance baostock gap) + ")
    print(f"      kline cache + baostock 补缺 fetch + matched index kline")
    if primary:
        print(
            f"primary T5: n_events={primary['n_events']} BHAR={primary['bhar']}% "
            f"n_dates={primary['n_dates']} day_t={primary['day_t']} "
            f"Bonf×{CROSS_STRATEGY_N}={primary['p_bonf']:.4f}"
        )
        print(f"           net_BHAR={primary['net_ev']}% wf[test_ev={primary['wf_test_ev']}% p={primary['wf_test_p']}]")
        print(f"verdict: {primary['verdict']}")
    print(f"诚实约束: post-inclusion 口径 (非 announcement run-up); n_dates<60 结构性 underpowered;")
    print(f"          调入含 selection (指数公司选定, 非 winner 但可能含 momentum) — 已审。")
    print(f"禁止外推: 单事件策略 ≠ 事件驱动有/无 edge ≠ 短线有/无 edge。")

    bs.logout()


if __name__ == "__main__":
    main()
