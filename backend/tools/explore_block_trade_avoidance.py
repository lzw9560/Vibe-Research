# -*- coding: utf-8 -*-
"""S4: 大宗折价避险信号 — BHAR vs size-matched benchmark (R12).

信号: premium_ratio < -0.10 (深折价=smart money 卖出/派发) AND buyer != seller
      (排除关联方对倒) → 该股 T+1 open → T+10/T+20 close 是否 underperform
      同 size-decile peers (BHAR < 0).

逻辑: 把"跟吸筹"翻转为"避派发". 大宗深折价=大宗买方拿到折价=卖方急于出清
      (smart money distributing). 若这些股后续 underperform 同体量 peers →
      避开它们 = 正向 alpha (avoidance valid).

口径 (§44 v3 + 10 flaw):
  - entry = T+1 open (T 盘后信号 → T+1 open 执行, 非 T close look-ahead)
  - exit = T+K close (K=5/10/20), 非 open_ev (防日内泄漏)
  - 不 skip 一字 (避险信号: 测"这些股是否 underperform", 非测"能否交易";
    若 T+1 一字跌停→已 crash, 避开更正确, 非 tradability 问题)
  - BHAR = stock_ret - size_decile_mean_ret (R12 全市场 decile, 非沪深300)
  - per-day-mean t (同日聚 day-mean, 非逐笔 t)
  - Bonferroni ×3 (3 windows: T+5/T+10/T+20)
  - walk-forward OOS (前半 train → 后半 test)
  - high-risk lens: 不 gate on median<0 / WR<45% (mean真负+left tail可捕获即可)

R13 survivorship: kline cache 5248 codes, 多数 ~179 bars (2025-12~2026-09).
  block trade 2026-02~2026-09. cache 建 ~2026-09. 信号期股存在→survivorship
  最小. 但退市股 (如有) 缺 exit bar → skip → 负收益缺失 → BHAR 偏高 (保守).
"""
import json, sqlite3, sys, statistics, time
from pathlib import Path
from collections import defaultdict
from math import erf, sqrt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import limit_for_code, is_yizi_t1, COST, ALPHA

ROOT = Path(__file__).resolve().parents[2]
BLOCK = ROOT / ".vibe-research" / "block_trade_raw.json"
KLINE_DB = ROOT / ".vibe-research" / "baostock_kline_cache.db"
IDX = ROOT / ".vibe-research" / "index_ohlc_cache.json"
N_BONF = 3  # Bonferroni ×3 (T+5/T+10/T+20)
WINDOWS = [5, 10, 20]
DISCOUNT_THRESH = -0.10


def norm_sf_neg(t: float) -> float:
    """One-sided p for NEGATIVE edge test (avoidance): P(Z <= t).
    For t<0 (negative mean) → small p = significant underperformance.
    For t>=0 → p>=0.5 = no underperformance."""
    return 0.5 * (1 + erf(t / sqrt(2)))


