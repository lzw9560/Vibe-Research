# -*- coding: utf-8 -*-
"""explore_rotation_factor-return.py

方法论改变：从 long-only 绝对 EV（跟市场 beta 混淆）→ **alpha-isolated**
cross-sectional 行业动量因子（Fama-French 风格）。

核心思路（factor-return 法）：
  每个再平衡日，按行业过去 N 周动量排序，做多 top-K + 做空 bottom-K 构建
  **零投资 dollar-neutral 组合**。因子收益 = 多头收益 - 空头收益（市场 beta
  在多空对冲中抵消 → 剩余即 alpha）。时间序列 t 检验因子收益序列。

为什么 alpha 被隔离：
  - long-short dollar-neutral → 市场系统性 beta 在多头腿与空头腿近似抵消
  - 因子收益 = cross-sectional spread，不含市场方向
  - 隔离审计：回归因子收益于市场基准，beta 应 ≈ 0；若 beta≠0 则 alpha 被
    残留 beta 污染（诚实标注）

学术标准方法测因子 alpha（Jegadeesh-Titman / Fama-French 行业动量）。

数据：.vibe-research/sector_rotation_data.json
  - sector_returns: {industry: [daily decimal or None]} (close-to-close, equal-weight)
  - benchmark: sh.000001 上证指数 daily returns (decimal)
  - 干净窗口: 2018-01-03 .. 2026-09-18 (drop degenerate tail 09-21/22/23, only 21 codes)
  - universe: median membership >= 10 over window (27 industries, well-covered core)

过严口径（保留）：
  - 非重叠 holding block（独立观察，t 有效）
  - signal 用 [s-N*5, s-1]（信号截止 holding 前一日），holding [s, s+H-1]
    → 信号与持有不重叠，无 look-ahead
  - 行业组合 close-to-close（FF 学术标准；T+1 open 在行业聚合层无意义）
  - per-rebalance-block t（n = n_rebalances，非 per-day——同 block 日内相关）
  - Bonferroni ×4（4 方法并行）× 3（formation 2/3/4 周搜索）= ×12
  - walk-forward OOS + train_ev>0（前半 train → 后半 test）
  - 估计换手率→交易成本扣减（net alpha）
  - 隔离审计：回归 LS 因子收益于基准 block 收益，验 beta≈0
  - 散户可行性：long-short 需融券（A 股散户难）；附 long-only Jensen alpha 交叉验证

禁止：
  - 禁止 long-only 绝对 EV 作主 verdict（必须 alpha-isolated）
  - 禁止 trust 未验证数字
  - 禁止外推（行业轮动因子 ≠ 轮动有/无 edge ≠ 短线有/无 edge）
"""
from __future__ import annotations
import json
import math
import sys
from pathlib import Path
from statistics import mean, pstdev

# DRY: 复用 _factor_helpers 的统计/校正函数
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import bonferroni_p, norm_sf_positive  # noqa: E402

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
SRC = DATA / "sector_rotation_data.json"

# ---------- 参数 ----------
WINDOW_START = "2018-01-01"
WINDOW_END = "2026-09-19"          # through 2026-09-18 (drop degenerate tail)
MIN_MEDIAN_MEMBERSHIP = 10         # universe floor
K_LONG_SHORT = 5                   # top-5 / bottom-5 industries (decile-ish tail)
HOLDING_WEEKS = 2                  # 2-week holding (10 trading days)
FORMATION_WEEKS_LIST = [2, 3, 4]   # search formation N (Bonferroni ×3 within-method)
TRADING_DAYS_PER_WEEK = 5
ROUND_TRIP_COST = 0.003            # 0.3% per round-trip (matches helpers COST)
N_METHODS_PARALLEL = 4             # cross-method Bonferroni ×4
ALPHA_LEVEL = 0.05


