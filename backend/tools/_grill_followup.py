# -*- coding: utf-8 -*-
"""Follow-up: V2 gap window (D+1close->D+2open) by lbc tier + kechuang date concentration + regime."""
from __future__ import annotations
import sys, sqlite3, statistics, json
from collections import defaultdict, Counter
from pathlib import Path
from math import erf, sqrt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir
from engine.kline_cache_store import get_bars
from tools._factor_helpers import (limit_for_code, is_yizi_t1, ev_stats,
                                     day_paired_t, COST)

ZT_DB = resolve_data_dir() / "zt_history.db"

def load_zt():
    conn = sqlite3.connect(str(ZT_DB))
    rows = [(d,c,l if l else 1) for d,c,l in conn.execute("SELECT date, code, lbc FROM zt_history")]
    conn.close(); return rows

def gap_ev(p):
    """V2 window: entry=D+1 close, exit=D+2 open. net of cost."""
    ce = p["t1_bar"].get("close"); oe = p["t2_bar"].get("open")
    if ce is None or oe is None or ce<=0 or oe<=0: return None
    return (oe-ce)/ce*100 - COST*100

def build_picks(code_cache, cal, zt_rows, lbc_lo, lbc_hi=999):
    di = {d:i for i,d in enumerate(cal)}
    picks=[]
    for zt_date,code,lbc in zt_rows:
        if lbc<lbc_lo or lbc>lbc_hi: continue
        idx = di.get(zt_date)
        if idx is None or idx+2>=len(cal): continue
        dm = code_cache.get(code)
        if not dm: continue
        t = dm.get(zt_date)
        if t is None or t.get("close") is None or t["close"]<=0: continue
        t1 = dm.get(cal[idx+1]); t2 = dm.get(cal[idx+2])
        if t1 is None or t2 is None: continue
        if t1.get("open") is None or t2.get("open") is None: continue
        is_st = t.get("isST")=="1"
        lim = limit_for_code(code, is_st)
        if is_yizi_t1(t1, t["close"], lim): continue
        picks.append({"code":code,"zt_date":zt_date,"t1_bar":t1,"t2_bar":t2,"lbc":lbc,
                      "board": ("chuangye" if code.startswith(("300","301")) else
                                "kechuang" if code.startswith(("688","689")) else
                                "bj" if code.startswith(("4","8")) else "main")})
    return picks

def cell(name, picks, ret_fn=gap_ev):
    if not picks:
        print(f"  {name:<30} n=0"); return
    rets=[ret_fn(p) for p in picks]; rets=[r for r in rets if r is not None]
    if not rets: print(f"  {name:<30} n=0 (no rets)"); return
    s=ev_stats(rets)
    bd=defaultdict(list)
    for p in picks:
        r=ret_fn(p)
        if r is not None: bd[p["zt_date"]].append(r)
    dt=day_paired_t(bd)
    print(f"  {name:<30} n={s['n']:>4} days={dt['n_days']:>3} net_EV={s['ev']:>+7.3f}% "
          f"WR={s['wr']:>5.1f}% day_t={dt['t']:>+6.2f} p={dt['p_one_sided']:.4f}")

def main():
    zt=load_zt()
    relay_codes=sorted({c for _,c,l in zt if l>=2})
    print(f"loading {len(relay_codes)} relay codes...")
    cc={}; alld=set()
    for code in relay_codes:
        bars=get_bars(code)
        if not bars: continue
        dm={b["date"]:b for b in bars if b.get("date")}
        cc[code]=dm; alld.update(dm)
    cal=sorted(alld)
    print(f"loaded {len(cc)} codes, cal {len(cal)} ({cal[0]}~{cal[-1]})")

    print(f"\n{'='*78}\n[A] V2 gap window (D+1close->D+2open, net) by lbc tier\n{'='*78}")
    print(f"  (V2 verdict was lbc>=2 merged = bull -1.66%; here decomposed + all-regime)")
    for lo,hi,lab in [(2,2,"lbc=2"),(3,3,"lbc=3"),(4,4,"lbc=4"),(5,99,"lbc>=5"),(2,99,"lbc>=2(all)"),(4,99,"lbc>=4")]:
        pk=build_picks(cc,cal,zt,lo,hi); cell(lab,pk)

    print(f"\n{'='*78}\n[B] close_ev cross-check SKIPPED (have it from _grill_factor_decomp [1])\n  close_ev: lbc=2 -0.742%net | lbc=3 -1.241% | lbc=4 -2.476% | lbc>=4 -1.954%\n{'='*78}")

    print(f"\n{'='*78}\n[C] kechuang positive cell: date concentration check\n{'='*78}")
    kc=build_picks(cc,cal,zt,2,99)
    kc=[p for p in kc if p["board"]=="kechuang"]
    mc=Counter(p["zt_date"][:7] for p in kc)
    print(f"  kechuang relay picks: {len(kc)} across {len(mc)} months")
    for m,c in sorted(mc.items()): print(f"    {m}: {c}")
    # top single days
    dc=Counter(p["zt_date"] for p in kc)
    print(f"  top 5 single days:")
    for d,c in dc.most_common(5): print(f"    {d}: {c} picks")

    print(f"\n{'='*78}\n[D] regime (bull/bear) x lbc — load regime labels\n{'='*78}")
    try:
        from tools.gap_regime_stratified import compute_regime_labels
        rm=compute_regime_labels()
        if not rm:
            print("  no regime labels available (index_ma20_regime.json missing)")
        else:
            print(f"  regime labels: {len(rm)} days, {Counter(rm.values())}")
            for tag in ["bull","bear","range"]:
                for lo,hi,lab in [(2,99,"lbc>=2"),(4,99,"lbc>=4")]:
                    pk=build_picks(cc,cal,zt,lo,hi)
                    pk=[p for p in pk if rm.get(p["zt_date"])==tag]
                    cell(f"{tag}/{lab}",pk)
    except Exception as e:
        print(f"  regime load err: {repr(e)[:150]}")

if __name__=="__main__":
    main()