def ev_stats(rets):
    n = len(rets)
    if n == 0:
        return {"n": 0, "ev": 0.0, "std": 0.0, "t": 0.0, "wr": 0.0, "median": 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    wr = sum(1 for x in rets if x > 0) / n
    return {"n": n, "ev": round(mean, 3), "std": round(std, 3), "t": round(t, 2),
            "wr": round(wr * 100, 1), "median": round(statistics.median(rets), 3)}


def day_paired_t_neg(rets_by_date):
    """Per-day-mean t for NEGATIVE test (avoidance)."""
    day_means = [sum(rs) / len(rs) for rs in rets_by_date.values() if rs]
    n = len(day_means)
    if n == 0:
        return {"n_days": 0, "mean": 0.0, "std": 0.0, "t": 0.0, "p_one_sided": 1.0}
    mean = sum(day_means) / n
    std = statistics.pstdev(day_means) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = norm_sf_neg(t)
    return {"n_days": n, "mean": round(mean, 3), "std": round(std, 3),
            "t": round(t, 2), "p_one_sided": round(p, 6)}


# ── 1. Load block trades, filter ──────────────────────────────────────────
print("=" * 74)
print("S4: 大宗折价避险 — BHAR vs size-matched benchmark (R12)")
print("=" * 74)
bt_raw = json.loads(BLOCK.read_bytes())
print(f"block_trade_raw: {len(bt_raw)} records")
best = {}
n_deep = 0
n_duodao = 0
for r in bt_raw:
    pr = r.get("premium_ratio")
    if pr is None:
        continue
    if pr >= DISCOUNT_THRESH:
        continue  # only deep discount
    n_deep += 1
    if r.get("buyer") == r.get("seller"):
        n_duodao += 1
        continue  # exclude 对倒
    code = str(r["code"]).zfill(6)
    key = (r["date"], code)
    if key not in best or pr < best[key]["premium_ratio"]:
        best[key] = {**r, "code": code}
dates = sorted(set(d for d, _ in best))
print(f"deep(<{DISCOUNT_THRESH*100:.0f}%): {n_deep}, exclude buyer==seller 对倒: {n_duodao}")
print(f"→ {len(best)} (date,code) signals, {len(dates)} dates ({dates[0]}~{dates[-1]})")

# ── 2. Load kline cache ──────────────────────────────────────────────────
print("\nLoading kline cache...", end=" ", flush=True)
t0 = time.time()
conn = sqlite3.connect(str(KLINE_DB))
code_map = {}
all_dates = set()
bar_counts = []
for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
    bars = json.loads(bj)
    dmap = {b["date"]: b for b in bars if b.get("date")}
    if dmap:
        code_map[code] = dmap
        all_dates.update(dmap.keys())
        bar_counts.append(len(dmap))
conn.close()
calendar = sorted(all_dates)
date_idx = {d: i for i, d in enumerate(calendar)}
print(f"{len(code_map)} codes, {len(calendar)} dates, "
      f"bars/code: min={min(bar_counts)} med={statistics.median(bar_counts)} max={max(bar_counts)} "
      f"({time.time()-t0:.1f}s)")

# ── 3. Size deciles (float_mcap proxy = close * volume * 100 / turn) ──────
print("Computing size deciles...", end=" ", flush=True)
mcap = {}
for code, dmap in code_map.items():
    vals = []
    for b in dmap.values():
        t, v, c = b.get("turn"), b.get("volume"), b.get("close")
        if t and v and c and t > 0 and v > 0 and c > 0:
            vals.append(c * v * 100 / t)
    if vals:
        mcap[code] = statistics.median(vals)
sorted_codes = sorted(mcap, key=lambda c: mcap[c])
n = len(sorted_codes)
decile_of = {}
for i, code in enumerate(sorted_codes):
    decile_of[code] = min(9, i * 10 // n)
print(f"{n} codes with mcap → 10 deciles")
sig_dec = defaultdict(int)
for (_, code) in best:
    d = decile_of.get(code)
    if d is not None:
        sig_dec[d] += 1
print(f"signal stock decile dist (0=smallest→9=largest): {dict(sorted(sig_dec.items()))}")
sm_sig = sum(v for k, v in sig_dec.items() if k <= 2)
print(f"  decile 0-2 (small): {sm_sig} ({100*sm_sig/len(best):.1f}%) | "
      f"decile 7-9 (large): {sum(v for k,v in sig_dec.items() if k>=7)} ({100*sum(v for k,v in sig_dec.items() if k>=7)/len(best):.1f}%)")

# ── 4. Pre-compute size-decile benchmark returns per (date, K) ───────────
print("Pre-computing size-decile benchmark...", end=" ", flush=True)
benchmark = {}
for bt_date in dates:
    di = date_idx.get(bt_date)
    if di is None:
        continue
    ei = di + 1
    if ei >= len(calendar):
        continue
    ed = calendar[ei]
    for K in WINDOWS:
        xi = di + K
        if xi >= len(calendar):
            continue
        xd = calendar[xi]
        dec_rets = defaultdict(list)
        for code, dmap in code_map.items():
            d = decile_of.get(code)
            if d is None:
                continue
            eb = dmap.get(ed)
            xb = dmap.get(xd)
            if not eb or not xb:
                continue
            eo, xc = eb.get("open"), xb.get("close")
            if not eo or not xc or eo <= 0 or xc <= 0:
                continue
            if str(eb.get("isST", "0")) == "1":
                continue
            dec_rets[d].append((xc - eo) / eo * 100)
        benchmark[(bt_date, K)] = {d: statistics.mean(rs) for d, rs in dec_rets.items() if rs}
print(f"done ({time.time()-t0:.1f}s)")

# ── 4b. 上证综指 benchmark (diagnostic only, NOT verdict benchmark) ────
idx_data = json.loads(IDX.read_bytes())
idx_bars = idx_data.get("sh.000001", [])
idx_map = {b["date"]: b for b in idx_bars if b.get("date")}

# ── 5. Build picks + BHAR ─────────────────────────────────────────────────
results_by_K = {K: [] for K in WINDOWS}
n_no_kline = 0
n_no_exit = 0
for (bt_date, code) in best:
    di = date_idx.get(bt_date)
    if di is None:
        continue
    ei = di + 1
    if ei >= len(calendar):
        continue
    ed = calendar[ei]
    dmap = code_map.get(code)
    if not dmap:
        n_no_kline += 1
        continue
    eb = dmap.get(ed)
    if not eb:
        n_no_kline += 1
        continue
    eo = eb.get("open")
    if not eo or eo <= 0:
        continue
    if str(eb.get("isST", "0")) == "1":
        continue
    dec = decile_of.get(code)
    if dec is None:
        continue
    for K in WINDOWS:
        xi = di + K
        if xi >= len(calendar):
            n_no_exit += 1
            continue
        xd = calendar[xi]
        xb = dmap.get(xd)
        if not xb:
            n_no_exit += 1
            continue
        xc = xb.get("close")
        if not xc or xc <= 0:
            n_no_exit += 1
            continue
        stock_ret = (xc - eo) / eo * 100
        bench = benchmark.get((bt_date, K), {}).get(dec)
        if bench is None:
            continue
        bhar = stock_ret - bench
        # 上证综指 return over same window (diagnostic)
        ib = idx_map.get(ed)
        ix = idx_map.get(xd)
        idx_ret = None
        if ib and ix and ib.get("open") and ix.get("close"):
            idx_ret = (ix["close"] - ib["open"]) / ib["open"] * 100
        results_by_K[K].append({
            "code": code, "bt_date": bt_date, "stock_ret": stock_ret,
            "bench": bench, "bhar": bhar, "decile": dec, "idx_ret": idx_ret,
        })
print(f"\npicks: skipped {n_no_kline} (no kline/ST), {n_no_exit} (no exit bar within calendar)")

# ── 6. Stats + verdict per window ────────────────────────────────────────
summary = {}
for K in WINDOWS:
    picks = results_by_K[K]
    print(f"\n{'=' * 74}")
    print(f"Window: T+{K} close (n_picks={len(picks)})")
    print(f"{'=' * 74}")
    if not picks:
        print("  无 picks")
        continue

    bhars = [p["bhar"] for p in picks]
    raws = [p["stock_ret"] for p in picks]
    benchs = [p["bench"] for p in picks]
    idxs = [p["idx_ret"] for p in picks if p["idx_ret"] is not None]
    s = ev_stats(bhars)
    rs = ev_stats(raws)
    bs = ev_stats(benchs)
    print(f"  raw stock return:  mean={rs['ev']:+.3f}% std={rs['std']:.3f}% WR={rs['wr']}% median={rs['median']:+.3f}%")
    print(f"  size-decile bench: mean={bs['ev']:+.3f}% std={bs['std']:.3f}%")
    if idxs:
        is_ = ev_stats(idxs)
        print(f"  上证综指 (diag):    mean={is_['ev']:+.3f}%")
    print(f"  BHAR (abnormal):   mean={s['ev']:+.3f}% std={s['std']:.3f}% "
          f"t={s['t']:.2f} WR(underperf)={100*sum(1 for b in bhars if b<0)/len(bhars):.1f}% "
          f"median={s['median']:+.3f}%")

    by_date = defaultdict(list)
    for p in picks:
        by_date[p["bt_date"]].append(p["bhar"])
    dt = day_paired_t_neg(by_date)
    p_bonf = min(1.0, dt["p_one_sided"] * N_BONF)
    print(f"  per-day BHAR: n_days={dt['n_days']} day_mean={dt['mean']:+.3f}% "
          f"day_t={dt['t']:.2f} p_one_sided(neg)={dt['p_one_sided']:.6f} "
          f"Bonf×{N_BONF}={p_bonf:.6f}")

    # walk-forward
    ps = sorted(picks, key=lambda p: p["bt_date"])
    wdates = sorted(set(p["bt_date"] for p in ps))
    mid = len(wdates) // 2
    train_dates = set(wdates[:mid])
    test_dates = set(wdates[mid:])
    train_b = [p["bhar"] for p in ps if p["bt_date"] in train_dates]
    test_b = [p["bhar"] for p in ps if p["bt_date"] in test_dates]
    train_ev = sum(train_b)/len(train_b) if train_b else 0
    test_ev = sum(test_b)/len(test_b) if test_b else 0
    test_by_date = defaultdict(list)
    for p in ps:
        if p["bt_date"] in test_dates:
            test_by_date[p["bt_date"]].append(p["bhar"])
    test_dt = day_paired_t_neg(test_by_date)
    test_p_bonf = min(1.0, test_dt["p_one_sided"] * N_BONF)
    print(f"  walk-forward: train_BHAR={train_ev:+.3f}% (n={len(train_b)},{mid}d) | "
          f"test_BHAR={test_ev:+.3f}% (n={len(test_b)},{len(wdates)-mid}d)")
    print(f"    test day_t={test_dt['t']:.2f} test_p={test_dt['p_one_sided']:.6f} "
          f"Bonf={test_p_bonf:.6f}")

    # verdict (avoidance: BHAR<0 = valid)
    print(f"\n  VERDICT (avoidance: BHAR<0 & significant = edge-confirmed):")
    if dt["mean"] >= 0:
        print(f"    → FALSIFIED: day-mean BHAR={dt['mean']:+.3f}% >= 0 "
              f"(avoided stocks do NOT underperform size peers)")
        v = "falsified"
    elif dt["n_days"] < 60:
        print(f"    → UNDERPOWERED: n_days={dt['n_days']} < 60 (single regime)")
        v = "underpowered"
    elif p_bonf >= ALPHA:
        print(f"    → FALSIFIED: Bonf p={p_bonf:.6f} >= {ALPHA} (not significant)")
        v = "falsified"
    elif test_ev >= 0:
        print(f"    → FALSIFIED: walk-forward test_BHAR={test_ev:+.3f}% >= 0 (OOS not negative)")
        v = "falsified"
    elif test_p_bonf >= ALPHA:
        print(f"    → EXPLORATORY: OOS test BHAR<0 but test_p Bonf={test_p_bonf:.6f} >= {ALPHA}")
        v = "exploratory"
    else:
        print(f"    → EDGE-CONFIRMED: BHAR<0, Bonf PASS, OOS test BHAR<0 & significant")
        v = "edge-confirmed"
    summary[K] = {"n": len(picks), "n_days": dt["n_days"], "gross_ev": rs["ev"],
                  "bench_ev": bs["ev"], "bhar_ev": s["ev"], "net_ev": s["ev"],
                  "median_ev": s["median"], "wr": s["wr"], "day_t": dt["t"],
                  "p_raw": dt["p_one_sided"], "p_bonf": p_bonf,
                  "wf_train_ev": round(train_ev, 3), "wf_test_ev": round(test_ev, 3),
                  "wf_test_p": test_dt["p_one_sided"], "verdict": v}

# ── 7. Summary + R12/R13 report ───────────────────────────────────────────
print(f"\n{'=' * 74}")
print("SUMMARY")
print(f"{'=' * 74}")
print(f"{'window':<8} {'n':>6} {'days':>5} {'gross':>8} {'bench':>8} {'BHAR':>8} "
      f"{'med':>7} {'wr':>6} {'day_t':>7} {'Bonf':>8} {'wf_test':>8}  verdict")
print("-" * 105)
for K in WINDOWS:
    r = summary.get(K)
    if not r:
        continue
    print(f"T+{K:<6} {r['n']:>6} {r['n_days']:>5} {r['gross_ev']:>+7.3f}% {r['bench_ev']:>+7.3f}% "
          f"{r['bhar_ev']:>+7.3f}% {r['median_ev']:>+6.3f}% {r['wr']:>5.1f}% "
          f"{r['day_t']:>7.2f} {r['p_bonf']:>7.4f} {r['wf_test_ev']:>+7.3f}%  {r['verdict']}")

# R12 verdict
best_K = None
best_bh = -999
for K in WINDOWS:
    r = summary.get(K)
    if r and r["bhar_ev"] < best_bh:
        best_bh = r["bhar_ev"]
        best_K = K
print(f"\n--- R12 size-matched benchmark verdict ---")
if best_K:
    r = summary[best_K]
    print(f"  best window T+{best_K}: BHAR={r['bhar_ev']:+.3f}% (gross={r['gross_ev']:+.3f}% "
          f"vs size-decile bench={r['bench_ev']:+.3f}%)")
    if r["bhar_ev"] < 0 and r["p_bonf"] < ALPHA:
        print(f"  → avoided stocks underperform size peers by {abs(r['bhar_ev']):.3f}% "
              f"(Bonf p={r['p_bonf']:.4f}) → R12 PASS (underperformance is NOT just size effect)")
    elif r["bhar_ev"] < 0:
        print(f"  → BHAR<0 but not significant (Bonf p={r['p_bonf']:.4f}) → R12 weak")
    else:
        print(f"  → BHAR>=0 → R12 FAIL (no underperformance vs size peers)")

print(f"\n--- R13 survivorship ---")
print(f"  kline cache: {len(code_map)} codes, bars/code min={min(bar_counts)} med={statistics.median(bar_counts)} max={max(bar_counts)}")
print(f"  calendar: {calendar[0]}~{calendar[-1]} ({len(calendar)} dates)")
print(f"  block trade dates: {dates[0]}~{dates[-1]} ({len(dates)} dates)")
print(f"  R13: cache built ~2026-09, block trades 2026-02~09. Signal-period stocks exist")
print(f"       at cache-build → survivorship minimal for THIS signal window.")
print(f"       BUT: ~{statistics.median(bar_counts):.0f} bars/code → most codes only have recent data")
print(f"       (2025-12~2026-09). Any stock delisted between block trade date and cache-build")
print(f"       → missing exit bar → skipped → its crash return absent → BHAR biased UPWARD")
print(f"       (conservative for avoidance: if underperformance survives despite missing")
print(f"       delisted losers, real effect is STRONGER). Cannot quantify delisted count")
print(f"       without separate delisting data → known unquantified bias direction.")

print(f"\n--- honest positioning ---")
print(f"  signal = avoidance (避派发), NOT buy. verdict = BHAR<0 & significant = avoidance valid.")
print(f"  high-risk lens: mean真负 + left tail可捕获, 不 gate on median<0/WR<45%.")
print(f"  {len(dates)} dates single regime (2026-02~09) → cross-regime NOT tested.")
print(f"  不外推: 大宗折价避险 ≠ 全事件驱动有/无 edge ≠ 短线有/无 edge.")
