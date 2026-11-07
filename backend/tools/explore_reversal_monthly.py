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


def load_monthly_returns_by_month(universe: list[str]) -> tuple[dict[str, dict[str, float]], list[str]]:
    """code -> {YYYY-MM: monthly return}, 对齐所有股用月份 key（各股月末交易日不同，精确日期不匹配）。
    返回 (code_monthly_ret, sorted_months)。"""
    conn = sqlite3.connect(str(KLINE_DB))
    code_month_close: dict[str, dict[str, float]] = defaultdict(dict)
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        if code not in universe:
            continue
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
            code_month_close[code][month] = c
    conn.close()
    # 算月收益 code -> {month: return}
    code_monthly_ret: dict[str, dict[str, float]] = {}
    all_months: set[str] = set()
    for code, mc in code_month_close.items():
        sorted_m = sorted(mc.keys())
        r: dict[str, float] = {}
        for i in range(1, len(sorted_m)):
            prev_c = mc[sorted_m[i - 1]]
            cur_c = mc[sorted_m[i]]
            if prev_c > 0:
                r[sorted_m[i]] = (cur_c - prev_c) / prev_c
                all_months.add(sorted_m[i])
        code_monthly_ret[code] = r
    return code_monthly_ret, sorted(all_months)


def backtest_reversal(lookback: int, code_monthly_ret: dict, all_months: list, universe: list[str]) -> dict:
    """bottom decile by past N-month return（超卖反弹）, hold 1 month. 月份对齐."""
    rebal_months = [m for m in all_months if m >= "2018-06"]
    excess_rets: list[float] = []
    strategy_rets: list[float] = []
    benchmark_rets: list[float] = []
    dates_used: list[str] = []
    for rm in rebal_months:
        mi = all_months.index(rm) if rm in all_months else -1
        if mi < lookback:
            continue
        past_months = all_months[mi - lookback : mi]
        next_month = all_months[mi + 1] if mi + 1 < len(all_months) else None
        if next_month is None:
            continue
        candidates: list[tuple[str, float]] = []
        bench: list[str] = []
        for code in universe:
            # holding return = next_month return
            next_r = code_monthly_ret.get(code, {}).get(next_month)
            if next_r is None:
                continue
            bench.append(code)
            # past N-month cumulative
            cum = 1.0
            ok = True
            for pm in past_months:
                r = code_monthly_ret.get(code, {}).get(pm)
                if r is None:
                    ok = False
                    break
                cum *= 1 + r
            if not ok:
                continue
            candidates.append((code, cum - 1, next_r))
        if len(candidates) < 20:
            continue
        candidates.sort(key=lambda x: x[1])  # ascending by past return, worst first
        n_bot = max(5, len(candidates) // 10)
        bot = candidates[:n_bot]
        s_r = statistics.mean(c[2] for c in bot)
        b_r = statistics.mean(c[2] for c in candidates)  # filtered benchmark（有完整数据股）
        strat_net = s_r - COST
        excess = strat_net - b_r
        excess_rets.append(excess * 100)
        strategy_rets.append(strat_net * 100)
        benchmark_rets.append(b_r * 100)
        dates_used.append(rm)
    if len(excess_rets) < 24:
        return {"status": "too_few", "n": len(excess_rets)}
    mid = len(dates_used) // 2
    return {
        "status": "ok",
        "n": len(excess_rets),
        "excess": excess_rets,
        "strategy": strategy_rets,
        "benchmark": benchmark_rets,
        "train": excess_rets[:mid],
        "test": excess_rets[mid:],
    }


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
    code_monthly_ret, all_months = load_monthly_returns_by_month(universe)
    print(
        f"monthly returns: {len(code_monthly_ret)} stocks, {len(all_months)} months ({all_months[0]}~{all_months[-1]})"
    )
    for lb in (1, 3):
        print(f"\n{'=' * 60}\n=== 中频反转 lookback={lb}月 bottom-decile long ===\n{'=' * 60}")
        r = backtest_reversal(lb, code_monthly_ret, all_months, universe)
        if r["status"] != "ok":
            print(f"  {r['status']} n={r.get('n', 0)}")
            continue
        for label, rets in [("full", r["excess"]), ("train(2018-2022)", r["train"]), ("test(2022-2026)", r["test"])]:
            nw = nw_t(rets)
            wr = sum(1 for x in rets if x > 0) / len(rets) * 100 if rets else 0
            pb = bonferroni_p(nw["p"], N_BONF)
            print(
                f"  {label}: n={nw['n']} mean={nw['mean']:.4f}%/月 WR={wr:.1f}% t_nw={nw['t']} p={nw['p']} Bonf×{N_BONF}={pb:.4f}"
            )
        if r["benchmark"]:
            print(
                f"  benchmark等权 mean: {statistics.mean(r['benchmark']):.4f}%/月 | strategy: {statistics.mean(r['strategy']):.4f}%/月"
            )
        te = nw_t(r["test"])
        tm = statistics.mean(r["test"])
        print(
            f"  VERDICT: test excess={tm:.4f}% t={te['t']} → {'FALSIFIED' if tm < 0.1 or te['t'] < 2.9 else 'exploratory' if bonferroni_p(te['p'], N_BONF) >= 0.05 else 'edge-confirmed-provisional'}"
        )


if __name__ == "__main__":
    main()
