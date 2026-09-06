# -*- coding: utf-8 -*-
"""大宗交易折价（印迹效应）§44 v2 verdict 脚本。

因子：大宗交易折价率（block trade discount）。D-1 有大宗交易的股，按折价率分层。
target：D open→exit net（扣 0.70% round-trip cost），day_paired lift vs 同期无大宗 universe。
方法论：§44 v2 — 前置窗口 sanity + day_paired 非池化 + within-day null + Bonferroni + 不外推。

数据源：
  - block_trade_raw.json（eastmoney RPT_DATA_BLOCKTRADE 市场全量, 20000 records, 136 dates）
  - baostock_kline_cache.json（5226 stocks, daily K-line）
"""
import datetime, json, sys, time, statistics, math
from pathlib import Path
from collections import defaultdict
import random

ROOT = Path(__file__).resolve().parents[2]  # S163 R3: repo root，不硬编码绝对路径
sys.path.insert(0, str(ROOT / "backend"))
from data_quality.schema_validator import validate_or_reject  # S163 R1: bad-data gate
BLOCK = ROOT / ".vibe-research" / "block_trade_raw.json"
KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
COST = 0.70
EXIT_WINDOWS = [1, 3, 5]
N_PERM = 2000
BONF_K = 9           # 3 strata × 3 windows
ALPHA = 0.05 / BONF_K
SEED = 42

random.seed(SEED)

# ── 1. Load data ──────────────────────────────────────────────────────────
print("=" * 72)
print("大宗交易折价（印迹效应）§44 v2 分析")
print("=" * 72)

t0 = time.time()
print("Loading block trades...", end=" ", flush=True)
bt_raw = json.loads(BLOCK.read_bytes())
# S163 R1: bad data gate — eastmoney block_trade
validate_or_reject("eastmoney_block_trade", bt_raw, as_of=datetime.date.today().isoformat())
print(f"{len(bt_raw)} records ({time.time()-t0:.1f}s)")

print("Loading kline cache...", end=" ", flush=True)
cache = json.loads(KLINE.read_bytes())
print(f"{len(cache)} stocks ({time.time()-t0:.1f}s)")
# S163 R1: 坏 bar（缺字段/负价/high<low/stale/空/错型）拒绝进 §44 verdict
validate_or_reject("baostock_kline",
                   [b for bars in cache.values() for b in bars],
                   as_of=datetime.date.today().isoformat())

# ── 2. Aggregate by (date, code) — most discounted ─────────────────────────
print("\nAggregating block trades by (date, code)...")
best = {}
for r in bt_raw:
    key = (r["date"], str(r["code"]).zfill(6))
    pr = r.get("premium_ratio")
    if pr is None:
        continue
    if key not in best or pr < best[key]["premium_ratio"]:
        best[key] = {**r, "code": str(r["code"]).zfill(6)}

STRATA = {
    "deep_discount": lambda p: p < -0.05,         # 折价>5%
    "mild_discount": lambda p: -0.05 <= p < 0,     # 折价0-5%
    "premium":       lambda p: p >= 0,              # 溢价
}
strata_pairs = {s: {} for s in STRATA}
for key, rec in best.items():
    p = rec["premium_ratio"]
    for sname, sfn in STRATA.items():
        if sfn(p):
            strata_pairs[sname][key] = rec
            break

for sname, pairs in strata_pairs.items():
    print(f"  {sname}: {len(pairs)} pairs")

# ── 3. Build kline index ──────────────────────────────────────────────────
print("\nBuilding kline date index...", end=" ", flush=True)
code_date_idx = {}
for code, bars in cache.items():
    di = {}
    for i, b in enumerate(bars):
        ds = str(b["date"])[:10]
        if ds not in di:
            di[ds] = i
    code_date_idx[code] = di
print(f"done ({time.time()-t0:.1f}s)")

# ── 4. Forward returns: block-trade stocks ────────────────────────────────
# Block trade on D_bt → entry D_bt+1 open → exit D_bt+1/3/5 close (1d/3d/5d)

def compute_returns(code, bt_date):
    di = code_date_idx.get(code)
    if not di:
        return None
    idx = di.get(bt_date)
    if idx is None:
        return None
    bars = cache[code]
    entry_idx = idx + 1
    if entry_idx >= len(bars):
        return None
    entry_open = bars[entry_idx].get("open")
    if not entry_open or entry_open <= 0:
        return None
    if str(bars[entry_idx].get("isST", "0")) == "1":
        return None
    results = {}
    for w in EXIT_WINDOWS:
        exit_idx = entry_idx + (w - 1)
        if exit_idx >= len(bars):
            results[w] = None
            continue
        exit_close = bars[exit_idx].get("close")
        if not exit_close or exit_close <= 0:
            results[w] = None
            continue
        gross = (exit_close - entry_open) / entry_open * 100
        results[w] = gross - COST
    return results

