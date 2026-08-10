# -*- coding: utf-8 -*-
"""S031 R20/R21：按战法历史回测引擎。

只用 DB 已有历史日（gene_scores），不触发 em_get 回溯。流程：
逐历史日 ``load_gene_scores`` → ``match_strategies`` 判定命中战法 → K 线算
入场（次日开盘）/出场（max_hold 收盘或 stop_loss/take_profit 提前平）→ 按战法
聚合 win_rate/avg_return/sample_size。

设计决策（grill 第 3 轮锁定 + 数据现实修正）：
- **不复用 match_strategies 的 entry_price**（limitup_strategy.py:680 拿基因得分当
  价格，假值）。入场价 = 次日开盘价（K 线）；出场 = max_hold_days 后收盘 或
  stop_loss_pct/take_profit_pct 提前平。
- **只跑 DB 已有历史日**（R21 防封）：_get_available_dates 查 gene_scores 表
  DISTINCT date，lookback_days 按实际截断；不触发 em_get。随预计算 seed 积累扩展。
- **匹配全部 gene_scores**（不只 qualify）：战法匹配基于因子（封板率/炸板后溢价…），
  独立于合格阈值；R20「哪些股命中哪个战法」取全部命中。plan 骨架的
  ``if not gene.qualify: continue`` 在 qualified≈0 的现实下产空回测，已弃用
  （B6「sample_size ≤ available_days」系 qualify-gate 假设，已按实际策略命中修正）。
- K 线按 code 缓存（同股跨日复用）；结果 12h 缓存（_CACHE），重复请求不重算。
- 胜率/收益属客观历史统计特征，用户可见输出挂「历史统计特征，市场有风险」。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import astock
from data.mappers import kline_from_mootdx
from limitup_screener.data import get_db, load_gene_scores
from limitup_strategy import STRATEGY_REGISTRY, match_strategies


@dataclass
class StrategyBacktestResult:
    """单战法回测聚合结果。"""

    strategy_code: str
    strategy_name: str
    win_rate: float  # 0-1
    avg_return: float  # 百分比
    sample_size: int  # 实际回测交易笔数
    available_days: int  # DB 实际可用天数（可能 < lookback_days）
    skipped: int = 0  # K 线缺失等跳过的笔数


# 结果缓存（按 lookback_days 键），12h TTL——重复请求不重算
_CACHE: dict[int, list[StrategyBacktestResult]] = {}
_CACHE_TS: dict[int, float] = {}
_CACHE_TTL = 43200  # 12 小时


def _get_available_dates(lookback_days: int) -> list[str]:
    """查 DB DISTINCT date（只跑 DB 已有日，不触发 em_get）。按日期降序。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT DISTINCT date FROM gene_scores ORDER BY date DESC LIMIT ?",
            (lookback_days,),
        ).fetchall()
        return [r["date"] for r in rows]
    finally:
        conn.close()


def _backtest_single(
    bars: list[Any],
    date: str,
    max_hold_days: int,
    stop_pct: float,
    profit_pct: float,
) -> dict[str, Any] | None:
    """K 线算入场(次日开盘)/出场(max_hold 收盘或 stop/profit 提前平)。缺数据返 None。

    stop_pct 为负（止损，如 -3）、profit_pct 为正（止盈，如 8）。
    """
    if not bars:
        return None
    idx = next((i for i, b in enumerate(bars) if (getattr(b, "date", "") or "")[:10] == date), None)
    if idx is None or idx + 1 >= len(bars):
        return None
    entry = getattr(bars[idx + 1], "open", 0)
    if not entry or entry <= 0:
        return None
    # 持仓期内逐日检查 stop_loss / take_profit 提前平
    for j in range(idx + 1, min(idx + 1 + max_hold_days, len(bars))):
        low = getattr(bars[j], "low", 0)
        high = getattr(bars[j], "high", 0)
        if low and low <= entry * (1 + stop_pct / 100):
            return {"won": False, "return_pct": float(stop_pct)}
        if high and high >= entry * (1 + profit_pct / 100):
            return {"won": True, "return_pct": float(profit_pct)}
    exit_idx = min(idx + max_hold_days, len(bars) - 1)
    exit_price = getattr(bars[exit_idx], "close", 0)
    if not exit_price:
        return None
    ret = (exit_price - entry) / entry * 100
    return {"won": ret > 0, "return_pct": round(ret, 2)}


