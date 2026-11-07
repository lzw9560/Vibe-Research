# -*- coding: utf-8 -*-
"""除权除息填权/贴权事件驱动策略 — OOS backtest with §44 v3 anti-fake-edge.

策略假设: 除权除息日 T+1 open 买, T+3/T+5 close 卖. 填权 (涨回) → 正 EV, 贴权 → 负 EV.
Regime 假设: strong regime → 填权 (正 EV), weak regime → 贴权 (负 EV).

数据 (2026-10-06 实测):
- 除权日: baostock query_dividend_data(code, year) → dividOperateDate (cached in
  dividend_events_cache.json, 由 fetch_dividend_data.py 后台拉取).
- K线: baostock_kline_cache.db, 5248 codes, 2018-01-02~2026-09-23. 前复权 (adjustflag=2).
  关键: 前复权对除权日后的收益无影响 (调整因子在 entry/exit 间抵消, 实测 000006 T+1→T+3
  未复权 4.87% vs 前复权 4.88% 差 0.006%). → post-ex 收益 adjustment-invariant, cache 可用.
  但仅 786 codes 有 2018 起完整历史 (其余仅 ~179 天), 限定 long-range codes.
- Regime: index_ma20_regime.json, 上证综指 close + strong/weak (5502 天).

§44 v3 anti-fake-edge (过严口径):
- realistic entry: 除权日 T+1 open (非 T close — T close 已除权, 散户 T+1 才能买)
- close_ev: T+1 open → T+3/T+5 close (非 open_ev — open_ev 有 T+1 日内泄漏)
- per-day-mean t: 同日多笔聚成 day-mean, effective N = n_ex_dates 非 n_events
- Bonferroni ×4: 2 策略 (dividend + index-addition) × 2 变体 (basic + regime)
  另加 ×2 windows (T+3, T+5) → 总 ×8 报告; verdict 用 ×4 (task spec).
- walk-forward OOS: 前半 train → 后半 test + train_ev>0 检查
- BHAR vs equal-weight market (isolate ex-dividend effect vs market beta)
  FIX 2026-10-07: was close-to-close (t1_close ref), but entry is T+1 open.
  Now open-to-close: Event=(t_k_close-t1_open)/t1_open, Market=EW same window.
  R12: equal-weight market benchmark (size-matched, not cap-weighted 沪深300).
- regime 分层 (strong/weak)
- DSR 估算 (event-level Sharpe, multiple-testing haircut)
- survivorship: 除权股全市场非选股 winner, 但除权本身是公司决策须审
- 禁止外推: 除权除息单事件策略 ≠ 事件驱动有/无 edge ≠ 短线有/无 edge
"""
from __future__ import annotations
import json
import sys
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt

# import shared helpers (DRY) — reuse statistical functions
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools._factor_helpers import (  # noqa: E402
    ev_stats, day_paired_t, bonferroni_p, norm_sf_positive, ALPHA, COST,
    verdict_for,
)

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
DIV_CACHE = DATA / "dividend_events_cache.json"
REGIME_FILE = DATA / "index_ma20_regime.json"

# Event windows: (name, exit_offset) — entry always T+1 open, exit T+n close
WINDOWS = [
    ("t3", 3),   # T+1 open → T+3 close (2 trading days holding)
    ("t5", 5),   # T+1 open → T+5 close (4 trading days holding)
]

# Bonferroni: 2 strategies × 2 variants (basic + regime) = ×4 (task spec)
# Additional ×2 for 2 windows (t3, t5) → ×8 total reported
N_CROSS_STRATEGY = 4   # task: 2 策略 × 2 变体
N_WINDOWS = 2


# ---------- data loading ----------

def load_dividend_events() -> list[dict]:
    """Load cached dividend events. Returns list of {code, ex_date, cash, stocks, ...}."""
    if not DIV_CACHE.exists():
        print(f"[ERROR] dividend cache not found: {DIV_CACHE}")
        print("        Run: python tools/fetch_dividend_data.py (background ~24 min)")
        sys.exit(1)
    with open(DIV_CACHE) as f:
        events = json.load(f)
    print(f"[data] dividend events loaded: {len(events)} from {DIV_CACHE.name}")
    return events


def load_kline_db() -> tuple[dict[str, dict[str, dict]], set[str]]:
    """Load kline cache. Returns (code -> {date: bar}, all_dates set)."""
    import sqlite3
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
    print(f"[data] kline cache: {len(code_map)} codes, {len(all_dates)} unique dates")
    return code_map, all_dates


def load_regime() -> tuple[dict[str, dict], list[str]]:
    """Load 上证综指 close + regime. Returns (date -> bar, sorted trading days)."""
    with open(REGIME_FILE) as f:
        raw = json.load(f)
    bars = {d: v for d, v in raw.items() if isinstance(v, dict) and "close" in v}
    days = sorted(bars.keys())
    print(f"[data] regime: {len(days)} trading days ({days[0]}~{days[-1]})")
    return bars, days


