# -*- coding: utf-8 -*-
"""crisis-concentration lens 审计：去掉危机期 edge 还显著？

关键测试：
1. 复现 crisis/bull/bear/range 分层数字（验证报告数字）
2. 去掉 crisis picks → 非危机期 BHAR + verdict（§44 v3 全套）
3. 危机期贡献占比（n_picks / n_days / 总 alpha 贡献）
4. 危机期是均值回归（NAV 跳变）还是 ETF 收敛 alpha（d_exit - d_entry）
5. 非危机期 walk-forward OOS 是否仍显著
6. 逐 crisis window 拆解：哪个危机窗口贡献最多
"""

from __future__ import annotations
import json
import sys
import statistics
from collections import defaultdict
from pathlib import Path
from math import sqrt, erf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._factor_helpers import ev_stats, day_paired_t, bonferroni_p, walk_forward, ALPHA

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
ETF_CACHE = DATA / "etf_premium_cache.json"
INDEX_CACHE = DATA / "index_ohlc_cache.json"

ETF_COST = 0.15

CRISIS_WINDOWS = [
    ("2008-GFC", "2008-01-01", "2009-03-31"),
    ("2015-崩盘", "2015-06-01", "2016-02-29"),
    ("2018-贸易战", "2018-03-01", "2019-01-31"),
    ("2020-COVID", "2020-02-01", "2020-04-30"),
    ("2024-1月崩盘", "2024-01-01", "2024-03-31"),
]


def load_etf_data():
    with open(ETF_CACHE) as f:
        return json.load(f)


def load_index():
    with open(INDEX_CACHE) as f:
        raw = json.load(f)
    bars = raw.get("sh.000001", [])
    return {b["date"]: b for b in bars if "date" in b}


def build_calendar(etf_data):
    all_dates = set()
    for days in etf_data.values():
        all_dates.update(days.keys())
    return sorted(all_dates)


def is_yizi_etf_proxy(t1_open, t_close):
    if t_close <= 0:
        return False
    return t1_open / t_close >= 1.099


def build_picks(etf_data, calendar, threshold=-0.3, hold_days=1):
    date_idx = {d: i for i, d in enumerate(calendar)}
    exit_offset = 1 + hold_days
    picks = []
    for code, days in etf_data.items():
        for d, b in days.items():
            nav_signal = b.get("nav")
            close_signal = b.get("close")
            if nav_signal is None or nav_signal <= 0 or close_signal is None:
                continue
            disc = (close_signal - nav_signal) / nav_signal * 100
            if disc >= threshold:
                continue
            di = date_idx.get(d)
            if di is None or di + exit_offset >= len(calendar):
                continue
            t1_date = calendar[di + 1]
            exit_date = calendar[di + exit_offset]
            t1 = days.get(t1_date)
            ex = days.get(exit_date)
            if t1 is None or ex is None:
                continue
            entry = t1.get("open")
            exit_close = ex.get("close")
            nav_t1 = t1.get("nav")
            nav_exit = ex.get("nav")
            if None in (entry, exit_close, nav_t1, nav_exit):
                continue
            if entry <= 0 or exit_close <= 0 or nav_t1 <= 0 or nav_exit <= 0:
                continue
            if is_yizi_etf_proxy(entry, close_signal):
                continue
            picks.append(
                {
                    "code": code,
                    "signal_date": d,
                    "t1_date": t1_date,
                    "exit_date": exit_date,
                    "hold_days": hold_days,
                    "discount_t": disc,
                    "entry": entry,
                    "exit_close": exit_close,
                    "nav_signal": nav_signal,
                    "nav_t1": nav_t1,
                    "nav_exit": nav_exit,
                    "zt_date": d,
                }
            )
    return picks


def bhar_corrected(p):
    d_entry = (p["entry"] - p["nav_signal"]) / p["nav_signal"] * 100
    d_exit = (p["exit_close"] - p["nav_exit"]) / p["nav_exit"] * 100
    return d_exit - d_entry


