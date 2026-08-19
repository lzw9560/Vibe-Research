# -*- coding: utf-8 -*-
"""R2 资金流（B4）。主力净流/龙虎榜机构/北向；北向不可得记 missing（§8）。"""

from __future__ import annotations

import astock
from data.mappers import dragon_tiger_from_dict
from predict.features.fund_flow import fetch_dt_hot_money_relay, fetch_northbound


def fetch_fund_flow(codes: list[str], as_of: str, sectors: list[dict] | None = None, industry_map: dict[str, str] | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in codes:
        entry: dict = {
            "main_net_inflow": None,
            "main_net_5d": None,
            "dragon_tiger_inst_net": None,
            "dragon_tiger_hot_money_relay": None,
            "northbound": None,
            # S084 R4.2：板块资金 3 字段（行业级，从 market.get_overview()['sectors'] 按个股行业匹配）
            "sector_net_inflow": None,
            "sector_inflow": None,
            "sector_outflow": None,
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
                # S049a：降级源（push2delay）只回最新 1 行——单行时不拿当日
                # 净流冒充"5 日累计"，标 missing 透明（AC6）；≥2 行沿用既有
                # 契约"不足 5 天按可用天数求和"（test_main_net_5d_is_sum_of_last_five_in_wan）。
                if len(flows) < 2:
                    entry["main_net_5d"] = None
                    entry["missing"]["main_net_5d"] = "资金流仅 1 天（降级源），5 日累计暂不可得"
                # S049 C2：暴露数据源最新行日期（供 diagnose as_of 取最早）
                entry["_as_of"] = (flows[-1].get("date") or "")[:10] or None
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

        # S084 R4.2：板块资金（行业级，sectors 外部传入——由 funnel 调 market.get_overview()['sectors']
        # 5min 缓存 batch 复用，避免 per-code raw akshare 调用违反防封底线）
        if sectors:
            # S084 R4.2：行业从 zt pool hybk 提取（em_get-backed，替代 raw akshare individual_info，防封底线 review HIGH 修复）
            industry = industry_map.get(c) if industry_map else None
            if industry:
                match = next((s for s in sectors if s.get("name") == industry), None)
                if match:
                    entry["sector_net_inflow"] = match.get("net")
                    entry["sector_inflow"] = match.get("inflow")
                    entry["sector_outflow"] = match.get("outflow")
                else:
                    entry["missing"]["sector_net_inflow"] = "行业未匹配（板块列表无此行业）"
            else:
                entry["missing"]["sector_net_inflow"] = "个股行业未取得（zt pool 无 hybk）"
        else:
            entry["missing"]["sector_net_inflow"] = "板块资金未采集（sectors 未传入）"
        out[c] = entry
    return out
