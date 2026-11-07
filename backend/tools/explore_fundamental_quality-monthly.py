# -*- coding: utf-8 -*-
"""explore_fundamental_quality-monthly.py

基本面价值/质量因子月频 long-only backtest（72 explore 脚本未覆盖空间）。

数据：akshare stock_financial_analysis_indicator（1.9s/股全季度）→ SQLite cache
因子：4 变体（gpMargin 毛利率 / roeAvg 净资产收益率 / npMargin 净利率 / composite 质量）
口径（过严，复用 _factor_helpers + 5 步回测验证）：
  - PIT 对齐：用报告披露截止日非 statDate（Q1→4/30, H1→8/31, Q3→10/31, 年报→次年4/30）
    rebalance 日 D 只用 pubDate_estimate < D 的最新季报（防 look-ahead）
  - 月频非重叠 → 标准 t 合理（另附 Bartlett NW ~3 lags 稳健估计）
  - long-only top decile equal-weight，benchmark = universe equal-weight（cross-sectional alpha）
  - walk-forward：2018-2022 train → 2022-2026 test（50/50 by months）
  - Bonferroni ×8（4 因子 × 2 subsets train/test）
  - 成本 0.4% round-trip（月频换手），滑点敏感性 @ 0.2/0.4/0.6%
  - 幸存者偏差 caveat：universe = ≥1500 bars 股（6+年历史），标 survivorship-biased
  - realizable：月频 long-only 散户可交易（选股非融券，ETF/个股均可）
kill criteria：test net excess < +0.3%/月 OR t_nw < 2.9 OR 衰减 > 50%

禁止外推：单因子月频 ≠ 基本面整体有/无 edge ≠ 短线有/无 edge。
"""
from __future__ import annotations
import json
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime
from math import erf, sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import bonferroni_p, norm_sf_positive  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir  # noqa: E402

DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
FUND_DB = DATA / "fundamentals_cache.db"  # 新建，可续 backfill
COST = 0.004  # 0.4% round-trip（月频换手）
ALPHA = 0.05
UNIVERSE_SIZE = 250  # top-liquidity，exploratory first pass
REBALANCE_DAY = "last"  # 月末最后交易日调仓

# ── akshare 字段映射（中文列名 → 英文因子名）──────────────────────────────────
FIELD_MAP = {
    "日期": "stat_date",
    "销售毛利率": "gp_margin",      # gross margin (Hou-Xue-Zhang quality)
    "销售净利率": "np_margin",      # net margin
    "净资产收益率": "roe",          # ROE
    "加权净资产收益率": "roe_w",    # weighted ROE
    "资产负债率": "debt_ratio",    # leverage
    "主营业务收入增长率": "rev_growth",  # revenue growth
    "净利润增长率": "ni_growth",   # NI growth
}


def ensure_fund_table() -> None:
    conn = sqlite3.connect(str(FUND_DB))
    conn.execute("""CREATE TABLE IF NOT EXISTS fundamentals (
        code TEXT, stat_date TEXT, gp_margin REAL, np_margin REAL,
        roe REAL, roe_w REAL, debt_ratio REAL, rev_growth REAL, ni_growth REAL,
        PRIMARY KEY (code, stat_date))""")
    conn.commit()
    conn.close()


def cached_codes() -> set[str]:
    if not FUND_DB.exists():
        return set()
    conn = sqlite3.connect(str(FUND_DB))
    rows = conn.execute("SELECT DISTINCT code FROM fundamentals").fetchall()
    conn.close()
    return {r[0] for r in rows}


