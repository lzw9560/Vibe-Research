# -*- coding: utf-8 -*-
"""策略扫描器 — scan_strategy4_tail_drop。

从 feishu_daily_push.py 拆出。删除项（exp-1 审计要求）：
- ❌ scan_strategy1_suffocation：窒息量低吸已证伪（t1_open -8.188% 死亡信号）
- ❌ _scan_strategy4_tail_drop_legacy：降级副本，引擎不可用时本应静默返回空而非降级

保留：scan_strategy4_tail_drop（集成 tail_dip_engine 多专家共识引擎）。
注意：该函数本身也在 build_intraday_card 中标"已归档"（walk-forward 证伪），
保留供复现/参考，不再接入买入候选推送。
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone, timedelta

from .data import get_index_snapshot, get_market_snapshot_all

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


def scan_strategy4_tail_drop() -> list:
    """策略4进化版：尾盘错杀承接扫描（集成 tail_dip_engine 多专家共识引擎）。

    ⚠️ 2026-10-17 归档：本信号经 8 年 walk-forward 证伪（见 build_intraday_card
    证伪通告）。函数保留供复现/参考，不再接入买入候选推送。

    v2.00 进化点：
    - calculate_anomalous_deviation：个股vs板块偏离度>=3%才算错杀（非绝对跌幅）
    - financial_red_line_shield：商誉/质押/连板高度硬红线过滤
    - 跌幅限定-3%~-5%甜区（回测最优，重跌是基本面恶化）
    - 止损-10%（误杀率仅9.8%，非旧版-5%的22%）
    - 周五自动升级安全门槛
    """
    all_stocks = get_market_snapshot_all()
    if not all_stocks:
        return []

    # 导入进化引擎
    backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    try:
        from strategies.tail_dip_engine import (
            calculate_anomalous_deviation,
            financial_red_line_shield,
            HARD_THRESHOLDS,
        )
    except ImportError as e:
        # 引擎不可用时：不再降级为证伪的 legacy 口径，直接返回空（避免误推）
        logger.warning("tail_dip_engine 不可用，scan_strategy4 返回空: %s", e)
        return []

    # 判断是否周五/周末前（收紧安全门槛）
    now = datetime.now(CST)
    is_weekend_eve = now.weekday() == 4  # Friday

    # v4.00：用全市场中位数涨跌幅替代深证成指近似（更抗极值）
    # 降级链：全市场中位数 → 深证成指 → 0
    valid_stocks = [s for s in all_stocks if s.get("price_change_ratio_pct") is not None]
    sector_change_pct = 0.0
    sector_source = "降级(无数据)"
    if valid_stocks:
        sorted_chgs = sorted(s["price_change_ratio_pct"] for s in valid_stocks)
        sector_change_pct = sorted_chgs[len(sorted_chgs) // 2]  # 中位数
        sector_source = f"全市场中位数(n={len(valid_stocks)})"
    else:
        indices = get_index_snapshot()
        if indices:
            for idx in indices:
                if "399001" in idx.get("thscode", ""):
                    sector_change_pct = idx.get("price_change_ratio_pct", 0.0)
                    sector_source = "深证成指(降级)"
                    break

    logger.debug("sector_change_pct=%.4f (%s)", sector_change_pct, sector_source)

    results = []
    for s in all_stocks:
        chg = s.get("price_change_ratio_pct")
        turnover = s.get("turnover")
        price = s.get("last_price")
        volume = s.get("volume")
        if chg is None or turnover is None or price is None:
            continue

        # ━━━ 基础筛选：跌幅-3%~-5%甜区 + 成交额>1000万 + 价格2-80 ━━━
        if chg > HARD_THRESHOLDS["min_drop_pct"]:  # > -3% 不算错杀
            continue
        if chg < HARD_THRESHOLDS["max_drop_pct"]:  # < -5% 重跌不接
            continue
        if turnover < HARD_THRESHOLDS["min_amount"]:
            continue
        if price < HARD_THRESHOLDS["min_price"] or price > 80:
            continue

        # ━━━ 错杀偏离度因子：个股跌 vs 板块涨跌 ━━━
        # 量能收缩比：用 vol_ratio 近似（CLI snapshot 有 vol_ratio 字段）
        vol_ratio_raw = s.get("vol_ratio", 1.0) or 1.0
        # vol_ratio 是量比（今日量/前5日均量），直接传入
        deviation = calculate_anomalous_deviation(
            code=s.get("thscode", ""),
            individual_change_pct=chg,
            sector_change_pct=sector_change_pct,
            volume_today=float(volume or 0),
            volume_ma5=float(volume or 0) / max(vol_ratio_raw, 0.01),  # 反推5日均量
        )

        if not deviation.is_anomalous:
            continue  # 非错杀（板块共跌）→ 跳过

        # ━━━ 财务红线防火墙（降级模式：无财务数据时跳过红线检查）━━━
        # 生产环境应接入akshare拉商誉/质押/应收数据
        # 这里用 limitup_boards 近似（从涨停池数据判断）
        redline = financial_red_line_shield(
            code=s.get("thscode", ""),
            name=s.get("name", ""),
            limitup_boards=0,  # 跌3%+的票不可能是连板，设0
            is_weekend_eve=is_weekend_eve,
        )
        if not redline.passed:
            continue  # 红线拦截

        results.append({
            "code": s.get("thscode", ""),
            "name": s.get("name", ""),
            "price": price,
            "chg": chg,
            "turnover": turnover / 1e8,
            "deviation": deviation.anomalous_deviation,
            "confidence": deviation.confidence,
            "detail": deviation.detail,
            "stop_loss": HARD_THRESHOLDS["max_stop_loss"],   # -10%
            "take_profit": HARD_THRESHOLDS["take_profit"],   # +10%
            "max_hold": HARD_THRESHOLDS["max_hold_days"] if not is_weekend_eve else 3,
            "is_weekend_eve": is_weekend_eve,
        })

    # 按偏离度降序（偏离越大越可能是错杀）
    results.sort(key=lambda x: x["deviation"], reverse=True)
    return results[:10]
