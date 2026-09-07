# -*- coding: utf-8 -*-
# ⚠️ §44 v2 窗口caveat（2026-09-06）：以下 verdict 在 D+1-开盘→D+4 path 窗口（隔夜正之后的反转负段，entry=D+1开盘=gap 之后），非绝对无 edge——是"对窗口无 selection edge"。隔夜 gap（D收→D+1开 +1.15%）是真事件 edge 但薄/不可选/部分不可交易。见 S159 spec + memory s44-quant-validation-loop。
# PE valuation verdict (2026-09-06, baostock profit_data 800股缓存/1126 obs/39天):
#   all net-WR 34.81% | 低PE 1.031x 未validated | 高PE 1.031x 未validated(低高无差异=零信号)
# PE(valuation)无 tradeable edge(<2x). value 长期因子非短期涨停, 合 prior.
# caveat: 800/~2000股缓存(baostock profit_data per-code 慢 fetch 超时),1126 obs modest
# 但结论(无edge)与全维度一致. 低高PE相同35.89%或小样本巧合(quintile per-T 少股日退化)
"""用已缓存的 profit_data（800 股）跑 PE_TTM §44 测试，不重新 fetch。"""
import datetime, json, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # S163 R3: repo root，不硬编码绝对路径
sys.path.insert(0, str(ROOT / "backend"))
from strategies.kline_returns import simulate_holding, _is_unbuyable_next_bar
from data_quality.schema_validator import validate_or_reject  # S163 R1: bad-data gate
from tools._s44_wire import wire_verdict  # noqa: E402  # S168 接线 §44v2
KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
DB = ROOT / ".vibe-research" / "gene_scores.db"
PCACHE = ROOT / ".vibe-research" / "profit_data_cache.json"
COST = 0.70; PARAMS = (-3.0, 8.0, 3)
cache = json.loads(KLINE.read_bytes())
# S163 R1: 坏 bar（缺字段/负价/high<low/stale/空/错型）拒绝进 §44 verdict
validate_or_reject("baostock_kline",
                   [b for bars in cache.values() for b in bars],
                   as_of=datetime.date.today().isoformat())
pcache = json.loads(PCACHE.read_text())
# S163 R1: bad data gate — baostock profit_data (3 级 dict → flatten 2 级 for field 校验)
_flat_pcache = {f"{c}_{q}": v for c, qs in pcache.items() if isinstance(qs, dict)
                for q, v in qs.items() if isinstance(v, dict)}
validate_or_reject("baostock_profit_data", _flat_pcache)
conn = sqlite3.connect(str(DB), timeout=10)
pairs = conn.execute("SELECT DISTINCT date, code FROM gene_scores WHERE data_source='eastmoney_live' ORDER BY date").fetchall()
conn.close()
obs = []; n_no_eps = n_not_in_cache = 0
for D, rawcode in pairs:
    code = str(rawcode).zfill(6)
    if code not in pcache: n_not_in_cache += 1; continue
    bars = cache.get(code)
    if not bars: continue
    d_idx = next((i for i,b in enumerate(bars) if str(b["date"])[:10] == D), None)
    if d_idx is None or d_idx+1 >= len(bars): continue
    if _is_unbuyable_next_bar(bars[d_idx+1]): continue
    price = bars[d_idx].get("close") or 0
    if not price or price <= 0: continue
    latest = None
    for qk, v in pcache[code].items():
        if v.get("epsTTM") and v.get("pubDate","9999")[:10] <= D:
            if latest is None or v["pubDate"] > latest["pubDate"]: latest = v
    if not latest or not latest.get("epsTTM") or latest["epsTTM"] <= 0: n_no_eps += 1; continue
    pe = price / latest["epsTTM"]
    sim = simulate_holding(bars, D, *PARAMS)
    if sim is None: continue
    net = sim["return_pct"] - COST
    obs.append({"D": D, "pe": pe, "net": net, "win": 1 if net > 0 else 0})
print(f"obs={len(obs)} (not_in_cache={n_not_in_cache} no_eps={n_no_eps}) days={len(set(o['D'] for o in obs))}")
if len(obs) < 30: print("n<30 探索性"); sys.exit()
all_wins = sum(o["win"] for o in obs); wr_all = all_wins/len(obs)
print(f"all net-WR(涨停股 D+1): {wr_all*100:.2f}% (n={len(obs)})\n")
for name, take_high in [("低PE(底quintile)", False), ("高PE(顶quintile)", True)]:
    tw, tn = 0, 0
    for D in set(o["D"] for o in obs):
        day = [o for o in obs if o["D"]==D]
        if len(day) < 10: continue
        ds = sorted(day, key=lambda o: o["pe"])
        q = max(1, len(ds)//5)
        top = ds[-q:] if take_high else ds[:q]
        tw += sum(o["win"] for o in top); tn += len(top)
    if not tn: print(f"  {name}: n=0"); continue
    wr = tw/tn; lift = wr/wr_all if wr_all else 0
    st = "≥2x validated" if lift>=2 else ("未validated" if lift>=1 else "劣于随机")
    print(f"  {name}: net-WR {wr*100:.2f}% (n={tn}) vs all {wr_all*100:.2f}% | net lift={lift:.3f}x {st}")

# ── S168 接线：2 verdict（低PE/高PE quintile × selection）落 Recorder + lineage ──
_FROZEN_S168 = "aa34840"  # frozen commit（last touch S163/S167）
_all_days = sorted(set(o["D"] for o in obs))
_day_obs_map = {}  # D -> sorted-by-pe obs (>=10 only, 与 harness 现有 len(day)<10 过滤一致)
for _D in _all_days:
    _day_obs = [o for o in obs if o["D"] == _D]
    if len(_day_obs) >= 10:
        _day_obs_map[_D] = sorted(_day_obs, key=lambda o: o["pe"])
universe_by_day = {d: [o["net"] for o in day] for d, day in _day_obs_map.items()}
for _arm_name, _take_high in [("low_pe", False), ("high_pe", True)]:
    _surv_by_day = {}
    for _D, _day_obs in _day_obs_map.items():
        _q = max(1, len(_day_obs) // 5)
        _picks = _day_obs[-_q:] if _take_high else _day_obs[:_q]
        _surv_by_day[_D] = [o["net"] for o in _picks]
    _rets = [r for rs in _surv_by_day.values() for r in rs]
    _dts = [d for d, rs in _surv_by_day.items() for _ in rs]
    if len(_rets) < 2:
        print(f"[S168] valuation_pe:{_arm_name} skips (n<2)")
        continue
    wire_verdict(
        line_id=f"valuation_pe:{_arm_name}",
        returns=_rets,
        dates=_dts,
        edge_type="selection",
        frozen_commit=_FROZEN_S168,
        survivors_by_day=dict(_surv_by_day),
        universe_by_day=dict(universe_by_day),
        n_comparisons=2,  # 2 arms（低/高PE quintile）Bonferroni
        round_trip_cost=COST,
        script="tools/valuation_pe_lift.py",
        params={"arm": _arm_name, "quintile": "top" if _take_high else "bottom",
                "path": list(PARAMS), "cost": COST, "min_day_size": 10},
    )
