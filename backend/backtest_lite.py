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
from data.mappers import kline_from_mootdx
from limitup_screener import public_resolve_date, public_fetch_zt_pool, public_collect_zt_history_batch, LOOKBACK_DAYS
from limitup_screener.models import compute_factors, calc_total_score

_CACHE_FILE = Path(__file__).resolve().parent / "data" / "backtest_cache.json"

# 分桶方案：(标签, 下界含, 上界) —— 上界含（末桶用 float("inf") 兜住右端点）
_GENE_SCORE_BUCKETS = (("0-60", 0, 60.0), ("60-75", 60.0, 75.0), ("75-100", 75.0, float("inf")))
_PREMIUM_BUCKETS = (
    ("0-30", 0, 30.0),
    ("30-50", 30.0, 50.0),
    ("50-70", 50.0, 70.0),
    ("70-100", 70.0, float("inf")),
)


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
    factor_percentile_analysis: dict[str, Any] | None = None


def _calc_next_day_return(code: str, date_str: str, kline_cache: dict[str, Any] | None = None) -> float:
    """计算次日真实收益率（基于 K 线收盘价）。kline_cache 按 code 缓存 bars，跨日复用。"""
    try:
        if kline_cache is not None and code in kline_cache:
            bars = kline_cache[code]
        else:
            _meta = kline_cache.get("_offset") if kline_cache is not None else None
            offset = int(_meta) if isinstance(_meta, (int, float)) else 5
            raw = astock.kline(code, category=4, offset=offset)
            bars = kline_from_mootdx(code, raw).bars
            if kline_cache is not None:
                kline_cache[code] = bars
        if not bars:
            return 0.0
        # 找到当前日期或之后第一个交易日
        target_close = None
        next_close = None
        for i, b in enumerate(bars):
            if (b.date or "")[:10] == date_str:
                target_close = b.close
                if i + 1 < len(bars):
                    next_close = bars[i + 1].close
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

    # K 线按 code 缓存（同股跨日复用），offset = 日历天数 + 15 余量
    from datetime import datetime as _dt
    window_days = (_dt.strptime(end, "%Y-%m-%d") - _dt.strptime(start, "%Y-%m-%d")).days
    kline_cache: dict[str, Any] = {"_offset": max(5, window_days + 15)}

    current = start
    while current <= end:
        try:
            result = await ls.get_screener_result(current)
            for g in result.gene_scores:
                # 获取次日真实收益（基于 K 线收盘价）
                next_day_return = _calc_next_day_return(g.code, current, kline_cache)
                points.append({
                    "gene_score": g.total_score,
                    "next_day_return": next_day_return,
                    "code": g.code,
                    "date": current,
                    "industry": getattr(g, "industry", "未知"),
                    "factor_premium_rate": (g.factors or {}).get("次日溢价率", 0),
                    "data_source": getattr(g, "data_source", "eastmoney_live"),
                    "missing_factors": getattr(g, "missing_factors", []),
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

    # K 线按 code 缓存（同股跨日复用），offset = 日历天数 + 15 余量
    from datetime import datetime as _dt
    window_days = (_dt.strptime(end_date, "%Y-%m-%d") - _dt.strptime(start_date, "%Y-%m-%d")).days
    kline_cache: dict[str, Any] = {"_offset": max(5, window_days + 15)}

    current = start_date
    while current <= end_date:
        try:
            result = await ls.get_screener_result(current)
            for g in result.gene_scores:
                if g.total_score < 60:
                    continue
                total_signals += 1
                # 使用真实 K 线计算次日收益率
                next_day_return = _calc_next_day_return(g.code, current, kline_cache)
                returns.append(next_day_return)
                if next_day_return > 0:
                    hit_count += 1
                scatter.append({
                    "date": current,
                    "code": g.code,
                    "gene_score": g.total_score,
                    "next_day_return": next_day_return,
                    "factor_premium_rate": (g.factors or {}).get("次日溢价率", 0),
                    "data_source": getattr(g, "data_source", "eastmoney_live"),
                    "missing_factors": getattr(g, "missing_factors", []),
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
    factor_percentile_analysis = _calc_factor_percentile_analysis(
        scatter, "factor_premium_rate", _PREMIUM_BUCKETS
    )

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
        factor_percentile_analysis=factor_percentile_analysis,
    )

    cache[cache_key] = asdict(backtest_result)
    _save_cache(cache)
    return backtest_result


def run_backtest(start_date: str, end_date: str) -> BacktestResult:
    """运行简化版回测（同步兼容层）。"""
    return asyncio.run(run_backtest_async(start_date, end_date))


def _calc_factor_percentile_analysis(
    scatter: list[dict],
    factor_key: str,
    buckets: tuple[tuple[str, float, float], ...],
) -> dict[str, Any]:
    """按指定因子分桶的分位分析，各桶输出 count / avg_return / hit_rate。

    buckets: (标签, 下界含, 上界) 序列；末桶上界建议 float("inf") 兜住右端点。
    """
    acc = {label: {"count": 0, "returns": []} for label, _, _ in buckets}
    for p in scatter:
        value = p.get(factor_key, 0)
        ret = p.get("next_day_return", 0)
        for label, lo, hi in buckets:
            if lo <= value < hi or (hi == float("inf") and value >= lo):
                acc[label]["count"] += 1
                acc[label]["returns"].append(ret)
                break

    result = {}
    for label, _, _ in buckets:
        data = acc[label]
        if data["count"] > 0:
            result[label] = {
                "count": data["count"],
                "avg_return": round(sum(data["returns"]) / len(data["returns"]), 4),
                "hit_rate": round(sum(1 for r in data["returns"] if r > 0) / len(data["returns"]), 4),
            }
        else:
            result[label] = {"count": 0, "avg_return": 0.0, "hit_rate": 0.0}
    return result


def _calc_percentile_analysis(scatter: list[dict]) -> dict[str, Any]:
    """分位分析（按 gene_score 三档，泛化函数的特例）。"""
    return _calc_factor_percentile_analysis(scatter, "gene_score", _GENE_SCORE_BUCKETS)