# ---------- equal-weight market benchmark (R12: size-matched) ----------

_ew_cache: dict[tuple[str, str], float | None] = {}


def build_date_index(
    code_map: dict[str, dict[str, dict]],
    needed_dates: set[str],
) -> dict[str, dict[str, dict]]:
    """Build {date: {code: bar}} inverted index, only for needed dates.

    R12: equal-weight market benchmark — gives small-cap stocks equal
    representation (unlike market-cap-weighted 上证综指/沪深300).
    Dividend stocks may skew small-cap, so equal-weight is the proper
    size-matched benchmark.
    """
    date_index: dict[str, dict[str, dict]] = defaultdict(dict)
    for code, dmap in code_map.items():
        for d, bar in dmap.items():
            if d in needed_dates:
                date_index[d][code] = bar
    print(f"[data] date_index built: {len(date_index)} dates "
          f"(R12 equal-weight market benchmark)")
    return dict(date_index)


def ew_market_return(
    t1_date: str, exit_date: str,
    date_index: dict[str, dict[str, dict]],
) -> float | None:
    """Equal-weight market return from t1 open to exit close (open-to-close).

    Matches actual entry window (T+1 open → T+n close).
    Equal-weight = mean of individual stock returns, not return of mean prices.
    Cached by (t1_date, exit_date) pair for efficiency.
    """
    key = (t1_date, exit_date)
    if key in _ew_cache:
        return _ew_cache[key]
    t1_bars = date_index.get(t1_date, {})
    exit_bars = date_index.get(exit_date, {})
    if not t1_bars or not exit_bars:
        _ew_cache[key] = None
        return None
    rets: list[float] = []
    for code, t1_bar in t1_bars.items():
        exit_bar = exit_bars.get(code)
        if exit_bar is None:
            continue
        o = t1_bar.get("open")
        c = exit_bar.get("close")
        if o is not None and c is not None and o > 0:
            rets.append((c - o) / o * 100)
    mret = sum(rets) / len(rets) if rets else None
    _ew_cache[key] = mret
    return mret


# ---------- pick construction ----------

def is_locked_bar(bar: dict) -> bool:
    """Check if bar is 一字 (locked at single price, can't buy).
    open≈high≈low within 0.1% → locked (一字涨停 or 一字跌停).
    Note: ex-dividend limit calc differs (reference price adjusted), so use
    price-equality check instead of limit_for_code (safer for dividend dates)."""
    o = bar.get("open")
    h = bar.get("high")
    l = bar.get("low")
    if o is None or h is None or l is None or o <= 0:
        return False
    return abs(o - h) / o < 0.001 and abs(o - l) / o < 0.001


def build_dividend_picks(
    events: list[dict],
    code_map: dict[str, dict[str, dict]],
    calendar: list[str],
) -> list[dict]:
    """Build picks: for each dividend ex-date, entry=T+1 open, exit=T+3/T+5 close.

    Skip if:
    - ex_date not in calendar or too close to end (< 6 trading days buffer)
    - code not in kline cache
    - T+1/T+3/T+5 bars missing or invalid
    - T+1 is locked (一字, can't buy)

    Returns picks with: code, ex_date, t1_date, t3_date, t5_date,
    entry (T+1 open), t1_bar, t3_bar, t5_bar, t1_close, regime, cash, stocks.
    """
    date_idx = {d: i for i, d in enumerate(calendar)}
    picks: list[dict] = []

    for ev in events:
        code = ev["code"]
        ex_date = ev["ex_date"]
        d_idx = date_idx.get(ex_date)
        if d_idx is None or d_idx + 6 >= len(calendar):
            continue  # need T+1 through T+5 minimum

        dmap = code_map.get(code)
        if not dmap:
            continue

        t1_date = calendar[d_idx + 1]
        t3_date = calendar[d_idx + 3]
        t5_date = calendar[d_idx + 5]

        t1_bar = dmap.get(t1_date)
        t3_bar = dmap.get(t3_date)
        t5_bar = dmap.get(t5_date)
        if t1_bar is None or t3_bar is None or t5_bar is None:
            continue

        entry = t1_bar.get("open")
        if entry is None or entry <= 0:
            continue

        # skip locked T+1 (一字, can't buy)
        if is_locked_bar(t1_bar):
            continue

        # need valid closes for exit
        t3_close = t3_bar.get("close")
        t5_close = t5_bar.get("close")
        t1_close = t1_bar.get("close")
        if t3_close is None or t5_close is None or t1_close is None:
            continue
        if t3_close <= 0 or t5_close <= 0 or t1_close <= 0:
            continue

        picks.append({
            "code": code,
            "ex_date": ex_date,
            "t1_date": t1_date,
            "t3_date": t3_date,
            "t5_date": t5_date,
            "entry": entry,
            "t1_close": t1_close,
            "t3_close": t3_close,
            "t5_close": t5_close,
            "t1_bar": t1_bar,
            "t3_bar": t3_bar,
            "t5_bar": t5_bar,
            "cash": ev.get("cash_before_tax", 0),
            "stocks": ev.get("stocks_ps", 0),
            "div_type": _div_type(ev),
        })
    return picks


