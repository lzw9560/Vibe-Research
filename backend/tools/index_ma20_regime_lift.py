# -*- coding: utf-8 -*-
"""§44 v2 verdict: index_ma20 regime gate —— 涨停股隔夜 gap 是否被 regime 条件化.

Factor: index sh.000001 close vs MA20 (strong=close>MA20 / weak=close<MA20), day-level binary.
Target: 涨停股隔夜 gap (D close -> D+1 open), net of 0.70% round-trip cost.
Sample: zt_history (is_final=1) + baostock_kline_cache 涨停股 (pctChg at limit threshold).
Methodology (§44 v2 strict):
  1. Multi-window sanity (mean+WR+IC per regime bucket)
  2. day_paired (per-day mean, non-pooled — high-count days don't dominate)
  3. Permutation null (shuffle regime labels across days) + Bonferroni (K=1)
  4. Cost: 0.70% round-trip; one-word D-day boards excluded (sealed, unbuyable)
  5. No extrapolation (regime-edge on selection != full-pipeline edge)
"""
import datetime, json, sqlite3, sys, statistics, random, math
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]  # S163 R3: repo root，不硬编码绝对路径
sys.path.insert(0, str(ROOT / "backend"))
from data_quality.schema_validator import validate_or_reject  # S163 R1: bad-data gate
KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
ZT_DB = ROOT / ".vibe-research" / "zt_history.db"
REGIME_F = ROOT / ".vibe-research" / "index_ma20_regime.json"
COST = 0.70          # % round-trip
TOL = 0.01           # one-word board price tolerance
MA_WINDOW = 20
N_PERM = 10000       # permutation iterations

# ---- limit-up thresholds by board prefix ----
def is_limit_up(code, pctchg):
    """Identify limit-up close from baostock pctChg."""
    if pctchg is None:
        return False
    if code.startswith("30") or code.startswith("688"):
        return 19.5 <= pctchg <= 20.5    # ChiNext / STAR: +20%
    if code.startswith("8") or code.startswith("43") or code.startswith("83") or code.startswith("87") or code.startswith("92"):
        return 29.0 <= pctchg <= 30.5     # BSE: +30% (broad catch)
    return 9.8 <= pctchg <= 10.2          # main board: +10%

def is_one_word_d(bar):
    """D-day one-word board: open≈high≈low≈close (sealed, unbuyable)."""
    o, h, l, c = (bar.get("open") or 0), (bar.get("high") or 0), (bar.get("low") or 0), (bar.get("close") or 0)
    if not (o and h and l and c):
        return False
    return abs(h - l) <= TOL and abs(o - c) <= TOL and abs(h - o) <= TOL

def find_idx(bars, D):
    return next((i for i, b in enumerate(bars) if str(b["date"])[:10] == D), None)

# ---- load data ----
print("loading data...")
cache = json.loads(KLINE.read_bytes())
# S163 R1: 坏 bar（缺字段/负价/high<low/stale/空/错型）拒绝进 §44 verdict
validate_or_reject("baostock_kline",
                   [b for bars in cache.values() for b in bars],
                   as_of=datetime.date.today().isoformat())
regime = json.loads(REGIME_F.read_text())
# NOTE: index_ma20_regime.json（index_ma20_regime_fetch 派生产物，dict_of_dicts）无对应 schema — 派生 artifact

# zt_history set (date, code) for high-quality flag
zt_conn = sqlite3.connect(str(ZT_DB))
zt_set = set()
for d, c in zt_conn.execute("SELECT date, code FROM zt_history WHERE is_final=1"):
    zt_set.add((d, str(c).zfill(6)))
zt_conn.close()
print(f"zt_history final pairs: {len(zt_set)}")

# ---- build observations ----
# Strategy: iterate kline cache, identify limit-up days by pctChg, compute gap.
# Mark whether the (date, code) is in zt_history for cross-validation.
obs = []          # {D, code, gap, net_gap, win, regime, from_zt}
n_no_d1 = n_one_word = n_no_regime = n_codes = 0

