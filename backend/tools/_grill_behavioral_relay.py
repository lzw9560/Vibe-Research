# -*- coding: utf-8 -*-
"""行为金融角度 grill consecutive_relay 证否.

质疑点：-1.66% bull / -1.89% bear "definitive falsified" 假设连板接力人群同质。
行为金融预测：overreaction reversal / lottery preference / anchoring 是条件性的——
极端 attention + chasing gap + 小盘 lottery tail 可能拖垮整体，
而低 chase / 大盘 / 低 attention 子集可能中性甚至为正。

测试条件变量（V2 close_ev 口径 = helper 的 close_ev_basic：T+1 open 买 → T+2 close 卖）：
  1. gap_pct = (t1_open - t_close)/t_close  → anchoring/chasing（T+1 开盘溢价）
  2. lbc 高度 → attention extreme
  3. ltsz 市值 → lottery preference（小盘 = lottery）
  4. t 日内振幅 (high-low)/close → 波动率/lottery
  5. 是否 new theme（hybk 首次出现 vs 拥挤）

跑法: cd backend && .venv/bin/python tools/_grill_behavioral_relay.py
"""
from __future__ import annotations
import sys
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tools._factor_helpers import (  # noqa: E402
    load_kline_db, load_zt, build_picks_generic, close_ev_basic,
    close_ev_stop, ev_stats, day_paired_t, limit_for_code, is_yizi_t1,
)

ZT_DB = ROOT / ".vibe-research" / "zt_history.db"


def load_zt_with_meta() -> list[dict]:
    """zt_history with lbc/hybk/ltsz/zbc(封单成交比)/fund(资金净流入)."""
    conn = sqlite3.connect(str(ZT_DB))
    rows = []
    for r in conn.execute(
        "SELECT date, code, name, lbc, zbc, fund, zje, p, ltsz, fundamt, hybk, source "
        "FROM zt_history WHERE is_final=1 ORDER BY date"
    ):
        rows.append({
            "date": r[0], "code": r[1], "name": r[2], "lbc": r[3] or 1,
            "zbc": r[4], "fund": r[5], "zje": r[6], "p": r[7],
            "ltsz": r[8], "fundamt": r[9], "hybk": r[10], "source": r[11],
        })
    conn.close()
    return rows


def load_regime_labels() -> dict[str, str]:
    """从 gap_regime_stratified.compute_regime_labels 读 regime (bull/bear/range)."""
    try:
        from tools.gap_regime_stratified import compute_regime_labels  # noqa: PLC0415
        return compute_regime_labels()
    except Exception as e:
        print(f"[WARN] regime load failed: {e}")
        return {}


def norm_sf_positive(t: float) -> float:
    if t <= 0:
        return 1.0
    return 0.5 * (1 - erf(t / sqrt(2)))


def build_relay_picks_with_meta(code_map, calendar, zt_meta_rows):
    """lbc>=2 picks with behavioral meta. entry=T+1 open, exit=T+2 close.
    跳过 T+1 一字涨停。附加 gap_pct/lbc/ltsz/zbc/fund/hybk/t_amplitude."""
    date_idx = {d: i for i, d in enumerate(calendar)}
    meta_by_dc = {(r["date"], r["code"]): r for r in zt_meta_rows}
    picks = []
    for r in zt_meta_rows:
        if r["lbc"] < 2:
            continue
        zt_date, code = r["date"], r["code"]
        di = date_idx.get(zt_date)
        if di is None or di + 2 >= len(calendar):
            continue
        dmap = code_map.get(code)
        if not dmap:
            continue
        t_bar = dmap.get(zt_date)
        if t_bar is None or t_bar.get("close") is None:
            continue
        t_close = t_bar["close"]
        if t_close <= 0:
            continue
        t1_date = calendar[di + 1]
        t2_date = calendar[di + 2]
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
        # behavioral meta
        gap_pct = (t1_open - t_close) / t_close * 100  # T+1 open premium (chasing)
        t_high = t_bar.get("high") or t_close
        t_low = t_bar.get("low") or t_close
        t_ampl = (t_high - t_low) / t_close * 100 if t_close > 0 else 0.0
        ltsz_yi = (r["ltsz"] / 1e8) if r["ltsz"] else None
        picks.append({
            "code": code, "zt_date": zt_date, "t1_date": t1_date, "t2_date": t2_date,
            "entry": t1_open, "t_close": t_close, "t1_bar": t1_bar, "t2_bar": t2_bar,
            "lbc": r["lbc"], "gap_pct": gap_pct, "t_ampl": t_ampl,
            "ltsz_yi": ltsz_yi, "zbc": r["zbc"], "fund": r["fund"],
            "hybk": r["hybk"], "t_bar": t_bar,
        })
    return picks


