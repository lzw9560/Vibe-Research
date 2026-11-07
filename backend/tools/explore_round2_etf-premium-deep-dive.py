# -*- coding: utf-8 -*-
"""ETF 折溢价 Round 2 深挖——唯一 formal-pass 策略的 edge 消亡诊断。

Round 1 结论：disc<-0.3% 全样本 BHAR 0.379%/net 0.229% 过 7 门，但 2023-2026
BHAR=-0.075% 消失。本脚本深挖：

维度 1 — 结构断点（era split + 年度 BHAR 趋势 + breakpoint）：edge 消亡是
         市场效率提升（永久）还是周期性？
维度 2 — regime 分层（bull/bear/crisis via sh.000001）：edge 是否集中在 bear/危机？
维度 3 — 窗口对比（1d/2d/4d/5d hold）：长窗口能否捕获更慢的收敛？
维度 4 — 阈值分桶（<-0.3%/<-0.5%/<-1%/<-1.5%/<-2%）：更深折价=更多 edge（单调）？
维度 5 — ETF 类型分层（宽基 vs 行业/主题）：edge 是否集中某一类？
维度 6 — BHAR 口径修正（R1 beta 泄漏 vs 修正 beta-neutral 收敛 alpha）：
         R1 BHAR = price_ret(1.5d) - nav_ret(1d)，T+1 日内 beta 未扣除→通胀。
         修正 BHAR = (price/NAV at exit) - (price/NAV at entry)，纯收敛 beta-neutral。
维度 7 — 2023-2026 子条件 sweep（阈值×窗口×类型×regime）：
         近期数据是否有 ANY 子条件存活 §44 v3？

§44 v3 全套（ETF 适配）：
- realistic entry T+1 open（非 T 收盘，nav_T 当晚公告已知，无 look-ahead）
- close_ev 非 open_ev（T+1 open 买 → T+k close 卖，防日内泄漏）
- BHAR gate（NAV 自身 benchmark，隔离收敛 alpha vs 市场 beta）——核心
- per-day-mean t（同日多 ETF 聚 day-mean）
- Bonferroni ×3（Round 2 三策略并行：ETF 折溢价/大股东增持/跌停打开）
- walk-forward OOS + train_ev>0
- is_yizi ETF 代理（无 high/low，用 t1_open>=t_close*1.099 近似一字涨停买不进）
- R6 stop N/A（ETF 无 high/low 数据 + 收敛策略不用 stop）
- DSR/PBO：Bonferroni 已覆盖多重检验；event 策略 day-paired t 是主推断

诚实约束：
- ETF 无 high/low → R6 stop 不可算（收敛策略本不用 stop，N/A 非缺口）
- 跨境 QDII 已排除（申赎暂停，折价持久不收敛）
- 子条件 sweep 多重检验用 within-script Bonferroni 严控（防 p-hacking）
- 禁止外推：ETF 折溢价单策略 ≠ 机制套利域有/无 edge
"""
from __future__ import annotations
import json
import sys
import statistics
from collections import defaultdict
from pathlib import Path
from math import sqrt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._factor_helpers import (
    ev_stats, day_paired_t, bonferroni_p, walk_forward, verdict_for, ALPHA,
)

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
ETF_CACHE = DATA / "etf_premium_cache.json"
INDEX_CACHE = DATA / "index_ohlc_cache.json"

ETF_COST = 0.15  # ETF round-trip cost % (免印花税, 佣金~0.06% + 滑点~0.09%)
N_CROSS_STRATEGY = 3   # Round 2 三策略并行 cross-strategy Bonferroni
N_FAMILY_VARIANTS = 5  # within-script 5 阈值变体 family Bonferroni（维度 4）

# 国内权益 ETF universe（同 Round 1，跨境 QDII 排除）
ETF_UNIVERSE = {
    # 宽基指数（broad-base）
    "510300": ("沪深300ETF", "broad"), "510050": ("上证50ETF", "broad"),
    "510500": ("中证500ETF", "broad"), "510880": ("红利ETF", "broad"),
    "512890": ("红利低波ETF", "broad"), "512100": ("中证1000ETF", "broad"),
    "588000": ("科创50ETF", "broad"), "159901": ("深100ETF", "broad"),
    "510310": ("价值ETF", "broad"), "159955": ("中小盘ETF", "broad"),
    "159915": ("创业板ETF", "broad"),
    # 行业/主题（sector/theme）
    "512760": ("半导体ETF", "sector"), "159995": ("芯片ETF", "sector"),
    "515790": ("光伏ETF", "sector"), "512660": ("军工ETF", "sector"),
}

