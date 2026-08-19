# -*- coding: utf-8 -*-
"""S040 v2 · K 线重建涨停池历史——从日 K 线推导涨停日 + 连板数 + 基因分。

诚实降级：3 因子可推（连板率/红盘率/涨停频次），2 因子不可推（封板率/炸板后溢价）标注 None。
total_score 用 3 因子重算权重（weights="rebuild"）。
data_source="kline_rebuild"，missing_factors=["封板率","炸板后溢价"]。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import astock
from data.mappers import kline_from_mootdx
from limitup_screener.models import (
    GeneScore,
    ZTPoolItem,
    compute_factors,
    calc_total_score,
    validate_limit_up_price,
    wilson_lower_bound,
    GENE_QUALIFY_THRESHOLD,
    GENE_HIGH_THRESHOLD,
    LOOKBACK_DAYS,
    DISCLAIMER,
)
from limitup_screener.data import get_db

logger = logging.getLogger(__name__)

_MISSING_FACTORS = ["封板率", "炸板后溢价"]
_TOLERANCE = 0.015  # 涨停价判定容差（1.5 分钱，覆盖四舍五入 + tick size 差异）
_CONCURRENCY = 20  # K 线获取并发度（mootdx 不限流，TickFlow 10/min 由其 SDK 自限）


def is_limit_up(close: float, prev_close: float, code: str, tolerance: float = _TOLERANCE) -> bool:
    """判定当日是否涨停：close ≈ validate_limit_up_price(prev_close, code) 容差内。"""
    if not prev_close or prev_close <= 0:
        return False
    limit_up_price, _ = validate_limit_up_price(prev_close, code)
    if limit_up_price <= 0:
        return False
    return abs(close - limit_up_price) <= tolerance


def count_consecutive_boards(bars: list, end_idx: int) -> int:
    """从 bars[end_idx] 往前数连续涨停天数（含 end_idx）。bars 需含 .date/.close 属性。"""
    count = 0
    for i in range(end_idx, -1, -1):
        if i == 0:
            break
        b = bars[i]
        prev = bars[i - 1]
        if is_limit_up(b.close, prev.close, _code_from_bar(b)):
            count += 1
        else:
            break
    return count


def _code_from_bar(bar: Any) -> str:
    """从 K 线 bar 提取 code（mootdx bar 可能无 code 字段，用外部传入）。"""
    return getattr(bar, "code", "") or getattr(bar, "symbol", "") or ""


def build_ztpool_items_from_klines(
    code: str, name: str, bars: list, target_date: str,
) -> tuple[list[ZTPoolItem], ZTPoolItem | None]:
    """从 K 线序列构造历史涨停 ZTPoolItem 列表 + 当日 pool_item（若涨停）。

    bars: 已按日期升序排列的 K 线列表，每项含 .date/.close。
    返回 (history_ztpool_items, today_pool_item_or_None)。
    """
    history: list[ZTPoolItem] = []
    today_item: ZTPoolItem | None = None

    for i, b in enumerate(bars):
        date_str = (b.date or "")[:10]
        if not date_str:
            continue
        if i == 0:
            continue  # 第一天无 prev_close
        prev_close = bars[i - 1].close
        close = b.close
        if not is_limit_up(close, prev_close, code):
            continue

        # 涨停日：构造 ZTPoolItem
        boards = count_consecutive_boards(bars, i)
        limit_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0.0
        limit_price, _ = validate_limit_up_price(prev_close, code)
        item = ZTPoolItem(
            code=code,
            name=name,
            boards=float(boards),
            seal_time=None,  # K 线不可推
            broken_count=None,  # K 线不可推
            limit_price=limit_price,
            open=getattr(b, "open", None),
            seal_amount=None,  # K 线不可推
            float_shares=None,  # K 线不可推
            prev_close=prev_close,
            limit_pct=limit_pct,
            industry=None,
            pool_date=date_str,
        )
        history.append(item)
        if date_str == target_date:
            today_item = item

    return history, today_item


def _get_kline_bars(code: str, end_date: str, lookback_days: int = LOOKBACK_DAYS) -> list:
    """取某 code 的日 K 线。mootdx 为主，TickFlow 兜底。返回 bars 列表（升序，<= end_date）。"""
    # 主源：mootdx
    try:
        raw = astock.kline(code, category=4, offset=lookback_days + 20)
        bars = list(kline_from_mootdx(code, raw).bars)
        result = [b for b in bars if (b.date or "")[:10] <= end_date]
        if result:
            return result
    except Exception:
        pass  # mootdx 失败，fallback TickFlow

    # 备用源：TickFlow
    try:
        from data.sources.tickflow import fetch_klines_as_bars
        bars = fetch_klines_as_bars(code, count=lookback_days + 20)
        result = [b for b in bars if (b.date or "")[:10] <= end_date]
        if result:
            return result
    except Exception:
        pass

    return []


async def rebuild_date(
    date: str,
    codes: list[str] | None = None,
    lookback_days: int = LOOKBACK_DAYS,
) -> list[GeneScore]:
    """K 线重建某日的涨停池基因分（3 因子降级）。

    codes: 待扫描的 code 列表。None 时从 DB 取所有曾出现的 code。
    返回当日涨停股的 GeneScore 列表（data_source="kline_rebuild"）。
    """
    if codes is None:
        codes = await _get_db_codes()

    target_date = date.replace("-", "")
    results: list[GeneScore] = []

    # 分批并发获取 K 线 + 判定涨停（mootdx 同步阻塞，用 to_thread 包装）
    async def _process_code(code: str) -> GeneScore | None:
        try:
            bars = await asyncio.to_thread(_get_kline_bars, code, date, lookback_days)
        except Exception:
            return None
        if len(bars) < 3:
            return None

        today_bar = None
        for b in bars:
            if (b.date or "")[:10] == date:
                today_bar = b
                break
        if today_bar is None:
            return None

        today_idx = bars.index(today_bar)
        if today_idx == 0:
            return None
        prev_close = bars[today_idx - 1].close
        if not is_limit_up(today_bar.close, prev_close, code):
            return None

        name = getattr(today_bar, "name", "") or ""
        history, today_item = build_ztpool_items_from_klines(code, name, bars, date)
        if not history:
            return None

        factors = compute_factors(history, [], [])
        factors["封板率"] = None  # type: ignore
        factors["炸板后溢价"] = None  # type: ignore

        total = calc_total_score(factors, weights="rebuild")
        wilson_adj = round(total * wilson_lower_bound(len(history), max(len(history), 1), z=1.96), 2)

        last_dates = sorted(
            {h.pool_date for h in history if h.pool_date},
            reverse=True,
        )[:10]

        return GeneScore(
            code=code,
            name=name,
            total_score=total,
            factors=factors,
            wilson_adjusted=wilson_adj,
            qualify=total >= GENE_QUALIFY_THRESHOLD,
            high_gene=total >= GENE_HIGH_THRESHOLD,
            last_zt_dates=last_dates,
            zt_count_250d=len(history),
            data_source="kline_rebuild",
            missing_factors=list(_MISSING_FACTORS),
            date=date,
        )

    # 分批 gather，每批 _CONCURRENCY 个
    for i in range(0, len(codes), _CONCURRENCY):
        batch = codes[i:i + _CONCURRENCY]
        batch_results = await asyncio.gather(*[_process_code(c) for c in batch], return_exceptions=True)
        for r in batch_results:
            if isinstance(r, GeneScore):
                results.append(r)

    results.sort(key=lambda g: g.total_score, reverse=True)
    logger.info("[kline_rebuild] %s: %d 只涨停股重建完成（并发=%d）", date, len(results), _CONCURRENCY)
    return results


async def _get_db_codes() -> list[str]:
    """从 DB 取所有曾出现的 code 列表（去重）。"""
    try:
        from limitup_screener.data import get_db
        conn = get_db()
        rows = conn.execute("SELECT DISTINCT code FROM gene_scores").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def rebuild_date_sync(date: str, codes: list[str] | None = None) -> list[GeneScore]:
    """同步封装。"""
    return asyncio.run(rebuild_date(date, codes))
