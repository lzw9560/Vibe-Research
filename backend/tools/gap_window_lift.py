# -*- coding: utf-8 -*-
# gap-window lift verdict (2026-09-06, 6专家审计 recommended_next_test, decisive):
#   gap(D收→D+1开) all: mean +1.15% net +0.45%(扣0.70%cost) net_WR 46.5%(薄,14天66%活跃regime)
#   top(高score) lift 0.942x 劣于随机 | pearson(score,gap)=-0.075 弱负
#   gene_score 无 gap 选股力(预测哪个涨停股gap大)→ §44无selection edge在对窗口也成立,真非bug
#   gap本身是真事件edge(薄+不可选+部分不可交易,sealed D收买不到,需盘中打板intraday)
# 答"全因子劣于随机":无因子有选股力(对窗口也验证);gap是薄事件edge非选股edge,需intraday捕获
# §44 overreach=把"无selection edge"外推成"无edge"(外推禁令违反)
"""decisive: gap-window lift（因子是否预测隔夜 gap）——6 专家审计 recommended_next_test。
premium_baseline 899 samples（D 收盘→D+1 开盘 gap）+ gene_scores total_score + 过滤 D 日一字板 + 0.70% cost。"""
import datetime, json, sqlite3, sys, statistics
from pathlib import Path
from collections import defaultdict
ROOT = Path(__file__).resolve().parents[2]  # S163 R3: repo root，不硬编码绝对路径
sys.path.insert(0, str(ROOT / "backend"))
from data_quality.schema_validator import validate_or_reject  # S163 R1: bad-data gate
from tools._s44_wire import wire_verdict  # noqa: E402  # S168 接线 §44v2
KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
DB = ROOT / ".vibe-research" / "gene_scores.db"
PREMIUM = ROOT / ".vibe-research" / "first_board_premium_baseline.json"
COST = 0.70
TOL = 0.01  # 一字板价格容差

def is_one_word_d(bar):
    """D 日一字板：open≈high≈low≈close（无日内区间）→ 封死不可买。"""
    o,h,l,c = bar.get("open") or 0, bar.get("high") or 0, bar.get("low") or 0, bar.get("close") or 0
    if not (o and h and l and c): return False
    return abs(h-l) <= TOL and abs(o-c) <= TOL and abs(h-o) <= TOL

prem = json.loads(PREMIUM.read_text())
# NOTE: first_board_premium_baseline.json（first_board_premium_baseline 派生产物）无对应 schema — 派生 artifact
samples = prem["samples"]
cache = json.loads(KLINE.read_bytes())
# S163 R1: 坏 bar（缺字段/负价/high<low/stale/空/错型）拒绝进 §44 verdict
validate_or_reject("baostock_kline",
                   [b for bars in cache.values() for b in bars],
                   as_of=datetime.date.today().isoformat())
conn = sqlite3.connect(str(DB), timeout=10)
# gene_scores total_score per (date, code)
gs = {}
for r in conn.execute("SELECT date, code, total_score FROM gene_scores WHERE data_source='eastmoney_live'"):
    gs[(r[0], str(r[1]).zfill(6))] = r[2] if r[2] is not None else 0
conn.close()

obs = []  # {D, code, premium(gap%), net_gap, win, total_score, zt_count}
n_no_score = n_one_word = n_no_bar = 0
for s in samples:
    D, code, premium = s["date"], str(s["code"]).zfill(6), s["premium"]
    score = gs.get((D, code))
    if score is None: n_no_score += 1; continue
    bars = cache.get(code)
    if not bars: n_no_bar += 1; continue
    d_idx = next((i for i,b in enumerate(bars) if str(b["date"])[:10] == D), None)
    if d_idx is None: n_no_bar += 1; continue
    if is_one_word_d(bars[d_idx]): n_one_word += 1; continue  # D 日一字板封死不可买
    net_gap = premium - COST
    obs.append({"D": D, "code": code, "premium": premium, "net_gap": net_gap,
                "win": 1 if net_gap > 0 else 0, "score": float(score),
                "zt_count": s.get("zt_count")})

