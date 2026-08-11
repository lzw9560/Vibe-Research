# -*- coding: utf-8 -*-
"""S057：八项标准三态判定纯函数。

DSA `SEAL_PLATE_ARCHITECTURE.md` §5 八项标准原型：
①流通市值 30-150 亿 ②换手 5-20% ③量比≥1.5 ④10:30 前封板 ⑤开板≤1
⑥封单>流通市值 1% ⑦题材热度 TOP10 ⑧低位首板或平台突破。

三态判定（pass/fail/missing）——缺失数据不参与计数，守不臆造红线。
未过数≥3 → 漏斗最终得分封顶 55（在 funnel.py 接入处实施）。
"""

from __future__ import annotations

from typing import Any

from candidate_funnel.models import (
    EightStandardItem,
    EightStandardResult,
    IndicatorSet,
)
from candidate_funnel.thresholds import (
    EIGHT_STANDARD_FLOAT_CAP_MAX,
    EIGHT_STANDARD_FLOAT_CAP_MIN,
    EIGHT_STANDARD_HOT_SECTOR_TOPN,
    EIGHT_STANDARD_MAX_REOPENS,
    EIGHT_STANDARD_SEAL_RATIO_MIN,
    EIGHT_STANDARD_SEAL_TIME_HOUR,
    EIGHT_STANDARD_SEAL_TIME_MINUTE,
    EIGHT_STANDARD_TURNOVER_MAX,
    EIGHT_STANDARD_TURNOVER_MIN,
    EIGHT_STANDARD_VOL_RATIO_MIN,
)


def _fmt_money(v: float | None) -> str | None:
    """流通市值（元）→ 亿单位字符串。None→None。"""
    if v is None:
        return None
    return f"{v / 1e8:.2f}亿"


def _fmt_pct(v: float | None, unit: str = "%") -> str | None:
    if v is None:
        return None
    return f"{v}{unit}"


def _check_float_cap(ind: IndicatorSet) -> EightStandardItem:
    """①流通市值 30-150 亿。"""
    fmc = ind.float_market_cap
    if fmc is None:
        return EightStandardItem(
            key="1",
            label="流通市值 30-150 亿",
            status="missing",
            actual=None,
            expected=f"{EIGHT_STANDARD_FLOAT_CAP_MIN / 1e8:.0f}-{EIGHT_STANDARD_FLOAT_CAP_MAX / 1e8:.0f}亿",
            note="流通市值未取得",
        )
    ok = EIGHT_STANDARD_FLOAT_CAP_MIN <= fmc <= EIGHT_STANDARD_FLOAT_CAP_MAX
    return EightStandardItem(
        key="1",
        label="流通市值 30-150 亿",
        status="pass" if ok else "fail",
        actual=_fmt_money(fmc),
        expected=f"{EIGHT_STANDARD_FLOAT_CAP_MIN / 1e8:.0f}-{EIGHT_STANDARD_FLOAT_CAP_MAX / 1e8:.0f}亿",
    )


def _check_turnover(ind: IndicatorSet) -> EightStandardItem:
    """②换手 5-20%。"""
    t = ind.turnover_pct
    if t is None:
        return EightStandardItem(
            key="2",
            label="换手 5-20%",
            status="missing",
            actual=None,
            expected=f"{EIGHT_STANDARD_TURNOVER_MIN}-{EIGHT_STANDARD_TURNOVER_MAX}%",
            note="换手未取得",
        )
    ok = EIGHT_STANDARD_TURNOVER_MIN <= t <= EIGHT_STANDARD_TURNOVER_MAX
    return EightStandardItem(
        key="2",
        label="换手 5-20%",
        status="pass" if ok else "fail",
        actual=_fmt_pct(t),
        expected=f"{EIGHT_STANDARD_TURNOVER_MIN}-{EIGHT_STANDARD_TURNOVER_MAX}%",
    )


