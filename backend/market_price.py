# -*- coding: utf-8 -*-
"""S038：市价拉价——settled 流转时自动填 exit_price 的行情源桥接。

拉价是"尽力而为"的增强：失败返 None（不抛），由调用方 fallback 到
S034 既有"缺价跳过"路径。行情源走 astock.tencent_quote（腾讯源，非
em_get，无封 IP 风险）。
"""
from __future__ import annotations

import logging

import astock
from data.mappers import quote_from_tencent

logger = logging.getLogger("vibe-research")


def fetch_current_price(code: str) -> float | None:
    """调 tencent_quote 拉当前价。失败返 None（尽力而为，不抛）。

    raw dict → mappers.quote_from_tencent → Quote.price。任一步异常/空 → None。
    """
    try:
        raw = astock.tencent_quote([code]) or {}
        model = quote_from_tencent(code, raw.get(code, {}))
        return model.price or None
    except Exception as e:  # noqa: BLE001 — 拉价是增强，失败兜底
        logger.debug("[market_price] 拉价失败 %s: %s", code, e)
        return None
