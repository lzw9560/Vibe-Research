"""
LimitUp metrics router.
"""
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime
from typing import Any, Dict

import asyncio
import astock
import limitup_screener as _ls
import time

router = APIRouter(tags=["limitup"])

# 模块级缓存
_METRICS_CACHE: dict = {}
_METRICS_CACHE_TTL = 600  # 10 分钟


@router.get("/api/limitup/metrics")
async def limitup_metrics(date: str = Query(None, description="日期 YYYY-MM-DD，不传则取最近交易日")) -> Dict[str, Any]:
    """涨停策略聚合指标：基因分布、席位情绪、市场情绪、回测胜率。"""
    try:
        result = await _compute_limitup_metrics(date)
        return result
    except Exception as e:
        raise HTTPException(502, f"metrics 异常：{e}") from e


async def _compute_limitup_metrics(date: str | None) -> Dict[str, Any]:
    """内部：计算涨停策略聚合指标。"""
    trade_date = date or datetime.now(_ls.BEIJING_TZ).strftime("%Y-%m-%d")
    cache_key = f"metrics:{trade_date}"

    # 检查缓存
    now = time.time()
    if cache_key in _METRICS_CACHE:
        data, ts = _METRICS_CACHE[cache_key]
        if now - ts < _METRICS_CACHE_TTL:
            return data

    date_fmt = trade_date.replace("-", "") if "-" in trade_date else trade_date

    # 获取当日涨停池
    zt_pool = await asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZTPool", date_fmt, "fbt:asc")
    total = len(zt_pool) if zt_pool else 0

    # 获取基因得分统计
    screener_result = await _ls.get_screener_result(trade_date)
    # ScreenerResult 字段为 gene_scores/qualified/high_gene（list[GeneScore]），无 candidates；
    # GeneScore 是 pydantic 模型，得分字段为 total_score（无 gene_score / avg_fbt）。
    pool = screener_result.qualified if screener_result else []
    gene_scores = [g.total_score for g in pool]

    high_gene = sum(1 for s in gene_scores if s >= 80)
    mid_gene = sum(1 for s in gene_scores if 50 <= s < 80)
    low_gene = sum(1 for s in gene_scores if s < 50)

    win_rate = 0.0
    if pool:
        # GeneScore 无 avg_fbt 字段；有则计首板时间正者，无则胜率分项置 0
        wins = sum(1 for g in pool if (getattr(g, "avg_fbt", 0) or 0) > 0)
        win_rate = wins / len(pool)

    result = {
        "date": trade_date,
        "total_zt": total,
        "gene_distribution": {
            "high": high_gene,
            "mid": mid_gene,
            "low": low_gene,
        },
        "avg_gene_score": round(sum(gene_scores) / len(gene_scores), 2) if gene_scores else 0.0,
        "backtest_win_rate": round(win_rate, 4),
        "updated": datetime.now(_ls.BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
        "disclaimer": "免责声明：客观公开数据，非投资建议。",
    }

    # 写入缓存
    _METRICS_CACHE[cache_key] = (result, now)
    return result


__all__ = ["router"]
