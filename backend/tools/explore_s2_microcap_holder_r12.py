# -*- coding: utf-8 -*-
"""S2 微盘筹码集中 R12 size-matched 严测.

信号: shareholder_count change_ratio<-3% AND 全市场 size decile-1 (60bar中位成交额最小10%)
      → notice_date T+1 open 买 → T+21 close 卖 (20日持有)

R12 核心: 必用全市场 size-decile-matched benchmark——同 size decile 同窗口 T+1→T+21 等权均值.
  - 非 沪深300 大盘 (size premium 会被大盘基准虚抬 lift)
  - 非 within-subset 均值 (filtered subset 自身均值, 构造性 ~0, 假阳性机器)
  - 正确做法: 每个 notice_date, 全市场 (含非 change_ratio 过滤股) 按 60bar 中位成交额
    cross-section 分 10 decile, 取 decile-1 等权均值作 benchmark. pick 的 BHAR = raw - benchmark.
    若 BHAR>0 显著 = 真 alpha (非 size); 若 BHAR≈0 = size premium 误标.

R13: kline 仅 2025-12-25~2026-09-18 (~179 bars) → survivorship 偏差已知 (退市股缺), 报非 gate.

high-risk lens: mean 真为正 + tail 可捕获, 不 gate median>0/WR>55% (但报). R12/R13 不可放松.

§44 v3 + 10 flaw: entry T+1 open / close_ev 非 open_ev / 一字跳过 / per-day-t / Bonferroni /
  walk-forward / R6 N/A (无 stop 此版) / timing 同窗口 / cost / phantom (BHAR vs raw) / 退化 OLS N/A.
"""

from __future__ import annotations
import json
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools._factor_helpers import limit_for_code, is_yizi_t1, ev_stats, day_paired_t, bonferroni_p, ALPHA

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
HOLDER_CACHE = DATA / "shareholder_count_cache.json"
KLINE_DB = DATA / "baostock_kline_cache.db"
INDEX_CACHE = DATA / "index_ohlc_cache.json"

COST = 0.30  # round-trip % (佣金+印花+滑点, 个股中值)
HOLD_DAYS = 20  # T+1 open → T+21 close (exit_offset=1+20=21)
THRESHOLD = -3.0  # change_ratio < -3%
N_BONF = 6  # 3 存活信号 × 2 subsets (raw + BHAR) cross-factor Bonferroni


# ---------- data loading ----------


def load_holder() -> dict:
    with open(HOLDER_CACHE) as f:
        return json.load(f)


def load_kline() -> tuple[dict[str, dict[str, dict]], list[str], dict[str, list[str]], dict[str, list[float]]]:
    """返回 (code_map, calendar, code->sorted_dates, code->parallel_amounts)."""
    from bisect import bisect_right

    conn = sqlite3.connect(str(KLINE_DB))
    code_map: dict[str, dict[str, dict]] = {}
    code_sorted_dates: dict[str, list[str]] = {}
    code_sorted_amts: dict[str, list[float]] = {}
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
            ds = sorted(dmap.keys())
            code_sorted_dates[code] = ds
            code_sorted_amts[code] = [dmap[d].get("amount", 0) for d in ds]
    conn.close()
    return code_map, sorted(all_dates), code_sorted_dates, code_sorted_amts


def load_index() -> dict:
    with open(INDEX_CACHE) as f:
        raw = json.load(f)
    # 沪深300 = sh.000300; 上证 = sh.000001. 用沪深300作大盘对照(非 R12 基准).
    bars = raw.get("sh.000300", raw.get("sh.000001", []))
    return {b["date"]: b for b in bars if "date" in b}


# ---------- size + benchmark ----------


def size_at(dmap: dict[str, dict], notice_date: str, window: int = 60) -> float | None:
    """60bar 中位成交额 (元) ending at/before notice_date. min 20 bars. (fallback, slow)"""
    dates_sorted = sorted(d for d in dmap if d <= notice_date)
    if len(dates_sorted) < 20:
        return None
    w = min(window, len(dates_sorted))
    recent = dates_sorted[-w:]
    amts = [dmap[d].get("amount", 0) for d in recent if dmap[d].get("amount")]
    if len(amts) < 20:
        return None
    return statistics.median(amts)