def _div_type(ev: dict) -> str:
    """Classify dividend type: cash (除息), stock (除权), both."""
    cash = ev.get("cash_before_tax", 0) or 0
    stocks = ev.get("stocks_ps", 0) or 0
    reserve = ev.get("reserve_to_stock", 0) or 0
    has_cash = cash > 0
    has_stock = stocks > 0 or reserve > 0
    if has_cash and has_stock:
        return "both"
    if has_stock:
        return "stock"
    return "cash"


# ---------- return functions ----------

def ev_t3(p: dict) -> float | None:
    """T+1 open → T+3 close. Raw EV (realistic entry, close_ev not open_ev)."""
    return (p["t3_close"] - p["entry"]) / p["entry"] * 100


def ev_t5(p: dict) -> float | None:
    """T+1 open → T+5 close."""
    return (p["t5_close"] - p["entry"]) / p["entry"] * 100


def bhar_t3(p: dict, date_index: dict[str, dict[str, dict]]) -> float | None:
    """BHAR T+1 open → T+3 close vs equal-weight market (open-to-close).

    FIX (2026-10-07): was close-to-close (t1_close as reference), but actual
    entry is T+1 open. Using t1_close missed T+1 intraday return (+0.207%),
    underestimating BHAR by +0.12%. Now uses open-to-close matching entry.

    Event_oc = (t3_close - t1_open) / t1_open  [open-to-close, matches entry]
    Market_oc = EW mean of (exit_close - t1_open) / t1_open across all stocks
    BHAR = Event_oc - Market_oc
    """
    mret = ew_market_return(p["t1_date"], p["t3_date"], date_index)
    if mret is None:
        return None
    ev_oc = (p["t3_close"] - p["entry"]) / p["entry"] * 100
    return ev_oc - mret


def bhar_t5(p: dict, date_index: dict[str, dict[str, dict]]) -> float | None:
    """BHAR T+1 open → T+5 close vs equal-weight market (open-to-close).

    FIX (2026-10-07): same reference mismatch as bhar_t3 — now open-to-close.
    """
    mret = ew_market_return(p["t1_date"], p["t5_date"], date_index)
    if mret is None:
        return None
    ev_oc = (p["t5_close"] - p["entry"]) / p["entry"] * 100
    return ev_oc - mret


# ---------- walk-forward (event-study adapted) ----------

def walk_forward_event(
    picks: list[dict],
    ret_fn,
    index_bars: dict[str, dict] | None = None,
) -> dict:
    """Walk-forward OOS: sort by ex_date, split half train/half test.
    ret_fn: (p, index_bars?) -> float | None. Returns train/test stats."""
    if not picks:
        return {"status": "no_picks"}
    ps = sorted(picks, key=lambda p: p["ex_date"])
    dates = sorted(set(p["ex_date"] for p in ps))
    if len(dates) < 4:
        return {"status": "too_few_dates", "n_dates": len(dates)}
    mid = len(dates) // 2
    train_dates = set(dates[:mid])
    test_dates = set(dates[mid:])

    def _rets(subset_dates: set[str]) -> tuple[list[float], dict[str, list[float]]]:
        rets: list[float] = []
        by_date: dict[str, list[float]] = defaultdict(list)
        for p in ps:
            if p["ex_date"] not in subset_dates:
                continue
            r = ret_fn(p, index_bars) if index_bars else ret_fn(p)
            if r is not None:
                rets.append(r)
                by_date[p["ex_date"]].append(r)
        return rets, by_date

    tr_rets, tr_by_date = _rets(train_dates)
    te_rets, te_by_date = _rets(test_dates)
    return {
        "status": "ok",
        "n_train": len(tr_rets), "n_test": len(te_rets),
        "n_train_dates": len(train_dates), "n_test_dates": len(test_dates),
        "train_ev": ev_stats(tr_rets),
        "test_ev": ev_stats(te_rets),
        "train_day_t": day_paired_t(tr_by_date),
        "test_day_t": day_paired_t(te_by_date),
    }


# ---------- regime stratification ----------

