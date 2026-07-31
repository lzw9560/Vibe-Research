# -*- coding: utf-8 -*-
"""R2 全市场活跃度（B3）。换手/量比/成交额/振幅，批次 50，经 astock 限流（AC7）。"""

from __future__ import annotations

import astock

_BATCH = 50


def fetch_activity(codes: list[str], as_of: str) -> dict[str, dict]:
    """返回 {code: {name, price, change_pct, turnover_pct, vol_ratio, amount_yi,
    amplitude_pct, limit_up, limit_down, missing?}}。"""
    out: dict[str, dict] = {}
    for i in range(0, len(codes), _BATCH):
        batch = codes[i : i + _BATCH]
        try:
            quotes = astock.tencent_quote(batch) or {}
        except Exception:
            for c in batch:
                out[c] = {"missing": {"turnover_pct": "行情未取得"}}
            continue
        for c, q in quotes.items():
            # astock._parse_gtimg 返回 amount_wan（万），需换算成亿；
            # 不用 `or` 兜底以免吞掉 0.0。
            amount_wan = q.get("amount_wan")
            if amount_wan is not None:
                amount_yi = round(amount_wan / 10000.0, 4)
            else:
                amount_yi = q.get("amount_yi")
            entry = {
                "name": q.get("name"),
                "price": q.get("price"),
                "change_pct": q.get("pct") or q.get("change_pct"),
                "turnover_pct": q.get("turnover") or q.get("turnover_pct"),
                "vol_ratio": q.get("vol_ratio"),
                "amount_yi": amount_yi,
                "amplitude_pct": q.get("amplitude") or q.get("amplitude_pct"),
                "limit_up": q.get("limit_up"),
                "limit_down": q.get("limit_down"),
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