def run_strategy_backtest(lookback_days: int = 60) -> list[StrategyBacktestResult]:
    """对 8 战法各跑历史 lookback_days（按 DB 实际可用天数截断）。

    返回 8 个 StrategyBacktestResult（按 STRATEGY_REGISTRY 顺序，sample_size=0 的也列出）。
    """
    now = time.time()
    if lookback_days in _CACHE and now - _CACHE_TS.get(lookback_days, 0) < _CACHE_TTL:
        return _CACHE[lookback_days]

    dates = _get_available_dates(lookback_days)
    available_days = len(dates)

    strat_params = {s["code"]: s for s in STRATEGY_REGISTRY}
    # K 线按 code 缓存（同股跨日复用，减少 mootdx 调用）
    kline_cache: dict[str, list[Any]] = {}

    def get_bars(code: str) -> list[Any]:
        if code not in kline_cache:
            try:
                raw = astock.kline(code, category=4, offset=lookback_days + 15)
                kline_cache[code] = kline_from_mootdx(code, raw).bars
            except Exception:
                kline_cache[code] = []
        return kline_cache[code]

    trades: list[dict[str, Any]] = []
    skipped = 0
    for d in dates:
        scores = load_gene_scores(d) or []
        for gene in scores:
            bars = get_bars(gene.code)
            signals = match_strategies(gene.code, gene)
            for sig in signals:
                params = strat_params.get(sig.strategy_code)
                if not params:
                    continue
                res = _backtest_single(
                    bars,
                    d,
                    int(params.get("max_hold_days", 3)),
                    float(params.get("stop_loss_pct", -7)),
                    float(params.get("take_profit_pct", 15)),
                )
                if res is None:
                    skipped += 1
                    continue
                trades.append({
                    "date": d,
                    "code": gene.code,
                    "name": getattr(gene, "name", gene.code),
                    "strategy_code": sig.strategy_code,
                    "strategy_name": sig.strategy_name,
                    "won": res["won"],
                    "return_pct": res["return_pct"],
                    "data_source": getattr(gene, "data_source", "eastmoney_live"),
                    "missing_factors": getattr(gene, "missing_factors", []),
                })

    # 按战法聚合
    by_strat: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        by_strat.setdefault(t["strategy_code"], []).append(t)

    results: list[StrategyBacktestResult] = []
    for s in STRATEGY_REGISTRY:
        items = by_strat.get(s["code"], [])
        total = len(items)
        wins = sum(1 for t in items if t["won"])
        avg_ret = sum(t["return_pct"] for t in items) / total if total else 0.0
        results.append(StrategyBacktestResult(
            strategy_code=s["code"],
            strategy_name=s["name"],
            win_rate=round(wins / total, 4) if total else 0.0,
            avg_return=round(avg_ret, 2),
            sample_size=total,
            available_days=available_days,
            skipped=skipped,
        ))

    _CACHE[lookback_days] = results
    _CACHE_TS[lookback_days] = now
    return results


def clear_cache() -> None:
    """清结果缓存（测试 / 强制重算用）。"""
    _CACHE.clear()
    _CACHE_TS.clear()


def list_trades(strategy_code: str, lookback_days: int = 60) -> dict[str, Any]:
    """S049 D8：某战法的回溯交易明细（懒加载，复用 run_strategy_backtest 缓存的 trades 不重算）。

    只返 DB 已有日期的交易（R21 防封：不触发 em_get 拉 K 线之外的历史）。
    available_days 如实标样本天数。
    """
    results = run_strategy_backtest(lookback_days)
    matching = next((r for r in results if r.strategy_code == strategy_code), None)
    available = matching.available_days if matching else 0
    # 重跑取 trades 列表（run_strategy_backtest 内部 12h 缓存，重复请求不重算）
    dates = _get_available_dates(lookback_days)
    strat_params = {s["code"]: s for s in STRATEGY_REGISTRY}
    params = strat_params.get(strategy_code)
    if not params:
        return {"strategy_code": strategy_code, "trades": [], "available_days": 0, "lookback_days": lookback_days}
    kline_cache: dict[str, list[Any]] = {}

    def get_bars(code: str) -> list[Any]:
        if code not in kline_cache:
            try:
                raw = astock.kline(code, category=4, offset=lookback_days + 15)
                kline_cache[code] = kline_from_mootdx(code, raw).bars
            except Exception:
                kline_cache[code] = []
        return kline_cache[code]

    trades: list[dict[str, Any]] = []
    for d in dates:
        scores = load_gene_scores(d) or []
        for gene in scores:
            bars = get_bars(gene.code)
            signals = match_strategies(gene.code, gene)
            for sig in signals:
                if sig.strategy_code != strategy_code:
                    continue
                res = _backtest_single(
                    bars, d,
                    int(params.get("max_hold_days", 3)),
                    float(params.get("stop_loss_pct", -7)),
                    float(params.get("take_profit_pct", 15)),
                )
                if res is None:
                    continue
                trades.append({
                    "date": d, "code": gene.code, "name": getattr(gene, "name", gene.code),
                    "won": res["won"], "return_pct": res["return_pct"],
                })
    return {
        "strategy_code": strategy_code,
        "trades": trades,
        "available_days": available,
        "lookback_days": lookback_days,
    }