def stratify_by_regime(
    picks: list[dict], regime_bars: dict[str, dict]
) -> dict[str, list[dict]]:
    """Split picks by regime on ex_date. Returns {regime_name: [picks]}."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        rb = regime_bars.get(p["ex_date"])
        regime = rb.get("regime", "unknown") if rb else "unknown"
        buckets[regime].append(p)
    return dict(buckets)


# ---------- DSR estimation ----------

def estimate_dsr(ev_mean: float, ev_std: float, n_events: int,
                 n_trials: int) -> dict:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014) + MinTRL.

    Multiple-testing haircut: if annualized Sharpe exceeds the expected max
    Sharpe under H0 (no skill), the signal survives.

    DSR = Φ((SR_hat - E[max SR]) / σ(SR_hat))
    where E[max SR] = sqrt(2*ln(N)) * (1 - γ/(2*ln(N))), γ ≈ 0.5772
    σ(SR_hat) = sqrt(1/T), T = years of data
    MinTRL = (1 + (1-γ)*ln(N)) / SR_hat^2
    """
    import math
    EULER_GAMMA = 0.5772  # Euler-Mascheroni constant

    if ev_std <= 0 or n_events <= 0 or ev_mean <= 0:
        return {"event_sharpe": 0, "ann_sharpe": 0, "dsr": 0,
                "expected_max_sr": 0, "min_trl_years": 0,
                "actual_years": 0, "n_trials": n_trials,
                "survives": False}

    # per-event Sharpe (signal-to-noise, not annualized)
    event_sharpe = ev_mean / ev_std
    # A-share dividends ~1/yr per stock, events span ~8 years (2018-2025)
    n_years = 8
    events_per_year = max(n_events / n_years, 1)
    ann_sharpe = event_sharpe * sqrt(events_per_year)

    # Expected max SR under H0: E[max of N iid N(0,1)]
    if n_trials > 1:
        ln_n = math.log(n_trials)
        expected_max_sr = sqrt(2 * ln_n) * (1 - EULER_GAMMA / (2 * ln_n))
    else:
        expected_max_sr = 0

    # σ(SR_hat) = sqrt(1/T)
    sigma_sr = sqrt(1 / n_years) if n_years > 0 else 0

    # DSR = Φ((SR_hat - E[max SR]) / σ(SR_hat))
    if sigma_sr > 0:
        z = (ann_sharpe - expected_max_sr) / sigma_sr
        dsr = 0.5 * (1 + erf(z / sqrt(2)))
    else:
        dsr = 0

    # Minimum Track Record Length (years needed for significance)
    min_trl = ((1 + (1 - EULER_GAMMA) * math.log(n_trials)) / (ann_sharpe ** 2)
               if ann_sharpe > 0 and n_trials > 1 else 0)

    survives = ann_sharpe > expected_max_sr and dsr > 0.95

    return {
        "event_sharpe": round(event_sharpe, 4),
        "ann_sharpe": round(ann_sharpe, 3),
        "expected_max_sr": round(expected_max_sr, 4),
        "sigma_sr": round(sigma_sr, 4),
        "dsr": round(dsr, 4),
        "min_trl_years": round(min_trl, 1),
        "actual_years": n_years,
        "n_trials": n_trials,
        "survives": survives,
    }


# ---------- main analysis ----------

def analyze_window(
    name: str,
    picks: list[dict],
    ret_fn,
    index_bars: dict[str, dict] | None = None,
    ret_label: str = "EV",
) -> dict:
    """Run full analysis on one window/variant: EV stats + day-paired t + walk-forward."""
    print(f"\n{'=' * 70}")
    print(f"窗口: {name} (n_picks={len(picks)})  [{ret_label}]")
    print(f"{'=' * 70}")

    if not picks:
        print("  无 picks, 跳过")
        return {"name": name, "n_picks": 0}

    # ---- returns ----
    rets: list[float] = []
    by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        r = ret_fn(p, index_bars) if index_bars else ret_fn(p)
        if r is not None:
            rets.append(r)
            by_date[p["ex_date"]].append(r)

    if not rets:
        print("  无有效收益, 跳过")
        return {"name": name, "n_picks": 0}

    s = ev_stats(rets)
    med = statistics.median(rets) if rets else 0.0
    net = s["ev"] - COST * 100
    dt = day_paired_t(by_date)

    print(f"\n--- {ret_label} stats ---")
    print(f"  n={s['n']} n_dates={dt['n_days']} gross_{ret_label}={s['ev']}% "
          f"median={med:.3f}% WR={s['wr']}% std={s['std']}% "
          f"t={s['t']} CI[{s['ci_lo']},{s['ci_hi']}]")
    print(f"  net_{ret_label} (after {COST*100:.1f}% cost): {net:.3f}%")
    print(f"  day-paired t: n_days={dt['n_days']} mean={dt['mean']}% "
          f"t={dt['t']} p_one_sided={dt['p_one_sided']}")

    # ---- walk-forward ----
    print(f"\n--- walk-forward OOS (前半 train → 后半 test) ---")
    wf = walk_forward_event(picks, ret_fn, index_bars)
    if wf["status"] == "ok":
        tr = wf["train_ev"]
        te = wf["test_ev"]
        tr_dt = wf["train_day_t"]
        te_dt = wf["test_day_t"]
        print(f"  train: n={tr['n']} n_dates={wf['n_train_dates']} "
              f"EV={tr['ev']}% t={tr['t']} day_t={tr_dt['t']}")
        print(f"  test:  n={te['n']} n_dates={wf['n_test_dates']} "
              f"EV={te['ev']}% t={te['t']} day_t={te_dt['t']} "
              f"p={te_dt['p_one_sided']}")
        decay = ((tr["ev"] - te["ev"]) / abs(tr["ev"]) * 100
                 if tr["ev"] != 0 else 0)
        print(f"  decay: {decay:.0f}% (train→test)")
    else:
        print(f"  {wf['status']} (n_dates={wf.get('n_dates', 0)})")

    return {
        "name": name,
        "n_picks": len(picks),
        "n_events": s["n"],
        "n_dates": dt["n_days"],
        "gross_ev": s["ev"],
        "median_ev": round(med, 3),
        "net_ev": net,
        "ev_std": s["std"],
        "wr": s["wr"],
        "t_trade": s["t"],
        "day_t": dt["t"],
        "day_p": dt["p_one_sided"],
        "ci_lo": s["ci_lo"],
        "ci_hi": s["ci_hi"],
        "wf": wf,
    }


