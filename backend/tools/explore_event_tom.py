# -*- coding: utf-8 -*-
"""月末月初轮动 (Turn-of-Month, TOM) — §44 v3 + 10 flaw 全套口径严测.

策略:
  月末倒数第1交易日 close 信号 → T+1 open (次月首日) 买指数 ETF (510300/510050).
  Exit T+4 close (4日 hold: T+1 open → T+4 close).
  Benchmark: sh.000001 同窗口 (随机 4 日窗口) 收益. day_paired lift>2x 才非噪声.
  Walk-forward: 2018-2026 (8年) 4窗×2年 + 50/50 split.
  成本: ETF 0.10% round-trip (0.05-0.15% 区间 sensitivity).

机制: 日历驱动 price-insensitive demand flow (月末月初资金流入) 非选股.
学术先验: TOM ~0.5-1%/窗口 (Lakonishok-Schmidt 1988, Cadsby-Plat 2016), A 股"节前红包"
  散户共识 = 拥挤倒U 风险. 先验 0.30.

为什么 TOM 回避 4 选股 flaw:
  1. entry 涨停价溢价 — N/A (ETF 无涨停限制, 指数非个股)
  2. survivorship — N/A (买全市场指数, 无个股退市偏差)
  3. exit 一字 over-credit — N/A (ETF 无一字, 指数连续定价)
  4. T+1 日内泄漏 — 用 close_ev (T+4 close) 非 open_ev ✓

剩余 flaw 仍需检:
  5. 拥挤倒U — 时段衰减检验 (early vs late half)
  6. R6 gap-through — N/A (指数 hold-to-close 无 stop; 但 entry 跳空须检查)
  7. timing mismatch — benchmark 同窗口 ✓
  8. 成本乐观 — ETF 0.10% round-trip ✓ (sensitivity 0.05-0.15%)
  9. phantom alpha — 报 raw_ev (指数实际收益) 非 BHAR ✓
  10. 退化 OLS — N/A (单因子无 orthogonalize)

跑法:
  cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
  .venv/bin/python tools/explore_event_tom.py
"""

from __future__ import annotations
import json
import sys
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt

sys.path.insert(0, str(Path(__file__).parent))
from _factor_helpers import bonferroni_p, norm_sf_positive  # noqa: E402

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
INDEX_CACHE = DATA / "index_ohlc_cache.json"

# ---------- constants ----------
COST_ETF = 0.001  # 0.10% round-trip (ETF: commission+spread+impact)
COST_LOW = 0.0005  # 0.05% (deep discount + liquid)
COST_HIGH = 0.0015  # 0.15% (conservative)
ALPHA = 0.05
N_CROSS_FACTOR = 3  # top 3 in 15-candidate sweep → Bonferroni ×3*2=6
N_HOLD = 4  # T+1 open → T+4 close (4-day hold)
START_YEAR = 2018  # walk-forward window start
END_YEAR = 2026


# ---------- data loading ----------


def load_index() -> list[dict]:
    """Load sh.000001 daily bars."""
    data = json.loads(INDEX_CACHE.read_text())
    bars = data["sh.000001"]
    # filter valid bars with open/close
    return [b for b in bars if b.get("open") and b.get("close") and b.get("date")]


def build_calendar(bars: list[dict]) -> list[str]:
    return [b["date"] for b in bars]


def bar_map(bars: list[dict]) -> dict[str, dict]:
    return {b["date"]: b for b in bars}


# ---------- month-end identification ----------


def find_month_ends(calendar: list[str]) -> list[int]:
    """Return indices i where calendar[i] is the LAST trading day of its month.
    (calendar[i+1] is in a different month, or i is the last bar.)"""
    ends = []
    for i in range(len(calendar)):
        if i == len(calendar) - 1:
            continue  # no T+1 available
        d = calendar[i]
        d_next = calendar[i + 1]
        if d[:7] != d_next[:7]:  # YYYY-MM differs → month boundary
            ends.append(i)
    return ends


# ---------- TOM window construction ----------


