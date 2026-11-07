# -*- coding: utf-8 -*-
"""Alpha-isolated 行业轮动回测 — long-short（市场中性）方法。

方法论背景
==========
原 long-only 绝对 EV 把 alpha 跟市场 beta 混淆——策略 EV>0 可能只是大盘涨。
本脚本换 alpha-isolated 口径：long-short 市场中性组合，beta 由多空对冲抵消，
残余收益即纯 timing/selection alpha。

策略
====
- Universe: 2018-2025 窗口内 >=5 只股票覆盖 >=90% 交易日的行业（56 个 long-core
  行业，稳定 panel，避免两波 cache 的 membership regime shift）。
- Formation: 过去 N 周累积收益动量排序（N=2/3/4 周 = 10/15/20 交易日），多 top-3
  + 空 bottom-3，等权。
- Rebalance: 每 2 周（H=10 交易日）。
- Realistic T+1: 信号在 S_k 收盘已知，仓位在 S_k+1 收盘建立（不能在 S_k 收盘信号
  后立即交易），首个实现收益日 = S_k+2。holding block = [S_k+2, S_{k+1}+1]。
- alpha = long-short 组合日均收益（decimal），per-rebalance-block 聚 day-mean 后
  做 t（effective N = n_rebalances，避免块内日相关夸大 N）。

过严口径（保留）
================
- per-rebalance-block t（同再平衡日聚 day-mean，非 per-day t）
- Bonferroni ×4（4 方法并行 long-short/active/factor/capm）×3（formation 搜索）= ×12
- walk-forward OOS（块按时间前半 train / 后半 test）+ train_ev>0
- 禁止外推：行业轮动 long-short ≠ 轮动有/无 edge ≠ 短线有/无 edge

诚实审计（alpha 是否真从 beta 隔离）
====================================
- OLS 回归 L-S 日收益于上证基准：beta 应 ~0（多空抵消）。若 beta 显著≠0 说明
  短腿没完全对冲市场，alpha 仍掺 beta——这是 long-short 抵消审。
- 净 alpha：扣 A 股 long-short 真实成本（佣金+印花+融券费），审散户可行性。

DRY: import tools._factor_helpers（ev_stats / day_paired_t / bonferroni_p）。
walk_forward 是 pick 级（单股），组合块级 OOS 自写（同逻辑：时间分半）。
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _factor_helpers as H  # noqa: E402  (ev_stats / day_paired_t / bonferroni_p / ALPHA)

# ---------- config ----------
# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

ROOT = Path(__file__).resolve().parents[2]
DATA_JSON = resolve_data_dir() / "sector_rotation_data.json"

WINDOW_END = "2025-12-31"  # 截到 2025 末（避 2026 degenerate tail + recent wave）
MIN_STOCKS = 5  # 行业当日 >=5 只才纳入
MIN_COVER_FRAC = 0.90  # 行业在窗口内 >=90% 交易日达标才进 universe
HOLD_DAYS = 10  # 2 周再平衡
TOP_K = 3  # 多 top-3 / 空 bottom-3
FORMATION_WEEKS = [2, 3, 4]  # 搜索 2/3/4 周
N_METHODS_PARALLEL = 4  # long-short / active / factor / capm
BONF_METHODS = N_METHODS_PARALLEL  # ×4 跨方法
BONF_FORMATION = len(FORMATION_WEEKS)  # ×3 formation 搜索
BONF_TOTAL = BONF_METHODS * BONF_FORMATION  # ×12 全搜索空间
MIN_BLOCK_DAYS = HOLD_DAYS // 2  # 块 >=5 天才保留（避免碎片）

# A 股 long-short 真实成本（每再平衡 round-trip，占组合名义）
#   long 腿: 佣金 0.05% (buy+sell) + 印花 0.1% (sell) = 0.15% × 0.5 权重 = 0.075%
#   short 腿: 佣金 0.05% + 印花 0.1% (开空=sell) + 融券费 ~5%年化×10/250=0.2% = 0.35% × 0.5 = 0.175%
#   合计 ≈ 0.25%/rebalance → 日拖累 0.025%/day
COST_PER_REBALANCE = 0.0025  # 0.25% 组合名义
TRADING_DAYS_YR = 252


# ---------- data ----------


def load_panel() -> tuple[list[str], list[str], np.ndarray, np.ndarray, np.ndarray, dict]:
    """返回 (dates, industries, R[T×I], bench[T], meta). R 为 decimal 日收益，null→0."""
    raw = json.load(open(DATA_JSON))
    all_dates: list[str] = raw["dates"]
    lo = next(i for i, d in enumerate(all_dates) if d >= "2018-01-01")
    hi = next(i for i, d in enumerate(all_dates) if d > WINDOW_END)  # exclusive
    dates = all_dates[lo:hi]
    T = len(dates)
    bench_full = raw["benchmark"]["returns"]
    bench = np.array([0.0 if bench_full[lo + i] is None else bench_full[lo + i] for i in range(T)], dtype=float)
    memb = raw["sector_membership"]
    rets = raw["sector_returns"]
    # 选 universe：窗口内 >=MIN_STOCKS 占 >=MIN_COVER_FRAC 的行业
    inds: list[str] = []
    for ind, m in memb.items():
        sub = m[lo:hi]
        frac = sum(1 for x in sub if x >= MIN_STOCKS) / T
        if frac >= MIN_COVER_FRAC:
            inds.append(ind)
    inds.sort()
    I = len(inds)
    R = np.zeros((T, I), dtype=float)
    valid = np.zeros((T, I), dtype=bool)
    for j, ind in enumerate(inds):
        sr = rets[ind][lo:hi]
        for t in range(T):
            v = sr[t]
            if v is not None:
                R[t, j] = v
                valid[t, j] = True
    meta = {
        "window": [dates[0], dates[-1]],
        "n_days": T,
        "n_industries": I,
        "industries": inds,
        "benchmark_mean_daily_pct": float(bench.mean() * 100),
        "benchmark_annualized_pct": float((np.prod(1 + bench) - 1) * 100),
    }
    return dates, inds, R, valid, bench, meta


# ---------- momentum + portfolio ----------


def momentum_at(R: np.ndarray, valid: np.ndarray, t: int, lookback: int) -> np.ndarray:
    """各行业在 day t 的过去 lookback 日累积收益（product(1+r)-1）。
    缺测日按 0（持有）补；有效日 < 80% lookback → 返回 NaN（该行业该日不参与排序）。"""
    s = max(0, t - lookback + 1)
    seg = R[s : t + 1, :]  # (lookback, I)
    vseg = valid[s : t + 1, :]
    prod = np.ones(R.shape[1])
    frac_valid = vseg.mean(axis=0)
    prod = np.prod(seg + 1.0, axis=0) - 1.0
    prod[frac_valid < 0.80] = np.nan
    return prod


def run_long_short(R: np.ndarray, valid: np.ndarray, dates: list[str], formation_weeks: int) -> dict:
    """跑一个 formation 配置的 long-short 轮动，返回块级 + 日级结果。"""
    lookback = formation_weeks * 5
    T, I = R.shape
    H = HOLD_DAYS
    # 信号日：从 lookback 起，每 H 天一个，留足 holding（最后块至少 MIN_BLOCK_DAYS）
    signal_idx = list(range(lookback, T - 2, H))
    blocks: list[dict] = []
    daily_ls = np.full(T, np.nan)
    daily_long = np.full(T, np.nan)
    daily_short = np.full(T, np.nan)
    for k, s in enumerate(signal_idx):
        mom = momentum_at(R, valid, s, lookback)
        if np.isnan(mom).all():
            continue
        order = np.argsort(mom)  # NaN 排末尾
        # 取非 NaN 的 top/bottom K
        finite = [o for o in order if not np.isnan(mom[o])]
        if len(finite) < 2 * TOP_K + 2:
            continue
        long_idx = finite[-TOP_K:]  # 动量最高 → 多
        short_idx = finite[:TOP_K]  # 动量最低 → 空
        # holding 区间：[s+2, 下一信号+1] 或末块 [s+2, T-1]
        start = s + 2
        end = (signal_idx[k + 1] + 1) if k + 1 < len(signal_idx) else T - 1
        if end < start:
            continue
        days = list(range(start, end + 1))
        if len(days) < MIN_BLOCK_DAYS:
            continue
        # 日级 L-S 收益（等权 long mean - 等权 short mean）
        for d in days:
            lmask = np.zeros(I, dtype=bool)
            lmask[long_idx] = True
            smask = np.zeros(I, dtype=bool)
            smask[short_idx] = True
            lr = R[d, lmask]
            sr_ = R[d, smask]
            # 行业当日有效才计入（核心 panel 几乎全有效）
            lv = valid[d, lmask]
            sv = valid[d, smask]
            lmean = lr[lv].mean() if lv.any() else np.nan
            smean = sr_[sv].mean() if sv.any() else np.nan
            if not (np.isnan(lmean) or np.isnan(smean)):
                daily_ls[d] = lmean - smean
                daily_long[d] = lmean
                daily_short[d] = smean
        bm = daily_ls[start : end + 1]
        bm = bm[~np.isnan(bm)]
        if len(bm) == 0:
            continue
        blocks.append(
            {
                "k": k,
                "signal_date": dates[s],
                "start": dates[start],
                "n_days": int(len(bm)),
                "block_mean_daily": float(bm.mean()),
                "block_long": float(daily_long[start : end + 1][~np.isnan(daily_long[start : end + 1])].mean())
                if not np.all(np.isnan(daily_long[start : end + 1]))
                else 0.0,
                "block_short": float(daily_short[start : end + 1][~np.isnan(daily_short[start : end + 1])].mean())
                if not np.all(np.isnan(daily_short[start : end + 1]))
                else 0.0,
                "mom_top": [float(mom[i]) for i in long_idx],
                "mom_bot": [float(mom[i]) for i in short_idx],
            }
        )
    return {
        "blocks": blocks,
        "daily_ls": daily_ls,
        "daily_long": daily_long,
        "daily_short": daily_short,
        "formation_weeks": formation_weeks,
        "lookback": lookback,
        "n_signal": len(signal_idx),
    }


# ---------- stats (DRY helper + 块级) ----------


def block_stats(blocks: list[dict]) -> dict:
    """per-rebalance-block t：把每块当日收益聚成 block-mean，t on block-means。
    effective N = n_blocks。复用 H.day_paired_t（{block_id: [daily_rets]}）。"""
    by_block: dict[str, list[float]] = {}
    block_means: list[float] = []
    for b in blocks:
        # 重建块内日收益列表：用 block_mean × n_days 不够，需原始；这里块均值已足够做 t
        block_means.append(b["block_mean_daily"] * 100)  # 转百分号
        by_block[str(b["k"])] = [b["block_mean_daily"] * 100]  # 单元素（块均值）
    # day_paired_t 对单元素 list 退化为均值=该值，std=0 → t=0。故改用 ev_stats on 块均值。
    es = H.ev_stats(block_means)
    # 手算块级 t（ev_stats 用 pstdev，与 day_paired_t 一致）
    import statistics as st

    n = len(block_means)
    mean = sum(block_means) / n if n else 0.0
    std = st.pstdev(block_means) if n > 1 else 0.0
    se = std / (n**0.5) if n else 0.0
    t = mean / se if se > 0 else 0.0
    p = H.norm_sf_positive(t)
    return {
        "n_blocks": n,
        "block_mean_pct": round(mean, 4),
        "block_std_pct": round(std, 4),
        "t": round(t, 3),
        "p_one_sided": round(p, 6),
        "ev_stats": es,
        "wr_blocks": round(sum(1 for x in block_means if x > 0) / n * 100, 1) if n else 0.0,
    }


def daily_sharpe(daily_ls: np.ndarray) -> dict:
    v = daily_ls[~np.isnan(daily_ls)]
    if len(v) < 2:
        return {"sharpe_daily": 0.0, "mean_daily_pct": 0.0, "std_daily_pct": 0.0, "sharpe_ann": 0.0}
    m = v.mean()
    sd = v.std()
    return {
        "n_days": int(len(v)),
        "mean_daily_pct": round(m * 100, 5),
        "std_daily_pct": round(sd * 100, 5),
        "sharpe_daily": round(m / sd, 4) if sd > 0 else 0.0,
        "sharpe_ann": round(m / sd * (TRADING_DAYS_YR**0.5), 3) if sd > 0 else 0.0,
    }


def capm_audit(daily_ls: np.ndarray, bench: np.ndarray) -> dict:
    """OLS: ls = alpha + beta*bench + eps。alpha/beta + OLS t。审 long-short 抵消 beta。"""
    mask = ~np.isnan(daily_ls)
    y = daily_ls[mask]
    x = bench[mask]
    xm = x.mean()
    ym = y.mean()
    cov = ((x - xm) * (y - ym)).mean()
    varx = ((x - xm) ** 2).mean()
    beta = cov / varx if varx > 0 else 0.0
    alpha = ym - beta * xm
    resid = y - (alpha + beta * x)
    n = len(y)
    s2 = (resid**2).sum() / (n - 2) if n > 2 else 0.0
    se_alpha = (s2 * (1 / n + xm * xm / ((x - xm) ** 2).sum())) ** 0.5 if n > 2 else 0.0
    se_beta = (s2 / ((x - xm) ** 2).sum()) ** 0.5 if n > 2 else 0.0
    t_alpha = alpha / se_alpha if se_alpha > 0 else 0.0
    t_beta = beta / se_beta if se_beta > 0 else 0.0
    p_alpha = H.norm_sf_positive(t_alpha)
    return {
        "alpha_daily_pct": round(alpha * 100, 5),
        "beta": round(beta, 4),
        "alpha_t_ols": round(t_alpha, 3),
        "alpha_p_ols": round(p_alpha, 6),
        "beta_t": round(t_beta, 3),
        "n": n,
    }


def walk_forward_blocks(blocks: list[dict]) -> dict:
    """块按时间前半 train / 后半 test。train_ev>0 + test 显著才 edge-confirmed。"""
    if len(blocks) < 4:
        return {"status": "too_few_blocks", "n_blocks": len(blocks)}
    bs = sorted(blocks, key=lambda b: b["signal_date"])
    mid = len(bs) // 2
    train = [b["block_mean_daily"] * 100 for b in bs[:mid]]
    test = [b["block_mean_daily"] * 100 for b in bs[mid:]]
    import statistics as st

    def tt(xs):
        n = len(xs)
        m = sum(xs) / n
        sd = st.pstdev(xs) if n > 1 else 0.0
        se = sd / (n**0.5) if n else 0.0
        return n, m, sd, (m / se if se > 0 else 0.0), (H.norm_sf_positive(m / se) if se > 0 else 1.0)

    tn, tm, tsd, ttv, tp = tt(train)
    en, em, esd, etv, ep = tt(test)
    return {
        "status": "ok",
        "n_train": tn,
        "n_test": en,
        "train_mean_pct": round(tm, 4),
        "test_mean_pct": round(em, 4),
        "train_t": round(ttv, 3),
        "test_t": round(etv, 3),
        "test_p_raw": round(ep, 6),
    }


def verdict(gross_alpha_ann_pct: float, net_alpha_ann_pct: float, block_t: float, p_raw: float, n_blocks: int, wf: dict) -> tuple[str, str]:
    """诚实判定级联。返回 (verdict, reason)。"""
    p_bonf = H.bonferroni_p(p_raw, BONF_TOTAL)
    if gross_alpha_ann_pct < 0:
        return (
            "falsified",
            f"gross alpha {gross_alpha_ann_pct:.2f}%/yr < 0（动量反转/loser signal，long top + short bottom 赔钱）",
        )
    if n_blocks < 60:
        return "underpowered", f"n_blocks={n_blocks} < 60"
    if p_bonf >= H.ALPHA:
        return "falsified", f"Bonferroni p={p_bonf:.4f} (×{BONF_TOTAL}) >= {H.ALPHA}（不显著，alpha 噪声级）"
    if net_alpha_ann_pct <= 0:
        return (
            "falsified",
            f"gross {gross_alpha_ann_pct:.2f}%/yr > 0 但净 {net_alpha_ann_pct:.2f}%/yr <= 0（A 股 L-S 成本吃掉 gross alpha）",
        )
    if wf["status"] == "ok":
        if wf["train_mean_pct"] <= 0:
            return (
                "exploratory",
                f"train 半 alpha {wf['train_mean_pct']:.3f}% <= 0（edge 只在 test 半，regime 过拟合嫌疑）",
            )
        if wf["test_mean_pct"] <= 0:
            return "falsified", f"walk-forward test alpha {wf['test_mean_pct']:.3f}% <= 0"
        wf_p_bonf = H.bonferroni_p(wf["test_p_raw"], BONF_TOTAL)
        if wf_p_bonf >= H.ALPHA:
            return (
                "exploratory",
                f"OOS test alpha {wf['test_mean_pct']:.3f}% > 0 但 test p={wf['test_p_raw']} Bonf×{BONF_TOTAL}={wf_p_bonf:.4f} >= {H.ALPHA}（OOS 不显著）",
            )
        return (
            "edge-confirmed",
            f"gross+net alpha>0, Bonf×{BONF_TOTAL}={p_bonf:.4f}<{H.ALPHA}, OOS test {wf['test_mean_pct']:.3f}% 显著 (p={wf['test_p_raw']})",
        )
    return "exploratory", "walk-forward not available"


# ---------- main ----------


def main() -> None:
    dates, inds, R, valid, bench, meta = load_panel()
    print("=" * 74)
    print("Alpha-isolated 行业轮动 long-short（市场中性）")
    print("=" * 74)
    print(f"窗口: {meta['window']}  ({meta['n_days']} 交易日)")
    print(f"Universe: {meta['n_industries']} 个 long-core 行业（>=5 股覆盖 >=90% 交易日）")
    print(f"基准: 上证指数  mean_daily={meta['benchmark_mean_daily_pct']:.4f}%  年化={meta['benchmark_annualized_pct']:.2f}%")
    print(f"再平衡: 每 {HOLD_DAYS} 交易日（2 周），多 top-{TOP_K} + 空 bottom-{TOP_K} 等权")
    print(f"Bonferroni: ×{BONF_METHODS}（4 方法）×{BONF_FORMATION}（formation 搜索）= ×{BONF_TOTAL}")
    print(
        f"成本: {COST_PER_REBALANCE * 100:.2f}%/rebalance → 日拖累 "
        f"{COST_PER_REBALANCE / HOLD_DAYS * 100:.4f}%/day ({COST_PER_REBALANCE / HOLD_DAYS * 100 * TRADING_DAYS_YR:.2f}%/yr)"
    )

    results: list[dict] = []
    for fw in FORMATION_WEEKS:
        print(f"\n{'─' * 74}\nFormation = {fw} 周 (lookback {fw * 5} 天)\n{'─' * 74}")
        ls = run_long_short(R, valid, dates, fw)
        blocks = ls["blocks"]
        bs = block_stats(blocks)
        sh = daily_sharpe(ls["daily_ls"])
        cap = capm_audit(ls["daily_ls"], bench)
        wf = walk_forward_blocks(blocks)
        gross_ann_pct = bs["block_mean_pct"] * TRADING_DAYS_YR  # %/yr (块均日% × 252)
        cost_ann_pct = COST_PER_REBALANCE / HOLD_DAYS * 100 * TRADING_DAYS_YR
        net_ann_pct = gross_ann_pct - cost_ann_pct
        p_bonf = H.bonferroni_p(bs["p_one_sided"], BONF_TOTAL)
        v, reason = verdict(gross_ann_pct, net_ann_pct, bs["t"], bs["p_one_sided"], bs["n_blocks"], wf)
        print(f"  blocks: n={bs['n_blocks']} (signal={ls['n_signal']})")
        print(f"  block-mean: {bs['block_mean_pct']:.4f}%/day  std={bs['block_std_pct']:.4f}%  WR(blocks>0)={bs['wr_blocks']}%")
        print(f"  per-rebalance-block t={bs['t']}  p_one_sided={bs['p_one_sided']}  Bonf×{BONF_TOTAL}={p_bonf:.4f}")
        print(f"  daily Sharpe: ann={sh['sharpe_ann']}  mean={sh['mean_daily_pct']}%/day  std={sh['std_daily_pct']}%")
        print(
            f"  CAPM audit (L-S vs 上证): beta={cap['beta']} (t={cap['beta_t']}), "
            f"alpha={cap['alpha_daily_pct']}%/day (OLS t={cap['alpha_t_ols']}, p={cap['alpha_p_ols']})"
        )
        if wf["status"] == "ok":
            print(
                f"  walk-forward: train={wf['train_mean_pct']:.4f}%/day (n={wf['n_train']}) "
                f"→ test={wf['test_mean_pct']:.4f}%/day (n={wf['n_test']}, t={wf['test_t']}, p={wf['test_p_raw']})"
            )
        print(f"  gross alpha: {gross_ann_pct:.2f}%/yr  | cost: {cost_ann_pct:.2f}%/yr  | net: {net_ann_pct:.2f}%/yr")
        print(f"  → VERDICT: {v.upper()}  ({reason})")
        # 长短腿分解（看是 long 还是 short 贡献）
        if blocks:
            lm = sum(b["block_long"] for b in blocks) / len(blocks) * 100
            sm = sum(b["block_short"] for b in blocks) / len(blocks) * 100
            print(f"  leg split: long_mean={lm:.4f}%/day  short_mean={sm:.4f}%/day  (L-S={lm - sm:.4f}%)")
        results.append(
            {
                "formation_weeks": fw,
                "n_blocks": bs["n_blocks"],
                "block_mean_pct": bs["block_mean_pct"],
                "block_t": bs["t"],
                "p_raw": bs["p_one_sided"],
                "p_bonf": p_bonf,
                "sharpe_ann": sh["sharpe_ann"],
                "beta": cap["beta"],
                "capm_alpha_daily_pct": cap["alpha_daily_pct"],
                "capm_alpha_t": cap["alpha_t_ols"],
                "capm_alpha_p": cap["alpha_p_ols"],
                "gross_ann_pct": gross_ann_pct,
                "net_ann_pct": net_ann_pct,
                "cost_ann_pct": cost_ann_pct,
                "wf_train": wf.get("train_mean_pct"),
                "wf_test": wf.get("test_mean_pct"),
                "wf_test_p": wf.get("test_p_raw"),
                "wf_status": wf["status"],
                "verdict": v,
                "reason": reason,
            }
        )

    # 选最佳 formation（最高 gross block-t，in-sample 搜索 → 已 Bonferroni ×3 校正）
    best = max(results, key=lambda r: r["block_t"])
    print(f"\n{'=' * 74}\n最佳 formation（最高 block-t，已 Bonferroni 校正搜索）")
    print(f"{'=' * 74}")
    print(f"  formation = {best['formation_weeks']} 周  lookback={best['formation_weeks'] * 5} 天")
    print(f"  n_blocks = {best['n_blocks']}  block-t = {best['block_t']}  p_raw = {best['p_raw']}")
    print(f"  Bonf×{BONF_TOTAL} = {best['p_bonf']:.4f}")
    print(f"  gross alpha = {best['gross_ann_pct']:.2f}%/yr  net = {best['net_ann_pct']:.2f}%/yr")
    print(f"  Sharpe(ann) = {best['sharpe_ann']}  CAPM beta = {best['beta']}  CAPM alpha t = {best['capm_alpha_t']}")
    if best["wf_status"] == "ok":
        print(f"  walk-forward: train={best['wf_train']:.4f}%/day → test={best['wf_test']:.4f}%/day (p={best['wf_test_p']})")
    print(f"  VERDICT: {best['verdict'].upper()}")

    # 散户可行性审计
    print(f"\n{'─' * 74}\n散户可行性审计（long-short 需做空）")
    print(f"{'─' * 74}")
    print("  A 股做空渠道: 融券（券商借券）+ 股指期货（IF/IH）+ ETF 融券")
    print("  融券限制: 2023-10 起限售股转融通禁 + 融券 T+1；券源稀缺，行业组合 3 只全借难")
    print("  融券费: ~5-8% 年化（已计入成本），10 天 holding = 0.2-0.32%")
    print("  股指期货: 保证金 ~12%（IF），但做空行业需个股融券非指数期货")
    print("  结论: 纯行业 long-short 散户结构性不可行（券源+费率+限制）；机构可行。")
    print("        alpha 测试回答'轮动 timing 有无 alpha'，与可行性正交。")

    # 诚实外推边界
    print(f"\n{'─' * 74}\n外推边界（禁止外推）")
    print(f"{'─' * 74}")
    print("  本测试 = 行业轮动 long-short（market-neutral）timing alpha。")
    print("  ≠ '行业轮动有/无 edge'（active-return/factor/capm 三个 sibling 方法待合并判）")
    print("  ≠ '短线有/无 edge'（轮动 2-3 周非短线打板）")
    print("  ≠ '动量因子 A 股有效'（top-3/bottom-3 极端组 + 2-4 周短窗口，非标准 6-12 月）")
    print("  universe = 56 long-core 行业（银行/保险 absent），≠ 全市场行业")

    # 写 JSON 摘要
    out = {"method": "long-short", "best": best, "all_formation": results, "meta": meta, "bonf_total": BONF_TOTAL}
    op = Path(__file__).resolve().parent / "_rotation_long_short_result.json"
    op.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n摘要 JSON: {op}")


if __name__ == "__main__":
    main()
