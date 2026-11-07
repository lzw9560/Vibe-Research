# -*- coding: utf-8 -*-
"""大股东增持 (Insider Buy) 深挖 — Round 2 event-study with §44 v3 anti-fake-edge.

学术先验: Lakonishok-Lee (2001) — 内部人增持后 12 个月 +5-8% 异常收益.
A股先验: 2015 暴跌期 5692 笔增持 (平时 1500-3000) → 可能是"暴跌后反弹"混杂.

事件定义:
- Event date = 公告日 (announcement date — 公开才可知, 非变动开始日)
- Filter: 增持 + 占总股本比例 >= 0.1% (material)
- Entry = T+1 open (next trading day after announcement, realistic)
- Windows: T+5 / T+10 / T+20 (drift 慢月级, T+5 可能不够)

深挖维度:
1. 窗口对比: T+5 vs T+10 vs T+20 (定位 drift 时间结构)
2. 阈值分桶: >=0.1% / >=0.5% / >=1% / >=5% (规模→信号力)
3. Regime 分层: strong (index>MA20) vs weak (index<MA20) — 控制暴跌后反弹混杂
4. 结构断点: pre-2020 / 2020-2022 / 2023-2026 (市场结构变化)
5. 暴跌期控制: 2015H2 crash vs non-crash (直接测混杂根因)

§44 v3 全套:
- BHAR vs 上证综指 (isolate beta — 非 raw EV)
- per-day-mean t (同日多笔聚 day-mean)
- Bonferroni x3 (3 策略并行: insider-buy + ETF premium + downtick)
- walk-forward OOS + train_ev>0
- DSR 估算 (multiple-testing haircut)
- is_yizi T+1 过滤 (一字涨停买不进)
- 禁止外推: insider-buy 单策略 != 事件驱动有/无 edge

数据限制 (诚实):
- kline cache 仅 ~821 codes 有 2020 前数据 (5248 codes 中多数仅 ~179 天)
- 2015 暴跌期大量增持事件因无 kline 数据被排除 → 样本偏向近年
- 这是数据管道限制非策略缺陷, 须如实报告
"""

from __future__ import annotations
import json
import sys
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt

# import shared helpers (DRY)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools._factor_helpers import (  # noqa: E402
    ev_stats,
    day_paired_t,
    bonferroni_p,
    norm_sf_positive,
    limit_for_code,
    is_yizi_t1,
    ALPHA,
    COST,
)

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
INDEX_FILE = DATA / "index_ohlc_cache.json"
REGIME_FILE = DATA / "index_ma20_regime.json"

# Windows: (name, exit_offset) — entry always T+1 open, exit T+n close
WINDOWS = [
    ("t5", 5),
    ("t10", 10),
    ("t20", 20),
]

# Bonferroni: 3 strategies in parallel (insider-buy + ETF premium + downtick)
N_CROSS_STRATEGY = 3
# Additional windows tested
N_WINDOWS = 3


# ---------- data loading ----------


def load_insider_buys() -> list[dict]:
    """Fetch material insider buys from akshare. Returns list of events."""
    import akshare as ak

    df = ak.stock_ggcg_em(symbol="全部")
    inc = df[df["持股变动信息-增减"] == "增持"].copy()
    mat = inc[inc["持股变动信息-占总股本比例"] >= 0.1].copy()
    events: list[dict] = []
    for _, row in mat.iterrows():
        code = str(row["代码"]).strip()
        ann_date = str(row["公告日"]).strip()
        pct = float(row["持股变动信息-占总股本比例"])
        shareholder = str(row.get("股东名称", ""))
        if not code or not ann_date or ann_date == "nan":
            continue
        events.append(
            {
                "code": code,
                "ann_date": ann_date,
                "pct_total": pct,
                "shareholder": shareholder,
            }
        )
    print(f"[data] insider buys: {len(events)} material events (>=0.1% of total shares)")
    return events