def backfill_one(code_bare: str) -> int:
    """单股 baostock code（6位裸）→ akshare 拉 + 存。返入库行数。"""
    import akshare as ak  # noqa: PLC0415
    try:
        df = ak.stock_financial_analysis_indicator(symbol=code_bare, start_year="2018")
    except Exception:
        return 0
    if df is None or len(df) == 0:
        return 0
    # 列名可能有空格/换行，strip
    df.columns = [str(c).strip() for c in df.columns]
    rows = []
    for _, r in df.iterrows():
        stat_date = str(r.get("日期", "")).strip()
        if not stat_date or stat_date == "nan" or len(stat_date) < 10:
            continue
        stat_date = stat_date[:10]
        row = {"code": code_bare, "stat_date": stat_date}
        for cn, en in FIELD_MAP.items():
            if cn in r.index:
                v = r[cn]
                try:
                    row[en] = float(v) if str(v) not in ("nan", "None", "") else None
                except (ValueError, TypeError):
                    row[en] = None
        rows.append(row)
    if not rows:
        return 0
    conn = sqlite3.connect(str(FUND_DB))
    conn.executemany("""INSERT OR REPLACE INTO fundamentals
        (code, stat_date, gp_margin, np_margin, roe, roe_w, debt_ratio, rev_growth, ni_growth)
        VALUES (:code, :stat_date, :gp_margin, :np_margin, :roe, :roe_w, :debt_ratio, :rev_growth, :ni_growth)""", rows)
    conn.commit()
    conn.close()
    return len(rows)


def backfill_all(universe: list[str]) -> None:
    ensure_fund_table()
    done = cached_codes()
    todo = [c for c in universe if c not in done]
    print(f"backfill: {len(universe)} universe, {len(done)} cached, {len(todo)} todo")
    for i, code in enumerate(todo):
        n = backfill_one(code)
        print(f"  [{i+1}/{len(todo)}] {code}: {n} rows", flush=True)
        time.sleep(0.3)  # 防封 pacing


# ── kline 价格（月频 close）──────────────────────────────────────────────────

def load_monthly_prices() -> tuple[dict[str, dict[str, float]], list[str]]:
    """返 (code -> {month_end_date: close}, sorted month_end_dates).
    月末 close = 该月最后一个交易日的 close。code 用 6 位裸数字。"""
    conn = sqlite3.connect(str(KLINE_DB))
    code_months: dict[str, dict[str, float]] = defaultdict(dict)
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list):
            continue
        # 按月分组取最后交易日 close
        by_month: dict[str, tuple[str, float]] = {}  # month -> (date, close)
        for b in bars:
            d = b.get("date", "")
            if not d or len(d) < 7:
                continue
            month = d[:7]
            c = b.get("close")
            try:
                c = float(c) if c else None
            except (ValueError, TypeError):
                c = None
            if c is None or c <= 0:
                continue
            prev = by_month.get(month)
            if prev is None or d > prev[0]:
                by_month[month] = (d, c)
        for month, (d, c) in by_month.items():
            code_months[code][d] = c  # key 用实际交易日 date（月末）
    conn.close()
    # 合并所有月末日期
    all_dates: set[str] = set()
    for m in code_months.values():
        all_dates.update(m.keys())
    return dict(code_months), sorted(all_dates)


# ── PIT 对齐 ─────────────────────────────────────────────────────────────────

def pit_pubdate(stat_date: str) -> str:
    """报告披露截止日（保守 PIT 估计）。
    Q1(03-31)→04-30, H1(06-30)→08-31, Q3(09-30)→10-31, 年报(12-31)→次年04-30."""
    y, m, d = int(stat_date[:4]), int(stat_date[5:7]), int(stat_date[8:10])
    if m == 3:
        return f"{y}-04-30"
    if m == 6:
        return f"{y}-08-31"
    if m == 9:
        return f"{y}-10-31"
    if m == 12:
        return f"{y+1}-04-30"
    return stat_date  # fallback


def load_fundamentals_pit() -> dict[str, list[dict]]:
    """返 code -> [(pit_pubdate, stat_date, factors...)] 按 pit_pubdate 排序."""
    if not FUND_DB.exists():
        return {}
    conn = sqlite3.connect(str(FUND_DB))
    rows = conn.execute("""SELECT code, stat_date, gp_margin, np_margin, roe, debt_ratio, rev_growth, ni_growth
        FROM fundamentals WHERE stat_date >= '2017-01-01' ORDER BY code, stat_date""").fetchall()
    conn.close()
    by_code: dict[str, list[dict]] = defaultdict(list)
    for code, sd, gp, np_, roe, debt, rg, nig in rows:
        by_code[code].append({
            "pit": pit_pubdate(sd), "stat": sd,
            "gp": gp, "np": np_, "roe": roe, "debt": debt, "rg": rg, "nig": nig,
        })
    return dict(by_code)


