# -*- coding: utf-8 -*-
"""S066 §6 日历因子（PositionAdvisor 增强前置）。

仓位乘数按日历调仓：
- 周五 ×0.7（周末 gap 风险）
- 节前 3 日 ×0.5，节前最后 1 日 ×0.3（资金抽离）
- 周四 ×1.0（逆势涨停=强信号，不降仓）
- 节后第一日：跳空高开>3% → 红包确认（加仓），跳空低开>2% → 清退

数据源：backend/data/holidays.json（纯本地，零 API）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

_HOLIDAYS_PATH = Path(__file__).resolve().parent.parent / "data" / "holidays.json"
_HOLIDAYS_CACHE: dict | None = None


def _load_holidays() -> dict:
    global _HOLIDAYS_CACHE
    if _HOLIDAYS_CACHE is not None:
        return _HOLIDAYS_CACHE
    try:
        _HOLIDAYS_CACHE = json.loads(_HOLIDAYS_PATH.read_text(encoding="utf-8"))
    except Exception:
        _HOLIDAYS_CACHE = {}
    return _HOLIDAYS_CACHE


def is_pre_holiday_last_day(date_str: str) -> bool:
    """date_str 是否节前最后交易日。"""
    h = _load_holidays()
    return date_str in h.get("pre_holiday_last_trading_day", [])


def is_post_holiday_first_day(date_str: str) -> bool:
    """date_str 是否节后第一交易日。"""
    h = _load_holidays()
    return date_str in h.get("post_holiday_first_trading_day", [])


def is_pre_holiday(date_str: str, days: int = 3) -> bool:
    """date_str 是否在节前 N 日内（检查 date_str 后 days 个交易日是否有长假）。

    简化实现：检查 date_str 是否在 pre_holiday_last_trading_day 前 days 个日历日内。
    """
    h = _load_holidays()
    last_days = h.get("pre_holiday_last_trading_day", [])
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return False
    for ld in last_days:
        try:
            ld_dt = datetime.strptime(ld, "%Y-%m-%d")
            if 0 < (ld_dt - target).days <= days:
                return True
        except ValueError:
            continue
    return False


def calendar_factor(signal_date: str) -> tuple[float, str]:
    """返回 (仓位乘数, 原因)。

    优先级（spec §16.12 信号优先级）：
    1. 节前最后 1 日 → ×0.3
    2. 节前 3 日 → ×0.5
    3. 周五 → ×0.7
    4. 周四 → ×1.0（不降仓，逆势涨停=强信号）
    5. 其他 → ×1.0

    跨层冲突取更保守（min），不是叠加。
    """
    if is_pre_holiday_last_day(signal_date):
        return 0.3, "节前最后1日降仓70%（留节后红包窗口）"
    if is_pre_holiday(signal_date, days=3):
        return 0.5, "节前3日降仓50%"
    try:
        dow = datetime.strptime(signal_date, "%Y-%m-%d").weekday()
    except ValueError:
        return 1.0, ""
    if dow == 4:
        return 0.7, "周五周末gap风险降仓30%"
    if dow == 3:
        return 1.0, "周四逆势涨停=强信号（不降仓）"
    return 1.0, ""


def post_holiday_confirmation(open_pct: float, prev_close: float) -> tuple[str, float, str]:
    """节后红包确认策略（spec §6.2）。

    open_pct: 当日开盘价
    prev_close: 节前最后交易日收盘价
    返回 (signal, 仓位乘数, 原因)
    - signal: "red_envelope" | "capital_flight" | "normal"
    """
    if prev_close <= 0:
        return "normal", 0.5, "节后首日，无前收盘参考，正常处理仓位×0.5"
    gap_pct = (open_pct - prev_close) / prev_close * 100
    if gap_pct > 3.0:
        return "red_envelope", 0.6, f"节后红包确认（跳空高开{gap_pct:.1f}%），节前仓位0.3+追加0.3=总0.6"
    if gap_pct < -2.0:
        return "capital_flight", 0.0, f"资金出逃（跳空低开{gap_pct:.1f}%），节前候选清退"
    return "normal", 0.5, f"节后首日正常处理（gap {gap_pct:.1f}%），仓位×0.5"