def load_kline_db() -> dict[str, dict[str, dict]]:
    """Load kline cache. Returns code -> {date: bar}."""
    import sqlite3

    conn = sqlite3.connect(str(KLINE_DB))
    code_map: dict[str, dict[str, dict]] = {}
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
        if dmap:
            code_map[code] = dmap
    conn.close()
    print(f"[data] kline cache: {len(code_map)} codes")
    return code_map


def load_index() -> tuple[dict[str, dict], list[str]]:
    """Load 上证综指. Returns (date -> bar, sorted trading days)."""
    with open(INDEX_FILE) as f:
        raw = json.load(f)
    bars_list = raw.get("sh.000001", [])
    idx_bars: dict[str, dict] = {}
    for b in bars_list:
        d = b.get("date")
        if d:
            idx_bars[d] = b
    days = sorted(idx_bars.keys())
    print(f"[data] index: {len(days)} trading days ({days[0]}~{days[-1]})")
    return idx_bars, days


def load_regime() -> dict[str, str]:
    """Load regime (strong/weak based on MA20). Returns date -> regime."""
    with open(REGIME_FILE) as f:
        raw = json.load(f)
    regime_map: dict[str, str] = {}
    for d, v in raw.items():
        if isinstance(v, dict) and "regime" in v:
            regime_map[d] = v["regime"]
    print(f"[data] regime: {len(regime_map)} days")
    return regime_map


# ---------- pick construction ----------


def build_insider_picks(
    events: list[dict],
    code_map: dict[str, dict[str, dict]],
    calendar: list[str],
    idx_bars: dict[str, dict],
    regime_map: dict[str, str],
) -> list[dict]:
    """Build picks: for each insider buy announcement, entry=T+1 open.

    For each window (t5/t10/t20), store exit date + close.
    Skip if:
    - ann_date not in calendar or too close to end (< 21 trading days buffer for t20)
    - code not in kline cache
    - T+1 bar missing or T+1 open invalid
    - T+1 is locked (一字涨停, can't buy) — using limit_for_code
    - Any exit bar (t5/t10/t20) missing

    Returns picks with: code, ann_date, t1_date, entry, regime,
    t5_date/t5_close, t10_date/t10_close, t20_date/t20_close,
    pct_total, t1_bar (for yizi check reference).
    """
    date_idx = {d: i for i, d in enumerate(calendar)}
    picks: list[dict] = []

    for ev in events:
        code = ev["code"]
        ann_date = ev["ann_date"]
        d_idx = date_idx.get(ann_date)
        if d_idx is None or d_idx + 21 >= len(calendar):
            continue  # need T+1 through T+20 minimum

        dmap = code_map.get(code)
        if not dmap:
            continue

        t1_date = calendar[d_idx + 1]
        t1_bar = dmap.get(t1_date)
        if t1_bar is None:
            continue
        t1_open = t1_bar.get("open")
        if t1_open is None or t1_open <= 0:
            continue

        # Need T bar (announcement day) for limit reference
        t_bar = dmap.get(ann_date)
        if t_bar is None or t_bar.get("close") is None or t_bar["close"] <= 0:
            continue
        t_close = t_bar["close"]

        # is_yizi check on T+1 (one-character limit-up, can't buy)
        is_st = t_bar.get("isST") == "1"
        limit = limit_for_code(code, is_st)
        if is_yizi_t1(t1_bar, t_close, limit):
            continue  # T+1 一字涨停, 买不进

        # Collect exit bars for each window
        exit_data: dict[str, tuple[str, float]] = {}
        all_valid = True
        for wname, woff in WINDOWS:
            exit_date = calendar[d_idx + woff]
            exit_bar = dmap.get(exit_date)
            if exit_bar is None or exit_bar.get("close") is None or exit_bar["close"] <= 0:
                all_valid = False
                break
            exit_data[wname] = (exit_date, exit_bar["close"])

        if not all_valid:
            continue

        regime = regime_map.get(ann_date, "unknown")

        pick = {
            "code": code,
            "ann_date": ann_date,
            "t1_date": t1_date,
            "entry": t1_open,
            "t_close": t_close,
            "regime": regime,
            "pct_total": ev["pct_total"],
            "year": ann_date[:4],
        }
        for wname, (edate, eclose) in exit_data.items():
            pick[f"{wname}_date"] = edate
            pick[f"{wname}_close"] = eclose
        picks.append(pick)

    print(
        f"[picks] built {len(picks)} picks from {len(events)} events (skipped {len(events) - len(picks)} — no kline / yizi / missing bars)"
    )
    return picks