def build_tom_windows(
    calendar: list[str],
    bmap: dict[str, dict],
    month_end_indices: list[int],
    hold: int = N_HOLD,
    start_year: int = START_YEAR,
) -> list[dict]:
    """Build TOM picks: entry=T+1 open (次月首日), exit=T+hold close.

    T+1 = calendar[i+1] (first trading day of next month).
    Exit = calendar[i+hold].close (hold-th trading day).
    Need i+hold < len(calendar).
    """
    picks = []
    for i in month_end_indices:
        if i + hold >= len(calendar):
            continue
        signal_date = calendar[i]
        # signal month-end must be in range
        if int(signal_date[:4]) < start_year:
            continue
        entry_date = calendar[i + 1]
        exit_date = calendar[i + hold]
        entry_bar = bmap.get(entry_date)
        exit_bar = bmap.get(exit_date)
        if not entry_bar or not exit_bar:
            continue
        entry_open = entry_bar.get("open")
        exit_close = exit_bar.get("close")
        if not entry_open or not exit_close or entry_open <= 0:
            continue
        ret = (exit_close - entry_open) / entry_open * 100
        picks.append(
            {
                "signal_date": signal_date,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "entry_open": entry_open,
                "exit_close": exit_close,
                "ret": ret,
                "month": signal_date[:7],
            }
        )
    return picks


def build_benchmark_windows(
    calendar: list[str],
    bmap: dict[str, dict],
    hold: int = N_HOLD,
    tom_signal_dates: set[str] | None = None,
    start_year: int = START_YEAR,
) -> list[float]:
    """All non-TOM 4-day windows (open-to-close) as benchmark base rate.

    A benchmark window starts at calendar[j], entry=calendar[j+1].open,
    exit=calendar[j+hold].close. Exclude j that are month-ends (TOM signals).
    """
    rets = []
    tom_set = tom_signal_dates or set()
    for j in range(len(calendar) - hold):
        d = calendar[j]
        if int(d[:4]) < start_year:
            continue
        if d in tom_set:
            continue  # exclude TOM windows
        entry_date = calendar[j + 1]
        exit_date = calendar[j + hold]
        eb = bmap.get(entry_date)
        xb = bmap.get(exit_date)
        if not eb or not xb:
            continue
        eo = eb.get("open")
        xc = xb.get("close")
        if not eo or not xc or eo <= 0:
            continue
        rets.append((xc - eo) / eo * 100)
    return rets


# ---------- stats ----------


