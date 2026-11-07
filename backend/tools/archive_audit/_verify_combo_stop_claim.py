# -*- coding: utf-8 -*-
"""Adversarial verification of the '-10% stop = near-free tail insurance' claim.

Key refutation angle: the original script defines 误杀 (false kill) as ONLY
nostop > 0 (would have ended positive). But a stop at -10% that sells at -10%
when the stock would have recovered to -5% is ALSO harmed by the stop. The
broader 误杀 should be nostop > stop (ended better than the stop price).
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
COST = 0.004
TOP_N = 20


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
            if today_ret >= bl:
                continue
            t1_close = closes[i + 1]
            t5_close = closes[i + 5]
            if not t1_close or not t5_close:
                continue
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


def rank_top(lst, n=TOP_N):
    if len(lst) < n * 10:
        return None
    nn = len(lst)
    st = sorted(range(nn), key=lambda k: lst[k]["tr"])
    sa = sorted(range(nn), key=lambda k: lst[k]["amt"])
    rt = {o: r / nn for r, o in enumerate(st)}
    ra = {o: 1 - r / nn for r, o in enumerate(sa)}
    top_idx = sorted(range(nn), key=lambda k: rt[k] + ra[k], reverse=True)[:n]
    return [lst[k] for k in top_idx]


def stop_ret_realistic(p, stop):
    e = p["entry"]
    if not e:
        return p["nostop"]
    trigger = e * (1.0 + stop)
    for low, opn in p["path"]:
        if low <= trigger:
            fill = opn if (opn and opn <= trigger) else trigger
            return (fill - e) / e
    return p["nostop"]


def trigger_maxdd(p):
    e = p["entry"]
    if not e or not p["path"]:
        return 0.0
    min_low = min(low for low, _ in p["path"])
    return min_low / e - 1.0


def main():
    print("loading cache...", flush=True)
    by_date = build_by_date()
    all_d = sorted(by_date.keys())
    all_picks = []
    for d in all_d:
        top = rank_top(by_date[d])
        if top:
            all_picks.extend(top)
    n = len(all_picks)
    print(f"dates={len(all_d)} picks={n}", flush=True)

    STOP = -0.10
    nostop_rets = [p["nostop"] for p in all_picks]
    stop_rets = [stop_ret_realistic(p, STOP) for p in all_picks]
    mdds = [trigger_maxdd(p) for p in all_picks]

    # --- Claim verification ---
    print("\n=== CLAIM VERIFICATION: -10% stop ===\n")

    # 1. Delta net
    nostop_mean = statistics.mean(
        [statistics.mean(p["nostop"] for p in rank_top(by_date[d]))
         for d in all_d if rank_top(by_date[d])]
    )
    stop_mean = statistics.mean(
        [statistics.mean(stop_ret_realistic(p, STOP) for p in rank_top(by_date[d]))
         for d in all_d if rank_top(by_date[d])]
    )
    delta_net = (stop_mean - COST) - (nostop_mean - COST)
    print(f"[1] Δnet = {delta_net*100:+.4f}% (claim: -0.010%)")
    print(f"    nostop net={ (nostop_mean-COST)*100:+.4f}%  stop net={ (stop_mean-COST)*100:+.4f}%")

    # 2. Trigger rate
    triggered = [p for p in all_picks if trigger_maxdd(p) <= STOP]
    trig_rate = len(triggered) / n
    print(f"\n[2] 触发率 = {trig_rate*100:.2f}% ({len(triggered)}/{n})  (claim: 4.2% / 1735)")

    # 3. 误杀率 - THE KEY ISSUE
    # Original (narrow): nostop > 0
    killed_narrow = sum(1 for p in triggered if p["nostop"] > 0)
    # Broader: nostop > stop (would have ended better than stop price)
    killed_broad = sum(1 for p in triggered if p["nostop"] > STOP)
    # Also check: nostop > stop_ret (would have ended better than what stop actually got)
    killed_broad2 = sum(1 for i, p in enumerate(triggered)
                        if p["nostop"] > stop_ret_realistic(p, STOP))
    print(f"\n[3] 误杀率 (KEY REFUTATION):")
    print(f"    Narrow (nostop>0, original):    {killed_narrow}/{len(triggered)} = {killed_narrow/len(triggered)*100:.1f}%  (claim: 5% / 81)")
    print(f"    Broad (nostop>stop=-10%):        {killed_broad}/{len(triggered)} = {killed_broad/len(triggered)*100:.1f}%")
    print(f"    Broadest (nostop>stop_ret):      {killed_broad2}/{len(triggered)} = {killed_broad2/len(triggered)*100:.1f}%")
    print(f"    => '95% 真救' framing: {killed_broad/len(triggered)*100:.0f}% triggered ended <=-10% nostop")
    print(f"       but {killed_broad-killed_narrow} picks ended between -10% and 0% — stop locked in -10% when loss would be smaller")

    # 4. Distribution of nostop outcomes for triggered picks
    print(f"\n[4] Triggered picks nostop outcome distribution:")
    buckets = [(-99, -0.20), (-0.20, -0.15), (-0.15, -0.10), (-0.10, -0.05),
               (-0.05, 0), (0, 0.05), (0.05, 0.10), (0.10, 99)]
    for lo, hi in buckets:
        cnt = sum(1 for p in triggered if lo <= p["nostop"] < hi)
        if cnt:
            print(f"    nostop [{lo*100:+.0f}%, {hi*100:+.0f}%): {cnt} ({cnt/len(triggered)*100:.1f}%)")

    # 5. Per-pick Δ: stop_ret - nostop (positive = stop helped)
    deltas = [stop_ret_realistic(p, STOP) - p["nostop"] for p in triggered]
    helped = sum(1 for d in deltas if d > 0)
    hurt = sum(1 for d in deltas if d < 0)
    same = sum(1 for d in deltas if d == 0)
    print(f"\n[5] Per-pick Δ (stop_ret - nostop) for triggered:")
    print(f"    Helped (stop_ret > nostop): {helped} ({helped/len(triggered)*100:.1f}%)")
    print(f"    Hurt   (stop_ret < nostop): {hurt} ({hurt/len(triggered)*100:.1f}%)")
    print(f"    Same   (stop_ret = nostop): {same} ({same/len(triggered)*100:.1f}%)")
    print(f"    Mean Δ = {statistics.mean(deltas)*100:+.3f}%  Median Δ = {statistics.median(deltas)*100:+.3f}%")

    # 6. nostop<-10% deep group
    deep = [(p, stop_ret_realistic(p, STOP)) for p in all_picks if p["nostop"] <= -0.10]
    if deep:
        nm = statistics.mean(x[0]["nostop"] for x in deep)
        sm = statistics.mean(x[1] for x in deep)
        gap_worse = sum(1 for p, s in deep if s < p["nostop"])
        print(f"\n[6] nostop<=-10% group: {len(deep)} picks (claim: 1290)")
        print(f"    nostop mean={nm*100:+.2f}%  stop mean={sm*100:+.2f}%  (claim: -14.28% → -11.30%)")
        print(f"    削亏 = {(sm-nm)*100:+.2f}pp (claim: +2.98pp)")
        print(f"    gap穿仓(stop反更差): {gap_worse}/{len(deep)} = {gap_worse/len(deep)*100:.0f}% (claim: 6%)")

    # 7. Worst single day
    print(f"\n[7] Worst single day (portfolio level):")
    worst_nostop = -99
    worst_stop = -99
    worst_date_n = ""
    worst_date_s = ""
    for d in all_d:
        top = rank_top(by_date[d])
        if not top:
            continue
        mn = statistics.mean(p["nostop"] for p in top)
        ms = statistics.mean(stop_ret_realistic(p, STOP) for p in top)
        if mn < worst_nostop:
            worst_nostop = mn
            worst_date_n = d
        if ms < worst_stop:
            worst_stop = ms
            worst_date_s = d
    print(f"    nostop worst = {worst_nostop*100:+.2f}% on {worst_date_n} (claim: -16.82%)")
    print(f"    stop-10% worst = {worst_stop*100:+.2f}% on {worst_date_s} (claim: -11.59%)")
    print(f"    NOTE: are they the same day? {worst_date_n == worst_date_s}")
    # Also check: on the nostop worst day, what does stop give?
    top_wn = rank_top(by_date[worst_date_n])
    if top_wn:
        stop_on_worst_n = statistics.mean(stop_ret_realistic(p, STOP) for p in top_wn)
        print(f"    On nostop-worst day ({worst_date_n}), stop-10% gives {stop_on_worst_n*100:+.2f}%")

    # 8. Tail count: does -10% stop reduce <-10% count?
    nostop_t10 = sum(1 for x in nostop_rets if x <= -0.10) / n
    stop_t10 = sum(1 for x in stop_rets if x <= -0.10) / n
    print(f"\n[8] Tail <-10% count: nostop={nostop_t10*100:.1f}%  stop-10%={stop_t10*100:.1f}%  (claim: 3.1% vs 3.4%)")
    print(f"    Stop does NOT reduce <-10% count: {stop_t10 >= nostop_t10}")

    # 9. Alternative: what about -8% stop? (claim says -5% Δnet -0.057%)
    for s in [-0.05, -0.08, -0.15]:
        sm = statistics.mean(
            [statistics.mean(stop_ret_realistic(p, s) for p in rank_top(by_date[d]))
             for d in all_d if rank_top(by_date[d])]
        )
        dn = (sm - COST) - (nostop_mean - COST)
        sr = [stop_ret_realistic(p, s) for p in all_picks]
        st10 = sum(1 for x in sr if x <= -0.10) / n
        trig = sum(1 for p in all_picks if trigger_maxdd(p) <= s)
        print(f"\n[9-alt] stop={s*100:.0f}%: Δnet={dn*100:+.4f}%  tail<-10%={st10*100:.1f}%  triggered={trig} ({trig/n*100:.1f}%)")

    # 10. The real question: is the stop "near-free" or does it have hidden cost?
    # Count picks where stop HURT (stop_ret < nostop) by magnitude
    hurt_picks = [(p, stop_ret_realistic(p, STOP) - p["nostop"])
                  for p in all_picks if stop_ret_realistic(p, STOP) < p["nostop"]]
    if hurt_picks:
        hurt_amts = [h for _, h in hurt_picks]
        print(f"\n[10] Hidden cost: {len(hurt_picks)} picks where stop hurt")
        print(f"     Mean harm = {statistics.mean(hurt_amts)*100:+.3f}%  Median = {statistics.median(hurt_amts)*100:+.3f}%")
        print(f"     Total harm = {sum(hurt_amts)*100:.2f}% across {len(hurt_picks)} picks")
    helped_picks = [(p, stop_ret_realistic(p, STOP) - p["nostop"])
                    for p in all_picks if stop_ret_realistic(p, STOP) > p["nostop"]]
    if helped_picks:
        helped_amts = [h for _, h in helped_picks]
        print(f"     vs {len(helped_picks)} picks where stop helped")
        print(f"     Mean help = {statistics.mean(helped_amts)*100:+.3f}%  Total help = {sum(helped_amts)*100:.2f}%")
        print(f"     Net effect = {(sum(helped_amts)+sum(hurt_amts))*100:.4f}% across {n} picks")


if __name__ == "__main__":
    main()