# ---------- return functions ----------


def raw_ev(p: dict, wname: str) -> float | None:
    """Raw EV: (T+n close - T+1 open) / T+1 open."""
    eclose = p.get(f"{wname}_close")
    entry = p.get("entry")
    if eclose is None or entry is None or entry <= 0:
        return None
    return (eclose - entry) / entry * 100


def bhar(p: dict, wname: str, idx_bars: dict[str, dict]) -> float | None:
    """BHAR: stock return - market return over same window.

    Stock: (T+n close - T+1 open) / T+1 open  (matches actual trade entry)
    Market: (index T+n close - index T+1 open) / index T+1 open
    BHAR = Stock - Market  (isolates beta)
    """
    eclose = p.get(f"{wname}_close")
    entry = p.get("entry")
    t1_date = p.get("t1_date")
    exit_date = p.get(f"{wname}_date")
    if eclose is None or entry is None or entry <= 0 or t1_date is None or exit_date is None:
        return None
    i_t1 = idx_bars.get(t1_date)
    i_exit = idx_bars.get(exit_date)
    if i_t1 is None or i_exit is None:
        return None
    i_t1_open = i_t1.get("open")
    i_exit_close = i_exit.get("close")
    if i_t1_open is None or i_exit_close is None or i_t1_open <= 0:
        return None
    stock_ret = (eclose - entry) / entry * 100
    mkt_ret = (i_exit_close - i_t1_open) / i_t1_open * 100
    return stock_ret - mkt_ret


# ---------- walk-forward (event-study adapted) ----------


def walk_forward_event(
    picks: list[dict],
    wname: str,
    idx_bars: dict[str, dict],
) -> dict:
    """Walk-forward OOS: sort by ann_date, split half train/half test.
    Uses BHAR as return function."""
    if not picks:
        return {"status": "no_picks"}
    ps = sorted(picks, key=lambda p: p["ann_date"])
    dates = sorted(set(p["ann_date"] for p in ps))
    if len(dates) < 4:
        return {"status": "too_few_dates", "n_dates": len(dates)}
    mid = len(dates) // 2
    train_dates = set(dates[:mid])
    test_dates = set(dates[mid:])

    def _bhar_rets(subset_dates: set[str]) -> tuple[list[float], dict[str, list[float]]]:
        rets: list[float] = []
        by_date: dict[str, list[float]] = defaultdict(list)
        for p in ps:
            if p["ann_date"] not in subset_dates:
                continue
            r = bhar(p, wname, idx_bars)
            if r is not None:
                rets.append(r)
                by_date[p["ann_date"]].append(r)
        return rets, by_date

    tr_rets, tr_by_date = _bhar_rets(train_dates)
    te_rets, te_by_date = _bhar_rets(test_dates)
    tr_dt = day_paired_t(tr_by_date)
    te_dt = day_paired_t(te_by_date)
    return {
        "status": "ok",
        "n_train": len(tr_rets),
        "n_test": len(te_rets),
        "n_train_dates": len(train_dates),
        "n_test_dates": len(test_dates),
        "train_ev": ev_stats(tr_rets),
        "test_ev": ev_stats(te_rets),
        "train_day_t": tr_dt,
        "test_day_t": te_dt,
    }


# ---------- DSR estimation ----------