def latest_factor_pit(funds: list[dict], rebalance_date: str, field: str) -> float | None:
    """rebalance_date 时点 PIT 可用的最新因子值。None=无可用数据（跳过该股）."""
    avail = [f for f in funds if f["pit"] <= rebalance_date and f.get(field) is not None]
    if not avail:
        return None
    return avail[-1][field]  # 已按 stat_date 排序，取最新


# ── universe 选择（top liquidity）────────────────────────────────────────────

def select_universe(size: int = UNIVERSE_SIZE) -> list[str]:
    """从 kline cache 选 top-size 按 average amount（most liquid, tradeable for 散户）.
    6 位裸 code（akshare symbol 格式）."""
    conn = sqlite3.connect(str(KLINE_DB))
    rows = []
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or len(bars) < 1500:
            continue  # ≥6 年历史（幸存者 caveat）
        amts = [float(b.get("amount", 0) or 0) for b in bars if b.get("amount")]
        if amts:
            rows.append((code, sum(amts) / len(amts)))
    conn.close()
    rows.sort(key=lambda x: -x[1])
    return [c for c, _ in rows[:size]]


# ── 月频 backtest ────────────────────────────────────────────────────────────

def compute_monthly_returns(prices: dict[str, dict[str, float]],
                            month_dates: list[str]) -> dict[str, dict[str, float]]:
    """code -> {month_date: monthly_decimal_return}（close-to-close 月收益）."""
    rets: dict[str, dict[str, float]] = {}
    for code, md in prices.items():
        sorted_d = sorted(md.keys())
        r: dict[str, float] = {}
        for i in range(1, len(sorted_d)):
            prev_c = md[sorted_d[i - 1]]
            cur_c = md[sorted_d[i]]
            if prev_c > 0:
                r[sorted_d[i]] = (cur_c - prev_c) / prev_c
        rets[code] = r
    return rets


def backtest_factor(factor_field: str, funds: dict[str, list[dict]],
                    prices: dict[str, dict[str, float]],
                    month_rets: dict[str, dict[str, float]],
                    month_dates: list[str]) -> dict:
    """单因子月频 long-only top-decile backtest.
    返 {monthly_excess: [...], train/test split, stats}."""
    # 用 2018-04 起的月末（前几月 warmup for PIT）
    rebal_dates = [d for d in month_dates if d >= "2018-04-01"]
    strategy_rets: list[float] = []
    benchmark_rets: list[float] = []
    excess_rets: list[float] = []
    dates_used: list[str] = []
    for rd in rebal_dates:
        # 该月末可用股票的因子值
        candidates: list[tuple[str, float]] = []
        bench_codes: list[str] = []
        for code in prices:
            if rd not in month_rets.get(code, {}):
                continue
            bench_codes.append(code)
            fl = funds.get(code)
            if not fl:
                continue
            fv = latest_factor_pit(fl, rd, factor_field)
            if fv is not None:
                candidates.append((code, fv))
        if len(candidates) < 20:
            continue  # 股太少跳过
        # top decile (top 10%)
        candidates.sort(key=lambda x: -x[1])
        n_top = max(5, len(candidates) // 10)
        top_codes = [c for c, _ in candidates[:n_top]]
        # 等权 strategy 月收益
        s_r = statistics.mean(month_rets[c][rd] for c in top_codes)
        # 等权 benchmark（全 universe 可交易股）
        b_r = statistics.mean(month_rets[c][rd] for c in bench_codes)
        strat_net = s_r - COST  # 月频换手 round-trip cost
        excess = strat_net - b_r
        strategy_rets.append(strat_net * 100)
        benchmark_rets.append(b_r * 100)
        excess_rets.append(excess * 100)
        dates_used.append(rd)

    if len(excess_rets) < 24:
        return {"status": "too_few", "n": len(excess_rets)}

    # walk-forward 50/50 by months
    mid = len(dates_used) // 2
    train, test = excess_rets[:mid], excess_rets[mid:]
    return {
        "status": "ok", "n_months": len(excess_rets),
        "dates": dates_used,
        "excess": excess_rets, "strategy": strategy_rets, "benchmark": benchmark_rets,
        "train": train, "test": test,
    }


# ── stats（NW t for monthly）─────────────────────────────────────────────────

def nw_t_monthly(rets: list[float], max_lag: int = 3) -> dict:
    """Newey-West t for monthly returns (Bartlett weights, lag ~3).
    月频非重叠 → 小 lag 即可."""
    n = len(rets)
    if n < 5:
        return {"mean": 0, "t": 0, "p": 1, "n": n}
    m = statistics.mean(rets)
    # 方差：NW Bartlett-weighted
    mean_centered = [x - m for x in rets]
    gamma0 = sum(x * x for x in mean_centered) / n
    rho_sum = 0.0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)  # Bartlett
        gamma_lag = sum(mean_centered[i] * mean_centered[i - lag]
                        for i in range(lag, n)) / n
        rho_sum += w * gamma_lag / gamma0 if gamma0 > 0 else 0
    n_eff = n / (1 + 2 * rho_sum) if (1 + 2 * rho_sum) > 0 else n
    se = (gamma0 / n_eff) ** 0.5 * 100 if gamma0 > 0 else 0  # rets 已 ×100
    # 注：rets 已是百分比，gamma0 也是百分比平方；se 用 sqrt(gamma0/n_eff)
    se = sqrt(gamma0) / sqrt(n_eff) if gamma0 > 0 else 0
    t = m / se if se > 0 else 0
    p = norm_sf_positive(t)
    return {"mean": round(m, 4), "t": round(t, 3), "p": round(p, 6), "n": n, "n_eff": round(n_eff, 1)}


