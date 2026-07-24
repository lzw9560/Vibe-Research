# -*- coding: utf-8 -*-
"""简化版回测 —— 基因得分 vs 次日表现散点图 + 分位分析。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import astock
import limitup_screener as ls
from limitup_screener import public_resolve_date, public_fetch_zt_pool, public_collect_zt_history_batch, LOOKBACK_DAYS
from limitup_screener.models import compute_factors, calc_total_score

_CACHE_FILE = Path(__file__).resolve().parent / "data" / "backtest_cache.json"


def _load_cache() -> dict[str, dict[str, Any]]:
    """加载回测缓存（按 start_date|end_date 键）。"""
    try:
        if _CACHE_FILE.exists():
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    """持久化回测缓存。"""
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


@dataclass
class BacktestResult:
    """简化版回测结果。"""
    period: str
    total_signals: int
    hit_count: int
    hit_rate: float
    avg_return: float
    max_drawdown: float
    sharpe_ratio: float
    scatter_data: list[dict]
    percentile_analysis: dict[str, Any]


def _calc_next_day_return(code: str, date_str: str) -> float:
    """计算次日真实收益率（基于 K 线收盘价）。"""
    try:
        klines = astock.kline(code, category=4, offset=5)
        if not klines:
            return 0.0
        # 找到当前日期或之后第一个交易日
        target_close = None
        next_close = None
        for i, k in enumerate(klines):
            k_date = k.get("date", "")[:10]
            if k_date == date_str:
                target_close = k.get("close")
                if i + 1 < len(klines):
                    next_close = klines[i + 1].get("close")
                break
        if target_close is None or next_close is None:
            return 0.0
        return (next_close - target_close) / target_close if target_close else 0.0
    except Exception:
        return 0.0


async def generate_scatter_data(date_range: tuple[str, str]) -> list[dict]:
    """生成基因得分与次日表现的散点图数据。"""
    points: list[dict] = []
    start, end = date_range

    current = start
    while current <= end:
        try:
            result = await ls.get_screener_result(current)
            for g in result.gene_scores:
                # 获取次日真实收益（基于 K 线收盘价）
                next_day_return = _calc_next_day_return(g.code, current)
                points.append({
                    "gene_score": g.total_score,
                    "next_day_return": next_day_return,
                    "code": g.code,
                    "date": current,
                    "industry": getattr(g, "industry", "未知"),
                })
        except Exception:
            pass
        current = _next_trading_day(current)

    return points


def _next_trading_day(date_str: str) -> str:
    """返回下一个交易日（跳过周末和 A 股法定节假日）。"""
    from datetime import datetime, timedelta

    # 从 data/trading_calendar.json 加载节假日
    _holidays: set[str] = set()
    try:
        import json
        from pathlib import Path
        cal_file = Path(__file__).resolve().parent / "data" / "trading_calendar.json"
        if cal_file.exists():
            with open(cal_file, "r", encoding="utf-8") as f:
                _holidays = set(json.load(f).get("holidays", []))
    except Exception:
        pass  # 加载失败则跳过节假日过滤

    d = datetime.strptime(date_str, "%Y-%m-%d")
    while True:
        d += timedelta(days=1)
        # 跳过周末（周六=5, 周日=6）
        if d.weekday() >= 5:
            continue
        # 跳过节假日
        if d.strftime("%Y-%m-%d") in _holidays:
            continue
        return d.strftime("%Y-%m-%d")


async def run_backtest_async(start_date: str, end_date: str) -> BacktestResult:
    """运行简化版回测（异步版本，带增量缓存）。"""
    cache = _load_cache()
    cache_key = f"{start_date}|{end_date}"
    if cache_key in cache:
        cached = cache[cache_key]
        return BacktestResult(**cached)

    scatter = []
    total_signals = 0
    hit_count = 0
    returns: list[float] = []

    current = start_date
    while current <= end_date:
        try:
            result = await ls.get_screener_result(current)
            for g in result.gene_scores:
                if g.total_score < 60:
                    continue
                total_signals += 1
                # 使用真实 K 线计算次日收益率
                next_day_return = _calc_next_day_return(g.code, current)
                returns.append(next_day_return)
                if next_day_return > 0:
                    hit_count += 1
                scatter.append({
                    "date": current,
                    "code": g.code,
                    "gene_score": g.total_score,
                    "next_day_return": next_day_return,
                })
        except Exception:
            pass
        current = _next_trading_day(current)

    hit_rate = hit_count / total_signals if total_signals else 0.0
    avg_return = sum(returns) / len(returns) if returns else 0.0

    # 最大回撤
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in returns:
        cumulative += r
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # 夏普比率
    if len(returns) > 1:
        mean = avg_return
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        std = variance ** 0.5
        sharpe = (mean / std) if std > 0 else 0.0
    else:
        sharpe = 0.0

    # 分位分析
    percentile_analysis = _calc_percentile_analysis(scatter)

    backtest_result = BacktestResult(
        period=f"{start_date} ~ {end_date}",
        total_signals=total_signals,
        hit_count=hit_count,
        hit_rate=round(hit_rate, 4),
        avg_return=round(avg_return, 4),
        max_drawdown=round(max_dd, 4),
        sharpe_ratio=round(sharpe, 4),
        scatter_data=scatter,
        percentile_analysis=percentile_analysis,
    )

    cache[cache_key] = asdict(backtest_result)
    _save_cache(cache)
    return backtest_result


def run_backtest(start_date: str, end_date: str) -> BacktestResult:
    """运行简化版回测（同步兼容层）。"""
    return asyncio.run(run_backtest_async(start_date, end_date))


def _calc_percentile_analysis(scatter: list[dict]) -> dict[str, Any]:
    """分位分析。"""
    buckets = {
        "75-100": {"count": 0, "returns": []},
        "60-75": {"count": 0, "returns": []},
        "0-60": {"count": 0, "returns": []},
    }
    for p in scatter:
        score = p.get("gene_score", 0)
        ret = p.get("next_day_return", 0)
        if score >= 75:
            bucket = "75-100"
        elif score >= 60:
            bucket = "60-75"
        else:
            bucket = "0-60"
        buckets[bucket]["count"] += 1
        buckets[bucket]["returns"].append(ret)

    result = {}
    for bucket, data in buckets.items():
        if data["count"] > 0:
            result[bucket] = {
                "count": data["count"],
                "avg_return": round(sum(data["returns"]) / len(data["returns"]), 4),
                "hit_rate": round(sum(1 for r in data["returns"] if r > 0) / len(data["returns"]), 4),
            }
        else:
            result[bucket] = {"count": 0, "avg_return": 0.0, "hit_rate": 0.0}
    return result
