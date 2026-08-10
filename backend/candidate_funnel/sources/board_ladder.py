# -*- coding: utf-8 -*-
"""R1 连板梯队（B2）。聚合涨停四池 → 无个股名指标（合规）。

S049 B：个股 IndicatorSet 不再带市场级三率（封板率/炸板率/晋级率）——
它们来自全市场聚合（同日所有股票同值），塞个股无信息量。个股只留 consec_boards。
市场级数据由 _fetch_market_emotion 统一展示（简报市场情绪区）。

`fetch_board_ladder` 现只返 lianban_stocks（供 build_indicator_set 按码匹配 consec_boards）。
`get_market_emotion_raw` 是全市场情绪的 TTL 缓存包装，供 _fetch_market_emotion 与
STI engine 复用同一份 emotion（避免重复外调触发限流，D6 采集去重共用）。
"""

from __future__ import annotations

import astock  # noqa: F401
import time

_EMOTION_TTL = 300  # 5 分钟；全站共享，省数据源压力
_emotion_cache: dict[str, tuple[float, dict]] = {}


def get_market_emotion_raw(date: str) -> dict:
    """取当日市场情绪原始聚合（含三率/ladder/涨跌停家数/lianban_stocks）。

    TTL 缓存：同日内多调用（_fetch_market_emotion + STI compute + funnel board）
    只外调一次 market._emotion。空结果不缓存（em_get 首调限流，下次请求直接重试）。
    返回 dict 形状同 market._emotion（空时为 {}）。
    """
    now = time.time()
    hit = _emotion_cache.get(date)
    if hit and now - hit[0] < _EMOTION_TTL:
        return hit[1]
    try:
        import market
        emo = market._emotion(date)
    except Exception:
        emo = {}
    if emo:  # 空结果不缓存（限流时下次重试）
        _emotion_cache[date] = (now, emo)
    return emo


def fetch_board_ladder(date: str) -> dict:
    """返回连板梯队数据（个股级仅 lianban_stocks，市场级三率已移简报）。

    返回 {lianban_stocks, missing?}。lianban_stocks 供 build_indicator_set
    按 code 匹配个股自身连板数（consec_boards）。
    """
    emo = get_market_emotion_raw(date)
    if not emo:
        return {"lianban_stocks": [], "missing": "连板梯队未取得"}
    return {"lianban_stocks": emo.get("lianban_stocks", [])}
