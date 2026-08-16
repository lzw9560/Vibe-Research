#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""§44 caveat 收口：kline TA edge 的 3 步 robustness 验证。

1. day-cluster bootstrap：breakout/volatility lift 在 day-resample 下 robust 吗（CI 下界>1→非日级 confound）。
2. premium-return：breakout/volatility → T return_open2close（cache 算），per-quintile avg → edge translate 到 PnL？
3. incremental-8：今日涨停子集上，TA-alone vs 8-alone vs 8+TA → T+1 涨停 lift（8 增量还是稀释？）。

用法：cd backend && .venv/bin/python tools/kline_ta_robustness.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import random
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/tools"))

KLINE_CACHE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
DB = ROOT / ".vibe-research" / "gene_scores.db"


def _wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return c - h, c + h


def _compute_ta(bars: list[dict], target_date: str) -> dict | None:
    """复用 kline_ta_validation 的 TA 计算（T-1 features for target T）。"""
    from kline_ta_validation import _compute_ta as _ta
    return _ta(bars, target_date)


def _t_return(bars: list[dict], target_date: str) -> float | None:
    """T 日 open→close 收益率（从 cache 的 T bar 算）。"""
    for b in bars:
        if b["date"] == target_date:
            o, c = b.get("open", 0), b.get("close", 0)
            return (c - o) / o * 100 if o else None
    return None


