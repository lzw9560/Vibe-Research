# -*- coding: utf-8 -*-
# 秒板 superset 31天 verdict (2026-09-06, baostock 5min first_lock_idx==0, H2 cache 31天):
#   首 bar 涨停(秒板+近秒, idx==0): net-WR 7.69% (n=104) vs all 34.86% → net lift 0.221x 劣于随机
#   前2bar涨停(idx<=1): 0.172x 劣于随机
# REFUTES S156 zt_pool 秒板 13天 1.312x hint(小n+近期regime假象)。秒板股 D+1 崩最狠(reversal)。
# §44 所有维度所有时间窗全无 tradeable edge, definitively 收口。
"""秒板 superset（首 bar 涨停, first_lock_idx==0）31 天 net 验证——补 S156 的 13 天。
复用 H2 cache (h2_features_cache_full.json, 31 天) + baostock kline + simulate_holding net。
S156 秒板 13 天 1.312x hint → 31 天首 bar 涨停 superset 验证是否 robust。"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # S163 R3: repo root，不硬编码绝对路径
sys.path.insert(0, str(ROOT / "backend"))
from strategies.kline_returns import simulate_holding, _is_unbuyable_next_bar

H2_CACHE = ROOT / ".vibe-research" / "h2_features_cache_full.json"
KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
ROUND_TRIP_COST = 0.70
PARAMS = (-3.0, 8.0, 3)

feats = json.loads(H2_CACHE.read_text())
bars_cache = json.loads(KLINE.read_bytes())
print(f"H2 cache: {len(feats)} features across {len(set(f['date'] for f in feats))} 日\n")

obs = []
for f in feats:
    D = f["date"]; code = f["code"]
    bars = bars_cache.get(code)
    if not bars: continue
    d_idx = next((i for i,b in enumerate(bars) if str(b["date"])[:10] == D), None)
    if d_idx is None or d_idx+1 >= len(bars): continue
    if _is_unbuyable_next_bar(bars[d_idx+1]): continue  # D+1 一字板不可买
    sim = simulate_holding(bars, D, *PARAMS)
    if sim is None: continue
    net = sim["return_pct"] - ROUND_TRIP_COST
    obs.append({"D": D, "first_lock_idx": f.get("first_lock_idx"),
                "is_first_bar": f.get("first_lock_idx") == 0,
                "is_early": f.get("first_lock_idx") is not None and f["first_lock_idx"] <= 1,
                "net": net, "win": 1 if net > 0 else 0})

if len(obs) < 30:
    print(f"n={len(obs)} <30 探索性"); sys.exit()
all_wins = sum(o["win"] for o in obs); wr_all = all_wins/len(obs)
print(f"obs={len(obs)} days={len(set(o['D'] for o in obs))} | all net-WR(涨停股 D+1): {wr_all*100:.2f}%\n")

def lift_for(key):
    tw, tn = 0, 0
    for D in set(o["D"] for o in obs):
        day = [o for o in obs if o["D"]==D]
        top = [o for o in day if o[key]]
        tw += sum(o["win"] for o in top); tn += len(top)
    if not tn: return None
    return tw/tn, tn, (tw/tn)/wr_all if wr_all else 0

for name, key in [("首bar涨停(秒板+近秒, idx==0)", "is_first_bar"),
                   ("前2bar涨停(idx<=1)", "is_early")]:
    r = lift_for(key)
    if not r: print(f"  {name}: n=0"); continue
    wr, n, lift = r
    st = "VALIDATED" if lift>=2 else ("未validated" if lift>=1 else "劣于随机")
    print(f"  {name}: net-WR {wr*100:.2f}% (n={n}) vs all {wr_all*100:.2f}% | net lift={lift:.3f}x {st}")
print(f"\n对比: S156 zt_pool 秒板(首封≤09:31) 13天 net lift=1.312x; 本测试 31天首bar涨停 superset")