print("\nComputing block-trade forward returns...", end=" ", flush=True)
block_returns = {s: {w: [] for w in EXIT_WINDOWS} for s in STRATA}
n_skip = 0
for sname, pairs in strata_pairs.items():
    for (bt_date, code), rec in pairs.items():
        rets = compute_returns(code, bt_date)
        if rets is None:
            n_skip += 1
            continue
        for w in EXIT_WINDOWS:
            r = rets.get(w)
            if r is not None:
                block_returns[sname][w].append((bt_date, code, r))
print(f"done ({time.time()-t0:.1f}s, skipped {n_skip} no-kline)")

# ── 5. Universe returns per day ────────────────────────────────────────────
print("Computing universe returns per day...", end=" ", flush=True)
bt_dates = sorted(set(r["date"] for r in bt_raw))
bt_codes_per_date = defaultdict(set)
for (bt_date, code) in best.keys():
    bt_codes_per_date[bt_date].add(code)

universe_returns = defaultdict(lambda: {w: [] for w in EXIT_WINDOWS})
n_univ_total = 0
for bt_date in bt_dates:
    excluded = bt_codes_per_date.get(bt_date, set())
    for code, bars in cache.items():
        if code in excluded:
            continue
        di = code_date_idx.get(code)
        if not di:
            continue
        idx = di.get(bt_date)
        if idx is None:
            continue
        entry_idx = idx + 1
        if entry_idx >= len(bars):
            continue
        entry_open = bars[entry_idx].get("open")
        if not entry_open or entry_open <= 0:
            continue
        if str(bars[entry_idx].get("isST", "0")) == "1":
            continue
        for w in EXIT_WINDOWS:
            exit_idx = entry_idx + (w - 1)
            if exit_idx >= len(bars):
                continue
            exit_close = bars[exit_idx].get("close")
            if not exit_close or exit_close <= 0:
                continue
            gross = (exit_close - entry_open) / entry_open * 100
            universe_returns[bt_date][w].append(gross - COST)
            n_univ_total += 1
print(f"done ({time.time()-t0:.1f}s, {n_univ_total} obs across {len(universe_returns)} days)")

# ── 6. §44 v2 metrics ─────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("§44 v2 — day_paired non-pooled + within-day null + Bonferroni")
print("=" * 72)
print(f"Bonferroni K={BONF_K}, corrected alpha={ALPHA:.5f}")
print(f"Within-day null: {N_PERM} permutations/day, seed={SEED}\n")

all_results = []

