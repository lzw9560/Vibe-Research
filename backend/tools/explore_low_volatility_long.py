# -*- coding: utf-8 -*-
"""explore_low_volatility_long.py

低波动率因子 long-only 月频 backtest（散户可交易版）。
经典 low-volatility anomaly（Fama-French / Baker-Haugen）：低波股风险调整后跑赢。

**重要**：workflow methodology agent claim "低波 t=3.211 exploratory" 但其引用的
_low_volatility_result.json + 脚本从未存在于代码库 = hallucination。本脚本用 REAL 数据 clean test。
低波因子本身经典先验强 + long-only 散户可交易 + 项目真未测过，值得测。

设计：
- Universe: top-250 liquidity
- 因子: vol_20d（过去20交易日日收益标准差），月频 rebalance
- bottom decile（最低波）long-only equal-weight
- benchmark = universe equal-weight
- walk-forward 2018-2022/2022-2026 + Bonf×2 + NW t
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
N_BONF = 2


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


def load_kline_daily(universe: list[str]) -> dict[str, list[tuple[str, float]]]:
    """code -> [(date, close), ...] sorted，只 universe 股。"""
    conn = sqlite3.connect(str(KLINE_DB))
    out: dict[str, list[tuple[str, float]]] = {}
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        if code not in universe:
            continue
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list):
            continue
        pairs = []
        for b in bars:
            d = b.get("date", "")
            c = b.get("close")
            try:
                c = float(c) if c else None
            except (ValueError, TypeError):
                c = None
            vol = b.get("volume", 0)
            try:
                vol = float(vol) if vol else 0
            except (ValueError, TypeError):
                vol = 0
            if d and c and c > 0 and vol > 0:
                pairs.append((d, c))
        if pairs:
            out[code] = sorted(pairs, key=lambda x: x[0])
    conn.close()
    return out


def compute_vol_and_returns(daily: dict[str, list[tuple[str, float]]]) -> tuple[dict, dict, list[str]]:
    """返 (code -> {month_end_date: vol_20d}, code -> {month_end_date: next_month_return}, all_month_ends).
    vol_20d at month-end D = std of past 20 trading days' daily returns ending at D.
    next_month_return = close[D+1month]/close[D] - 1."""
    # 先建 code -> {date: close} + 按 code 算 daily returns
    code_daily: dict[str, dict[str, float]] = {}
    for code, pairs in daily.items():
        code_daily[code] = {d: c for d, c in pairs}
    # 全局 month-ends（各股月末最后交易日）
    code_month_end: dict[str, list[str]] = {}
    all_months: dict[str, list[str]] = defaultdict(list)  # YYYY-MM -> [dates]
    for code, pairs in daily.items():
        by_month: dict[str, str] = {}
        for d, c in pairs:
            m = d[:7]
            if m not in by_month or d > by_month[m]:
                by_month[m] = d
        code_month_end[code] = [by_month[m] for m in sorted(by_month)]
        for m, d in by_month.items():
            all_months[m].append(d)
    # 全局月份排序
    sorted_months = sorted(all_months.keys())
    # 对每股，算每月末 vol_20d + next month return
    vol_by_code: dict[str, dict[str, float]] = {}
    ret_by_code: dict[str, dict[str, float]] = {}
    for code, pairs in daily.items():
        dmap = code_daily[code]
        sorted_dates = [d for d, _ in pairs]
        date_idx = {d: i for i, d in enumerate(sorted_dates)}
        v: dict[str, float] = {}
        r: dict[str, float] = {}
        me_list = code_month_end[code]
        for mi, me in enumerate(me_list):
            di = date_idx[me]
            if di < 20:
                continue
            # past 20 daily returns ending at me (inclusive)
            window_closes = [sorted_dates[j] for j in range(di - 19, di + 1)]
            window_rets = []
            for j in range(1, len(window_closes)):
                pc = dmap[window_closes[j - 1]]
                cc = dmap[window_closes[j]]
                if pc > 0:
                    window_rets.append((cc - pc) / pc)
            if len(window_rets) >= 15:
                v[me] = statistics.pstdev(window_rets)
            # next month return
            if mi + 1 < len(me_list):
                next_me = me_list[mi + 1]
                pc = dmap[me]
                cc = dmap[next_me]
                if pc > 0:
                    r[me] = (cc - pc) / pc
        vol_by_code[code] = v
        ret_by_code[code] = r
    # all month-ends (union, sorted) — 用各股 me 的并集
    all_me: set[str] = set()
    for v in vol_by_code.values():
        all_me.update(v.keys())
    return vol_by_code, ret_by_code, sorted(all_me)


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
    daily = load_kline_daily(universe)
    print(f"daily bars loaded: {len(daily)} stocks")
    vol_by_code, ret_by_code, all_me = compute_vol_and_returns(daily)
    print(f"vol + returns computed, {len(all_me)} month-ends")

    rebal = [d for d in all_me if d >= "2018-06-01"]
    excess_rets, strat_rets, bench_rets, dates_used = [], [], [], []
    for rd in rebal:
        cand: list[tuple[str, float]] = []  # (code, vol)
        bench: list[str] = []
        for code in universe:
            vol = vol_by_code.get(code, {}).get(rd)
            ret = ret_by_code.get(code, {}).get(rd)
            if vol is None or ret is None:
                continue
            cand.append((code, vol, ret))
            bench.append(code)
        if len(cand) < 20:
            continue
        # bottom decile = LOWEST vol（低波 long）
        cand.sort(key=lambda x: x[1])  # ascending vol, lowest first
        n_bot = max(5, len(cand) // 10)
        bot = cand[:n_bot]
        s_r = statistics.mean(c[2] for c in bot)
        b_r = statistics.mean(c[2] for c in cand)  # filtered benchmark
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
    print(f"\n{'='*60}\n=== 低波 long-only bottom-decile（vol_20d, 月频）===\n{'='*60}")
    for label, rets in [("full", excess_rets), ("train(2018-2022)", train), ("test(2022-2026)", test)]:
        nw = nw_t(rets)
        wr = sum(1 for x in rets if x > 0) / len(rets) * 100 if rets else 0
        pb = bonferroni_p(nw["p"], N_BONF)
        print(f"  {label}: n={nw['n']} mean={nw['mean']:.4f}%/月 WR={wr:.1f}% t_nw={nw['t']} p={nw['p']} Bonf×{N_BONF}={pb:.4f}")
    print(f"  benchmark等权 mean: {statistics.mean(bench_rets):.4f}%/月 | strategy: {statistics.mean(strat_rets):.4f}%/月")
    te = nw_t(test)
    tm = statistics.mean(test)
    pb = bonferroni_p(te["p"], N_BONF)
    print(f"\n--- VERDICT ---")
    print(f"  test excess={tm:.4f}% t={te['t']} Bonf={pb:.4f}")
    if tm < 0.1 or te["t"] < 2.9:
        print(f"  → {'FALSIFIED' if tm<0.1 else 'KILL(t<2.9)'}")
    elif pb >= 0.05:
        print(f"  → exploratory（Bonf {pb:.4f}>=0.05）")
    else:
        print(f"  → ✅ edge-confirmed-provisional（须幸存者+realizable 审查）")
    out = {"n": len(excess_rets), "test_excess": round(tm,3), "test_t": te["t"], "bonf": pb}
    Path(__file__).parent / "_low_vol_long_result.json"
    p = Path(__file__).parent / "_low_vol_long_result.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"result -> {p}")


if __name__ == "__main__":
    main()