def estimate_dsr(bhar_rets: list[float], n_tests: int) -> dict:
    """Deflated Sharpe Ratio estimation (López de Prado).

    For event studies, use BHAR as the per-event return.
    DSR adjusts the observed Sharpe for multiple testing.
    """
    n = len(bhar_rets)
    if n < 2:
        return {"dsr": 0.0, "sharpe": 0.0, "n": n, "haircut": 0.0}
    mean = sum(bhar_rets) / n
    std = statistics.pstdev(bhar_rets)
    if std <= 0:
        return {"dsr": 0.0, "sharpe": 0.0, "n": n, "haircut": 0.0}
    sharpe = mean / std * sqrt(n)  # annualized-ish (per-event Sharpe * sqrt(n))
    # Expected max Sharpe under null (multiple testing)
    # e_z = (1 - euler_gamma) * norm_ppf(1 - 1/n_tests) + euler_gamma * norm_ppf(1 - 1/(n_tests*e))
    # Simplified: expected max SR ~ sqrt(2*ln(n_tests))
    from math import log, pi

    e_sr0 = sqrt(2 * log(n_tests)) if n_tests > 1 else 0.0
    # DSR = norm_sf((sharpe - e_sr0) / sqrt(1/n)) approx
    se = 1.0 / sqrt(n) if n > 0 else 1.0
    z = (sharpe / sqrt(n) - e_sr0 / sqrt(n)) / se if se > 0 else 0
    # Simpler: DSR ~ probability that observed Sharpe > expected max under null
    dsr = norm_sf_positive(z)
    haircut = max(0, 1 - sharpe / (e_sr0 * sqrt(n) + 0.001)) if e_sr0 > 0 else 0.0
    return {
        "dsr": round(dsr, 4),
        "sharpe": round(sharpe, 3),
        "e_sr0": round(e_sr0, 3),
        "n": n,
        "n_tests": n_tests,
        "haircut": round(haircut, 3),
    }


# ---------- analysis ----------


