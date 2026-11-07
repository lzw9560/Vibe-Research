# -*- coding: utf-8 -*-
"""
Stage 2: 实际可交易收益分析（诚实 EV）。
信号: turn>20 & vr5>2 (top) + turn 10-20 & vr5>2 (broad) + pct 5-9.3% (momentum) + base 全样本
entry = T 日 close; exit 规则多种；报告 mean/median/WR/EV + 一字涨停 可卖率 + 止损敏感性。
不臆造：所有数字来自 baostock kline + zt_history 实算。
"""
import sqlite3, json, math, statistics, sys
from pathlib import Path
from collections import defaultdict

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir
_DATA = resolve_data_dir()
KLINE_DB = str(_DATA / "baostock_kline_cache.db")
ZT_DB = str(_DATA / "zt_history.db")

zdb = sqlite3.connect(ZT_DB); zcur = zdb.cursor()
zcur.execute("SELECT date, code FROM zt_history")
zt_by_date = defaultdict(set)
for d, c in zcur.fetchall():
    zt_by_date[d].add(c)
zdb.close()
cal = sorted(zt_by_date.keys()); date_idx = {d: i for i, d in enumerate(cal)}
def next_td(d):
    i = date_idx.get(d)
    return cal[i+1] if i is not None and i+1 < len(cal) else None
def next_td2(d):
    i = date_idx.get(d)
    return cal[i+2] if i is not None and i+2 < len(cal) else None

T_MIN, T_MAX = "2025-12-25", "2026-09-16"  # need T+1 AND T+2 kline for 一字 forced-hold exit

kdb = sqlite3.connect(KLINE_DB); kcur = kdb.cursor()
kcur.execute("SELECT code, bars_json FROM kline")
code_bars = {}
for code, bj in kcur.fetchall():
    try: bars = json.loads(bj)
    except: continue
    if isinstance(bars, list) and bars:
        code_bars[code] = bars
kdb.close()
print(f"loaded {len(code_bars)} codes", file=sys.stderr)

code_map = {}; code_dates = {}
for code, bars in code_bars.items():
    m = {}
    for b in bars:
        if b.get("date"): m[b["date"]] = b
    if m:
        code_map[code] = m; code_dates[code] = sorted(m.keys())

def vr5(code, idx):
    ds = code_dates[code]; m = code_map[code]
    tbar = m[ds[idx]]
    if tbar.get("volume") is None: return None
    prev = ds[max(0,idx-5):idx]
    if len(prev) < 5: return None
    pv = [m[p].get("volume") for p in prev]
    if any(v is None or v==0 for v in pv): return None
    return tbar["volume"] / (sum(pv)/5.0)

# build pick records with returns
picks_top = []        # turn>20 & vr5>2
picks_broad = []      # turn 10-20 & vr5>2
picks_mom = []        # pct 5-9.3% (strong not-ZT)
picks_base = []        # all non-ZT (control)

for code, ds in code_dates.items():
    m = code_map[code]
    for idx, d in enumerate(ds):
        if d < T_MIN or d > T_MAX: continue
        nd = next_td(d); nd2 = next_td2(d)
        if nd is None: continue
        bar = m[d]
        if code in zt_by_date.get(d, ()): continue  # T-day non-ZT
        t1 = m.get(nd)
        if t1 is None: continue
        entry = bar.get("close")
        if entry is None or entry <= 0: continue
        pct = bar.get("pctChg"); turn = bar.get("turn"); v = vr5(code, idx)
        if pct is None or turn is None or v is None: continue
        t1_close = t1.get("close"); t1_open = t1.get("open"); t1_high = t1.get("high"); t1_low = t1.get("low")
        if None in (t1_close, t1_open, t1_high, t1_low): continue
        t1_zt = 1 if code in zt_by_date.get(nd, ()) else 0
        # 一字涨停: T+1 opens at/near limit-up AND low stays at/near limit (locked, no fill for sellers)
        lim = entry * 1.10  # main board approx
        t1_yizi = 1 if (t1_zt and t1_open >= entry*1.095 and t1_low >= entry*1.095) else 0
        # forced-hold exit for 一字: need T+2 open
        t2 = m.get(nd2) if nd2 else None
        t2_open = t2.get("open") if t2 else None
        rec = dict(entry=entry, t1_close=t1_close, t1_open=t1_open, t1_high=t1_high, t1_low=t1_low,
                   t1_zt=t1_zt, t1_yizi=t1_yizi, t2_open=t2_open, pct=pct, turn=turn, vr5=v, d=d, code=code)
        picks_base.append(rec)
        if turn > 20 and v > 2: picks_top.append(rec)
        if 10 <= turn <= 20 and v > 2: picks_broad.append(rec)
        if 5 <= pct <= 9.3: picks_mom.append(rec)

def ret_close(r):   # sell T+1 close regardless
    return (r["t1_close"] - r["entry"]) / r["entry"]
