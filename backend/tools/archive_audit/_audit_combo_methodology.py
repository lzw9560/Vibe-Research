# -*- coding: utf-8 -*-
"""Methodology compliance: DSR / MinTRL / PBO-estimate / effective-rank for combo.

One DB pass -> close-to-close daily returns + real-exec daily returns -> moments -> DSR/MinTRL.
Plus a simple PBO estimate via multiple combinatorial splits (not single split).
"""
import json, sqlite3, statistics, math
from collections import defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

DB = resolve_data_dir() / "baostock_kline_cache.db"
COST = 0.004
TOP_N = 20

def board_limit(code):
    c = code.replace("sz.","").replace("sh.","").replace("bj.","")
    if c.startswith("30") or c.startswith("68"): return 0.20
    if c.startswith("8") or c.startswith("4"): return 0.30
    return 0.10

print("loading...", flush=True)
conn = sqlite3.connect(str(DB))
rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
conn.close()
print(f"stocks={len(rows)}", flush=True)

by_date = defaultdict(list)
nd = 0
for code, bj in rows:
    try:
        bars = sorted(json.loads(bj), key=lambda b: b.get("date",""))
    except Exception:
        continue
    nb = len(bars)
    if nb < 70:
        continue
    bl = board_limit(code)
    closes = [0.0]*nb; opens=[0.0]*nb; amts=[0.0]*nb
    for j in range(nb):
        closes[j]=float(bars[j].get("close",0) or 0)
        opens[j]=float(bars[j].get("open",0) or 0)
        amts[j]=float(bars[j].get("amount",0) or 0)
    cs=[0.0]*(nb+1)
    for j in range(nb): cs[j+1]=cs[j]+closes[j]
    for i in range(60, nb-5):
        prev_c=closes[i-1]; o=opens[i]; c=closes[i]; amt=amts[i]
        if not prev_c or not c or not o: continue
        ma60=(cs[i]-cs[i-60])/60.0
        if not ma60: continue
        tr=(c-prev_c)/prev_c
        gap=(o-prev_c)/prev_c
        if tr>=bl: continue  # filtered mode
        t1o=float(bars[i+1].get("open",0) or 0); t1v=float(bars[i+1].get("volume",0) or 0)
        t5c=closes[i+5]
        if not t1o or not t5c: continue
        t1_gap=(t1o-c)/c
        if t1v<=0 or t1_gap>=bl: continue  # T+1 unbuyable filter
        re=(t5c-t1o)/t1o
        cc=(t5c-c)/c
        by_date[bars[i].get("date","")].append({"gap":gap,"tr":tr,"amt":amt,"re":re,"cc":cc})
    nd+=1
    if nd%1000==0: print(f"  {nd}/{len(rows)}", flush=True)

all_d=sorted(by_date.keys())
print(f"dates={len(all_d)} {all_d[0]}~{all_d[-1]}", flush=True)

def rank_top(lst):
    if len(lst)<TOP_N*10: return None
    n=len(lst)
    sg=sorted(range(n),key=lambda k:lst[k]["gap"])
    st=sorted(range(n),key=lambda k:lst[k]["tr"])
    sa=sorted(range(n),key=lambda k:lst[k]["amt"])
    rg={o:r/n for r,o in enumerate(sg)}
    rt={o:r/n for r,o in enumerate(st)}
    ra={o:1-r/n for r,o in enumerate(sa)}
    top=sorted(range(n),key=lambda k:rg[k]+rt[k]+ra[k],reverse=True)[:TOP_N]
    return [lst[k] for k in top]

def daily_series(dates, field):
    out=[]
    for d in dates:
        t=rank_top(by_date[d])
        if not t: continue
        out.append(statistics.mean(x[field] for x in t))
    return out

# close-to-close and real-exec full series
cc_full = daily_series(all_d,"cc")
re_full = daily_series(all_d,"re")

def moments(series):
    n=len(series); m=statistics.mean(series)
    sd=statistics.pstdev(series) if n>1 else 0
    sr=m/sd if sd>0 else 0
    if n<4: return n,m,sd,sr,0,3
    s=sum((x-m)**3 for x in series)/(n*sd**3) if sd>0 else 0
    k=sum((x-m)**4 for x in series)/(n*sd**4) if sd>0 else 3
    return n,m,sd,sr,s,k

# NW t
def nw_t(series, min_lag=5):
    n=len(series)
    if n<5: return 0.0
    m=statistics.mean(series); g0=statistics.pvariance(series)
    lag=max(min_lag,int(4*(n/100)**(2/9))); lag=min(lag,n-1)
    s=g0
    for l in range(1,lag+1):
        cov=sum((series[t]-m)*(series[t+l]-m) for t in range(n-l))/n
        s+=2*(1-l/(lag+1))*cov
    if s<=0: return 0.0
    return m/((s/n)**0.5)

