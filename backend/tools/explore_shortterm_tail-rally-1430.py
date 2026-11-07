# -*- coding: utf-8 -*-
"""短线策略探索: tail-rally-1430 (尾盘14:30异动).

原始假设: 14:30-15:00 量增价升股 T收盘买 T+1开盘卖 (持有最短 T+1, 风险最低).

=== 数据诚实声明 (CRITICAL) ===
原始策略需要 5min intraday bars 来隔离 14:30-15:00 段 ("量增价升" 在该段内发生).
本环境 5min 数据实测:
  - baostock 5min 单次单股单日 0.03s (孤立调用快)
  - 但任何批量 (10 calls / 20 calls / 50 stocks×1day / 1股×1月) 全部 timeout (>40-120s)
  - 全市场扫描 5235股×2119日×48bar = 5.7M fetch 不可行
结论: 原始 14:30 段策略 = NO-DATA (无法隔离 14:30 段).

=== 本脚本所测: 日K近似代理 (测的是不同假设, 非原始 14:30 策略) ===
日K可翻译子假设: "尾盘强收 + 量增 → 隔夜 gap 正" (close 接近当日 high + 量增 →
T收盘买 T+1开盘卖 的隔夜收益 > 市场隔夜漂移).

代理局限 (必须诚实):
  1. close_strength=(close-low)/(high-low) 高 = 收盘在当日区间上部,
     但无法区分"早涨横盘到收盘"vs"14:30 才拉升"——这是 DIFFERENT signal.
  2. 日级 volume surge 无法隔离 14:30 段量增 (全天量代理).
  3. 与已 falsified 信号亲缘: 接近"强收 momentum"+"隔夜 gap"(涨停股 gap 已测 +1.30%
     但薄+不可选). 本代理测 NON-涨停 强收股的隔夜 gap 差额.
  4. 代理 verdict ≠ 原始 14:30 策略 verdict.

=== §44 v3 过严口径 ===
  - entry = T close (收盘集合竞价可成交, ~close 价), exit = T+1 open (开盘可卖).
  - 隔夜 hold: 无 intraday stop (gap 即风险, 无法盘中止损).
  - ret = (T+1 open - T close)/T close × 100  (close_ev, 非 open_ev——隔夜本身无日内泄漏).
  - T+1 一字跌停 (封死卖不出): fill at T+1 close (最差可卖时机), 标 exit_reason.
  - 排除: T 涨停封板 (close=high=limit, close_strength=1 假象, 与 consecutive_relay
    falsified 同宇宙, 不重测).
  - BHAR: 信号组隔夜收益 - 当日全市场等权隔夜收益 (控 bull 市全涨混杂).
  - per-day-mean t (同日 picks 聚成 day-mean, effective N=n_dates).
  - Bonferroni cross-strategy ×5 (跨策略族).
  - walk-forward OOS + train_ev>0.
  - DSR/PBO: N/A (单隔夜信号无 return series, DSR 需 Sharpe series).
  - 禁止外推: 代理结果 ≠ 短线/隔夜 有/无 edge.
"""

from __future__ import annotations
import sys
from pathlib import Path
from collections import defaultdict
from statistics import mean, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import (  # noqa: E402
    load_kline_db,
    limit_for_code,
    is_yizi_t1,
    ev_stats,
    day_paired_t,
    bonferroni_p,
    walk_forward,
    verdict_for,
    COST,
    ALPHA,
)

# ---------- 代理参数 ----------
CLOSE_STRENGTH_THRESH = 0.90  # close 在当日区间上部 >= 90% (强收代理)
VOL_SURGE_MULT = 1.5  # 量增: vol_T >= 1.5 × 近5日均量
VOL_LOOKBACK = 5
OVERNIGHT_COST = 0.0015  # 隔夜往返成本 0.15% (买佣0.025+卖佣0.025+印花0.05+滑点)
N_CROSS_STRATEGY = 5  # 跨策略 Bonferroni ×5
FAMILY_THRESHOLDS = (0.80, 0.90, 0.95)  # 家族阈值敏感性 (cross-parameter Bonf)