if len(obs) < 30:
    print(f"n={len(obs)} <30 探索性"); sys.exit()
all_wins = sum(o["win"] for o in obs); wr_all = all_wins/len(obs)
all_net_mean = statistics.mean(o["net_gap"] for o in obs)
print(f"obs={len(obs)} days={len(set(o['D'] for o in obs))} | no_score={n_no_score} no_bar={n_no_bar} one_word_D_excluded={n_one_word}")
print(f"gap (D收→D+1开) all: mean={statistics.mean(o['premium'] for o in obs):.2f}% net_gap(mean,扣{COST}%cost)={all_net_mean:.2f}% net_WR={wr_all*100:.1f}%\n")

# per-T top-quintile by total_score vs base (gap net lift)
tw, tn, bw, bn = 0,0,0,0
top_gap, bot_gap, all_gap_list = [], [], []
for D in set(o["D"] for o in obs):
    day = [o for o in obs if o["D"]==D]
    if len(day) < 10: continue
    ds = sorted(day, key=lambda o: o["score"])
    q = max(1, len(ds)//5)
    top = ds[-q:]; bot = ds[:q]
    top_gap += [o["net_gap"] for o in top]; bot_gap += [o["net_gap"] for o in bot]; all_gap_list += [o["net_gap"] for o in day]
    tw += sum(o["win"] for o in top); tn += len(top)
    bw += sum(o["win"] for o in bot); bn += len(bot)
wr_top = tw/tn if tn else 0; wr_bot = bw/bn if bn else 0
lift = wr_top/wr_all if wr_all else 0
print(f"gap-window lift (top-quintile score vs all):")
print(f"  top (高 score): net_gap mean={statistics.mean(top_gap):.2f}% net_WR={wr_top*100:.1f}% (n={tn})")
print(f"  bot (低 score): net_gap mean={statistics.mean(bot_gap):.2f}% net_WR={wr_bot*100:.1f}% (n={bn})")
print(f"  all:            net_WR={wr_all*100:.1f}%")
print(f"  lift(top/all)={lift:.3f}x {'VALIDATED' if lift>=2 else ('未validated' if lift>=1 else '劣于随机')}")
# Spearman rank corr score vs gap (selection power)
import math
# pearson(score, gap)

# ── S168 接线：§44v2 verifier 落 Recorder + lineage ──
_FROZEN_S168 = "3de6ab0"  # pre-registration commit (gap-window lift decisive test)
# 从 obs 重建 by_day 结构（harness 现有循环只建 flat list，不破现有逻辑）
_surv_by_day = {}   # D -> top-quintile net_gap（survivors）
_univ_by_day = {}   # D -> all net_gap（universe，≥10 picks/day）
for _D in set(o["D"] for o in obs):
    _day = [o for o in obs if o["D"] == _D]
    if len(_day) < 10:
        continue
    _ds = sorted(_day, key=lambda o: o["score"])
    _q = max(1, len(_ds) // 5)
    _surv_by_day[_D] = [o["net_gap"] for o in _ds[-_q:]]
    _univ_by_day[_D] = [o["net_gap"] for o in _day]
if _surv_by_day:
    _s168_rets = [r for rs in _surv_by_day.values() for r in rs]
    _s168_dates = [d for d, rs in _surv_by_day.items() for _ in rs]
    if len(_s168_rets) >= 2:
        wire_verdict(
            line_id="gap_window:top",
            returns=_s168_rets,
            dates=_s168_dates,
            edge_type="selection",
            frozen_commit=_FROZEN_S168,
            survivors_by_day=dict(_surv_by_day),
            universe_by_day=dict(_univ_by_day),
            n_comparisons=1,
            round_trip_cost=COST,
            script="tools/gap_window_lift.py",
            params={
                "arm": "top", "cost_pct": COST, "quintile": "top_1/5",
                "min_day_size": 10, "one_word_excluded": True,
                "tol": TOL,
            },
        )
    else:
        print("[S168] gap_window:top skips (n<2)")
else:
    print("[S168] gap_window:top skips (no survivors_by_day)")
