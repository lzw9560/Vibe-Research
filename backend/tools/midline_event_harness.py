# -*- coding: utf-8 -*-
"""S169 中线 event 共享 harness——build_return_series + run_event_verdict。

PEAD/摘帽/重组等中线 event edge 复用。event edge 用 day-clustered t-test
（mean event-return>0 after costs）非 lift/permutation（§44v1 category mismatch 修正）。

grill 修复：
- #1 日期范围过滤：pub_date 在 kline_cache 窗口外的事件跳过（49% 事件 crash 修）
- #4 日历下一交易日：pub_date 非交易日时用 calendar_next 找 D+1 bar（60% 事件 fix）
- exit bar volume guard：entry + exit 都 volume>0（停牌跳过）
- #5 input_files：wire_verdict 传 input 文件 hash（forecast_reports/kline_cache 复现锚点）
- n_comparisons：多 horizon/arm 多重比较校正（BH K=15，verifier event 分支已加 p_bonf/p_bh）
"""
from __future__ import annotations

import bisect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tools._s44_wire import wire_verdict  # noqa: E402


def _calendar_next(calendar: list[str], pub_date: str) -> str | None:
    """日历中 pub_date 后第一交易日（bisect_right）。pub_date 非交易日时找下一个。"""
    idx = bisect.bisect_right(calendar, pub_date)
    if idx < len(calendar):
        return calendar[idx]
    return None


def build_return_series(
    events: list[dict],
    kline_cache: dict,
    calendar: list[str],
    horizon: int,
    cost_pct: float = 0.0070,
) -> tuple[list[float], list[str], dict]:
    """构建 event edge return series（decimal 制，扣 cost）。

    return = exit_close / entry_open - 1.0 - cost_pct
    date = event pub_date（day-clustering key）

    guards（grill #1/#4 修复）：
    - 日期范围过滤：pub_date 在 cache 日期范围外跳过（#1，49% 事件 crash 修）
    - calendar_next 找 D+1 entry bar（#4，pub_date 非交易日 60% 事件 fix）
    - entry bar volume>0（停牌跳过）
    - exit bar 存在（horizon 不够跳过）
    - exit bar volume>0
    """
    if not calendar:
        return [], [], {"n_events": len(events), "n_valid": 0, "n_out_of_range": 0,
                         "n_no_entry": 0, "n_no_exit": 0, "n_halted": 0}
    cache_min, cache_max = calendar[0], calendar[-1]
    returns: list[float] = []
    dates: list[str] = []
    n_out_of_range = n_no_entry = n_no_exit = n_halted = 0

    for ev in events:
        pub_date = ev.get("pub_date") or ev.get("pubDate")
        if not pub_date:
            continue
        # #1 日期范围过滤
        if pub_date < cache_min or pub_date >= cache_max:
            n_out_of_range += 1
            continue
        code = ev.get("code")
        bars = kline_cache.get(code)
        if not bars:
            continue
        # #4 calendar_next 找 D+1 entry bar
        entry_date = _calendar_next(calendar, pub_date)
        if entry_date is None:
            n_no_entry += 1
            continue
        entry_idx = next((i for i, b in enumerate(bars) if b.get("date") == entry_date), None)
        if entry_idx is None:
            n_no_entry += 1
            continue
        entry_bar = bars[entry_idx]
        # entry volume guard
        try:
            if float(entry_bar.get("volume", 0) or 0) <= 0:
                n_halted += 1
                continue
            entry_open = float(entry_bar.get("open", 0) or 0)
        except (TypeError, ValueError):
            n_halted += 1
            continue
        if entry_open <= 0:
            n_halted += 1
            continue
        # exit bar（horizon 后）
        exit_idx = entry_idx + horizon
        if exit_idx >= len(bars):
            n_no_exit += 1
            continue
        exit_bar = bars[exit_idx]
        try:
            if float(exit_bar.get("volume", 0) or 0) <= 0:
                n_halted += 1
                continue
            exit_close = float(exit_bar.get("close", 0) or 0)
        except (TypeError, ValueError):
            n_halted += 1
            continue
        if exit_close <= 0:
            n_halted += 1
            continue
        ret = exit_close / entry_open - 1.0 - cost_pct
        returns.append(ret)
        dates.append(pub_date)

    guards = {
        "n_events": len(events),
        "n_valid": len(returns),
        "n_out_of_range": n_out_of_range,
        "n_no_entry": n_no_entry,
        "n_no_exit": n_no_exit,
        "n_halted": n_halted,
    }
    return returns, dates, guards


def run_event_verdict(
    *,
    line_id: str,
    events: list[dict],
    kline_cache: dict,
    calendar: list[str],
    horizon: int,
    cost: float = 0.0070,
    frozen_commit: str,
    n_comparisons: int = 1,
    params: dict | None = None,
    input_files: dict[str, str] | None = None,
) -> object:
    """跑 event edge verdict：build_return_series → wire_verdict(edge_type="event")。

    edge_type="event" 不传 survivors/universe（避免 category mismatch）。
    verify event 分支 day_clustered_t_test + p_bonf/p_bh（grill #3 多重比较校正）。
    """
    returns, dates, guards = build_return_series(
        events, kline_cache, calendar, horizon, cost,
    )
    return wire_verdict(
        line_id=line_id,
        returns=returns,
        edge_type="event",
        dates=dates,
        frozen_commit=frozen_commit,
        round_trip_cost=cost,
        n_comparisons=n_comparisons,
        script="tools/midline_event_harness.py",
        params={"horizon": horizon, **guards, **(params or {})},
        input_files=input_files,
    )
