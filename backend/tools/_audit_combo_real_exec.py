# -*- coding: utf-8 -*-
"""combo real-execution edge 钉死（2026-11-04，高3，workflow w14fiyl16 建议）。

生产 mode=filtered 口径（剔 ST+920+涨停 ratio 口径）+ real-execution（T+1 open→T+5 close）。
对比 close-to-close（T close→T+5 close）。钉死 entry gap 吃多少 edge。

gate 判定：net real-exec > +0.3% = edge 存活可上小钱；≤+0.15% = 执行幻觉 combo 降级 paper-only。
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


def board_limit(code: str) -> float:
    c = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    if c.startswith("30") or c.startswith("68"):
        return 0.20
    if c.startswith("8") or c.startswith("4"):
        return 0.30
    return 0.10


def build_by_date() -> dict:
    """每日：{code, gap, tr, amt, real_exec, close_close, entry_gap}，生产 mode=filtered 过滤。"""
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
            isST = str(bars[i].get("isST", "0"))
            if not prev_c or not c or not o or not amt:
                continue
            ma60 = statistics.mean(float(bars[j].get("close", 0) or 0) for j in range(i - 60, i))
            if not ma60:
                continue
            today_ret = (c - prev_c) / prev_c
            gap = (o - prev_c) / prev_c
            # 生产 mode=filtered 过滤（复用 commander_runner.load_combo_5d_today 逻辑）
            if isST not in ("0", "", "0.0"):
                continue  # 剔 ST
            if code.startswith("920"):
                continue  # 剔北交
            if today_ret >= bl:
                continue  # 剔涨停（ratio 口径 (c-prev_c)/prev_c >= board_limit）
            t1_bar = bars[i + 1]
            t1_open = float(t1_bar.get("open", 0) or 0)
            t1_high = float(t1_bar.get("high", 0) or 0)
            t1_low = float(t1_bar.get("low", 0) or 0)
            t1_vol = float(t1_bar.get("volume", 0) or 0)
            t5_close = float(bars[i + 5].get("close", 0) or 0)
            t_close = c
            if not t1_open or not t5_close:
                continue
            # P0 修高危④(2026-11-06 backtest-guard)：T+1 入场日涨停/停牌检查
            # 信号日(T)已滤涨停，但入场日(T+1)未滤——T+1 一字涨停/停牌不可买但回测成交，系统性高估可交易 picks
            if t1_vol <= 0:
                continue  # T+1 停牌(volume=0)不可买
            t1_gap = (t1_open - t_close) / t_close if t_close else 0  # T+1 open vs T 日 close（A 股涨停基准是前日收盘）
            if t1_gap >= bl:
                continue  # T+1 open 涨停(高开>=board_limit)不可买
            if t1_open == t1_high == t1_low and t1_gap >= bl * 0.98:
                continue  # T+1 一字板(open=high=low 近涨停)不可买
            real_exec = (t5_close - t1_open) / t1_open  # T+1 open → T+5 close
            close_close = (t5_close - t_close) / t_close  # T close → T+5 close
            by_date[bars[i].get("date", "")].append({
                "code": code, "gap": gap, "tr": today_ret, "amt": amt,
                "real_exec": real_exec, "close_close": close_close,
                "entry_gap": (t1_open - t_close) / t_close,  # T+1 open vs T close
            })
    return by_date


def rank_top(lst: list, n: int = TOP_N) -> list | None:
    if len(lst) < n * 10:
        return None
    nn = len(lst)
    sg = sorted(range(nn), key=lambda k: lst[k]["gap"])
    st = sorted(range(nn), key=lambda k: lst[k]["tr"])
    sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
    rg = {o: r / nn for r, o in enumerate(sg)}
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    score = lambda k: rg[k] + rt[k] + ra[k]
    top_idx = sorted(range(nn), key=score, reverse=True)[:n]
    return [lst[k] for k in top_idx]


def stats(dates: list, by_date: dict, field: str) -> dict | None:
    daily_mean, daily_median, all_picks = [], [], []
    for d in dates:
        top = rank_top(by_date[d])
        if not top:
            continue
        rets = [x[field] for x in top]
        daily_mean.append(statistics.mean(rets))
        daily_median.append(statistics.median(rets))
        all_picks.extend(rets)
    if not daily_mean:
        return None
    m = statistics.mean(daily_mean)
    med = statistics.mean(daily_median)
    wr = sum(1 for x in all_picks if x > 0) / len(all_picks)
    std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
    se = std / (len(daily_mean) ** 0.5) if daily_mean else 0
    t = m / se if se > 0 else 0
    return {"n_days": len(daily_mean), "n_picks": len(all_picks),
            "mean": m, "median": med, "wr": wr, "net": m - COST, "t": t}


def main() -> None:
    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    print(f"\n=== combo real-execution edge（生产 mode=filtered，{len(all_d)} 日 {all_d[0]}~{all_d[-1]}）===\n")

    for label, field in [("close-to-close (T close→T+5 close)", "close_close"),
                         ("real-execution (T+1 open→T+5 close)", "real_exec")]:
        r = stats(all_d, by_date, field)
        if r:
            print(f"【{label}】")
            print(f"  days={r['n_days']} picks={r['n_picks']}")
            print(f"  mean={r['mean']*100:+.3f}% median={r['median']*100:+.3f}% WR={r['wr']*100:.1f}% net={r['net']*100:+.3f}% t={r['t']:.2f}")
    print()

    # entry gap 分布
    picks = []
    for d in all_d:
        top = rank_top(by_date[d])
        if top:
            picks.extend([x["entry_gap"] for x in top])
    if picks:
        n = len(picks)
        print(f"【entry gap 分布】（T+1 open vs T close，{n} picks）")
        print(f"  mean={statistics.mean(picks)*100:+.3f}% median={statistics.median(picks)*100:+.3f}%")
        print(f"  >0(T+1高于T收):{sum(1 for x in picks if x>0)/n*100:.1f}%  >+1%:{sum(1 for x in picks if x>0.01)/n*100:.1f}%  <-1%:{sum(1 for x in picks if x<-0.01)/n*100:.1f}%")

    cc = stats(all_d, by_date, "close_close")
    re = stats(all_d, by_date, "real_exec")
    if cc and re:
        eaten = cc["mean"] - re["mean"]
        print(f"\n【entry gap 吃 edge】close-close {cc['mean']*100:+.3f}% → real-exec {re['mean']*100:+.3f}% = 吃掉 {eaten*100:+.3f}%")
        print(f"  median: {cc['median']*100:+.3f}% → {re['median']*100:+.3f}%（real-exec median 归零=变 lottery）")
        net_re = re["net"]
        if net_re > 0.003:
            verdict = "✅ net >+0.3% edge 存活可上小钱"
        elif net_re <= 0.0015:
            verdict = "⚠️ net ≤+0.15% 执行幻觉 combo 降级 paper-only 不上真钱"
        else:
            verdict = "🟡 0.15-0.3% 灰区 60天前向定"
        print(f"  net real-exec = {net_re*100:+.3f}% → {verdict}")


if __name__ == "__main__":
    main()
