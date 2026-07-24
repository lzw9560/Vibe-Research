# -*- coding: utf-8 -*-
"""limitup_screener 服务层 —— 业务逻辑、缓存、预计算。"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from datetime import datetime, timedelta

import astock

from limitup_screener.data import run_migrations, save_gene_scores, load_gene_scores
from limitup_screener.models import (
    GeneScore,
    ScreenerResult,
    DISCLAIMER,
    compute_gene_score,
    wilson_lower_bound,
    LOOKBACK_DAYS,
    GENE_QUALIFY_THRESHOLD,
    GENE_HIGH_THRESHOLD,
)

_BEIJING_TZ = datetime.now().astimezone().tzinfo
_logger = logging.getLogger(__name__)

# ---- 缓存 ----
_CACHE: dict = {}
_CACHE_TTL = 43200  # 12 小时
_COMPUTING: dict = {}
_RESOLVED_DATE_CACHE: dict[str, str] = {}
_RESOLVED_DATE_TTL = 3600  # 1 小时
_DATA_STALE_THRESHOLD = 3600  # 1 小时视为 stale
_DATA_EXPIRED_THRESHOLD = 86400  # 24 小时视为 expired


def _assess_freshness(age_seconds: float) -> str:
    """评估数据新鲜度。"""
    if age_seconds <= _DATA_STALE_THRESHOLD:
        return "fresh"
    if age_seconds <= _DATA_EXPIRED_THRESHOLD:
        return "stale"
    return "expired"


async def _resolve_date(date: str | None) -> str:
    """解析日期参数，回推到最近交易日（异步，带缓存）。"""
    if date:
        return date.replace("-", "")
    
    # 检查缓存
    now = time.time()
    cache_key = "latest_trading_day"
    cached = _RESOLVED_DATE_CACHE.get(cache_key)
    if cached and now - cached[0] < _RESOLVED_DATE_TTL:
        return cached[1]
    
    today = datetime.now(_BEIJING_TZ).strftime("%Y%m%d")
    for back in range(5):
        d = (datetime.now(_BEIJING_TZ) - timedelta(days=back)).strftime("%Y%m%d")
        try:
            pool = await asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZTPool", d)
            if pool:
                _RESOLVED_DATE_CACHE[cache_key] = (now, d)
                return d
        except Exception:
            continue
    
    _RESOLVED_DATE_CACHE[cache_key] = (now, today)
    return today


async def _fetch_zt_pool(date: str):
    """获取涨停池、昨涨停池、炸板池（并发）。"""
    try:
        zt, yzt, zb = await asyncio.gather(
            asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZTPool", date, "fbt:asc"),
            asyncio.to_thread(astock.em_zt_topic_pool, "getYesterdayZTPool", date, "zs:desc"),
            asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZBPool", date, "fbt:asc"),
        )
        return zt, yzt, zb
    except Exception as e:
        _logger.exception("获取涨停池失败: date=%s", date)
        return [], [], []


async def _collect_zt_history_batch(codes: set[str], date: str, lookback: int = 252) -> dict[str, list[dict]]:
    """批量回溯 lookback 天，收集多只股的涨停记录（并发优化）。"""
    results: dict[str, list[dict]] = {c: [] for c in codes}
    target_date = datetime.strptime(date, "%Y%m%d")

    all_dates = []
    for back in range(1, min(lookback, 30)):
        d = (target_date - timedelta(days=back)).strftime("%Y%m%d")
        all_dates.append(d)

    BATCH_SIZE = 20
    SLEEP_BETWEEN_BATCHES = 0.02
    for i in range(0, len(all_dates), BATCH_SIZE):
        batch = all_dates[i:i + BATCH_SIZE]
        tasks = [
            asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZTPool", d, "fbt:asc")
            for d in batch
        ]
        pools = await asyncio.gather(*tasks, return_exceptions=True)

        for d, pool in zip(batch, pools):
            if isinstance(pool, Exception):
                _logger.warning("获取涨停池失败: date=%s, error=%s", d, pool)
                continue
            for item in pool:
                code = str(item.get("c", ""))
                if code in codes and code.isdigit() and len(code) == 6:
                    results.setdefault(code, []).append(dict(item, _pool_date=d))

        if i + BATCH_SIZE < len(all_dates):
            await asyncio.sleep(SLEEP_BETWEEN_BATCHES)

    return results


async def _compute_and_cache_async(target_date: str, cache_key: str) -> ScreenerResult:
    """执行基因得分计算并缓存结果（异步版本）。"""
    now = time.time()

    zt_pool, yzt_pool, zb_pool = await _fetch_zt_pool(target_date)
    display_date = target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:]
    if not zt_pool:
        result = ScreenerResult(
            date=display_date,
            gene_scores=[],
            qualified=[],
            high_gene=[],
            updated=datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
            disclaimer=DISCLAIMER,
            data_freshness="fresh",
            data_age_seconds=0.0,
        )
        _CACHE[cache_key] = (now, result)
        return result

    seen: dict[str, dict] = {}
    for item in zt_pool:
        code = str(item.get("c", ""))
        if code and code not in seen:
            seen[code] = item

    codes = {c for c in seen.keys() if c.isdigit() and len(c) == 6}
    batch_history = await _collect_zt_history_batch(codes, target_date, LOOKBACK_DAYS)

    scores = []
    for code, item in seen.items():
        if not code.isdigit() or len(code) != 6:
            continue
        name = item.get("n", "")
        history = batch_history.get(code, [])
        scores.append((code, name, history, yzt_pool, zb_pool, item))

    # 并行计算基因得分
    async def _compute_one(args: tuple) -> GeneScore:
        c, n, h, y, z, item = args
        return compute_gene_score(c, n, h, y, z, include_backtest=True, pool_item=item)

    gene_tasks = [_compute_one(s) for s in scores]
    gene_results = await asyncio.gather(*gene_tasks, return_exceptions=True)
    gene_scores = [g for g in gene_results if not isinstance(g, Exception)]

    gene_scores.sort(key=lambda g: g.total_score, reverse=True)

    qualified = [g for g in gene_scores if g.qualify]
    high_gene_list = [g for g in gene_scores if g.high_gene]

    result = ScreenerResult(
        date=display_date,
        gene_scores=gene_scores,
        qualified=qualified,
        high_gene=high_gene_list,
        updated=datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
        disclaimer=DISCLAIMER,
        data_freshness="fresh",
        data_age_seconds=0.0,
    )

    await asyncio.to_thread(save_gene_scores, display_date, gene_scores)
    _CACHE[cache_key] = (now, result)
    return result


def _compute_and_cache(target_date: str, cache_key: str):
    """执行基因得分计算并缓存结果（同步兼容层）。"""
    return asyncio.run(_compute_and_cache_async(target_date, cache_key))


async def get_screener_result(date: str | None = None) -> ScreenerResult:
    """获取全市场涨停股基因得分清单（客观数据，无行动建议）。"""
    target_date = await _resolve_date(date)
    cache_key = f"limitup_screener_{target_date}"
    now = time.time()

    hit = _CACHE.get(cache_key)
    if hit and now - hit[0] < _CACHE_TTL:
        age = now - hit[0]
        freshness = _assess_freshness(age)
        result = hit[1].model_copy(update={
            "data_freshness": freshness,
            "data_age_seconds": round(age, 1),
        })
        return result

    db_scores = load_gene_scores(target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:])
    if db_scores is not None:
        qualified = [g for g in db_scores if g.qualify]
        high_gene_list = [g for g in db_scores if g.high_gene]
        result = ScreenerResult(
            date=target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:],
            gene_scores=db_scores,
            qualified=qualified,
            high_gene=high_gene_list,
            updated=datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
            disclaimer=DISCLAIMER,
            data_freshness="fresh",
            data_age_seconds=0.0,
        )
        _CACHE[cache_key] = (now, result)
        return result

    if cache_key in _COMPUTING:
        waited = 0
        while cache_key in _COMPUTING and waited < 60:
            await asyncio.sleep(0.5)
            waited += 0.5
        hit = _CACHE.get(cache_key)
        if hit and now - hit[0] < _CACHE_TTL:
            age = now - hit[0]
            freshness = _assess_freshness(age)
            return hit[1].model_copy(update={
                "data_freshness": freshness,
                "data_age_seconds": round(age, 1),
            })
        db_scores = load_gene_scores(target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:])
        if db_scores is not None:
            qualified = [g for g in db_scores if g.qualify]
            high_gene_list = [g for g in db_scores if g.high_gene]
            result = ScreenerResult(
                date=target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:],
                gene_scores=db_scores,
                qualified=qualified,
                high_gene=high_gene_list,
                updated=datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
                disclaimer=DISCLAIMER,
                data_freshness="fresh",
                data_age_seconds=0.0,
            )
            _CACHE[cache_key] = (now, result)
            return result

    _COMPUTING[cache_key] = True
    result_holder = []
    error_holder = []

    def _compute_with_timeout():
        try:
            result_holder.append(_compute_and_cache(target_date, cache_key))
        except Exception as e:
            error_holder.append(e)

    compute_thread = threading.Thread(target=_compute_with_timeout, daemon=True)
    compute_thread.start()
    compute_thread.join(timeout=90)

    if error_holder:
        raise error_holder[0]

    if result_holder:
        return result_holder[0]

    _COMPUTING.pop(cache_key, None)
    return ScreenerResult(
        date=target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:],
        gene_scores=[],
        qualified=[],
        high_gene=[],
        updated=datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
        disclaimer=DISCLAIMER + " （计算超时，请稍后刷新）",
        data_freshness="expired",
        data_age_seconds=0.0,
    )


# ---- 公有接口（供 limitup_strategy 等外部模块调用） ----

async def public_resolve_date(date: str | None = None) -> str:
    """公有：解析日期参数，回推到最近交易日。"""
    return await _resolve_date(date)


async def public_fetch_zt_pool(date: str):
    """公有：获取涨停池、昨涨停池、炸板池（并发）。"""
    return await _fetch_zt_pool(date)


async def public_collect_zt_history_batch(codes: set[str], date: str, lookback: int = 252) -> dict[str, list[dict]]:
    """公有：批量回溯 lookback 天，收集多只股的涨停记录（并发优化）。"""
    return await _collect_zt_history_batch(codes, date, lookback)


def public_get_cache() -> dict:
    """公有：获取内存缓存（只读）。"""
    return _CACHE


def public_get_cache_ttl() -> int:
    """公有：获取缓存 TTL。"""
    return _CACHE_TTL


def public_load_gene_scores(date: str) -> list | None:
    """公有：从数据库加载基因得分。"""
    from limitup_screener.data import load_gene_scores
    return load_gene_scores(date)


async def precompute_daily_async(date: str | None = None) -> ScreenerResult:
    """每日预计算入口（异步版本）。"""
    if date is None:
        date = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
    date_fmt = date.replace("-", "") if "-" in date else date
    target_date = await _resolve_date(date_fmt)
    cache_key = f"limitup_screener_{target_date}"
    return await _compute_and_cache_async(target_date, cache_key)


def precompute_daily(date: str | None = None) -> ScreenerResult:
    """每日预计算入口（同步兼容层）。"""
    if date is None:
        date = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
    date_fmt = date.replace("-", "") if "-" in date else date
    target_date = asyncio.run(_resolve_date(date_fmt))
    cache_key = f"limitup_screener_{target_date}"
    return _compute_and_cache(target_date, cache_key)


async def backfill_async(start_date: str, end_date: str | None = None) -> list[ScreenerResult]:
    """历史回填（异步版本）。"""
    if end_date is None:
        end_date = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    results = []
    current_dt = start_dt
    while current_dt <= end_dt:
        date_str = current_dt.strftime("%Y-%m-%d")
        try:
            result = await precompute_daily_async(date_str)
            results.append(result)
        except Exception as e:
            logging.getLogger("vibe-research").warning("[%s] 预计算失败: %s", date_str, e)
        current_dt += timedelta(days=1)
        await asyncio.sleep(0.5)
    return results


def backfill(start_date: str, end_date: str | None = None) -> list[ScreenerResult]:
    """历史回填（同步兼容层）。"""
    if end_date is None:
        end_date = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    results = []
    current_dt = start_dt
    while current_dt <= end_dt:
        date_str = current_dt.strftime("%Y-%m-%d")
        try:
            result = precompute_daily(date_str)
            results.append(result)
        except Exception as e:
            logging.getLogger("vibe-research").warning("[%s] 预计算失败: %s", date_str, e)
        current_dt += timedelta(days=1)
        time.sleep(0.5)
    return results