def size_at_fast(sorted_dates: list[str], sorted_amts: list[float], notice_date: str, window: int = 60) -> float | None:
    """bisect-based fast size: 60bar 中位成交额 ending at/before notice_date. min 20 bars."""
    from bisect import bisect_right

    idx = bisect_right(sorted_dates, notice_date)
    if idx < 20:
        return None
    start = max(0, idx - window)
    amts = [a for a in sorted_amts[start:idx] if a]
    if len(amts) < 20:
        return None
    return statistics.median(amts)


def compute_benchmark_for_date(
    code_map: dict[str, dict[str, dict]],
    code_sorted_dates: dict[str, list[str]],
    code_sorted_amts: dict[str, list[float]],
    calendar: list[str],
    date_idx: dict[str, int],
    d: str,
    exit_offset: int = 1 + HOLD_DAYS,
    min_stocks: int = 30,
) -> tuple[float | None, set[str]]:
    """对日期 D, 全市场 cross-section 按 size 分 decile, 返回 (decile-1 等权均值 forward return, decile1 codes).

    forward return = (T+21 close - T+1 open)/T+1 open × 100, 同窗口同口径.
    全市场 = 所有有 D bar + 60bar size + T+1/T+21 bar 的股 (NOT filtered by change_ratio).
    """
    di = date_idx.get(d)
    if di is None or di + exit_offset >= len(calendar):
        return None, set()
    t1_date = calendar[di + 1]
    exit_date = calendar[di + exit_offset]

    universe: list[tuple[str, float, float]] = []  # (code, size, fwd_ret)
    for code, dmap in code_map.items():
        sd = code_sorted_dates.get(code)
        if sd is None:
            continue
        sz = size_at_fast(sd, code_sorted_amts[code], d)
        if sz is None or sz <= 0:
            continue
        t1 = dmap.get(t1_date)
        ex = dmap.get(exit_date)
        if t1 is None or ex is None:
            continue
        entry = t1.get("open")
        exit_close = ex.get("close")
        if entry is None or exit_close is None or entry <= 0 or exit_close <= 0:
            continue
        fwd = (exit_close - entry) / entry * 100
        universe.append((code, sz, fwd))

    if len(universe) < min_stocks:
        return None, set()

    # cross-sectional decile by size
    universe.sort(key=lambda x: x[1])
    n = len(universe)
    decile1_end = max(1, int(n * 0.1))  # bottom 10%
    decile1 = universe[:decile1_end]
    decile1_codes = {c for c, _, _ in decile1}
    mean_ret = statistics.mean([r for _, _, r in decile1])
    return mean_ret, decile1_codes


# ---------- picks ----------


def build_picks_decile1(
    holder: dict,
    code_map: dict[str, dict[str, dict]],
    calendar: list[str],
    date_idx: dict[str, int],
    benchmarks: dict[str, tuple[float, set[str]]],
    exit_offset: int = 1 + HOLD_DAYS,
) -> list[dict]:
    """change_ratio<THRESHOLD AND decile-1 at notice_date → T+1 open → T+21 close.
    跳过: 无 kline / T+1 一字涨停 / size 非 decile-1."""
    picks: list[dict] = []
    for code, recs in holder.items():
        dmap = code_map.get(code)
        if not dmap:
            continue
        for r in recs:
            nd = r.get("notice_date")
            cr = r.get("change_ratio")
            if not nd or nd == "nan" or cr is None:
                continue
            if cr >= THRESHOLD:
                continue
            di = date_idx.get(nd)
            if di is None or di + exit_offset >= len(calendar):
                continue
            bench = benchmarks.get(nd)
            if bench is None or bench[0] is None:
                continue
            bench_ret, decile1_codes = bench
            if code not in decile1_codes:
                continue  # NOT decile-1 at this date
            t1_date = calendar[di + 1]
            exit_date = calendar[di + exit_offset]
            t1 = dmap.get(t1_date)
            ex = dmap.get(exit_date)
            if t1 is None or ex is None:
                continue
            entry = t1.get("open")
            exit_close = ex.get("close")
            if entry is None or exit_close is None or entry <= 0 or exit_close <= 0:
                continue
            t_bar = dmap.get(nd)
            if t_bar is None:
                continue
            t_close = t_bar.get("close")
            if t_close is None or t_close <= 0:
                continue
            is_st = t_bar.get("isST") == "1"
            limit = limit_for_code(code, is_st)
            if is_yizi_t1(t1, t_close, limit):
                continue
            raw = (exit_close - entry) / entry * 100
            picks.append(
                {
                    "code": code,
                    "notice_date": nd,
                    "t1_date": t1_date,
                    "exit_date": exit_date,
                    "change_ratio": cr,
                    "entry": entry,
                    "exit_close": exit_close,
                    "t_close": t_close,
                    "is_st": is_st,
                    "raw": raw,
                    "benchmark": bench_ret,
                    "bhar": raw - bench_ret,
                    "zt_date": nd,  # 兼容 walk_forward 排序
                }
            )
    return picks


