# -*- coding: utf-8 -*-
"""R2 全市场活跃度（B3）。换手/量比/成交额/振幅，批次 50，经 astock 限流（AC7）。"""

from __future__ import annotations

import astock
from data.mappers import quote_from_tencent

_BATCH = 50


def fetch_activity(codes: list[str], as_of: str) -> dict[str, dict]:
    """返回 {code: {name, price, change_pct, turnover_pct, vol_ratio, amount_yi,
    amplitude_pct, limit_up, limit_down, missing?}}。

    读侧经 ``quote_from_tencent`` 拿 Quote 模型（单位已统一、字段 rename 已集中），
    输出 dict shape 保持不变以兼容下游 candidate_funnel/funnel（本轮不迁下游）。
    """
    out: dict[str, dict] = {}
    for i in range(0, len(codes), _BATCH):
        batch = codes[i : i + _BATCH]
        try:
            raw = astock.tencent_quote(batch) or {}
        except Exception:
            for c in batch:
                out[c] = {"missing": {"turnover_pct": "行情未取得"}}
            continue
        for c in batch:
            model = quote_from_tencent(c, raw.get(c, {}))
            # turnover 为元，换算成亿元；不用 `or` 兜底以免吞掉 0.0
            turnover = model.turnover
            amount_yi = round(turnover / 1e8, 4) if turnover is not None else None
            entry = {
                "name": model.name,
                "price": model.price,
                "change_pct": model.change_pct,
                "turnover_pct": model.turnover_rate,
                "vol_ratio": model.vol_ratio,
                "amount_yi": amount_yi,
                "amplitude_pct": model.amplitude,
                "limit_up": model.limit_up_price,
                "limit_down": model.limit_down_price,
            }
            missing: dict[str, str] = {}
            for k in ("turnover_pct", "vol_ratio", "amount_yi", "amplitude_pct"):
                if entry[k] is None:
                    missing[k] = "行情字段未取得"
            if missing:
                entry["missing"] = missing
            out[c] = entry
        for c in batch:
            if c not in out:
                out[c] = {"missing": {"turnover_pct": "行情未取得"}}
    return out
