"""Behavior / micro-structure feature specs — S018 R12 slice.

Short-term reversal, abnormal turnover, auction signal, yesterday limit-up
performance, and day-trip risk (hot-money seat profile). Pure computation
functions only — no I/O, no network side effects.

S3 auction / yesterday-limit-up live fetchers: TODO — data from astock.em_get
and limitup_sti, wired in S008.
"""

from __future__ import annotations

from predict.features.registry import FeatureSpec, Registry


# ── Module-level immutable spec declarations ────────────────────────

BEHAVIOR_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="short_term_reversal",
        source="computed",
        category="behavior",
        availability_offset=0,
        stage="s1",
        compliance_flag="ok",
        description=(
            "短期反转：过去1-5日累计收益（%）。A股最强负向因子之一，"
            "反映短期动量反转效应。"
        ),
    ),
    FeatureSpec(
        name="abnormal_turnover",
        source="computed",
        category="behavior",
        availability_offset=0,
        stage="s1",
        compliance_flag="ok",
        description=(
            "异常换手率/量比：当日换手率/成交量相对于近期均值的倍数。"
            "散户注意力代理变量，通常负向。"
        ),
    ),
    FeatureSpec(
        name="auction_signal",
        source="astock.em_get",
        category="behavior",
        availability_offset=0,
        stage="s3",
        compliance_flag="ok",
        description=(
            "集合竞价信号：9:15-9:25 竞价金额/高开幅度/竞价封单。"
            "次日开盘强领先信号，S3阶段解锁。"
            "TODO: S3竞价数据走 astock.em_get + limitup_sti，S008接。"
        ),
    ),
    FeatureSpec(
        name="yesterday_limit_today",
        source="limitup_sti",
        category="behavior",
        availability_offset=1,
        stage="s1",
        compliance_flag="ok",
        description=(
            "昨涨停今表现：前日涨停股票次日开盘/收盘表现及打板盈亏比。"
            "市场情绪温度计。"
            "TODO: 昨涨停池取数走 limitup_sti，S008接。"
        ),
    ),
    FeatureSpec(
        name="day_trip_risk",
        source="limitup_sti",
        category="behavior",
        availability_offset=1,
        stage="s1",
        compliance_flag="aggregate_only",
        description=(
            "游资一日游风险评分：基于龙虎榜席位聚合持仓周期画像。"
            "不依赖个体席位标签，只用聚合持仓天数。"
            "一日游参与过高=负向风险特征。"
        ),
    ),
)


# ── Registration ────────────────────────────────────────────────────

def register_behavior(registry: Registry) -> None:
    """Register all behavior FeatureSpecs into the given Registry.

    Raises:
        KeyError: If any feature name is already registered.
    """
    for spec in BEHAVIOR_SPECS:
        registry.register(spec)


# ── Pure computation (no side effects, no network) ──────────────────

def short_term_reversal_ret(bars: list[dict], window: int = 5) -> float | None:
    """Return the cumulative return (%) over the last *window* trading days.

    Formula: (close[-1] - close[-window-1]) / close[-window-1] * 100

    Parameters
    ----------
    bars:
        List of bar dicts ordered by ascending date. Each dict must contain
        a ``close`` key (float).
    window:
        Number of trading days to compute the cumulative return over.

    Returns
    -------
    float | None
        Cumulative return as a percentage, or ``None`` if insufficient bars or
        a ``close`` value is missing.
    """
    if len(bars) < window + 1:
        return None
    try:
        old = bars[-window - 1]["close"]
        new = bars[-1]["close"]
    except (KeyError, TypeError):
        return None
    if old is None or new is None:
        return None
    return (new - old) / old * 100


def abnormal_turnover_ratio(
    volumes: list[float | None], avg_window: int = 5
) -> float | None:
    """Compute the volume ratio (量比): today's volume / avg of past *avg_window* days.

    Parameters
    ----------
    volumes:
        Ordered list of daily volumes (ascending by date). ``None`` values are
        skipped when computing the historical average.
    avg_window:
        Number of prior days to average.

    Returns
    -------
    float | None
        The volume ratio, or ``None`` if insufficient data.
    """
    if len(volumes) < avg_window + 1:
        return None
    today = volumes[-1]
    if today is None:
        return None
    hist = volumes[-1 - avg_window : -1]
    valid = [v for v in hist if v is not None]
    if not valid:
        return None
    avg = sum(valid) / len(valid)
    return today / avg


def day_trip_risk_score(seat_records: list[dict]) -> float | None:
    """Compute a day-trip risk score from aggregated seat records.

    The score is the proportion of seats whose historical average hold_days
    is <= 1 (day-trip style). Records with ``None`` hold_days are ignored.

    Parameters
    ----------
    seat_records:
        List of dicts, each containing ``hold_days`` (int | None).

    Returns
    -------
    float | None
        Proportion of day-trip seats (0.0..1.0), or ``None`` if all
        hold_days are ``None`` or the list is empty.
    """
    if not seat_records:
        return None
    valid: list[int] = []
    for rec in seat_records:
        hd = rec.get("hold_days")
        if hd is not None:
            valid.append(hd)
    if not valid:
        return None
    day_trip_count = sum(1 for hd in valid if hd <= 1)
    return day_trip_count / len(valid)
