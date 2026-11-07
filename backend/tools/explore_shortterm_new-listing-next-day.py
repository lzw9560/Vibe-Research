# -*- coding: utf-8 -*-
"""新股上市次日效应 (new-listing-next-day) — OOS backtest with §44 v3 anti-fake-edge.

策略假设: 新股上市首日(T)后, T+1 open 买, T+2/T+5 close 卖.
"炒新"情绪: 首日暴涨后, 次日是否延续 (momentum) 或反转 (mean-reversion)?
学术先验: Ritter 1991 IPO 长期 underperformance → 期望负 EV (反转).
A 股特色: 主板 2014-2023 首日+44% 限价→T+1 常一字涨停(买不进); 创业板/科创板
  首日不限价(前5日无涨跌幅)→T+1 可买. 2023-02 主板注册制改革后全部前5日不限价.

数据 (2026-10-06 实测核验):
- kline cache: baostock_kline_cache.json (505MB, 5248 codes).
  关键发现: cache 是分批 backfill 的, 非 IPO 日开始的码 first_bar 是 backfill 日
  (2025-12-25: 2914 码 / 2024-06-03: 981 码 / 2018-01-02: 778 码 / 2025-06-03: 192 码).
  排除这些 backfill 日后 370 码 first_bar == baostock IPO date (15/15 sample 验证).
  bar 字段: date/open/high/low/close/volume/amount (turn/pctChg/isST 仅 9% 覆盖).
- regime: index_ma20_regime.json, 上证综指 close + strong/weak (5502 天 2004~2026).
- baostock query_stock_basic: ipoDate 核验 (15/15 match cache first_bar for non-backfill).

§44 v3 anti-fake-edge (过严口径):
- realistic entry: T+1 open (T=IPO 首日, T+1=次日, 散户才能买——T close 已封板不可买)
- close_ev: T+1 open → T+2/T+5 close (非 open_ev——open_ev 有 T+1 日内泄漏)
- 一字涨停/一字跌停跳过: is_locked_bar (open≈high≈low, 买不进)
- per-day-mean t: 同日多笔聚成 day-mean, effective N = n_ipo_dates 非 n_events
- Bonferroni ×5: cross-strategy (5 策略并行) + ×2 windows = ×10 报告; verdict 用 ×5
- walk-forward OOS: 前半 train → 后半 test + train_ev>0 检查
- BHAR vs 上证综指同期收益 (isolate IPO effect vs market beta)
- board type 分层 (主板/创业板/科创板——限价规则不同)
- era 分层 (pre/post 2020-08-24 创业板 reform / pre/post 2023-02 主板 reform)
- survivorship: cache 仅含仍上市码, 退市新股缺失 → 上偏 (诚实标注)
- 禁止外推: 新股次日单策略 ≠ 事件驱动有/无 edge ≠ 短线有/无 edge
"""

from __future__ import annotations
import json
import sys
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from math import erf, sqrt

# import shared helpers (DRY) — reuse statistical functions
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
KLINE_JSON = DATA / "baostock_kline_cache.json"
REGIME_FILE = DATA / "index_ma20_regime.json"

# Event windows: entry=T+1 open, exit=T+n close
WINDOWS = [
    ("t2", 2),  # T+1 open → T+2 close (1-day hold)
    ("t5", 5),  # T+1 open → T+5 close (4-day hold)
]

# Bonferroni: ×5 cross-strategy (task spec) ×2 windows = ×10 total reported
N_CROSS_STRATEGY = 5
N_WINDOWS = 2

# Backfill artifact dates: codes whose first bar is one of these are NOT new listings
# (verified: 2914+981+778+192 = 4865 of 5248 codes are backfill, not IPO)
BACKFILL_DATES = {"2018-01-02", "2024-06-03", "2025-06-03", "2025-12-25"}

# Era boundaries (A-share new listing limit reform)
CHUANGYE_REFORM = "2020-08-24"  # 创业板注册制: 前5日无涨跌幅
MAIN_REFORM = "2023-02-01"  # 主板注册制: 前5日无涨跌幅 (approx date)


# ---------- data loading ----------


