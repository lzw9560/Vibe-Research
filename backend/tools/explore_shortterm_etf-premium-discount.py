# -*- coding: utf-8 -*-
"""ETF 折溢价套利探索——机制套利域（非动量非打板）。

机制：ETF 二级市场价格 vs 基金净值（NAV）的偏离（折价/溢价）。
- 真套利：折价买入 + 申赎换篮子 → T+0 无风险收敛。但散户申赎门槛高（creation unit
  50万-100万份，~50-200万资金），且跨境 QDII 申赎常暂停。散户结构性不可行（纯套利子策略）。
- 统计版（本测）：折价日 T 收盘买（信号 = close_T vs nav_T，nav_T 当晚公告，T+1 开盘可交易），
  T+2 收盘卖。若折价收敛（price → NAV），alpha = price_return - nav_return > 0。

机制独立性：跨市场 primary/secondary 定价错误，非涨停/动量/RSI/竞价——genuinely different。

数据源（实测可用，非臆测）：
- fund_etf_hist_sina（新浪源，非东财，不封 IP）：ETF 二级市场日 OHLC
- fund_open_fund_info_em（东财 datacenter，单 ETF 历史净值）：NAV 时间序列
- fund_etf_fund_daily_em：全市场 ETF 最新 2 日 NAV+市价+折价率（仅快照，无历史）

look-ahead 核查：discount_T = (close_T - nav_T)/nav_T。nav_T 是 T 日收盘净值，
基金公司 T 日收盘后 ~17:00 公告。entry = T+1 open（nav_T 已知，无 look-ahead）。

口径（§44 v3）：
- close_ev（T+1 open 买 → T+2 close 卖，非 open_ev 防日内泄漏）
- BHAR：alpha = price_return - nav_return（NAV 自身做 benchmark，隔离收敛 alpha vs 市场 beta）
- per-day-mean t（同日多 ETF 折价聚成 day-mean）
- Bonferroni ×5（cross-strategy，机制套利域并行 5 策略）+ ×3（within-family 3 阈值变体）
- walk-forward OOS + train_ev>0
- ETF 成本 0.15%（免印花税，佣金 ~0.06% 往返 + 滑点 ~0.09%）

诚实约束：
- 跨境 QDII ETF（日经/中韩半导体等）申赎常暂停 → 折价持久不收敛 → 排除（不同 regime）
- 仅测国内权益 ETF（申赎可用，折价应收敛——这是可证伪假设）
- 若数据 blocked 报 no-data 不臆造；禁止外推
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from collections import defaultdict
from math import sqrt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import akshare as ak

from tools._factor_helpers import (
    ev_stats, day_paired_t, bonferroni_p, walk_forward, verdict_for,
    norm_sf_positive, ALPHA,
)

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
CACHE = DATA / "etf_premium_cache.json"

ETF_COST = 0.15  # ETF round-trip cost % (免印花税, 佣金~0.06% + 滑点~0.09%)
N_CROSS_STRATEGY = 5   # 机制套利域并行 5 策略 cross-strategy Bonferroni
N_FAMILY_VARIANTS = 3  # within-script 3 阈值变体 family Bonferroni

# 国内权益 ETF（申赎可用，折价应收敛——可证伪假设）
ETF_UNIVERSE = {
    "510300": "沪深300ETF", "510050": "上证50ETF", "159915": "创业板ETF",
    "510500": "中证500ETF", "510880": "红利ETF", "512890": "红利低波ETF",
    "512100": "中证1000ETF", "588000": "科创50ETF", "159901": "深100ETF",
    "510310": "价值ETF", "159955": "中小盘ETF", "512760": "半导体ETF",
    "159995": "芯片ETF", "515790": "光伏ETF", "512660": "军工ETF",
}


def fetch_etf(code: str) -> dict:
    """取单 ETF：OHLC（sina）+ NAV（em datacenter）。返回 {date: {open,close,nav}}."""
    prefix = "sh" if code.startswith("5") else "sz"
    ohlc = ak.fund_etf_hist_sina(symbol=prefix + code)
    nav = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
    ohlc["date"] = ohlc["date"].astype(str)
    nav["净值日期"] = nav["净值日期"].astype(str)
    nav_map = {r["净值日期"]: float(r["单位净值"]) for _, r in nav.iterrows()}
    out: dict[str, dict] = {}
    for _, r in ohlc.iterrows():
        d = r["date"]
        nav_v = nav_map.get(d)
        if nav_v is None or nav_v <= 0:
            continue
        try:
            o = float(r["open"]); c = float(r["close"])
        except (ValueError, TypeError):
            continue
        if o <= 0 or c <= 0:
            continue
        out[d] = {"open": o, "close": c, "nav": nav_v}
    return out


def load_all_etfs() -> dict[str, dict[str, dict]]:
    """取全 universe，带缓存。返回 {code: {date: {open,close,nav}}}."""
    if CACHE.exists():
        with open(CACHE) as f:
            cache = json.load(f)
        if set(cache.keys()) == set(ETF_UNIVERSE.keys()):
            print(f"[cache hit] {len(cache)} ETFs loaded from {CACHE.name}")
            return cache
    cache: dict[str, dict[str, dict]] = {}
    for code, name in ETF_UNIVERSE.items():
        t0 = time.time()
        try:
            d = fetch_etf(code)
            cache[code] = d
            print(f"  fetched {code} {name}: {len(d)} days  ({time.time()-t0:.1f}s)")
        except Exception as e:
            print(f"  FAIL {code} {name}: {type(e).__name__} {str(e)[:80]}")
    with open(CACHE, "w") as f:
        json.dump(cache, f)
    print(f"[cached] {len(cache)} ETFs -> {CACHE.name}")
    return cache


def build_calendar(etf_data: dict[str, dict[str, dict]]) -> list[str]:
    all_dates: set[str] = set()
    for days in etf_data.values():
        all_dates.update(days.keys())
    return sorted(all_dates)


def discount_for(code: str, date: str, etf_data: dict) -> float | None:
    """T 日折价率% = (close - nav)/nav * 100."""
    days = etf_data.get(code, {})
    b = days.get(date)
    if b is None:
        return None
    if b["nav"] <= 0:
        return None
    return (b["close"] - b["nav"]) / b["nav"] * 100


def build_picks(
    etf_data: dict[str, dict[str, dict]],
    calendar: list[str],
    threshold: float,
) -> list[dict]:
    """折价 < threshold 的日 → pick。entry=T+1 open, exit=T+2 close.

    返回 pick 含 signal_date/code/discount/entry(t1_open)/t2_close/nav_t1/nav_t2.
    跳过：无 T+1/T+2 bar / nav<=0 / open<=0.
    """
    date_idx = {d: i for i, d in enumerate(calendar)}
    picks: list[dict] = []
    for code, days in etf_data.items():
        for d, b in days.items():
            disc = (b["close"] - b["nav"]) / b["nav"] * 100
            if disc >= threshold:  # threshold 是负数，disc < threshold 才纳入
                continue
            di = date_idx.get(d)
            if di is None or di + 2 >= len(calendar):
                continue
            t1_date = calendar[di + 1]
            t2_date = calendar[di + 2]
            t1 = days.get(t1_date)
            t2 = days.get(t2_date)
            if t1 is None or t2 is None:
                continue
            entry = t1["open"]
            t2_close = t2["close"]
            nav_t1 = t1["nav"]
            nav_t2 = t2["nav"]
            if entry <= 0 or t2_close <= 0 or nav_t1 <= 0 or nav_t2 <= 0:
                continue
            picks.append({
                "code": code,
                "signal_date": d,
                "t1_date": t1_date,
                "t2_date": t2_date,
                "discount_t": disc,
                "entry": entry,
                "t2_close": t2_close,
                "nav_t1": nav_t1,
                "nav_t2": nav_t2,
                # 兼容 helper.walk_forward（它用 zt_date 排序）
                "zt_date": d,
            })
    return picks


def raw_ev(p: dict) -> float:
    """ETF 二级市场价 raw 收益%：T+1 open 买 → T+2 close 卖。"""
    return (p["t2_close"] - p["entry"]) / p["entry"] * 100


def bhar(p: dict) -> float:
    """BHAR alpha% = price_return - nav_return（NAV 自身做 benchmark，隔离收敛 alpha）.

    price_return = (t2_close - t1_open)/t1_open
    nav_return = (nav_t2 - nav_t1)/nav_t1  （T+1 close nav → T+2 close nav，匹配持仓期）
    若折价收敛 → price 涨快于 nav（或跌慢于 nav）→ bhar>0.
    """
    price_ret = (p["t2_close"] - p["entry"]) / p["entry"] * 100
    nav_ret = (p["nav_t2"] - p["nav_t1"]) / p["nav_t1"] * 100
    return price_ret - nav_ret


def analyze_variant(name: str, picks: list[dict], threshold: float) -> dict:
    print(f"\n{'=' * 72}")
    print(f"变体: {name} (disc < {threshold}%)  n_picks={len(picks)}")
    print(f"{'=' * 72}")
    if not picks:
        print("  无 picks")
        return {"name": name, "n": 0}

    # ---- raw EV (ETF 二级市场价 raw 收益) ----
    raw_rets = [raw_ev(p) for p in picks]
    raw_s = ev_stats(raw_rets)
    print(f"\n--- raw EV (二级市场价收益, T+1 open→T+2 close) ---")
    print(f"  n={raw_s['n']} gross_EV={raw_s['ev']}% std={raw_s['std']}% "
          f"WR={raw_s['wr']}% t={raw_s['t']} CI[{raw_s['ci_lo']},{raw_s['ci_hi']}]")
    raw_net = raw_s["ev"] - ETF_COST
    print(f"  net EV (after {ETF_COST}% ETF cost): {raw_net:.3f}%")
    raw_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        raw_by_date[p["signal_date"]].append(raw_ev(p))
    raw_dt = day_paired_t(raw_by_date)
    print(f"  day-paired: n_days={raw_dt['n_days']} mean={raw_dt['mean']}% "
          f"t={raw_dt['t']} p_one_sided={raw_dt['p_one_sided']}")

    # ---- BHAR (alpha vs NAV) ----
    bhar_rets = [bhar(p) for p in picks]
    bhar_s = ev_stats(bhar_rets)
    print(f"\n--- BHAR alpha (price_return - nav_return, 折价收敛 alpha) ---")
    print(f"  n={bhar_s['n']} gross_BHAR={bhar_s['ev']}% std={bhar_s['std']}% "
          f"WR={bhar_s['wr']}% t={bhar_s['t']} CI[{bhar_s['ci_lo']},{bhar_s['ci_hi']}]")
    bhar_net = bhar_s["ev"] - ETF_COST
    print(f"  net BHAR (after {ETF_COST}% cost): {bhar_net:.3f}%")
    bhar_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        bhar_by_date[p["signal_date"]].append(bhar(p))
    bhar_dt = day_paired_t(bhar_by_date)
    print(f"  day-paired: n_days={bhar_dt['n_days']} mean={bhar_dt['mean']}% "
          f"t={bhar_dt['t']} p_one_sided={bhar_dt['p_one_sided']}")

    # ---- walk-forward (BHAR) ----
    print(f"\n--- walk-forward OOS (BHAR, 前半 train → 后半 test) ---")
    wf = walk_forward(picks, bhar)
    if wf["status"] == "ok":
        tr = wf["train_ev"]; te = wf["test_ev"]
        tr_dt = wf["train_day_t"]; te_dt = wf["test_day_t"]
        print(f"  train: n={tr['n']} n_dates={wf['n_train_dates']} "
              f"BHAR={tr['ev']}% t={tr['t']} day_t={tr_dt['t']}")
        print(f"  test:  n={te['n']} n_dates={wf['n_test_dates']} "
              f"BHAR={te['ev']}% t={te['t']} day_t={te_dt['t']} "
              f"p={te_dt['p_one_sided']}")
        decay = ((tr["ev"] - te["ev"]) / abs(tr["ev"]) * 100
                 if tr["ev"] != 0 else 0)
        print(f"  decay: {decay:.0f}% (train→test)")
    else:
        print(f"  {wf['status']} (n_dates={wf.get('n_dates', 0)})")

    # ---- verdict (on BHAR, the convergence alpha) ----
    wf_status = wf.get("status", "no_picks")
    wf_train_ev = wf.get("train_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
    wf_test_ev = wf.get("test_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
    wf_test_p = wf.get("test_day_t", {}).get("p_one_sided", 1.0) if wf_status == "ok" else 1.0

    # Bonferroni: cross-strategy ×5 AND within-family ×3 → 保守取乘积
    n_tests = N_CROSS_STRATEGY * N_FAMILY_VARIANTS
    print(f"\n--- verdict (BHAR alpha, Bonferroni ×{N_CROSS_STRATEGY}(cross-strat) "
          f"×{N_FAMILY_VARIANTS}(family) = ×{n_tests}) ---")
    v = verdict_for(
        ev_gross=bhar_s["ev"],
        t_day=bhar_dt["t"],
        p_raw=bhar_dt["p_one_sided"],
        wf_status=wf_status,
        wf_train_ev=wf_train_ev,
        wf_test_ev=wf_test_ev,
        wf_test_p=wf_test_p,
        n_days=bhar_dt["n_days"],
        net_ev=bhar_net,
        subset_name=name,
        n_cross_factor=n_tests,  # verdict_for 内部 ×2 subsets 也叠加
    )

    # 也对 raw EV 出一个 verdict（散户实际 P&L）
    print(f"\n--- verdict (raw EV, 散户实际 P&L, 同 Bonferroni) ---")
    v_raw = verdict_for(
        ev_gross=raw_s["ev"],
        t_day=raw_dt["t"],
        p_raw=raw_dt["p_one_sided"],
        wf_status=wf_status,
        wf_train_ev=wf_train_ev,  # raw 与 bhar 同期 split
        wf_test_ev=wf_test_ev,
        wf_test_p=wf_test_p,
        n_days=raw_dt["n_days"],
        net_ev=raw_net,
        subset_name=f"{name} (raw EV)",
        n_cross_factor=n_tests,
    )

    return {
        "name": name, "threshold": threshold, "n_picks": len(picks),
        "n_days": bhar_dt["n_days"],
        "raw_ev": raw_s, "raw_net": raw_net, "raw_day_t": raw_dt,
        "bhar": bhar_s, "bhar_net": bhar_net, "bhar_day_t": bhar_dt,
        "walk_forward": wf, "verdict_bhar": v, "verdict_raw": v_raw,
    }


def discount_autocorr(etf_data: dict) -> dict:
    """折价自相关诊断：ac1 高 → 折价持久（趋势，不收敛）→ 策略必败。
    ac1 低 → 折价回归 → 策略可能 work。per-ETF 算 ac1 取中位数。"""
    ac1s: list[float] = []
    for code, days in etf_data.items():
        ds = sorted(days.keys())
        discs = [((days[d]["close"] - days[d]["nav"]) / days[d]["nav"])
                 for d in ds if days[d]["nav"] > 0]
        if len(discs) < 30:
            continue
        mean = sum(discs) / len(discs)
        num = sum((discs[i] - mean) * (discs[i - 1] - mean)
                  for i in range(1, len(discs)))
        den = sum((x - mean) ** 2 for x in discs)
        if den > 0:
            ac1 = num / den
            ac1s.append(ac1)
    if not ac1s:
        return {"n_etfs": 0}
    ac1s.sort()
    n = len(ac1s)
    med = ac1s[n // 2]
    mean_ac1 = sum(ac1s) / n
    print(f"\n--- 折价自相关 ac1（持久 vs 回归诊断）---")
    print(f"  {n} ETFs: median ac1={med:.3f} mean ac1={mean_ac1:.3f} "
          f"min={ac1s[0]:.3f} max={ac1s[-1]:.3f}")
    if med > 0.8:
        print(f"  → ac1>0.8：折价持久（趋势），回归弱 → 策略先验负")
    elif med > 0.5:
        print(f"  → 0.5<ac1<0.8：折价半持久，部分回归 → 策略先验弱")
    else:
        print(f"  → ac1<0.5：折价回归倾向强 → 策略先验正")
    return {"n_etfs": n, "median_ac1": round(med, 3),
            "mean_ac1": round(mean_ac1, 3)}


def main() -> None:
    print("=" * 72)
    print("ETF 折溢价套利探索（机制套利域，非动量非打板）")
    print("=" * 72)

    print("\n[1] 取 ETF 数据（OHLC sina + NAV em datacenter）...")
    etf_data = load_all_etfs()
    n_etfs = len(etf_data)
    total_days = sum(len(v) for v in etf_data.values())
    print(f"  {n_etfs} ETFs, {total_days} total bar-days")

    # 数据可用性诚实标注
    print("\n[1a] 数据可用性（实测，非臆测）：")
    print("  - ETF OHLC（二级市场价）：fund_etf_hist_sina 新浪源 OK（非东财，不封 IP）")
    print("  - ETF NAV（基金净值）：fund_open_fund_info_em 东财 datacenter OK")
    print("  - IOPV（盘中实时参考净值）：无历史源（fund_etf_spot_em IP 封）")
    print("    → 本测用 end-of-day NAV（非 IOPV）。日级统计策略不需盘中 IOPV。")
    print("  - 真套利（申赎 T+0）：散户结构性不可行（creation unit 50-200万资金，")
    print("    跨境 QDII 申赎常暂停）。本测统计版（T+1 open 买 T+2 close 卖）散户可做。")
    print("  - 跨境 QDII ETF（日经/中韩半导体等）申赎暂停→折价持久→排除（不同 regime）")

    calendar = build_calendar(etf_data)
    print(f"\n  calendar: {len(calendar)} distinct dates "
          f"({calendar[0]} ~ {calendar[-1]})")

    # 折价自相关诊断
    ac = discount_autocorr(etf_data)

    # 全 universe 折价分布
    all_discs: list[float] = []
    for days in etf_data.values():
        for b in days.values():
            if b["nav"] > 0:
                all_discs.append((b["close"] - b["nav"]) / b["nav"] * 100)
    if all_discs:
        all_discs.sort()
        n = len(all_discs)
        med = all_discs[n // 2]
        p5 = all_discs[int(n * 0.05)]
        p95 = all_discs[int(n * 0.95)]
        print(f"\n  全 universe 折价分布: n={n} median={med:.3f}% "
              f"p5={p5:.3f}% p95={p95:.3f}%")
        print(f"  （median 略负 = 结构性——ETF 二级价小幅低于 NAV 因 creation cost/T+1）")

    # 3 阈值变体
    print("\n[2] 构建 picks + 分析（3 阈值变体，within-family Bonferroni ×3）...")
    variants = [
        ("disc<-0.3%", -0.3),
        ("disc<-0.5%", -0.5),
        ("disc<-1.0%", -1.0),
    ]
    results = []
    for name, thr in variants:
        picks = build_picks(etf_data, calendar, thr)
        r = analyze_variant(name, picks, thr)
        results.append(r)

    # ---- 汇总 ----
    print(f"\n\n{'=' * 72}")
    print("汇总（BHAR alpha = 折价收敛，隔离市场 beta）")
    print(f"{'=' * 72}")
    print(f"{'变体':<14} {'n':>6} {'n_days':>7} {'BHAR%':>8} {'net%':>7} "
          f"{'day_t':>7} {'p_raw':>9} {'wf_test%':>9} {'verdict':<16}")
    for r in results:
        if r.get("n_picks", 0) == 0:
            continue
        wf = r.get("walk_forward", {})
        wf_te = wf.get("test_ev", {}).get("ev", "-") if wf.get("status") == "ok" else "-"
        print(f"{r['name']:<14} {r['n_picks']:>6} {r['n_days']:>7} "
              f"{r['bhar']['ev']:>8} {r['bhar_net']:>7} "
              f"{r['bhar_day_t']['t']:>7} {r['bhar_day_t']['p_one_sided']:>9} "
              f"{str(wf_te):>9} {r['verdict_bhar']:<16}")

    print(f"\n{'=' * 72}")
    print("诚实总结")
    print(f"{'=' * 72}")
    bhar_verdicts = [r.get("verdict_bhar", "?") for r in results if r.get("n_picks", 0) > 0]
    raw_verdicts = [r.get("verdict_raw", "?") for r in results if r.get("n_picks", 0) > 0]
    print(f"BHAR alpha verdicts: {bhar_verdicts}")
    print(f"raw EV verdicts:     {raw_verdicts}")
    print(f"折价自相关 median ac1: {ac.get('median_ac1', 'n/a')} "
          f"({'持久' if ac.get('median_ac1', 0) > 0.8 else '部分回归' if ac.get('median_ac1', 0) > 0.5 else '回归倾向'})")

    # 最终判定：取最严变体（disc<-0.5%，平衡频率与信号强度）
    primary = next((r for r in results if r["name"] == "disc<-0.5%"), None)
    if primary and primary.get("n_picks", 0) > 0:
        final_v = primary["verdict_bhar"]
        final_ev = primary["bhar"]["ev"]
        print(f"\n主判定（disc<-0.5% BHAR）: verdict={final_v} gross_BHAR={final_ev}%")
        # 禁外推
        print("\n禁外推声明：本测仅覆盖 15 国内权益 ETF 的折价回归信号。")
        print("跨境 QDII/LOF/封基/期货基差未测。单策略结果 ≠ 机制套利域有/无 edge。")


if __name__ == "__main__":
    main()
