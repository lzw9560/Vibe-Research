# -*- coding: utf-8 -*-
"""explore_piotroski.py

Piotroski F-Score 简化版（5 项会计指标复合，0-5 分）月频 long-only。
经典复合因子（项目未测，专家大概率推荐），数据在 fundamentals_cache.db。

F-Score 5 项（data available）：
- F1: ROE > 0（roe）
- F2: ROE YoY 上升（当前季 roe > 去年同季 roe）
- F3: 资产负债率 YoY 下降（debt_ratio 当前 < 去年同季）
- F4: 毛利率 YoY 上升（gp_margin 当前 > 去年同季）
- F5: 营收增长 > 0（rev_growth 已是 YoY）
Score 0-5，long top decile（高分=质量改善）。

设计同 value/quality：月频 long-only top-decile, PIT 对齐, filtered benchmark, walk-forward, Bonf×2, NW t。
"""
from __future__ import annotations
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import bonferroni_p, norm_sf_positive  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir  # noqa: E402

DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
FUND_DB = DATA / "fundamentals_cache.db"
COST = 0.004
N_BONF = 2  # 1 factor × 2 subsets


def pit_pubdate(stat_date: str) -> str:
    y, m = int(stat_date[:4]), int(stat_date[5:7])
    if m == 3: return f"{y}-04-30"
    if m == 6: return f"{y}-08-31"
    if m == 9: return f"{y}-10-31"
    if m == 12: return f"{y+1}-04-30"
    return stat_date


def load_funds() -> dict[str, list[dict]]:
    if not FUND_DB.exists():
        return {}
    conn = sqlite3.connect(str(FUND_DB))
    rows = conn.execute("""SELECT code, stat_date, roe, gp_margin, debt_ratio, rev_growth
        FROM fundamentals WHERE stat_date >= '2017-01-01' ORDER BY code, stat_date""").fetchall()
    conn.close()
    by_code: dict[str, list[dict]] = defaultdict(list)
    for code, sd, roe, gp, debt, rg in rows:
        by_code[code].append({"pit": pit_pubdate(sd), "stat": sd, "roe": roe, "gp": gp, "debt": debt, "rg": rg})
    return dict(by_code)


def piotroski_score(funds: list[dict], rebalance_date: str) -> int | None:
    """F-Score 0-5 at rebalance_date (PIT). 须当前季 + 去年同季都有."""
    avail = [f for f in funds if f["pit"] <= rebalance_date]
    if not avail:
        return None
    cur = avail[-1]
    cur_stat = cur["stat"]
    cur_y, cur_m = int(cur_stat[:4]), int(cur_stat[5:7])
    prior_same = f"{cur_y - 1}-{cur_stat[5:]}"
    prior = next((f for f in avail if f["stat"] == prior_same), None)
    if prior is None:
        return None
    score = 0
    # F1: ROE > 0
    if cur["roe"] is not None and cur["roe"] > 0:
        score += 1
    # F2: ROE YoY up
    if cur["roe"] is not None and prior["roe"] is not None and cur["roe"] > prior["roe"]:
        score += 1
    # F3: debt YoY down
    if cur["debt"] is not None and prior["debt"] is not None and cur["debt"] < prior["debt"]:
        score += 1
    # F4: gp YoY up
    if cur["gp"] is not None and prior["gp"] is not None and cur["gp"] > prior["gp"]:
        score += 1
    # F5: rev_growth > 0
    if cur["rg"] is not None and cur["rg"] > 0:
        score += 1
    return score


def select_universe(size: int = 250) -> list[str]:
    conn = sqlite3.connect(str(KLINE_DB))
    rows = []
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or len(bars) < 1500:
            continue
        amts = [float(b.get("amount", 0) or 0) for b in bars if b.get("amount")]
        if amts:
            rows.append((code, sum(amts) / len(amts)))
    conn.close()
    rows.sort(key=lambda x: -x[1])
    return [c for c, _ in rows[:size]]


def load_monthly_prices() -> tuple[dict, list]:
    conn = sqlite3.connect(str(KLINE_DB))
    code_months: dict = defaultdict(dict)
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list):
            continue
        by_month: dict = {}
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
            vol = b.get("volume", 0)
            try:
                vol = float(vol) if vol else 0
            except (ValueError, TypeError):
                vol = 0
            if vol <= 0:
                continue
            prev = by_month.get(month)
            if prev is None or d > prev[0]:
                by_month[month] = (d, c)
        for month, (d, c) in by_month.items():
            code_months[code][d] = c
    conn.close()
    all_dates: set = set()
    for m in code_months.values():
        all_dates.update(m.keys())
    return dict(code_months), sorted(all_dates)


