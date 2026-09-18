#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# GAP-WINDOW VARIANT of sector_heat_validation.py (2026-09-18, T+1 research lever).
#
# §44 v1 wrong-window context: the existing harness measured BINARY next-day-new-ZT
# rate (hot/cold) on 49 eastmoney_live days → lift 1.536 zt>=3 (registry stale
# 1.359/41d, evaluation.py:171). Two gaps: (1) only 49 days (underpowered, "60日后
# 复验"), (2) it's a binary-ZT-rate test NOT a return test — the overnight GAP return
# (where consecutive_relay's +1.04% edge lives) was never measured for sector_heat.
#
# This variant does BOTH on the 318-day zt_history backfill (S214):
#   (A) BINARY next-day-new-ZT framing — re-run existing logic on 318 days (was 49).
#       Does 1.536 hold / cross 2.0 with 6x more data?
#   (B) GAP-WINDOW RETURN (gap_net_return, D收→D+1开, accounting.py:262) for hot/cold
#       members — the true gap-window analog. lift = hot_gap_WR/cold_gap_WR + mean lift.
#
# sector_heat definition (zt>=3 hot / 0-zt cold / exclude D-ZT) IDENTICAL to existing.
# Only data source (zt_history 318d vs eastmoney_live 49d) + return window change.
#
# REALIZABILITY ADVANTAGE (honest): hot-sector members that did NOT ZT on D are NOT
# sealed at D close -> buying at D close IS realizable (unlike consecutive_relay/late_lock
# where the signal stock is sealed at D close). sector_heat's gap return is MORE tradeable.
#
# DATA: zt_history.db (318d, join code->code_industry.industry, 99.9% covered) +
# baostock_kline_cache.json (D close + D+1 open). eastmoney_live has industry directly
# but only 49d; code_industry covers all 318d (fuller names, semantically same — verified
# 90% exact match, rest truncation artifacts like "其他电源设备II" vs "其他电源").
"""GAP-window re-run of sector_heat (板块热度->次日新涨停 / 隔夜 gap return).

Does NOT modify tools/sector_heat_validation.py (path/binary harness preserved).
"""
from __future__ import annotations

import datetime
import json
import sqlite3
import statistics
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from data_quality.schema_validator import validate_or_reject  # noqa: E402  R1 bad-data gate
from engine.accounting import _cost_pct, gap_net_return  # noqa: E402  accounting.py:262

KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
ZHDB = ROOT / ".vibe-research" / "zt_history.db"
GSDB = ROOT / ".vibe-research" / "gene_scores.db"
TOL = 0.01  # 一字板价格容差


