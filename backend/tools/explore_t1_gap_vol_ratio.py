# -*- coding: utf-8 -*-
"""S232 扩展：gap × T+1量比 双维度组合 EV 验证。

T+1量比 = T+1 bar volume / T bar volume（T 日量在 T bar，T+1 量在 T+1 bar）。
量比分组：<0.8（缩量）/ 0.8~1.2（平量）/ >1.2（放量），叠加 gap 5 桶 = 15 组。
找 EV > +0.70%（低开-5%~-2% baseline）且 n>=30 的组合。

跑法：cd backend && .venv/bin/python -m tools.explore_t1_gap_vol_ratio
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from tools.t1_forecast import (
    _generate_from_preloaded,
    _load_kline_bars,
    _zt_db_path,
)

_logger = logging.getLogger("vibe-research")

GAP_BUCKETS = [
    ("低开<-5%", lambda g: g < -5),
    ("低开-5%~-2%", lambda g: -5 <= g < -2),
    ("平开-2%~+2%", lambda g: -2 <= g <= 2),
    ("高开+2%~+5%", lambda g: 2 < g <= 5),
    ("高开>+5%", lambda g: g > 5),
]
VR_BUCKETS = [
    ("缩量<0.8", lambda v: v < 0.8),
    ("平量0.8~1.2", lambda v: 0.8 <= v <= 1.2),
    ("放量>1.2", lambda v: v > 1.2),
]


def _vol_ratio_bucket(v: float) -> str:
    for name, fn in VR_BUCKETS:
        if fn(v):
            return name
    return VR_BUCKETS[-1][0]


def _gap_bucket(g: float) -> str:
    for name, fn in GAP_BUCKETS:
        if fn(g):
            return name
    return GAP_BUCKETS[-1][0]


def t1_gap_vol_ratio_analysis(end_date: str, days: int = 180) -> dict[str, Any]:
    """gap × T+1量比 双维度组合 EV。"""
    import sqlite3

    all_bars = _load_kline_bars()
    zt_db = _zt_db_path()
    zt_by_date: dict[str, set[str]] = {}
    if zt_db.exists():
        conn = sqlite3.connect(str(zt_db))
        try:
            for d, c in conn.execute("SELECT date, code FROM zt_history"):
                zt_by_date.setdefault(d, set()).add(c)
        finally:
            conn.close()

    cal = sorted(zt_by_date.keys())
    if end_date not in cal:
        return {"status": "no_end_date", "end_date": end_date}
    end_idx = cal.index(end_date)
    pairs = [(cal[i], cal[i + 1]) for i in range(max(0, end_idx - days), end_idx) if i + 1 < len(cal)]

    date_idx = {d: i for i, d in enumerate(cal)}
    records: list[dict[str, Any]] = []
    for t, t1 in pairs:
        zt_t = zt_by_date.get(t, set())
        zt_t1 = zt_by_date.get(t1, set())
        t1_idx = date_idx.get(t1)
        if t1_idx is None or t1_idx + 1 >= len(cal):
            continue
        t2 = cal[t1_idx + 1]
        zt_t2 = zt_by_date.get(t2, set())
        wl = _generate_from_preloaded(t, all_bars, zt_t)
        for s in wl["stocks"]:
            code = s["code"]
            t_close = s["close"]
            if t_close is None:
                continue
            bars = all_bars.get(code, [])
            t_bar = next((b for b in bars if b.get("date") == t), None)
            t1_bar = next((b for b in bars if b.get("date") == t1), None)
            if not t_bar or not t1_bar:
                continue
            t1_open = t1_bar.get("open")
            t1_close = t1_bar.get("close")
            if t1_open is None or t1_close is None or t1_open == 0:
                continue
            t2_bar = next((b for b in bars if b.get("date") == t2), None)
            if not t2_bar or t2_bar.get("open") is None:
                continue
            t2_open = t2_bar["open"]
            # T+1 量比 = T+1 volume / T volume
            t_vol = t_bar.get("volume")
            t1_vol = t1_bar.get("volume")
            if not t_vol or not t1_vol:
                continue
            vr = t1_vol / t_vol
            gap = (t1_open - t_close) / t_close * 100
            was_zt_t1 = code in zt_t1
            was_zt_t2 = code in zt_t2
            zt_limit = 0.2 if code.startswith(("sz30", "sh68")) else 0.1
            zt_price_t2 = t1_close * (1 + zt_limit)
            ret = ((zt_price_t2 - t1_open) / t1_open * 100) if was_zt_t2 else ((t2_open - t1_open) / t1_open * 100)
            records.append(
                {
                    "code": code,
                    "t": t,
                    "t1": t1,
                    "t2": t2,
                    "gap": round(gap, 2),
                    "vr": round(vr, 3),
                    "gap_b": _gap_bucket(gap),
                    "vr_b": _vol_ratio_bucket(vr),
                    "was_zt_t1": was_zt_t1,
                    "was_zt_t2": was_zt_t2,
                    "ret": round(ret, 2),
                }
            )

    # gap-only buckets（验证 baseline 一致）
    gap_buckets: list[dict[str, Any]] = []
    for name, fn in GAP_BUCKETS:
        sub = [r for r in records if fn(r["gap"])]
        n = len(sub)
        hit = sum(1 for r in sub if r["was_zt_t2"])
        ev = sum(r["ret"] for r in sub) / n if n else 0.0
        gap_buckets.append(
            {
                "combo": f"{name}|全量比",
                "n": n,
                "hit": hit,
                "rate": round(hit / n, 4) if n else 0,
                "ev": round(ev, 2),
                "positive_ev": ev > 0,
            }
        )

    # gap × vr 组合（15 组）
    combos: list[dict[str, Any]] = []
    for gname, gfn in GAP_BUCKETS:
        for vname, vfn in VR_BUCKETS:
            sub = [r for r in records if gfn(r["gap"]) and vfn(r["vr"])]
            n = len(sub)
            hit = sum(1 for r in sub if r["was_zt_t2"])
            ev = sum(r["ret"] for r in sub) / n if n else 0.0
            combos.append(
                {
                    "combo": f"{gname}|{vname}",
                    "n": n,
                    "hit": hit,
                    "rate": round(hit / n, 4) if n else 0,
                    "ev": round(ev, 2),
                    "positive_ev": ev > 0,
                }
            )

    total_n = len(records)
    total_hit = sum(1 for r in records if r["was_zt_t2"])
    total_ev = sum(r["ret"] for r in records) / total_n if total_n else 0.0
    baseline = {
        "combo": "全样本(不筛 gap+vr)",
        "n": total_n,
        "hit": total_hit,
        "rate": round(total_hit / total_n, 4) if total_n else 0,
        "ev": round(total_ev, 2),
        "positive_ev": total_ev > 0,
    }

    # 找 EV > +0.70% 且 n>=30 的组合（排除小样本不可信）
    candidates = [c for c in combos if c["ev"] > 0.70 and c["n"] >= 30]
    candidates.sort(key=lambda c: c["ev"], reverse=True)

    print(f"\n=== t1_gap_vol_ratio_analysis: end_date={end_date} days={days} ===")
    print(f"pairs={len(pairs)} records={total_n}")
    print(f"\nBASELINE: n={baseline['n']} hit={baseline['hit']} rate={baseline['rate'] * 100:.2f}% EV={baseline['ev']:+.2f}%")
    print(f"\n--- gap-only buckets（验证 baseline 一致）---")
    for b in gap_buckets:
        print(f"  {b['combo']:30s} n={b['n']:5d} hit={b['hit']:4d} rate={b['rate'] * 100:5.2f}% EV={b['ev']:+6.2f}% {'POS' if b['positive_ev'] else ''}")
    print(f"\n--- gap × T+1量比 combos（15 组）---")
    for c in combos:
        flag = "  <-- BEATS BASELINE+0.70% n>=30" if c["ev"] > 0.70 and c["n"] >= 30 else ""
        print(f"  {c['combo']:35s} n={c['n']:5d} hit={c['hit']:4d} rate={c['rate'] * 100:5.2f}% EV={c['ev']:+6.2f}% {flag}")
    print(f"\n--- candidates EV>+0.70% n>=30 ({len(candidates)}) ---")
    for c in candidates:
        print(f"  {c['combo']:35s} n={c['n']:5d} hit={c['hit']:4d} rate={c['rate'] * 100:5.2f}% EV={c['ev']:+6.2f}%")

    return {
        "status": "ok",
        "days": len(pairs),
        "total_records": total_n,
        "baseline": baseline,
        "gap_buckets": gap_buckets,
        "combos": combos,
        "candidates": candidates,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    t1_gap_vol_ratio_analysis("2026-09-17", days=180)