def load_kline_json() -> dict[str, list[dict]]:
    """Load kline cache from JSON. Returns {code: [bars sorted by date]}."""
    if not KLINE_JSON.exists():
        print(f"[ERROR] kline cache not found: {KLINE_JSON}")
        sys.exit(1)
    with open(KLINE_JSON) as f:
        raw = json.load(f)
    # ensure bars are lists sorted by date
    code_map: dict[str, list[dict]] = {}
    for code, bars in raw.items():
        if isinstance(bars, list) and bars:
            bars_sorted = sorted(bars, key=lambda b: b.get("date", ""))
            code_map[code] = bars_sorted
    print(f"[data] kline JSON: {len(code_map)} codes, {KLINE_JSON.name}")
    return code_map


def load_regime() -> tuple[dict[str, dict], list[str]]:
    """Load 上证综指 close + regime. Returns (date -> bar, sorted trading days)."""
    if not REGIME_FILE.exists():
        print(f"[ERROR] regime file not found: {REGIME_FILE}")
        sys.exit(1)
    with open(REGIME_FILE) as f:
        raw = json.load(f)
    bars = {d: v for d, v in raw.items() if isinstance(v, dict) and "close" in v}
    days = sorted(bars.keys())
    print(f"[data] regime: {len(days)} trading days ({days[0]}~{days[-1]})")
    return bars, days


# ---------- board classification ----------


def board_type(code: str) -> str:
    """Classify by board: main / chuangye / kechuang / beijiao / other."""
    if code.startswith(("300", "301")):
        return "chuangye"
    if code.startswith(("688", "689")):
        return "kechuang"
    if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return "main"
    if code.startswith(("4", "8")):
        return "beijiao"
    return "other"


def era_of(ipo_date: str) -> str:
    """Classify era by IPO date relative to limit reforms."""
    if ipo_date < CHUANGYE_REFORM:
        return "era1_pre2020"  # 主板+创业板 首日+44%限价, T+1 常
    if ipo_date < MAIN_REFORM:
        return "era2_2020_2023"  # 创业板/科创板 前5日无限价, 主板仍+44%
    return "era3_post2023"  # 全部前5日无限价


def has_first5_limit(ipo_date: str, board: str) -> bool:
    """Whether T+1 has daily limit (and thus could be 一字涨停 locked).
    If True, T+1 might be locked (can't buy). If False, T+1 is tradeable."""
    if board in ("chuangye", "kechuang"):
        if board == "chuangye" and ipo_date < CHUANGYE_REFORM:
            return True  # pre-reform 创业板 had limits
        return False  # post-reform / 科创板: no first-5-day limit
    if board == "main":
        if ipo_date < MAIN_REFORM:
            return True  # pre-reform 主板 had +44% then 10% limit
        return False  # post-reform: no first-5-day limit
    return True  # unknown/beijiao: assume has limit (conservative)


# ---------- locked bar check ----------


def is_locked_bar(bar: dict) -> bool:
    """Check if bar is 一字 (locked at single price, can't buy).
    open≈high≈low within 0.1% → locked (一字涨停 or 一字跌停)."""
    o = bar.get("open")
    h = bar.get("high")
    l = bar.get("low")
    if o is None or h is None or l is None or o <= 0:
        return False
    return abs(o - h) / o < 0.001 and abs(o - l) / o < 0.001


# ---------- pick construction ----------


