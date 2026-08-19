# -*- coding: utf-8 -*-
"""涨停池原始 dict source（S084 R2）。

复用 strategies.first_board_filter.fetch_zt_pool(date)（走 em_get 限流 + 24h 缓存），
按 code 建 {code: raw_dict} 映射供 DiagnosisCard.pool_item。
盘前取 T-1 昨日池（date=yesterday_date）；个股不在涨停池→pool_item=None。

防封底线：fetch_zt_pool 内部走 astock.em_zt_topic_pool → em_get（0.3s 限流 + circuit_breaker），
不裸调 requests。
"""
from __future__ import annotations


def fetch_zt_pool_map(date: str) -> dict[str, dict]:
    """返回 {code: 涨停池原始 dict}。走 em_get 限流（防封底线）。

    复用 first_board_filter.fetch_zt_pool(date)（已实现，走 em_get + 24h 缓存），
    返回 list[dict]，每项含 c(代码)/n(名)/lbc(连板数)/zbc(炸板次数)/fbt(首封时间)/
    zdp(涨幅%)/zje(涨停价)/hybk(行业)/p(涨停价)/fund(封单额) 等。
    按 c 建 {code: raw_dict} 映射。
    """
    try:
        from strategies.first_board_filter import fetch_zt_pool
        pool = fetch_zt_pool(date) or []
    except Exception:
        return {}
    return {str(p.get("c", "")): p for p in pool if p.get("c")}
