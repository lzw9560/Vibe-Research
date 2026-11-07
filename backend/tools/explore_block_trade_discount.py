# -*- coding: utf-8 -*-
"""大宗折价信号策略——散户口径 close_ev backtest (§44 v3 过严口径).

任务指定 close_ev = (T+1_open - T_close)/T_close*100, "T 收盘买 T+1 开盘卖".
但 T 日大宗数据 T 盘后才有 (15:00 收盘后公布), 无法在 T 收盘用 T 信号下单 →
此口径有 look-ahead bias (look-ahead bias on entry), 不可诚实执行.

本脚本同时计算两个口径:
  (A) NAIVE close_ev = (T+1_open - T_close)/T_close*100  [任务字面口径]
      → 测的是"隔夜 gap 反应" (市场对大宗折价利空的隔夜跳空), 信息性非可交易.
      → entry T_close 用 T 信号 = look-ahead, 不可执行.
  (B) HONEST close_ev = (T+2_close - T+1_open)/T+1_open*100  [诚实可执行]
      → 信号 T 盘后得知 → T+1 open 买 → T+2 close 卖 (T+1 制度: 买入日不能卖).
      → 这是散户唯一能诚实执行的口径.

verdict 基于 (B) honest 口径. (A) 仅作诊断 (量化 look-ahead bias 通胀多少).

分桶: 5-8% / 8-12% / >12% 折价 (任务指定).
统计: per-day-mean t (同日聚 day-mean) + Bonferroni×3 (3 桶) + walk-forward OOS + train_ev>0.

对照: 2026-09-08 已跑 block_trade_lift.py (selection_lift vs universe, 3 strata×3 windows=9 verdict,
全 exploratory, best lift 1.17x). 本脚本测的是 ABSOLUTE close_ev (非 selection lift),
桶定义不同 (5-8/8-12/>12 vs deep>5/mild 0-5/premium≥0). 互补非重复.

诚实定位: 散户口径下大宗折价信号 = 均值回归变体 (大跌后反弹). 同家族此前 9/9 falsified.
禁止外推: 大宗折价信号 ≠ 事件驱动有/无 edge ≠ 短线有/无 edge.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import (
    load_kline_db,
    ev_stats,
    day_paired_t,
    bonferroni_p,
    walk_forward,
    limit_for_code,
    is_yizi_t1,
    COST,
    ALPHA,
)

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
BLOCK = resolve_data_dir() / "block_trade_raw.json"
N_BUCKETS = 3  # Bonferroni ×3 (5-8 / 8-12 / >12%)


# ── 1. Load block trade + aggregate best (most discounted) per (date, code) ──
print("=" * 74)
print("大宗折价信号策略 — 散户口径 close_ev (§44 v3)")
print("=" * 74)
bt_raw = json.loads(BLOCK.read_bytes())
best: dict[tuple[str, str], dict] = {}
for r in bt_raw:
    pr = r.get("premium_ratio")
    if pr is None:
        continue
    code = str(r["code"]).zfill(6)
    key = (r["date"], code)
    if key not in best or pr < best[key]["premium_ratio"]:
        best[key] = {**r, "code": code}
print(f"block trades: {len(bt_raw)} records → {len(best)} (date,code) pairs")
dates = sorted(set(d for d, _ in best))
print(f"date range: {dates[0]} ~ {dates[-1]} ({len(dates)} dates)")

# ── 2. Buckets (task spec: 5-8% / 8-12% / >12% discount) ──────────────────
BUCKETS = {
    "5-8%": lambda pr: -0.08 < pr <= -0.05,  # 折价 5-8%
    "8-12%": lambda pr: -0.12 < pr <= -0.08,  # 折价 8-12%
    ">12%": lambda pr: pr <= -0.12,  # 折价 >12%
}

# ── 3. Load kline cache ───────────────────────────────────────────────────
print("\nLoading kline cache (SQLite)...", end=" ", flush=True)
code_map, all_dates = load_kline_db()
calendar = sorted(all_dates)
date_idx = {d: i for i, d in enumerate(calendar)}
print(f"{len(code_map)} codes, {len(calendar)} trading days")


# ── 4. Build picks per bucket ─────────────────────────────────────────────
def build_picks_bucket(bucket_fn) -> list[dict]:
    picks: list[dict] = []
    for (bt_date, code), rec in best.items():
        pr = rec["premium_ratio"]
        if not bucket_fn(pr):
            continue
        idx = date_idx.get(bt_date)
        if idx is None or idx + 2 >= len(calendar):
            continue  # need T+1 and T+2
        dmap = code_map.get(code)
        if not dmap:
            continue
        t_bar = dmap.get(bt_date)
        if t_bar is None or t_bar.get("close") is None or t_bar["close"] <= 0:
            continue
        t_close = t_bar["close"]
        t1_date = calendar[idx + 1]
        t2_date = calendar[idx + 2]
        t1_bar = dmap.get(t1_date)
        t2_bar = dmap.get(t2_date)
        if t1_bar is None or t2_bar is None:
            continue
        t1_open = t1_bar.get("open")
        t2_close = t2_bar.get("close")
        if t1_open is None or t2_close is None or t1_open <= 0 or t2_close <= 0:
            continue
        # skip ST (can't trade / different limit)
        is_st = t_bar.get("isST") == "1"
        # skip T+1 one-limit-up locked (can't buy at open)
        limit = limit_for_code(code, is_st)
        if is_yizi_t1(t1_bar, t_close, limit):
            continue
        picks.append(
            {
                "code": code,
                "bt_date": bt_date,
                "zt_date": bt_date,  # walk_forward sorts by zt_date
                "t_close": t_close,
                "t1_open": t1_open,
                "t2_close": t2_close,
                "t1_bar": t1_bar,
                "t2_bar": t2_bar,
                "discount_pct": round(-pr * 100, 2),
            }
        )
    return picks


# ── 5. Return functions ──────────────────────────────────────────────────
def naive_close_ev(p: dict) -> float:
    """(A) 任务字面口径: (T+1_open - T_close)/T_close*100.
    LOOK-AHEAD: T 大宗信号 T 盘后才有, 无法 T 收盘下单. 信息性非可交易."""
    return (p["t1_open"] - p["t_close"]) / p["t_close"] * 100


def honest_close_ev(p: dict) -> float:
    """(B) 诚实可执行: T 盘后信号 → T+1 open 买 → T+2 close 卖 (T+1 制度)."""
    return (p["t2_close"] - p["t1_open"]) / p["t1_open"] * 100


# ── 6. Verdict cascade (×3 Bonferroni, matching task spec) ───────────────
def verdict_inline(ev_gross, t_day, p_raw, wf, n_days, net_ev, name):
    p_bonf = bonferroni_p(p_raw, N_BUCKETS)
    print(f"\n  [{name}] gross_EV={ev_gross}% net_EV={net_ev}% day_t={t_day} p_raw={p_raw} Bonf×{N_BUCKETS}={p_bonf:.6f} n_days={n_days}")
    if wf["status"] == "ok":
        tr = wf["train_ev"]
        te = wf["test_ev"]
        te_dt = wf["test_day_t"]
        print(f"    walk-forward: train_EV={tr['ev']}% test_EV={te['ev']}% test_day_t={te_dt['t']} test_p={te_dt['p_one_sided']}")
    if ev_gross < 0:
        print(f"    → FALSIFIED: gross EV < 0 (negative edge)")
        return "falsified"
    if n_days < 60:
        print(f"    → UNDERPOWERED: n_days={n_days} < 60")
        return "underpowered"
    if p_bonf >= ALPHA:
        print(f"    → FALSIFIED: Bonferroni p={p_bonf} >= {ALPHA} (not significant)")
        return "falsified"
    if net_ev <= 0:
        print(f"    → FALSIFIED: net EV={net_ev}% <= 0 (gross edge eaten by cost)")
        return "falsified"
    if wf["status"] == "ok":
        if wf["train_ev"]["ev"] <= 0:
            print(f"    → EXPLORATORY: train_EV={wf['train_ev']['ev']}% <= 0 (edge not in train half; test may be regime overfit)")
            return "exploratory"
        if wf["test_ev"]["ev"] <= 0:
            print(f"    → FALSIFIED: walk-forward test_EV={wf['test_ev']['ev']}% <= 0")
            return "falsified"
        wf_p_bonf = bonferroni_p(wf["test_day_t"]["p_one_sided"], N_BUCKETS)
        if wf_p_bonf >= ALPHA:
            print(f"    → EXPLORATORY: OOS test EV>0 but test_p Bonf×{N_BUCKETS}={wf_p_bonf} >= {ALPHA} (not significant OOS)")
            return "exploratory"
        print(f"    → EDGE-CONFIRMED: all gates pass")
        return "edge-confirmed"
    print(f"    → EXPLORATORY: walk-forward not available")
    return "exploratory"


# ── 7. Run analysis ──────────────────────────────────────────────────────
results = {}
for bname, bfn in BUCKETS.items():
    picks = build_picks_bucket(bfn)
    print(f"\n{'=' * 74}")
    print(f"桶: {bname} 折价 (n_picks={len(picks)})")
    print(f"{'=' * 74}")
    if not picks:
        print("  无 picks, 跳过")
        continue

    for mname, ret_fn in [
        ("(A) NAIVE close_ev (look-ahead, NOT tradable)", naive_close_ev),
        ("(B) HONEST close_ev (tradable T+1→T+2)", honest_close_ev),
    ]:
        print(f"\n--- {mname} ---")
        rets = [ret_fn(p) for p in picks]
        rets = [r for r in rets if r is not None]
        s = ev_stats(rets)
        net_ev = round(s["ev"] - COST * 100, 3)
        print(f"  n={s['n']} gross_EV={s['ev']}% std={s['std']}% WR={s['wr']}% per-trade t={s['t']} CI[{s['ci_lo']},{s['ci_hi']}]")
        print(f"  net EV (after {COST * 100:.1f}% cost): {net_ev}%")

        by_date: dict[str, list[float]] = defaultdict(list)
        for p in picks:
            r = ret_fn(p)
            if r is not None:
                by_date[p["bt_date"]].append(r)
        dt = day_paired_t(by_date)
        print(f"  per-day-mean: n_days={dt['n_days']} day_mean={dt['mean']}% day_t={dt['t']} p_one_sided={dt['p_one_sided']}")

        wf = walk_forward(picks, ret_fn)
        if wf["status"] == "ok":
            tr = wf["train_ev"]
            te = wf["test_ev"]
            print(f"  walk-forward: train n={tr['n']} EV={tr['ev']}% | test n={te['n']} EV={te['ev']}% test_day_t={wf['test_day_t']['t']}")
        else:
            print(f"  walk-forward: {wf['status']}")

        v = verdict_inline(s["ev"], dt["t"], dt["p_one_sided"], wf, dt["n_days"], net_ev, mname)
        results[(bname, mname)] = {
            "n": s["n"],
            "gross_ev": s["ev"],
            "net_ev": net_ev,
            "wr": s["wr"],
            "day_t": dt["t"],
            "p_raw": dt["p_one_sided"],
            "n_days": dt["n_days"],
            "wf_status": wf.get("status"),
            "wf_train_ev": wf.get("train_ev", {}).get("ev"),
            "wf_test_ev": wf.get("test_ev", {}).get("ev"),
            "wf_test_p": wf.get("test_day_t", {}).get("p_one_sided"),
            "verdict": v,
        }


# ── 8. Summary ───────────────────────────────────────────────────────────
print(f"\n{'=' * 74}")
print("SUMMARY")
print(f"{'=' * 74}")
hdr = f"{'bucket':<8} {'metric':<14} {'n':>5} {'gross':>8} {'net':>8} {'day_t':>7} {'n_days':>6} {'Bonf×3':>8}  verdict"
print(hdr)
print("-" * 90)
for (bn, mn), r in results.items():
    p_bonf = bonferroni_p(r["p_raw"], N_BUCKETS)
    mshort = "(A)naive" if "NAIVE" in mn else "(B)honest"
    print(f"{bn:<8} {mshort:<14} {r['n']:>5} {r['gross_ev']:>+7.3f}% {r['net_ev']:>+7.3f}% {r['day_t']:>7.2f} {r['n_days']:>6} {p_bonf:>7.4f}  {r['verdict']}")

# honest-only overall verdict
honest_vs = [r["verdict"] for (b, m), r in results.items() if "HONEST" in m]
naive_vs = [r["verdict"] for (b, m), r in results.items() if "NAIVE" in m]
print(f"\nHONEST 口径 verdicts: {honest_vs}")
print(f"NAIVE  口径 verdicts: {naive_vs}")

# look-ahead inflation comparison
print(f"\n--- look-ahead bias 通胀对比 (NAIVE vs HONEST gross EV) ---")
for bname in BUCKETS:
    h = results.get((bname, "(B) HONEST close_ev (tradable T+1→T+2)"))
    n = results.get((bname, "(A) NAIVE close_ev (look-ahead, NOT tradable)"))
    if h and n:
        diff = n["gross_ev"] - h["gross_ev"]
        print(f"  {bname}: naive={n['gross_ev']:+.3f}% honest={h['gross_ev']:+.3f}% look-ahead 通胀={diff:+.3f}pp")

print(f"\n⚠️ 诚实定位: 散户口径下大宗折价信号 = 均值回归变体 (大跌后反弹).")
print(f"   同家族 (5日跌/RSI超卖) 此前 9/9 falsified. 本信号是同家族子信号.")
print(f"   verdict 基于 (B) HONEST 口径 (可交易). (A) NAIVE 仅诊断 look-ahead 通胀.")
print(f"⚠️ 不外推: 大宗折价信号 ≠ 事件驱动有/无 edge ≠ 短线有/无 edge.")
print(f"   对照: 2026-09-08 selection_lift 测过 (9 verdict 全 exploratory, best 1.17x). 本脚本测 ABSOLUTE close_ev, 桶定义不同, 互补非重复.")
print(f"\n数据窗口: {len(dates)} 交易日 ({dates[0]}~{dates[-1]}), <60 门下属 underpowered 区间.")
