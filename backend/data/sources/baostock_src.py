# -*- coding: utf-8 -*-
"""baostock 数据源封装（S167）。

baostock 证券宝（无 IP 限制，免防封）。历史可回测 K 线 + 财报。本模块封装
项目用到的 baostock 接口，供 scheduled_tasks + tools 复用（去重 S152 harness 内联副本）。

**单次 login**：baostock login 状态是进程全局的；本模块用模块级 flag 保证一次 login，
避免 per-call 重登（S152 实测 per-call 840 次登录拖垮）。login 失败 raise
DependencyMissing（复用 _common 范式，下游惯用降级）。

工程底线：无臆造——缺数据返 []，不补默认值。baostock 端点本身免费不限流，无需熔断。
"""
from __future__ import annotations

import logging
from typing import Any

from data.sources._common import DependencyMissing

logger = logging.getLogger("vibe-research")

_BS_READY = False


def ensure_login() -> None:
    """单次 baostock login（进程级，幂等）。失败 raise DependencyMissing。"""
    global _BS_READY
    if _BS_READY:
        return
    import baostock as bs  # noqa: PLC0415
    rs = bs.login()
    if rs.error_code != "0":
        raise DependencyMissing(f"baostock login 失败: {rs.error_code} {rs.error_msg}")
    _BS_READY = True


def _six_to_baostock(code: str) -> str:
    """6 位 A 股 code → baostock 9 位（sh./sz. 前缀）。

    复刻 S152 harness：6/9 开头 sh（沪市主板/科创板）否则 sz（深市/创业板）。
    北交所（8/4 开头）baostock 暂不支持，仍按 sz 映射（返空自然处理，不臆造）。
    """
    return f"sh.{code}" if code[0] in "689" else f"sz.{code}"


def fetch_5min_bars(code: str, start: str, end: str) -> list[dict[str, Any]]:
    """baostock 5min K 线（qfq 前复权）。

    Args:
        code: 6 位裸 code。
        start/end: 'YYYY-MM-DD'（end 含，baostock 区间闭）。

    返 [{date, time, open, high, low, close, volume}, ...]。缺数据/异常返 []（不臆造）。
    login 单次（ensure_login，不 per-call 重登）。
    """
    try:
        ensure_login()
    except DependencyMissing as e:
        logger.warning("[baostock] login 不可用: %s", e)
        return []
    import baostock as bs  # noqa: PLC0415
    bc = _six_to_baostock(code)
    bars: list[dict[str, Any]] = []
    try:
        rs = bs.query_history_k_data_plus(
            bc, "date,time,open,high,low,close,volume",
            start_date=start, end_date=end, frequency="5", adjustflag="2",
        )
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            bars.append({
                "date": row[0], "time": row[1],
                "open": float(row[2]), "high": float(row[3]),
                "low": float(row[4]), "close": float(row[5]),
                "volume": float(row[6]) if row[6] else 0.0,
            })
    except Exception as e:  # noqa: BLE001
        logger.warning("[baostock] fetch_5min_bars %s %s~%s 失败: %s", code, start, end, e)
        return []
    return bars