# ---------- 数据加载 ----------
def load_data():
    print("[1] 加载日K (5235 codes) + index regime ...")
    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    import json

    idx = json.load(open(resolve_data_dir() / "index_ma20_regime.json"))
    print(f"    codes={len(code_map)} dates={len(calendar)} ({calendar[0]}..{calendar[-1]}) index_days={len(idx)}")
    return code_map, calendar, idx


# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]


# ---------- 市场隔夜基准 (控 bull 全涨混杂) ----------
def build_market_overnight(code_map, calendar):
    """每日全市场等权隔夜收益 (T close -> T+1 open).
    返回 {T_date: market_overnight_pct}."""
    date_idx = {d: i for i, d in enumerate(calendar)}
    by_date: dict[str, list[float]] = defaultdict(list)
    for code, dm in code_map.items():
        # 该 code 的有 bar 的交易日, 按 calendar 顺序
        present = sorted(dm.keys(), key=lambda d: date_idx.get(d, -1))
        for i in range(len(present) - 1):
            d = present[i]
            di = date_idx.get(d)
            if di is None or di + 1 >= len(calendar):
                continue
            d_next = calendar[di + 1]
            # 必须 T+1 (下一交易日) 该 code 有 bar (未停牌)
            if d_next not in dm:
                continue
            t_close = dm[d].get("close")
            t1_open = dm[d_next].get("open")
            if not t_close or not t1_open or t_close <= 0:
                continue
            by_date[d].append((t1_open - t_close) / t_close * 100)
    market = {}
    for d, rets in by_date.items():
        if rets:
            market[d] = mean(rets)
    return market, by_date


# ---------- 涨停/跌停封板检测 (排除) ----------
def is_limit_closed(bar, prev_close, code, is_st):
    """当日收盘封涨停或封跌停 (close=high=limit 或 close=low=limit)."""
    if prev_close is None or prev_close <= 0:
        return False, False
    lim = limit_for_code(code, is_st)
    pc = bar.get("pctChg")
    pct = pc if pc is not None else (bar.get("close", 0) - prev_close) / prev_close * 100
    up_closed = pct >= lim * 100 - 0.3  # 涨停封板 (含一字)
    dn_closed = pct <= -lim * 100 + 0.3  # 跌停封板
    return up_closed, dn_closed


# ---------- build_picks: 日K代理 (非 zt-based) ----------
def build_picks_tail_rally(
    code_map, calendar, market_overnight, close_thresh=CLOSE_STRENGTH_THRESH, vol_mult=VOL_SURGE_MULT
):
    """代理: close_strength >= thresh AND 量增 → T close 买, T+1 open 卖."""
    date_idx = {d: i for i, d in enumerate(calendar)}
    picks = []
    skipped = defaultdict(int)
    for code, dm in code_map.items():
        present = sorted(dm.keys(), key=lambda d: date_idx.get(d, -1))
        # 预计算 rolling 5日成交量均值
        vols = []
        for i in range(len(present)):
            d = present[i]
            di = date_idx.get(d)
            if di is None or di + 1 >= len(calendar):
                vols.append(None)
                continue
            bar = dm[d]
            d_next = calendar[di + 1]
            t1_bar = dm.get(d_next)
            if t1_bar is None:
                vols.append(None)
                continue
            o, h, l, c = bar.get("open"), bar.get("high"), bar.get("low"), bar.get("close")
            vol = bar.get("volume")
            if None in (o, h, l, c, vol) or c <= 0 or h <= 0:
                vols.append(None)
                continue
            # close_strength (guard high==low)
            cs = (c - l) / (h - l) if h > l else 0.5
            # rolling vol mean (前 VOL_LOOKBACK 个有值的)
            lookback = [vols[j] for j in range(max(0, i - VOL_LOOKBACK), i) if vols[j]]
            if len(lookback) < 3:
                vols.append(vol)
                continue
            vmean = mean(lookback)
            vols.append(vol)

            # prev_close (排除涨停封板用)
            prev_close = dm[present[i - 1]].get("close") if i > 0 else None
            is_st = bar.get("isST") == "1"
            up_closed, dn_closed = is_limit_closed(bar, prev_close, code, is_st)
            if up_closed:
                skipped["zt_closed"] += 1
                continue  # 排除涨停封板 (与 consecutive_relay falsified 同宇宙)
            if dn_closed:
                skipped["dt_closed"] += 1
                continue  # 跌停封板非尾盘拉升

            # 信号: 强收 + 量增
            if cs < close_thresh:
                continue
            if vmean > 0 and vol < vmean * vol_mult:
                continue

            # entry/exit
            t1_open = t1_bar.get("open")
            t1_low = t1_bar.get("low")
            t1_close = t1_bar.get("close")
            if not t1_open or t1_open <= 0:
                continue

            # T+1 一字跌停 (封死卖不出 open) -> fill at T+1 close (最差可卖)
            exit_reason = "t1_open"
            exit_px = t1_open
            lim = limit_for_code(code, is_st)
            # 一字跌停: open==low 且 open <= close*(1-lim)
            if (
                t1_low is not None
                and abs(t1_open - t1_low) / t1_open < 0.005
                and prev_close
                and t1_open <= prev_close * (1 - lim + 0.005)
            ):
                exit_px = t1_close if t1_close and t1_close > 0 else t1_open
                exit_reason = "t1_limit_down_fill_close"

            ret = (exit_px - c) / c * 100
            mkt = market_overnight.get(d)
            bhar = ret - mkt if mkt is not None else None

            picks.append(
                {
                    "code": code,
                    "zt_date": d,
                    "t1_date": d_next,
                    "entry": c,
                    "t1_bar": t1_bar,
                    "t_close": c,
                    "close_strength": round(cs, 3),
                    "vol_surge": round(vol / vmean, 2) if vmean else 0,
                    "ret": ret,
                    "bhar": bhar,
                    "exit_reason": exit_reason,
                }
            )
    return picks, skipped