def subset_stats(picks, ret_fn=close_ev_basic, cost_pct=0.3):
    rets = []
    by_date = defaultdict(list)
    for p in picks:
        r = ret_fn(p)
        if r is None:
            continue
        rets.append(r)
        by_date[p["zt_date"]].append(r)
    if not rets:
        return {"n": 0, "n_days": 0}
    s = ev_stats(rets)
    dt = day_paired_t(by_date)
    net = s["ev"] - cost_pct
    return {
        "n": s["n"], "n_days": dt["n_days"], "gross_ev": s["ev"], "net_ev": round(net, 3),
        "wr": s["wr"], "day_t": dt["t"], "p_one_sided": dt["p_one_sided"],
        "ci_lo": s["ci_lo"], "ci_hi": s["ci_hi"],
    }


def ps(x):
    if x.get("n", 0) == 0:
        return f"n=0"
    return (f"n={x['n']} days={x['n_days']} gross={x['gross_ev']}% "
            f"net={x['net_ev']}% WR={x['wr']}% day_t={x['day_t']} "
            f"p={x['p_one_sided']} CI[{x['ci_lo']},{x['ci_hi']}]")


def main():
    print("=" * 72)
    print("行为金融角度 grill consecutive_relay 证否 (-1.66% bull p=1.0 definitive)")
    print("=" * 72)

    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    zt_meta = load_zt_with_meta()
    regime = load_regime_labels()
    print(f"kline codes={len(code_map)} calendar_days={len(calendar)}")
    print(f"zt_meta rows={len(zt_meta)} (lbc>=2: {sum(1 for r in zt_meta if r['lbc']>=2)})")
    print(f"regime labels={len(regime)} "
          f"(bull={sum(1 for v in regime.values() if v=='bull')} "
          f"bear={sum(1 for v in regime.values() if v=='bear')})")

    picks = build_relay_picks_with_meta(code_map, calendar, zt_meta)
    print(f"\nrelay picks (lbc>=2, T+1 一字过滤后): {len(picks)}")
    if not picks:
        print("[FATAL] 无 picks")
        return

    # regime split
    bull = [p for p in picks if regime.get(p["zt_date"]) == "bull"]
    bear = [p for p in picks if regime.get(p["zt_date"]) == "bear"]
    rng = [p for p in picks if regime.get(p["zt_date"]) == "range"]
    print(f"  bull={len(bull)} bear={len(bear)} range={len(rng)} no_regime={len(picks)-len(bull)-len(bear)-len(rng)}")

    # ---- 1. 复现证否 (V2 close_ev basic) ----
    print("\n" + "=" * 72)
    print("1. 复现证否：V2 close_ev (T+1 open → T+2 close) lbc>=2 按 regime")
    print("=" * 72)
    print(f"  ALL:  {ps(subset_stats(picks))}")
    print(f"  BULL: {ps(subset_stats(bull))}")
    print(f"  BEAR: {ps(subset_stats(bear))}")
    print(f"  RANGE:{ps(subset_stats(rng))}")

    # ---- 2. lbc 高度 conditioning (attention extreme) ----
    print("\n" + "=" * 72)
    print("2. lbc 高度 conditioning（attention extreme：连板越高=attention 越极端）")
    print("   行为预测：若 overreaction reversal，高 lbc 应最负；低 lbc(2) 可能中性")
    print("=" * 72)
    for lbl, sub in [("lbc=2", [p for p in picks if p["lbc"] == 2]),
                     ("lbc=3", [p for p in picks if p["lbc"] == 3]),
                     ("lbc>=4", [p for p in picks if p["lbc"] >= 4]),
                     ("lbc>=6", [p for p in picks if p["lbc"] >= 6])]:
        print(f"  ALL {lbl}: {ps(subset_stats(sub))}")
    print("  --- bull only ---")
    for lbl, sub in [("lbc=2", [p for p in bull if p["lbc"] == 2]),
                     ("lbc=3", [p for p in bull if p["lbc"] == 3]),
                     ("lbc>=4", [p for p in bull if p["lbc"] >= 4])]:
        print(f"  BULL {lbl}: {ps(subset_stats(sub))}")

    # ---- 3. gap_pct conditioning (anchoring/chasing) ----
    print("\n" + "=" * 72)
    print("3. gap_pct conditioning（T+1 开盘溢价 = anchoring/chasing 强度）")
    print("   行为预测：高 gap=追涨 anchoring，应最负；低/负 gap 可能中性或正")
    print("=" * 72)
    gaps = sorted(p["gap_pct"] for p in picks)
    q25 = gaps[len(gaps) // 4]
    q50 = gaps[len(gaps) // 2]
    q75 = gaps[3 * len(gaps) // 4]
    print(f"  gap_pct quartiles: q25={q25:.2f}% q50={q50:.2f}% q75={q75:.2f}%")
    bins = [(-999, -1, "gap<-1% (低开/平开, 不追)"),
            (-1, 1, "-1%<=gap<1% (温和)"),
            (1, 3, "1%<=gap<3% (中追)"),
            (3, 999, "gap>=3% (高追 anchoring)")]
    for lo, hi, lbl in bins:
        sub = [p for p in picks if lo <= p["gap_pct"] < hi]
        print(f"  ALL {lbl}: {ps(subset_stats(sub))}")
    print("  --- bull only ---")
    for lo, hi, lbl in bins:
        sub = [p for p in bull if lo <= p["gap_pct"] < hi]
        print(f"  BULL {lbl}: {ps(subset_stats(sub))}")

    # ---- 4. ltsz conditioning (lottery preference) ----
    print("\n" + "=" * 72)
    print("4. ltsz 市值 conditioning（lottery preference：小盘=lottery，散户偏好）")
    print("   行为预测：小盘 lottery tail 拖垮；大盘可能中性")
    print("=" * 72)
    cap_bins = [(0, 50, "小盘<50亿 (lottery)"),
                (50, 200, "中盘50-200亿"),
                (200, 99999, "大盘>=200亿")]
    for lo, hi, lbl in cap_bins:
        sub = [p for p in picks if p["ltsz_yi"] is not None and lo <= p["ltsz_yi"] < hi]
        print(f"  ALL {lbl}: {ps(subset_stats(sub))}")
    print("  --- bull only ---")
    for lo, hi, lbl in cap_bins:
        sub = [p for p in bull if p["ltsz_yi"] is not None and lo <= p["ltsz_yi"] < hi]
        print(f"  BULL {lbl}: {ps(subset_stats(sub))}")

    # ---- 5. t_ampl conditioning (lottery/volatility) ----
    print("\n" + "=" * 72)
    print("5. T 日振幅 conditioning（lottery/volatility：高振幅=lottery）")
    print("=" * 72)
    ampls = sorted(p["t_ampl"] for p in picks)
    med_ampl = ampls[len(ampls) // 2]
    print(f"  median t_ampl={med_ampl:.2f}%")
    for lo, hi, lbl in [(0, med_ampl, f"低振幅<{med_ampl:.1f}%"),
                        (med_ampl, 999, f"高振幅>={med_ampl:.1f}%")]:
        sub = [p for p in picks if lo <= p["t_ampl"] < hi]
        print(f"  ALL {lbl}: {ps(subset_stats(sub))}")

    # ---- 6. new theme vs crowded (herd behavior) ----
    print("\n" + "=" * 72)
    print("6. new theme vs crowded（herd behavior：主题首次出现 vs 拥挤）")
    print("   行为预测：新主题 first-appearance 接力可能不反转；拥挤主题反转")
    print("=" * 72)
    # count hybk appearances by date
    theme_first_date = {}
    theme_count_by_date = defaultdict(lambda: defaultdict(int))
    for r in sorted(zt_meta, key=lambda x: x["date"]):
        if r["hybk"] and r["lbc"] >= 2:
            if r["hybk"] not in theme_first_date:
                theme_first_date[r["hybk"]] = r["date"]
            theme_count_by_date[r["date"]][r["hybk"]] += 1
    # for each pick, is it in a theme that's appearing for first time today (new)?
    # or is the theme already crowded (>=3 relays same day in same theme)?
    new_theme_picks = []
    crowded_picks = []
    for p in picks:
        hybk = p["hybk"]
        if not hybk:
            continue
        first = theme_first_date.get(hybk)
        same_day_theme_count = theme_count_by_date.get(p["zt_date"], {}).get(hybk, 0)
        if first == p["zt_date"] and same_day_theme_count <= 2:
            new_theme_picks.append(p)
        elif same_day_theme_count >= 3:
            crowded_picks.append(p)
    print(f"  ALL new-theme: {ps(subset_stats(new_theme_picks))}")
    print(f"  ALL crowded(>=3 same-day same-theme): {ps(subset_stats(crowded_picks))}")
    print("  --- bull only ---")
    print(f"  BULL new-theme: {ps(subset_stats([p for p in new_theme_picks if regime.get(p['zt_date'])=='bull']))}")
    print(f"  BULL crowded: {ps(subset_stats([p for p in crowded_picks if regime.get(p['zt_date'])=='bull']))}")

    # ---- 7. combined behavioral filter (low-chase + large/mid cap + low-mid lbc) ----
    print("\n" + "=" * 72)
    print("7. 组合行为过滤（低追 gap<1% + 中大盘>=50亿 + lbc<=3）")
    print("   测试：排除 behavioral-extreme tail 后核心是否中性")
    print("=" * 72)
    core = [p for p in picks if p["gap_pct"] < 1.0 and p["lbc"] <= 3
            and p["ltsz_yi"] is not None and p["ltsz_yi"] >= 50]
    print(f"  ALL core (low-chase+midcap+lbc<=3): {ps(subset_stats(core))}")
    print(f"  BULL core: {ps(subset_stats([p for p in core if regime.get(p['zt_date'])=='bull']))}")
    # even tighter: gap<=0 (no chase at all)
    ncore = [p for p in picks if p["gap_pct"] <= 0.0 and p["lbc"] <= 3
             and p["ltsz_yi"] is not None and p["ltsz_yi"] >= 50]
    print(f"  ALL no-chase core (gap<=0+midcap+lbc<=3): {ps(subset_stats(ncore))}")
    print(f"  BULL no-chase core: {ps(subset_stats([p for p in ncore if regime.get(p['zt_date'])=='bull']))}")

    # ---- 8. stop variant on core (does -3% stop rescue?) ----
    print("\n" + "=" * 72)
    print("8. -3% stop variant on core（止损能否救行为反转）")
    print("=" * 72)
    def stop_ret(p):
        r = close_ev_stop(p)
        return r[0] if r else None
    if core:
        print(f"  ALL core +stop: {ps(subset_stats(core, ret_fn=stop_ret))}")

    # ---- 9. zbc (封单成交比) conditioning if available ----
    print("\n" + "=" * 72)
    print("9. zbc 封单成交比 conditioning（封板强度：高 zbc=封单强=attention）")
    print("=" * 72)
    zbc_vals = [p["zbc"] for p in picks if p["zbc"] is not None and p["zbc"] > 0]
    if zbc_vals:
        zmed = statistics.median(zbc_vals)
        print(f"  zbc median={zmed:.2f} (n with zbc={len(zbc_vals)})")
        hi = [p for p in picks if p["zbc"] is not None and p["zbc"] >= zmed]
        lo = [p for p in picks if p["zbc"] is not None and p["zbc"] < zmed]
        print(f"  ALL high-zbc(>={zmed:.2f}): {ps(subset_stats(hi))}")
        print(f"  ALL low-zbc(<{zmed:.2f}): {ps(subset_stats(lo))}")
    else:
        print("  zbc 数据缺失")


if __name__ == "__main__":
    main()