def analyze_subset(
    name: str,
    picks: list[dict],
    wname: str,
    idx_bars: dict[str, dict],
) -> dict:
    """Analyze one subset for one window: raw EV + BHAR + day-t + walk-forward + DSR."""
    print(f"\n{'=' * 70}")
    print(f"子集: {name} | 窗口: {wname} | n_picks={len(picks)}")
    print(f"{'=' * 70}")

    if not picks:
        print("  无 picks, 跳过")
        return {"name": name, "wname": wname, "n_picks": 0}

    # ---- raw EV (for reference, NOT primary) ----
    raw_rets = [raw_ev(p, wname) for p in picks]
    raw_rets = [r for r in raw_rets if r is not None]
    raw_s = ev_stats(raw_rets)
    print(f"\n--- raw EV (reference, NOT primary) ---")
    print(f"  n={raw_s['n']} gross_EV={raw_s['ev']}% WR={raw_s['wr']}% t={raw_s['t']} CI[{raw_s['ci_lo']},{raw_s['ci_hi']}]")

    # ---- BHAR (PRIMARY metric) ----
    bhar_rets = [bhar(p, wname, idx_bars) for p in picks]
    bhar_rets = [r for r in bhar_rets if r is not None]
    bhar_s = ev_stats(bhar_rets)
    bhar_net = bhar_s["ev"] - COST * 100
    print(f"\n--- BHAR vs 上证综指 (PRIMARY) ---")
    print(
        f"  n={bhar_s['n']} BHAR_gross={bhar_s['ev']}% std={bhar_s['std']}% "
        f"WR={bhar_s['wr']}% t={bhar_s['t']} CI[{bhar_s['ci_lo']},{bhar_s['ci_hi']}]"
    )
    print(f"  BHAR_net (after {COST * 100:.1f}% cost): {bhar_net:.3f}%")

    # ---- per-day-mean t ----
    bhar_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        r = bhar(p, wname, idx_bars)
        if r is not None:
            bhar_by_date[p["ann_date"]].append(r)
    bhar_dt = day_paired_t(bhar_by_date)
    print(f"  day-paired: n_days={bhar_dt['n_days']} mean={bhar_dt['mean']}% t={bhar_dt['t']} p_one_sided={bhar_dt['p_one_sided']}")

    # ---- Bonferroni ----
    # ×3 strategies × 3 windows = ×9 total tests reported
    # But verdict uses ×3 (cross-strategy) per window
    n_tests_verdict = N_CROSS_STRATEGY  # ×3 per window for verdict
    n_tests_report = N_CROSS_STRATEGY * N_WINDOWS  # ×9 for full report
    p_bonf_verdict = bonferroni_p(bhar_dt["p_one_sided"], n_tests_verdict)
    p_bonf_report = bonferroni_p(bhar_dt["p_one_sided"], n_tests_report)
    print(
        f"  Bonferroni: p_raw={bhar_dt['p_one_sided']} "
        f"×{n_tests_verdict}(verdict)={p_bonf_verdict:.6f} "
        f"×{n_tests_report}(full)={p_bonf_report:.6f}"
    )

    # ---- walk-forward OOS (BHAR) ----
    print(f"\n--- walk-forward OOS (BHAR, 前半 train → 后半 test) ---")
    wf = walk_forward_event(picks, wname, idx_bars)
    if wf["status"] == "ok":
        tr = wf["train_ev"]
        te = wf["test_ev"]
        tr_dt = wf["train_day_t"]
        te_dt = wf["test_day_t"]
        print(f"  train: n={tr['n']} n_dates={wf['n_train_dates']} BHAR={tr['ev']}% t={tr_dt['t']}")
        print(f"  test:  n={te['n']} n_dates={wf['n_test_dates']} BHAR={te['ev']}% t={te_dt['t']} p={te_dt['p_one_sided']}")
        decay = (tr["ev"] - te["ev"]) / abs(tr["ev"]) * 100 if tr["ev"] != 0 else 0
        print(f"  decay: {decay:.0f}% (train→test)")
    else:
        print(f"  {wf['status']} (n_dates={wf.get('n_dates', 0)})")

    # ---- DSR ----
    dsr = estimate_dsr(bhar_rets, n_tests_report)
    print(f"\n--- DSR (Deflated Sharpe Ratio, ×{n_tests_report} tests) ---")
    print(f"  Sharpe={dsr['sharpe']} e_sr0={dsr['e_sr0']} DSR={dsr['dsr']} haircut={dsr['haircut']}")

    # ---- verdict ----
    verdict = _verdict(
        bhar_gross=bhar_s["ev"],
        bhar_net=bhar_net,
        t_day=bhar_dt["t"],
        p_raw=bhar_dt["p_one_sided"],
        p_bonf=p_bonf_verdict,
        wf_status=wf["status"],
        wf_train_ev=wf.get("train_ev", {}).get("ev", 0) if wf["status"] == "ok" else 0,
        wf_test_ev=wf.get("test_ev", {}).get("ev", 0) if wf["status"] == "ok" else 0,
        wf_test_p=wf.get("test_day_t", {}).get("p_one_sided", 1.0) if wf["status"] == "ok" else 1.0,
        n_days=bhar_dt["n_days"],
    )

    return {
        "name": name,
        "wname": wname,
        "n_picks": len(picks),
        "n_days": bhar_dt["n_days"],
        "raw_ev": raw_s,
        "bhar_gross": bhar_s["ev"],
        "bhar_net": round(bhar_net, 3),
        "bhar_stats": bhar_s,
        "bhar_day_t": bhar_dt,
        "p_bonf_verdict": round(p_bonf_verdict, 6),
        "p_bonf_full": round(p_bonf_report, 6),
        "walk_forward": wf,
        "dsr": dsr,
        "verdict": verdict,
    }


