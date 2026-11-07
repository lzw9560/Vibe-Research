# -*- coding: utf-8 -*-
"""explore_value_factor-monthly.py

value 因子（E/P, B/P, D/P）月频 long-only backtest。
基本面第三族（quality+growth 已 FALSIFIED，value 未测，学术最强先验 Liu-Stambaugh-Yuan 2019 JFE）。

设计来源：workflow wvl205za9 synthesis（4 agent 设计+outward+数据+A股特殊性）。
关键盲点（design agent 戳出，quality 脚本漏）：
  - 幸存者+排除亏损双重通胀（universe ≥1500bars=survivors + E/P 排除负 epsTTM ~32%）
  - 前复权/不复权 PE-PB 错配（as-reported EPS 配 qfq 价→送转股 PE 虚低，S171 承重 bug）
  - benchmark 须 filtered（同 filter 后 universe，非 raw，消除机械排除效应）
  - value 是 mean 现象非 winrate（PRIMARY 用 mean excess NW t，非 winrate_lift）
  - 行业偏斜（B/P top decile 金融 40-60%=银行 sector bet 非 value）

本脚本 v1：B/P raw（数据就绪：bvps_调整后 in cache + qfq close，同调整口径自洽）。
  B/P = 每股净资产_调整后(PIT) / qfq_close(D)
  - bvps 调整后已对送股转增复权，与 qfq 价一致（不像 E/P 的 as-reported EPS 须不复权价）
  - benchmark = filtered universe（有有效 bvps+close 的股）等权
  - walk-forward 2018-2022 train → 2022-2026 test
  - Bonf×6（3 因子 × 2 版本 raw+sector-neutral，v1 只 B/P raw 占 2 tests）
  - NW t mean excess one-sided Bartlett lag3
  - 滑点敏感性 @0.2/0.4/0.6/0.8%
  - 幸存者 caveat（≥1500bars，v1 标注不纠正，v2 加退市股）
  - kill: test net excess <+0.3%/月 OR t_nw<2.9 OR 衰减>50%（regime caveat）

v2 待加（synthesis）：E/P（需不复权 close backfill）+ D/P（需分红 backfill）+ sector-neutral + 退市股纠正
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
COST = 0.004  # 0.4% round-trip
UNIVERSE_SIZE = 250
N_BONF = 6  # 3 factors × 2 versions (v1 B/P raw 占 2 tests)


def pit_pubdate(stat_date: str) -> str:
    """报告披露截止日（保守 PIT 估计，akshare 无实际 pubDate）。"""
    y, m = int(stat_date[:4]), int(stat_date[5:7])
    if m == 3: return f"{y}-04-30"
    if m == 6: return f"{y}-08-31"
    if m == 9: return f"{y}-10-31"
    if m == 12: return f"{y+1}-04-30"
    return stat_date


def load_fundamentals_pit() -> dict[str, list[dict]]:
    """code -> [(pit, stat, bvps, eps)] 按 stat_date 排序。"""
    if not FUND_DB.exists():
        return {}
    conn = sqlite3.connect(str(FUND_DB))
    rows = conn.execute("""SELECT code, stat_date, bvps, eps
        FROM fundamentals WHERE stat_date >= '2017-01-01' ORDER BY code, stat_date""").fetchall()
    conn.close()
    by_code: dict[str, list[dict]] = defaultdict(list)
    for code, sd, bvps, eps in rows:
        by_code[code].append({"pit": pit_pubdate(sd), "stat": sd, "bvps": bvps, "eps": eps})
    return dict(by_code)


def latest_factor_pit(funds: list[dict], rebalance_date: str, field: str) -> float | None:
    avail = [f for f in funds if f["pit"] <= rebalance_date and f.get(field) is not None]
    if not avail:
        return None
    return avail[-1][field]


def load_monthly_prices() -> tuple[dict[str, dict[str, float]], list[str]]:
    """code -> {month_end_date: qfq close}（kline cache 是 qfq，B/P 用 qfq 配调整后 bvps 自洽）。"""
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
            # 停牌过滤：volume==0 stale close 跳过（design agent CRITICAL：停牌与 Q1 value 重叠）
            vol = b.get("volume", 0)
            try:
                vol = float(vol) if vol else 0
            except (ValueError, TypeError):
                vol = 0
            if vol <= 0:
                continue  # 停牌冻结 close 不用
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


def compute_monthly_returns(prices: dict[str, dict[str, float]],
                            month_dates: list[str]) -> dict[str, dict[str, float]]:
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


def select_universe(size: int = UNIVERSE_SIZE) -> list[str]:
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


def nw_t_monthly(rets: list[float], max_lag: int = 3) -> dict:
    """NW t for monthly returns (Bartlett weights, mean excess one-sided)。value 是 mean 现象非 winrate。"""
    n = len(rets)
    if n < 5:
        return {"mean": 0, "t": 0, "p": 1, "n": n, "n_eff": n}
    m = statistics.mean(rets)
    mc = [x - m for x in rets]
    g0 = sum(x * x for x in mc) / n
    rho_sum = 0.0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)
        gl = sum(mc[i] * mc[i - lag] for i in range(lag, n)) / n
        rho_sum += w * gl / g0 if g0 > 0 else 0
    n_eff = n / (1 + 2 * rho_sum) if (1 + 2 * rho_sum) > 0 else n
    se = (g0 / n_eff) ** 0.5 if g0 > 0 else 0
    t = m / se if se > 0 else 0
    p = norm_sf_positive(t)
    return {"mean": round(m, 4), "t": round(t, 3), "p": round(p, 6), "n": n, "n_eff": round(n_eff, 1)}


def backtest_bp(funds: dict[str, list[dict]], prices: dict[str, dict[str, float]],
                month_rets: dict[str, dict[str, float]], month_dates: list[str]) -> dict:
    """B/P raw: top decile high B/P long-only. benchmark = filtered universe（有效 bvps+close）等权。"""
    rebal_dates = [d for d in month_dates if d >= "2018-04-01"]
    excess_rets: list[float] = []
    strategy_rets: list[float] = []
    benchmark_rets: list[float] = []
    dates_used: list[str] = []
    n_excluded_neg = 0  # B/P 无负值排除（vs E/P 排除负 eps），但报 bvps<=0 排除
    for rd in rebal_dates:
        candidates: list[tuple[str, float]] = []
        bench_codes: list[str] = []
        for code in prices:
            if rd not in month_rets.get(code, {}):
                continue
            close = prices[code].get(rd)
            if not close or close <= 0:
                continue
            bench_codes.append(code)
            fl = funds.get(code)
            if not fl:
                continue
            bvps = latest_factor_pit(fl, rd, "bvps")
            if bvps is not None and bvps > 0:
                bp = bvps / close
                candidates.append((code, bp))
            elif bvps is not None and bvps <= 0:
                n_excluded_neg += 1
        if len(candidates) < 20:
            continue
        candidates.sort(key=lambda x: -x[1])  # high B/P = value
        n_top = max(5, len(candidates) // 10)
        top_codes = [c for c, _ in candidates[:n_top]]
        s_r = statistics.mean(month_rets[c][rd] for c in top_codes)
        b_r = statistics.mean(month_rets[c][rd] for c in bench_codes)  # filtered benchmark
        strat_net = s_r - COST
        excess = strat_net - b_r
        excess_rets.append(excess * 100)
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
        "n_excluded_neg_bvps": n_excluded_neg,
    }


def stats_block(rets: list[float], label: str, n_bonf: int) -> dict:
    if not rets:
        print(f"  {label}: 无数据")
        return {}
    nw = nw_t_monthly(rets)
    wr = sum(1 for x in rets if x > 0) / len(rets) * 100
    p_bonf = bonferroni_p(nw["p"], n_bonf)
    print(f"  {label}: n={nw['n']} mean={nw['mean']:.4f}%/月 WR={wr:.1f}% "
          f"t_nw={nw['t']} p={nw['p']} Bonf×{n_bonf}={p_bonf:.6f} n_eff={nw['n_eff']}")
    return {**nw, "wr": round(wr, 1), "p_bonf": round(p_bonf, 6)}


def slippage_sensitivity_bp(funds, prices, month_rets, month_dates) -> None:
    print(f"\n--- 滑点敏感性（B/P，net @ 多 COST + annual drag）---")
    rebal_dates = [d for d in month_dates if d >= "2018-04-01"]
    for cost_pct in (0.2, 0.4, 0.6, 0.8):
        cost = cost_pct / 100
        excess: list[float] = []
        for rd in rebal_dates:
            cand: list[tuple[str, float]] = []
            bench: list[str] = []
            for code in prices:
                if rd not in month_rets.get(code, {}):
                    continue
                close = prices[code].get(rd)
                if not close or close <= 0:
                    continue
                bench.append(code)
                fl = funds.get(code)
                if not fl:
                    continue
                bvps = latest_factor_pit(fl, rd, "bvps")
                if bvps is not None and bvps > 0:
                    cand.append((code, bvps / close))
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
    ap.add_argument("--size", type=int, default=UNIVERSE_SIZE)
    args = ap.parse_args()

    universe = select_universe(args.size)
    print(f"universe: top-{args.size} liquidity, {len(universe)} stocks (≥6yr history, survivorship caveat)")

    print("\n=== load data ===")
    funds = load_fundamentals_pit()
    print(f"fundamentals: {len(funds)} stocks cached (bvps+eps)")
    prices, month_dates = load_monthly_prices()
    print(f"prices(qfq): {len(prices)} stocks, {len(month_dates)} month-ends")
    month_rets = compute_monthly_returns(prices, month_dates)

    print(f"\n{'='*70}\n=== B/P 月频 long-only top-decile（2018-2026, PIT 对齐, filtered benchmark）===\n{'='*70}")
    r = backtest_bp(funds, prices, month_rets, month_dates)
    if r["status"] != "ok":
        print(f"  {r['status']} (n={r.get('n', 0)})")
        return
    print(f"  bvps<=0 排除: {r.get('n_excluded_neg_bvps',0)}（B/P 无负值，仅排除 bvps<=0 异常）")
    full = stats_block(r["excess"], "full", N_BONF)
    train = stats_block(r["train"], "train(2018-2022)", N_BONF)
    test = stats_block(r["test"], "test(2022-2026)", N_BONF)
    if train and test and train.get("mean", 0) != 0:
        decay = (train["mean"] - test["mean"]) / abs(train["mean"]) * 100
        print(f"  衰减: {decay:.0f}% (train→test) — regime caveat: value cycle-timing, 2018-2026 growth-favorable")
    if r["benchmark"]:
        print(f"  benchmark(filtered universe等权) mean: {statistics.mean(r['benchmark']):.4f}%/月")
        print(f"  strategy mean: {statistics.mean(r['strategy']):.4f}%/月 (net @ 0.4% cost)")

    slippage_sensitivity_bp(funds, prices, month_rets, month_dates)

    # verdict
    print(f"\n{'='*70}\n=== VERDICT（B/P raw, Bonf×{N_BONF}, walk-forward, kill criteria）===\n{'='*70}")
    test = r["test"]
    if test:
        nw = nw_t_monthly(test)
        train_mean = statistics.mean(r["train"]) if r["train"] else 0
        test_mean = statistics.mean(test)
        decay = (train_mean - test_mean) / abs(train_mean) * 100 if train_mean != 0 else 0
        p_bonf = bonferroni_p(nw["p"], N_BONF)
        print(f"  test: net_excess={test_mean:.4f}%/月 t_nw={nw['t']} p={nw['p']} Bonf×{N_BONF}={p_bonf:.4f}")
        print(f"  train={train_mean:.4f}% test={test_mean:.4f}% 衰减={decay:.0f}%")
        if test_mean < 0.1:
            print(f"  → FALSIFIED: test net_excess {test_mean:.4f}% < +0.1%/月")
        elif test_mean < 0.3:
            if nw["t"] >= 2.9 and p_bonf < 0.05:
                print(f"  → EXPLORATORY thin-edge: test +0.1~0.3% t_nw>2.9 Bonf PASS（须 OOS+独立复现）")
            else:
                print(f"  → FALSIFIED: test +0.1~0.3% BUT t_nw={nw['t']}<2.9 或 Bonf={p_bonf:.4f}>=0.05")
        elif nw["t"] < 2.9:
            print(f"  → KILL: test net_excess {test_mean:.4f}%>=0.3 BUT t_nw {nw['t']}<2.9")
        elif decay > 50:
            print(f"  → regime caveat: 衰减 {decay:.0f}%>50 BUT value cycle-timing（2018-2026 growth-favorable），降级 regime-dependent period-specific 非硬 kill")
        elif p_bonf < 0.05:
            print(f"  → ✅ edge-confirmed-provisional: test net>0.3% t_nw>2.9 衰减<50% Bonf PASS（须幸存者审查：value 通过 0.3%/月门槛 likely bias-inflated）")
        else:
            print(f"  → exploratory: Bonf {p_bonf:.4f}>=0.05")
    # 存 result
    out = {"bp_raw": {k: v for k, v in r.items() if k in ("status", "n_months", "n_excluded_neg_bvps")},
           "_meta": {"universe_size": args.size, "n_bonf": N_BONF, "cost": COST,
                     "survivorship_caveat": "≥6yr history survivors, v1 不纠正（v2 加退市股）",
                     "data_note": "B/P=bvps_调整后/qfq_close（同调整口径自洽，无需不复权）"}}
    p = Path(__file__).parent / "_value_factor_bp_result.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nresult JSON -> {p}")


if __name__ == "__main__":
    main()
