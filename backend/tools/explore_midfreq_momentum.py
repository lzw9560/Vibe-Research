# -*- coding: utf-8 -*-
"""explore_midfreq_momentum.py

中频动量因子（1-3 月 horizon, positive momentum）月频 long-only backtest。

背景：
  - 短反转已证伪（memory: explore_reversal_monthly.py 1月反转 t0.54 / 3月反转 t-2.43）。
  - 3月反转 t=-2.43 显著负 = losers 继续亏 = 动量的"另一面"。
    但这是 LOSERS 长端的证据，WINNERS 侧（买过去涨的）未独立测。
  - A 股动量 sign-flip（学术：短期反转 / 中长期动量），1-3 月是边界区间。
    outward 印证 momentum 时变 regime dependent。
  - 本脚本 = reversal 脚本的镜像：top decile（winner）long-only，skip-1（JT 标准，
    避短期反转干扰），3 个 lookback 窗口（1/2/3 月）。

设计（与 reversal 脚本同口径，便于镜像比较）：
  - Universe: top-250 liquidity（≥6yr history, survivorship caveat）+ broad 敏感性（全 ≥1500bars）
  - 因子: 过去 N 月 cumulative return（N=1,2,3）, top decile（动量最高 10% = winner）
  - Skip-1: formation = months [mi-lookback, mi-1], skip month mi, hold month mi+1
            （与 reversal 完全一致——month mi 是 buffer，避 1 月反转污染）
  - 持有 1 月, 月频调仓
  - benchmark = filtered universe（有完整 formation+holding 数据的股）等权
    （自动排除停牌 vol=0 + 缺数据股；ST/涨停 monthly 频率影响小，caveat 标注）
  - walk-forward: 前半 train / 后半 test（~2018-2022 / ~2022-2026）
  - NW-HAC t (Bartlett lag3), Bonferroni×3（3 lookback 窗口）
  - 滑点敏感性 @0.2/0.4/0.6/0.8%
  - 成本 0.4% round-trip

诚实盲点：
  - 幸存者偏差（≥1500bars = survivors, 退市的没算）INFLATES——v1 标注不纠正
  - regime dependent（outward 印证 momentum 时变）
  - A 股动量 sign-flip（1-3 月是边界，可能正可能负）
  - qfq 前复权 return = total return（含分红送转），与 reversal 同口径

kill criteria（per task）:
  - 全 3 窗口 full t<2 → FALSIFIED
  - walk-forward test FAIL（test excess<0 OR test t<2）→ 该窗口 FALSIFIED
  - 某窗口 t>2 但 walk-forward 不稳健（decay>50% 或 test t<2）→ EXPLORATORY 非 confirmed
  - 某窗口 test t≥2 AND Bonf×3 p<0.05 AND decay<50% → edge-confirmed-provisional
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
COST = 0.004  # 0.4% round-trip
N_BONF = 3  # 3 lookback 窗口
REBAL_START = "2018-06"  # 与 reversal 同口径（镜像可比）
T_KILL = 2.0  # task kill threshold（另报 §44 严格 t≥2.9 对比）


# ── universe + monthly returns（与 reversal 同口径，镜像可比）──────────────────


def select_universe(size: int = 250) -> list[str]:
    """top-N liquidity（avg amount），≥1500 bars（survivorship caveat）。"""
    conn = sqlite3.connect(str(KLINE_DB))
    rows: list[tuple[str, float]] = []
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


def select_broad_universe(min_bars: int = 1500) -> list[str]:
    """全 ≥min_bars bars 的股（~3650，含中/小盘，momentum 常在中小盘更强）。"""
    conn = sqlite3.connect(str(KLINE_DB))
    codes: list[str] = []
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(bars, list) and len(bars) >= min_bars:
            codes.append(code)
    conn.close()
    return codes


def load_monthly_returns_by_month(universe: list[str]) -> tuple[dict[str, dict[str, float]], list[str]]:
    """code -> {YYYY-MM: monthly return}, vol>0 过滤停牌（stale close 不用）。
    取每月最后一个交易日 close。返回 (code_monthly_ret, sorted_months)。"""
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
                continue  # 停牌冻结 close 不用
            prev = by_month.get(month)
            if prev is None or d > prev[0]:
                by_month[month] = (d, c)
        for month, (_d, c) in by_month.items():
            code_month_close[code][month] = c
    conn.close()
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


# ── backtest（top decile winner, skip-1 JT）─────────────────────────────────────


def backtest_momentum(
    lookback: int,
    code_monthly_ret: dict[str, dict[str, float]],
    all_months: list[str],
    universe: list[str],
    skip: bool = True,
    cost: float = COST,
) -> dict:
    """top decile by past N-month cumulative return（winner）, skip-1, hold 1 month.

    skip=True（默认，JT 标准）: formation=[mi-lookback, mi-1], skip month mi, hold mi+1.
    skip=False（对照）: formation=[mi-lookback+1, mi], hold mi+1（无 buffer，受 1 月反转污染）.
    benchmark = filtered universe（完整 formation+holding 数据）等权.
    """
    month_idx = {m: i for i, m in enumerate(all_months)}
    rebal_months = [m for m in all_months if m >= REBAL_START]
    excess_rets: list[float] = []
    strategy_rets: list[float] = []
    benchmark_rets: list[float] = []
    dates_used: list[str] = []
    n_picks_per_month: list[int] = []
    for rm in rebal_months:
        mi = month_idx.get(rm, -1)
        if mi < 0:
            continue
        if skip:
            # formation = months [mi-lookback, mi-1]; holding = mi+1 (skip month mi)
            if mi < lookback:
                continue
            past_months = all_months[mi - lookback : mi]
            hold_month = all_months[mi + 1] if mi + 1 < len(all_months) else None
        else:
            # no-skip: formation = months [mi-lookback+1, mi]; holding = mi+1
            if mi < lookback - 1:
                continue
            past_months = all_months[mi - lookback + 1 : mi + 1]
            hold_month = all_months[mi + 1] if mi + 1 < len(all_months) else None
        if hold_month is None:
            continue
        candidates: list[tuple[str, float, float]] = []  # (code, formation_ret, hold_ret)
        for code in universe:
            hold_r = code_monthly_ret.get(code, {}).get(hold_month)
            if hold_r is None:
                continue
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
            candidates.append((code, cum - 1.0, hold_r))
        if len(candidates) < 20:
            continue
        # top decile = highest past return (winner) —— DESCENDING sort
        candidates.sort(key=lambda x: -x[1])
        n_top = max(5, len(candidates) // 10)
        top = candidates[:n_top]
        s_r = statistics.mean(c[2] for c in top)
        b_r = statistics.mean(c[2] for c in candidates)  # filtered benchmark
        strat_net = s_r - cost
        excess = strat_net - b_r
        excess_rets.append(excess * 100)
        strategy_rets.append(strat_net * 100)
        benchmark_rets.append(b_r * 100)
        dates_used.append(rm)
        n_picks_per_month.append(n_top)
    if len(excess_rets) < 24:
        return {"status": "too_few", "n": len(excess_rets)}
    mid = len(dates_used) // 2
    return {
        "status": "ok",
        "n": len(excess_rets),
        "dates": dates_used,
        "excess": excess_rets,
        "strategy": strategy_rets,
        "benchmark": benchmark_rets,
        "train": excess_rets[:mid],
        "test": excess_rets[mid:],
        "train_dates": dates_used[:mid],
        "test_dates": dates_used[mid:],
        "avg_picks": round(statistics.mean(n_picks_per_month), 1),
    }


# ── stats ──────────────────────────────────────────────────────────────────────


def nw_t(rets: list[float], lag: int = 3) -> dict:
    """NW-HAC t (Bartlett weights), one-sided positive-edge p."""
    n = len(rets)
    if n < 5:
        return {"mean": 0, "t": 0, "p": 1, "n": n, "n_eff": n}
    m = statistics.mean(rets)
    mc = [x - m for x in rets]
    g0 = sum(x * x for x in mc) / n
    rho_sum = 0.0
    for l in range(1, lag + 1):
        w = 1 - l / (lag + 1)
        gl = sum(mc[i] * mc[i - l] for i in range(l, n)) / n
        rho_sum += w * gl / g0 if g0 > 0 else 0
    n_eff = n / (1 + 2 * rho_sum) if (1 + 2 * rho_sum) > 0 else n
    se = (g0 / n_eff) ** 0.5 if g0 > 0 else 0
    t = m / se if se > 0 else 0
    return {"mean": round(m, 4), "t": round(t, 3), "p": round(norm_sf_positive(t), 6), "n": n, "n_eff": round(n_eff, 1)}


def stats_block(rets: list[float], label: str) -> dict:
    if not rets:
        print(f"  {label}: 无数据")
        return {}
    nw = nw_t(rets)
    wr = sum(1 for x in rets if x > 0) / len(rets) * 100
    pb = bonferroni_p(nw["p"], N_BONF)
    print(
        f"  {label}: n={nw['n']} mean={nw['mean']:.4f}%/月 WR={wr:.1f}% "
        f"t_nw={nw['t']} p={nw['p']} Bonf×{N_BONF}={pb:.4f} n_eff={nw['n_eff']}"
    )
    return {**nw, "wr": round(wr, 1), "p_bonf": round(pb, 4)}


def _verdict(r: dict, label: str) -> str:
    """per-task kill criteria. 返回 verdict 字符串。"""
    print(f"\n--- VERDICT {label}（Bonf×{N_BONF}, walk-forward, kill t<{T_KILL}）---")
    full = nw_t(r["excess"])
    train = nw_t(r["train"])
    test = nw_t(r["test"])
    train_mean = statistics.mean(r["train"]) if r["train"] else 0
    test_mean = statistics.mean(r["test"])
    decay = (train_mean - test_mean) / abs(train_mean) * 100 if train_mean != 0 else 0
    pb_full = bonferroni_p(full["p"], N_BONF)
    pb_test = bonferroni_p(test["p"], N_BONF)
    print(
        f"  full:  excess={full['mean']:.4f}%/月 t_nw={full['t']} p={full['p']} Bonf×{N_BONF}={pb_full:.4f}"
    )
    print(
        f"  train: excess={train['mean']:.4f}%/月 t_nw={train['t']} (n={train['n']})  "
        f"| test: excess={test['mean']:.4f}%/月 t_nw={test['t']} p={test['p']} Bonf={pb_test:.4f} (n={test['n']})"
    )
    print(f"  衰减={decay:.0f}% (train→test)")
    print(f"  §44 严格参考: t≥2.9 {'PASS' if test['t'] >= 2.9 else 'FAIL'} | Harvey t≥3.0 {'PASS' if test['t'] >= 3.0 else 'FAIL'}")
    # per-task kill logic
    verdict = "FALSIFIED"
    if test_mean < 0:
        verdict = "FALSIFIED"
        print(f"  → FALSIFIED: test excess {test_mean:.4f}% < 0（OOS 负）")
    elif test["t"] < T_KILL:
        verdict = "FALSIFIED"
        print(f"  → FALSIFIED: test t_nw={test['t']}<{T_KILL}")
    elif decay > 50:
        verdict = "EXPLORATORY"
        print(f"  → EXPLORATORY: test t≥{T_KILL} BUT 衰减 {decay:.0f}%>50%（regime-dependent，非 robust）")
    elif pb_test >= 0.05:
        verdict = "EXPLORATORY"
        print(f"  → EXPLORATORY: test t≥{T_KILL} BUT Bonf×{N_BONF}={pb_test:.4f}≥0.05（多重检验不显著）")
    else:
        verdict = "edge-confirmed-provisional"
        print(f"  → edge-confirmed-provisional: test t={test['t']}≥{T_KILL} Bonf={pb_test:.4f}<0.05 decay={decay:.0f}%<50%")
        print(f"    （须幸存者审查 + 独立复现；§44 t≥2.9 {'未达' if test['t'] < 2.9 else '达标'}）")
    return verdict


def slippage_sensitivity(lookback: int, code_monthly_ret, all_months, universe) -> None:
    print(f"\n--- 滑点敏感性（lookback={lookback}月, net @ 多 COST）---")
    for cost_pct in (0.2, 0.4, 0.6, 0.8):
        cost = cost_pct / 100
        r = backtest_momentum(lookback, code_monthly_ret, all_months, universe, skip=True, cost=cost)
        if r["status"] != "ok":
            continue
        nw = nw_t(r["excess"])
        te = nw_t(r["test"])
        print(f"  COST={cost_pct:.1f}%: full_excess={nw['mean']:.4f}%/月 t={nw['t']} | test_excess={te['mean']:.4f}%/月 t={te['t']} (n={nw['n']})")


# ── main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=250, help="primary universe size (top-N liquidity)")
    ap.add_argument("--broad", action="store_true", help="也跑 broad universe（全 ≥1500bars）敏感性")
    args = ap.parse_args()

    universe = select_universe(args.size)
    print(f"PRIMARY universe: top-{args.size} liquidity, {len(universe)} stocks (≥6yr history, survivorship caveat)")
    code_monthly_ret, all_months = load_monthly_returns_by_month(universe)
    print(
        f"monthly returns: {len(code_monthly_ret)} stocks, {len(all_months)} months "
        f"({all_months[0]}~{all_months[-1]})"
    )
    print(f"cost={COST*100:.1f}% round-trip | skip-1 (JT) | Bonf×{N_BONF} | kill t<{T_KILL}")
    print(f"survivorship caveat: ≥1500bars=survivors, 退市股未算 → INFLATES（v1 标注不纠正）")

    verdicts: dict[str, str] = {}
    for lb in (1, 2, 3):
        print(f"\n{'=' * 72}\n=== 中频动量 lookback={lb}月 top-decile winner long (skip-1, filtered benchmark) ===\n{'=' * 72}")
        r = backtest_momentum(lb, code_monthly_ret, all_months, universe)
        if r["status"] != "ok":
            print(f"  {r['status']} n={r.get('n', 0)}")
            verdicts[f"mom{lb}m_top250"] = "TOO_FEW"
            continue
        print(f"  avg picks/month={r['avg_picks']} | n_months={r['n']}")
        stats_block(r["excess"], "full")
        stats_block(r["train"], f"train(~{r['train_dates'][0][:7]}~{r['train_dates'][-1][:7]})")
        stats_block(r["test"], f"test(~{r['test_dates'][0][:7]}~{r['test_dates'][-1][:7]})")
        if r["benchmark"]:
            print(
                f"  benchmark(filtered等权) mean: {statistics.mean(r['benchmark']):.4f}%/月 "
                f"| strategy: {statistics.mean(r['strategy']):.4f}%/月"
            )
        slippage_sensitivity(lb, code_monthly_ret, all_months, universe)
        verdicts[f"mom{lb}m_top250"] = _verdict(r, f"mom {lb}m (top-250)")

    # ── no-skip 对照（看 1 月反转污染程度）──
    print(f"\n{'=' * 72}\n=== NO-SKIP 对照（formation 含最近月, hold 次月, 受 1 月反转污染）===\n{'=' * 72}")
    print("  目的：验证 skip-1 的必要性。若无 skip 仍正 = 动量强于反转；若无 skip 翻负 = 反转主导。")
    for lb in (1, 2, 3):
        r = backtest_momentum(lb, code_monthly_ret, all_months, universe, skip=False)
        if r["status"] != "ok":
            print(f"  lookback={lb}m no-skip: {r['status']}")
            continue
        f = nw_t(r["excess"])
        te = nw_t(r["test"])
        print(f"  lookback={lb}m no-skip: full excess={f['mean']:.4f}%/月 t={f['t']} | test excess={te['mean']:.4f}%/月 t={te['t']}")

    # ── broad universe 敏感性（momentum 常在中小盘更强）──
    if args.broad:
        print(f"\n{'=' * 72}\n=== BROAD universe 敏感性（全 ≥1500bars, 含中小盘）===\n{'=' * 72}")
        broad = select_broad_universe()
        print(f"broad universe: {len(broad)} stocks (全 ≥1500bars, survivorship caveat 更强)")
        cmr_b, months_b = load_monthly_returns_by_month(broad)
        print(f"broad monthly returns: {len(cmr_b)} stocks, {len(months_b)} months")
        for lb in (1, 2, 3):
            r = backtest_momentum(lb, cmr_b, months_b, broad)
            if r["status"] != "ok":
                print(f"  lookback={lb}m broad: {r['status']}")
                continue
            f = nw_t(r["excess"])
            te = nw_t(r["test"])
            pb = bonferroni_p(te["p"], N_BONF)
            print(f"  lookback={lb}m broad: full excess={f['mean']:.4f}%/月 t={f['t']} | test excess={te['mean']:.4f}%/月 t={te['t']} Bonf={pb:.4f} (n={te['n']})")
            verdicts[f"mom{lb}m_broad"] = _verdict(r, f"mom {lb}m (broad)")

    # ── summary ──
    print(f"\n{'=' * 72}\n=== SUMMARY ===\n{'=' * 72}")
    for k, v in verdicts.items():
        print(f"  {k}: {v}")
    all_falsified = all(v == "FALSIFIED" for v in verdicts.values() if v not in ("TOO_FEW",))
    any_confirmed = any(v == "edge-confirmed-provisional" for v in verdicts.values())
    any_exploratory = any(v == "EXPLORATORY" for v in verdicts.values())
    if any_confirmed:
        overall = "edge-confirmed-provisional（须幸存者审查+独立复现）"
    elif any_exploratory:
        overall = "EXPLORATORY（某窗口 t>2 但 walk-forward 不稳健）"
    elif all_falsified:
        overall = "FALSIFIED（全窗口 t<2 或 walk-forward test FAIL）"
    else:
        overall = "mixed"
    print(f"  OVERALL: {overall}")

    out = {
        "_meta": {
            "factor": "midfreq_momentum (1-3m positive, top decile, skip-1 JT)",
            "universe": f"top-{args.size} + broad={args.broad}",
            "cost": COST,
            "n_bonf": N_BONF,
            "t_kill": T_KILL,
            "survivorship_caveat": "≥1500bars=survivors, 退市未算 → INFLATES",
            "data_note": "qfq monthly return = total return (含分红送转), 同 reversal 口径",
            "skip_note": "skip-1: formation=[mi-lb,mi-1], skip mi, hold mi+1 (避 1 月反转)",
        },
        "verdicts": verdicts,
        "overall": overall,
    }
    p = Path(__file__).parent / "_midfreq_momentum_result.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nresult JSON -> {p}")


if __name__ == "__main__":
    main()
