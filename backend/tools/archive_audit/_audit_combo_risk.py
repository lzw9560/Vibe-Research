# -*- coding: utf-8 -*-
"""combo-5d 风险控制审计（2026-11-03）。

测 4 个未测维度（winrate 脚本只算 fwd5 close-to-close，没测路径/回撤/止损/regime 回撤）：
  1. 单只路径回撤：持有期内最大跌幅（min low / entry），定尾部 + 仓位上限依据
  2. 组合回撤：日组合收益链成权益曲线 → max drawdown（peak-to-trough）
  3. nostop vs 软止损：模拟 -5%/-8%/-10%/-15% stop，看压 mean 多少 + 砍多少尾部
  4. regime 回撤：gate=OFF 日权益曲线 max drawdown（2026 弱市 OFF t0.81 的真实回撤）

复用 _audit_combo_winrate.py 的 rank 逻辑（去涨停 top-20），加路径追踪 + 权益曲线 + stop 模拟。

口径冻结：entry=signal_day close（与 winrate fwd5 一致 apples-to-apples）；持有 bars[i+1..i+5]。
路径用 daily low（非分钟，A 股 T+1 当天不能卖，stop 次日成交）。
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / ".vibe-research" / "baostock_kline_cache.db"
COST = 0.004  # 双边 0.4%
TOP_N = 20
STOPS = [-0.05, -0.08, -0.10, -0.15]  # 软止损档


def board_limit(code: str) -> float:
    c = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    if c.startswith("30") or c.startswith("68"):
        return 0.20
    if c.startswith("8") or c.startswith("4"):
        return 0.30
    return 0.10


def build_by_date() -> dict:
    """每日：每只票 {gap, tr, amt, entry, lows[], closes[], fwd5, up, past5, limit}。"""
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    by_date: dict = defaultdict(list)
    for code, bj in rows:
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        if len(bars) < 70:
            continue
        bl = board_limit(code)
        for i in range(60, len(bars) - 5):
            prev_c = float(bars[i - 1].get("close", 0) or 0)
            o = float(bars[i].get("open", 0) or 0)
            c = float(bars[i].get("close", 0) or 0)
            amt = float(bars[i].get("amount", 0) or 0)
            if not prev_c or not c or not o:
                continue
            ma60 = statistics.mean(float(bars[j].get("close", 0) or 0) for j in range(i - 60, i))
            if not ma60:
                continue
            today_ret = (c - prev_c) / prev_c
            gap = (o - prev_c) / prev_c
            past5_c = float(bars[i - 5].get("close", 0) or 0) if i >= 5 else prev_c
            past_5d = (c - past5_c) / past5_c if past5_c else 0.0
            nc = float(bars[i + 5].get("close", 0) or 0)
            if not nc:
                continue
            fwd5 = (nc - c) / c
            # 持有期路径：bars[i+1..i+5] 的 low 和 close
            lows = [float(bars[i + k].get("low", 0) or 0) for k in range(1, 6)]
            fwd_closes = [float(bars[i + k].get("close", 0) or 0) for k in range(1, 6)]
            by_date[bars[i].get("date", "")].append({
                "code": code, "gap": gap, "tr": today_ret, "amt": amt,
                "entry": c, "fwd5": fwd5, "lows": lows, "fwd_closes": fwd_closes,
                "up": c > ma60, "past5": past_5d,
                "limit": today_ret >= bl * 0.98,
            })
    return by_date


def rank_top(lst: list, n: int = TOP_N) -> list | None:
    pool = [x for x in lst if not x["limit"]]
    if len(pool) < n * 10:
        return None
    nn = len(pool)
    sg = sorted(range(nn), key=lambda k: pool[k]["gap"])
    st = sorted(range(nn), key=lambda k: pool[k]["tr"])
    sa = sorted(range(nn), key=lambda k: pool[k]["amt"])
    rg = {o: r / nn for r, o in enumerate(sg)}
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    score = lambda k: rg[k] + rt[k] + ra[k]
    top_idx = sorted(range(nn), key=score, reverse=True)[:n]
    return [pool[k] for k in top_idx]


def pick_max_dd(p: dict) -> float:
    """单只持有期最大回撤（min low / entry - 1）。"""
    e = p["entry"]
    if not e:
        return 0.0
    min_low = min(p["lows"]) if p["lows"] else e
    return min_low / e - 1.0


def pick_stop_ret(p: dict, stop: float) -> float:
    """止损模拟：首个 low<=entry*(1+stop) 的日按 stop 价成交，否则 T+5 close。"""
    e = p["entry"]
    if not e:
        return p["fwd5"]
    trigger = e * (1.0 + stop)
    for k, low in enumerate(p["lows"]):
        if low <= trigger:
            return stop  # 次日按 stop 成交（保守，假设 fill at stop）
    return p["fwd5"]  # 未触发，持有到 T+5


def gate_on(d: str, by_date: dict) -> bool:
    lst = by_date[d]
    if len(lst) < 20:
        return False
    breadth = sum(1 for x in lst if x["up"]) / len(lst)
    srt = sorted(lst, key=lambda x: x["amt"])
    dec = max(1, len(srt) // 10)
    small = srt[:dec]
    sm5 = statistics.mean(x["past5"] for x in small)
    return breadth > 0.4 and sm5 > 0


def equity_curve(dates: list, by_date: dict) -> tuple[list, list]:
    """日组合等权收益 → 权益曲线 + 日收益序列。"""
    daily_rets: list[float] = []
    for d in dates:
        top = rank_top(by_date[d])
        if not top:
            continue
        rets = [x["fwd5"] for x in top]
        daily_rets.append(statistics.mean(rets))
    eq = [1.0]
    for r in daily_rets:
        eq.append(eq[-1] * (1.0 + r - COST))  # 扣成本
    return eq, daily_rets


def max_drawdown(eq: list) -> tuple[float, int]:
    """权益曲线 max drawdown（peak-to-trough）+ 持续天数。"""
    peak = eq[0]
    mdd = 0.0
    mdd_len = 0
    cur_len = 0
    for v in eq[1:]:
        if v > peak:
            peak = v
            cur_len = 0
        else:
            cur_len += 1
            dd = v / peak - 1.0
            if dd < mdd:
                mdd = dd
                mdd_len = cur_len
    return mdd, mdd_len


def main() -> None:
    print("loading cache (5255 stocks x 8yr)...")
    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    print(f"dates={len(all_d)} range={all_d[0]}~{all_d[-1]}\n")

    # 收集所有 picks（去涨停 top-20）
    all_picks: list = []
    for d in all_d:
        top = rank_top(by_date[d])
        if top:
            all_picks.extend(top)
    n = len(all_picks)
    print(f"=== combo-5d 风险控制审计（去涨停 top-20，{n} picks）===\n")

    # ── 维度1：单只路径回撤 ──
    mdds = [pick_max_dd(p) for p in all_picks]
    fwd5s = [p["fwd5"] for p in all_picks]
    print("【维度1 单只持有期最大回撤】（entry→持有期 min low）")
    print(f"  max_dd mean={statistics.mean(mdds)*100:+.2f}% median={statistics.median(mdds)*100:+.2f}%")
    for thr in [-0.05, -0.08, -0.10, -0.15, -0.20]:
        cnt = sum(1 for x in mdds if x <= thr)
        print(f"  max_dd<={thr*100:+.0f}%: {cnt}/{n}={cnt/n*100:.1f}%  (这些单只盘中跌穿)")
    # 最终正但盘中跌穿 <-10% 的比例（ nostop 扛住的）
    both = sum(1 for p, md in zip(all_picks, mdds) if p["fwd5"] > 0 and md <= -0.10)
    print(f"  最终赚(fwd5>0)但盘中跌穿-10%: {both}/{n}={both/n*100:.1f}%  (nostop 必须扛的心理成本)")
    print()

    # ── 维度2：组合回撤 ──
    eq_all, rets_all = equity_curve(all_d, by_date)
    mdd_all, mdd_len_all = max_drawdown(eq_all)
    # 日组合收益分布
    m_ret = statistics.mean(rets_all)
    sd_ret = statistics.pstdev(rets_all)
    # 最差单日组合
    worst_day = min(rets_all)
    worst_5 = sorted(rets_all)[:5]
    print("【维度2 组合回撤】（日组合等权 → 权益曲线 max drawdown）")
    print(f"  全历史 {len(rets_all)} 日权益终值={eq_all[-1]:.3f} (1.0起)")
    print(f"  max drawdown={mdd_all*100:+.2f}%  回撤持续={mdd_len_all} 日")
    print(f"  日组合 mean={m_ret*100:+.3f}% std={sd_ret*100:.2f}% Sharpe(年化估)= {m_ret/sd_ret*15.87:.2f}" if sd_ret else "")
    print(f"  最差单日组合={worst_day*100:+.2f}%  最差5日={[f'{x*100:+.2f}%' for x in worst_5]}")
    # 连续亏损天数
    max_streak = cur = 0
    for r in rets_all:
        if r - COST < 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0
    print(f"  最长连续亏损日数(net<0)={max_streak}")
    print()

    # ── 维度3：nostop vs 软止损 ──
    print("【维度3 nostop vs 软止损】（stop 触发次日按 stop 价成交，未触发持到 T+5）")
    # nostop baseline
    nostop_rets = [p["fwd5"] for p in all_picks]
    nostop_mean = statistics.mean(nostop_rets)
    nostop_wr = sum(1 for x in nostop_rets if x > 0) / n
    nostop_tail10 = sum(1 for x in nostop_rets if x <= -0.10) / n
    print(f"  nostop:      mean={nostop_mean*100:+.3f}% net={(nostop_mean-COST)*100:+.3f}% WR={nostop_wr*100:.1f}% tail(<-10%)={nostop_tail10*100:.1f}%")
    for stop in STOPS:
        stop_rets = [pick_stop_ret(p, stop) for p in all_picks]
        sm = statistics.mean(stop_rets)
        swr = sum(1 for x in stop_rets if x > 0) / n
        stail = sum(1 for x in stop_rets if x <= -0.10) / n
        trigger_rate = sum(1 for p in all_picks if pick_max_dd(p) <= stop) / n
        delta = sm - nostop_mean
        print(f"  stop={stop*100:+.0f}%: mean={sm*100:+.3f}% net={(sm-COST)*100:+.3f}% WR={swr*100:.1f}% tail(<-10%)={stail*100:.1f}% 触发率={trigger_rate*100:.1f}%  Δmean={delta*100:+.3f}%")
    print()

    # ── 维度4：regime 回撤 ──
    on_d = [d for d in all_d if gate_on(d, by_date)]
    off_d = [d for d in all_d if not gate_on(d, by_date)]
    print("【维度4 regime 回撤】（gate=ON/OFF 分层权益曲线 max drawdown）")
    for label, ds in [("gate=ON ", on_d), ("gate=OFF", off_d)]:
        if not ds:
            continue
        eq, rets = equity_curve(ds, by_date)
        mdd, mlen = max_drawdown(eq)
        m = statistics.mean(rets)
        wr = sum(1 for x in rets if x > 0) / len(rets) if rets else 0
        worst = min(rets) if rets else 0
        print(f"  {label}: days={len(rets):>4} mean={m*100:+.3f}% 日胜率={wr*100:.1f}% maxDD={mdd*100:+.2f}%(持续{mlen}日) 最差单日={worst*100:+.2f}% 终值={eq[-1]:.3f}")
    # 2026 单独（当前 regime 错）
    d2026 = [d for d in all_d if d.startswith("2026")]
    if d2026:
        eq26, rets26 = equity_curve(d2026, by_date)
        mdd26, mlen26 = max_drawdown(eq26)
        m26 = statistics.mean(rets26) if rets26 else 0
        print(f"  2026单独:    days={len(rets26):>4} mean={m26*100:+.3f}% maxDD={mdd26*100:+.2f}%(持续{mlen26}日) 终值={eq26[-1]:.3f}")
    print()

    # ── 综合：单只仓位上限建议 ──
    print("【仓位上限推导】（单只 max_dd 分位 → 每只仓位上限）")
    pct1 = sorted(mdds)[int(n * 0.01)]  # 1st percentile
    pct5 = sorted(mdds)[int(n * 0.05)]
    print(f"  1%最惨单只 max_dd={pct1*100:+.2f}%  5%最惨={pct5*100:+.2f}%")
    print(f"  若单只仓位 W%, 1%尾部单亏 = |{pct1*100:.1f}%|*W% → 想单亏<2%总仓 → W<{2/abs(pct1*100)*100:.1f}%/只")
    print(f"  组合 maxDD={mdd_all*100:+.2f}% × 总仓50% = 实际账户回撤 ~{abs(mdd_all)*0.5*100:.1f}%")


if __name__ == "__main__":
    main()
