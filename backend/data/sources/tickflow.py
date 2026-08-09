# -*- coding: utf-8 -*-
"""S040 R8 · TickFlow K 线源 fetcher —— mootdx 备用，提供日 K 线回溯。

定位：kline_rebuild 的备用 K 线源。mootdx 失败时 fallback 到 TickFlow。
API key 从 .env 读 TICKFLOW_API_KEY，不进 git。

TickFlow SDK：``TickFlow(api_key).klines.get(symbol, period="1d", count=N, as_dataframe=True)``
返回 DataFrame 列：symbol/name/timestamp/trade_date/trade_time/open/high/low/close/volume/amount
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# 懒加载——TickFlow SDK 可选装
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from tickflow import TickFlow
        _client = TickFlow(api_key=api_key, timeout=15)
        return _client
    except ImportError:
        logger.warning("[tickflow] SDK 未安装，pip install tickflow")
        return None
    except Exception as exc:
        logger.warning("[tickflow] 客户端初始化失败: %s", exc)
        return None


def _to_tickflow_symbol(code: str) -> str | None:
    """本项目 code（6位数字）→ TickFlow symbol（带 .SH/.SZ 后缀）。"""
    if not code or len(code) != 6 or not code.isdigit():
        return None
    if code.startswith(("60", "68", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def fetch_klines(code: str, count: int = 300) -> list[dict]:
    """从 TickFlow 取日 K 线，返回 mootdx 兼容的 raw bars list[dict]。

    返回格式与 astock.kline 的 raw 一致（含 open/close/high/low/vol/amount/date），
    可直接喂给 data.mappers.kline_from_mootdx。
    """
    symbol = _to_tickflow_symbol(code)
    if not symbol:
        return []

    client = _get_client()
    if client is None:
        return []

    try:
        df = client.klines.get(symbol, period="1d", count=count, as_dataframe=True)
        if df is None or len(df) == 0:
            return []

        bars: list[dict] = []
        for _, row in df.iterrows():
            trade_date = str(row.get("trade_date", "") or "")[:10]
            if not trade_date:
                continue
            bars.append({
                "date": trade_date,
                "open": float(row.get("open", 0) or 0),
                "close": float(row.get("close", 0) or 0),
                "high": float(row.get("high", 0) or 0),
                "low": float(row.get("low", 0) or 0),
                "vol": float(row.get("volume", 0) or 0),
                "amount": float(row.get("amount", 0) or 0),
            })
        return bars
    except Exception as exc:
        logger.warning("[tickflow] %s K线获取失败: %s", code, exc)
        return []


def fetch_klines_as_bars(code: str, count: int = 300) -> list[Any]:
    """从 TickFlow 取日 K 线，返回 KLineBar 列表（经 kline_from_mootdx 转换）。

    返回的 bars 与 astock.kline → kline_from_mootdx 的 bars 格式一致，
    可直接喂给 kline_rebuild._get_kline_bars 的调用方。
    """
    from data.mappers import kline_from_mootdx
    raw = fetch_klines(code, count)
    if not raw:
        return []
    return list(kline_from_mootdx(code, raw).bars)