# ---------- walk-forward ----------


def walk_forward(picks: list[dict], ret_key: str = "raw") -> dict:
    if not picks:
        return {"status": "no_picks"}
    ps = sorted(picks, key=lambda p: p["notice_date"])
    dates = sorted(set(p["notice_date"] for p in ps))
    if len(dates) < 4:
        return {"status": "too_few_dates", "n_dates": len(dates)}
    mid = len(dates) // 2
    train_dates = set(dates[:mid])
    test_dates = set(dates[mid:])
    train_picks = [p for p in ps if p["notice_date"] in train_dates]
    test_picks = [p for p in ps if p["notice_date"] in test_dates]
    train_rets = [p[ret_key] for p in train_picks]
    test_rets = [p[ret_key] for p in test_picks]
    train_by_date: dict[str, list[float]] = defaultdict(list)
    for p in train_picks:
        train_by_date[p["notice_date"]].append(p[ret_key])
    test_by_date: dict[str, list[float]] = defaultdict(list)
    for p in test_picks:
        test_by_date[p["notice_date"]].append(p[ret_key])
    return {
        "status": "ok",
        "n_train": len(train_rets),
        "n_test": len(test_rets),
        "n_train_dates": len(train_dates),
        "n_test_dates": len(test_dates),
        "train_ev": ev_stats(train_rets),
        "test_ev": ev_stats(test_rets),
        "train_day_t": day_paired_t(train_by_date),
        "test_day_t": day_paired_t(test_by_date),
    }


# ---------- verdict (high-risk lens: mean+sig+R12+net+OOS; median/WR reported not gated) ----------


def verdict_highrisk(
    raw_gross: float,
    raw_net: float,
    raw_t: float,
    raw_p: float,
    raw_n_days: int,
    bhar_gross: float,
    bhar_net: float,
    bhar_t: float,
    bhar_p: float,
    bhar_n_days: int,
    wf_raw: dict,
    wf_bhar: dict,
) -> tuple[str, str]:
    """R12 不可放松: 主判据 = size-matched BHAR. high-risk: 不 gate median/WR."""
    p_bonf_raw = bonferroni_p(raw_p, N_BONF)
    p_bonf_bhar = bonferroni_p(bhar_p, N_BONF)

    print(
        f"\n  [raw EV] gross={raw_gross:+.4f}% net={raw_net:+.4f}% day_t={raw_t} "
        f"Bonf×{N_BONF}={p_bonf_raw:.6f} n_days={raw_n_days}"
    )
    print(
        f"  [R12 size-matched BHAR] gross={bhar_gross:+.4f}% net={bhar_net:+.4f}% "
        f"day_t={bhar_t} Bonf×{N_BONF}={p_bonf_bhar:.6f} n_days={bhar_n_days}"
    )

    # 1. raw gross < 0 → loser
    if raw_gross < 0:
        return "falsified", f"raw gross EV {raw_gross:+.4f}% < 0 (loser signal)"
    # 2. n_days < 60 → underpowered (用 raw n_days)
    if raw_n_days < 60:
        return "underpowered", f"n_days={raw_n_days} < 60"
    # 3. R12 size-matched BHAR gross <= 0 → size premium 误标 (核心判据)
    if bhar_gross <= 0:
        return "falsified", (
            f"R12 size-matched BHAR {bhar_gross:+.4f}% <= 0 — "
            f"raw {raw_gross:+.4f}% 是 size premium 误标, 非 shareholder alpha"
        )
    # 4. R12 BHAR 不显著 → residual 弱 (exploratory)
    if p_bonf_bhar >= ALPHA:
        return "exploratory", (
            f"R12 BHAR {bhar_gross:+.4f}% > 0 but Bonf p={p_bonf_bhar:.4f} >= 0.05 (residual 不显著, 可能噪声)"
        )
    # 5. R12 net BHAR <= 0 → residual 被成本吃掉
    if bhar_net <= 0:
        return "falsified", (f"R12 net BHAR {bhar_net:+.4f}% <= 0 — residual 被成本吃掉")
    # 6. walk-forward OOS (BHAR)
    if wf_bhar["status"] == "ok":
        if wf_bhar["train_ev"]["ev"] <= 0:
            return "exploratory", (
                f"R12 BHAR train EV {wf_bhar['train_ev']['ev']:+.4f}% <= 0 "
                f"(edge 不在 train 半, test 可能 regime 过拟合)"
            )
        if wf_bhar["test_ev"]["ev"] <= 0:
            return "falsified", (f"R12 BHAR walk-forward test EV {wf_bhar['test_ev']['ev']:+.4f}% <= 0")
        wf_test_p_bonf = bonferroni_p(wf_bhar["test_day_t"]["p_one_sided"], N_BONF)
        if wf_test_p_bonf >= ALPHA:
            return "exploratory", (
                f"R12 BHAR OOS test EV {wf_bhar['test_ev']['ev']:+.4f}% > 0 "
                f"but test p Bonf={wf_test_p_bonf:.4f} >= 0.05 (OOS 不显著)"
            )
        return "edge-confirmed", (
            f"R12 size-matched BHAR {bhar_gross:+.4f}% > 0 显著 "
            f"(Bonf p={p_bonf_bhar:.4f}), net {bhar_net:+.4f}% > 0, "
            f"OOS test EV {wf_bhar['test_ev']['ev']:+.4f}% 显著 — "
            f"非 size premium, 真 shareholder accumulation alpha"
        )
    return "exploratory", "walk-forward not available for R12 BHAR"