# 危机窗口（透明固定，非事后调参）
CRISIS_WINDOWS = [
    ("2008-GFC", "2008-01-01", "2009-03-31"),
    ("2015-崩盘", "2015-06-01", "2016-02-29"),
    ("2018-贸易战", "2018-03-01", "2019-01-31"),
    ("2020-COVID", "2020-02-01", "2020-04-30"),
    ("2024-1月崩盘", "2024-01-01", "2024-03-31"),
]


# ---------- data loading ----------

def load_etf_data() -> dict[str, dict[str, dict]]:
    with open(ETF_CACHE) as f:
        return json.load(f)


def load_index() -> dict[str, dict]:
    """sh.000001 → {date: bar}. 用于 regime 分层."""
    with open(INDEX_CACHE) as f:
        raw = json.load(f)
    bars = raw.get("sh.000001", [])
    return {b["date"]: b for b in bars if "date" in b}


def build_calendar(etf_data: dict[str, dict[str, dict]]) -> list[str]:
    all_dates: set[str] = set()
    for days in etf_data.values():
        all_dates.update(days.keys())
    return sorted(all_dates)


# ---------- pick construction (event-driven, configurable exit window) ----------

def is_yizi_etf_proxy(t1_open: float, t_close: float) -> bool:
    """ETF 一字涨停代理（无 high/low）：T+1 open 接近 +10% 涨停价 → 可能买不进.

    ETF 涨跌停 ±10%（跨境 QDII 已排除）。若 T+1 开盘价 >= T 收盘*1.099
    （开盘即在涨停价附近），保守跳过（可能封板买不进）。
    实测影响极小（ETF 极少一字涨停），但 §44 v3 严格要求。
    """
    if t_close <= 0:
        return False
    return t1_open / t_close >= 1.099


def build_picks_window(
    etf_data: dict[str, dict[str, dict]],
    calendar: list[str],
    threshold: float,
    hold_days: int = 1,
    etf_filter: set[str] | None = None,
    date_lo: str | None = None,
    date_hi: str | None = None,
) -> list[dict]:
    """折价 < threshold 的日 → pick. entry=T+1 open, exit=T+(1+hold_days) close.

    hold_days=1 → exit T+2 close（Round 1 口径）.
    hold_days=4 → exit T+5 close（~1 周）.
    etf_filter: 限定 ETF code 集合（None=全 universe）.
    date_lo/date_hi: 信号日范围（YYYY-MM-DD），用于 era/regime 分层.
    跳过：无 T+1..T+k bar / nav<=0 / open<=0 / 一字涨停代理.
    """
    date_idx = {d: i for i, d in enumerate(calendar)}
    exit_offset = 1 + hold_days  # hold_days=1 → exit at calendar[i+2]
    picks: list[dict] = []
    codes = etf_filter if etf_filter is not None else set(etf_data.keys())
    for code in codes:
        days = etf_data.get(code)
        if not days:
            continue
        for d, b in days.items():
            if date_lo and d < date_lo:
                continue
            if date_hi and d > date_hi:
                continue
            nav_signal = b.get("nav")
            close_signal = b.get("close")
            if nav_signal is None or nav_signal <= 0 or close_signal is None:
                continue
            disc = (close_signal - nav_signal) / nav_signal * 100
            if disc >= threshold:  # threshold 负，disc<threshold 才纳入
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
            # is_yizi ETF 代理（§44 v3）
            if is_yizi_etf_proxy(entry, close_signal):
                continue
            picks.append({
                "code": code,
                "signal_date": d,
                "t1_date": t1_date,
                "exit_date": exit_date,
                "hold_days": hold_days,
                "discount_t": disc,
                "entry": entry,
                "exit_close": exit_close,
                "nav_signal": nav_signal,  # T close NAV（信号时已知，无 look-ahead）
                "nav_t1": nav_t1,         # T+1 close NAV
                "nav_exit": nav_exit,     # T+k close NAV
                "zt_date": d,              # 兼容 helper.walk_forward 排序
            })
    return picks