for code, bars in cache.items():
    if not bars or len(bars) < 2:
        continue
    n_codes += 1
    for i in range(len(bars) - 1):
        bar = bars[i]
        pct = bar.get("pctChg")
        if not is_limit_up(code, pct):
            continue
        D = str(bar["date"])[:10]
        d_close = bar.get("close") or 0
        d1_open = bars[i + 1].get("open") or 0
        if not d_close or not d1_open:
            n_no_d1 += 1
            continue
        if is_one_word_d(bar):
            n_one_word += 1
            continue
        reg = regime.get(D)
        if reg is None:
            n_no_regime += 1
            continue
        gap = (d1_open - d_close) / d_close * 100
        net_gap = gap - COST
        obs.append({
            "D": D,
            "code": code,
            "gap": gap,
            "net_gap": net_gap,
            "win": 1 if net_gap > 0 else 0,
            "regime": reg["regime"],
            "from_zt": (D, code) in zt_set,
        })

print(f"scanned {n_codes} codes | obs={len(obs)} | excluded: no_d1={n_no_d1} one_word={n_one_word} no_regime={n_no_regime}")
unique_days = sorted(set(o["D"] for o in obs))
print(f"unique days={len(unique_days)} | zt-tagged={sum(1 for o in obs if o['from_zt'])}")

# ---- per-day aggregation (non-pooled) ----
day_data = defaultdict(list)
for o in obs:
    day_data[o["D"]].append(o)

day_summary = []  # {D, regime, n, mean_gap, mean_net_gap, wr}
for D in unique_days:
    picks = day_data[D]
    reg = picks[0]["regime"]  # regime is day-level, same for all picks that day
    day_summary.append({
        "D": D,
        "regime": reg,
        "n": len(picks),
        "mean_gap": statistics.mean(o["gap"] for o in picks),
        "mean_net_gap": statistics.mean(o["net_gap"] for o in picks),
        "wr": sum(o["win"] for o in picks) / len(picks),
    })

strong_days = [d for d in day_summary if d["regime"] == "strong"]
weak_days = [d for d in day_summary if d["regime"] == "weak"]

def agg(days, key):
    vals = [d[key] for d in days]
    return vals

# ---- §44 v2 stats ----
print("\n" + "=" * 70)
print("§44 v2 VERDICT: index_ma20 regime gate (涨停股隔夜 gap 条件化)")
print("=" * 70)

# 1. multi-window sanity
print("\n[1] Multi-window sanity (per regime, per-day means non-pooled):")
for label, days in [("strong(bull)", strong_days), ("weak(bear)", weak_days)]:
    if not days:
        print(f"  {label}: n_days=0 — CANNOT TEST")
        continue
    ng = agg(days, "mean_net_gap")
    wr = agg(days, "wr")
    mg = agg(days, "mean_gap")
    ns = agg(days, "n")
    total_picks = sum(ns)
    print(f"  {label}: n_days={len(days)} n_picks={total_picks}")
    print(f"    gross_gap mean={statistics.mean(mg):.2f}% net_gap mean={statistics.mean(ng):.2f}% net_WR mean={statistics.mean(wr)*100:.1f}%")
    print(f"    net_gap median={statistics.median(ng):.2f}% net_gap std={statistics.pstdev(ng):.2f}%" if len(ng) > 1 else "")

# overall
all_ng = [o["net_gap"] for o in obs]
all_wr = sum(o["win"] for o in obs) / len(obs)
print(f"  ALL: n_days={len(day_summary)} n_picks={len(obs)} net_gap mean={statistics.mean(all_ng):.2f}% net_WR={all_wr*100:.1f}%")

# 2. day_paired lift (strong vs weak)
print("\n[2] day_paired lift (strong vs weak, per-day means):")
if not strong_days or not weak_days:
    print("  CANNOT TEST — one regime bucket empty")