# ---------- 分析 (含 BHAR) ----------
def analyze_proxy(name, picks, n_cross=N_CROSS_STRATEGY):
    print(f"\n{'=' * 72}\n代理: {name} (n_picks={len(picks)})\n{'=' * 72}")
    if not picks:
        print("  无 picks")
        return {}

    rets = [p["ret"] for p in picks]
    bhars = [p["bhar"] for p in picks if p["bhar"] is not None]

    s = ev_stats(rets)
    net_ev = s["ev"] - OVERNIGHT_COST * 100
    print(f"\n--- 原始隔夜 EV (T close -> T+1 open, no cost) ---")
    print(f"  n={s['n']} gross_EV={s['ev']}% net_EV(overnight cost {OVERNIGHT_COST * 100}%)={net_ev:.3f}%")
    print(f"  std={s['std']}% WR={s['wr']}% t={s['t']} CI[{s['ci_lo']},{s['ci_hi']}]")

    # 市场隔夜基准对比
    mkt_rets = [p["ret"] - (p["bhar"] or 0) for p in picks if p["bhar"] is not None]
    if mkt_rets:
        ms = ev_stats(mkt_rets)
        print(f"  市场隔夜基准 (同期): mean={ms['ev']}% n={ms['n']}")
        print(f"  → 信号组 - 市场 = {s['ev'] - ms['ev']:.3f}% (BHAR)")

    # BHAR day-paired t
    print(f"\n--- BHAR (信号隔夜 - 市场隔夜, day-paired) ---")
    bhar_by_date = defaultdict(list)
    for p in picks:
        if p["bhar"] is not None:
            bhar_by_date[p["zt_date"]].append(p["bhar"])
    bdt = day_paired_t(bhar_by_date)
    print(
        f"  n_days={bdt['n_days']} BHAR_mean={bdt['mean']}% std={bdt['std']}% "
        f"t={bdt['t']} p_one_sided={bdt['p_one_sided']}"
    )
    n_tests = max(2, n_cross)
    p_bonf = bonferroni_p(bdt["p_one_sided"], n_tests)
    print(f"  Bonferroni ×{n_tests} (cross-strategy): p={p_bonf:.6f} {'PASS' if p_bonf < ALPHA else 'FAIL'}")

    # 原始 EV day-paired (无 BHAR)
    ret_by_date = defaultdict(list)
    for p in picks:
        ret_by_date[p["zt_date"]].append(p["ret"])
    rdt = day_paired_t(ret_by_date)
    print(f"\n--- 原始 EV day-paired (无 BHAR 基准) ---")
    print(f"  n_days={rdt['n_days']} mean={rdt['mean']}% t={rdt['t']} p={rdt['p_one_sided']}")

    # walk-forward (用 ret_fn 返回 ret)
    def ret_fn(p):
        return p["ret"]

    wf = walk_forward(picks, ret_fn)
    print(f"\n--- walk-forward OOS (前半 train → 后半 test) ---")
    if wf["status"] == "ok":
        tr, te = wf["train_ev"], wf["test_ev"]
        print(f"  train: n={tr['n']} n_dates={wf['n_train_dates']} EV={tr['ev']}% t={tr['t']}")
        print(
            f"  test:  n={te['n']} n_dates={wf['n_test_dates']} EV={te['ev']}% t={te['t']} "
            f"day_t={wf['test_day_t']['t']}"
        )
        decay = ((tr["ev"] - te["ev"]) / abs(tr["ev"]) * 100) if tr["ev"] else 0
        print(f"  decay: {decay:.0f}% (train→test)")
    else:
        print(f"  {wf['status']} (n_dates={wf.get('n_dates', 0)})")

    # exit reasons
    reasons = defaultdict(int)
    for p in picks:
        reasons[p["exit_reason"]] += 1
    print(f"\n--- exit reasons ---")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {r}: {c} ({c / len(picks) * 100:.1f}%)")

    # verdict (用 BHAR day-t, 因为 BHAR 才是真 edge)
    print(f"\n--- verdict (基于 BHAR day-paired, Bonf ×{n_cross}) ---")
    v = verdict_for(
        ev_gross=bdt["mean"],
        t_day=bdt["t"],
        p_raw=bdt["p_one_sided"],
        wf_status=wf["status"],
        wf_train_ev=wf.get("train_ev", {}).get("ev", 0),
        wf_test_ev=wf.get("test_ev", {}).get("ev", 0),
        wf_test_p=wf.get("test_day_t", {}).get("p_one_sided", 1),
        n_days=bdt["n_days"],
        net_ev=bdt["mean"] - OVERNIGHT_COST * 100,
        subset_name=f"{name} (BHAR)",
        n_cross_factor=n_cross,
    )
    return {"n": len(picks), "ev": s, "bhar_day_t": bdt, "wf": wf, "verdict": v}