def _check_vol_ratio(ind: IndicatorSet) -> EightStandardItem:
    """③量比≥1.5。"""
    v = ind.vol_ratio
    if v is None:
        return EightStandardItem(
            key="3",
            label=f"量比≥{EIGHT_STANDARD_VOL_RATIO_MIN}",
            status="missing",
            actual=None,
            expected=f"≥{EIGHT_STANDARD_VOL_RATIO_MIN}",
            note="量比未取得",
        )
    ok = v >= EIGHT_STANDARD_VOL_RATIO_MIN
    return EightStandardItem(
        key="3",
        label=f"量比≥{EIGHT_STANDARD_VOL_RATIO_MIN}",
        status="pass" if ok else "fail",
        actual=_fmt_pct(v, ""),
        expected=f"≥{EIGHT_STANDARD_VOL_RATIO_MIN}",
    )


def _check_seal_time(market_ctx: dict) -> EightStandardItem:
    """④10:30 前封板。依赖涨停池原始数据 first_seal_time。"""
    t = market_ctx.get("first_seal_time")
    if t is None:
        return EightStandardItem(
            key="4",
            label=f"{EIGHT_STANDARD_SEAL_TIME_HOUR}:{EIGHT_STANDARD_SEAL_TIME_MINUTE:02d}前封板",
            status="missing",
            actual=None,
            expected=f"≤{EIGHT_STANDARD_SEAL_TIME_HOUR}:{EIGHT_STANDARD_SEAL_TIME_MINUTE:02d}",
            note="首次封板时间未取得",
        )
    # t 形如 "09:35" 或 "0935" 或 HH:MM 字符串
    ok = _time_within(t, EIGHT_STANDARD_SEAL_TIME_HOUR, EIGHT_STANDARD_SEAL_TIME_MINUTE)
    return EightStandardItem(
        key="4",
        label=f"{EIGHT_STANDARD_SEAL_TIME_HOUR}:{EIGHT_STANDARD_SEAL_TIME_MINUTE:02d}前封板",
        status="pass" if ok else "fail",
        actual=str(t),
        expected=f"≤{EIGHT_STANDARD_SEAL_TIME_HOUR}:{EIGHT_STANDARD_SEAL_TIME_MINUTE:02d}",
    )


def _time_within(t: Any, hour: int, minute: int) -> bool:
    """判时间字符串是否 ≤ HH:MM。"""
    s = str(t).strip().replace(":", "")
    if not s.isdigit():
        return False
    if len(s) == 4:
        h, m = int(s[:2]), int(s[2:])
    elif len(s) >= 3:
        h, m = int(s[:-2]), int(s[-2:])
    else:
        return False
    return (h, m) <= (hour, minute)


def _check_reopens(market_ctx: dict) -> EightStandardItem:
    """⑤开板次数≤1。依赖涨停池 open_count。"""
    r = market_ctx.get("open_count")
    if r is None:
        return EightStandardItem(
            key="5",
            label=f"开板次数≤{EIGHT_STANDARD_MAX_REOPENS}",
            status="missing",
            actual=None,
            expected=f"≤{EIGHT_STANDARD_MAX_REOPENS}",
            note="开板次数未取得",
        )
    ok = r <= EIGHT_STANDARD_MAX_REOPENS
    return EightStandardItem(
        key="5",
        label=f"开板次数≤{EIGHT_STANDARD_MAX_REOPENS}",
        status="pass" if ok else "fail",
        actual=str(r),
        expected=f"≤{EIGHT_STANDARD_MAX_REOPENS}",
    )


def _check_seal_ratio(ind: IndicatorSet) -> EightStandardItem:
    """⑥封单>流通市值 1%。依赖 seal_amount + float_market_cap。"""
    sa = ind.seal_amount
    fmc = ind.float_market_cap
    if sa is None or fmc is None:
        return EightStandardItem(
            key="6",
            label="封单>流通市值1%",
            status="missing",
            actual=None,
            expected=f">{EIGHT_STANDARD_SEAL_RATIO_MIN * 100:.0f}%",
            note="封单或流通市值未取得",
        )
    ratio = sa / fmc if fmc > 0 else 0.0
    ok = ratio > EIGHT_STANDARD_SEAL_RATIO_MIN
    return EightStandardItem(
        key="6",
        label="封单>流通市值1%",
        status="pass" if ok else "fail",
        actual=f"{ratio * 100:.2f}%",
        expected=f">{EIGHT_STANDARD_SEAL_RATIO_MIN * 100:.0f}%",
    )


