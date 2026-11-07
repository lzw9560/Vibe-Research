# -*- coding: utf-8 -*-
"""Stage 3: 验证盈亏平衡 + 扫描更多组合找正 EV 甜点。"""
# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
import sqlite3, json, math, statistics, sys
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir
_DATA = resolve_data_dir()
KLINE_DB = str(_DATA / "baostock_kline_cache.db")
ZT_DB = str(_DATA / "zt_history.db")
zdb = sqlite3.connect(ZT_DB); zcur = zdb.cursor(); zcur.execute("SELECT date, code FROM zt_history")
zt_by_date = defaultdict(set)
for d, c in zcur.fetchall(): zt_by_date[d].add(c)
zdb.close()
cal = sorted(zt_by_date.keys()); date_idx = {d:i for i,d in enumerate(cal)}
def next_td(d):
    i=date_idx.get(d); return cal[i+1] if i is not None and i+1<len(cal) else None
T_MIN, T_MAX = "2025-12-25", "2026-09-17"
kdb = sqlite3.connect(KLINE_DB); kcur = kdb.cursor(); kcur.execute("SELECT code, bars_json FROM kline")
code_bars={}
for code, bj in kcur.fetchall():
    try: bars=json.loads(bj)
    except: continue
    if isinstance(bars,list) and bars: code_bars[code]=bars
kdb.close()
code_map={}; code_dates={}
for code,bars in code_bars.items():
    m={b["date"]:b for b in bars if b.get("date")}
    if m: code_map[code]=m; code_dates[code]=sorted(m.keys())
def vr5(code,idx):
    ds=code_dates[code]; m=code_map[code]; tbar=m[ds[idx]]
    if tbar.get("volume") is None: return None
    prev=ds[max(0,idx-5):idx]
    if len(prev)<5: return None
    pv=[m[p].get("volume") for p in prev]
    if any(v is None or v==0 for v in pv): return None
    return tbar["volume"]/(sum(pv)/5.0)
def cir(b):
    h,l,c=b.get("high"),b.get("low"),b.get("close")
    return (c-l)/(h-l) if h and l and c and h!=l else None

recs=[]
for code,ds in code_dates.items():
    m=code_map[code]
    for idx,d in enumerate(ds):
        if d<T_MIN or d>T_MAX: continue
        nd=next_td(d)
        if nd is None: continue
        bar=m[d]
        if code in zt_by_date.get(d,()): continue
        t1=m.get(nd)
        if t1 is None: continue
        entry=bar.get("close")
        if not entry or entry<=0: continue
        pct=bar.get("pctChg");turn=bar.get("turn");v=vr5(code,idx);c=cir(bar)
        if None in (pct,turn,v,c): continue
        t1c=t1.get("close")
        if t1c is None: continue
        t1_zt=1 if code in zt_by_date.get(nd,()) else 0
        recs.append((pct,turn,v,c,entry,t1c,t1_zt,d,code))

def ev(mask):
    sub=[r for r in recs if mask(r)]
    n=len(sub)
    if n==0: return
    rets=[(r[5]-r[4])/r[4] for r in sub]  # sell T+1 close
    mean=statistics.mean(rets); wr=sum(1 for x in rets if x>0)/n
    zt=sum(r[6] for r in sub)
    # breakeven: if losers avg L and winners avg W, hit=h; need h*W_real >= (1-h)*L_real where W_real~+12.5%
    zt_picks=[r for r in sub if r[6]]; nzt_picks=[r for r in sub if not r[6]]
    w_zt=statistics.mean([(r[5]-r[4])/r[4] for r in zt_picks]) if zt_picks else 0
    l_nzt=statistics.mean([(r[5]-r[4])/r[4] for r in nzt_picks]) if nzt_picks else 0
    h=zt/n
    # EV if we could capture +12.5% on ZT and actual on non-ZT:
    ev_opt = h*0.125 + (1-h)*l_nzt
    print(f"n={n:6d} hit={h*100:4.1f}% mean={mean*100:6.2f}% WR={wr*100:4.1f}% ZT_win={w_zt*100:5.2f}% nZT_loss={l_nzt*100:5.2f}% EV@ifZT+12.5%={ev_opt*100:6.2f}%")

print("=== 扫描组合（sell@T+1 close）===")
ev(lambda r: True)
ev(lambda r: 5<=r[0]<=9.3 and r[2]>2)                    # mom+vol
ev(lambda r: 5<=r[0]<=9.3 and 10<=r[1]<=20)              # mom+midturn
ev(lambda r: 5<=r[0]<=9.3 and r[2]>2 and 10<=r[1]<=20)   # mom+midturn+vol
ev(lambda r: 4<=r[0]<=8 and r[2]>1.5 and r[1]>8)        # balanced
ev(lambda r: 6<=r[0]<=9.3 and r[2]>2 and r[3]>0.7)       # strong+vol+closeHigh
ev(lambda r: 8<=r[0]<=9.3 and r[2]>2)                    # near-ZT strong
ev(lambda r: r[0]<-7 and r[2]>2)                         # 大跌反转
ev(lambda r: r[0]<-7 and r[1]>10)                        # 大跌+高换手

print("\n=== 盈亏平衡分析（TOP signal turn>20&vr5>2）===")
# need hit rate h such that h*W + (1-h)*L = 0 → h = -L/(W-L)
L=-1.16/100; W=12.48/100  # from stage 2
h_be = -L/(W-L)
print(f"loser avg L={L*100:.2f}% winner avg W={W*100:.2f}% → breakeven hit rate = {h_be*100:.1f}%")
print(f"actual hit rate = 4.4% → 需要 hit rate 提升到 {h_be*100:.1f}% (×{h_be/0.044:.1f}) 才能盈亏平衡")
print(f"即 lift 需从 5.28x 提升到 {h_be/0.00822:.1f}x (base 0.822%)")