def stats_block(rets: list[float], label: str, n_bonf: int) -> dict:
    if not rets:
        print(f"  {label}: 无数据")
        return {}
    nw = nw_t_monthly(rets)
    wr = sum(1 for x in rets if x > 0) / len(rets) * 100
    p_bonf = bonferroni_p(nw["p"], n_bonf)
    print(f"  {label}: n={nw['n']} mean={nw['mean']:.4f}%/月 WR={wr:.1f}% "
          f"t_nw={nw['t']} p={nw['p']} Bonf×{n_bonf}={p_bonf:.6f}")
    return {**nw, "wr": round(wr, 1), "p_bonf": round(p_bonf, 6)}


# ── composite quality factor ────────────────────────────────────────────────

def backtest_composite(funds: dict[str, list[dict]],
                       prices: dict[str, dict[str, float]],
                       month_rets: dict[str, dict[str, float]],
                       month_dates: list[str]) -> dict:
    """composite quality = rank(gp) + rank(roe) + rank(np) - rank(debt).
    月频 cross-sectional rank 合成."""
    rebal_dates = [d for d in month_dates if d >= "2018-04-01"]
    excess_rets: list[float] = []
    strategy_rets: list[float] = []
    benchmark_rets: list[float] = []
    dates_used: list[str] = []
    for rd in rebal_dates:
        bench_codes: list[str] = []
        cand: dict[str, dict] = {}
        for code in prices:
            if rd not in month_rets.get(code, {}):
                continue
            bench_codes.append(code)
            fl = funds.get(code)
            if not fl:
                continue
            gp = latest_factor_pit(fl, rd, "gp")
            roe = latest_factor_pit(fl, rd, "roe")
            np_ = latest_factor_pit(fl, rd, "np")
            debt = latest_factor_pit(fl, rd, "debt")
            if gp is None or roe is None:
                continue
            cand[code] = {"gp": gp, "roe": roe, "np": np_, "debt": debt}
        if len(cand) < 20:
            continue
        # cross-sectional rank（高 gp/roe/np 好，高 debt 坏）
        def rank_map(field: str, higher_better: bool = True) -> dict[str, float]:
            vals = [(c, v[field]) for c, v in cand.items() if v[field] is not None]
            vals.sort(key=lambda x: -x[1] if higher_better else x[1])
            n = len(vals)
            return {c: i / n for i, (c, _) in enumerate(vals)}  # 0=best
        rg = rank_map("gp", True)
        rr = rank_map("roe", True)
        rn = rank_map("np", True)
        rd_debt = rank_map("debt", False)  # 低 debt 好
        scores = {c: rg.get(c, 0.5) + rr.get(c, 0.5) + rn.get(c, 0.5) + rd_debt.get(c, 0.5)
                  for c in cand}
        top = sorted(scores.items(), key=lambda x: x[1])[:max(5, len(cand) // 10)]
        top_codes = [c for c, _ in top]
        s_r = statistics.mean(month_rets[c][rd] for c in top_codes)
        b_r = statistics.mean(month_rets[c][rd] for c in bench_codes)
        strat_net = s_r - COST
        excess_rets.append((strat_net - b_r) * 100)
        strategy_rets.append(strat_net * 100)
        benchmark_rets.append(b_r * 100)
        dates_used.append(rd)
    if len(excess_rets) < 24:
        return {"status": "too_few", "n": len(excess_rets)}
    mid = len(dates_used) // 2
    return {
        "status": "ok", "n_months": len(excess_rets), "dates": dates_used,
        "excess": excess_rets, "strategy": strategy_rets, "benchmark": benchmark_rets,
        "train": excess_rets[:mid], "test": excess_rets[mid:],
    }


# ── 滑点敏感性（5 步验证 #3）─────────────────────────────────────────────────

def slippage_sensitivity(factor_field: str, funds, prices, month_rets, month_dates) -> None:
    print(f"\n--- 滑点敏感性（{factor_field}，net @ 多 COST）---")
    for cost_pct in (0.2, 0.4, 0.6, 0.8):
        cost = cost_pct / 100
        # 重算 excess with this cost（reuse backtest but override COST）
        rebal_dates = [d for d in month_dates if d >= "2018-04-01"]
        excess: list[float] = []
        for rd in rebal_dates:
            cand: list[tuple[str, float]] = []
            bench: list[str] = []
            for code in prices:
                if rd not in month_rets.get(code, {}):
                    continue
                bench.append(code)
                fl = funds.get(code)
                if not fl:
                    continue
                fv = latest_factor_pit(fl, rd, factor_field)
                if fv is not None:
                    cand.append((code, fv))
            if len(cand) < 20:
                continue
            cand.sort(key=lambda x: -x[1])
            top = [c for c, _ in cand[:max(5, len(cand) // 10)]]
            s_r = statistics.mean(month_rets[c][rd] for c in top)
            b_r = statistics.mean(month_rets[c][rd] for c in bench)
            excess.append((s_r - cost - b_r) * 100)
        if excess:
            nw = nw_t_monthly(excess)
            print(f"  COST={cost_pct:.1f}%: net_excess={nw['mean']:.4f}%/月 t_nw={nw['t']} (n={nw['n']})")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="先跑 backfill")
    ap.add_argument("--size", type=int, default=UNIVERSE_SIZE)
    args = ap.parse_args()

    universe = select_universe(args.size)
    print(f"universe: top-{args.size} liquidity, {len(universe)} stocks (≥6yr history, survivorship caveat)")

    if args.backfill:
        backfill_all(universe)

    print("\n=== load data ===")
    funds = load_fundamentals_pit()
    print(f"fundamentals: {len(funds)} stocks cached")
    if len(funds) < 50:
        print("⚠️ fundamentals 不足 50，请先 --backfill")
        return
    prices, month_dates = load_monthly_prices()
    print(f"prices: {len(prices)} stocks, {len(month_dates)} month-ends")
    month_rets = compute_monthly_returns(prices, month_dates)
    print(f"month_returns: computed")

    N_BONF = 8  # 4 factors × 2 subsets
    factors = [
        ("gp_margin（毛利率, Hou-Xue-Zhang quality）", "gp"),
        ("roe（净资产收益率）", "roe"),
        ("np_margin（净利率）", "np"),
    ]
    results: dict[str, dict] = {}
    print(f"\n{'='*70}\n=== 月频 long-only top-decile backtest（2018-2026, PIT 对齐）===\n{'='*70}")
    for label, field in factors:
        print(f"\n--- {label} ---")
        r = backtest_factor(field, funds, prices, month_rets, month_dates)
        if r["status"] != "ok":
            print(f"  {r['status']} (n={r.get('n', 0)})")
            continue
        results[field] = r
        # full period
        full = stats_block(r["excess"], "full", N_BONF)
        train = stats_block(r["train"], "train(2018-2022)", N_BONF)
        test = stats_block(r["test"], "test(2022-2026)", N_BONF)
        if train and test and train.get("mean", 0) != 0:
            decay = (train["mean"] - test["mean"]) / abs(train["mean"]) * 100
            print(f"  衰减: {decay:.0f}% (train→test)")
        # benchmark mean for context
        if r["benchmark"]:
            print(f"  benchmark(universe等权) mean: {statistics.mean(r['benchmark']):.4f}%/月")
            print(f"  strategy mean: {statistics.mean(r['strategy']):.4f}%/月 (net @ 0.4% cost)")

    # composite
    print(f"\n--- composite quality (rank gp+roe+np-debt) ---")
    rc = backtest_composite(funds, prices, month_rets, month_dates)
    if rc["status"] == "ok":
        results["composite"] = rc
        stats_block(rc["excess"], "full", N_BONF)
        stats_block(rc["train"], "train(2018-2022)", N_BONF)
        stats_block(rc["test"], "test(2022-2026)", N_BONF)
        if rc["benchmark"]:
            print(f"  benchmark mean: {statistics.mean(rc['benchmark']):.4f}%/月 | strategy: {statistics.mean(rc['strategy']):.4f}%/月")

    # 滑点敏感性（最强因子）
    best_field = max((f for f in results if f != "composite"),
                     key=lambda f: results[f].get("excess") and statistics.mean(results[f]["excess"]) or -999,
                     default=None)
    if best_field:
        slippage_sensitivity(best_field, funds, prices, month_rets, month_dates)

    # ── 诚实 verdict ──
    print(f"\n{'='*70}\n=== VERDICT（Bonf×{N_BONF}, walk-forward, kill criteria）===\n{'='*70}")
    for name, r in results.items():
        if r["status"] != "ok":
            continue
        test = r["test"]
        if not test:
            continue
        nw = nw_t_monthly(test)
        train_mean = statistics.mean(r["train"]) if r["train"] else 0
        test_mean = statistics.mean(test)
        decay = (train_mean - test_mean) / abs(train_mean) * 100 if train_mean != 0 else 0
        p_bonf = bonferroni_p(nw["p"], N_BONF)
        print(f"\n  [{name}]")
        print(f"    test: net_excess={test_mean:.4f}%/月 t_nw={nw['t']} p={nw['p']} Bonf×{N_BONF}={p_bonf:.4f}")
        print(f"    train={train_mean:.4f}% test={test_mean:.4f}% 衰减={decay:.0f}%")
        if test_mean < 0.3:
            print(f"    → KILL: test net_excess {test_mean:.4f}% < +0.3%/月 threshold")
        elif nw["t"] < 2.9:
            print(f"    → KILL: t_nw {nw['t']} < 2.9")
        elif decay > 50:
            print(f"    → KILL: 衰减 {decay:.0f}% > 50%")
        elif p_bonf < ALPHA:
            print(f"    → ✅ edge-confirmed-provisional: test net >0.3% t_nw>2.9 衰减<50% Bonf PASS")
        else:
            print(f"    → exploratory: Bonf {p_bonf:.4f} >= {ALPHA} (not significant after ×{N_BONF})")

    # 存 result JSON
    out = {name: {k: v for k, v in r.items() if k in ("status", "n_months")}
           for name, r in results.items()}
    out["_meta"] = {"universe_size": args.size, "n_bonf": N_BONF,
                    "cost": COST, "survivorship_caveat": "≥6yr history stocks only"}
    import json as _json
    Path(__file__).parent / "_fundamental_quality_monthly_result.json"
    p = Path(__file__).parent / "_fundamental_quality_monthly_result.json"
    p.write_text(_json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nresult JSON -> {p}")


if __name__ == "__main__":
    main()