def build_ipo_picks(
    code_map: dict[str, list[dict]],
    max_exit_offset: int = 5,
) -> list[dict]:
    """Build picks for new-listing-next-day strategy.

    For each code whose first cache bar is a real IPO date (not backfill artifact):
    - T = IPO date = bars[0]
    - T+1 = bars[1] (entry = T+1 open)
    - exit = bars[exit_offset] (T+2 or T+5 close)

    Skip if:
    - first bar date is a backfill artifact (not real IPO)
    - first bar date < 2018-01-01 (outside analysis window)
    - fewer than max_exit_offset+1 bars (can't compute longest exit)
    - T+1 bar is locked (一字, can't buy)
    - T+1 open or exit close missing/invalid

    Returns picks with: code, ipo_date, board, era, has_limit,
    t1_date, exit dates, entry (T+1 open), t1_bar, exit bars, t1_close.
    """
    picks: list[dict] = []
    skipped_backfill = 0
    skipped_pre2018 = 0
    skipped_short = 0
    skipped_locked = 0
    skipped_invalid = 0

    for code, bars in code_map.items():
        if not bars:
            continue
        ipo_date = bars[0].get("date", "")
        if not ipo_date:
            continue

        # skip backfill artifacts (not real IPOs)
        if ipo_date in BACKFILL_DATES:
            skipped_backfill += 1
            continue
        # skip pre-2018 (outside analysis window)
        if ipo_date < "2018-01-01":
            skipped_pre2018 += 1
            continue
        # need enough bars for all exit windows
        if len(bars) < max_exit_offset + 1:
            skipped_short += 1
            continue

        board = board_type(code)
        era = era_of(ipo_date)
        limit_on_t1 = has_first5_limit(ipo_date, board)

        t1_bar = bars[1]
        entry = t1_bar.get("open")
        if entry is None or entry <= 0:
            skipped_invalid += 1
            continue

        # skip locked T+1 (一字涨停/跌停, can't buy)
        if is_locked_bar(t1_bar):
            skipped_locked += 1
            continue

        t1_date = t1_bar.get("date", "")
        t1_close = t1_bar.get("close")
        if t1_close is None or t1_close <= 0:
            skipped_invalid += 1
            continue

        # exit bars for each window
        exit_bars: dict[str, dict] = {}
        exit_dates: dict[str, str] = {}
        exit_closes: dict[str, float] = {}
        for wname, offset in WINDOWS:
            if offset < len(bars):
                eb = bars[offset]
                ec = eb.get("close")
                if ec is not None and ec > 0:
                    exit_bars[wname] = eb
                    exit_dates[wname] = eb.get("date", "")
                    exit_closes[wname] = ec

        if not exit_bars:
            skipped_invalid += 1
            continue

        # first-day return (T close vs T open) for context
        t0_open = bars[0].get("open")
        t0_close = bars[0].get("close")
        first_day_ret = (t0_close - t0_open) / t0_open * 100 if t0_open and t0_close and t0_open > 0 else None

        picks.append(
            {
                "code": code,
                "ipo_date": ipo_date,
                "board": board,
                "era": era,
                "has_limit_t1": limit_on_t1,
                "t1_date": t1_date,
                "t1_bar": t1_bar,
                "t1_close": t1_close,
                "entry": entry,
                "exit_bars": exit_bars,
                "exit_dates": exit_dates,
                "exit_closes": exit_closes,
                "first_day_ret": first_day_ret,
            }
        )

    print(f"[build] total codes: {len(code_map)}")
    print(f"[build] skipped backfill (not real IPO): {skipped_backfill}")
    print(f"[build] skipped pre-2018: {skipped_pre2018}")
    print(f"[build] skipped too few bars (<{max_exit_offset + 1}): {skipped_short}")
    print(f"[build] skipped locked T+1 (一字, can't buy): {skipped_locked}")
    print(f"[build] skipped invalid (missing OHLC): {skipped_invalid}")
    print(f"[build] valid picks: {len(picks)}")
    return picks


# ---------- return functions ----------


def ev_window(p: dict, wname: str) -> float | None:
    """Raw EV: T+1 open → T+n close. Realistic entry, close_ev not open_ev."""
    ec = p["exit_closes"].get(wname)
    if ec is None:
        return None
    return (ec - p["entry"]) / p["entry"] * 100