def _quintile_lift(vals: list[tuple[float, int]], q: int = 5) -> tuple[float, float, float, int, int]:
    """vals: [(feature_val, is_target)] sorted by feature. 返 (top_rate, bottom_rate, lift, top_n, bottom_n)."""
    vals.sort(key=lambda x: x[0])
    n = len(vals)
    qs = max(1, n // q)
    bottom = vals[:qs]
    top = vals[-qs:]
    b_t = sum(v[1] for v in bottom)
    t_t = sum(v[1] for v in top)
    b_r = b_t / qs if qs else 0
    t_r = t_t / qs if qs else 0
    return t_r, b_r, (t_r / b_r if b_r else 0.0), t_t, qs


def main() -> int:
    cache = json.loads(KLINE_CACHE.read_bytes())
    conn = sqlite3.connect(str(DB), timeout=10)
    try:
        em_dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM gene_scores WHERE data_source='eastmoney_live' ORDER BY date"
        ).fetchall()]
        zt_by_date = {d: {r[0] for r in conn.execute(
            "SELECT DISTINCT code FROM gene_scores WHERE date=? AND data_source='eastmoney_live'", (d,)).fetchall()}
            for d in em_dates}
        # 8 因子（gene_scores，今日涨停子集）
        gene8_by_date = {d: {r[0]: r for r in conn.execute(
            "SELECT code, factor_seal_rate, factor_rebound_rate, factor_red_rate, "
            "factor_premium_rate, factor_freq_score, total_score "
            "FROM gene_scores WHERE date=? AND data_source='eastmoney_live'", (d,)).fetchall()}
            for d in em_dates}
    finally:
        conn.close()

    # 收集 observations: (T, code, ta_features, is_zt_T, t_return)
    obs: list[dict] = []
    for T in em_dates:
        zt_T = zt_by_date.get(T, set())
        for code, bars in cache.items():
            ta = _compute_ta(bars, T)
            if ta is None:
                continue
            tr = _t_return(bars, T)
            obs.append({"T": T, "code": code, "ta": ta,
                        "is_zt": 1 if code in zt_T else 0, "t_return": tr})

    n = len(obs)
    n_days = len(set(o["T"] for o in obs))
    print(f"=== §44 caveat 收口（{n} obs, {n_days} T 日）===\n")

    # === Step 1: day-cluster bootstrap（breakout + volatility）===
    print("── Step 1: day-cluster bootstrap ──")
    by_day = defaultdict(list)
    for o in obs:
        by_day[o["T"]].append(o)
    days = list(by_day.keys())
    for feat in ("breakout", "volatility"):
        lifts = []
        random.seed(42)
        for _ in range(200):
            sampled = [by_day[d] for d in random.choices(days, k=len(days))]
            flat = [o for day_obs in sampled for o in day_obs]
            vals = [(o["ta"][feat], o["is_zt"]) for o in flat]
            _, _, lift, _, _ = _quintile_lift(vals)
            lifts.append(lift)
        lifts.sort()
        lo = lifts[10]  # 5th percentile
        hi = lifts[190]  # 95th percentile
        med = lifts[100]
        print(f"  {feat}: day-cluster lift median={med:.3f}x, 90%CI[{lo:.3f}, {hi:.3f}]"
              f" → {'robust（下界>1）' if lo > 1.0 else 'NOT robust（日级 confound 风险）'}")

    # === Step 2: premium-return（breakout/volatility → T return_open2close）===
    print("\n── Step 2: premium-return（T open2close）──")
    for feat in ("breakout", "volatility"):
        rets = [(o["ta"][feat], o["t_return"]) for o in obs if o["t_return"] is not None]
        rets.sort(key=lambda x: x[0])
        q = max(1, len(rets) // 5)
        bottom = rets[:q]
        top = rets[-q:]
        b_avg = sum(r[1] for r in bottom) / q
        t_avg = sum(r[1] for r in top) / q
        spread = t_avg - b_avg
        print(f"  {feat}: top-quintile avg return={t_avg:.3f}%  bottom={b_avg:.3f}%  spread={spread:.3f}%"
              f" → {'edge translate 到 PnL' if spread > 0.1 else 'NOT translate（涨停edge≠溢价edge）'}")

    # === Step 3: incremental-8（今日涨停子集，TA vs 8 vs 8+TA → T+1 涨停）===
    print("\n── Step 3: incremental-8（今日涨停子集 → T+1 涨停）──")
    # 今日涨停子集（有 8 因子 + cache TA）
    cont_obs: list[dict] = []
    for i, T in enumerate(em_dates[:-1]):
        T1 = em_dates[i + 1]
        zt_T1 = zt_by_date.get(T1, set())
        g8 = gene8_by_date.get(T, {})
        for code in zt_by_date.get(T, set()):
            if code not in cache or code not in g8:
                continue
            ta = _compute_ta(cache[code], T)
            if ta is None:
                continue
            g = g8[code]  # (code, seal, rebound, red, premium, freq, total)
            total_score = g[6] or 0  # total_score
            cont_obs.append({"T": T, "code": code, "ta": ta, "total": total_score,
                             "is_zt_T1": 1 if code in zt_T1 else 0})

    print(f"  今日涨停子集: {len(cont_obs)} obs（有 8 因子 + TA + T+1 目标）")
    if cont_obs:
        base = sum(o["is_zt_T1"] for o in cont_obs) / len(cont_obs)
        print(f"  T+1 涨停 base rate: {base*100:.1f}%")
        # TA-alone（breakout）
        ta_vals = [(o["ta"]["breakout"], o["is_zt_T1"]) for o in cont_obs]
        t_r, b_r, lift_ta, _, _ = _quintile_lift(ta_vals)
        print(f"  TA-alone (breakout→T+1涨停): lift={lift_ta:.3f}x (top {t_r*100:.1f}% vs bot {b_r*100:.1f}%)")
        # 8-alone（total_score）
        g_vals = [(o["total"], o["is_zt_T1"]) for o in cont_obs]
        t_r, b_r, lift_8, _, _ = _quintile_lift(g_vals)
        print(f"  8-alone (total_score→T+1涨停): lift={lift_8:.3f}x (top {t_r*100:.1f}% vs bot {b_r*100:.1f}%)")
        # 8+TA（combined rank: rank(total) + rank(breakout) + rank(volatility)）
        ranked = sorted(cont_obs, key=lambda o: o["total"])
        rank_total = {o["code"] + o["T"]: i for i, o in enumerate(ranked)}
        ranked2 = sorted(cont_obs, key=lambda o: o["ta"]["breakout"])
        rank_brk = {o["code"] + o["T"]: i for i, o in enumerate(ranked2)}
        ranked3 = sorted(cont_obs, key=lambda o: o["ta"]["volatility"])
        rank_vol = {o["code"] + o["T"]: i for i, o in enumerate(ranked3)}
        combined = [(rank_total[o["code"]+o["T"]] + rank_brk[o["code"]+o["T"]] + rank_vol[o["code"]+o["T"]],
                     o["is_zt_T1"]) for o in cont_obs]
        t_r, b_r, lift_combo, _, _ = _quintile_lift(combined)
        print(f"  8+TA (combined rank→T+1涨停): lift={lift_combo:.3f}x (top {t_r*100:.1f}% vs bot {b_r*100:.1f}%)")
        verdict = "8 有增量价值（保留）" if lift_combo > max(lift_ta, lift_8) + 0.05 else "8 无增量/稀释（可丢）"
        print(f"  → {verdict}（combo {lift_combo:.3f} vs max(TA {lift_ta:.3f}, 8 {lift_8:.3f})）")
    else:
        print("  无数据（今日涨停 ∩ cache 交集空？）")

    print(f"\n=== 收口结论 ===")
    print("全 3 步过 → TA edge validated + robust + translate-to-PnL + 8 保/丢有据 → 建选股系统。")
    print("任何步崩 → 早知道，不浪费建。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
