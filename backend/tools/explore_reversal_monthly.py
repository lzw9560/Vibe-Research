# -*- coding: utf-8 -*-
"""explore_reversal_monthly.py

中频反转因子（1-3 月 horizon）月频 long-only backtest。
短反转（1-3天）已证伪（72脚本），但中频反转不同 horizon（Jegadeesh-Titman: 1月反转存在, 3-12月动量）。
未测空间——做减法定型后专家审查期间并行测。

设计：
- Universe: top-250 liquidity（与 value/quality 一致）
- 因子: 过去 N 月 return（N=1,3）, bottom decile（超卖/loser）long-only
- 持有 1 月, 月频调仓
- benchmark = universe equal-weight
- walk-forward 2018-2022/2022-2026 + Bonf×4 + NW t
- 幸存者 caveat（≥1500bars）
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
COST = 0.004
N_BONF = 4  # 2 lookback × 2 subsets


def load_monthly_prices() -> tuple[dict[str, dict[str, float]], list[str]]:
    conn = sqlite3.connect(str(KLINE_DB))
    code_months: dict[str, dict[str, float]] = defaultdict(dict)
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list):
            continue
        by_month: dict[str, tuple[str, float]] = {}
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
    all_dates: set[str] = set()
    for m in code_months.values():
        all_dates.update(m.keys())
    return dict(code_months), sorted(all_dates)


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


def backtest_reversal(lookback: int, prices: dict, month_dates: list, universe: list[str]) -> dict:
    """bottom decile by past N-month return（超卖反弹）, hold 1 month."""
    # 算每股月收益 + past N-month cumulative return
    code_monthly_ret: dict[str, dict[str, float]] = {}
    for code in universe:
        md = prices.get(code, {})
        sorted_d = sorted(md.keys())
        r: dict[str, float] = {}
        for i in range(1, len(sorted_d)):
            prev_c = md[sorted_d[i - 1]]
            cur_c = md[sorted_d[i]]
            if prev_c > 0:
                r[sorted_d[i]] = (cur_c - prev_c) / prev_c
        code_monthly_ret[code] = r

    rebal_dates = [d for d in month_dates if d >= "2018-06-01"]  # warmup for lookback
    excess_rets: list[float] = []
    strategy_rets: list[float] = []
    benchmark_rets: list[float] = []
    dates_used: list[str] = []
    for rd in rebal_dates:
        # 算每股 past N-month cumulative return at rd
        candidates: list[tuple[str, float]] = []
        bench: list[str] = []
        rd_idx = month_dates.index(rd) if rd in month_dates else -1
        if rd_idx < lookback:
            continue
        for code in universe:
            if rd not in code_monthly_ret.get(code, {}):
                continue
            bench.append(code)
            # past N-month cumulative = ∏(1+ret) - 1 over past N months ending at rd (exclusive)
            past_dates = month_dates[rd_idx - lookback:rd_idx]
            cum = 1.0
            ok = True
            for pd in past_dates:
                r = code_monthly_ret[code].get(pd)
                if r is None:
                    ok = False
                    break
                cum *= (1 + r)
            if not ok:
                continue
            past_ret = (cum - 1)
            candidates.append((code, past_ret))
        if len(candidates) < 20:
            continue
        # bottom decile = worst past return (超卖) → long (reversal bet)
        candidates.sort(key=lambda x: x[1])  # ascending, worst first
        n_bot = max(5, len(candidates) // 10)
        bot_codes = [c for c, _ in candidates[:n_bot]]
        s_r = statistics.mean(code_monthly_ret[c][rd] for c in bot_codes)
        b_r = statistics.mean(code_monthly_ret[c][rd] for c in bench)
        strat_net = s_r - COST
        excess = strat_net - b_r
        excess_rets.append(excess * 100)
        strategy_rets.append(strat_net * 100)
        benchmark_rets.append(b_r * 100)
        dates_used.append(rd)
    if len(excess_rets) < 24:
        return {"status": "too_few", "n": len(excess_rets)}
    mid = len(dates_used) // 2
    return {"status": "ok", "n": len(excess_rets), "excess": excess_rets,
            "strategy": strategy_rets, "benchmark": benchmark_rets,
            "train": excess_rets[:mid], "test": excess_rets[mid:]}


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
    return {"mean": round(m, 4), "t": round(t, 3), "p": round(norm_sf_positive(t), 6), "n": n, "ne": round(ne, 1)}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=250)
    args = ap.parse_args()
    universe = select_universe(args.size)
    print(f"universe: top-{args.size} liquidity, {len(universe)} stocks")
    prices, month_dates = load_monthly_prices()
    print(f"prices: {len(prices)} stocks, {len(month_dates)} month-ends")
    for lb in (1, 3):
        print(f"\n{'='*60}\n=== 中频反转 lookback={lb}月 bottom-decile long ===\n{'='*60}")
        r = backtest_reversal(lb, prices, month_dates, universe)
        if r["status"] != "ok":
            print(f"  {r['status']} n={r.get('n',0)}")
            continue
        for label, rets in [("full", r["excess"]), ("train(2018-2022)", r["train"]), ("test(2022-2026)", r["test"])]:
            nw = nw_t(rets)
            wr = sum(1 for x in rets if x > 0) / len(rets) * 100 if rets else 0
            pb = bonferroni_p(nw["p"], N_BONF)
            print(f"  {label}: n={nw['n']} mean={nw['mean']:.4f}%/月 WR={wr:.1f}% t_nw={nw['t']} p={nw['p']} Bonf×{N_BONF}={pb:.4f}")
        if r["benchmark"]:
            print(f"  benchmark等权 mean: {statistics.mean(r['benchmark']):.4f}%/月 | strategy: {statistics.mean(r['strategy']):.4f}%/月")
        te = nw_t(r["test"])
        tm = statistics.mean(r["test"])
        print(f"  VERDICT: test excess={tm:.4f}% t={te['t']} → {'FALSIFIED' if tm<0.1 or te['t']<2.9 else 'exploratory' if bonferroni_p(te['p'],N_BONF)>=0.05 else 'edge-confirmed-provisional'}")


if __name__ == "__main__":
    main()