else:
    s_ng = agg(strong_days, "mean_net_gap")
    w_ng = agg(weak_days, "mean_net_gap")
    s_wr = agg(strong_days, "wr")
    w_wr = agg(weak_days, "wr")
    mean_s = statistics.mean(s_ng)
    mean_w = statistics.mean(w_ng)
    wr_s = statistics.mean(s_wr)
    wr_w = statistics.mean(w_wr)
    base = statistics.mean(all_ng)
    lift_s = mean_s / base if base != 0 else float("inf")
    lift_w = mean_w / base if base != 0 else float("inf")
    ratio = mean_s / mean_w if mean_w != 0 else float("inf")
    print(f"  strong: mean_net_gap={mean_s:.2f}% WR={wr_s*100:.1f}% (n_days={len(strong_days)})")
    print(f"  weak:   mean_net_gap={mean_w:.2f}% WR={wr_w*100:.1f}% (n_days={len(weak_days)})")
    print(f"  lift(strong/all)={lift_s:.3f}x  lift(weak/all)={lift_w:.3f}x  ratio(strong/weak)={ratio:.3f}x")
    print(f"  {'VALIDATED (>=2x)' if max(lift_s, lift_w, ratio) >= 2 else 'NO validated edge (<2x)'}")

# 3. IC (regime binary vs gap) — point-biserial
print("\n[3] IC (regime→gap point-biserial correlation):")
if strong_days and weak_days:
    # per-day: regime binary (1=strong, 0=weak) vs mean_net_gap
    x_reg = [1 if d["regime"] == "strong" else 0 for d in day_summary]
    y_gap = [d["mean_net_gap"] for d in day_summary]
    n = len(x_reg)
    mx = sum(x_reg) / n
    my = sum(y_gap) / n
    sxy = sum((x_reg[i] - mx) * (y_gap[i] - my) for i in range(n))
    sx = math.sqrt(sum((v - mx) ** 2 for v in x_reg))
    sy = math.sqrt(sum((v - my) ** 2 for v in y_gap))
    ic = sxy / (sx * sy) if sx and sy else 0
    print(f"  per-day IC (regime↔net_gap) = {ic:.4f}  (n_days={n})")
    # also pick-level IC
    x_reg_p = [1 if o["regime"] == "strong" else 0 for o in obs]
    y_gap_p = [o["net_gap"] for o in obs]
    n_p = len(x_reg_p)
    mx_p = sum(x_reg_p) / n_p
    my_p = sum(y_gap_p) / n_p
    sxy_p = sum((x_reg_p[i] - mx_p) * (y_gap_p[i] - my_p) for i in range(n_p))
    sx_p = math.sqrt(sum((v - mx_p) ** 2 for v in x_reg_p))
    sy_p = math.sqrt(sum((v - my_p) ** 2 for v in y_gap_p))
    ic_p = sxy_p / (sx_p * sy_p) if sx_p and sy_p else 0
    print(f"  pick-level IC (regime↔net_gap) = {ic_p:.4f}  (n_picks={n_p})")

# 4. Permutation null (day-level regime shuffle)
print(f"\n[4] Permutation null (shuffle regime labels across {len(day_summary)} days, {N_PERM} iters):")
if strong_days and weak_days:
    observed_diff = statistics.mean(agg(strong_days, "mean_net_gap")) - statistics.mean(agg(weak_days, "mean_net_gap"))
    # precompute day net_gap means
    day_ng = [d["mean_net_gap"] for d in day_summary]
    day_reg = [d["regime"] for d in day_summary]
    rng = random.Random(42)
    count_ge = 0
    diffs = []
    for _ in range(N_PERM):
        shuffled = day_reg[:]
        rng.shuffle(shuffled)
        s_vals = [day_ng[i] for i in range(len(day_ng)) if shuffled[i] == "strong"]
        w_vals = [day_ng[i] for i in range(len(day_ng)) if shuffled[i] == "weak"]
        if not s_vals or not w_vals:
            continue
        diff = statistics.mean(s_vals) - statistics.mean(w_vals)
        diffs.append(diff)
        if abs(diff) >= abs(observed_diff):
            count_ge += 1
    p_perm = count_ge / N_PERM
    # Bonferroni K=1 (single comparison)
    p_bonf = min(1.0, p_perm * 1)
    print(f"  observed diff (strong-weak mean_net_gap) = {observed_diff:.2f}%")
    if diffs:
        sorted_diffs = sorted(diffs)
        null_mean = statistics.mean(diffs)
        null_std = statistics.pstdev(diffs)
        print(f"  null: mean={null_mean:.2f}% std={null_std:.2f}%")
        print(f"  perm p-value (|diff|>=observed) = {p_perm:.4f}")
        print(f"  Bonferroni p (K=1) = {p_bonf:.4f}")
        # z-score
        z = (observed_diff - null_mean) / null_std if null_std else 0
        print(f"  z-score = {z:.2f}")
        sig = "SIGNIFICANT (p<0.05)" if p_bonf < 0.05 else "NOT significant (p>=0.05)"
        print(f"  verdict: {sig}")