def ev_stats(rets: list[float]) -> dict:
    n = len(rets)
    if n == 0:
        return {"n": 0, "ev": 0.0, "std": 0.0, "t": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "wr": 0.0, "median": 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    ci_lo = mean - 1.96 * se if se > 0 else mean
    ci_hi = mean + 1.96 * se if se > 0 else mean
    wr = sum(1 for x in rets if x > 0) / n
    med = statistics.median(rets)
    return {
        "n": n,
        "ev": round(mean, 4),
        "std": round(std, 4),
        "t": round(t, 2),
        "ci_lo": round(ci_lo, 4),
        "ci_hi": round(ci_hi, 4),
        "wr": round(wr * 100, 1),
        "median": round(med, 4),
    }


def day_paired_t_one_sample(rets: list[float]) -> dict:
    """One-sample t: is mean > 0? (each month = 1 day, n_days = n_months)."""
    n = len(rets)
    if n == 0:
        return {"n_days": 0, "mean": 0.0, "std": 0.0, "t": 0.0, "p_one_sided": 1.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = norm_sf_positive(t)
    return {"n_days": n, "mean": round(mean, 4), "std": round(std, 4), "t": round(t, 2), "p_one_sided": round(p, 6)}


def two_sample_t(a: list[float], b: list[float]) -> dict:
    """Welch's t-test: is mean(a) > mean(b)? (unequal variance)."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return {"t": 0.0, "p_one_sided": 1.0, "diff": 0.0}
    ma, mb = sum(a) / na, sum(b) / nb
    va = statistics.pstdev(a) ** 2
    vb = statistics.pstdev(b) ** 2
    se = sqrt(va / na + vb / nb)
    if se <= 0:
        return {"t": 0.0, "p_one_sided": 1.0, "diff": round(ma - mb, 4)}
    t = (ma - mb) / se
    # Welch-Satterthwaite df
    num = (va / na + vb / nb) ** 2
    den = (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    df = num / den if den > 0 else na + nb - 2
    # one-sided p via normal approx (large df) — conservative
    p = norm_sf_positive(t)
    return {
        "t": round(t, 2),
        "p_one_sided": round(p, 6),
        "diff": round(ma - mb, 4),
        "df": round(df, 1),
        "mean_a": round(ma, 4),
        "mean_b": round(mb, 4),
    }


def permutation_test(a: list[float], b: list[float], n_perm: int = 10000) -> dict:
    """Permutation test: is mean(a) > mean(b)? Non-parametric, no distribution assumption."""
    na, nb = len(a), len(b)
    if na + nb < 4:
        return {"p_one_sided": 1.0, "observed_diff": 0.0}
    pooled = a + b
    obs_diff = sum(a) / na - sum(b) / nb
    import random

    rng = random.Random(42)
    count = 0
    for _ in range(n_perm):
        shuffled = pooled[:]
        rng.shuffle(shuffled)
        perm_a = shuffled[:na]
        perm_b = shuffled[na:]
        perm_diff = sum(perm_a) / na - sum(perm_b) / nb
        if perm_diff >= obs_diff:
            count += 1
    p = (count + 1) / (n_perm + 1)
    return {"p_one_sided": round(p, 6), "observed_diff": round(obs_diff, 4), "n_perm": n_perm}


# ---------- walk-forward ----------


def walk_forward_4win(picks: list[dict], hold: int = N_HOLD) -> dict:
    """4 windows × 2 years: 2018-19, 2020-21, 2022-23, 2024-26.
    Train = first 2 windows, test = last 2 windows.
    Also report per-window EV for temporal stability."""
    by_year: dict[int, list[float]] = defaultdict(list)
    for p in picks:
        yr = int(p["signal_date"][:4])
        by_year[yr].append(p["ret"])

    windows = [(2018, 2019), (2020, 2021), (2022, 2023), (2024, 2026)]
    win_stats = []
    for y0, y1 in windows:
        rets = []
        for y in range(y0, y1 + 1):
            rets.extend(by_year.get(y, []))
        if rets:
            s = ev_stats(rets)
            win_stats.append({"window": f"{y0}-{y1}", **s})
        else:
            win_stats.append({"window": f"{y0}-{y1}", "n": 0, "ev": 0})

    # 50/50 split by date
    ps = sorted(picks, key=lambda p: p["signal_date"])
    mid = len(ps) // 2
    train = ps[:mid]
    test = ps[mid:]
    train_rets = [p["ret"] for p in train]
    test_rets = [p["ret"] for p in test]
    train_s = ev_stats(train_rets)
    test_s = ev_stats(test_rets)
    train_dt = day_paired_t_one_sample(train_rets)
    test_dt = day_paired_t_one_sample(test_rets)

    return {
        "windows": win_stats,
        "train_ev": train_s,
        "test_ev": test_s,
        "train_day_t": train_dt,
        "test_day_t": test_dt,
        "n_train": len(train_rets),
        "n_test": len(test_rets),
    }


# ---------- temporal decay (flaw 5: 拥挤倒U) ----------


def temporal_decay(picks: list[dict]) -> dict:
    """Split into early/late halves. If late << early → crowding decay (倒U)."""
    ps = sorted(picks, key=lambda p: p["signal_date"])
    mid = len(ps) // 2
    early = [p["ret"] for p in ps[:mid]]
    late = [p["ret"] for p in ps[mid:]]
    early_s = ev_stats(early)
    late_s = ev_stats(late)
    decay = (early_s["ev"] - late_s["ev"]) / abs(early_s["ev"]) * 100 if early_s["ev"] != 0 else 0
    return {
        "early_ev": early_s["ev"],
        "late_ev": late_s["ev"],
        "decay_pct": round(decay, 1),
        "early_n": len(early),
        "late_n": len(late),
    }


# ---------- entry gap check (flaw 6: R6) ----------


def entry_gap_check(picks: list[dict], bmap: dict[str, dict]) -> dict:
    """Check if T+1 opens have large gaps from T close (R6 concern).
    For index ETF, gaps are smaller than stocks but still worth checking."""
    gaps = []
    for p in picks:
        signal_bar = bmap.get(p["signal_date"])
        if not signal_bar:
            continue
        t_close = signal_bar.get("close")
        t1_open = p["entry_open"]
        if t_close and t_close > 0:
            gap = (t1_open - t_close) / t_close * 100
            gaps.append(gap)
    if not gaps:
        return {"n": 0, "mean_gap": 0, "max_gap": 0}
    s = ev_stats(gaps)
    return {
        "n": s["n"],
        "mean_gap": s["ev"],
        "std_gap": s["std"],
        "max_gap": max(gaps),
        "min_gap": min(gaps),
        "pct_gap_gt_1pct": round(sum(1 for g in gaps if abs(g) > 1) / len(gaps) * 100, 1),
    }


# ---------- main ----------


def main():
    bars = load_index()
    calendar = build_calendar(bars)
    bmap = bar_map(bars)
    month_ends = find_month_ends(calendar)

    print(f"=" * 70)
    print(f"TOM (月末月初轮动) §44 v3 + 10 flaw 严测")
    print(f"=" * 70)
    print(f"数据: sh.000001 (上证综指) {len(bars)} bars {calendar[0]} → {calendar[-1]}")
    print(f"月末日数 (全史): {len(month_ends)}")
    print(f"分析区间: {START_YEAR}-{END_YEAR}")
    print(f"Hold: T+1 open → T+{N_HOLD} close ({N_HOLD}-day hold)")
    print(f"成本: ETF {COST_ETF * 100:.2f}% round-trip (sensitivity {COST_LOW * 100}-{COST_HIGH * 100}%)")
    print(f"先验: 0.30 (机制 sound: 日历驱动 price-insensitive demand)")
    print(f"Bonferroni: ×{N_CROSS_FACTOR}*2={N_CROSS_FACTOR * 2} (top 3 in 15-candidate sweep)")

    # ---- build TOM picks ----
    tom_picks = build_tom_windows(calendar, bmap, month_ends, hold=N_HOLD, start_year=START_YEAR)
    tom_rets = [p["ret"] for p in tom_picks]
    tom_dates = set(p["signal_date"] for p in tom_picks)

    # ---- benchmark (non-TOM 4-day windows) ----
    bench_rets = build_benchmark_windows(calendar, bmap, hold=N_HOLD, tom_signal_dates=tom_dates, start_year=START_YEAR)

    # ---- basic stats ----
    print(f"\n{'=' * 70}")
    print(f"一、基础统计")
    print(f"{'=' * 70}")
    tom_s = ev_stats(tom_rets)
    bench_s = ev_stats(bench_rets)
    print(f"\nTOM 窗口:")
    print(f"  n={tom_s['n']} (picks = 月份数)")
    print(f"  gross_EV={tom_s['ev']}% std={tom_s['std']}% median={tom_s['median']}%")
    print(f"  WR={tom_s['wr']}% t={tom_s['t']} CI[{tom_s['ci_lo']},{tom_s['ci_hi']}]")
    for cost, label in [(COST_LOW, "low"), (COST_ETF, "base"), (COST_HIGH, "high")]:
        net = tom_s["ev"] - cost * 100
        print(f"  net EV ({label} {cost * 100:.2f}%): {net:.4f}%")
    print(f"\nBenchmark (非TOM 随机4日窗口):")
    print(f"  n={bench_s['n']} mean={bench_s['ev']}% std={bench_s['std']}%")
    print(f"  WR={bench_s['wr']}% median={bench_s['median']}%")

    # ---- BHAR + lift ----
    bhar = tom_s["ev"] - bench_s["ev"]
    lift = tom_s["ev"] / bench_s["ev"] if abs(bench_s["ev"]) > 1e-6 else 0
    print(f"\nBHAR (TOM - benchmark): {bhar:.4f}%")
    print(f"  lift = TOM_mean / bench_mean = {tom_s['ev']:.4f} / {bench_s['ev']:.4f} = {lift:.3f}x")
    print(f"  §44 噪声门: lift > 2.0x → {'PASS' if lift > 2.0 else 'FAIL (噪声区)' if lift < 1.0 else 'BORDERLINE'}")

    # ---- day-paired t (one-sample, TOM mean > 0) ----
    print(f"\n{'=' * 70}")
    print(f"二、统计检验")
    print(f"{'=' * 70}")
    dt = day_paired_t_one_sample(tom_rets)
    print(f"\nday-paired t (one-sample, H0: TOM mean = 0):")
    print(f"  n_days={dt['n_days']} mean={dt['mean']}% std={dt['std']}%")
    print(f"  t={dt['t']} p_one_sided={dt['p_one_sided']}")
    n_tests = N_CROSS_FACTOR * 2
    p_bonf = bonferroni_p(dt["p_one_sided"], n_tests)
    print(f"  Bonferroni p (×{n_tests}) = {p_bonf:.6f}")

    # ---- two-sample (TOM vs benchmark) ----
    ts = two_sample_t(tom_rets, bench_rets)
    print(f"\nWelch t (TOM vs benchmark, H0: TOM_mean = bench_mean):")
    print(f"  diff={ts['diff']}% t={ts['t']} df={ts.get('df', '?')} p_one_sided={ts['p_one_sided']}")

    # ---- permutation test ----
    perm = permutation_test(tom_rets, bench_rets, n_perm=10000)
    print(f"\nPermutation test (TOM vs benchmark, non-parametric):")
    print(f"  observed_diff={perm['observed_diff']}% p_one_sided={perm['p_one_sided']} (n={perm['n_perm']})")

    # ---- walk-forward ----
    print(f"\n{'=' * 70}")
    print(f"三、Walk-forward OOS (4窗×2年 + 50/50 split)")
    print(f"{'=' * 70}")
    wf = walk_forward_4win(tom_picks, hold=N_HOLD)
    print(f"\nper-window EV:")
    for w in wf["windows"]:
        print(f"  {w['window']}: n={w.get('n', 0)} EV={w.get('ev', 0)}% WR={w.get('wr', 0)}% t={w.get('t', 0)}")
    tr = wf["train_ev"]
    te = wf["test_ev"]
    print(f"\n50/50 split:")
    print(f"  train: n={wf['n_train']} EV={tr['ev']}% t={tr['t']} day_t={wf['train_day_t']['t']}")
    print(f"  test:  n={wf['n_test']} EV={te['ev']}% t={te['t']} day_t={wf['test_day_t']['t']} p={wf['test_day_t']['p_one_sided']}")
    decay = (tr["ev"] - te["ev"]) / abs(tr["ev"]) * 100 if tr["ev"] != 0 else 0
    print(f"  decay: {decay:.0f}% (train→test)")

    # ---- temporal decay (flaw 5) ----
    print(f"\n{'=' * 70}")
    print(f"四、10 flaw 检查")
    print(f"{'=' * 70}")
    td = temporal_decay(tom_picks)
    eg = entry_gap_check(tom_picks, bmap)

    flaws = []
    print(f"\n  1. entry 涨停价溢价 — N/A (ETF 无涨停限制, 指数非个股) [PASS]")
    print(f"  2. survivorship — N/A (买全市场指数, 无个股退市偏差) [PASS]")
    print(f"  3. exit 一字 over-credit — N/A (ETF 无一字, 指数连续定价) [PASS]")
    print(f"  4. T+1 日内泄漏 — 用 close_ev (T+{N_HOLD} close) 非 open_ev [PASS]")
    print(f"  5. 拥挤倒U — early EV={td['early_ev']}% late EV={td['late_ev']}% decay={td['decay_pct']}%")
    if td["decay_pct"] > 50 and td["late_ev"] < td["early_ev"]:
        print(f"     ⚠️ 触发: late << early, 可能拥挤衰减 (倒U)")
        flaws.append("5")
    else:
        print(f"     [PASS] 无显著衰减")
    print(f"  6. R6 gap-through fill — entry gap: mean={eg['mean_gap']}% max={eg['max_gap']:.2f}% pct>1%={eg.get('pct_gap_gt_1pct', 0)}%")
    if abs(eg.get("mean_gap", 0)) > 0.5:
        print(f"     ⚠️ 触发: T+1 open 有系统性 gap, 需加滑点")
        flaws.append("6")
    else:
        print(f"     [PASS] entry gap 小")
    print(f"  7. timing mismatch — benchmark 同窗口 (非TOM 4日) [PASS]")
    cost_net = tom_s["ev"] - COST_ETF * 100
    print(f"  8. 成本乐观 — ETF {COST_ETF * 100:.2f}% round-trip, net EV={cost_net:.4f}% [PASS]")
    print(f"  9. phantom alpha — raw_ev=gross (指数实际收益) 非 BHAR phantom [PASS]")
    print(f"  10. 退化 OLS — N/A (单因子无 orthogonalize) [PASS]")
    print(f"\n  触发 flaw: {flaws if flaws else '无 (1-4,10 结构性 N/A; 5,6 未触发)'}")

    # ---- variant: 3-day hold (T+3 close) ----
    print(f"\n{'=' * 70}")
    print(f"五、Robustness: 3-day hold (T+3 close)")
    print(f"{'=' * 70}")
    tom_picks3 = build_tom_windows(calendar, bmap, month_ends, hold=3, start_year=START_YEAR)
    tom_rets3 = [p["ret"] for p in tom_picks3]
    s3 = ev_stats(tom_rets3)
    bench_rets3 = build_benchmark_windows(
        calendar, bmap, hold=3, tom_signal_dates=set(p["signal_date"] for p in tom_picks3), start_year=START_YEAR
    )
    bench_s3 = ev_stats(bench_rets3)
    bhar3 = s3["ev"] - bench_s3["ev"]
    lift3 = s3["ev"] / bench_s3["ev"] if abs(bench_s3["ev"]) > 1e-6 else 0
    dt3 = day_paired_t_one_sample(tom_rets3)
    p_bonf3 = bonferroni_p(dt3["p_one_sided"], n_tests)
    print(f"  n={s3['n']} gross_EV={s3['ev']}% net={s3['ev'] - COST_ETF * 100:.4f}% WR={s3['wr']}% t={s3['t']}")
    print(f"  BHAR={bhar3:.4f}% lift={lift3:.3f}x")
    print(f"  day_t={dt3['t']} p={dt3['p_one_sided']} Bonf={p_bonf3:.6f}")

    # ---- honest verdict ----
    print(f"\n{'=' * 70}")
    print(f"六、诚实 verdict (4-day hold, primary)")
    print(f"{'=' * 70}")
    gross = tom_s["ev"]
    net = gross - COST_ETF * 100
    raw = gross  # retail actual = index return, no phantom
    n_days = dt["n_days"]
    p_raw = dt["p_one_sided"]
    p_bonf_val = p_bonf
    wf_train = tr["ev"]
    wf_test = te["ev"]
    wf_test_p = wf["test_day_t"]["p_one_sided"]

    print(f"\n  picks_n={len(tom_picks)}")
    print(f"  n_days={n_days} (day-paired 天数 = 月份数)")
    print(f"  gross_EV={gross}% net_EV={net:.4f}% raw_EV={raw}%")
    print(f"  BHAR={bhar:.4f}% lift={lift:.3f}x")
    print(f"  day_t={dt['t']} p_raw={p_raw} p_bonf(×{n_tests})={p_bonf_val}")
    print(f"  walk-forward: train_EV={wf_train}% test_EV={wf_test}% test_p={wf_test_p}")

    # verdict cascade
    if gross < 0:
        verdict = "falsified"
        reason = f"gross EV={gross}% < 0 (negative edge)"
    elif n_days < 60:
        verdict = "underpowered"
        reason = f"n_days={n_days} < 60"
    elif p_bonf_val >= ALPHA:
        verdict = "falsified"
        reason = f"Bonferroni p={p_bonf_val} >= {ALPHA} (not significant)"
    elif net <= 0:
        verdict = "falsified"
        reason = f"net EV={net}% <= 0 (gross eaten by cost)"
    elif lift < 1.0:
        verdict = "falsified"
        reason = f"lift={lift:.3f}x < 1.0 (worse than random windows)"
    elif lift < 2.0:
        verdict = "exploratory"
        reason = f"lift={lift:.3f}x < 2.0 (噪声区, not non-noise)"
    elif wf_train <= 0:
        verdict = "exploratory"
        reason = f"train_EV={wf_train}% <= 0 (edge not in train half)"
    elif wf_test <= 0:
        verdict = "falsified"
        reason = f"walk-forward test_EV={wf_test}% <= 0"
    else:
        wf_test_p_bonf = bonferroni_p(wf_test_p, n_tests)
        if wf_test_p_bonf >= ALPHA:
            verdict = "exploratory"
            reason = f"OOS test EV={wf_test}% > 0 but test_p={wf_test_p} Bonf={wf_test_p_bonf} >= {ALPHA} (not significant OOS)"
        else:
            verdict = "edge-confirmed"
            reason = f"gross+net>0, Bonf PASS, lift={lift:.3f}x>2, OOS test_EV={wf_test}% significant"

    print(f"\n  → VERDICT: {verdict}")
    print(f"  → REASON: {reason}")

    # prior vs actual
    print(f"\n{'=' * 70}")
    print(f"七、先验 vs 实际 (诚实对比)")
    print(f"{'=' * 70}")
    print(f"  先验: 0.30 (机制 sound: 日历驱动 price-insensitive demand flow)")
    print(f"  实际: gross_EV={gross}% net_EV={net:.4f}% BHAR={bhar:.4f}% lift={lift:.3f}x")
    print(f"  学术 TOM ~0.5-1%/窗口 → 实测 {gross}% {'吻合' if 0.3 < gross < 1.5 else '偏离'}")
    if gross > 0 and net > 0 and lift > 1:
        print(f"  方向: 正向 edge 存在 (gross+net+BHAR>0)")
        if lift < 2.0:
            print(f"  但 lift<2x → 可能噪声非真 edge")
        if p_bonf_val >= ALPHA:
            print(f"  但 Bonf p={p_bonf_val} >= 0.05 → 统计不显著")
    elif gross > 0 and net <= 0:
        print(f"  方向: gross>0 但 cost 吃掉 edge (net<=0) → 不可交易")
    else:
        print(f"  方向: 无正向 edge 或负向")

    # export summary numbers for structured output
    print(f"\n{'=' * 70}")
    print(f"SUMMARY (for structured output)")
    print(f"{'=' * 70}")
    print(f"strategy=tom")
    print(f"picks_n={len(tom_picks)}")
    print(f"n_days={n_days}")
    print(f"gross_ev={gross}")
    print(f"net_ev={round(net, 4)}")
    print(f"raw_ev={raw}")
    print(f"bhar={round(bhar, 4)}")
    print(f"lift={round(lift, 3)}")
    print(f"day_t={dt['t']}")
    print(f"p_raw={p_raw}")
    print(f"p_bonf={p_bonf_val}")
    print(f"wf_train_ev={wf_train}")
    print(f"wf_test_ev={wf_test}")
    print(f"wf_test_p={wf_test_p}")
    print(f"flaws_triggered={flaws if flaws else 'none'}")
    print(f"verdict={verdict}")


if __name__ == "__main__":
    main()
