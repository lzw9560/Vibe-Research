# -*- coding: utf-8 -*-
"""explore_bp_sector_neutral.py

B/P sector-neutral 月频 long-only（剥离金融 beta confound）。
value 脚本自认：B/P top decile 40-60% 银行 = sector bet 非 value。本脚本 clean test：
行业内 rank B/P，每行业取 top-k，聚合 → sector-neutral value。

synthesis P1 closure（B/P raw t=-2.3 显著负，sector-neutral 大概率也负但闭合 documented gap）。
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
SECTOR_DB = DATA / "sector_map.db"
COST = 0.004
N_BONF = 2


def pit_pubdate(stat_date: str) -> str:
    y, m = int(stat_date[:4]), int(stat_date[5:7])
    if m == 3: return f"{y}-04-30"
    if m == 6: return f"{y}-08-31"
    if m == 9: return f"{y}-10-31"
    if m == 12: return f"{y+1}-04-30"
    return stat_date


def load_funds() -> dict[str, list[dict]]:
    conn = sqlite3.connect(str(FUND_DB))
    rows = conn.execute("""SELECT code, stat_date, bvps FROM fundamentals
        WHERE stat_date >= '2017-01-01' ORDER BY code, stat_date""").fetchall()
    conn.close()
    by_code: dict[str, list[dict]] = defaultdict(list)
    for code, sd, bvps in rows:
        by_code[code].append({"pit": pit_pubdate(sd), "bvps": bvps})
    return dict(by_code)


def latest_bvps(funds: list[dict], rd: str) -> float | None:
    avail = [f for f in funds if f["pit"] <= rd and f["bvps"] is not None and f["bvps"] > 0]
    return avail[-1]["bvps"] if avail else None


def load_sector_map() -> dict[str, str]:
    if not SECTOR_DB.exists():
        return {}
    conn = sqlite3.connect(str(SECTOR_DB))
    m = dict(conn.execute("SELECT code, sector FROM sector_map WHERE sector NOT IN ('Error','Unknown')").fetchall())
    conn.close()
    return m


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


def backtest_bp_sector_neutral(funds, prices, month_dates, sector_map, universe) -> dict:
    """行业内 rank B/P，每行业取 top 20%，聚合 sector-neutral portfolio。"""
    rebal = [d for d in month_dates if d >= "2018-04-01"]
    excess_rets, strat_rets, bench_rets, dates_used = [], [], [], []
    for rd in rebal:
        # 按行业分组
        by_sector: dict[str, list[tuple[str, float]]] = defaultdict(list)
        bench: list[str] = []
        for code in universe:
            if rd not in prices.get(code, {}):
                continue
            close = prices[code].get(rd)
            if not close or close <= 0:
                continue
            fl = funds.get(code)
            if not fl:
                continue
            bvps = latest_bvps(fl, rd)
            if bvps is None:
                continue
            sec = sector_map.get(code)
            if not sec:
                continue
            by_sector[sec].append((code, bvps / close))
            bench.append(code)
        if len(bench) < 20:
            continue
        # 每行业 top 20%（高 B/P），行业 ≥3 才取
        picks: list[str] = []
        for sec, cand in by_sector.items():
            if len(cand) < 3:
                continue
            cand.sort(key=lambda x: -x[1])  # high B/P first
            n_top = max(1, len(cand) // 5)  # top 20% within sector
            picks.extend(c for c, _ in cand[:n_top])
        if len(picks) < 10:
            continue
        s_r = statistics.mean(prices[c][rd] and ((prices[c][rd] - 0) / prices[c][rd]) or 0 for c in picks)  # placeholder
        # 正确：用 next month return
        # 先算 returns（code -> {date: ret}）
    return {"status": "need_returns"}


def main() -> None:
    universe = select_universe(250)
    print(f"universe: {len(universe)} stocks")
    sector_map = load_sector_map()
    print(f"sector_map: {len(sector_map)} stocks mapped")
    if len(sector_map) < 100:
        print("⚠️ sector_map 不足 100，先 fetch sector")
        return
    funds = load_funds()
    print(f"fundamentals: {len(funds)} stocks")
    prices, month_dates = load_monthly_prices()
    print(f"prices: {len(prices)} stocks, {len(month_dates)} month-ends")
    # 算月收益
    code_ret: dict = {}
    for code, md in prices.items():
        sd = sorted(md.keys())
        r = {}
        for i in range(1, len(sd)):
            if md[sd[i-1]] > 0:
                r[sd[i]] = (md[sd[i]] - md[sd[i-1]]) / md[sd[i-1]]
        code_ret[code] = r

    rebal = [d for d in month_dates if d >= "2018-04-01"]
    excess_rets, strat_rets, bench_rets, dates_used = [], [], [], []
    for rd in rebal:
        by_sector: dict[str, list[tuple[str, float]]] = defaultdict(list)
        bench: list[str] = []
        for code in universe:
            if rd not in code_ret.get(code, {}):
                continue
            close = prices[code].get(rd)
            if not close or close <= 0:
                continue
            fl = funds.get(code)
            if not fl:
                continue
            bvps = latest_bvps(fl, rd)
            if bvps is None:
                continue
            sec = sector_map.get(code)
            if not sec:
                continue
            by_sector[sec].append((code, bvps / close))
            bench.append(code)
        if len(bench) < 20:
            continue
        picks: list[str] = []
        for sec, cand in by_sector.items():
            if len(cand) < 3:
                continue
            cand.sort(key=lambda x: -x[1])
            n_top = max(1, len(cand) // 5)
            picks.extend(c for c, _ in cand[:n_top])
        if len(picks) < 10:
            continue
        s_r = statistics.mean(code_ret[c][rd] for c in picks)
        b_r = statistics.mean(code_ret[c][rd] for c in bench)
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
    print(f"\n{'='*60}\n=== B/P sector-neutral（行业内 top 20%）===\n{'='*60}")
    for label, rets in [("full", excess_rets), ("train(2018-2022)", train), ("test(2022-2026)", test)]:
        nw = nw_t(rets)
        wr = sum(1 for x in rets if x > 0) / len(rets) * 100 if rets else 0
        pb = bonferroni_p(nw["p"], N_BONF)
        print(f"  {label}: n={nw['n']} mean={nw['mean']:.4f}%/月 WR={wr:.1f}% t_nw={nw['t']} p={nw['p']} Bonf×{N_BONF}={pb:.4f}")
    print(f"  benchmark等权 mean: {statistics.mean(bench_rets):.4f}%/月 | strategy: {statistics.mean(strat_rets):.4f}%/月")
    te = nw_t(test)
    tm = statistics.mean(test)
    pb = bonferroni_p(te["p"], N_BONF)
    print(f"\n--- VERDICT (B/P sector-neutral vs raw B/P t=-2.3) ---")
    print(f"  test excess={tm:.4f}% t={te['t']} Bonf={pb:.4f}")
    if tm < 0.1 or te["t"] < 2.9:
        print(f"  → FALSIFIED（sector-neutral 未救活 B/P）")
    elif pb >= 0.05:
        print(f"  → exploratory")
    else:
        print(f"  → ✅ edge-confirmed-provisional（sector-neutral 暴露残留 edge）")


if __name__ == "__main__":
    main()