def ret_real(r):    # realizability-aware: 一字 → hold to T+2 open; else sell T+1 close (or limit if ZT)
    if r["t1_zt"] and not r["t1_yizi"]:
        return (r["t1_high"] * 0.999 - r["entry"]) / r["entry"]  # sell near limit during封板 (slippage)
    if r["t1_zt"] and r["t1_yizi"]:
        if r["t2_open"] is not None:
            return (r["t2_open"] - r["entry"]) / r["entry"]   # forced hold to T+2 open
        return (r["t1_close"] - r["entry"]) / r["entry"]      # fallback
    return (r["t1_close"] - r["entry"]) / r["entry"]
def ret_stop(r, pct_stop):
    # if T+1 low breaks entry*(1-stop), exit at stop; else sell T+1 close (or limit if ZT non-一字)
    stop_px = r["entry"] * (1 - pct_stop)
    if r["t1_low"] is not None and r["t1_low"] <= stop_px:
        return -pct_stop
    return ret_real(r)

def summarize(name, picks, retfn):
    if not picks:
        print(f"{name:42s} | n=0"); return
    rets = [retfn(r) for r in picks]
    n = len(rets); mean = statistics.mean(rets); med = statistics.median(rets)
    wins = sum(1 for x in rets if x > 0); wr = wins/n
    # gross (no cost) — apply ~0.3% round-trip cost (印花+佣金+滑点) for net
    cost = 0.003
    net = mean - cost
    zt = sum(r["t1_zt"] for r in picks); yizi = sum(r["t1_yizi"] for r in picks)
    pos = [x for x in rets if x > 0]; neg = [x for x in rets if x <= 0]
    # t-test
    if n > 1:
        sd = statistics.stdev(rets); se = sd/math.sqrt(n); t = mean/se if se else 0
    else: t=0
    print(f"{name:42s} | n={n:5d} gross_mean={mean*100:6.2f}% net~{net*100:6.2f}% med={med*100:6.2f}% WR={wr*100:5.1f}% T+1ZT={zt:4d}({zt/n*100:.1f}%) 一字={yizi:3d}({yizi/max(zt,1)*100:.0f}%ofZT) t={t:.2f}")

print("\n===== BASE 全样本(T日未涨停) control =====")
summarize("sell@T+1 close (gross)", picks_base, ret_close)
summarize("realizability-aware exit", picks_base, ret_real)
print("\n===== TOP: turn>20 & vr5>2 =====")
summarize("sell@T+1 close (gross)", picks_top, ret_close)
summarize("realizability-aware exit", picks_top, ret_real)
print("\n===== BROAD: turn 10-20 & vr5>2 =====")
summarize("sell@T+1 close (gross)", picks_broad, ret_close)
summarize("realizability-aware exit", picks_broad, ret_real)
print("\n===== MOMENTUM: pct 5-9.3% =====")
summarize("sell@T+1 close (gross)", picks_mom, ret_close)
summarize("realizability-aware exit", picks_mom, ret_real)

print("\n===== TOP 止损敏感性 (realizability-aware + stop) =====")
for s in [0.02, 0.03, 0.05, 0.08]:
    summarize(f"stop {s*100:.0f}%", picks_top, lambda r, s=s: ret_stop(r, s))
print("\n===== BROAD 止损敏感性 =====")
for s in [0.03, 0.05, 0.08]:
    summarize(f"stop {s*100:.0f}%", picks_broad, lambda r, s=s: ret_stop(r, s))

print("\n===== TOP: 一字涨停 forced-hold 实际收益分布 (一字 picks only) =====")
yizi_picks = [r for r in picks_top if r["t1_yizi"]]
if yizi_picks:
    rets_y = [(r["t2_open"] - r["entry"])/r["entry"] for r in yizi_picks if r["t2_open"]]
    if rets_y:
        print(f"一字 forced→T+2 open: n={len(rets_y)} mean={statistics.mean(rets_y)*100:.2f}% med={statistics.median(rets_y)*100:.2f}% WR={sum(1 for x in rets_y if x>0)/len(rets_y)*100:.1f}%")
print("\n===== TOP: 拆分 T+1涨停 vs 非涨停 子组收益 (realizability-aware) =====")
zt_picks = [r for r in picks_top if r["t1_zt"]]; nzt_picks = [r for r in picks_top if not r["t1_zt"]]
if zt_picks:
    rz = [ret_real(r) for r in zt_picks]; print(f"T+1涨停子组: n={len(rz)} mean={statistics.mean(rz)*100:.2f}% WR={sum(1 for x in rz if x>0)/len(rz)*100:.1f}%")
if nzt_picks:
    rn = [ret_real(r) for r in nzt_picks]; print(f"T+1非涨停子组: n={len(rn)} mean={statistics.mean(rn)*100:.2f}% WR={sum(1 for x in rn if x>0)/len(rn)*100:.1f}%")

print("\n===== regime check: TOP picks 月度分布 =====")
from collections import Counter
mc = Counter(r["d"][:7] for r in picks_top)
for mth in sorted(mc): print(f"  {mth}: {mc[mth]} picks")
