# -*- coding: utf-8 -*-
"""combo-5d real-exec stop-loss convergence audit (2026-11-05).

生产口径 = 去 gap rank（动量 tr + 小盘 amt）+ mode=filtered + T+1 close 买 → T+5 close 卖（4 日持有）。
这是 11-05 entry_point 定的执行口径（net +0.389% t=10.72）。本脚本在此口径上测 hard stop。

A股 T+1 stop 口径（per inst-dominant-stop-caliber-fix）：T+1 close 买入 → 首个可卖日 = T+2。
stop 监控日 = T+2/T+3/T+4（bars[i+2..i+4] 的 low）。T+5 = 自然 exit（close）。
触发：sellable 日 low <= entry*(1+stop)。
成交（现实 stop-order 语义）：触发日 OPEN <= stop_price（跳空穿仓）→ 按 OPEN 成交；否则按 stop_price 成交。
另报保守 next-day-open caliber（触发→次日 open）作下界。

lottery 结构（median 负）预期：stop 割右尾反弹 → 压 mean，但截深亏尾部。
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vr_paths import resolve_data_dir


DB = resolve_data_dir() / "baostock_kline_cache.db"
COST = 0.004  # 双边 0.4%
TOP_N = 20
STOPS = [-0.05, -0.08, -0.10, -0.15]


def board_limit(code: str) -> float:
    c = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    if c.startswith("30") or c.startswith("68"):
        return 0.20
    if c.startswith("8") or c.startswith("4"):
        return 0.30
    return 0.10


def build_by_date() -> dict:
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    by_date: dict = defaultdict(list)
    for code, bj in rows:
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        nb = len(bars)
        if nb < 70:
            continue
        c0 = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
        bl = board_limit(code)
        closes = [0.0] * nb
        opens = [0.0] * nb
        lows = [0.0] * nb
        amts = [0.0] * nb
        issts = ["0"] * nb
        dates_l = [""] * nb
        for j in range(nb):
            b = bars[j]
            dates_l[j] = b.get("date", "")
            closes[j] = float(b.get("close", 0) or 0)
            opens[j] = float(b.get("open", 0) or 0)
            lows[j] = float(b.get("low", 0) or 0)
            amts[j] = float(b.get("amount", 0) or 0)
            issts[j] = str(b.get("isST", "0"))
        cumsum = [0.0] * (nb + 1)
        for j in range(nb):
            cumsum[j + 1] = cumsum[j] + closes[j]
        for i in range(60, nb - 5):
            prev_c = closes[i - 1]
            c = closes[i]
            amt = amts[i]
            if not prev_c or not c or not amt:
                continue
            if issts[i] not in ("0", "", "0.0"):
                continue
            if code.startswith("920"):
                continue
            today_ret = (c - prev_c) / prev_c
            if today_ret >= bl:  # 剔涨停（ratio 口径）
                continue
            t1_close = closes[i + 1]
            t5_close = closes[i + 5]
            if not t1_close or not t5_close:
                continue
            # 持有期 sellable lows: T+2,T+3,T+4 (bars i+2..i+4) + 触发日 open
            path = []
            for k in (2, 3, 4):
                if i + k < nb:
                    path.append((lows[i + k], opens[i + k]))
            nostop = (t5_close - t1_close) / t1_close
            by_date[dates_l[i]].append({
                "code": code, "tr": today_ret, "amt": amt,
                "entry": t1_close, "nostop": nostop, "path": path,
            })
    return by_date


def rank_top(lst: list, n: int = TOP_N) -> list | None:
    if len(lst) < n * 10:
        return None
    nn = len(lst)
    st = sorted(range(nn), key=lambda k: lst[k]["tr"])
    sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    top_idx = sorted(range(nn), key=lambda k: rt[k] + ra[k], reverse=True)[:n]
    return [lst[k] for k in top_idx]


def stop_ret_realistic(p: dict, stop: float) -> float:
    """现实 stop-order：触发日 low<=trigger，OPEN<=trigger→按OPEN，否则按 stop_price。"""
    e = p["entry"]
    if not e:
        return p["nostop"]
    trigger = e * (1.0 + stop)
    for low, opn in p["path"]:
        if low <= trigger:
            fill = opn if (opn and opn <= trigger) else trigger
            return (fill - e) / e
    return p["nostop"]


def stop_ret_nextday_open(p: dict, stop: float) -> float:
    """保守下界：触发→次日 open 成交（gap-through 更差）。T+4 触发→T+5 open（=exit 近似）。"""
    e = p["entry"]
    if not e:
        return p["nostop"]
    trigger = e * (1.0 + stop)
    for idx, (low, _opn) in enumerate(p["path"]):
        if low <= trigger:
            # 次日 open = path[idx+1] 的 open；若末位则用 trigger 近似（T+5 open≈exit）
            if idx + 1 < len(p["path"]):
                nxt_open = p["path"][idx + 1][1]
                return (nxt_open - e) / e if nxt_open else stop
            return stop  # T+4 触发，T+5 open 未知，用 stop 保守
    return p["nostop"]


def trigger_maxdd(p: dict) -> float:
    """持有期 path 最深 low / entry - 1（用于触发率 + 尾部分布）。"""
    e = p["entry"]
    if not e or not p["path"]:
        return 0.0
    min_low = min(low for low, _ in p["path"])
    return min_low / e - 1.0


def daily_stats(dates, by_date, ret_fn) -> dict:
    daily_mean, all_picks = [], []
    for d in dates:
        top = rank_top(by_date[d])
        if not top:
            continue
        rets = [ret_fn(p) for p in top]
        daily_mean.append(statistics.mean(rets))
        all_picks.extend(rets)
    if not daily_mean:
        return {}
    m = statistics.mean(daily_mean)
    med = statistics.mean([statistics.median([ret_fn(p) for p in rank_top(by_date[d])])
                           for d in dates if rank_top(by_date[d])]) if False else 0
    wr = sum(1 for x in all_picks if x > 0) / len(all_picks)
    std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
    se = std / (len(daily_mean) ** 0.5) if daily_mean else 0
    t = m / se if se > 0 else 0
    # median across all picks
    pick_med = statistics.median(all_picks)
    return {"n_days": len(daily_mean), "n_picks": len(all_picks), "mean": m,
            "pick_median": pick_med, "wr": wr, "net": m - COST, "t": t}


def main() -> None:
    print("loading cache (5255 stocks x 8yr)...", flush=True)
    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    print(f"dates={len(all_d)} range={all_d[0]}~{all_d[-1]}", flush=True)

    all_picks = []
    for d in all_d:
        top = rank_top(by_date[d])
        if top:
            all_picks.extend(top)
    n = len(all_picks)
    print(f"\n=== combo-5d real-exec stop convergence（T+1 close→T+5 close，去涨停 top-20，{n} picks）===\n")

    # nostop baseline
    nostop = daily_stats(all_d, by_date, lambda p: p["nostop"])
    # path max_dd 分布（尾部上下文）
    mdds = [trigger_maxdd(p) for p in all_picks]
    nostop_rets = [p["nostop"] for p in all_picks]

    print("【nostop 基线】（生产口径 T+1 close→T+5 close）")
    print(f"  days={nostop['n_days']} picks={nostop['n_picks']}")
    print(f"  mean={nostop['mean']*100:+.3f}% net={nostop['net']*100:+.3f}% pick_median={nostop['pick_median']*100:+.3f}% WR={nostop['wr']*100:.1f}% t={nostop['t']:.2f}")
    print(f"  最终收益尾部分布: <-10%={sum(1 for x in nostop_rets if x<=-0.10)/n*100:.1f}%  <-5%={sum(1 for x in nostop_rets if x<=-0.05)/n*100:.1f}%  >+5%={sum(1 for x in nostop_rets if x>=0.05)/n*100:.1f}%  >+10%={sum(1 for x in nostop_rets if x>=0.10)/n*100:.1f}%")
    print(f"  路径最深回撤: max_dd mean={statistics.mean(mdds)*100:+.2f}% median={statistics.median(mdds)*100:+.2f}%  path<=-10%={sum(1 for x in mdds if x<=-0.10)/n*100:.1f}%  path<=-15%={sum(1 for x in mdds if x<=-0.15)/n*100:.1f}%")
    # 赚钱但盘中跌穿-10%（nostop 必须扛的心理成本）
    both = sum(1 for p, md in zip(all_picks, mdds) if p["nostop"] > 0 and md <= -0.10)
    print(f"  最终赚但盘中跌穿-10%: {both}/{n}={both/n*100:.1f}%（nostop 扛住的心理成本 / stop 会误杀这部分）")
    print()

    print("【hard stop 网格】（现实 stop-order 语义：触发日 low<=stop，OPEN<=stop→按OPEN 否则 stop_price）")
    print(f"  {'stop':>7}{'mean':>10}{'net':>10}{'median':>10}{'WR':>7}{'t':>7}{'触发率':>8}{'tail<-10%':>11}{'tail<-5%':>9}{'Δmean':>9}{'Δnet':>9}")
    print("  " + "-" * 96)
    base_mean = nostop["mean"]
    base_net = nostop["net"]
    base_t10 = sum(1 for x in nostop_rets if x <= -0.10) / n
    base_t5 = sum(1 for x in nostop_rets if x <= -0.05) / n
    rows = []
    for stop in STOPS:
        r = daily_stats(all_d, by_date, lambda p, s=stop: stop_ret_realistic(p, s))
        rets = [stop_ret_realistic(p, stop) for p in all_picks]
        trig = sum(1 for p in all_picks if trigger_maxdd(p) <= stop) / n
        t10 = sum(1 for x in rets if x <= -0.10) / n
        t5 = sum(1 for x in rets if x <= -0.05) / n
        dm = r["mean"] - base_mean
        dn = r["net"] - base_net
        rows.append((stop, r, trig, t10, t5, dm, dn))
        print(f"  {stop*100:>+6.0f}%{r['mean']*100:>+9.3f}%{r['net']*100:>+9.3f}%{r['pick_median']*100:>+9.3f}%{r['wr']*100:>6.1f}%{r['t']:>6.2f}{trig*100:>7.1f}%{t10*100:>10.1f}%{t5*100:>8.1f}%{dm*100:>+8.3f}%{dn*100:>+8.3f}%")
    print(f"  {'nostop':>7}{base_mean*100:>+9.3f}%{base_net*100:>+9.3f}%{nostop['pick_median']*100:>+9.3f}%{nostop['wr']*100:>6.1f}%{nostop['t']:>6.2f}{'—':>7}{'':>10}{base_t10*100:>10.1f}%{base_t5*100:>8.1f}%{'—':>8}{'—':>8}")
    print()

    # 保守下界（next-day-open）for -10/-15
    print("【保守下界 -10%/-15%（触发→次日 open 成交，gap-through 更差）】")
    for stop in [-0.10, -0.15]:
        r = daily_stats(all_d, by_date, lambda p, s=stop: stop_ret_nextday_open(p, s))
        rets = [stop_ret_nextday_open(p, stop) for p in all_picks]
        t10 = sum(1 for x in rets if x <= -0.10) / n
        print(f"  stop={stop*100:+.0f}%: mean={r['mean']*100:+.3f}% net={r['net']*100:+.3f}% WR={r['wr']*100:.1f}% tail<-10%={t10*100:.1f}% Δnet={ (r['net']-base_net)*100:+.3f}%")
    print()

    # lottery 结构权衡：stop 割掉的右尾反弹（最终赚但盘中跌穿的比例被 stop 杀）
    print("【lottery 权衡：stop 误杀的右尾反弹】")
    for stop, r, trig, t10, t5, dm, dn in rows:
        # 被触发且 nostop 最终>0 的 picks（stop 卖在低点错过反弹）
        killed = sum(1 for p in all_picks if trigger_maxdd(p) <= stop and p["nostop"] > 0)
        # 被触发且 nostop 最终<-stop（stop 真救了的）
        saved = sum(1 for p in all_picks if trigger_maxdd(p) <= stop and p["nostop"] <= stop)
        print(f"  stop={stop*100:+.0f}%: 触发 {int(trig*n)} 只 → 误杀右尾(最终本赚){killed} / 真救深亏{saved}（误杀/触发={killed/max(1,int(trig*n))*100:.0f}%）")
    print()

    # 收敛判定
    print("【收敛判定】")
    stop_nets = [f"{r['net']*100:+.3f}%" for _, r, *_ in rows]
    all_nets = [("nostop", nostop["net"])] + [(f"stop {s*100:.0f}%", r["net"]) for s, r, *_ in rows]
    best_label, best_net = max(all_nets, key=lambda x: x[1])
    print(f"  最高 net = {best_net*100:+.3f}%（{best_label}）")
    print(f"  nostop net = {nostop['net']*100:+.3f}% | 任何 stop net = {stop_nets}")
    any_improve = any(r["net"] > base_net for _, r, *_ in rows)
    print(f"  有 stop 提升 net？{'是 → stop 收敛可行' if any_improve else '否 → lottery 结构 stop 必压 mean，收敛=防尾部非抬 mean'}")
    print()

    # 尾部深度削减（防尾部的真义：不只看 count，看 <-10% 灾难的期望损失被砍多少）
    print("【尾部深度削减】（nostop 最终<-10% 的 picks，stop 砍了多少期望损失）")
    for stop in [-0.10, -0.15]:
        deep = [(p["nostop"], stop_ret_realistic(p, stop)) for p in all_picks if p["nostop"] <= -0.10]
        if deep:
            nmean = statistics.mean(x[0] for x in deep)
            smean = statistics.mean(x[1] for x in deep)
            cnt_deeper = sum(1 for n, s in deep if s < n)  # stop 更差（gap-through 穿仓）
            print(f"  stop={stop*100:+.0f}%: nostop<-10% 共 {len(deep)} 只，nostop 均亏 {nmean*100:+.2f}% → stop 后均亏 {smean*100:+.2f}%（削亏 {(smean-nmean)*100:+.2f}pp）；stop 反更差(gap穿仓) {cnt_deeper}/{len(deep)}={cnt_deeper/len(deep)*100:.0f}%")
    print()

    # 组合层权益曲线：nostop vs -10% stop（看 drawdown 削减 = stop 真价值）
    print("【组合层权益曲线 nostop vs -10% stop】（日组合等权 → max drawdown）")

    def equity(dates, ret_fn):
        rets = []
        for d in dates:
            top = rank_top(by_date[d])
            if not top:
                continue
            rets.append(statistics.mean(ret_fn(p) for p in top))
        eq = [1.0]
        for r in rets:
            eq.append(eq[-1] * (1.0 + r - COST))
        peak = eq[0]; mdd = 0.0; mlen = 0; cur = 0; worst = min(rets) if rets else 0
        for v in eq[1:]:
            if v > peak:
                peak = v; cur = 0
            else:
                cur += 1
                dd = v / peak - 1.0
                if dd < mdd:
                    mdd = dd; mlen = cur
        return eq[-1], mdd, mlen, worst, statistics.mean(rets)

    for label, fn in [("nostop ", lambda p: p["nostop"]),
                      ("stop-10%", lambda p: stop_ret_realistic(p, -0.10)),
                      ("stop-15%", lambda p: stop_ret_realistic(p, -0.15))]:
        term, mdd, mlen, worst, m = equity(all_d, fn)
        print(f"  {label}: 终值={term:.3f} maxDD={mdd*100:+.2f}%(持续{mlen}日) 最差单日={worst*100:+.2f}% 日mean={m*100:+.3f}%")


if __name__ == "__main__":
    main()