def _verdict(
    bhar_gross: float,
    bhar_net: float,
    t_day: float,
    p_raw: float,
    p_bonf: float,
    wf_status: str,
    wf_train_ev: float,
    wf_test_ev: float,
    wf_test_p: float,
    n_days: int,
) -> str:
    """Honest verdict cascade (§44 v3, BHAR-primary)."""
    print(f"\n  VERDICT cascade:")
    print(f"    BHAR_gross={bhar_gross}% BHAR_net={bhar_net}% day_t={t_day} Bonf_p={p_bonf} n_days={n_days}")

    if bhar_gross < 0:
        print(f"    → FALSIFIED: BHAR gross < 0 (negative abnormal return)")
        return "edge-falsified"
    if n_days < 60:
        print(f"    → UNDERPOWERED: n_days={n_days} < 60")
        return "underpowered"
    if p_bonf >= ALPHA:
        print(f"    → FALSIFIED: Bonferroni p={p_bonf} >= {ALPHA} (not significant)")
        return "edge-falsified"
    if bhar_net <= 0:
        print(f"    → FALSIFIED: BHAR net={bhar_net}% <= 0 (edge eaten by cost)")
        return "edge-falsified"
    if wf_status == "ok":
        if wf_train_ev <= 0:
            print(f"    → EXPLORATORY: train BHAR={wf_train_ev}% <= 0 (edge not in train half, test may be regime overfitting)")
            return "exploratory"
        if wf_test_ev <= 0:
            print(f"    → FALSIFIED: walk-forward test BHAR={wf_test_ev}% <= 0")
            return "edge-falsified"
        wf_test_p_bonf = bonferroni_p(wf_test_p, N_CROSS_STRATEGY)
        if wf_test_p_bonf >= ALPHA:
            print(
                f"    → EXPLORATORY: OOS test BHAR={wf_test_ev}% > 0 but "
                f"test p={wf_test_p} Bonf×{N_CROSS_STRATEGY}={wf_test_p_bonf} >= {ALPHA}"
            )
            return "exploratory"
        print(f"    → EDGE-CONFIRMED: BHAR gross+net > 0, Bonf PASS, OOS test BHAR={wf_test_ev}% significant")
        return "edge-confirmed"
    print(f"    → EXPLORATORY: walk-forward not available")
    return "exploratory"


# ---------- main ----------