def bhar_window(p: dict, wname: str, index_bars: dict[str, dict]) -> float | None:
    """BHAR: (event close-to-close) - (index close-to-close) over T+1→exit.
    Event_cc = (exit_close - t1_close) / t1_close.
    Market_cc = (index_exit_close - index_t1_close) / index_t1_close.
    BHAR = Event_cc - Market_cc."""
    ec = p["exit_closes"].get(wname)
    if ec is None:
        return None
    t1_close = p["t1_close"]
    exit_date = p["exit_dates"].get(wname)
    t1_date = p["t1_date"]
    if not exit_date or not t1_date:
        return None
    i_t1 = index_bars.get(t1_date)
    i_exit = index_bars.get(exit_date)
    if i_t1 is None or i_exit is None:
        return None
    i_t1_c = i_t1.get("close")
    i_exit_c = i_exit.get("close")
    if i_t1_c is None or i_exit_c is None or i_t1_c <= 0:
        return None
    ev_cc = (ec - t1_close) / t1_close * 100
    mk_cc = (i_exit_c - i_t1_c) / i_t1_c * 100
    return ev_cc - mk_cc


# ---------- walk-forward (event-study adapted) ----------


def walk_forward_event(
    picks: list[dict],
    ret_fn,
    index_bars: dict[str, dict] | None = None,
    wname: str = "t2",
) -> dict:
    """Walk-forward OOS: sort by ipo_date, split half train/half test."""
    if not picks:
        return {"status": "no_picks"}
    ps = sorted(picks, key=lambda p: p["ipo_date"])
    dates = sorted(set(p["ipo_date"] for p in ps))
    if len(dates) < 4:
        return {"status": "too_few_dates", "n_dates": len(dates)}
    mid = len(dates) // 2
    train_dates = set(dates[:mid])
    test_dates = set(dates[mid:])

    def _rets(subset_dates: set[str]) -> tuple[list[float], dict[str, list[float]]]:
        rets: list[float] = []
        by_date: dict[str, list[float]] = defaultdict(list)
        for p in ps:
            if p["ipo_date"] not in subset_dates:
                continue
            r = ret_fn(p, wname, index_bars) if index_bars else ret_fn(p, wname)
            if r is not None:
                rets.append(r)
                by_date[p["ipo_date"]].append(r)
        return rets, by_date

    tr_rets, tr_by_date = _rets(train_dates)
    te_rets, te_by_date = _rets(test_dates)
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


# ---------- DSR estimation ----------


def estimate_dsr(ev_mean: float, ev_std: float, n_events: int, n_trials: int, years: float = 8.0) -> dict:
    """Approximate Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).
    Multiple-testing haircut: if annualized Sharpe exceeds expected max under
    H0 (no skill) = sqrt(2*ln(N_trials)), the signal survives."""
    if ev_std <= 0 or n_events <= 0:
        return {"event_sharpe": 0, "ann_sharpe": 0, "dsr_approx": 0, "expected_max_sr": 0, "n_trials": n_trials}
    event_sharpe = ev_mean / ev_std
    events_per_year = max(n_events / years, 1)
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


# ---------- analysis per window ----------


