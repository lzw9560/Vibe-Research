# -*- coding: utf-8 -*-
"""R2 资金流（B4）。主力净流/龙虎榜机构/北向；北向不可得记 missing（§8）。"""

from __future__ import annotations

import astock
from data.mappers import dragon_tiger_from_dict
from predict.features.fund_flow import fetch_dt_hot_money_relay, fetch_northbound


def fetch_fund_flow(codes: list[str], as_of: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in codes:
        entry: dict = {
            "main_net_inflow": None,
            "main_net_5d": None,
            "dragon_tiger_inst_net": None,
            "dragon_tiger_hot_money_relay": None,
            "northbound": None,
            "missing": {},
        }
        try:
            flows = astock.stock_fund_flow_120d(c) or []
            if flows:
                # astock 返回 main_net 单位为"元"，模型口径为"万"，需换算。
                entry["main_net_inflow"] = round((flows[-1].get("main_net") or 0) / 10000.0, 1)
                last5 = flows[-5:]
                entry["main_net_5d"] = round(
                    sum((f.get("main_net") or 0) for f in last5) / 10000.0, 1
                )
            else:
                entry["missing"]["main_net_inflow"] = "资金流未取得"
        except Exception:
            entry["missing"]["main_net_inflow"] = "资金流取数失败"
        try:
            dt = dragon_tiger_from_dict(astock.dragon_tiger_board(c) or {})
            entry["dragon_tiger_inst_net"] = dt.institution_net
            if entry["dragon_tiger_inst_net"] is None:
                entry["missing"]["dragon_tiger_inst_net"] = "龙虎榜待披露"
        except Exception:
            entry["missing"]["dragon_tiger_inst_net"] = "龙虎榜未取得"
        try:
            relay = fetch_dt_hot_money_relay(c, as_of)
            entry["dragon_tiger_hot_money_relay"] = relay
            if relay is None:
                entry["missing"]["dragon_tiger_hot_money_relay"] = "龙虎榜未上榜"
        except Exception:
            entry["missing"]["dragon_tiger_hot_money_relay"] = "游资接力取数失败"
        try:
            nb = fetch_northbound(c, as_of)
            entry["northbound"] = nb
            if nb is None:
                entry["missing"]["northbound"] = "北向未取得（2024-08-19 后个股日级北向停更/当日无数据）"
        except Exception:
            entry["missing"]["northbound"] = "北向取数失败"
        out[c] = entry
    return out