def main() -> None:
    print("=" * 70)
    print("大股东增持 (Insider Buy) 深挖 — Round 2 §44 v3")
    print("=" * 70)

    # Load data
    events = load_insider_buys()
    code_map = load_kline_db()
    idx_bars, calendar = load_index()
    regime_map = load_regime()

    # Build picks
    picks = build_insider_picks(events, code_map, calendar, idx_bars, regime_map)

    if not picks:
        print("\n[ERROR] No picks built. Check data coverage.")
        return

    # ---- overall stats ----
    print(f"\n{'=' * 70}")
    print(f"OVERALL: {len(picks)} picks, {len(set(p['ann_date'] for p in picks))} unique dates")
    years = defaultdict(int)
    regimes = defaultdict(int)
    for p in picks:
        years[p["year"]] += 1
        regimes[p["regime"]] += 1
    print(f"  Year distribution: {dict(sorted(years.items()))}")
    print(f"  Regime distribution: {dict(regimes)}")
    print(
        f"  Threshold: min={min(p['pct_total'] for p in picks):.3f}% "
        f"median={statistics.median([p['pct_total'] for p in picks]):.3f}% "
        f"max={max(p['pct_total'] for p in picks):.3f}%"
    )

    # ---- dimension 1: window comparison (all picks) ----
    print(f"\n{'#' * 70}")
    print("# DIMENSION 1: Window comparison (T+5 vs T+10 vs T+20)")
    print(f"{'#' * 70}")
    results_windows: list[dict] = []
    for wname, _ in WINDOWS:
        r = analyze_subset("all", picks, wname, idx_bars)
        results_windows.append(r)

    # ---- dimension 2: threshold bucketing (T+20 primary window) ----
    print(f"\n{'#' * 70}")
    print("# DIMENSION 2: Threshold bucketing (T+20 window)")
    print(f"{'#' * 70}")
    thresholds = [(0.1, ">=0.1%"), (0.5, ">=0.5%"), (1.0, ">=1%"), (5.0, ">=5%")]
    results_thresholds: list[dict] = []
    for thresh, label in thresholds:
        sub = [p for p in picks if p["pct_total"] >= thresh]
        r = analyze_subset(f"thresh_{label}", sub, "t20", idx_bars)
        results_thresholds.append(r)

    # ---- dimension 3: regime stratification (T+20) ----
    print(f"\n{'#' * 70}")
    print("# DIMENSION 3: Regime stratification (T+20 window)")
    print(f"{'#' * 70}")
    for regime_label in ["strong", "weak"]:
        sub = [p for p in picks if p["regime"] == regime_label]
        analyze_subset(f"regime_{regime_label}", sub, "t20", idx_bars)

    # ---- dimension 4: structural break (T+20) ----
    print(f"\n{'#' * 70}")
    print("# DIMENSION 4: Structural break (T+20 window)")
    print(f"{'#' * 70}")
    periods = [
        ("pre2020", lambda y: y < "2020"),
        ("2020_2022", lambda y: "2020" <= y <= "2022"),
        ("2023_2026", lambda y: y >= "2023"),
    ]
    for plabel, pfn in periods:
        sub = [p for p in picks if pfn(p["year"])]
        analyze_subset(f"period_{plabel}", sub, "t20", idx_bars)

    # ---- dimension 5: crash period control (T+20) ----
    print(f"\n{'#' * 70}")
    print("# DIMENSION 5: Crash period control (2015H2 crash vs non-crash, T+20)")
    print(f"{'#' * 70}")
    # 2015 crash: Jun 2015 - Feb 2016
    crash_picks = [p for p in picks if "2015-06" <= p["ann_date"] <= "2016-02"]
    noncrash_picks = [p for p in picks if not ("2015-06" <= p["ann_date"] <= "2016-02")]
    print(f"  Crash period (2015-06~2016-02): {len(crash_picks)} picks")
    print(f"  Non-crash: {len(noncrash_picks)} picks")
    analyze_subset("crash_2015H2", crash_picks, "t20", idx_bars)
    analyze_subset("non_crash", noncrash_picks, "t20", idx_bars)

    # ---- summary ----
    print(f"\n{'=' * 70}")
    print("SUMMARY: 大股东增持深挖结果")
    print(f"{'=' * 70}")
    print(f"\n窗口对比 (all picks, BHAR):")
    for r in results_windows:
        if r.get("n_picks", 0) > 0:
            print(
                f"  {r['wname']}: BHAR_gross={r['bhar_gross']}% net={r['bhar_net']}% "
                f"t={r['bhar_day_t']['t']} p_bonf={r['p_bonf_verdict']} "
                f"verdict={r['verdict']}"
            )
    print(f"\n阈值分桶 (T+20, BHAR):")
    for r in results_thresholds:
        if r.get("n_picks", 0) > 0:
            print(
                f"  {r['name']}: n={r['n_picks']} BHAR_gross={r['bhar_gross']}% "
                f"net={r['bhar_net']}% t={r['bhar_day_t']['t']} "
                f"p_bonf={r['p_bonf_verdict']} verdict={r['verdict']}"
            )

    # Check if any sub-condition survives
    all_results = results_windows + results_thresholds
    survivors = [r for r in all_results if r.get("verdict") in ("edge-confirmed", "exploratory")]
    print(f"\n存活子条件: {len(survivors)}/{len(all_results)} (edge-confirmed or exploratory)")
    if survivors:
        for s in survivors:
            print(f"  → {s['name']} | {s['wname']}: {s['verdict']} BHAR={s['bhar_gross']}% p_bonf={s['p_bonf_verdict']}")


if __name__ == "__main__":
    main()
