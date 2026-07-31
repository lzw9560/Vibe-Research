# -*- coding: utf-8 -*-
"""R1 连板梯队（B2）。聚合涨停四池 → 无个股名指标（合规）。"""

from __future__ import annotations

import astock  # noqa: F401


def fetch_board_ladder(date: str) -> dict:
    """返回市场级聚合 {seal_rate, bomb_rate, advance_rate, lianban_stocks, missing?}。"""
    try:
        import market
        emo = market._emotion(date)
    except Exception:
        return {
            "seal_rate": None,
            "bomb_rate": None,
            "advance_rate": None,
            "lianban_stocks": [],
            "missing": "连板梯队未取得",
        }
    return {
        "seal_rate": emo.get("seal_rate"),
        "bomb_rate": emo.get("break_rate"),
        "advance_rate": emo.get("promotion_rate"),
        "lianban_stocks": emo.get("lianban_stocks", []),
    }
