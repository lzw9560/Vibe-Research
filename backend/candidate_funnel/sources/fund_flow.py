# -*- coding: utf-8 -*-
"""R2 资金流（B4）。主力净流/龙虎榜机构/北向；北向不可得记 missing（§8）。"""

from __future__ import annotations

import astock
from data.mappers import dragon_tiger_from_dict
from predict.features.fund_flow import fetch_dt_hot_money_relay, fetch_northbound
from concurrent.futures import ThreadPoolExecutor


def _fetch_single(c: str, as_of: str, sectors: list[dict] | None, industry_map: dict[str, str] | None) -> tuple[str, dict]:
    """单只股票的资金流采集（线程安全，无共享状态）。"""
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
        # S085 A6：按 as_of 过滤 flows ≤ as_of——修 replay 误取今日资金流。
        if as_of:
            flows = [f for f in flows if (f.get("date") or "")[:10] <= as_of]
        if flows:
            # astock 返回 main_net 单位为"元"，模型口径为"万"，需换算。
            entry["main_net_inflow"] = round((flows[-1].get("main_net") or 0) / 10000.0, 1)
            last5 = flows[-5:]
            entry["main_net_5d"] = round(
                sum((f.get("main_net") or 0) for f in last5) / 10000.0, 1
            )
            if len(flows) < 2:
                entry["main_net_5d"] = None
                entry["missing"]["main_net_5d"] = "资金流仅 1 天（降级源），5 日累计暂不可得"
            entry["_as_of"] = (flows[-1].get("date") or "")[:10] or None
        else:
            entry["missing"]["main_net_inflow"] = "资金流未取得"
    except Exception:
        entry["missing"]["main_net_inflow"] = "资金流取数失败"
    try:
        dt = dragon_tiger_from_dict(astock.dragon_tiger_board(c, trade_date=as_of) or {})
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

    # S084 R4.2：板块资金（行业级，sectors 外部传入）
    if sectors:
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
    return c, entry


def fetch_fund_flow(codes: list[str], as_of: str, sectors: list[dict] | None = None, industry_map: dict[str, str] | None = None) -> dict[str, dict]:
    """并行采集资金流（max_workers=5，防 em_get 限流）。

    原 36 只串行 186s → 并行后预估 ~37s（5 并发 × 36/5 × 2.6s/只）。
    """
    if not codes:
        return {}
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(5, len(codes))) as ex:
        futures = [ex.submit(_fetch_single, c, as_of, sectors, industry_map) for c in codes]
        for fu in futures:
            c, entry = fu.result()
            out[c] = entry
    return out