for sname in STRATA:
    for w in EXIT_WINDOWS:
        obs_list = block_returns[sname][w]
        if not obs_list:
            continue

        # Per-day aggregation (non-pooled)
        block_by_day = defaultdict(list)
        for bt_date, code, ret in obs_list:
            block_by_day[bt_date].append(ret)

        valid_days = [d for d in block_by_day
                      if d in universe_returns and universe_returns[d][w]]
        if not valid_days:
            continue

        day_lifts = []
        day_wr_lifts = []
        day_block_means = []
        day_universe_means = []
        perm_pvals_two = []  # two-sided per-day p

        for d in valid_days:
            block_rets = block_by_day[d]
            univ_rets = universe_returns[d][w]
            n_block = len(block_rets)
            n_univ = len(univ_rets)

            block_mean = statistics.mean(block_rets)
            univ_mean = statistics.mean(univ_rets)
            block_wr = sum(1 for r in block_rets if r > 0) / n_block
            univ_wr = sum(1 for r in univ_rets if r > 0) / n_univ if n_univ else 0

            day_lifts.append(block_mean - univ_mean)
            day_block_means.append(block_mean)
            day_universe_means.append(univ_mean)
            if univ_wr > 0:
                day_wr_lifts.append(block_wr / univ_wr)

            # Within-day null: sample n_block from universe, compute mean
            sample_size = min(n_block, n_univ)
            null_means = []
            for _ in range(N_PERM):
                sample = random.sample(univ_rets, sample_size)
                null_means.append(statistics.mean(sample))
            null_means.sort()

            # Two-sided p: P(|null| >= |actual|)
            actual_diff = block_mean - univ_mean
            n_extreme = sum(1 for m in null_means if abs(m - univ_mean) >= abs(actual_diff))
            perm_pvals_two.append(n_extreme / N_PERM)

        n_days = len(valid_days)
        n_picks = sum(len(block_by_day[d]) for d in valid_days)
        mean_lift = statistics.mean(day_lifts)
        mean_block = statistics.mean(day_block_means)
        mean_univ = statistics.mean(day_universe_means)
        mean_wr_lift = statistics.mean(day_wr_lifts) if day_wr_lifts else 0

        all_block = [r for d in valid_days for r in block_by_day[d]]
        all_univ = [r for d in valid_days for r in universe_returns[d][w]]
        pooled_block_wr = sum(1 for r in all_block if r > 0) / len(all_block)
        pooled_univ_wr = sum(1 for r in all_univ if r > 0) / len(all_univ)

        n_positive = sum(1 for l in day_lifts if l > 0)
        sign_frac = n_positive / n_days
        median_p = statistics.median(perm_pvals_two)

        # Verdict (§44 v2: n够 + lift + Bonferroni)
        if n_picks < 200 or n_days < 60:
            verdict_str = "UNDERPOWERED"
        elif mean_wr_lift >= 2.0 and median_p < ALPHA:
            verdict_str = "EDGE (validated, lift>=2x + p<alpha)"
        elif mean_wr_lift >= 1.5 and median_p < ALPHA:
            verdict_str = "WEAK EDGE (lift>=1.5x + p<alpha)"
        elif mean_wr_lift >= 1.0 and median_p < ALPHA:
            verdict_str = "THIN EDGE (lift>=1x + p<alpha)"
        elif mean_wr_lift < 1.0:
            verdict_str = "劣于随机 (wr_lift<1x)"
        else:
            verdict_str = "未validated (wr_lift>=1x but p>=alpha)"

        print(f"--- {sname} | exit={w}d ---")
        print(f"  n_picks={n_picks}  n_days={n_days}  (univ/day ~{len(all_univ)//n_days})")
        print(f"  block  mean={mean_block:+.3f}%  WR={pooled_block_wr*100:.1f}%")
        print(f"  univ   mean={mean_univ:+.3f}%  WR={pooled_univ_wr*100:.1f}%")
        print(f"  day_paired mean lift (block-univ)={mean_lift:+.3f}%")
        print(f"  day_paired WR lift (block/univ)={mean_wr_lift:.3f}x")
        print(f"  sign consistency: {n_positive}/{n_days} days block>univ ({sign_frac*100:.0f}%)")
        print(f"  within-day null: median two-sided p={median_p:.4f}  (alpha={ALPHA:.5f})")
        print(f"  verdict: {verdict_str}\n")

        all_results.append({
            "stratum": sname, "window": w, "n_picks": n_picks, "n_days": n_days,
            "block_mean": mean_block, "univ_mean": mean_univ,
            "mean_lift": mean_lift, "wr_lift": mean_wr_lift,
            "sign_frac": sign_frac, "median_p": median_p,
            "verdict": verdict_str,
            "pooled_block_wr": pooled_block_wr, "pooled_univ_wr": pooled_univ_wr,
        })

# ── 7. Summary ────────────────────────────────────────────────────────────
print("=" * 72)
print("SUMMARY")
print("=" * 72)
hdr = f"{'stratum':<16} {'win':>3} {'n':>6} {'days':>5} {'block':>8} {'univ':>8} {'lift':>7} {'wr_lift':>7} {'med_p':>7}  verdict"
print(hdr)
print("-" * 110)
for r in all_results:
    print(f"{r['stratum']:<16} {r['window']:>3}d {r['n_picks']:>6} {r['n_days']:>5} {r['block_mean']:>+7.3f}% {r['univ_mean']:>+7.3f}% {r['mean_lift']:>+6.3f}% {r['wr_lift']:>6.3f}x {r['median_p']:>6.4f}  {r['verdict']}")

any_edge = any(r["verdict"].startswith(("EDGE", "WEAK EDGE", "THIN EDGE")) for r in all_results)
all_underpowered = all(r["verdict"] == "UNDERPOWERED" for r in all_results)
if all_underpowered:
    overall = "UNDERPOWERED — n<200 or days<60"
elif any_edge:
    overall = "EDGE — at least one stratum×window validated (Bonferroni-corrected)"
else:
    overall = "NO EDGE — no stratum×window passes Bonferroni threshold"
print(f"\nOverall: {overall}")
print(f"\n⚠️ 不外推：此 verdict 仅限「大宗交易折价×选股(D-1大宗→D open入场)」对窗口；")
print(f"   「无 selection edge」≠「无 edge」（盘中、资金流、动态卖出未测）。")
print(f"\nElapsed: {time.time()-t0:.1f}s")