# ---------- regime 分层 ----------
def regime_stratify(picks, idx):
    print(f"\n--- regime 分层 (index ma20 strong/weak) ---")
    for reg in ("strong", "weak"):
        sub = [p for p in picks if idx.get(p["zt_date"], {}).get("regime") == reg]
        if not sub:
            continue
        bhars = [p["bhar"] for p in sub if p["bhar"] is not None]
        by_date = defaultdict(list)
        for p in sub:
            if p["bhar"] is not None:
                by_date[p["zt_date"]].append(p["bhar"])
        bdt = day_paired_t(by_date)
        print(
            f"  {reg}: n_picks={len(sub)} n_dates={bdt['n_days']} "
            f"BHAR_mean={bdt['mean']}% t={bdt['t']} p={bdt['p_one_sided']}"
        )


# ---------- main ----------
def main():
    print("=" * 72)
    print("tail-rally-1430 (尾盘14:30异动) — 日K代理探索")
    print("=" * 72)
    print("\n!! 诚实声明: 原始 14:30 策略需 5min 数据隔离 14:30-15:00 段, 5min 实测批量全 timeout → 原始策略 NO-DATA.")
    print("!! 本脚本测日K代理 (强收+量增→隔夜gap), 测的是不同假设, 代理 verdict ≠ 原始 14:30 策略 verdict.\n")

    code_map, calendar, idx = load_data()

    print("\n[2] 构建市场隔夜基准 (全市场等权 T close->T+1 open) ...")
    market, _ = build_market_overnight(code_map, calendar)
    print(f"    market_overnight: {len(market)} dates, mean={mean(market.values()):.4f}%/night")

    print(f"\n[3] 构建代理 picks (close_strength>={CLOSE_STRENGTH_THRESH}, vol_surge>={VOL_SURGE_MULT}x) ...")
    picks, skipped = build_picks_tail_rally(code_map, calendar, market)
    print(f"    picks={len(picks)} skipped={dict(skipped)}")
    if picks:
        cs = [p["close_strength"] for p in picks]
        vs = [p["vol_surge"] for p in picks]
        print(f"    close_strength: mean={mean(cs):.3f} range=[{min(cs)},{max(cs)}]")
        print(f"    vol_surge: mean={mean(vs):.2f}x range=[{min(vs)},{max(vs)}]")
        # picks per year
        per_year = defaultdict(int)
        for p in picks:
            per_year[p["zt_date"][:4]] += 1
        print(f"    per-year: {dict(sorted(per_year.items()))}")

    # 主代理分析
    res = analyze_proxy(f"strong-close+vol-surge (cs>={CLOSE_STRENGTH_THRESH},vol>={VOL_SURGE_MULT}x)", picks)

    if picks:
        regime_stratify(picks, idx)

    # 阈值家族敏感性 (cross-parameter Bonferroni)
    print(f"\n{'=' * 72}\n家族阈值敏感性 (close_strength: {FAMILY_THRESHOLDS})\n{'=' * 72}")
    family_results = []
    for th in FAMILY_THRESHOLDS:
        fp, _ = build_picks_tail_rally(code_map, calendar, market, close_thresh=th)
        by_date = defaultdict(list)
        for p in fp:
            if p["bhar"] is not None:
                by_date[p["zt_date"]].append(p["bhar"])
        bdt = day_paired_t(by_date)
        family_results.append((th, len(fp), bdt))
        print(
            f"  cs>={th}: n={len(fp)} n_dates={bdt['n_days']} "
            f"BHAR_mean={bdt['mean']}% t={bdt['t']} p={bdt['p_one_sided']}"
        )
    # 家族 Bonferroni ×len
    if family_results:
        print(f"\n  家族 Bonferroni ×{len(FAMILY_THRESHOLDS)} (cross-parameter):")
        for th, n, bdt in family_results:
            pb = bonferroni_p(bdt["p_one_sided"], len(FAMILY_THRESHOLDS))
            print(f"    cs>={th}: Bonf_p={pb:.6f} {'PASS' if pb < ALPHA else 'FAIL'}")

    # 无量增条件 (纯强收) 对照——隔离量增的贡献
    print(f"\n{'=' * 72}\n对照: 纯强收无量增 (隔离 vol_surge 贡献)\n{'=' * 72}")
    fp_novol, _ = build_picks_tail_rally(code_map, calendar, market, close_thresh=CLOSE_STRENGTH_THRESH, vol_mult=0.0)
    by_date = defaultdict(list)
    for p in fp_novol:
        if p["bhar"] is not None:
            by_date[p["zt_date"]].append(p["bhar"])
    bdt_nv = day_paired_t(by_date)
    print(
        f"  纯强收 (cs>={CLOSE_STRENGTH_THRESH}, 无量增): n={len(fp_novol)} "
        f"n_dates={bdt_nv['n_days']} BHAR_mean={bdt_nv['mean']}% t={bdt_nv['t']} "
        f"p={bdt_nv['p_one_sided']}"
    )
    print(
        f"  → 对比主代理: 量增条件 {'缩小' if len(fp_novol) > len(picks) else '扩大'}了样本 "
        f"({len(fp_novol)} -> {len(picks)})"
    )

    print(f"\n{'=' * 72}\n最终诚实结论\n{'=' * 72}")
    print(f"原始 14:30 策略: NO-DATA (5min 不可得, 无法隔离 14:30-15:00 段).")
    if res:
        print(f"日K代理 (强收+量增→隔夜gap BHAR): verdict={res.get('verdict', '?')}")
        bdt = res.get("bhar_day_t", {})
        print(
            f"  n_picks={res.get('n', 0)} n_dates={bdt.get('n_days', 0)} "
            f"BHAR_mean={bdt.get('mean', 0)}% day_t={bdt.get('t', 0)} "
            f"p={bdt.get('p_one_sided', 1)}"
        )
        print(f"  ⚠ 代理 verdict ≠ 原始 14:30 策略 verdict (不同假设).")
        print(f"  ⚠ survivorship: cache 仅含现上市股 (退市股缺失).")
        print(f"  ⚠ close_strength 无法区分早涨横盘 vs 14:30 尾盘拉升 (信号污染).")


if __name__ == "__main__":
    main()