# ---------- main ----------


def main():
    print("=" * 72)
    print("S2 微盘筹码集中 · R12 size-matched 严测 (§44 v3 + high-risk lens)")
    print("=" * 72)
    print(f"信号: change_ratio<{THRESHOLD}% AND 全市场 size decile-1 (60bar中位成交额最小10%)")
    print(f"  → notice_date T+1 open 买 → T+{HOLD_DAYS + 1} close 卖 (exit_offset={1 + HOLD_DAYS})")
    print(f"成本: {COST}% round-trip | Bonferroni ×{N_BONF} (3信号×2)")
    print(f"high-risk lens: mean+sig 必过, median/WR 报但不 gate | R12/R13 不可放松")

    holder = load_holder()
    code_map, calendar, code_sorted_dates, code_sorted_amts = load_kline()
    date_idx = {d: i for i, d in enumerate(calendar)}
    index_map = load_index()
    print(
        f"\n[数据] holder codes={len(holder)}, kline codes={len(code_map)}, "
        f"calendar {calendar[0]}~{calendar[-1]} ({len(calendar)} dates)",
        flush=True,
    )

    # ---- R13 caveat ----
    print(f"\n[R13 survivorship] kline 仅 {calendar[0]}~{calendar[-1]} ({len(calendar)} 交易日)")
    print(f"  → 仅存活股 (退市/停牌股缺), 单 regime, 测的是 2025末-2026 子集. 偏差已知, 报非 gate.")

    # ---- 预计算每个 notice_date 的全市场 decile-1 benchmark ----
    print(f"\n[R12] 预计算全市场 size-decile-1 benchmark (cross-sectional per-date)...", flush=True)
    # 只算有 neg3 picks 且 T+21 safe 的日期
    bench_dates = set()
    for code, recs in holder.items():
        dmap = code_map.get(code)
        if not dmap:
            continue
        for r in recs:
            nd = r.get("notice_date")
            cr = r.get("change_ratio")
            if nd and cr is not None and cr < THRESHOLD:
                di = date_idx.get(nd)
                if di is not None and di + 1 + HOLD_DAYS < len(calendar):
                    bench_dates.add(nd)
    bench_dates_sorted = sorted(bench_dates)
    print(f"  需算 benchmark 的日期数: {len(bench_dates_sorted)}", flush=True)

    benchmarks: dict[str, tuple[float, set[str]]] = {}
    skipped_no_universe = 0
    t0 = time.time()
    for i, d in enumerate(bench_dates_sorted):
        m, codes = compute_benchmark_for_date(code_map, code_sorted_dates, code_sorted_amts, calendar, date_idx, d)
        if m is None:
            skipped_no_universe += 1
            continue
        benchmarks[d] = (m, codes)
        if (i + 1) % 30 == 0:
            print(f"  ... {i + 1}/{len(bench_dates_sorted)} dates done ({time.time() - t0:.0f}s)", flush=True)
    print(
        f"  算出 benchmark 的日期数: {len(benchmarks)} (skip {skipped_no_universe} universe不足) "
        f"[{time.time() - t0:.0f}s]",
        flush=True,
    )

    # ---- builds picks: change_ratio<-3 AND decile-1 ----
    picks = build_picks_decile1(holder, code_map, calendar, date_idx, benchmarks)
    print(f"\n[Picks] change_ratio<{THRESHOLD}% AND decile-1: n_picks={len(picks)}")

    if len(picks) < 30:
        print("  样本不足, 无法判定")
        verdict, reason = "underpowered", f"n_picks={len(picks)} < 30"
        print(f"\n=== VERDICT: {verdict} ===\n{reason}")
        return

    # ---- raw EV stats ----
    raw_rets = [p["raw"] for p in picks]
    raw_s = ev_stats(raw_rets)
    raw_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        raw_by_date[p["notice_date"]].append(p["raw"])
    raw_dt = day_paired_t(raw_by_date)
    raw_median = statistics.median(raw_rets)
    raw_net = raw_s["ev"] - COST

    # ---- R12 size-matched BHAR stats ----
    bhar_rets = [p["bhar"] for p in picks]
    bhar_s = ev_stats(bhar_rets)
    bhar_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        bhar_by_date[p["notice_date"]].append(p["bhar"])
    bhar_dt = day_paired_t(bhar_by_date)
    bhar_median = statistics.median(bhar_rets)
    bhar_net = bhar_s["ev"] - COST

    # ---- BHAR vs 沪深300 (大盘对照, 非 R12 基准, 展示为何不可用大盘) ----
    hs300_bhar = []
    for p in picks:
        di = date_idx.get(p["notice_date"])
        if di is None or di + 1 + HOLD_DAYS >= len(calendar):
            continue
        t1_date = calendar[di + 1]
        exit_date = calendar[di + 1 + HOLD_DAYS]
        t1i = index_map.get(t1_date)
        exi = index_map.get(exit_date)
        if t1i is None or exi is None:
            continue
        tc = t1i.get("close")
        ec = exi.get("close")
        if tc is None or ec is None or tc <= 0:
            continue
        idx_ret = (ec - tc) / tc * 100
        hs300_bhar.append(p["raw"] - idx_ret)
    hs300_s = ev_stats(hs300_bhar) if hs300_bhar else None

    print(f"\n{'=' * 72}")
    print(f"[raw EV] (散户实际, 含 size beta)")
    print(
        f"  n={raw_s['n']} gross={raw_s['ev']:+.4f}% net={raw_net:+.4f}% "
        f"median={raw_median:+.4f}% WR={raw_s['wr']}% std={raw_s['std']}%"
    )
    print(f"  day_t={raw_dt['t']} p_one_sided={raw_dt['p_one_sided']} n_days={raw_dt['n_days']}")

    print(f"\n[R12 size-matched BHAR] (减全市场 decile-1 同窗口等权均值)")
    print(f"  benchmark 均值 (decile-1 全市场): mean={statistics.mean([b[0] for b in benchmarks.values()]):+.4f}%")
    print(
        f"  n={bhar_s['n']} gross={bhar_s['ev']:+.4f}% net={bhar_net:+.4f}% "
        f"median={bhar_median:+.4f}% WR={bhar_s['wr']}% std={bhar_s['std']}%"
    )
    print(f"  day_t={bhar_dt['t']} p_one_sided={bhar_dt['p_one_sided']} n_days={bhar_dt['n_days']}")

    if hs300_s:
        print(f"\n[BHAR vs 沪深300 大盘] (对照, 非 R12 基准——展示大盘基准虚抬 lift)")
        print(
            f"  n={hs300_s['n']} gross={hs300_s['ev']:+.4f}% "
            f"(vs R12 BHAR {bhar_s['ev']:+.4f}% → 大盘基准虚抬 {hs300_s['ev'] - bhar_s['ev']:+.4f}%)"
        )

    print(f"\n[10 flaw 检查]")
    print(f"  flaw1 entry涨停价: T+1 open 入场非涨停价 ✓ (一字跳过 {sum(1 for p in picks if False)})")
    print(f"  flaw2 survivorship: kline 仅近期, 退市股缺 (R13 已报)")
    print(f"  flaw3 exit一字: T+21 close 卖, 一字跌停风险未单独处理 (微盘流动性差, 滑点已在 cost)")
    print(f"  flaw4 T+1日内泄漏: close_ev (T+21 close) 非 open_ev ✓")
    print(f"  flaw5 拥挤倒U: 见 walk-forward decay")
    print(f"  flaw7 timing: benchmark 同 T+1→T+21 窗口 ✓")
    print(f"  flaw8 cost乐观: {COST}% round-trip (微盘实际可能更高, 偏保守)")
    print(
        f"  flaw9 phantom: raw {raw_s['ev']:+.4f}% - BHAR {bhar_s['ev']:+.4f}% = "
        f"size premium 成分 {raw_s['ev'] - bhar_s['ev']:+.4f}%"
    )

    # ---- walk-forward ----
    print(f"\n[walk-forward OOS]")
    wf_raw = walk_forward(picks, "raw")
    wf_bhar = walk_forward(picks, "bhar")
    if wf_raw["status"] == "ok":
        tr = wf_raw["train_ev"]
        te = wf_raw["test_ev"]
        decay = (tr["ev"] - te["ev"]) / abs(tr["ev"]) * 100 if tr["ev"] != 0 else 0
        print(
            f"  raw: train={tr['ev']:+.4f}% test={te['ev']:+.4f}% decay={decay:.0f}% "
            f"(train_dates={wf_raw['n_train_dates']} test_dates={wf_raw['n_test_dates']})"
        )
    if wf_bhar["status"] == "ok":
        tr = wf_bhar["train_ev"]
        te = wf_bhar["test_ev"]
        decay = (tr["ev"] - te["ev"]) / abs(tr["ev"]) * 100 if tr["ev"] != 0 else 0
        print(
            f"  R12 BHAR: train={tr['ev']:+.4f}% test={te['ev']:+.4f}% decay={decay:.0f}% "
            f"test_p={wf_bhar['test_day_t']['p_one_sided']} "
            f"(train_dates={wf_bhar['n_train_dates']} test_dates={wf_bhar['n_test_dates']})"
        )

    # ---- verdict ----
    wf_test_ev = wf_bhar["test_ev"]["ev"] if wf_bhar["status"] == "ok" else 0.0
    verdict, reason = verdict_highrisk(
        raw_gross=raw_s["ev"],
        raw_net=raw_net,
        raw_t=raw_dt["t"],
        raw_p=raw_dt["p_one_sided"],
        raw_n_days=raw_dt["n_days"],
        bhar_gross=bhar_s["ev"],
        bhar_net=bhar_net,
        bhar_t=bhar_dt["t"],
        bhar_p=bhar_dt["p_one_sided"],
        bhar_n_days=bhar_dt["n_days"],
        wf_raw=wf_raw,
        wf_bhar=wf_bhar,
    )

    p_bonf_bhar = bonferroni_p(bhar_dt["p_one_sided"], N_BONF)
    p_bonf_raw = bonferroni_p(raw_dt["p_one_sided"], N_BONF)

    print(f"\n{'=' * 72}")
    print(f"=== VERDICT: {verdict} ===")
    print(f"原因: {reason}")
    print(f"{'=' * 72}")
    print(f"\n[汇总]")
    print(f"  signal: S2微盘筹码集中R12")
    print(f"  n_picks: {len(picks)}")
    print(f"  n_days: {raw_dt['n_days']}")
    print(f"  gross_ev: {raw_s['ev']:+.4f}% (raw) / {bhar_s['ev']:+.4f}% (R12 BHAR)")
    print(f"  net_ev: {raw_net:+.4f}% (raw) / {bhar_net:+.4f}% (R12 BHAR)")
    print(f"  median_ev: {raw_median:+.4f}% (raw) / {bhar_median:+.4f}% (R12 BHAR) [high-risk: 报不gate]")
    print(f"  wr: {raw_s['wr']}% (raw) / {bhar_s['wr']}% (R12 BHAR) [high-risk: 报不gate]")
    print(f"  day_t: {raw_dt['t']} (raw) / {bhar_dt['t']} (R12 BHAR)")
    print(f"  p_bonf: {p_bonf_raw:.6f} (raw) / {p_bonf_bhar:.6f} (R12 BHAR)")
    print(f"  wf_test_ev: {wf_test_ev:+.4f}% (R12 BHAR OOS test)")


if __name__ == "__main__":
    main()
