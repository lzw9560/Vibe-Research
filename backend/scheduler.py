# -*- coding: utf-8 -*-
"""后台调度器 —— 盘后预计算 + 持仓定时刷新。"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger("vibe-research")


# ============================================================================
# LimitUp 盘后预计算调度器
# ============================================================================


async def _precompute_limitup_async() -> None:
    """后台线程：预计算最近 3 个交易日的基因得分 + STI + 竞价选股 + 复盘报告。"""
    try:
        import limitup_screener as _ls
        import limitup_sti as _ls_sti
        import auction_screener as _asc
        import daily_review as _dr

        for back in range(3):
            d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y%m%d")
            await _ls.get_screener_result(d[:4] + "-" + d[4:6] + "-" + d[6:])

        # STI 预计算（独立容错：失败不阻塞基因选股器）
        try:
            engine = _ls_sti.get_sti_engine()
            for back in range(3):
                d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                engine.precompute_daily(d)
        except Exception as e:
            logger.warning("[limitup_sti] STI 预计算失败（不影响主流程）: %s", e)

        # 竞价选股预计算（独立容错：失败不阻塞主流程）
        try:
            for back in range(3):
                d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                _asc.get_screener().precompute_daily(d)
        except Exception as e:
            logger.warning("[auction_screener] 竞价选股预计算失败（不影响主流程）: %s", e)

        # 复盘报告预计算（独立容错：失败不阻塞主流程）
        try:
            for back in range(3):
                d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                _dr.get_reviewer().precompute_daily(d)
        except Exception as e:
            logger.warning("[daily_review] 复盘报告预计算失败（不影响主流程）: %s", e)

    except Exception as e:
        logger.warning("[limitup] 预计算失败: %s", e)


def _precompute_limitup() -> None:
    """同步兼容层：在线程中运行异步预计算。"""
    try:
        asyncio.run(_precompute_limitup_async())
    except Exception as e:
        logger.warning("[limitup] 预计算失败: %s", e)


def _start_limitup_scheduler() -> None:
    """每天 15:30-15:35 触发一次预计算（盘后 5 分钟，数据稳定）。"""
    import limitup_screener as _ls

    def _loop() -> None:
        while True:
            time.sleep(60)  # 每分钟检查一次
            now = datetime.now(_ls.BEIJING_TZ)
            if now.hour == 15 and now.minute >= 30 and now.minute <= 35:
                threading.Thread(target=_precompute_limitup, daemon=True).start()

    threading.Thread(target=_loop, daemon=True).start()


def start_limitup_scheduler() -> None:
    """启动 LimitUp 预计算调度器（仅在环境变量开启时）。"""
    if os.getenv("LIMITUP_PRECOMPUTE", "false").lower() == "true":
        _start_limitup_scheduler()


# ============================================================================
# 持仓定时刷新调度器
# ============================================================================


def start_portfolio_scheduler(interval_seconds: int = 1800) -> None:
    """启动持仓数据定时刷新调度器。

    Args:
        interval_seconds: 刷新间隔（秒），默认 1800（30 分钟）。
    """
    import portfolio as pf

    pf.start_scheduler(interval_seconds)
