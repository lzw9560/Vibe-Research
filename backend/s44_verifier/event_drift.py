# -*- coding: utf-8 -*-
"""S204 R11 T5b: event edge base_rate=0 drift fix。

event edge 的 null 是 base_rate=0（单样本 mean>0）→ 牛市 drift 假阳性
（所有股票正收益，event mean>0 但非真 edge）。本模块两样本修正：
``drift_adjusted = event_mean - universe_mean``（减市场 drift）。

方案①（保 event 语义 + 减 drift，对抗审 wjiq1hkmz CRITICAL + 用户同意）：
event edge 也算 universe_by_day，``drift_adjusted = event_mean - universe_mean``。
``is_drift_inflated=True`` 表示 event_mean>0 但 drift_adjusted≤0（漂移假阳性）
→ verifier 降级 non-robust（防牛市假阳性 robust_edge）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class EventDriftResult:
    event_mean: float
    universe_mean: Optional[float]  # None if no universe provided
    drift_adjusted_mean: Optional[float]  # None if no universe
    is_drift_inflated: bool  # True if event_mean>0 but drift_adjusted<=0


def adjust_event_drift(
    event_returns: "np.ndarray | list[float]",
    universe_by_day: "dict[str, list[float]] | None",
) -> EventDriftResult:
    """两样本修正 event edge 的市场 drift。

    Args:
        event_returns: event picks 的 returns（may contain NaN）。
        universe_by_day: 同日全市场 universe returns ``{date: [returns]}``。
            None 或空 → 无法修正，返 ``universe_mean=None``（caller 回退单样本 mean>0）。

    Returns:
        EventDriftResult: ``event_mean``、``universe_mean``、``drift_adjusted_mean``、
        ``is_drift_inflated``（event_mean>0 但 drift_adjusted≤0）。

    不可变：frozen dataclass，纯函数（同输入→同输出）。
    """
    r = np.asarray(event_returns, dtype=float)
    r = r[~np.isnan(r)]
    event_mean = float(r.mean()) if r.size else 0.0

    if not universe_by_day:
        return EventDriftResult(
            event_mean=event_mean, universe_mean=None,
            drift_adjusted_mean=None, is_drift_inflated=False,
        )

    univ_returns: list[float] = []
    for rets in universe_by_day.values():
        univ_returns.extend(rets)
    u = np.asarray(univ_returns, dtype=float)
    u = u[~np.isnan(u)]
    universe_mean = float(u.mean()) if u.size else 0.0

    drift_adjusted = event_mean - universe_mean
    is_inflated = (event_mean > 0) and (drift_adjusted <= 0)
    return EventDriftResult(
        event_mean=event_mean, universe_mean=universe_mean,
        drift_adjusted_mean=drift_adjusted, is_drift_inflated=is_inflated,
    )
