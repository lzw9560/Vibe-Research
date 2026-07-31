"""Calendar feature specs — S018 T0 slice.

Calendar features (holiday / option delivery / meeting period dummies).
All features are computed locally from hard-coded public calendars and
pure date arithmetic; no network access.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from predict.features.registry import FeatureSpec, Registry


# ── Module-level immutable spec declarations ────────────────────────

CALENDAR_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="is_holiday",
        source="computed",
        category="calendar",
        availability_offset=0,
        stage="s2",
        compliance_flag="ok",
        description="A股节假日哑变量（含周末），基于公开交易日历硬编码2024-2026",
    ),
    FeatureSpec(
        name="is_delivery_day",
        source="computed",
        category="calendar",
        availability_offset=0,
        stage="s2",
        compliance_flag="ok",
        description="期权交割日哑变量：ETF期权每月第四个周三 + 股指期货每月第三个周五",
    ),
    FeatureSpec(
        name="meeting_dummy",
        source="computed",
        category="calendar",
        availability_offset=0,
        stage="s2",
        compliance_flag="ok",
        description="重要会议期间哑变量：两会(3/4-3/11) + 中央经济工作会议(12/11-12/12)",
    ),
)


# ── Registration ────────────────────────────────────────────────────

def register_calendar(registry: Registry) -> None:
    """Register all calendar FeatureSpecs into the given Registry.

    Raises:
        KeyError: If any feature name is already registered.
    """
    for spec in CALENDAR_SPECS:
        registry.register(spec)


# ── Pure computation (no side effects, no network) ──────────────────

# 节假日表为已知公开事实，硬编码 2024-2026，年度更新
_HOLIDAY_DATES: frozenset[str] = frozenset({
    # 2024
    "2024-01-01",
    "2024-02-10", "2024-02-11", "2024-02-12", "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16", "2024-02-17",
    "2024-04-04", "2024-04-05", "2024-04-06",
    "2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04", "2024-05-05",
    "2024-06-10",
    "2024-09-15", "2024-09-16", "2024-09-17",
    "2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04", "2024-10-05", "2024-10-06", "2024-10-07",
    # 2025
    "2025-01-01",
    "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31", "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",
    "2025-04-04", "2025-04-05", "2025-04-06",
    "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
    "2025-05-31",
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04", "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",
    # 2026
    "2026-01-01",
    "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23", "2026-02-24",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19",
    "2026-09-27", "2026-09-28", "2026-09-29",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",
})


def is_holiday(date_str: str) -> bool:
    """Return True if *date_str* is a non-trading day (holiday or weekend).

    Parameters
    ----------
    date_str:
        ISO format ``YYYY-MM-DD``.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return True
    return date_str in _HOLIDAY_DATES


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the n-th occurrence of *weekday* (Mon=0 … Sun=6) in *month*.

    Pure helper; no side effects.
    """
    # Find the first day of the month that matches the weekday
    first = date(year, month, 1)
    # Days until first occurrence of weekday in this month
    delta = (weekday - first.weekday()) % 7
    first_occurrence = first + timedelta(days=delta)
    # Add (n-1) weeks
    return first_occurrence + timedelta(weeks=n - 1)


def is_option_delivery_day(date_str: str) -> bool:
    """Return True if *date_str* is an delivery day for ETF options (4th Wed)
    or stock-index futures (3rd Fri).

    Parameters
    ----------
    date_str:
        ISO format ``YYYY-MM-DD``.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    # ETF options: 4th Wednesday
    etf_delivery = _nth_weekday(d.year, d.month, 2, 4)
    if d == etf_delivery:
        return True
    # Stock index futures: 3rd Friday
    futures_delivery = _nth_weekday(d.year, d.month, 4, 3)
    if d == futures_delivery:
        return True
    return False


def is_meeting_period(date_str: str) -> bool:
    """Return True if *date_str* falls within a major meeting period.

    Currently covers:
    - Two Sessions: approx. March 4-11
    - Central Economic Work Conference: approx. December 11-12

    Parameters
    ----------
    date_str:
        ISO format ``YYYY-MM-DD``.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    # Two Sessions: March 4-11
    if d.month == 3 and 4 <= d.day <= 11:
        return True
    # Central Economic Work Conference: December 11-12
    if d.month == 12 and 11 <= d.day <= 12:
        return True
    return False
