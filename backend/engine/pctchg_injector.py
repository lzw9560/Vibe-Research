# -*- coding: utf-8 -*-
"""S204 R14 T1b: baostock cache bars 无 pctChg → harness 层注入计算值。

baostock_kline_cache.json bar keys=[date,open,high,low,close,volume,amount]——无 pctChg。
`is_unbuyable_next_bar` (bar_utils.py:62 `_bar_get(nb,"pctChg",0.0)`) 对一字涨停返 0.0 < threshold →
误判可买，污染 ALL backtest returns。本模块 harness 层 enrich（不动 bar_utils 源码，决策#12）。

注入值 `pctChg=(close[d]-close[d-1])/close[d-1]*100`（可复算非臆造）。首日无前收返 0.0。
fallback 方案——优先 `refresh_kline_cache.py` 全量刷新 cache 补 baostock 原值（T1a），本模块是 stale cache 回退。
"""
from __future__ import annotations


def enrich_pctchg(bars: list[dict]) -> list[dict]:
    """给 baostock cache bars 注入 pctChg（immutable，返新 list）。

    Args:
        bars: baostock cache bar dict list（按 date asc），每 bar 至少有 close。

    Returns:
        新 list，每 bar 加 pctChg 键（**已有则保留原值不覆盖**——baostock 原值优先）。原 bars 不修改。

    注入值：``pctChg = (close[d] - close[d-1]) / close[d-1] * 100``。
    首日无前收 → 0.0（不臆造）。除权日 close[d-1]≠preclose → 与 baostock 原值微小差异，
    但一字板 +10% 阈值 9.8%（有容差）不受影响。
    """
    out: list[dict] = []
    prev_close: float | None = None
    for b in bars:
        close = b.get("close")
        if prev_close is not None and prev_close != 0 and close is not None:
            try:
                pct = (float(close) - float(prev_close)) / float(prev_close) * 100
            except (TypeError, ValueError, ZeroDivisionError):
                pct = 0.0
        else:
            pct = 0.0
        # 已有 pctChg（baostock 原值）保留不覆盖；缺则注入计算值
        enriched = {**b, "pctChg": b.get("pctChg", round(pct, 4))}
        out.append(enriched)
        prev_close = float(close) if close is not None else prev_close
    return out