# ---------- 数据加载 ----------
def load_data() -> dict:
    d = json.load(open(SRC))
    dates: list[str] = d["dates"]
    bench: list[float | None] = d["benchmark"]["returns"]
    sr: dict[str, list[float | None]] = d["sector_returns"]
    sm: dict[str, list[int]] = d["sector_membership"]
    import bisect
    i_start = bisect.bisect_left(dates, WINDOW_START)
    i_end = bisect.bisect_left(dates, WINDOW_END)
    return {
        "dates": dates[i_start:i_end],
        "bench": bench[i_start:i_end],
        "sector_returns": {ind: sr[ind][i_start:i_end]
                           for ind in sr},
        "sector_membership": {ind: sm[ind][i_start:i_end]
                              for ind in sm},
        "i_start": i_start,
    }


def select_universe(data: dict) -> list[str]:
    """industries with median membership >= floor over clean window."""
    sm = data["sector_membership"]
    out = []
    for ind, memb in sm.items():
        med = sorted(memb)[len(memb) // 2]
        if med >= MIN_MEDIAN_MEMBERSHIP:
            out.append(ind)
    return sorted(out)


# ---------- 因子构建 ----------
def compound_window(rets: list[float | None], lo: int, hi: int) -> float | None:
    """compound return over rets[lo..hi] inclusive; None if any null in window."""
    acc = 1.0
    for i in range(lo, hi + 1):
        r = rets[i]
        if r is None:
            return None
        acc *= (1.0 + r)
    return acc - 1.0


def build_factor_blocks(
    data: dict,
    universe: list[str],
    formation_weeks: int,
    holding_weeks: int = HOLDING_WEEKS,
    k: int = K_LONG_SHORT,
) -> dict:
    """构建非重叠 holding block 的因子收益序列。

    Block b (b=0,1,...):
      signal window  = [b*H, b*H + N*5 - 1]      (N weeks, ends before holding)
      holding window = [b*H + N*5, b*H + N*5 + H - 1]  (H days, non-overlapping)
    信号截止于 holding 前一日 → 无 look-ahead。
    """
    dates = data["dates"]
    bench = data["bench"]
    sr = data["sector_returns"]
    N = formation_weeks * TRADING_DAYS_PER_WEEK
    H = holding_weeks * TRADING_DAYS_PER_WEEK
    n_days = len(dates)

    block_factor: list[float] = []          # decimal
    block_bench: list[float] = []           # decimal, aligned for CAPM audit
    block_dates: list[tuple[str, str]] = [] # (hold_start_date, hold_end_date)
    long_sets: list[list[str]] = []
    short_sets: list[list[str]] = []
    daily_ls_all: list[float | None] = []   # per-day LS return (for diagnostics)

    b = 0
    while True:
        sig_lo = b * H
        sig_hi = b * H + N - 1
        hold_lo = b * H + N
        hold_hi = hold_lo + H - 1
        if hold_hi >= n_days:
            break
        # momentum per sector (skip sectors with null in signal window)
        moma: list[tuple[str, float]] = []
        for ind in universe:
            m = compound_window(sr[ind], sig_lo, sig_hi)
            if m is not None:
                moma.append((ind, m))
        if len(moma) < 2 * k:
            b += 1
            continue
        moma.sort(key=lambda x: x[1])
        shorts = [x[0] for x in moma[:k]]
        longs = [x[0] for x in moma[-k:]]
        # holding: daily LS return over [hold_lo, hold_hi]
        block_daily_ls: list[float] = []
        block_bench_comp = 1.0
        bench_ok = True
        for d in range(hold_lo, hold_hi + 1):
            top_rs = [sr[lg][d] for lg in longs if sr[lg][d] is not None]
            bot_rs = [sr[sh][d] for sh in shorts if sr[sh][d] is not None]
            top_mean = mean(top_rs) if top_rs else 0.0
            bot_mean = mean(bot_rs) if bot_rs else 0.0
            dls = top_mean - bot_mean
            block_daily_ls.append(dls)
            br = bench[d]
            if br is None:
                bench_ok = False
            else:
                block_bench_comp *= (1.0 + br)
        # compound daily LS -> block factor return
        acc = 1.0
        for x in block_daily_ls:
            acc *= (1.0 + x)
        block_factor.append(acc - 1.0)
        block_bench.append((block_bench_comp - 1.0) if bench_ok else None)
        block_dates.append((dates[hold_lo], dates[hold_hi]))
        long_sets.append(longs)
        short_sets.append(shorts)
        daily_ls_all.extend(block_daily_ls)
        b += 1

    return {
        "formation_weeks": formation_weeks,
        "holding_weeks": holding_weeks,
        "n_rebalances": len(block_factor),
        "block_factor": block_factor,        # decimal
        "block_bench": block_bench,
        "block_dates": block_dates,
        "long_sets": long_sets,
        "short_sets": short_sets,
    }


# ---------- 统计 ----------
def block_stats(block_returns: list[float]) -> dict:
    """t-test on non-overlapping block factor returns (n = n_blocks).
    Uses SAMPLE std (n-1) for t. Returns percent + t + p."""
    n = len(block_returns)
    if n == 0:
        return {"n": 0, "mean_pct": 0.0, "std_pct": 0.0, "se_pct": 0.0,
                "t": 0.0, "p_one_sided": 1.0, "wr_pct": 0.0}
    m = sum(block_returns) / n
    # sample std (n-1)
    if n > 1:
        var = sum((x - m) ** 2 for x in block_returns) / (n - 1)
        sd = math.sqrt(var)
    else:
        sd = 0.0
    se = sd / math.sqrt(n) if n > 0 else 0.0
    t = m / se if se > 0 else 0.0
    p = norm_sf_positive(t)
    wr = sum(1 for x in block_returns if x > 0) / n
    return {
        "n": n,
        "mean_pct": round(m * 100, 4),
        "std_pct": round(sd * 100, 4),
        "se_pct": round(se * 100, 4),
        "t": round(t, 3),
        "p_one_sided": round(p, 6),
        "wr_pct": round(wr * 100, 1),
    }


def estimate_turnover(long_sets: list[list[str]],
                      short_sets: list[list[str]], k: int) -> float:
    """平均换手率：相邻 block 间多头/空头集合变更名字比例 (0~1 per leg)."""
    if len(long_sets) < 2:
        return 0.0
    chg = []
    for i in range(1, len(long_sets)):
        prev_l = set(long_sets[i - 1])
        cur_l = set(long_sets[i])
        prev_s = set(short_sets[i - 1])
        cur_s = set(short_sets[i])
        dl = (k - len(prev_l & cur_l)) / k
        ds = (k - len(prev_s & cur_s)) / k
        chg.append((dl + ds) / 2.0)
    return mean(chg)


def ols_regression(y: list[float], x: list[float]) -> dict:
    """OLS y = a + b*x. Returns alpha, beta, beta_t, alpha_t, r2.
    y = factor block returns, x = benchmark block returns."""
    n = len(y)
    if n < 3:
        return {"alpha": 0.0, "beta": 0.0, "alpha_t": 0.0, "beta_t": 0.0, "r2": 0.0}
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((xi - mx) ** 2 for xi in x)
    sxy = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    beta = sxy / sxx if sxx > 0 else 0.0
    alpha = my - beta * mx
    # residuals
    resid = [y[i] - (alpha + beta * x[i]) for i in range(n)]
    if n > 2:
        sse = sum(r * r for r in resid)
        s2 = sse / (n - 2)
    else:
        s2 = 0.0
    se_beta = math.sqrt(s2 / sxx) if sxx > 0 and s2 > 0 else 0.0
    # se_alpha = sqrt(s2 * (1/n + mx^2/sxx))
    se_alpha = math.sqrt(s2 * (1.0 / n + mx * mx / sxx)) if s2 > 0 else 0.0
    beta_t = beta / se_beta if se_beta > 0 else 0.0
    alpha_t = alpha / se_alpha if se_alpha > 0 else 0.0
    syy = sum((yi - my) ** 2 for yi in y)
    r2 = 1 - sse / syy if syy > 0 else 0.0
    return {
        "alpha_pct": round(alpha * 100, 4),
        "beta": round(beta, 4),
        "alpha_t": round(alpha_t, 3),
        "beta_t": round(beta_t, 3),
        "r2": round(r2, 4),
    }


def walk_forward_blocks(block_returns: list[float],
                        block_dates: list[tuple[str, str]]) -> dict:
    """前半 train → 后半 test. 非重叠 block 已按时间排序."""
    n = len(block_returns)
    if n < 8:
        return {"status": "too_few", "n": n}
    mid = n // 2
    train = block_returns[:mid]
    test = block_returns[mid:]
    return {
        "status": "ok",
        "n_train": len(train),
        "n_test": len(test),
        "train_dates": (block_dates[0][0], block_dates[mid - 1][1]),
        "test_dates": (block_dates[mid][0], block_dates[-1][1]),
        "train": block_stats(train),
        "test": block_stats(test),
    }


# ---------- verdict (factor-return 专用) ----------
def verdict_for_factor(
    formation_weeks: int,
    gross_mean_pct: float,
    net_mean_pct: float,
    t_stat: float,
    p_raw: float,
    n_blocks: int,
    bonf_p: float,
    wf: dict,
    iso_beta: float,
) -> str:
    print(f"\n  [formation={formation_weeks}w] "
          f"gross={gross_mean_pct}% net={net_mean_pct}% t={t_stat} "
          f"p={p_raw} Bonf(×{N_METHODS_PARALLEL * len(FORMATION_WEEKS_LIST)})"
          f"={bonf_p} n_blocks={n_blocks}")
    print(f"    isolation audit: LS-benchmark beta={iso_beta} "
          f"({'CLEAN' if abs(iso_beta) < 0.20 else 'CONTAMINATED'})")
    if wf["status"] == "ok":
        tr = wf["train"]
        te = wf["test"]
        print(f"    walk-forward: train mean={tr['mean_pct']}% (t={tr['t']}) "
              f"| test mean={te['mean_pct']}% (t={te['t']} p={te['p_one_sided']})")

    if gross_mean_pct <= 0:
        print("    -> FALSIFIED: gross factor mean <= 0 (no positive alpha)")
        return "falsified"
    if n_blocks < 60:
        print(f"    -> UNDERPOWERED: n_blocks={n_blocks} < 60")
        return "underpowered"
    if bonf_p >= ALPHA_LEVEL:
        print(f"    -> FALSIFIED: Bonferroni p={bonf_p} >= {ALPHA_LEVEL} "
              f"(not significant after ×{N_METHODS_PARALLEL * len(FORMATION_WEEKS_LIST)} correction)")
        return "falsified"
    if net_mean_pct <= 0:
        print(f"    -> FALSIFIED: net factor mean={net_mean_pct}% <= 0 "
              f"(alpha eaten by transaction cost)")
        return "falsified"
    if wf["status"] == "ok":
        if wf["train"]["mean_pct"] <= 0:
            print(f"    -> EXPLORATORY: train mean={wf['train']['mean_pct']}% <= 0 "
                  f"(alpha absent in train half — test may be regime overfit)")
            return "exploratory"
        if wf["test"]["mean_pct"] <= 0:
            print(f"    -> FALSIFIED: walk-forward test mean={wf['test']['mean_pct']}% <= 0")
            return "falsified"
        wf_test_bonf = bonferroni_p(wf["test"]["p_one_sided"],
                                     N_METHODS_PARALLEL * len(FORMATION_WEEKS_LIST))
        if wf_test_bonf >= ALPHA_LEVEL:
            print(f"    -> EXPLORATORY: OOS test mean={wf['test']['mean_pct']}% > 0 but "
                  f"test p={wf['test']['p_one_sided']} Bonf={wf_test_bonf} >= {ALPHA_LEVEL}")
            return "exploratory"
        print(f"    -> EDGE-CONFIRMED: gross+net alpha > 0, Bonferroni PASS, "
              f"OOS test mean={wf['test']['mean_pct']}% significant")
        return "edge-confirmed"
    print("    -> EXPLORATORY: walk-forward unavailable")
    return "exploratory"


# ---------- 主流程 ----------
def run_one_formation(data: dict, universe: list[str],
                      fw: int) -> dict:
    fb = build_factor_blocks(data, universe, fw)
    bs = block_stats(fb["block_factor"])
    turnover = estimate_turnover(fb["long_sets"], fb["short_sets"], K_LONG_SHORT)
    cost_per_block = turnover * 2 * ROUND_TRIP_COST   # both legs
    gross_mean_pct = bs["mean_pct"]
    net_mean_pct = round(gross_mean_pct - cost_per_block * 100, 4)
    n_tests = N_METHODS_PARALLEL * len(FORMATION_WEEKS_LIST)
    bonf_p = bonferroni_p(bs["p_one_sided"], n_tests)
    bonf_p_methodonly = bonferroni_p(bs["p_one_sided"], N_METHODS_PARALLEL)

    # isolation audit: regress LS factor on benchmark block returns
    paired = [(f, b) for f, b in zip(fb["block_factor"], fb["block_bench"])
              if b is not None]
    iso = (ols_regression([p[0] for p in paired], [p[1] for p in paired])
           if len(paired) >= 5 else {"alpha_pct": 0, "beta": 0, "alpha_t": 0,
                                     "beta_t": 0, "r2": 0})

    # long-only Jensen alpha (散户可行性交叉验证: top-K only regressed on benchmark)
    # long-only block return = mean(top-K daily) compounded
    long_block = []
    for bi, longs in enumerate(fb["long_sets"]):
        # recompute long-only block return from daily (already have block_factor as LS)
        # approximate long-only = factor + short leg; recompute precisely:
        pass
    # recompute long-only and short-only block returns for diagnostics
    sr = data["sector_returns"]
    H = HOLDING_WEEKS * TRADING_DAYS_PER_WEEK
    N = fw * TRADING_DAYS_PER_WEEK
    n_days = len(data["dates"])
    long_only_blocks: list[float] = []
    short_only_blocks: list[float] = []
    b = 0
    while True:
        hold_lo = b * H + N
        hold_hi = hold_lo + H - 1
        if hold_hi >= n_days:
            break
        if b >= len(fb["long_sets"]):
            break
        longs = fb["long_sets"][b]
        shorts = fb["short_sets"][b]
        acc_l = 1.0
        acc_s = 1.0
        for d in range(hold_lo, hold_hi + 1):
            tl = [sr[lg][d] for lg in longs if sr[lg][d] is not None]
            ts = [sr[sh][d] for sh in shorts if sr[sh][d] is not None]
            if tl:
                acc_l *= (1 + mean(tl))
            if ts:
                acc_s *= (1 + mean(ts))
        long_only_blocks.append(acc_l - 1.0)
        short_only_blocks.append(acc_s - 1.0)
        b += 1
    long_bench = [bb for bb in fb["block_bench"] if bb is not None]
    jensen = (ols_regression(long_only_blocks[:len(long_bench)], long_bench)
              if len(long_bench) >= 5 else {"alpha_pct": 0, "beta": 0,
                                            "alpha_t": 0, "beta_t": 0, "r2": 0})

    wf = walk_forward_blocks(fb["block_factor"], fb["block_dates"])
    sharpe = (bs["mean_pct"] / bs["std_pct"] * math.sqrt(26)
              if bs["std_pct"] > 0 else 0.0)

    vd = verdict_for_factor(fw, gross_mean_pct, net_mean_pct,
                            bs["t"], bs["p_one_sided"],
                            bs["n"], bonf_p, wf, iso["beta"])
    return {
        "formation_weeks": fw,
        "n_rebalances": bs["n"],
        "gross_alpha_pct": gross_mean_pct,
        "net_alpha_pct": net_mean_pct,
        "cost_per_block_pct": round(cost_per_block * 100, 4),
        "turnover": round(turnover, 3),
        "t": bs["t"],
        "p_one_sided": bs["p_one_sided"],
        "bonf_p_x12": bonf_p,
        "bonf_p_x4": bonf_p_methodonly,
        "wr_pct": bs["wr_pct"],
        "std_pct": bs["std_pct"],
        "sharpe_annualized": round(sharpe, 3),
        "isolation_beta": iso["beta"],
        "isolation_alpha_pct": iso["alpha_pct"],
        "isolation_alpha_t": iso["alpha_t"],
        "isolation_r2": iso["r2"],
        "jensen_long_alpha_pct": jensen["alpha_pct"],
        "jensen_long_beta": jensen["beta"],
        "jensen_long_alpha_t": jensen["alpha_t"],
        "long_only_mean_pct": round(mean(long_only_blocks) * 100, 4)
                               if long_only_blocks else 0.0,
        "benchmark_mean_pct": round(mean(long_bench) * 100, 4)
                              if long_bench else 0.0,
        "walk_forward": wf,
        "verdict": vd,
        "block_factor_pct": [round(x * 100, 3) for x in fb["block_factor"]],
    }


def main() -> None:
    print("=" * 74)
    print("行业轮动 factor-return (cross-sectional 动量因子, Fama-French 风格)")
    print("alpha-isolated: long top-K / short bottom-K, dollar-neutral")
    print("=" * 74)
    data = load_data()
    universe = select_universe(data)
    dates = data["dates"]
    bench = [x for x in data["bench"] if x is not None]
    print(f"window: {dates[0]} .. {dates[-1]} ({len(dates)} days)")
    print(f"universe: {len(universe)} industries (median membership >= {MIN_MEDIAN_MEMBERSHIP})")
    print(f"benchmark: 上证指数 mean daily = {mean(bench)*100:.4f}% "
          f"-> annualized ~{(1+mean(bench))**250-1:.1%}")
    print(f"K (long/short): {K_LONG_SHORT} each "
          f"({K_LONG_SHORT/len(universe)*100:.0f}% tail)")
    print(f"holding: {HOLDING_WEEKS}w ({HOLDING_WEEKS*5}d non-overlapping blocks)")
    print(f"formation search: {FORMATION_WEEKS_LIST} weeks "
          f"(Bonferroni ×{N_METHODS_PARALLEL} methods ×{len(FORMATION_WEEKS_LIST)} formations "
          f"= ×{N_METHODS_PARALLEL*len(FORMATION_WEEKS_LIST)})")

    results = []
    for fw in FORMATION_WEEKS_LIST:
        print(f"\n{'#' * 74}\n# formation = {fw} weeks ({fw*5}d signal window)\n{'#' * 74}")
        r = run_one_formation(data, universe, fw)
        results.append(r)

    # summary table
    print(f"\n\n{'=' * 74}\nSUMMARY (factor-return, alpha-isolated)\n{'=' * 74}")
    print(f"{'form':>5} {'n':>5} {'gross%':>8} {'net%':>8} {'t':>7} "
          f"{'p':>9} {'Bonf×12':>9} {'Sharpe':>7} {'isoβ':>6} {'verdict':>14}")
    best = None
    for r in results:
        print(f"{r['formation_weeks']:>4}w {r['n_rebalances']:>5} "
              f"{r['gross_alpha_pct']:>8.3f} {r['net_alpha_pct']:>8.3f} "
              f"{r['t']:>7.2f} {r['p_one_sided']:>9.5f} {r['bonf_p_x12']:>9.5f} "
              f"{r['sharpe_annualized']:>7.2f} {r['isolation_beta']:>6.3f} "
              f"{r['verdict']:>14}")
        # pick best by gross alpha (the search winner)
        if best is None or r["gross_alpha_pct"] > best["gross_alpha_pct"]:
            best = r

    print(f"\n--- best (search winner, by gross alpha) ---")
    b = best
    print(f"  formation={b['formation_weeks']}w  n_rebalances={b['n_rebalances']}")
    print(f"  gross factor alpha = {b['gross_alpha_pct']}% per 2-week block")
    print(f"  net factor alpha   = {b['net_alpha_pct']}% (after est. cost "
          f"{b['cost_per_block_pct']}%/block, turnover {b['turnover']})")
    print(f"  t={b['t']}  p_one_sided={b['p_one_sided']}  "
          f"Bonf×12={b['bonf_p_x12']}  Bonf×4={b['bonf_p_x4']}")
    print(f"  annualized Sharpe={b['sharpe_annualized']}  win_rate={b['wr_pct']}%")
    print(f"  isolation audit: reg(LS,benchmark) beta={b['isolation_beta']} "
          f"alpha={b['isolation_alpha_pct']}% alpha_t={b['isolation_alpha_t']} "
          f"r2={b['isolation_r2']}")
    print(f"  long-only Jensen: alpha={b['jensen_long_alpha_pct']}% "
          f"beta={b['jensen_long_beta']} alpha_t={b['jensen_long_alpha_t']} "
          f"(散户可行性: long-only 可交易, long-short 需融券)")
    print(f"  long-only mean={b['long_only_mean_pct']}% vs benchmark={b['benchmark_mean_pct']}% per block")
    if b["walk_forward"]["status"] == "ok":
        wf = b["walk_forward"]
        print(f"  walk-forward: train({wf['train_dates']}) mean={wf['train']['mean_pct']}% t={wf['train']['t']}")
        print(f"                test ({wf['test_dates']})  mean={wf['test']['mean_pct']}% t={wf['test']['t']} p={wf['test']['p_one_sided']}")
    print(f"  VERDICT: {b['verdict']}")

    # 散户可行性 + 诚实总结
    print(f"\n--- 诚实总结 ---")
    print(f"  方法: factor-return (cross-sectional 动量因子, alpha-isolated via long-short)")
    print(f"  alpha 是否从 beta 隔离: ", end="")
    if abs(b["isolation_beta"]) < 0.20:
        print(f"是 — LS-benchmark beta={b['isolation_beta']} (|β|<0.20), "
              f"市场 beta 在多空对冲中抵消, 因子收益是纯 cross-sectional alpha")
    else:
        print(f"否/部分 — LS-benchmark beta={b['isolation_beta']} (|β|>=0.20), "
              f"alpha 含残留市场 beta, 隔离不彻底")
    print(f"  散户可行性: long-short 需融券做空行业 (A 股散户融券难/成本高); "
          f"long-only top-K 可交易但 Jensen alpha={b['jensen_long_alpha_pct']}% "
          f"(t={b['jensen_long_alpha_t']}) {'含市场 beta 非纯 alpha' if b['jensen_long_beta']>0.5 else ''}")
    print(f"  禁止外推: 行业轮动 factor-return ≠ 轮动整体有/无 edge ≠ 短线有/无 edge. "
          f"仅测了 3 个 formation (2/3/4w) × 1 holding (2w) × K=5 × 27 industries × "
          f"2018-2026 窗口.")

    # dump JSON for record
    out = {
        "method": "factor-return",
        "universe_n": len(universe),
        "window": [dates[0], dates[-1]],
        "k": K_LONG_SHORT,
        "holding_weeks": HOLDING_WEEKS,
        "formation_weeks_searched": FORMATION_WEEKS_LIST,
        "bonferroni_multiplier": N_METHODS_PARALLEL * len(FORMATION_WEEKS_LIST),
        "results": results,
        "best_formation_weeks": best["formation_weeks"],
        "best_verdict": best["verdict"],
    }
    OUT = Path(__file__).resolve().parent / "_rotation_factor_return_result.json"
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n  result JSON: {OUT}")


if __name__ == "__main__":
    main()