# ---------- BHAR: R1 (beta-leak) vs corrected (beta-neutral) ----------

def bhar_r1(p: dict) -> float:
    """Round 1 BHAR = price_ret - nav_ret（有 T+1 日内 beta 泄漏）.

    price_ret = (exit_close - entry)/entry  [T+1 open → T+k close, ~k+0.5 日]
    nav_ret = (nav_exit - nav_t1)/nav_t1     [T+1 close → T+k close, ~k-1 日]
    窗口不对齐：price_ret 多含 T+1 日内 (open→close) beta，nav_ret 不含 → 通胀。
    """
    price_ret = (p["exit_close"] - p["entry"]) / p["entry"] * 100
    nav_ret = (p["nav_exit"] - p["nav_t1"]) / p["nav_t1"] * 100
    return price_ret - nav_ret


def bhar_corrected(p: dict) -> float:
    """修正 BHAR = (price/NAV at exit) - (price/NAV at entry)，纯收敛 beta-neutral.

    d_entry = (entry - nav_signal)/nav_signal  [nav_signal=T 收盘 NAV，信号时已知]
    d_exit = (exit_close - nav_exit)/nav_exit    [T+k 收盘]
    alpha = d_exit - d_entry  [discount 收窄→正 alpha，与市场方向无关]

    beta-neutral 证明：若市场涨 10%，price 与 NAV 同涨 10% → price/NAV 不变 → alpha=0。
    仅 discount 收敛移动 price/NAV ratio。这是收敛策略的诚实 alpha 口径。
    nav_signal 用 T 收盘 NAV（entry T+1 open 时已知，无 look-ahead）。
    """
    d_entry = (p["entry"] - p["nav_signal"]) / p["nav_signal"] * 100
    d_exit = (p["exit_close"] - p["nav_exit"]) / p["nav_exit"] * 100
    return d_exit - d_entry


def raw_ev(p: dict) -> float:
    """散户实际 P&L% = (exit_close - entry)/entry（含市场 beta，非 alpha）."""
    return (p["exit_close"] - p["entry"]) / p["entry"] * 100


# ---------- analysis (per subset, both BHAR calibers) ----------

def analyze_subset(name: str, picks: list[dict], verbose: bool = True) -> dict:
    """对一个子集跑 R1 + 修正 BHAR 全分析."""
    if not picks:
        if verbose:
            print(f"  {name}: 无 picks")
        return {"name": name, "n": 0}

    # R1 BHAR
    r1_rets = [bhar_r1(p) for p in picks]
    r1_s = ev_stats(r1_rets)
    r1_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        r1_by_date[p["signal_date"]].append(bhar_r1(p))
    r1_dt = day_paired_t(r1_by_date)

    # 修正 BHAR
    cor_rets = [bhar_corrected(p) for p in picks]
    cor_s = ev_stats(cor_rets)
    cor_by_date: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        cor_by_date[p["signal_date"]].append(bhar_corrected(p))
    cor_dt = day_paired_t(cor_by_date)

    # walk-forward on 修正 BHAR（主口径）
    wf = walk_forward(picks, bhar_corrected)

    # raw EV（散户实际 P&L）
    raw_rets = [raw_ev(p) for p in picks]
    raw_s = ev_stats(raw_rets)

    if verbose:
        print(f"\n  {name}: n={len(picks)} n_days={cor_dt['n_days']}")
        print(f"    R1 BHAR:    gross={r1_s['ev']:+.3f}% net={r1_s['ev']-ETF_COST:+.3f}% "
              f"day_t={r1_dt['t']} p={r1_dt['p_one_sided']} WR={r1_s['wr']}%")
        print(f"    修正 BHAR:  gross={cor_s['ev']:+.3f}% net={cor_s['ev']-ETF_COST:+.3f}% "
              f"day_t={cor_dt['t']} p={cor_dt['p_one_sided']} WR={cor_s['wr']}%")
        print(f"    raw EV:     gross={raw_s['ev']:+.3f}% net={raw_s['ev']-ETF_COST:+.3f}% "
              f"WR={raw_s['wr']}%")
        print(f"    beta 泄漏 = R1 - 修正 = {r1_s['ev']-cor_s['ev']:+.3f}% "
              f"({'R1 通胀' if r1_s['ev'] > cor_s['ev'] else 'R1 通缩'})")
        if wf["status"] == "ok":
            tr = wf["train_ev"]; te = wf["test_ev"]
            print(f"    walk-forward(修正): train={tr['ev']:+.3f}% test={te['ev']:+.3f}% "
                  f"test_p={wf['test_day_t']['p_one_sided']} "
                  f"n_train_dates={wf['n_train_dates']} n_test_dates={wf['n_test_dates']}")

    return {
        "name": name, "n": len(picks), "n_days": cor_dt["n_days"],
        "r1": r1_s, "r1_dt": r1_dt, "r1_net": r1_s["ev"] - ETF_COST,
        "cor": cor_s, "cor_dt": cor_dt, "cor_net": cor_s["ev"] - ETF_COST,
        "raw": raw_s, "raw_net": raw_s["ev"] - ETF_COST,
        "walk_forward": wf,
        "beta_leak": round(r1_s["ev"] - cor_s["ev"], 3),
    }


