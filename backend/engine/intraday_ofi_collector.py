# -*- coding: utf-8 -*-
"""S176 R1 — 五档时序轮询采集器（tencent fetch_raw，不封 IP）。

盘中（9:30-15:00）轮询 tencent.fetch_raw(codes) → buy/sell 五档 → compute_ofi +
bid_ask_pressure → save_ofi（intraday_accumulation_store，独立 store 不喂 trade_journal）。

数据质量门：fetch_raw 缺 code / buy/sell 空 / 格式错 / save 失败 → 跳过该股该次，不崩。
涨停股 seal_amount 退化（KG 因子 3）——tencent 无 seal_amount 字段，暂 None；
涨停股联读 seal_intraday_snapshots（S167）补 seal_amount 是未来 refinement。

不喂 trade_journal：本模块不 import trade_journal（grep 确认），独立 intraday_accumulation_store。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from engine.intraday_ofi import compute_ofi, compute_ofi_abs, compute_bid_ask_pressure
from data.intraday_accumulation_store import save_ofi

_logger = logging.getLogger(__name__)


def collect_ofi_for_codes(
    codes: list[str], date: str, ts: str, regime: str | None = None,
) -> dict[str, Any]:
    """批量收集 OFI 五档快照 → save_ofi（intraday_accumulation_store）。

    输入：codes（候选股池 ~20-50 股）+ date + ts + regime（大盘 regime，conditioning 分层用）。
    返 {n_codes, n_collected, n_skipped}。
    数据质量门：fetch_raw 缺 code / buy+sell 空 / save 失败 → 跳过，不崩。
    """
    if not codes:
        return {"n_codes": 0, "n_collected": 0, "n_skipped": 0}
    try:
        from data.sources.tencent import fetch_raw  # noqa: PLC0415
        raw = fetch_raw(codes)
    except Exception as e:  # noqa: BLE001
        _logger.warning("collect_ofi: tencent.fetch_raw 失败: %s", e)
        return {"n_codes": len(codes), "n_collected": 0, "n_skipped": len(codes)}

    n_collected = 0
    n_skipped = 0
    for code in codes:
        item = raw.get(code)
        if not isinstance(item, dict):
            n_skipped += 1
            continue
        buy = item.get("buy") or []
        sell = item.get("sell") or []
        # 数据质量门：buy+sell 全空 → 跳过（tencent 偶发坏档/停牌）
        if not buy and not sell:
            n_skipped += 1
            continue
        ofi = compute_ofi(buy, sell)
        ofi_abs = compute_ofi_abs(buy, sell)
        pressure = compute_bid_ask_pressure(buy, sell)
        buy_vols = [lv.get("vol", 0) if isinstance(lv, dict) else 0 for lv in buy]
        sell_vols = [lv.get("vol", 0) if isinstance(lv, dict) else 0 for lv in sell]
        # tencent 无 seal_amount（东财 zt_pool 有），暂 None；涨停退化是未来 refinement
        seal_amount = item.get("seal_amount")
        try:
            save_ofi(date, ts, code, ofi, ofi_abs, pressure,
                      json.dumps(buy_vols), json.dumps(sell_vols), seal_amount, regime)
            n_collected += 1
        except Exception as e:  # noqa: BLE001
            _logger.warning("collect_ofi: save_ofi %s 失败: %s", code, e)
            n_skipped += 1
    return {"n_codes": len(codes), "n_collected": n_collected, "n_skipped": n_skipped}


__all__ = ["collect_ofi_for_codes"]
