# -*- coding: utf-8 -*-
"""交易日历 — is_trading_day + load_trade_calendar + 已知节假日降级。

从 feishu_daily_push.py 拆出。保留 hithink-finance CLI 日历刷新逻辑。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── 交易日历 ───
CALENDAR_CACHE = Path("/tmp/trade_calendar.json")
CALENDAR_DATES: set[str] | None = None


def refresh_trade_calendar() -> None:
    """刷新交易日历缓存（每年9月到期，提前刷新）。"""
    try:
        subprocess.run(
            "hithink-finance market calendar "
            "--output /tmp/trade_calendar.json --format json 2>/dev/null",
            shell=True, capture_output=True, timeout=30,
        )
        logger.info("交易日历已刷新 -> %s", CALENDAR_CACHE)
    except subprocess.TimeoutExpired:
        logger.warning("刷新交易日历超时（30s）")
    except Exception as e:
        logger.warning("刷新交易日历异常: %s", e)


def load_trade_calendar() -> set[str]:
    """加载交易日历，返回 'YYYYMMDD' 集合。缓存过期自动刷新。"""
    global CALENDAR_DATES
    if CALENDAR_DATES is not None:
        return CALENDAR_DATES

    # 缓存文件不存在或超过30天则刷新
    need_refresh = False
    if not CALENDAR_CACHE.exists():
        need_refresh = True
    else:
        age = time.time() - CALENDAR_CACHE.stat().st_mtime
        if age > 30 * 86400:
            need_refresh = True

    if need_refresh:
        refresh_trade_calendar()

    if not CALENDAR_CACHE.exists():
        CALENDAR_DATES = set()
        return CALENDAR_DATES

    try:
        with open(CALENDAR_CACHE) as f:
            d = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取交易日历缓存失败: %s", e)
        CALENDAR_DATES = set()
        return CALENDAR_DATES

    items = d.get("data", {}).get("item", [])
    if not items:
        items = d.get("item", [])
    CALENDAR_DATES = set(it["date"] for it in items if "date" in it)
    return CALENDAR_DATES


# 已知节假日（日历未覆盖时的降级）
_KNOWN_HOLIDAYS = {
    # 2026年国庆中秋
    "20261001", "20261002", "20261003", "20261004",
    "20261005", "20261006", "20261007",
    # 2026年元旦（预估）
    "20260101", "20260102", "20260103",
    # 2026年春节（预估2月中）
    "20260215", "20260216", "20260217", "20260218",
    "20260219", "20260220", "20260221",
    # 2026年清明（预估4月初）
    "20260404", "20260405", "20260406",
    # 2026年五一（预估）
    "20260501", "20260502", "20260503",
    # 2026年端午（预估6月中）
    "20260619", "20260620", "20260621",
    # 2026年中秋（预估9月中）
    "20260914", "20260915", "20260916",
    # 2027年元旦（预估）
    "20270101", "20270102", "20270103",
    # 2027年春节（预估2月初）
    "20270207", "20270208", "20270209", "20270210",
    "20270211", "20270212", "20270213",
    # 2027年清明（预估4月初）
    "20270403", "20270404", "20270405",
    # 2027年五一（预估）
    "20270501", "20270502", "20270503",
    # 2027年端午（预估6月中）
    "20270618", "20270619", "20270620",
}


def is_trading_day(dt: datetime) -> bool:
    """判断是否为A股交易日。

    优先用交易日历，日历不覆盖该日期时用周末+已知节假日降级。
    """
    dates = load_trade_calendar()
    date_str = dt.strftime("%Y%m%d")

    # 日历覆盖该日期 → 直接查
    if dates and (date_str in dates or any(d > date_str for d in dates)):
        return date_str in dates

    # 日历不覆盖（日期在日历范围之外）→ 降级判断
    # 1. 周末不是交易日
    if dt.weekday() >= 5:
        return False
    # 2. 已知节假日不是交易日
    if date_str in _KNOWN_HOLIDAYS:
        return False
    # 3. 其他工作日视为交易日
    return True
