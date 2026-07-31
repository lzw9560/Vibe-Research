# -*- coding: utf-8 -*-
"""seat_engine 模型与配置。"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, PrivateAttr


SEAT_DISCLAIMER = (
    "免责声明：席位标签基于龙虎榜历史数据统计特征，不代表对未来行为的预测，"
    "不构成投资建议。股市有风险，投资需谨慎。"
)

SEAT_LOOKBACK_DAYS = int(os.getenv("SEAT_LOOKBACK_DAYS", "180"))
SEAT_QUANT_THRESHOLD = int(os.getenv("SEAT_QUANT_THRESHOLD", "30"))
SEAT_ACTIVE_MIN = int(os.getenv("SEAT_ACTIVE_MIN", "10"))
SEAT_LARGE_POS = float(os.getenv("SEAT_LARGE_POS", "10000"))
SEAT_SMALL_POS = float(os.getenv("SEAT_SMALL_POS", "3000"))


class SeatProfile(BaseModel):
    """单个席位的统计画像。"""

    seat_name: str
    total_appearances: int = 0
    total_buy_amt: float = 0.0
    total_sell_amt: float = 0.0
    net_amt: float = 0.0
    avg_buy_amt: float = 0.0
    avg_sell_amt: float = 0.0
    stock_cooldown: int = 0
    last_seen: str = ""
    seat_type: str = "inactive"

    _buy_appearances: int = PrivateAttr(default=0)
    _sell_appearances: int = PrivateAttr(default=0)
    _stocks_traded: set = PrivateAttr(default_factory=set)
    _stock_buy_sell_pairs: set = PrivateAttr(default_factory=set)


class ConsensusSignal(BaseModel):
    """共识/分歧信号。"""

    signal: str | None
    details: dict[str, Any] = {}
    date: str = ""
    stock_code: str = ""
    disclaimer: str = SEAT_DISCLAIMER
