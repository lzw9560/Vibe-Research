# -*- coding: utf-8 -*-
"""S066 §9 游资席位周更聚合 executor——拉 60 日龙虎榜 → 聚合画像 → 写 seat_profiles.db B 字段。

背景（#13 follow-up research note lhb-axis-a-research-2026-09-19）：
seat_profiles.db B-fields（next_day_sell_rate/appearance_count/confidence/source/note）全空——
strategies.hot_money_seats.update_hot_money_seats() 全 backend 零调用，S066 §9 周更聚合器建了
从未通电。轴 A（席位类型分析）n=0 不够 §44。本 executor 通电 aggregator，每周一 06:00 周更
（~18 次 em_get 防封已守），积累后供 compute_seat_risk_factor 读画像 + 轴 A §44 复测。

工程底线（CLAUDE.md §1.2，保留非降级）：
- em_get 防封：astock.em_get 已包 0.3s 限流 + circuit_breaker 熔断 + 代理探测（fetch_billboard_*
  内部走 em_get，不裸调 requests——S079 AC6 处置，见 strategies/hot_money_seats.py docstring）
- 私有数据隔离：seat_profiles.db 在 .vibe-research/（SEAT_PROFILES_DB_PATH，gitignored，绝不进 git）
- 不臆造数据：真实拉 em datacenter RPT_BILLBOARD_DAILYDETAILSBUY/SELL；残缺日（buy_ok≠sell_ok）
  跳过聚合不喂 build_seat_profiles（S123 R2.2，见 update_hot_money_seats docstring）

数据 prep 非 spec S220（freeze 维持——不通电不写 spec，本 executor 只修 dead infra）。
不碰 evaluation.py / signal_report.py / s203 / routers/signals.py / journal_recorder.py
（只新 executor + seed.py + __init__ dispatch + test）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from scheduler.cron_fire_audit import fire_receipt

logger = logging.getLogger("vibe-research")


@fire_receipt("hot_money_seats_update")
def hot_money_seats_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    """周更聚合 60 日龙虎榜 → 画像 → 写 seat_profiles.db B 字段（S066 §9 通电，#13 follow-up）。

    调 strategies.hot_money_seats.update_hot_money_seats(days) 拉取 + 聚合 + 保存（约 18 次 em_get
    调用，走 astock.em_get 限流/熔断/代理）。返回画像席位数（含 preset 合并）。

    Args:
        payload: {"days": int=60}。days 默认 60（spec §9.3 60 日聚合窗口）。

    Returns:
        ok=聚合成功 n_seats≥1 席位；
        degraded=n_seats=0（fetch_billboard_dates 空返——em 端点空/熔断，次周自愈）；
        error=聚合异常（已 log，不 crash scheduled task，降级 error run）。
    """
    from strategies.hot_money_seats import update_hot_money_seats  # noqa: PLC0415

    days = int(payload.get("days", 60)) if isinstance(payload, dict) else 60
    try:
        n = update_hot_money_seats(days)
    except Exception as e:  # noqa: BLE001 — executor 崩不阻断 scheduled task，降级 error run
        logger.warning("[hot_money_seats_update] update_hot_money_seats 失败 days=%s: %s", days, e)
        return {"status": "error", "days": days, "n_seats": 0, "error": repr(e)[:200]}

    if n == 0:
        # fetch_billboard_dates 空返（em 端点空/熔断）→ update_hot_money_seats 早返 0 → degraded
        logger.info("[hot_money_seats_update] days=%d 聚合 0 席位（em 端点空/熔断），画像未变", days)
        return {"status": "degraded", "days": days, "n_seats": 0}

    logger.info("[hot_money_seats_update] days=%d 聚合 %d 席位 → seat_profiles.db B 字段", days, n)
    return {"status": "ok", "days": days, "n_seats": n}