def analyze_window(
    name: str,
    picks: list[dict],
    ret_fn,
    index_bars: dict[str, dict] | None = None,
    ret_label: str = "EV",
) -> dict:
    """Run full analysis on one window: EV stats + day-paired t + walk-forward."""
    print(f"\n{'=' * 70}")
    print(f"窗口: {name} (n_picks={len(picks)})  [{ret_label}]")
    print(f"{'=' * 70}")

    if not picks:
        print("  无 picks, 跳过")
        return {"name": name, "n_picks": 0}

    # detect window from name suffix (not substring — "t2" appears in "post2023")
    wname = "t2" if name.endswith("_t2") else "t5"
    rets: list[float] = []
    by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        if index_bars:
            r = ret_fn(p, wname, index_bars)
        else:
            r = ret_fn(p, wname)
        if r is not None:
            rets.append(r)
            by_date[p["ipo_date"]].append(r)

    if not rets:
        print("  无有效收益, 跳过")
        return {"name": name, "n_picks": 0}

    s = ev_stats(rets)
    net = s["ev"] - COST * 100
    dt = day_paired_t(by_date)

    print(f"\n--- {ret_label} stats ---")
    print(f"  n={s['n']} n_dates={dt['n_days']} gross_{ret_label}={s['ev']}% std={s['std']}% WR={s['wr']}% t={s['t']} CI[{s['ci_lo']},{s['ci_hi']}]")
    print(f"  net_{ret_label} (after {COST * 100:.1f}% cost): {net:.3f}%")
    print(f"  day-paired t: n_days={dt['n_days']} mean={dt['mean']}% t={dt['t']} p_one_sided={dt['p_one_sided']}")

    # walk-forward (reuse wname detected above)
    print(f"\n--- walk-forward OOS (前半 train → 后半 test) ---")
    wf = walk_forward_event(picks, ret_fn, index_bars, wname)
    if wf["status"] == "ok":
        tr = wf["train_ev"]
        te = wf["test_ev"]
        tr_dt = wf["train_day_t"]
        te_dt = wf["test_day_t"]
        print(f"  train: n={tr['n']} n_dates={wf['n_train_dates']} EV={tr['ev']}% t={tr['t']} day_t={tr_dt['t']}")
        print(f"  test:  n={te['n']} n_dates={wf['n_test_dates']} EV={te['ev']}% t={te['t']} day_t={te_dt['t']} p={te_dt['p_one_sided']}")
        decay = (tr["ev"] - te["ev"]) / abs(tr["ev"]) * 100 if tr["ev"] != 0 else 0
        print(f"  decay: {decay:.0f}% (train→test)")
    else:
        print(f"  {wf['status']} (n_dates={wf.get('n_dates', 0)})")

    return {
        "name": name,
        "n_picks": len(picks),
        "n_events": s["n"],
        "n_dates": dt["n_days"],
        "gross_ev": s["ev"],
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


# ---------- verdict cascade (§44 v3 for event study) ----------


def verdict_cascade(
    gross: float,
    net: float,
    n_dates: int,
    t_day: float,
    p_raw: float,
    p_bonf: float,
    wf_status: str,
    wf_train_ev: float,
    wf_test_ev: float,
    wf_test_p: float,
    n_tests: int,
    subset_name: str,
) -> str:
    """§44 v3 verdict cascade for event study."""
    print(f"\n  {subset_name}:")
    print(f"    gross_EV={gross}% net_EV={net:.3f}% day_t={t_day} Bonf_p(×{n_tests})={p_bonf:.6f} n_dates={n_dates}")
    if wf_status == "ok":
        print(f"    walk-forward: train_EV={wf_train_ev}% test_EV={wf_test_ev}% test_p={wf_test_p}")

    if gross < 0:
        print(f"    → FALSIFIED: gross EV={gross}% < 0 (新股次日反转, loser signal)")
        return "edge-falsified"
    if n_dates < 60:
        print(f"    → UNDERPOWERED: n_dates={n_dates} < 60 (IPO dates 太少)")
        return "underpowered"
    if p_bonf >= ALPHA:
        print(f"    → FALSIFIED: Bonferroni p={p_bonf:.6f} >= {ALPHA} (not significant after ×{n_tests} correction)")
        return "edge-falsified"
    if net <= 0:
        print(f"    → FALSIFIED: net EV={net:.3f}% <= 0 (gross edge eaten by cost)")
        return "edge-falsified"
    if wf_status == "ok":
        if wf_train_ev <= 0:
            print(f"    → EXPLORATORY: train_EV={wf_train_ev}% <= 0 (edge not in train half, test may be regime overfitting)")
            return "exploratory"
        if wf_test_ev <= 0:
            print(f"    → FALSIFIED: walk-forward test_EV={wf_test_ev}% <= 0")
            return "edge-falsified"
        wf_p_bonf = bonferroni_p(wf_test_p, n_tests)
        if wf_p_bonf >= ALPHA:
            print(f"    → EXPLORATORY: OOS test EV={wf_test_ev}% > 0 but test p={wf_test_p} Bonf×{n_tests}={wf_p_bonf} >= {ALPHA} (not significant OOS)")
            return "exploratory"
        print(f"    → EDGE-CONFIRMED: gross+net EV > 0, Bonferroni PASS, OOS test EV={wf_test_ev}% significant (p={wf_test_p})")
        return "edge-confirmed"
    print(f"    → EXPLORATORY: walk-forward not available")
    return "exploratory"


# ---------- main ----------


def main() -> None:
    # ---- load data ----
    code_map = load_kline_json()
    index_bars, calendar = load_regime()

    # ---- build picks ----
    print(f"\n[build] identifying real IPO codes (first bar not backfill artifact)...")
    picks = build_ipo_picks(code_map, max_exit_offset=5)
    if not picks:
        print("\n[verdict] no picks → no-data")
        _print_summary("new-listing-next-day", "no-data", 0, 0, 0, 1.0, "No valid IPO picks after filtering")
        return

    # ---- descriptive stats ----
    n_ipo_dates = len(set(p["ipo_date"] for p in picks))
    ipo_dates = sorted(set(p["ipo_date"] for p in picks))
    print(f"[build] picks: {len(picks)} IPOs across {n_ipo_dates} dates")
    print(f"[build] IPO date range: {ipo_dates[0]} ~ {ipo_dates[-1]}")

    board_counts = Counter(p["board"] for p in picks)
    era_counts = Counter(p["era"] for p in picks)
    limit_counts = Counter(p["has_limit_t1"] for p in picks)
    print(f"[build] board distribution: {dict(board_counts)}")
    print(f"[build] era distribution: {dict(era_counts)}")
    print(f"[build] T+1 has-limit distribution: {dict(limit_counts)}")

    # first-day return distribution (context: 炒新首日涨幅)
    fdr = [p["first_day_ret"] for p in picks if p["first_day_ret"] is not None]
    if fdr:
        fdr_mean = sum(fdr) / len(fdr)
        fdr_median = statistics.median(fdr)
        fdr_pos = sum(1 for x in fdr if x > 0)
        print(f"[build] first-day return: mean={fdr_mean:.1f}% median={fdr_median:.1f}% positive={fdr_pos}/{len(fdr)} ({fdr_pos / len(fdr) * 100:.1f}%)")

    # survivorship warning
    print(f"[build] ⚠ survivorship: cache 仅含仍上市码, 退市新股缺失 → 上偏")

    # ---- analysis: basic EV (all picks) ----
    print(f"\n{'#' * 70}")
    print(f"[basic EV analysis] T+1 open → T+2/T+5 close (raw EV)")
    print(f"{'#' * 70}")
    results: list[dict] = []
    for wname, offset in WINDOWS:
        r = analyze_window(f"basic_{wname}", picks, ev_window, ret_label="EV")
        results.append(r)

    # ---- BHAR analysis ----
    print(f"\n{'#' * 70}")
    print(f"[BHAR analysis] market-adjusted abnormal return (vs 上证综指)")
    print(f"{'#' * 70}")
    bhar_results: list[dict] = []
    for wname, offset in WINDOWS:
        r = analyze_window(f"bhar_{wname}", picks, bhar_window, index_bars=index_bars, ret_label="BHAR")
        bhar_results.append(r)

    # ---- board stratification ----
    print(f"\n{'#' * 70}")
    print(f"[board stratification] main / chuangye / kechuang")
    print(f"{'#' * 70}")
    board_results: dict[str, list[dict]] = {}
    for bname, bpicks in defaultdict(list, {b: [p for p in picks if p["board"] == b] for b in board_counts}).items():
        if bname == "other" or not bpicks:
            continue
        print(f"\n  === board: {bname} (n={len(bpicks)}) ===")
        rr: list[dict] = []
        for wname, offset in WINDOWS:
            r = analyze_window(f"board_{bname}_{wname}", bpicks, ev_window, ret_label="EV")
            rr.append(r)
        board_results[bname] = rr

    # ---- era stratification ----
    print(f"\n{'#' * 70}")
    print(f"[era stratification] pre-2020 / 2020-2023 / post-2023")
    print(f"{'#' * 70}")
    era_results: dict[str, list[dict]] = {}
    for ename, epicks in defaultdict(list, {e: [p for p in picks if p["era"] == e] for e in era_counts}).items():
        if not epicks:
            continue
        print(f"\n  === era: {ename} (n={len(epicks)}) ===")
        rr2: list[dict] = []
        for wname, offset in WINDOWS:
            r = analyze_window(f"era_{ename}_{wname}", epicks, ev_window, ret_label="EV")
            rr2.append(r)
        era_results[ename] = rr2

    # ---- DSR estimation ----
    print(f"\n{'#' * 70}")
    print(f"[overfitting check] DSR estimation")
    print(f"{'#' * 70}")
    best_basic = max(
        (r for r in results if r.get("n_events", 0) > 0),
        key=lambda r: r.get("gross_ev", -999),
        default=None,
    )
    if best_basic and best_basic.get("ev_std", 0) > 0:
        n_trials = N_CROSS_STRATEGY * N_WINDOWS
        # years span: IPOs from 2018-2026 ~ 8 years
        dsr = estimate_dsr(
            best_basic["gross_ev"],
            best_basic["ev_std"],
            best_basic["n_events"],
            n_trials,
            years=8.0,
        )
        print(f"  best window: {best_basic['name']}")
        print(f"  event Sharpe (per-event): {dsr['event_sharpe']}")
        print(f"  annualized Sharpe (×sqrt(n/8yr)): {dsr['ann_sharpe']}")
        print(f"  expected max SR (n_trials={n_trials}): {dsr['expected_max_sr']}")
        print(f"  DSR approx: {dsr['dsr_approx']}")
        if dsr["dsr_approx"] < 0:
            print(f"  → DSR<0: 经多重检验校正后 Sharpe 不显著 (overfitting 风险高)")
        else:
            print(f"  → DSR>0: 多重检验校正后 Sharpe 仍为正 (但需 walk-forward 确认)")
    else:
        print("  insufficient data for DSR estimation")

    # ---- Bonferroni + verdict ----
    print(f"\n{'#' * 70}")
    print(f"[verdict] cross-strategy Bonferroni ×{N_CROSS_STRATEGY} (5 策略并行) + ×{N_WINDOWS} windows = ×{N_CROSS_STRATEGY * N_WINDOWS}")
    print(f"{'#' * 70}")

    best = max(
        (r for r in results if r.get("n_events", 0) > 0),
        key=lambda r: r.get("gross_ev", -999),
        default=None,
    )
    if not best:
        print("\n  No results with data → no-data")
        _print_summary("new-listing-next-day", "no-data", 0, 0, 0, 1.0, "No valid results")
        return

    p_raw = best.get("day_p", 1.0)
    p_bonf5 = bonferroni_p(p_raw, N_CROSS_STRATEGY)
    p_bonf10 = bonferroni_p(p_raw, N_CROSS_STRATEGY * N_WINDOWS)

    wf = best.get("wf", {})
    wf_status = wf.get("status", "no_data")
    wf_train_ev = wf.get("train_ev", {}).get("ev", 0) if wf_status == "ok" else 0
    wf_test_ev = wf.get("test_ev", {}).get("ev", 0) if wf_status == "ok" else 0
    wf_test_p = wf.get("test_day_t", {}).get("p_one_sided", 1.0) if wf_status == "ok" else 1.0

    print(f"\n  best window: {best['name']}")
    print(f"    n_events={best['n_events']} n_dates={best['n_dates']} gross_EV={best['gross_ev']}% net_EV={best['net_ev']:.3f}%")
    print(f"    day_t={best['day_t']} raw_p={p_raw}")
    print(f"    Bonferroni ×{N_CROSS_STRATEGY}: p={p_bonf5:.6f}")
    print(f"    Bonferroni ×{N_CROSS_STRATEGY * N_WINDOWS} (with windows): p={p_bonf10:.6f}")
    if wf_status == "ok":
        print(f"    walk-forward: train_EV={wf_train_ev}% test_EV={wf_test_ev}% test_p={wf_test_p}")

    # best board-stratified result
    best_board: dict | None = None
    for bname, rr_list in board_results.items():
        for rr in rr_list:
            if rr.get("n_events", 0) > 0:
                if best_board is None or rr.get("gross_ev", -999) > best_board.get("gross_ev", -999):
                    best_board = rr
                    best_board["board_name"] = bname
    if best_board:
        bp_raw = best_board.get("day_p", 1.0)
        bp_bonf = bonferroni_p(bp_raw, N_CROSS_STRATEGY)
        print(f"\n  best board variant: {best_board.get('board_name', '?')} {best_board['name']}")
        print(f"    n_events={best_board['n_events']} n_dates={best_board['n_dates']} gross_EV={best_board['gross_ev']}% net_EV={best_board['net_ev']:.3f}%")
        print(f"    day_t={best_board['day_t']} Bonf×{N_CROSS_STRATEGY}={bp_bonf:.6f}")

    # verdict cascade
    print(f"\n  --- verdict cascade ---")
    verdict = verdict_cascade(
        best["gross_ev"],
        best["net_ev"],
        best["n_dates"],
        best["day_t"],
        p_raw,
        p_bonf5,
        wf_status,
        wf_train_ev,
        wf_test_ev,
        wf_test_p,
        N_CROSS_STRATEGY,
        "all_boards_best",
    )

    # ---- BHAR cross-check ----
    best_bhar = max(
        (r for r in bhar_results if r.get("n_events", 0) > 0),
        key=lambda r: r.get("gross_ev", -999),
        default=None,
    )
    if best_bhar:
        bp_raw2 = best_bhar.get("day_p", 1.0)
        bp_bonf2 = bonferroni_p(bp_raw2, N_CROSS_STRATEGY * N_WINDOWS)
        print(
            f"\n  BHAR cross-check: best={best_bhar['name']} "
            f"BHAR={best_bhar['gross_ev']}% day_t={best_bhar['day_t']} "
            f"Bonf×{N_CROSS_STRATEGY * N_WINDOWS}={bp_bonf2:.6f}"
        )
        if best_bhar["gross_ev"] < 0:
            print(f"    BHAR<0: market-adjusted abnormal return 为负 → raw EV 若为正仅是 market beta 非 IPO edge")
        else:
            print(f"    BHAR>0: 有正 abnormal return (但需 Bonf+OOS 确认)")

    # ---- summary ----
    print(f"\n{'#' * 70}")
    print(f"[SUMMARY]")
    print(f"{'#' * 70}")
    key_finding = (
        (
            f"best={best['name']} gross_EV={best['gross_ev']}% "
            f"net={best['net_ev']:.3f}% day_t={best['day_t']} "
            f"Bonf×{N_CROSS_STRATEGY}={p_bonf5:.4f} "
            f"wf_test_EV={wf_test_ev}% "
            f"| BHAR best={best_bhar['gross_ev'] if best_bhar else 'N/A'}% "
            f"| board: {dict(board_counts)} "
            f"| era: {dict(era_counts)} "
            f"| first-day ret mean={fdr_mean:.1f}% (炒新首日暴涨) "
            f"| ⚠ survivorship: cache 仅含仍上市码, 退市新股缺失 → 上偏 "
            f"| 禁止外推: 新股次日单策略 ≠ 事件驱动有/无 edge ≠ 短线有/无 edge"
        )
        if best and fdr
        else (
            f"best={best['name']} gross_EV={best['gross_ev']}% "
            f"net={best['net_ev']:.3f}% day_t={best['day_t']} "
            f"Bonf×{N_CROSS_STRATEGY}={p_bonf5:.4f} "
            f"| ⚠ survivorship bias "
            f"| 禁止外推"
        )
    )
    _print_summary(
        "new-listing-next-day",
        verdict,
        best.get("n_events", 0),
        best.get("n_dates", 0),
        best.get("gross_ev", 0),
        p_bonf5,
        key_finding,
    )


def _print_summary(
    strategy: str,
    verdict: str,
    n_events: int,
    n_dates: int,
    ev: float,
    bonf_p: float,
    key_finding: str,
) -> None:
    print(f"策略: 新股上市次日效应 (new-listing-next-day)")
    print(f"数据: {n_events} IPOs across {n_dates} IPO dates")
    print(f"  entry=IPO T+1 open, exit=T+2/T+5 close (realistic, close_ev)")
    print(f"  一字涨停/跌停 T+1 跳过 (买不进)")
    print(f"  ⚠ survivorship: cache 仅含仍上市码 (退市新股缺失)")
    print(f"verdict: {verdict}")
    print(f"key: {key_finding}")


if __name__ == "__main__":
    main()