def _check_hot_sector(ind: IndicatorSet, market_ctx: dict) -> EightStandardItem:
    """⑦题材热度 TOP10。复用板块热度数据。"""
    hot_sectors = market_ctx.get("hot_sectors") or []
    concepts = ind.concepts or []
    if not hot_sectors:
        return EightStandardItem(
            key="7",
            label=f"题材热度TOP{EIGHT_STANDARD_HOT_SECTOR_TOPN}",
            status="missing",
            actual=None,
            expected=f"板块在TOP{EIGHT_STANDARD_HOT_SECTOR_TOPN}",
            note="板块热度数据未取得",
        )
    if not concepts:
        return EightStandardItem(
            key="7",
            label=f"题材热度TOP{EIGHT_STANDARD_HOT_SECTOR_TOPN}",
            status="missing",
            actual=None,
            expected=f"板块在TOP{EIGHT_STANDARD_HOT_SECTOR_TOPN}",
            note="个股概念未取得",
        )
    top_names = {s.get("name") if isinstance(s, dict) else str(s) for s in hot_sectors[:EIGHT_STANDARD_HOT_SECTOR_TOPN]}
    ok = any(c in top_names for c in concepts)
    return EightStandardItem(
        key="7",
        label=f"题材热度TOP{EIGHT_STANDARD_HOT_SECTOR_TOPN}",
        status="pass" if ok else "fail",
        actual="/".join(concepts[:3]),
        expected=f"板块在TOP{EIGHT_STANDARD_HOT_SECTOR_TOPN}",
    )


def _check_price_position(ind: IndicatorSet, market_ctx: dict) -> EightStandardItem:
    """⑧低位首板或平台突破。依赖 consec_boards + ma20（平台突破近似）。"""
    cb = ind.consec_boards
    ma20 = ind.ma20
    price = ind.price
    if cb is None and (ma20 is None or price is None):
        return EightStandardItem(
            key="8",
            label="低位首板或平台突破",
            status="missing",
            actual=None,
            expected="首板(boards=1) 或 价格突破 MA20",
            note="连板数/均线数据未取得",
        )
    # 低位首板：consec_boards == 1
    low_first = cb == 1
    # 平台突破：price > ma20（近似）
    breakout = (price is not None and ma20 is not None and price > ma20)
    ok = low_first or breakout
    actual_parts = []
    if cb is not None:
        actual_parts.append(f"连板{cb}")
    if price is not None and ma20 is not None:
        actual_parts.append(f"价vsMA20({'突破' if price > ma20 else '未破'})")
    return EightStandardItem(
        key="8",
        label="低位首板或平台突破",
        status="pass" if ok else "fail",
        actual=" / ".join(actual_parts) if actual_parts else None,
        expected="首板(boards=1) 或 价格突破 MA20",
    )


def check_eight_standards(
    ind: IndicatorSet,
    market_ctx: dict | None = None,
) -> EightStandardResult:
    """八项标准三态判定。

    ind: 个股 IndicatorSet（须含 turnover/vol_ratio/seal_amount/float_market_cap 等）
    market_ctx: 市场级数据（first_seal_time/open_count/hot_sectors）
    返回 EightStandardResult，含逐项 items + fail_count + missing_count。
    missing 不计入 fail_count（独立第三态，守不臆造红线）。
    """
    ctx = market_ctx or {}
    items = [
        _check_float_cap(ind),
        _check_turnover(ind),
        _check_vol_ratio(ind),
        _check_seal_time(ctx),
        _check_reopens(ctx),
        _check_seal_ratio(ind),
        _check_hot_sector(ind, ctx),
        _check_price_position(ind, ctx),
    ]
    fail_count = sum(1 for i in items if i.status == "fail")
    missing_count = sum(1 for i in items if i.status == "missing")
    return EightStandardResult(
        items=items,
        fail_count=fail_count,
        missing_count=missing_count,
    )