print("\n=== MOMENTS + DSR ===")
EULER=0.5772156649015328606
def norm_cdf(z): return 0.5*math.erfc(-z/math.sqrt(2))
def norm_ppf(p):
    # inverse via rational approx (Acklam) good enough
    import struct
    a=[-3.963684074e1,2.209460984e2,-2.759993724e2,1.383577519e2,-3.066477139e1,2.506628277]
    b=[-5.447605099e1,1.615858833e2,-1.555989986e2,6.680131189e1,-1.328068155e1]
    c=[-7.784894002e-3,-3.223964535e-1,-2.400758277,0.0,-2.400758277*0+1]
    # simpler: bisection
    lo,hi=-10,10
    for _ in range(200):
        mid=(lo+hi)/2
        if norm_cdf(mid)<p: lo=mid
        else: hi=mid
    return (lo+hi)/2

def expected_max_sr(v, n_trials):
    if n_trials<2: return 0.0
    v=max(v,0.0); g=EULER
    z1=norm_ppf(1-1/n_trials); z2=norm_ppf(1-1/(n_trials*math.e))
    return math.sqrt(v)*((1-g)*z1+g*z2)

def psr(obs,bench,n,sk,ku):
    if n<2: return float('nan')
    denom=max(1-sk*obs+((ku-1)/4)*obs**2,1e-12)
    se=math.sqrt(denom/(n-1))
    return norm_cdf((obs-bench)/se)

def mintrl(obs,bench,sk,ku,conf=0.95):
    if obs<=bench: return float('inf')
    z=norm_ppf(conf)
    num=max(1-sk*obs+((ku-1)/4)*obs**2,1e-12)
    return 1+num*(z/(obs-bench))**2

for label, series in [("close-to-close",cc_full),("real-exec(T+1open)",re_full)]:
    net=[x-COST for x in series]
    n,m,sd,sr,sk,ku=moments(net)
    tnw=nw_t(net)
    print(f"\n[{label}] n={n} mean={m*100:+.4f}% sd={sd*100:.3f}% SR_period={sr:.4f} SR_ann={sr*math.sqrt(252):.3f}")
    print(f"  skew={sk:.3f} kurt(non-excess)={ku:.3f} t_nw={tnw:.3f}")
    # DSR with various trial counts
    sr_var = max(1-sk*sr+((ku-1)/4)*sr**2,1e-12)/max(n-1,1)  # fallback lower-bound var
    for ntr in [50,100,300]:
        sr0=expected_max_sr(sr_var,ntr)
        d=psr(sr,sr0,n,sk,ku)
        print(f"  DSR n_trials={ntr}: E[maxSR]={sr0:.5f} -> PSR(DSR)={d:.4f} {'PASS' if d>=0.95 else 'FAIL'}")
    mt=mintrl(sr,0,sk,ku)
    print(f"  MinTRL(SR>0, 95%)={mt:.0f} days  (have {n} days) -> {'enough' if n>=mt else 'NOT ENOUGH'}")
    # Bonferroni thresholds
    for ntr in [50,100,300]:
        z2=norm_ppf(1-0.025/ntr)
        print(f"  Bonferroni x{ntr} two-sided z-thresh={z2:.3f}  t_nw={tnw:.3f} -> {'PASS' if tnw>z2 else 'FAIL'}")

# PBO estimate: split into N blocks, combinatorial
print("\n=== PBO ESTIMATE (combinatorial, 8 blocks) ===")
import itertools
re_test = daily_series([d for d in all_d if d>="2023-01-01"],"re")
N=8
blk=len(re_test)//N
blocks=[re_test[i*blk:(i+1)*blk] for i in range(N)]
# For each combination of 4 train / 4 test: is mean(train)>0 and which block ranks best in train vs test
if len(blocks)==N:
    combos=list(itertools.combinations(range(N),N//2))
    pbo_count=0; total=0
    train_means=[]; test_means=[]
    for train_idx in combos:
        test_idx=tuple(i for i in range(N) if i not in train_idx)
        tr_s=[x for i in train_idx for x in blocks[i]]
        te_s=[x for i in test_idx for x in blocks[i]]
        tr_m=statistics.mean(tr_s); te_m=statistics.mean(te_s)
        train_means.append(tr_m); test_means.append(te_m)
        # rank blocks by train mean, pick best train block, check if it's top in test
        tr_blk_means=[statistics.mean(blocks[i]) for i in range(N)]
        te_blk_means=[statistics.mean(blocks[i]) for i in range(N)]
        best_train=tr_blk_means.index(max(tr_blk_means))
        # is best_train in top half of test?
        te_sorted=sorted(te_blk_means,reverse=True)
        rank_in_test=te_sorted.index(te_blk_means[best_train])
        if rank_in_test>=N//2:
            pbo_count+=1
        total+=1
    if total:
        print(f"  combos={total} PBO={pbo_count/total:.3f} (>0.5=overfit)")
        print(f"  train mean dist: min={min(train_means)*100:.3f}% max={max(train_means)*100:.3f}%")
        print(f"  test  mean dist: min={min(test_means)*100:.3f}% max={max(test_means)*100:.3f}%")
        # correlation train vs test means
        if len(train_means)>2:
            tm=statistics.mean(train_means); em=statistics.mean(test_means)
            num=sum((a-tm)*(b-em) for a,b in zip(train_means,test_means))
            den=(sum((a-tm)**2 for a in train_means)*sum((b-em)**2 for b in test_means))**0.5
            corr=num/den if den>0 else 0
            print(f"  train-test rank corr={corr:.3f}")