def bhar_r1(p):
    price_ret = (p["exit_close"] - p["entry"]) / p["entry"] * 100
    nav_ret = (p["nav_exit"] - p["nav_t1"]) / p["nav_t1"] * 100
    return price_ret - nav_ret


def raw_ev(p):
    return (p["exit_close"] - p["entry"]) / p["entry"] * 100


def classify_regime(date, index_map, idx_dates_sorted):
    for label, lo, hi in CRISIS_WINDOWS:
        if lo <= date <= hi:
            return "crisis"
    lo_i, hi_i = 0, len(idx_dates_sorted)
    di = None
    while lo_i < hi_i:
        mid = (lo_i + hi_i) // 2
        if idx_dates_sorted[mid] <= date:
            di = mid
            lo_i = mid + 1
        else:
            hi_i = mid
    if di is None or di < 60:
        return "range"
    start_date = idx_dates_sorted[di - 60]
    end_date = idx_dates_sorted[di]
    s = index_map.get(start_date, {}).get("close")
    e = index_map.get(end_date, {}).get("close")
    if s is None or e is None or s <= 0:
        return "range"
    ret60 = (e - s) / s
    if ret60 > 0.05:
        return "bull"
    if ret60 < -0.05:
        return "bear"
    return "range"


def crisis_window_of(date):
    for label, lo, hi in CRISIS_WINDOWS:
        if lo <= date <= hi:
            return label
    return None


