# -*- coding: utf-8 -*-
"""Grill: 对比三种 edge 定义在同 lbc>=2 picks 上的 verdict。

V1 (s203 harness): D close → D+1 open  (原 +1.04%, sealed premium)
V2 (s203 v2):      D+1 close → D+2 open (falsification -1.66%, 第二隔夜 gap)
CORRECT (_factor_helpers): T+1 open → T+2 close (实际可买 relay trade)

若 V2 falsified 而 CORRECT 不同 → V2 是 category error, 证否不成立。
不迎合不防御, 按 evidence 走。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._factor_helpers import (
    load_kline_db, load_zt, build_picks_generic,
    close_ev_basic, close_ev_stop, ev_stats, day_paired_t,
    walk_forward, verdict_for, COST, limit_for_code, is_yizi_t1,
)
from collections import defaultdict

def v1_ev(p):
    """D close → D+1 open. entry=D close (sealed), exit=D+1 open."""
    # D close = t_close (limit-up day close)
    d_close = p["t_close"]
    d1_open = p["t1_bar"]["open"]
    if d_close <= 0 or d1_open <= 0:
        return None
    return (d1_open - d_close) / d_close * 100

def v2_ev(p):
    """D+1 close → D+2 open. (V2 falsification edge)"""
    d1_close = p["t1_bar"]["close"]
    d2_open = p["t2_bar"]["open"]
    if d1_close <= 0 or d2_open <= 0:
        return None
    return (d2_open - d1_close) / d1_close * 100

def correct_ev(p):
    """T+1 open → T+2 close. (actual buyable relay trade = close_ev_basic)"""
    return close_ev_basic(p)

def run_subset(name, picks, ev_fn, label):
    if not picks:
        print(f"\n{name} [{label}]: no picks")
        return {}
    rets = [ev_fn(p) for p in picks]
    rets = [r for r in rets if r is not None]
    if not rets:
        print(f"\n{name} [{label}]: no valid rets")
        return {}
    s = ev_stats(rets)
    net = s["ev"] - COST*100
    by_date = defaultdict(list)
    for p in picks:
        r = ev_fn(p)
        if r is not None:
            by_date[p["zt_date"]].append(r)
    dt = day_paired_t(by_date)
    wf = walk_forward(picks, ev_fn)
    print(f"\n{name} [{label}]: n={s['n']} days={dt['n_days']} "
          f"gross_EV={s['ev']}% net_EV={net:.3f}% WR={s['wr']}% "
          f"day_t={dt['t']} day_p={dt['p_one_sided']}")
    if wf.get("status")=="ok":
        tr,te = wf["train_ev"],wf["test_ev"]
        print(f"  WF: train_EV={tr['ev']}% test_EV={te['ev']}% test_day_t={wf['test_day_t']['t']} "
              f"test_day_p={wf['test_day_t']['p_one_sided']} n_train_d={wf['n_train_dates']} n_test_d={wf['n_test_dates']}")
    v = verdict_for(s["ev"], dt["t"], dt["p_one_sided"],
                    wf.get("status","no"), wf.get("train_ev",{}).get("ev",0),
                    wf.get("test_ev",{}).get("ev",0), wf.get("test_day_t",{}).get("p_one_sided",1),
                    dt["n_days"], net, name, n_cross_factor=1)
    return {"stats":s, "dt":dt, "wf":wf, "verdict":v, "net":net}

def main():
    code_map, all_dates = load_kline_db()
    calendar = sorted(all_dates)
    zt_rows = load_zt()
    print(f"kline codes={len(code_map)} calendar_days={len(calendar)} zt_rows={len(zt_rows)}")
    print(f"calendar range: {calendar[0]} → {calendar[-1]}")

    # lbc>=2 picks (relay), using FIXED helpers (T+1 一字 filtered)
    picks_lbc2 = build_picks_generic(code_map, calendar, zt_rows,
                                     filter_fn=lambda c,lbc,t,t1,t2: lbc>=2)
    print(f"\n=== relay lbc>=2 picks: {len(picks_lbc2)} ===")
    # also split by lbc tier
    picks_l2 = [p for p in picks_lbc2 if p["lbc"]==2]
    picks_l3 = [p for p in picks_lbc2 if p["lbc"]==3]
    picks_l4 = [p for p in picks_lbc2 if p["lbc"]>=4]

    print(f"lbc==2: {len(picks_l2)}, lbc==3: {len(picks_l3)}, lbc>=4: {len(picks_l4)}")

    print("\n" + "="*70)
    print("ALL lbc>=2 — 三种 edge 定义对比")
    print("="*70)
    run_subset("relay-all", picks_lbc2, v1_ev, "V1 D-close→D+1-open")
    run_subset("relay-all", picks_lbc2, v2_ev, "V2 D+1-close→D+2-open")
    run_subset("relay-all", picks_lbc2, correct_ev, "CORRECT T+1-open→T+2-close")

    print("\n" + "="*70)
    print("anti-slope 检查: lbc 越高 edge 越负? (单调=真信号方向)")
    print("="*70)
    for tier_name, ps in [("lbc==2",picks_l2),("lbc==3",picks_l3),("lbc>=4",picks_l4)]:
        run_subset(tier_name, ps, correct_ev, "CORRECT")
        run_subset(tier_name, ps, v2_ev, "V2")

    print("\n" + "="*70)
    print("stop variant (CORRECT edge + -3% stop + R6 gap-through)")
    print("="*70)
    if picks_lbc2:
        stop_rets = [close_ev_stop(p) for p in picks_lbc2]
        stop_rets_c = [r[0] for r in stop_rets if r is not None]
        if stop_rets_c:
            ss = ev_stats(stop_rets_c)
            net_stop = ss["ev"] - COST*100
            by_date = defaultdict(list)
            for p in picks_lbc2:
                r = close_ev_stop(p)
                if r is not None:
                    by_date[p["zt_date"]].append(r[0])
            sdt = day_paired_t(by_date)
            print(f"relay-all [stop]: n={ss['n']} days={sdt['n_days']} "
                  f"gross_EV={ss['ev']}% net_EV={net_stop:.3f}% WR={ss['wr']}% "
                  f"day_t={sdt['t']} day_p={sdt['p_one_sided']}")

if __name__ == "__main__":
    main()
