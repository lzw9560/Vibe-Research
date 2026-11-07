# -*- coding: utf-8 -*-
"""因子分解角度 grill: consecutive_relay 证否的 lbc/板块/换手/封板 交互分解.

用 kline_cache_store.get_bars (per-code lazy, 低内存) 而非 load_kline_db (全量 2GB).
窗口: close_ev = T+1 open -> T+2 close (与 explore_factor_lbc-tier 一致, 非 V2 的 D+1close->D+2open gap).

诚实口径 (沿用 _factor_helpers):
- entry = T+1 open (非 T close sealed)
- 一字涨停 T+1 跳过 (FIXED limit_for_code)
- close_ev 非 open_ev (防 T+1 日内泄漏)
- per-day-mean t (同日聚合, 防同日相关夸大 N)
- Bonferroni 跨子集校正

输出: lbc 单维 (2/3/4/5/6+) + board×lbc + turnover×lbc + seal×lbc 交互.
"""

from __future__ import annotations
import sys
import sqlite3
import statistics
import json
from collections import defaultdict, Counter
from pathlib import Path
from math import erf, sqrt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir
from engine.kline_cache_store import get_bars
from tools._factor_helpers import (
    limit_for_code,
    is_yizi_t1,
    close_ev_basic,
    close_ev_stop,
    ev_stats,
    day_paired_t,
    bonferroni_p,
    COST,
    ALPHA,
    STOP_PCT,
)

ZT_DB = resolve_data_dir() / "zt_history.db"


def load_zt_relay() -> list[tuple[str, str, int]]:
    conn = sqlite3.connect(str(ZT_DB))
    rows = []
    for d, code, lbc in conn.execute("SELECT date, code, lbc FROM zt_history"):
        rows.append((d, code, lbc if lbc else 1))
    conn.close()
    return rows


def board_of(code: str) -> str:
    if code.startswith(("300", "301")):
        return "chuangye"
    if code.startswith(("688", "689")):
        return "kechuang"
    if code.startswith(("4", "8")):
        return "bj"
    return "main"


def build_picks(
    code_cache: dict[str, dict[str, dict]], calendar: list[str], zt_rows, lbc_lo: int, lbc_hi: int = 999
) -> list[dict]:
    date_idx = {d: i for i, d in enumerate(calendar)}
    picks = []
    for zt_date, code, lbc in zt_rows:
        if lbc < lbc_lo or lbc > lbc_hi:
            continue
        d_idx = date_idx.get(zt_date)
        if d_idx is None or d_idx + 2 >= len(calendar):
            continue
        dmap = code_cache.get(code)
        if not dmap:
            continue
        t_bar = dmap.get(zt_date)
        if t_bar is None or t_bar.get("close") is None:
            continue
        t_close = t_bar["close"]
        if t_close <= 0:
            continue
        t1_date = calendar[d_idx + 1]
        t2_date = calendar[d_idx + 2]
        t1_bar = dmap.get(t1_date)
        t2_bar = dmap.get(t2_date)
        if t1_bar is None or t2_bar is None:
            continue
        t1_open = t1_bar.get("open")
        t2_close = t2_bar.get("close")
        if t1_open is None or t2_close is None or t1_open <= 0 or t2_close <= 0:
            continue
        is_st = t_bar.get("isST") == "1"
        limit = limit_for_code(code, is_st)
        if is_yizi_t1(t1_bar, t_close, limit):
            continue
        # seal strength proxy: T-day close vs high (closed at top = strong seal)
        th = t_bar.get("high")
        tl = t_bar.get("low")
        seal = 1.0 if (th and tl and th > tl and abs(t_close - th) / (th - tl) < 0.3) else 0.0
        # turnover from T-day bar
        turn = t_bar.get("turn")
        turn_f = float(turn) if turn is not None else None
        picks.append(
            {
                "code": code,
                "zt_date": zt_date,
                "t1_date": t1_date,
                "t2_date": t2_date,
                "entry": t1_open,
                "t1_bar": t1_bar,
                "t2_bar": t2_bar,
                "t_close": t_close,
                "lbc": lbc,
                "board": board_of(code),
                "turn": turn_f,
                "seal": seal,
                "limit_pct": limit,
            }
        )
    return picks


def cell_stats(name: str, picks: list[dict]) -> dict:
    if not picks:
        print(f"  {name:<28} n=0")
        return {"name": name, "n": 0}
    rets = [close_ev_basic(p) for p in picks]
    rets = [r for r in rets if r is not None]
    s = ev_stats(rets)
    by_date = defaultdict(list)
    for p in picks:
        r = close_ev_basic(p)
        if r is not None:
            by_date[p["zt_date"]].append(r)
    dt = day_paired_t(by_date)
    net = s["ev"] - COST * 100
    print(
        f"  {name:<28} n={s['n']:>4} days={dt['n_days']:>3} gross_EV={s['ev']:>+7.3f}% "
        f"net={net:>+7.3f}% WR={s['wr']:>5.1f}% day_t={dt['t']:>+6.2f} "
        f"p={dt['p_one_sided']:.4f}"
    )
    return {
        "name": name,
        "n": s["n"],
        "n_days": dt["n_days"],
        "ev": s["ev"],
        "net": net,
        "wr": s["wr"],
        "t": dt["t"],
        "p": dt["p_one_sided"],
    }