def verdict_subset(name, picks, n_cross=3 * 5, ret_fn=bhar_corrected):
    """§44 v3 verdict on a subset of picks using corrected BHAR."""
    if not picks:
        print(f"  {name}: 无 picks")
        return {"name": name, "n": 0}
    rets = [ret_fn(p) for p in picks]
    s = ev_stats(rets)
    by_date = defaultdict(list)
    for p in picks:
        by_date[p["signal_date"]].append(ret_fn(p))
    dt = day_paired_t(by_date)
    wf = walk_forward(picks, ret_fn)
    n_tests = max(2, n_cross * 2)
    p_bonf = bonferroni_p(dt["p_one_sided"], n_tests)
    net = s["ev"] - ETF_COST

    wf_status = wf.get("status", "no_picks")
    wf_train_ev = wf.get("train_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
    wf_test_ev = wf.get("test_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
    wf_test_p = wf.get("test_day_t", {}).get("p_one_sided", 1.0) if wf_status == "ok" else 1.0
    wf_test_p_bonf = bonferroni_p(wf_test_p, n_tests) if wf_status == "ok" else 1.0

    # verdict cascade (matches helper.verdict_for)
    if s["ev"] < 0:
        v = "falsified (gross<0)"
    elif dt["n_days"] < 60:
        v = f"underpowered (n_days={dt['n_days']}<60)"
    elif p_bonf >= ALPHA:
        v = f"falsified (Bonf p={p_bonf:.6f}>=0.05)"
    elif net <= 0:
        v = f"falsified (net={net:.4f}<=0)"
    elif wf_status == "ok":
        if wf_train_ev <= 0:
            v = f"exploratory (train_ev={wf_train_ev}<=0)"
        elif wf_test_ev <= 0:
            v = f"falsified (wf test_ev={wf_test_ev}<=0)"
        elif wf_test_p_bonf >= ALPHA:
            v = f"exploratory (wf test_p Bonf={wf_test_p_bonf}>=0.05)"
        else:
            v = "edge-confirmed"
    else:
        v = f"exploratory (wf {wf_status})"

    print(f"\n  {name}: n={len(picks)} n_days={dt['n_days']}")
    print(
        f"    修正 BHAR: gross={s['ev']:+.4f}% net={net:+.4f}% day_t={dt['t']} "
        f"p_raw={dt['p_one_sided']} Bonf(×{n_tests})={p_bonf:.6f} WR={s['wr']}%"
    )
    if wf_status == "ok":
        print(
            f"    walk-forward: train={wf_train_ev:+.4f}% test={wf_test_ev:+.4f}% "
            f"test_p={wf_test_p} test_p_Bonf={wf_test_p_bonf:.6f} "
            f"n_train_dates={wf['n_train_dates']} n_test_dates={wf['n_test_dates']}"
        )
    print(f"    VERDICT: {v}")
    return {
        "name": name,
        "n": len(picks),
        "n_days": dt["n_days"],
        "gross": s["ev"],
        "net": net,
        "t": dt["t"],
        "p_raw": dt["p_one_sided"],
        "p_bonf": p_bonf,
        "wr": s["wr"],
        "wf": wf,
        "verdict": v,
        "wf_train_ev": wf_train_ev,
        "wf_test_ev": wf_test_ev,
        "wf_test_p": wf_test_p,
        "wf_test_p_bonf": wf_test_p_bonf,
    }


def main():
    print("=" * 78)
    print("crisis-concentration lens 审计：去掉危机期 edge 还显著？")
    print("=" * 78)

    etf_data = load_etf_data()
    index_map = load_index()
    calendar = build_calendar(etf_data)
    idx_dates_sorted = sorted(index_map.keys())
    print(f"\n[数据] {len(etf_data)} ETFs, calendar {calendar[0]}~{calendar[-1]} ({len(calendar)} dates)")

    picks = build_picks(etf_data, calendar, -0.3, hold_days=1)
    print(f"[picks] 全样本 disc<-0.3% 1d: n={len(picks)}")

    # tag regime + crisis window
    for p in picks:
        p["regime"] = classify_regime(p["signal_date"], index_map, idx_dates_sorted)
        p["crisis_window"] = crisis_window_of(p["signal_date"])

    by_regime = defaultdict(list)
    for p in picks:
        by_regime[p["regime"]].append(p)
    print(
        f"[regime] bull={len(by_regime['bull'])} bear={len(by_regime['bear'])} "
        f"range={len(by_regime['range'])} crisis={len(by_regime['crisis'])}"
    )

    # ============ 1. 复现 regime 分层数字 ============
    print("\n" + "=" * 78)
    print("1. 复现 regime 分层（修正 BHAR，验证报告数字）")
    print("=" * 78)
    regime_res = {}
    for rname in ("bull", "bear", "range", "crisis"):
        regime_res[rname] = verdict_subset(f"regime={rname}", by_regime[rname])

    # ============ 2. 去掉危机期 → 非危机 verdict ============
    print("\n" + "=" * 78)
    print("2. 关键测试：去掉危机期 → 非危机期 verdict（§44 v3 全套）")
    print("=" * 78)
    non_crisis = [p for p in picks if p["regime"] != "crisis"]
    crisis = by_regime["crisis"]
    print(f"  非危机 picks n={len(non_crisis)}  危机 picks n={len(crisis)} (危机占比 {len(crisis) / len(picks) * 100:.1f}%)")

    res_full = verdict_subset("全样本(含危机)", picks)
    res_noncrisis = verdict_subset("非危机期(bull+bear+range)", non_crisis)
    res_crisis = verdict_subset("危机期", crisis)

    # ============ 3. 危机贡献占比 ============
    print("\n" + "=" * 78)
    print("3. 危机期贡献占比（n_picks / n_days / 总 alpha 贡献）")
    print("=" * 78)
    full_alpha = sum(bhar_corrected(p) for p in picks)
    crisis_alpha = sum(bhar_corrected(p) for p in crisis)
    noncrisis_alpha = sum(bhar_corrected(p) for p in non_crisis)
    crisis_days = len(set(p["signal_date"] for p in crisis))
    noncrisis_days = len(set(p["signal_date"] for p in non_crisis))
    full_days = len(set(p["signal_date"] for p in picks))
    print(f"  总 alpha (sum BHAR): {full_alpha:+.2f}%")
    print(f"    危机贡献: {crisis_alpha:+.2f}% ({crisis_alpha / full_alpha * 100 if full_alpha else 0:.1f}% of total)")
    print(f"    非危机贡献: {noncrisis_alpha:+.2f}% ({noncrisis_alpha / full_alpha * 100 if full_alpha else 0:.1f}% of total)")
    print(
        f"  n_picks: 危机 {len(crisis)} ({len(crisis) / len(picks) * 100:.1f}%) / "
        f"非危机 {len(non_crisis)} ({len(non_crisis) / len(picks) * 100:.1f}%)"
    )
    print(
        f"  n_days: 危机 {crisis_days} ({crisis_days / full_days * 100:.1f}%) / "
        f"非危机 {noncrisis_days} ({noncrisis_days / full_days * 100:.1f}%)"
    )
    print(f"  per-pick alpha: 危机 {crisis_alpha / max(len(crisis), 1):+.4f}% / 非危机 {noncrisis_alpha / max(len(non_crisis), 1):+.4f}%")

    # ============ 4. 危机是均值回归 vs ETF 收敛 alpha ============
    print("\n" + "=" * 78)
    print("4. 危机期：均值回归（NAV 跳变）vs ETF 收敛 alpha（d_exit - d_entry）")
    print("=" * 78)
    # 折价是否真的收敛：d_entry vs d_exit
    print("  危机期 d_entry(入场折价) vs d_exit(出场折价)：")
    d_entries_c = [(p["entry"] - p["nav_signal"]) / p["nav_signal"] * 100 for p in crisis]
    d_exits_c = [(p["exit_close"] - p["nav_exit"]) / p["nav_exit"] * 100 for p in crisis]
    print(f"    d_entry mean={statistics.mean(d_entries_c):+.4f}% median={statistics.median(d_entries_c):+.4f}%")
    print(f"    d_exit  mean={statistics.mean(d_exits_c):+.4f}% median={statistics.median(d_exits_c):+.4f}%")
    print(f"    收敛量 d_exit-d_entry mean={statistics.mean(d_exits_c) - statistics.mean(d_entries_c):+.4f}%")
    # raw EV vs BHAR in crisis：raw EV 高 = NAV 本身涨（市场反弹）非收敛
    raw_c = [raw_ev(p) for p in crisis]
    bhar_c = [bhar_corrected(p) for p in crisis]
    nav_c = [(p["nav_exit"] - p["nav_t1"]) / p["nav_t1"] * 100 for p in crisis]
    print(f"  危机期 raw EV (散户实际) mean={statistics.mean(raw_c):+.4f}%")
    print(f"  危机期 NAV return mean={statistics.mean(nav_c):+.4f}% (市场反弹成分)")
    print(f"  危机期 修正 BHAR mean={statistics.mean(bhar_c):+.4f}% (收敛 alpha, beta-neutral)")
    print(
        f"  → raw EV {statistics.mean(raw_c):+.4f}% vs BHAR {statistics.mean(bhar_c):+.4f}%: "
        f"{'raw>>BHAR=市场反弹主导非收敛' if statistics.mean(raw_c) > statistics.mean(bhar_c) + 0.1 else 'raw≈BHAR=收敛主导'}"
    )
    # 非危机对比
    raw_nc = [raw_ev(p) for p in non_crisis]
    bhar_nc = [bhar_corrected(p) for p in non_crisis]
    nav_nc = [(p["nav_exit"] - p["nav_t1"]) / p["nav_t1"] * 100 for p in non_crisis]
    print(
        f"\n  非危机 raw EV mean={statistics.mean(raw_nc):+.4f}% NAV ret={statistics.mean(nav_nc):+.4f}% "
        f"BHAR={statistics.mean(bhar_nc):+.4f}%"
    )

    # ============ 5. 非危机 walk-forward ============
    print("\n" + "=" * 78)
    print("5. 非危机期 walk-forward OOS 是否仍显著")
    print("=" * 78)
    # 已在 res_noncrisis 里算，这里详打
    wf_nc = res_noncrisis["wf"]
    if wf_nc["status"] == "ok":
        print(
            f"  非危机 train_ev={res_noncrisis['wf_train_ev']:+.4f}% "
            f"test_ev={res_noncrisis['wf_test_ev']:+.4f}% "
            f"test_p={res_noncrisis['wf_test_p']} "
            f"test_p_Bonf={res_noncrisis['wf_test_p_bonf']:.6f}"
        )
        print(f"  n_train_dates={wf_nc['n_train_dates']} n_test_dates={wf_nc['n_test_dates']}")
    else:
        print(f"  walk-forward status={wf_nc['status']}")

    # ============ 6. 逐 crisis window 拆解 ============
    print("\n" + "=" * 78)
    print("6. 逐 crisis window 拆解：哪个危机窗口贡献最多")
    print("=" * 78)
    by_cw = defaultdict(list)
    for p in crisis:
        by_cw[p["crisis_window"]].append(p)
    print(f"{'crisis_window':<16} {'n':>6} {'n_days':>7} {'BHAR%':>9} {'net%':>8} {'rawEV%':>8} {'NAVret%':>8}")
    for cw, cwp in sorted(by_cw.items(), key=lambda x: -len(x[1])):
        bh = [bhar_corrected(p) for p in cwp]
        rv = [raw_ev(p) for p in cwp]
        nv = [(p["nav_exit"] - p["nav_t1"]) / p["nav_t1"] * 100 for p in cwp]
        s = ev_stats(bh)
        nd = len(set(p["signal_date"] for p in cwp))
        print(f"{cw:<16} {len(cwp):>6} {nd:>7} {s['ev']:>+9} {s['ev'] - ETF_COST:>+8} {statistics.mean(rv):>+8} {statistics.mean(nv):>+8}")

    # ============ 7. 非危机按 era 再拆（看非危机是否只是早期年代撑） ============
    print("\n" + "=" * 78)
    print("7. 非危机按 era 拆（看非危机 edge 是否被早期年代撑）")
    print("=" * 78)
    eras = [
        ("2005-2014 (早期)", "2005-01-01", "2014-12-31"),
        ("2015-2019", "2015-01-01", "2019-12-31"),
        ("2020-2022", "2020-01-01", "2022-12-31"),
        ("2023-2026 (近期)", "2023-01-01", "2026-12-31"),
    ]
    for label, lo, hi in eras:
        era_picks = [p for p in non_crisis if lo <= p["signal_date"] <= hi]
        if not era_picks:
            print(f"  {label}: 无 picks")
            continue
        bh = [bhar_corrected(p) for p in era_picks]
        s = ev_stats(bh)
        by_date = defaultdict(list)
        for p in era_picks:
            by_date[p["signal_date"]].append(bhar_corrected(p))
        dt = day_paired_t(by_date)
        print(
            f"  {label}: n={len(era_picks)} n_days={dt['n_days']} "
            f"BHAR={s['ev']:+.4f}% net={s['ev'] - ETF_COST:+.4f}% "
            f"day_t={dt['t']} p={dt['p_one_sided']}"
        )

    # ============ 8. 去掉危机 + 去掉早期 (2015+) 看近期非危机 ============
    print("\n" + "=" * 78)
    print("8. 非危机 + 仅 2015+（去掉早期低效市场年代）")
    print("=" * 78)
    noncrisis_2015 = [p for p in non_crisis if p["signal_date"] >= "2015-01-01"]
    verdict_subset("非危机 2015+", noncrisis_2015)

    # ============ 总结 ============
    print("\n" + "=" * 78)
    print("LENS 总结")
    print("=" * 78)
    print(f"全样本 verdict: {res_full['verdict']}")
    print(f"非危机 verdict: {res_noncrisis['verdict']}")
    print(f"危机 verdict:   {res_crisis['verdict']}")
    print(f"危机 alpha 贡献占比: {crisis_alpha / full_alpha * 100 if full_alpha else 0:.1f}%")
    print(f"危机 n_picks 占比: {len(crisis) / len(picks) * 100:.1f}%")
    print(f"危机 n_days 占比: {crisis_days / full_days * 100:.1f}%")


if __name__ == "__main__":
    main()
