#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""§44 验证：kline TA（T-1 价格/量能）→ T 涨停（盘前选股）。

假设：T-1 kline TA 特征（momentum/量能/MA/突破/波动）→ T 涨停概率↑（pre-涨停特征，
不需涨停事件，universe=有 kline 历史的股）。§44 bar：lift>=2x + CI 不重叠 + n>=30。

数据：baostock_kline_cache.json（1121 股 × 日K，2025-12-25→2026-08-13，缓存本地无限流）
+ gene_scores（T 涨停池，eastmoney_live 32 日）。T-1 覆盖 30 日（07-09→08-13）。

设计：对每个 T（eastmoney_live 日）：
  universe = cache 中有 T-1 bar（+ 20 bar 前置）的 code
  T-1 特征：momentum_5d / vol_surge / ma_align / breakout_20d / volatility_5d
  目标：T 涨停（code ∈ gene_scores T）
  lift = top-quintile 特征的涨停率 / bottom-quintile

用法：cd backend && .venv/bin/python tools/kline_ta_validation.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

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
    """bars（按 date 升序）→ target_date T 的 T-1 TA 特征。需 ≥21 bar 前置。"""
    t1_idx = None
    for i, b in enumerate(bars):
        if b["date"] >= target_date:
            break
        t1_idx = i
    if t1_idx is None or t1_idx < 20:
        return None
    t1 = bars[t1_idx]
    close_t1 = t1["close"]
    if not close_t1 or close_t1 <= 0:
        return None
    # momentum 5d
    close_t6 = bars[t1_idx - 5]["close"]
    momentum = (close_t1 - close_t6) / close_t6 if close_t6 else 0.0
    # volume surge
    vol_t1 = t1["volume"] or 0
    vols_prev = [bars[t1_idx - j]["volume"] or 0 for j in range(1, 6)]
    avg_vol = sum(vols_prev) / 5 if vols_prev else 1
    vol_surge = vol_t1 / avg_vol if avg_vol else 0.0
    # ma alignment
    closes = [bars[t1_idx - j]["close"] for j in range(20)]
    ma5 = sum(closes[:5]) / 5
    ma10 = sum(closes[:10]) / 10
    ma20 = sum(closes) / 20
    ma_align = 1 if ma5 > ma10 > ma20 else 0
    # breakout 20d
    highs_prev = [bars[t1_idx - j]["high"] or 0 for j in range(1, 21)]
    max_high = max(highs_prev) if highs_prev else 0
    breakout = 1 if close_t1 >= 0.95 * max_high and max_high else 0
    # volatility 5d
    highs5 = [bars[t1_idx - j]["high"] or 0 for j in range(5)]
    lows5 = [bars[t1_idx - j]["low"] or 0 for j in range(5)]
    volat = (max(highs5) - min(lows5)) / close_t1 if close_t1 else 0.0
    return {"momentum": momentum, "vol_surge": vol_surge, "ma_align": ma_align,
            "breakout": breakout, "volatility": volat}


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
    finally:
        conn.close()

    # 收集 (T, code, features, is_zt)
    features = ["momentum", "vol_surge", "ma_align", "breakout", "volatility"]
    observations: list[dict] = []  # {code, T, is_zt, **ta}
    for T in em_dates:
        zt_T = zt_by_date.get(T, set())
        for code, bars in cache.items():
            ta = _compute_ta(bars, T)
            if ta is None:
                continue
            observations.append({"code": code, "T": T,
                                  "is_zt": 1 if code in zt_T else 0, **ta})

    n = len(observations)
    n_zt = sum(o["is_zt"] for o in observations)
    base_rate = n_zt / n if n else 0
    print(f"=== kline TA → T 涨停 §44 验证 ===")
    print(f"观测: {n}（{len(em_dates)} T 日 × ~{n // len(em_dates)} 股/T）")
    print(f"涨停: {n_zt} = {base_rate*100:.2f}%（base rate）\n")

    for feat in features:
        vals = sorted(observations, key=lambda o: o[feat])
        q = max(1, n // 5)
        bottom = vals[:q]
        top = vals[-q:]
        b_zt = sum(o["is_zt"] for o in bottom)
        t_zt = sum(o["is_zt"] for o in top)
        b_rate = b_zt / q
        t_rate = t_zt / q
        lift = t_rate / b_rate if b_rate else 0.0
        tb_lo, tb_hi = _wilson(t_zt, q)
        bb_lo, bb_hi = _wilson(b_zt, q)
        sig = "CI不重叠" if tb_lo > bb_hi else "CI重叠"
        verdict = "≥2x EDGE" if lift >= 2.0 else "<2x 噪声"
        print(f"{feat:12s}: top {t_zt}/{q}={t_rate*100:.2f}%[{tb_lo*100:.1f},{tb_hi*100:.1f}]  "
              f"bottom {b_zt}/{q}={b_rate*100:.2f}%[{bb_lo*100:.1f},{bb_hi*100:.1f}]  "
              f"lift={lift:.3f}x → {verdict}（{sig}）")
    print(f"\ncaveat: n_days={len(em_dates)}；universe=cache 1109 股（有 kline 历史，非全市场）；"
          f"若全 <2x → kline TA 对次日涨停无 §44 edge。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