def nw_t(rets: list[float], lag: int = 3) -> dict:
    n = len(rets)
    if n < 5:
        return {"mean": 0, "t": 0, "p": 1, "n": n}
    m = statistics.mean(rets)
    mc = [x - m for x in rets]
    g0 = sum(x * x for x in mc) / n
    rho = 0.0
    for l in range(1, lag + 1):
        w = 1 - l / (lag + 1)
        gl = sum(mc[i] * mc[i - l] for i in range(l, n)) / n
        rho += w * gl / g0 if g0 > 0 else 0
    ne = n / (1 + 2 * rho) if (1 + 2 * rho) > 0 else n
    se = (g0 / ne) ** 0.5 if g0 > 0 else 0
    t = m / se if se > 0 else 0
    return {"mean": round(m, 4), "t": round(t, 3), "p": round(norm_sf_positive(t), 6), "n": n}


def main() -> None:
    universe = select_universe(250)
    print(f"universe: top-250 liquidity, {len(universe)} stocks")
    funds = load_funds()
    print(f"fundamentals: {len(funds)} stocks")
    prices, month_dates = load_monthly_prices()
    print(f"prices: {len(prices)} stocks, {len(month_dates)} month-ends")
    # 月收益
    code_ret: dict = {}
    for code, md in prices.items():
        sd = sorted(md.keys())
        r = {}
        for i in range(1, len(sd)):
            if md[sd[i-1]] > 0:
                r[sd[i]] = (md[sd[i]] - md[sd[i-1]]) / md[sd[i-1]]
        code_ret[code] = r

    rebal_dates = [d for d in month_dates if d >= "2018-06-01"]
    excess_rets, strat_rets, bench_rets, dates_used = [], [], [], []
    for rd in rebal_dates:
        cand: list[tuple[str, int]] = []
        bench: list[str] = []
        for code in universe:
            if rd not in code_ret.get(code, {}):
                continue
            bench.append(code)
            fl = funds.get(code)
            if not fl:
                continue
            sc = piotroski_score(fl, rd)
            if sc is not None:
                cand.append((code, sc))
        if len(cand) < 20:
            continue
        # top decile = highest F-Score（>=4 或 top 10%）
        cand.sort(key=lambda x: -x[1])
        n_top = max(5, len(cand) // 10)
        top = [c for c, _ in cand[:n_top]]
        s_r = statistics.mean(code_ret[c][rd] for c in top)
        b_r = statistics.mean(code_ret[c][rd] for c in cand)  # filtered benchmark（有 score 的股）
        strat_net = s_r - COST
        excess = strat_net - b_r
        excess_rets.append(excess * 100)
        strat_rets.append(strat_net * 100)
        bench_rets.append(b_r * 100)
        dates_used.append(rd)
    if len(excess_rets) < 24:
        print(f"too_few n={len(excess_rets)}")
        return
    mid = len(dates_used) // 2
    train, test = excess_rets[:mid], excess_rets[mid:]
    for label, rets in [("full", excess_rets), ("train(2018-2022)", train), ("test(2022-2026)", test)]:
        nw = nw_t(rets)
        wr = sum(1 for x in rets if x > 0) / len(rets) * 100 if rets else 0
        pb = bonferroni_p(nw["p"], N_BONF)
        print(f"  {label}: n={nw['n']} mean={nw['mean']:.4f}%/月 WR={wr:.1f}% t_nw={nw['t']} p={nw['p']} Bonf×{N_BONF}={pb:.4f}")
    print(f"  benchmark(有score股等权) mean: {statistics.mean(bench_rets):.4f}%/月 | strategy: {statistics.mean(strat_rets):.4f}%/月")
    te = nw_t(test)
    tm = statistics.mean(test)
    pb = bonferroni_p(te["p"], N_BONF)
    print(f"\n--- VERDICT ---")
    print(f"  test excess={tm:.4f}% t={te['t']} Bonf={pb:.4f}")
    if tm < 0.1 or te["t"] < 2.9:
        print(f"  → FALSIFIED")
    elif pb >= 0.05:
        print(f"  → exploratory")
    else:
        print(f"  → ✅ edge-confirmed-provisional")


if __name__ == "__main__":
    main()