# 5. zt_history-only cross-check (high-quality subset)
print("\n[5] zt_history-only cross-check (high-quality limit-up flag):")
zt_obs = [o for o in obs if o["from_zt"]]
if zt_obs:
    zt_strong = [o for o in zt_obs if o["regime"] == "strong"]
    zt_weak = [o for o in zt_obs if o["regime"] == "weak"]
    zt_days = defaultdict(list)
    for o in zt_obs:
        zt_days[o["D"]].append(o)
    zt_strong_days = [d for d in zt_days if zt_days[d][0]["regime"] == "strong"]
    zt_weak_days = [d for d in zt_days if zt_days[d][0]["regime"] == "weak"]
    print(f"  zt picks={len(zt_obs)} strong_picks={len(zt_strong)} weak_picks={len(zt_weak)}")
    print(f"  zt strong days={len(zt_strong_days)} weak days={len(zt_weak_days)}")
    if zt_strong:
        print(f"  zt strong: net_gap mean={statistics.mean(o['net_gap'] for o in zt_strong):.2f}% WR={sum(o['win'] for o in zt_strong)*100/len(zt_strong):.1f}%")
    if zt_weak:
        print(f"  zt weak:   net_gap mean={statistics.mean(o['net_gap'] for o in zt_weak):.2f}% WR={sum(o['win'] for o in zt_weak)*100/len(zt_weak):.1f}%")
else:
    print("  no zt_history overlap")

# 6. verdict summary
print("\n" + "=" * 70)
print("VERDICT SUMMARY")
print("=" * 70)
if not strong_days or not weak_days:
    print("UNDERPOWERED — one regime bucket empty, cannot test regime conditioning")
elif len(day_summary) < 30:
    print(f"UNDERPOWERED — only {len(day_summary)} days ({len(strong_days)} strong / {len(weak_days)} weak)")
    print("  <30 days; report descriptive only, no inferential verdict")
else:
    max_lift = max(
        statistics.mean(agg(strong_days, "mean_net_gap")) / (statistics.mean(all_ng) or 1),
        statistics.mean(agg(weak_days, "mean_net_gap")) / (statistics.mean(all_ng) or 1),
    )
    ratio_val = (statistics.mean(agg(strong_days, "mean_net_gap")) /
                 (statistics.mean(agg(weak_days, "mean_net_gap")) or 1))
    print(f"  days={len(day_summary)} ({len(strong_days)} strong / {len(weak_days)} weak) picks={len(obs)}")
    print(f"  max lift vs all = {max_lift:.3f}x | strong/weak ratio = {ratio_val:.3f}x")
    if max_lift >= 2 or (p_perm < 0.05 if 'p_perm' in dir() else False):
        print("  → EDGE: regime conditions gap (validated or significant)")
    else:
        print("  → NO EDGE: regime does not meaningfully condition gap (<2x lift, not significant)")
print("\nNote: regime-edge on overnight gap != full-pipeline edge (intraday 60% untested).")
print("Note: overnight gap itself is partly untradable (D-close sealed, needs intraday entry).")
