# -*- coding: utf-8 -*-
"""S202: 统一 get_kline 接口 + IC/IR 评价层 + 行业中性化。

verdict HIGH 优先 spec（quant workflow ww1bqpg70）：
- get_kline(code, start, end, freq) 标准接口（屏蔽 astock/bars_provider/baostock 差异）
- compute_ic（Spearman + Newey-West HAC）+ compute_ic_ir + 分层回测（Jonckheere-Terpstra）
- 行业中性化（demean + residualize，替代 recommendation_engine:156 stub）

IC/IR 是 Alphalens 因子筛选层，与 §44v2 lift 策略验证层互补非替代。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from scipy import stats as sp_stats

logger = logging.getLogger(__name__)

# ── get_kline 统一接口 ──────────────────────────────────────────────────────

def get_kline(
    code: str,
    start: str | None = None,
    end: str | None = None,
    freq: str = "D",
) -> list[dict]:
    """统一 K 线取数接口（屏蔽数据源差异）。

    优先级：KlineCache（内存+baostock fallback）> baostock 直拉 > []
    返回 list[dict]，每 bar 含 date/open/high/low/close/volume/amount。

    Args:
        code: 6 位股票代码
        start: YYYY-MM-DD（默认 400 天前）
        end: YYYY-MM-DD（默认今天）
        freq: 频率（D=日线，目前仅 D）
    """
    if not code or not code.strip():
        return []
    code = code.strip()
    if freq != "D":
        logger.warning("get_kline: 暂不支持 freq=%s，仅 D", freq)
        return []

    end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()
    start_dt = datetime.strptime(start, "%Y-%m-%d") if start else end_dt - timedelta(days=400)

    # 1. KlineCache（含 baostock fallback）
    try:
        from engine.bars_provider import KlineCacheBarsProvider
        provider = KlineCacheBarsProvider()
        all_bars = provider(code)
        if all_bars:
            return _filter_by_date(all_bars, start_dt, end_dt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_kline: KlineCacheBarsProvider 失败 %s: %s", code, exc)

    # 2. baostock 直拉 fallback
    try:
        from engine.bars_provider import _baostock_a_share_hist
        bars = _baostock_a_share_hist(code)
        if bars:
            return _filter_by_date(bars, start_dt, end_dt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_kline: baostock fallback 失败 %s: %s", code, exc)

    return []


def _filter_by_date(
    bars: list[dict], start_dt: datetime, end_dt: datetime
) -> list[dict]:
    """过滤 bars 在 [start, end] 范围内。"""
    out = []
    for b in bars:
        d = str(b.get("date", ""))[:10]
        if not d:
            continue
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            continue
        if start_dt <= dt <= end_dt:
            out.append(b)
    return out


# ── IC/IR 评价层（Alphalens 因子筛选，互补 §44v2 策略验证）─────────────────

# 门槛（verdict: monthly IC>0.03 AND IC_IR(HAC)>0.5 AND panels≥24）
IC_FLOOR = 0.03
IR_FLOOR = 0.5
PANEL_MIN = 24
NW_LAG_DEFAULT = 3  # Newey-West HAC lag


def compute_ic(
    factor_values: np.ndarray,
    forward_returns: np.ndarray,
) -> float:
    """Spearman rank IC（因子值 vs 下期收益的相关系数）。

    Args:
        factor_values: 截面因子值（N 股）
        forward_returns: 下期收益（同 N 股）
    Returns:
        IC（Spearman rho），[-1, 1]
    """
    mask = ~(np.isnan(factor_values) | np.isnan(forward_returns))
    fv = factor_values[mask]
    fr = forward_returns[mask]
    if len(fv) < 5:
        return 0.0
    rho, _ = sp_stats.spearmanr(fv, fr)
    return float(rho) if not np.isnan(rho) else 0.0


def compute_ic_series(
    factor_panel: dict[str, np.ndarray],
    return_panel: dict[str, np.ndarray],
) -> list[float]:
    """月度 IC 序列（逐期算截面 IC）。

    Args:
        factor_panel: {date: factor_values(N股)}
        return_panel: {date: forward_returns(同N股)}
    Returns:
        IC 序列 list[float]
    """
    dates = sorted(set(factor_panel.keys()) & set(return_panel.keys()))
    ics = []
    for d in dates:
        fv = np.asarray(factor_panel[d], dtype=float)
        fr = np.asarray(return_panel[d], dtype=float)
        n = min(len(fv), len(fr))
        if n < 5:
            continue
        ics.append(compute_ic(fv[:n], fr[:n]))
    return ics


def _newey_west_std(ic_series: list[float], lag: int = NW_LAG_DEFAULT) -> float:
    """Newey-West HAC 标准误（调 IC 序列自相关）。

    lag=3 适应月度 IC 的 AR(1)-AR(3) 自相关。
    """
    if len(ic_series) < 2:
        return 0.0
    arr = np.asarray(ic_series, dtype=float)
    n = len(arr)
    mean = arr.mean()
    var = np.sum((arr - mean) ** 2) / n
    for k in range(1, min(lag + 1, n)):
        gamma_k = np.sum((arr[k:] - mean) * (arr[:-k] - mean)) / n
        var += 2 * gamma_k
    return float(np.sqrt(max(var, 1e-12)))


def compute_ic_ir(ic_series: list[float]) -> tuple[float, float]:
    """IC IR = mean(IC) / std_HAC(IC)。

    Returns:
        (IR, std_HAC)
    """
    if len(ic_series) < 2:
        return 0.0, 0.0
    mean_ic = float(np.mean(ic_series))
    std_hac = _newey_west_std(ic_series)
    ir = mean_ic / std_hac if std_hac > 1e-12 else 0.0
    return ir, std_hac


def layered_backtest(
    factor_values: np.ndarray,
    forward_returns: np.ndarray,
    n_groups: int = 5,
) -> dict[str, Any]:
    """分层回测（N 组单调性检验 + day-clustered quantile spread）。

    Args:
        factor_values: 截面因子值
        forward_returns: 下期收益
        n_groups: 分组数（5 或 10）
    Returns:
        {group_means, monotonic, spread_t, spread_p}
    """
    mask = ~(np.isnan(factor_values) | np.isnan(forward_returns))
    fv = factor_values[mask]
    fr = forward_returns[mask]
    if len(fv) < n_groups * 3:
        return {"group_means": [], "monotonic": False, "spread_t": 0.0, "spread_p": 1.0}

    order = np.argsort(fv)
    group_size = len(fv) // n_groups
    group_means = []
    for g in range(n_groups):
        idx = order[g * group_size:(g + 1) * group_size]
        group_means.append(float(np.mean(fr[idx])))

    # Jonckheere-Terpstra 单调性（近似：检查是否单调递减，因子值高→收益高）
    monotonic = all(group_means[i] <= group_means[i + 1] for i in range(n_groups - 1)) or \
                all(group_means[i] >= group_means[i + 1] for i in range(n_groups - 1))

    # 最高组 vs 最低组 t-test
    top_idx = order[-group_size:]
    bot_idx = order[:group_size]
    top_ret = fr[top_idx]
    bot_ret = fr[bot_idx]
    if len(top_ret) < 2 or len(bot_ret) < 2:
        return {"group_means": group_means, "monotonic": monotonic, "spread_t": 0.0, "spread_p": 1.0}
    t_stat, p_val = sp_stats.ttest_ind(top_ret, bot_ret, equal_var=False)
    return {
        "group_means": group_means,
        "monotonic": monotonic,
        "spread_t": float(t_stat) if not np.isnan(t_stat) else 0.0,
        "spread_p": float(p_val) if not np.isnan(p_val) else 1.0,
    }


def ic_ir_verdict(
    ic_series: list[float],
    n_panels: int,
) -> dict[str, Any]:
    """IC/IR verdict（门槛：IC>0.03 AND IR>0.5 AND panels≥24）。

    Returns:
        {mean_ic, ir_hac, std_hac, n_panels, verdict}
    """
    ir, std_hac = compute_ic_ir(ic_series)
    mean_ic = float(np.mean(ic_series)) if ic_series else 0.0
    passes = (
        mean_ic > IC_FLOOR
        and ir > IR_FLOOR
        and n_panels >= PANEL_MIN
    )
    return {
        "mean_ic": mean_ic,
        "ir_hac": ir,
        "std_hac": std_hac,
        "n_panels": n_panels,
        "verdict": "strong_factor" if passes else "weak_or_noise",
        "thresholds": {"ic": IC_FLOOR, "ir": IR_FLOOR, "panels": PANEL_MIN},
    }


# ── 行业中性化 ─────────────────────────────────────────────────────────────

def industry_demean(
    factor_values: np.ndarray,
    industry_labels: np.ndarray,
) -> np.ndarray:
    """行业中位数 demean（去行业暴露）。

    Args:
        factor_values: 截面因子值（N 股）
        industry_labels: 行业标签（同 N 股，如 "电子"/"医药"/"金融"）
    Returns:
        residual = factor - industry_median
    """
    unique_ind = np.unique(industry_labels)
    residuals = np.zeros_like(factor_values, dtype=float)
    for ind in unique_ind:
        mask = industry_labels == ind
        if mask.sum() < 1:
            continue
        med = np.median(factor_values[mask])
        residuals[mask] = factor_values[mask] - med
    return residuals


def industry_neutralize(
    factor_values: np.ndarray,
    industry_labels: np.ndarray,
    size_proxy: np.ndarray | None = None,
) -> np.ndarray:
    """行业+市值中性化（demean industry + residualize size）。

    Args:
        factor_values: 截面因子值
        industry_labels: 行业标签
        size_proxy: 市值代理（如 log(mkt_cap)，None 跳过 size neutralize）
    Returns:
        orthogonalized factor（行业+市值中性后残差）
    """
    res = industry_demean(factor_values, industry_labels)
    if size_proxy is not None:
        mask = ~np.isnan(res) & ~np.isnan(size_proxy)
        if mask.sum() >= 5:
            # OLS residualize: factor ~ size, 取残差
            slope, intercept, _, _, _ = sp_stats.linregress(size_proxy[mask], res[mask])
            predicted = intercept + slope * size_proxy[mask]
            res_temp = res.copy()
            res_temp[mask] = res[mask] - predicted
            res = res_temp
    return res