def main() -> None:
    print("=" * 78)
    print("因子分解角度 grill: consecutive_relay 证否审视 (close_ev = T+1open->T+2close)")
    print("=" * 78)
    zt_rows = load_zt_relay()
    relay_rows = [(d, c, l) for d, c, l in zt_rows if l >= 2]
    print(f"zt rows: {len(zt_rows)} | relay (lbc>=2): {len(relay_rows)}")

    # load klines per-code for relay codes only (low memory)
    relay_codes = sorted({c for _, c, _ in relay_rows})
    print(f"loading klines for {len(relay_codes)} relay codes (per-code)...")
    code_cache = {}
    all_dates = set()
    for code in relay_codes:
        bars = get_bars(code)
        if not bars:
            continue
        dmap = {b["date"]: b for b in bars if b.get("date")}
        code_cache[code] = dmap
        all_dates.update(dmap.keys())
    calendar = sorted(all_dates)
    print(f"  loaded {len(code_cache)} codes, calendar {len(calendar)} ({calendar[0]} ~ {calendar[-1]})")

    # ===== 1. lbc 单维细分 (2/3/4/5/6+) =====
    print(f"\n{'=' * 78}\n[1] lbc 单维细分 (close_ev, 非 V2 gap 窗口)\n{'=' * 78}")
    tiers = [
        (2, 2, "lbc=2"),
        (3, 3, "lbc=3"),
        (4, 4, "lbc=4"),
        (5, 5, "lbc=5"),
        (6, 99, "lbc>=6"),
        (2, 99, "lbc>=2(all)"),
        (4, 99, "lbc>=4"),
    ]
    results1 = {}
    for lo, hi, lab in tiers:
        pk = build_picks(code_cache, calendar, zt_rows, lo, hi)
        results1[lab] = cell_stats(lab, pk)

    # ===== 2. board × lbc 交互 =====
    print(f"\n{'=' * 78}\n[2] 板块 × lbc 交互 (V2 合并所有板块)\n{'=' * 78}")
    relay_all = build_picks(code_cache, calendar, zt_rows, 2, 99)
    print(f"  relay picks usable: {len(relay_all)}")
    # board dist
    bdist = Counter(p["board"] for p in relay_all)
    print(f"  board dist: {dict(bdist)}")
    for board in ["main", "chuangye", "kechuang"]:
        for lo, hi, lab in [(2, 99, "lbc>=2"), (2, 2, "lbc=2"), (3, 3, "lbc=3"), (4, 99, "lbc>=4")]:
            pk = [p for p in relay_all if p["board"] == board and lo <= p["lbc"] <= hi]
            cell_stats(f"{board}/{lab}", pk)

    # ===== 3. turnover × lbc 交互 =====
    print(f"\n{'=' * 78}\n[3] 换手率 × lbc 交互 (T 日 turn 分位)\n{'=' * 78}")
    turns = [p["turn"] for p in relay_all if p["turn"] is not None]
    print(f"  picks with turn: {len(turns)} / {len(relay_all)}")
    if turns:
        q = statistics.quantiles(turns, n=3)
        print(f"  turn terciles: low<{q[0]:.2f}% | mid {q[0]:.2f}-{q[1]:.2f}% | high>{q[1]:.2f}%")

        def turn_grp(p):
            if p["turn"] is None:
                return "unk"
            if p["turn"] <= q[0]:
                return "low_turn"
            if p["turn"] <= q[1]:
                return "mid_turn"
            return "high_turn"

        for tg in ["low_turn", "mid_turn", "high_turn"]:
            for lo, hi, lab in [(2, 99, "lbc>=2"), (4, 99, "lbc>=4")]:
                pk = [p for p in relay_all if turn_grp(p) == tg and lo <= p["lbc"] <= hi]
                cell_stats(f"{tg}/{lab}", pk)

    # ===== 4. seal strength × lbc 交互 =====
    print(f"\n{'=' * 78}\n[4] 封板强度(seal proxy: T 收≈高) × lbc 交互\n{'=' * 78}")
    sdist = Counter(p["seal"] for p in relay_all)
    print(f"  seal dist: strong(1)={sdist[1]} weak(0)={sdist[0]}")
    for sl, lab in [(1, "strong_seal"), (0, "weak_seal")]:
        for lo, hi, l in [(2, 99, "lbc>=2"), (4, 99, "lbc>=4")]:
            pk = [p for p in relay_all if p["seal"] == sl and lo <= p["lbc"] <= hi]
            cell_stats(f"{lab}/{l}", pk)

    # ===== 5. Bonferroni 校正 (lbc 5 tiers single-dim) =====
    print(f"\n{'=' * 78}\n[5] Bonferroni 校正 (lbc 5 tiers ×2 = 10 tests)\n{'=' * 78}")
    for lab in ["lbc=2", "lbc=3", "lbc=4", "lbc=5", "lbc>=6"]:
        r = results1.get(lab, {})
        if not r or r.get("n", 0) == 0:
            continue
        bonf = bonferroni_p(r["p"], 10)
        verdict = (
            "FALSIFIED(gross<0)"
            if r["ev"] < 0
            else "UNDERPOWERED(days<60)"
            if r["n_days"] < 60
            else "FALSIFIED(bonf>=.05)"
            if bonf >= ALPHA
            else "FALSIFIED(net<=0)"
            if r["net"] <= 0
            else "exploratory"
        )
        print(
            f"  {lab:<10} gross={r['ev']:>+7.3f}% net={r['net']:>+7.3f}% "
            f"p={r['p']:.4f} Bonf×10={bonf:.4f} days={r['n_days']} -> {verdict}"
        )


if __name__ == "__main__":
    main()