def _wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval (lo, hi) for a binomial proportion."""
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return c - h, c + h


def _welch_t(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch's t (t-stat, df) for two independent means. No scipy dependency."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0, 0.0
    ma, mb = statistics.mean(a), statistics.mean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    se = (va / na + vb / nb) ** 0.5
    if se == 0:
        return 0.0, 0.0
    t = (ma - mb) / se
    df_num = (va / na + vb / nb) ** 2
    df_den = (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    df = df_num / df_den if df_den else 0.0
    return t, df


def load_industry_map() -> dict[str, str]:
    """code -> industry from gene_scores.code_industry (covers 99.9% of zt_history codes)."""
    conn = sqlite3.connect(str(GSDB), timeout=10)
    try:
        rows = conn.execute(
            "SELECT code, industry FROM code_industry WHERE industry IS NOT NULL AND industry != ''"
        ).fetchall()
    finally:
        conn.close()
    return {str(r[0]).zfill(6): r[1] for r in rows}


def load_zt_pools() -> dict[str, set[str]]:
    """date -> set(code) limit-up pool from zt_history (all sources, PK dedupes (date,code))."""
    conn = sqlite3.connect(str(ZHDB), timeout=10)
    try:
        pools: dict[str, set[str]] = defaultdict(set)
        for d, code in conn.execute("SELECT date, code FROM zt_history"):
            pools[d].add(str(code).zfill(6))
    finally:
        conn.close()
    return dict(pools)


def load_kline_and_calendar() -> tuple[dict, dict[str, list[int]], list[str]]:
    """kline cache + per-code sorted calendar-index list + global calendar.

    Returns (kline, code_cal_idx, calendar):
      kline: {code: [bars]} (raw, for close/open prices)
      code_cal_idx: {code: [global_cal_idx per bar]} (sorted, for bisect lookup)
      calendar: sorted list of distinct trading dates (global index space)
    """
    kline = json.loads(KLINE.read_text())
    # global calendar = sorted union of all bar dates
    all_dates = sorted({str(b.get("date", ""))[:10] for bars in kline.values() for b in bars})
    cal_idx = {d: i for i, d in enumerate(all_dates)}
    # per-code calendar-index list (bars already date-sorted; map each bar date -> global idx)
    code_cal_idx: dict[str, list[int]] = {}
    for code, bars in kline.items():
        idxs = [cal_idx[str(b.get("date", ""))[:10]] for b in bars]
        code_cal_idx[str(code).zfill(6)] = idxs
    return kline, code_cal_idx, all_dates


def _bar_at(kline: dict, code_cal_idx: dict, code: str, date: str, cal_idx: dict[str, int]) -> Any:
    """Return the bar for code on date, or None (halted/missing). Uses bisect on cal-idx list."""
    ckey = str(code).zfill(6)
    idxs = code_cal_idx.get(ckey)
    if not idxs:
        return None
    target = cal_idx.get(date)
    if target is None:
        return None
    pos = bisect_left(idxs, target)
    if pos < len(idxs) and idxs[pos] == target:
        return kline[ckey][pos]
    return None


def is_one_word_d(bar: dict) -> bool:
    """D-day one-word bar (open~=high~=low~=close, sealed/halted). Skip — not reliably tradeable."""
    o = bar.get("open") or 0
    h = bar.get("high") or 0
    l = bar.get("low") or 0
    c = bar.get("close") or 0
    if not (o and h and l and c):
        return True  # missing fields = unusable
    return abs(h - l) <= TOL and abs(o - c) <= TOL and abs(h - o) <= TOL


def _members(industry: dict[str, str], hot_inds: set[str], all_inds: set[str],
             d_zt_codes: set[str]) -> tuple[list[str], list[str]]:
    """Hot/cold member codes (exclude D-ZT stocks = new-ZT framing). IDENTICAL to existing harness."""
    hot_mem = [c for c, ind in industry.items() if ind in hot_inds and c not in d_zt_codes]
    cold_mem = [c for c, ind in industry.items() if ind not in all_inds and c not in d_zt_codes]
    return hot_mem, cold_mem


def binary_framing(zt: dict[str, set[str]], industry: dict[str, str],
                   calendar: list[str], cal_idx: dict[str, int]) -> None:
    """(A) Binary next-day-new-ZT rate lift, 318-day backfill (was 49d in existing harness)."""
    defs = [("top1", 1, 0), ("top3", 3, 0), ("top5", 5, 0), ("zt>=3", 99, 3), ("zt>=5", 99, 5)]
    zt_dates = sorted(d for d in zt if d in cal_idx)
    daily = []
    for i, d in enumerate(zt_dates):
        ni = cal_idx[d] + 1
        if ni >= len(calendar):
            continue
        d1 = calendar[ni]
        if d1 not in zt:
            continue  # binary framing needs D+1 ZT pool
        zt_by_ind = Counter()
        d_zt = set()
        for code in zt[d]:
            ind = industry.get(code)
            if ind:
                zt_by_ind[ind] += 1
                d_zt.add(code)
        daily.append((d, zt_by_ind, d_zt, zt[d1]))
    all_inds_per_day = [{ind for ind, c in z.items() if c > 0} for _, z, _, _ in daily]
    print(f"\n=== (A) BINARY next-day-new-ZT framing (zt_history {len(daily)} day-pairs) ===")
    for name, topn, thresh in defs:
        hm = hn = cm = cn = 0
        for idx, (_, zt_by_ind, d_zt, d1_zt) in enumerate(daily):
            ranked = sorted(zt_by_ind.items(), key=lambda x: -x[1])
            hot_inds = {ind for ind, _ in ranked[:topn]} if topn < 99 else \
                {ind for ind, c in zt_by_ind.items() if c >= thresh}
            all_inds = all_inds_per_day[idx]
            hot_mem, cold_mem = _members(industry, hot_inds, all_inds, d_zt)
            if not hot_mem or not cold_mem:
                continue
            hm += len(hot_mem); cm += len(cold_mem)
            hn += sum(1 for c in hot_mem if c in d1_zt)
            cn += sum(1 for c in cold_mem if c in d1_zt)
        hr = hn / hm if hm else 0.0
        cr = cn / cm if cm else 0.0
        lift = hr / cr if cr else 0.0
        hlo, hhi = _wilson(hn, hm)
        clo, chi = _wilson(cn, cm)
        sig = "CI不重叠" if hlo > chi else "CI重叠"
        verdict = ">=2x validated" if lift >= 2.0 else ("<2x 未validated" if lift >= 1.0 else "劣于随机")
        print(f"{name:6s}: hot {hn}/{hm}={hr*100:.2f}%[{hlo*100:.2f},{hhi*100:.2f}]  "
              f"cold {cn}/{cm}={cr*100:.2f}%[{clo*100:.2f},{chi*100:.2f}]  "
              f"lift={lift:.3f}x -> {verdict}({sig})")


def gap_framing(zt: dict[str, set[str]], industry: dict[str, str], kline: dict,
                code_cal_idx: dict[str, list[int]], calendar: list[str],
                cal_idx: dict[str, int]) -> None:
    """(B) Gap-window RETURN lift (gap_net_return, D收->D+1开) for hot/cold members."""
    validate_or_reject("baostock_kline",
                        [b for bars in kline.values() for b in bars],
                        as_of=datetime.date.today().isoformat())
    zt_dates = sorted(d for d in zt if d in cal_idx)
    hot_rets: list[float] = []
    cold_rets: list[float] = []
    hot_wins = cold_wins = 0
    n_days_hot = n_days_cold = 0
    skips = Counter()  # no_bar / one_word_D / no_D1_bar
    for di, d in enumerate(zt_dates):
        ni = cal_idx[d] + 1
        if ni >= len(calendar):
            continue
        d1 = calendar[ni]
        zt_by_ind = Counter()
        d_zt = set()
        for code in zt[d]:
            ind = industry.get(code)
            if ind:
                zt_by_ind[ind] += 1
                d_zt.add(code)
        hot_inds = {ind for ind, c in zt_by_ind.items() if c >= 3}  # zt>=3 (registry arm)
        all_inds = set(zt_by_ind.keys())
        hot_mem, cold_mem = _members(industry, hot_inds, all_inds, d_zt)
        day_hot = day_cold = 0
        for code in hot_mem:
            r = _gap_for(kline, code_cal_idx, code, d, d1, cal_idx, skips)
            if r is None:
                continue
            hot_rets.append(r[0]); day_hot += 1
            if r[0] > 0:
                hot_wins += 1
        for code in cold_mem:
            r = _gap_for(kline, code_cal_idx, code, d, d1, cal_idx, skips)
            if r is None:
                continue
            cold_rets.append(r[0]); day_cold += 1
            if r[0] > 0:
                cold_wins += 1
        if day_hot:
            n_days_hot += 1
        if day_cold:
            n_days_cold += 1
        if (di + 1) % 50 == 0:
            print(f"  ...{di+1}/{len(zt_dates)} days, hot_n={len(hot_rets)} "
                  f"cold_n={len(cold_rets)}", flush=True)
    _print_gap_results(hot_rets, cold_rets, hot_wins, cold_wins,
                       n_days_hot, n_days_cold, skips)


def _gap_for(kline: dict, code_cal_idx: dict, code: str, d: str, d1: str,
             cal_idx: dict[str, int], skips: Counter) -> tuple[float, float, float] | None:
    """gap_net_return(D close, D+1 open) for one code-day. None + skip-reason on miss."""
    d_bar = _bar_at(kline, code_cal_idx, code, d, cal_idx)
    if d_bar is None:
        skips["no_bar"] += 1
        return None
    if is_one_word_d(d_bar):
        skips["one_word_D"] += 1
        return None
    d1_bar = _bar_at(kline, code_cal_idx, code, d1, cal_idx)
    if d1_bar is None:
        skips["no_D1_bar"] += 1
        return None
    close_d = float(d_bar.get("close") or 0)
    open_d1 = float(d1_bar.get("open") or 0)
    if close_d <= 0 or open_d1 <= 0:
        skips["bad_price"] += 1
        return None
    net_ratio, cost_pct, gross_ratio = gap_net_return(close_d, open_d1, d, 100.0)
    return net_ratio * 100.0, cost_pct, gross_ratio * 100.0


def _print_gap_results(hot: list[float], cold: list[float], hw: int, cw: int,
                       ndh: int, ndc: int, skips: Counter) -> None:
    print(f"\n=== (B) GAP-window RETURN (D收->D+1开, gap_net_return) zt>=3 hot / 0-zt cold ===")
    print(f"  hot: n={len(hot)} days={ndh} | cold: n={len(cold)} days={ndc}")
    print(f"  excluded: {dict(skips)}")
    if not hot or not cold:
        print("  insufficient data")
        return
    wr_h = hw / len(hot)
    wr_c = cw / len(cold)
    mean_h = statistics.mean(hot)
    mean_c = statistics.mean(cold)
    hlo, hhi = _wilson(hw, len(hot))
    clo, chi = _wilson(cw, len(cold))
    wr_lift = wr_h / wr_c if wr_c else 0.0
    mean_lift = mean_h / mean_c if mean_c else 0.0
    sig = "CI不重叠" if hlo > chi else "CI重叠"
    wr_v = ">=2.0 robust_edge" if wr_lift >= 2.0 else ("<2 unvalidated" if wr_lift >= 1.0 else "falsified(劣于随机)")
    mean_v = ">=2.0 robust_edge" if mean_lift >= 2.0 else ("<2 unvalidated" if mean_lift >= 1.0 else "falsified(劣于随机)")
    print(f"  hot:  net_mean={mean_h:.3f}% net_WR={wr_h*100:.2f}%[{hlo*100:.2f},{hhi*100:.2f}]")
    print(f"  cold: net_mean={mean_c:.3f}% net_WR={wr_c*100:.2f}%[{clo*100:.2f},{chi*100:.2f}]")
    print(f"  winrate-lift(hot/cold) = {wr_lift:.3f}x -> {wr_v}({sig})")
    print(f"  mean-lift(hot/cold)    = {mean_lift:.3f}x -> {mean_v}")
    t, df = _welch_t(hot, cold)
    print(f"  Welch t(hot vs cold mean) = {t:.3f} df={df:.0f}  (|t|>2.58 ~p<0.01, >1.96 ~p<0.05)")
    # cost check
    avg_cost = _cost_pct(10.0, 100.0)  # nominal repr of round-trip cost scale
    print(f"  note: gap_net_return deducts _cost_pct (RTC+stamp+commission~{avg_cost:.2f}pp) per trade")


def main() -> None:
    print("sector_heat GAP-window variant (318-day zt_history backfill)")
    industry = load_industry_map()
    zt = load_zt_pools()
    kline, code_cal_idx, calendar = load_kline_and_calendar()
    cal_idx = {d: i for i, d in enumerate(calendar)}
    print(f"industry map: {len(industry)} codes | zt pools: {len(zt)} days | "
          f"kline: {len(kline)} codes | calendar: {len(calendar)} trading days")
    binary_framing(zt, industry, calendar, cal_idx)
    gap_framing(zt, industry, kline, code_cal_idx, calendar, cal_idx)
    print("\ncaveat: gap window measures overnight gap for NON-sealed hot-sector members "
          "(realizable at D close, unlike consecutive_relay/late_lock sealed signals). "
          "Binary framing tests D+1 new-ZT occurrence (T+1涨停 candidate). "
          "318d is 6x the 49d eastmoney_live — regression toward 1.0 expected if 1.536 was "
          "small-sample optimism; persistence above 1.5 + CI不重叠 = signal worth chasing.")


if __name__ == "__main__":
    main()