def formal_verdict(subset: dict, n_cross: int = N_CROSS_STRATEGY,
                   n_within: int = 1, label: str = "") -> str:
    """对修正 BHAR 出正式 verdict（Bonferroni = cross×within×2_subsets）."""
    cor = subset["cor"]
    cor_dt = subset["cor_dt"]
    wf = subset["walk_forward"]
    wf_status = wf.get("status", "no_picks")
    wf_train_ev = wf.get("train_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
    wf_test_ev = wf.get("test_ev", {}).get("ev", 0.0) if wf_status == "ok" else 0.0
    wf_test_p = wf.get("test_day_t", {}).get("p_one_sided", 1.0) if wf_status == "ok" else 1.0
    n_tests = max(2, n_cross * n_within * 2)
    v = verdict_for(
        ev_gross=cor["ev"], t_day=cor_dt["t"], p_raw=cor_dt["p_one_sided"],
        wf_status=wf_status, wf_train_ev=wf_train_ev, wf_test_ev=wf_test_ev,
        wf_test_p=wf_test_p, n_days=cor_dt["n_days"],
        net_ev=subset["cor_net"], subset_name=label or subset["name"],
        n_cross_factor=n_cross * n_within,
    )
    p_bonf = bonferroni_p(cor_dt["p_one_sided"], n_tests)
    subset["verdict"] = v
    subset["bonf_p"] = p_bonf
    subset["n_tests_bonf"] = n_tests
    return v


# ---------- regime classification ----------

def classify_regime(date: str, index_map: dict[str, dict],
                    idx_dates_sorted: list[str]) -> str:
    """bull/bear/range via 60-day index momentum; crisis via fixed windows."""
    for label, lo, hi in CRISIS_WINDOWS:
        if lo <= date <= hi:
            return "crisis"
    # 60-day momentum
    di = None
    # binary search-ish (dates sorted)
    lo_i, hi_i = 0, len(idx_dates_sorted)
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


def tag_regime(picks: list[dict], index_map: dict[str, dict]) -> dict[str, list[dict]]:
    idx_dates_sorted = sorted(index_map.keys())
    out: dict[str, list[dict]] = {"bull": [], "bear": [], "range": [], "crisis": []}
    for p in picks:
        r = classify_regime(p["signal_date"], index_map, idx_dates_sorted)
        p["regime"] = r
        out[r].append(p)
    return out


# ---------- main ----------

def main() -> None:
    print("=" * 78)
    print("ETF 折溢价 Round 2 深挖——edge 消亡诊断（唯一 formal-pass）")
    print("=" * 78)

    etf_data = load_etf_data()
    index_map = load_index()
    calendar = build_calendar(etf_data)
    total_bars = sum(len(v) for v in etf_data.values())
    print(f"\n[数据] {len(etf_data)} ETFs, {total_bars} bar-days, "
          f"{calendar[0]} ~ {calendar[-1]} ({len(calendar)} dates)")
    print(f"[指数] sh.000001 {len(index_map)} days")

    broad_codes = {c for c, (_, t) in ETF_UNIVERSE.items() if t == "broad"}
    sector_codes = {c for c, (_, t) in ETF_UNIVERSE.items() if t == "sector"}

    # ============================================================
    # 维度 6 先行：BHAR 口径修正（R1 beta 泄漏 vs 修正 beta-neutral）
    # 全样本 disc<-0.3% 1d hold，对比两种口径
    # ============================================================
    print("\n" + "=" * 78)
    print("维度 6: BHAR 口径修正（R1 beta 泄漏 vs 修正 beta-neutral）")
    print("=" * 78)
    print("R1 BHAR = price_ret(1.5d) - nav_ret(1d)，T+1 日内 beta 未扣除 → 通胀")
    print("修正 BHAR = (price/NAV exit) - (price/NAV entry)，纯收敛 beta-neutral")
    print("若 R1 gross > 修正 gross → R1 通胀了 edge（beta 泄漏假 edge）")

    picks_full = build_picks_window(etf_data, calendar, -0.3, hold_days=1)
    sub_full = analyze_subset("全样本 disc<-0.3% 1d", picks_full)
    n_yizi_skipped = 0  # 代理已在 build 内
    print(f"\n  全样本: n={len(picks_full)}（is_yizi ETF 代理跳过极少，ETF 极少一字涨停）")

    # ============================================================
    # 维度 1: 结构断点（era split + 年度趋势）
    # ============================================================
    print("\n" + "=" * 78)
    print("维度 1: 结构断点——edge 消亡是永久（效率提升）还是周期性？")
    print("=" * 78)

    eras = [
        ("pre-2020 (2005-2019)", "2005-01-01", "2019-12-31"),
        ("2020-2022", "2020-01-01", "2022-12-31"),
        ("2023-2026 (近期)", "2023-01-01", "2026-12-31"),
    ]
    print("\n--- era 分层（disc<-0.3% 1d，修正 BHAR）---")
    era_results = []
    for label, lo, hi in eras:
        pk = build_picks_window(etf_data, calendar, -0.3, hold_days=1,
                                date_lo=lo, date_hi=hi)
        r = analyze_subset(label, pk)
        era_results.append(r)

    # 年度趋势
    print("\n--- 年度 BHAR 趋势（修正 BHAR，看 edge 何时死）---")
    print(f"{'year':<6} {'n':>6} {'n_days':>7} {'BHAR%':>9} {'net%':>8} "
          f"{'day_t':>7} {'p':>9}")
    yearly_trend = []
    for yr in range(2015, 2027):
        lo = f"{yr}-01-01"; hi = f"{yr}-12-31"
        pk = build_picks_window(etf_data, calendar, -0.3, hold_days=1,
                                date_lo=lo, date_hi=hi)
        if not pk:
            continue
        r = analyze_subset(str(yr), pk, verbose=False)
        yearly_trend.append((yr, r))
        print(f"{yr:<6} {r['n']:>6} {r['n_days']:>7} {r['cor']['ev']:>+9} "
              f"{r['cor_net']:>+8} {r['cor_dt']['t']:>7} {r['cor_dt']['p_one_sided']:>9}")

    # 断点定位：哪一年 BHAR 首次转负且持续
    flip_year = None
    for i, (yr, r) in enumerate(yearly_trend):
        if r["cor"]["ev"] < 0 and i + 1 < len(yearly_trend) and yearly_trend[i+1][1]["cor"]["ev"] < 0:
            flip_year = yr
            break
    print(f"\n  断点: BHAR 首次持续转负年 = {flip_year}")

    # ============================================================
    # 维度 2: regime 分层（bull/bear/crisis）
    # ============================================================
    print("\n" + "=" * 78)
    print("维度 2: regime 分层——edge 是否集中在 bear/危机？")
    print("=" * 78)
    by_regime = tag_regime(picks_full, index_map)
    print(f"bull={len(by_regime['bull'])} bear={len(by_regime['bear'])} "
          f"range={len(by_regime['range'])} crisis={len(by_regime['crisis'])}")
    regime_results = {}
    for rname in ("bull", "bear", "range", "crisis"):
        r = analyze_subset(f"regime={rname}", by_regime[rname])
        regime_results[rname] = r

    # ============================================================
    # 维度 3: 窗口对比（1d/2d/4d/5d hold）
    # ============================================================
    print("\n" + "=" * 78)
    print("维度 3: 窗口对比——长窗口能否捕获更慢的收敛？")
    print("=" * 78)
    window_results = []
    for hd in (1, 2, 4, 5):
        pk = build_picks_window(etf_data, calendar, -0.3, hold_days=hd)
        r = analyze_subset(f"hold={hd}d (exit T+{hd+1})", pk)
        window_results.append((hd, r))

    # ============================================================
    # 维度 4: 阈值分桶（单调性测试）
    # ============================================================
    print("\n" + "=" * 78)
    print("维度 4: 阈值分桶——更深折价=更多 edge（单调）？")
    print("=" * 78)
    thr_results = []
    for thr in (-0.3, -0.5, -1.0, -1.5, -2.0):
        pk = build_picks_window(etf_data, calendar, thr, hold_days=1)
        r = analyze_subset(f"disc<{thr}%", pk)
        thr_results.append((thr, r))

    # ============================================================
    # 维度 5: ETF 类型分层（宽基 vs 行业/主题）
    # ============================================================
    print("\n" + "=" * 78)
    print("维度 5: ETF 类型分层——edge 是否集中宽基或行业？")
    print("=" * 78)
    pk_broad = build_picks_window(etf_data, calendar, -0.3, hold_days=1,
                                  etf_filter=broad_codes)
    pk_sector = build_picks_window(etf_data, calendar, -0.3, hold_days=1,
                                   etf_filter=sector_codes)
    analyze_subset("宽基(broad)", pk_broad)
    analyze_subset("行业(sector)", pk_sector)

    # ============================================================
    # 维度 7: 2023-2026 子条件 sweep（ANY 存活？）
    # ============================================================
    print("\n" + "=" * 78)
    print("维度 7: 2023-2026 子条件 sweep——近期数据是否有 ANY 子条件存活 §44 v3？")
    print("=" * 78)
    print("sweep: 阈值(0.3/0.5/1.0) × 窗口(1d/2d/4d) × 类型(全/宽基/行业) × regime(全/bear/crisis)")
    print("within-script Bonferroni 严控多重检验（防 p-hacking）")

    RECENT_LO, RECENT_HI = "2023-01-01", "2026-12-31"
    sub_conds = []
    for thr in (-0.3, -0.5, -1.0):
        for hd in (1, 2, 4):
            for fname, fset in (("all", None), ("broad", broad_codes),
                                 ("sector", sector_codes)):
                pk = build_picks_window(etf_data, calendar, thr, hold_days=hd,
                                        etf_filter=fset,
                                        date_lo=RECENT_LO, date_hi=RECENT_HI)
                if not pk:
                    continue
                # regime split
                rg = tag_regime(pk, index_map)
                # 全 regime
                r = analyze_subset(
                    f"23-26 thr{thr} h{hd} {fname}", pk, verbose=False)
                sub_conds.append(r)
                # bear only
                if rg["bear"]:
                    rb = analyze_subset(
                        f"23-26 thr{thr} h{hd} {fname} bear", rg["bear"],
                        verbose=False)
                    sub_conds.append(rb)
                # crisis only
                if rg["crisis"]:
                    rc = analyze_subset(
                        f"23-26 thr{thr} h{hd} {fname} crisis", rg["crisis"],
                        verbose=False)
                    sub_conds.append(rc)

    n_sub = len(sub_conds)
    print(f"\n  测试 {n_sub} 个子条件（2023-2026）")
    # within-script Bonferroni: n_sub 个子条件 × cross-strategy ×3 × 2 subsets
    n_bonf_sub = max(2, n_sub * N_CROSS_STRATEGY * 2)
    print(f"  within-script Bonferroni ×{n_sub}×{N_CROSS_STRATEGY}(cross)×2 = ×{n_bonf_sub}")

    survivors = []
    print(f"\n{'子条件':<40} {'n':>5} {'BHAR%':>8} {'net%':>7} {'p_raw':>9} "
          f"{'p_bonf':>9} {'verdict':<14}")
    for sc in sub_conds:
        p_bonf = bonferroni_p(sc["cor_dt"]["p_one_sided"], n_bonf_sub)
        sc["p_bonf_sub"] = p_bonf
        # 子条件 verdict：用修正 BHAR + 严格 Bonf
        if sc["n_days"] < 60:
            v = "underpowered"
        elif sc["cor"]["ev"] < 0:
            v = "falsified"
        elif p_bonf >= ALPHA:
            v = "falsified"
        elif sc["cor_net"] <= 0:
            v = "falsified"
        else:
            v = "survives-bonf"
        sc["sub_verdict"] = v
        flag = " <== survives Bonf" if v == "survives-bonf" else ""
        print(f"{sc['name']:<40} {sc['n']:>5} {sc['cor']['ev']:>+8} "
              f"{sc['cor_net']:>+7} {sc['cor_dt']['p_one_sided']:>9} "
              f"{p_bonf:>9} {v:<14}{flag}")
        if v == "survives-bonf":
            survivors.append(sc)

    # ============================================================
    # 正式 verdict（全样本 + 近期，修正 BHAR，Bonf×3×5）
    # ============================================================
    print("\n" + "=" * 78)
    print("正式 verdict（修正 BHAR，Bonferroni ×3 cross-strategy ×5 family）")
    print("=" * 78)

    # 全样本（disc<-0.3% 1d）
    v_full = formal_verdict(sub_full, n_cross=N_CROSS_STRATEGY,
                            n_within=N_FAMILY_VARIANTS,
                            label="全样本 disc<-0.3% 1d (修正BHAR)")

    # 2023-2026 全样本
    picks_recent = build_picks_window(etf_data, calendar, -0.3, hold_days=1,
                                      date_lo=RECENT_LO, date_hi=RECENT_HI)
    sub_recent = analyze_subset("2023-2026 disc<-0.3% 1d", picks_recent)
    v_recent = formal_verdict(sub_recent, n_cross=N_CROSS_STRATEGY,
                              n_within=N_FAMILY_VARIANTS,
                              label="2023-2026 disc<-0.3% 1d (修正BHAR)")

    # ============================================================
    # 诚实总结
    # ============================================================
    print("\n" + "=" * 78)
    print("诚实总结")
    print("=" * 78)
    print(f"\n[BHAR 口径] R1 全样本 gross={sub_full['r1']['ev']:+.3f}% vs "
          f"修正={sub_full['cor']['ev']:+.3f}% → beta 泄漏={sub_full['beta_leak']:+.3f}%")
    print(f"  → {'R1 通胀了 edge（beta 泄漏假 edge 成分）' if sub_full['beta_leak'] > 0 else 'R1 通缩了 edge'}")

    print(f"\n[结构断点] 断点年={flip_year}")
    print(f"  pre-2020 修正 BHAR={era_results[0]['cor']['ev']:+.3f}%")
    print(f"  2020-2022 修正 BHAR={era_results[1]['cor']['ev']:+.3f}%")
    print(f"  2023-2026 修正 BHAR={era_results[2]['cor']['ev']:+.3f}%")

    print(f"\n[regime] bear BHAR={regime_results['bear']['cor']['ev']:+.3f}% "
          f"crisis={regime_results['crisis']['cor']['ev']:+.3f}% "
          f"bull={regime_results['bull']['cor']['ev']:+.3f}%")

    # 窗口最佳
    best_win = max(window_results, key=lambda x: x[1]["cor"]["ev"])
    print(f"\n[窗口] 最佳 hold={best_win[0]}d BHAR={best_win[1]['cor']['ev']:+.3f}% "
          f"(1d={window_results[0][1]['cor']['ev']:+.3f}%)")

    # 阈值单调性
    print(f"\n[阈值单调] ", end="")
    for thr, r in thr_results:
        print(f"{thr}%→{r['cor']['ev']:+.3f}%  ", end="")
    print()

    print(f"\n[2023-2026 子条件] {n_sub} 测试，Bonf×{n_bonf_sub}，"
          f"存活 {len(survivors)} 个")
    if survivors:
        print("  存活子条件：")
        for s in survivors:
            print(f"    {s['name']}: BHAR={s['cor']['ev']:+.3f}% "
                  f"n={s['n']} n_days={s['n_days']} p_bonf={s['p_bonf_sub']:.6f}")

    print(f"\n[正式 verdict]")
    print(f"  全样本(2005-2026): {v_full}")
    print(f"  近期(2023-2026):   {v_recent}")

    print("\n禁外推声明：本测仅 ETF 折溢价单策略。大股东增持/跌停打开是独立策略，")
    print("不因 ETF edge 消亡而外推'机制套利域无 edge'。跨境 QDII/LOF/封基未测。")
    print("ETF 无 high/low → R6 stop N/A（收敛策略本不用 stop，非缺口）。")


if __name__ == "__main__":
    main()