def main() -> None:
    # ---- load data ----
    events = load_dividend_events()
    code_map, _ = load_kline_db()
    regime_bars, calendar = load_regime()

    # ---- build picks ----
    print(f"\n[build] matching {len(events)} dividend events to kline cache...")
    picks = build_dividend_picks(events, code_map, calendar)
    n_ex_dates = len(set(p["ex_date"] for p in picks))
    print(f"[build] picks: {len(picks)} events across {n_ex_dates} ex-dates")
    if not picks:
        print("[verdict] no picks → no-data")
        _print_summary("dividend-exright", "no-data", 0, 0, 0, 0,
                       "No valid picks after matching dividends to kline cache")
        return

    # dividend type breakdown
    type_counts = defaultdict(int)
    for p in picks:
        type_counts[p["div_type"]] += 1
    print(f"[build] div type: {dict(type_counts)}")

    # date range
    ex_dates = sorted(set(p["ex_date"] for p in picks))
    print(f"[build] ex-date range: {ex_dates[0]} ~ {ex_dates[-1]}")

    # regime assignment
    regime_buckets = stratify_by_regime(picks, regime_bars)
    regime_counts = {k: len(v) for k, v in regime_buckets.items()}
    print(f"[build] regime distribution: {regime_counts}")

    # ---- R12: build equal-weight market date_index (size-matched benchmark) ----
    needed_dates: set[str] = set()
    for p in picks:
        needed_dates.add(p["t1_date"])
        needed_dates.add(p["t3_date"])
        needed_dates.add(p["t5_date"])
    date_index = build_date_index(code_map, needed_dates)

    # ---- analysis: basic (all events) ----
    results: list[dict] = []
    for wname, exit_n in WINDOWS:
        ret_fn = ev_t3 if exit_n == 3 else ev_t5
        r = analyze_window(f"basic_{wname}", picks, ret_fn, ret_label="EV")
        results.append(r)

    # ---- BHAR analysis (FIXED: open-to-close, equal-weight market) ----
    print(f"\n{'#' * 70}")
    print(f"[BHAR analysis] market-adjusted abnormal return")
    print(f"  FIX 2026-10-07: open-to-close (matching T+1 open entry)")
    print(f"  R12: equal-weight market benchmark (size-matched, not 沪深300)")
    print(f"{'#' * 70}")
    bhar_results: list[dict] = []
    for wname, exit_n in WINDOWS:
        ret_fn = bhar_t3 if exit_n == 3 else bhar_t5
        r = analyze_window(f"bhar_{wname}", picks, ret_fn,
                           index_bars=date_index, ret_label="BHAR")
        bhar_results.append(r)

    # ---- regime stratification ----
    print(f"\n{'#' * 70}")
    print(f"[regime stratification] strong vs weak regime")
    print(f"{'#' * 70}")
    regime_results: dict[str, list[dict]] = {}
    for rname, rpicks in regime_buckets.items():
        if rname == "unknown" or not rpicks:
            continue
        print(f"\n  === regime: {rname} (n={len(rpicks)}) ===")
        rr: list[dict] = []
        for wname, exit_n in WINDOWS:
            ret_fn = ev_t3 if exit_n == 3 else ev_t5
            r = analyze_window(f"regime_{rname}_{wname}", rpicks, ret_fn,
                               ret_label="EV")
            rr.append(r)
        regime_results[rname] = rr

    # ---- dividend type stratification ----
    print(f"\n{'#' * 70}")
    print(f"[type stratification] cash (除息) vs stock (除权) vs both")
    print(f"{'#' * 70}")
    type_buckets: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        type_buckets[p["div_type"]].append(p)
    for tname, tpicks in type_buckets.items():
        if not tpicks:
            continue
        print(f"\n  === type: {tname} (n={len(tpicks)}) ===")
        ret_fn = ev_t3
        analyze_window(f"type_{tname}_t3", tpicks, ret_fn, ret_label="EV")

    # ---- DSR estimation ----
    print(f"\n{'#' * 70}")
    print(f"[overfitting check] DSR + MinTRL (Bailey & Lopez de Prado 2014)")
    print(f"{'#' * 70}")
    # use best basic window for DSR
    best_basic = max(
        (r for r in results if r.get("n_events", 0) > 0),
        key=lambda r: r.get("gross_ev", -999),
        default=None,
    )
    if best_basic and best_basic.get("ev_std", 0) > 0:
        n_trials = N_CROSS_STRATEGY * N_WINDOWS  # ×4 strategies-variants ×2 windows
        dsr = estimate_dsr(
            best_basic["gross_ev"], best_basic["ev_std"],
            best_basic["n_events"], n_trials,
        )
        print(f"  best window: {best_basic['name']}")
        print(f"  event Sharpe (per-event): {dsr['event_sharpe']}")
        print(f"  annualized Sharpe (×sqrt(n/8yr)): {dsr['ann_sharpe']}")
        print(f"  expected max SR under H0 (n_trials={n_trials}): {dsr['expected_max_sr']}")
        print(f"  σ(SR_hat): {dsr['sigma_sr']}")
        print(f"  DSR (Φ-based): {dsr['dsr']}")
        print(f"  MinTRL: {dsr['min_trl_years']} years (actual: {dsr['actual_years']} years)")
        if dsr["survives"]:
            print(f"  → DSR>0.95: 经多重检验校正后 Sharpe 仍显著 (survives haircut)")
        elif dsr["dsr"] > 0.5:
            print(f"  → DSR={dsr['dsr']}: 有一定 edge 但未过 0.95 门槛 (需更多数据)")
        else:
            print(f"  → DSR<0.5: 经多重检验校正后 Sharpe 不显著 (overfitting 风险高)")

        # Also run DSR on best BHAR (market-adjusted)
        best_bhar_for_dsr = max(
            (r for r in bhar_results if r.get("n_events", 0) > 0),
            key=lambda r: r.get("gross_ev", -999),
            default=None,
        )
        if best_bhar_for_dsr and best_bhar_for_dsr.get("ev_std", 0) > 0:
            dsr_bhar = estimate_dsr(
                best_bhar_for_dsr["gross_ev"], best_bhar_for_dsr["ev_std"],
                best_bhar_for_dsr["n_events"], n_trials,
            )
            print(f"\n  BHAR DSR (market-adjusted): best={best_bhar_for_dsr['name']}")
            print(f"  event Sharpe: {dsr_bhar['event_sharpe']}")
            print(f"  annualized Sharpe: {dsr_bhar['ann_sharpe']}")
            print(f"  DSR: {dsr_bhar['dsr']}  MinTRL: {dsr_bhar['min_trl_years']}yr")
            if dsr_bhar["survives"]:
                print(f"  → BHAR DSR>0.95: market-adjusted edge survives haircut")
            else:
                print(f"  → BHAR DSR={dsr_bhar['dsr']}: market-adjusted edge 未过 haircut")
    else:
        print("  insufficient data for DSR estimation")

    # ---- verdict cascade (§44 v3 7-step, using _factor_helpers.verdict_for) ----
    print(f"\n{'#' * 70}")
    print(f"[VERDICT] raw EV + BHAR (7-step cascade via verdict_for)")
    print(f"  Bonferroni: ×{N_CROSS_STRATEGY} (2 strategies × 2 variants) for verdict")
    print(f"             ×{N_CROSS_STRATEGY * N_WINDOWS} (with 2 windows) for reference")
    print(f"{'#' * 70}")

    # Find best result across all windows (basic EV for primary verdict)
    best = max(
        (r for r in results if r.get("n_events", 0) > 0),
        key=lambda r: r.get("gross_ev", -999),
        default=None,
    )
    if not best:
        print("\n  No results with data → no-data")
        _print_summary("dividend-exright", "no-data", 0, 0, 0, 0,
                       "No valid results")
        return

    # Also check best regime-stratified result (strong regime hypothesis)
    best_regime: dict | None = None
    for rname, rr_list in regime_results.items():
        for rr in rr_list:
            if rr.get("n_events", 0) > 0:
                if best_regime is None or rr.get("gross_ev", -999) > best_regime.get("gross_ev", -999):
                    best_regime = rr
                    best_regime["regime_name"] = rname

    # ---- Raw EV verdict (7-step) ----
    wf = best.get("wf", {})
    wf_status = wf.get("status", "no_data")
    wf_train_ev = wf.get("train_ev", {}).get("ev", 0) if wf_status == "ok" else 0
    wf_test_ev = wf.get("test_ev", {}).get("ev", 0) if wf_status == "ok" else 0
    wf_test_p = wf.get("test_day_t", {}).get("p_one_sided", 1.0) if wf_status == "ok" else 1.0

    p_raw = best.get("day_p", 1.0)
    p_bonf4 = bonferroni_p(p_raw, N_CROSS_STRATEGY)
    p_bonf8 = bonferroni_p(p_raw, N_CROSS_STRATEGY * N_WINDOWS)

    print(f"\n  === Raw EV verdict ===")
    print(f"  best window: {best['name']}")
    print(f"    n_events={best['n_events']} n_dates={best['n_dates']} "
          f"gross_EV={best['gross_ev']}% median={best.get('median_ev',0)}% "
          f"WR={best['wr']}% net_EV={best['net_ev']:.3f}%")
    print(f"    day_t={best['day_t']} raw_p={p_raw}")
    print(f"    Bonf×{N_CROSS_STRATEGY}: p={p_bonf4:.6f} | "
          f"Bonf×{N_CROSS_STRATEGY * N_WINDOWS}: p={p_bonf8:.6f}")
    if wf_status == "ok":
        print(f"    walk-forward: train_EV={wf_train_ev}% test_EV={wf_test_ev}% "
              f"test_p={wf_test_p}")

    verdict_ev = verdict_for(
        ev_gross=best["gross_ev"],
        t_day=best["day_t"],
        p_raw=p_raw,
        wf_status=wf_status,
        wf_train_ev=wf_train_ev,
        wf_test_ev=wf_test_ev,
        wf_test_p=wf_test_p,
        n_days=best["n_dates"],
        net_ev=best["net_ev"],
        subset_name=f"raw EV ({best['name']})",
        n_cross_factor=2,  # 2 strategies × 2 variants = ×4
    )

    if best_regime:
        r_wf = best_regime.get("wf", {})
        r_wf_status = r_wf.get("status", "no_data")
        r_wf_train = r_wf.get("train_ev", {}).get("ev", 0) if r_wf_status == "ok" else 0
        r_wf_test = r_wf.get("test_ev", {}).get("ev", 0) if r_wf_status == "ok" else 0
        r_wf_test_p = r_wf.get("test_day_t", {}).get("p_one_sided", 1.0) if r_wf_status == "ok" else 1.0
        rp_raw = best_regime.get("day_p", 1.0)
        print(f"\n  === Regime variant: {best_regime.get('regime_name','?')} ===")
        verdict_regime = verdict_for(
            ev_gross=best_regime["gross_ev"],
            t_day=best_regime["day_t"],
            p_raw=rp_raw,
            wf_status=r_wf_status,
            wf_train_ev=r_wf_train,
            wf_test_ev=r_wf_test,
            wf_test_p=r_wf_test_p,
            n_days=best_regime["n_dates"],
            net_ev=best_regime["net_ev"],
            subset_name=f"regime {best_regime.get('regime_name','?')}",
            n_cross_factor=2,
        )

    # ---- BHAR verdict (7-step, FIXED open-to-close) ----
    best_bhar = max(
        (r for r in bhar_results if r.get("n_events", 0) > 0),
        key=lambda r: r.get("gross_ev", -999),
        default=None,
    )
    verdict_bhar = "no-data"
    if best_bhar:
        bp_raw = best_bhar.get("day_p", 1.0)
        bp_bonf4 = bonferroni_p(bp_raw, N_CROSS_STRATEGY)
        bp_bonf8 = bonferroni_p(bp_raw, N_CROSS_STRATEGY * N_WINDOWS)
        bwf = best_bhar.get("wf", {})
        bwf_status = bwf.get("status", "no_data")
        bwf_train = bwf.get("train_ev", {}).get("ev", 0) if bwf_status == "ok" else 0
        bwf_test = bwf.get("test_ev", {}).get("ev", 0) if bwf_status == "ok" else 0
        bwf_test_p = bwf.get("test_day_t", {}).get("p_one_sided", 1.0) if bwf_status == "ok" else 1.0

        print(f"\n  === BHAR verdict (FIXED open-to-close, EW market) ===")
        print(f"  best BHAR window: {best_bhar['name']}")
        print(f"    n_events={best_bhar['n_events']} n_dates={best_bhar['n_dates']} "
              f"gross_BHAR={best_bhar['gross_ev']}% "
              f"median={best_bhar.get('median_ev',0)}% "
              f"WR={best_bhar['wr']}% "
              f"net_BHAR={best_bhar['net_ev']:.3f}%")
        print(f"    day_t={best_bhar['day_t']} raw_p={bp_raw}")
        print(f"    Bonf×{N_CROSS_STRATEGY}: p={bp_bonf4:.6f} | "
              f"Bonf×{N_CROSS_STRATEGY * N_WINDOWS}: p={bp_bonf8:.6f}")
        if bwf_status == "ok":
            print(f"    walk-forward: train_BHAR={bwf_train}% test_BHAR={bwf_test}% "
                  f"test_p={bwf_test_p}")

        verdict_bhar = verdict_for(
            ev_gross=best_bhar["gross_ev"],
            t_day=best_bhar["day_t"],
            p_raw=bp_raw,
            wf_status=bwf_status,
            wf_train_ev=bwf_train,
            wf_test_ev=bwf_test,
            wf_test_p=bwf_test_p,
            n_days=best_bhar["n_dates"],
            net_ev=best_bhar["net_ev"],
            subset_name=f"BHAR ({best_bhar['name']})",
            n_cross_factor=2,
        )

    # ---- combined verdict ----
    # BHAR is the primary metric (isolates ex-dividend effect from market beta)
    # If BHAR passes but raw EV doesn't, edge is market beta not ex-dividend
    # If both pass, edge is ex-dividend specific (edge-confirmed)
    # If raw EV passes but BHAR doesn't, edge is just market beta
    print(f"\n  === Combined verdict ===")
    print(f"    raw EV: {verdict_ev}")
    print(f"    BHAR:   {verdict_bhar}")
    if verdict_bhar in ("edge-confirmed",):
        verdict = "edge-confirmed"
    elif verdict_bhar == "falsified" or verdict_ev == "falsified":
        verdict = "edge-falsified"
    elif verdict_bhar == "underpowered" or verdict_ev == "underpowered":
        verdict = "underpowered"
    else:
        verdict = "exploratory"
    print(f"    → final: {verdict}")

    # ---- summary ----
    print(f"\n{'#' * 70}")
    print(f"[SUMMARY]")
    print(f"{'#' * 70}")
    _print_summary(
        "dividend-exright",
        verdict,
        best.get("n_events", 0),
        best.get("n_dates", 0),
        best.get("gross_ev", 0),
        p_bonf4,
        f"raw_EV={best['name']}: gross={best['gross_ev']}% "
        f"median={best.get('median_ev',0)}% WR={best['wr']}% "
        f"net={best['net_ev']:.3f}% day_t={best['day_t']} "
        f"Bonf×{N_CROSS_STRATEGY}={p_bonf4:.4f} "
        f"wf_test_EV={wf_test_ev}% "
        f"| BHAR={best_bhar['name'] if best_bhar else 'N/A'}: "
        f"gross={best_bhar['gross_ev'] if best_bhar else 'N/A'}% "
        f"net={best_bhar['net_ev'] if best_bhar else 'N/A'}% "
        f"day_t={best_bhar['day_t'] if best_bhar else 'N/A'} "
        f"Bonf×{N_CROSS_STRATEGY}={bp_bonf4 if best_bhar else 'N/A'} "
        f"| regime: {regime_counts} | types: {dict(type_counts)} "
        f"| R12: EW market benchmark (size-matched) "
        f"| R13: survivorship—kline cache 偏近期 (仅 786 codes full-history, "
        f"其余 ~179 天, 偏差方向未知) "
        f"| 前复权 cache post-ex 收益 adjustment-invariant (实测) "
        f"| 禁止外推: 除权除息单事件 ≠ 事件驱动有/无 edge ≠ 短线有/无 edge",
    )


def _print_summary(
    strategy: str, verdict: str, n_events: int, n_dates: int,
    ev: float, bonf_p: float, key_finding: str,
) -> None:
    print(f"策略: 除权除息填权/贴权 (dividend-exright)")
    print(f"数据: {n_events} events across {n_dates} ex-dates")
    print(f"  entry=除权日 T+1 open, exit=T+3/T+5 close (realistic, close_ev)")
    print(f"  BHAR FIX 2026-10-07: open-to-close (was close-to-close, 低估 +0.12%)")
    print(f"  R12: equal-weight market benchmark (size-matched, not 沪深300)")
    print(f"  R13: survivorship—kline cache 偏近期 (786 codes full-history)")
    print(f"verdict: {verdict}")
    print(f"key: {key_finding}")


if __name__ == "__main__":
    main()
