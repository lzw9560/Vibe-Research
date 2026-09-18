# -*- coding: utf-8 -*-
"""S219 #11 fund 前向累积 executor——每日盘后 UPDATE zt_history.fund/fundamt（前向累积）。

背景：S219 封单成交比 spec deferred（grill 8 CRITICAL），R1 fund 历史回补不可行
（akshare em 历史日全空 + hithink/ths 不带 fund + baostock 无 fund）。un-defer 条件含
"fund≥60 天"——只能向前累积：每日盘后取 em 当日涨停池 fund（封单额）+ fundamt（成交额），
UPDATE-only 已落定 zt_history 行。~60 天后 S219 un-defer 条件3 满足。

工程底线：
- em_get 限流（astock.em_zt_topic_pool 已包熔断+代理，不裸调 requests）
- 私有 DB 在 .vibe-research/zt_history.db（zt_history_store._DB_PATH）
- 不臆造数据（em 真实 fund/fundamt；缺字段 _to_float→None，COALESCE 保留旧值）
- **绝不 DELETE+INSERT 整日**（deep-review #8 finding 3：毁 consecutive_relay 生产 lbc）——
  UPDATE-only-fund，不翻 is_final，不碰 lbc/fbt/source

dispatch 注册待 #8 agent（scheduler/executors/__init__.py _executors dict）。seed.py 已建
fund_accumulation cron task（30 16 * * 0-4），dispatch 未接线前 cron 触发落 failed run
（未知任务类型）——预期行为，#8 接线后生效。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("vibe-research")


def fund_accumulation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """每日盘后 UPDATE zt_history.fund/fundamt（前向累积，S219 #11）。

    调 astock.em_zt_topic_pool("getTopicZTPool", date, "fbt:asc") 取当日涨停池，提取
    fund（封单额）+ fundamt（成交额），调 zt_history_store.backfill_fund_only UPDATE-only
    已落定行（不 DELETE+INSERT，不翻 is_final，不碰 lbc/fbt/source）。

    16:30 跑时 sti_post_market（15:35）已 snapshot 当日行 → 命中 UPDATE；若当日行未就绪
    （snapshot 失败/延迟），n_updated=0 不 crash，次日或 17:15 终盘 snapshot 补。

    Args:
        payload: {"date": "YYYY-MM-DD"|"YYYYMMDD"|None}。None=最近交易日。

    Returns:
        ok=em 取数成功且 UPDATE ≥0 行；degraded=em 返空池（非交易日/端点空）；
        error=em 取数异常（已 log，不 crash）。
    """
    import astock  # noqa: PLC0415
    from data.zt_history_store import _to_iso, backfill_fund_only  # noqa: PLC0415
    from vr_paths import last_trading_date_str  # noqa: PLC0415

    raw_date = payload.get("date") if isinstance(payload, dict) else None
    if raw_date:
        d_iso = _to_iso(raw_date)
        d_compact = d_iso.replace("-", "") if d_iso else ""
    else:
        d_iso = last_trading_date_str()
        d_compact = d_iso.replace("-", "")

    if not d_iso or not d_compact:
        logger.warning("[fund_accumulation] 无法解析日期 payload=%r", payload)
        return {"status": "error", "date": "", "n_updated": 0, "source": "",
                "error": "无法解析日期"}

    # em 取当日涨停池（走 em_get 限流/熔断/代理，不裸调 requests）
    try:
        pool = astock.em_zt_topic_pool("getTopicZTPool", d_compact, "fbt:asc") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("[fund_accumulation] em_zt_topic_pool 失败 date=%s err=%s", d_iso, e)
        return {"status": "error", "date": d_iso, "n_updated": 0, "source": "em",
                "error": str(e)}

    if not pool:
        logger.info("[fund_accumulation] date=%s em 涨停池空（非交易日/端点空），0 行更新", d_iso)
        return {"status": "degraded", "date": d_iso, "n_updated": 0, "source": "em"}

    # 提取 fund/fundamt → fund_map（仅 fund/fundamt 两字段，不读 lbc/fbt/source/name/hybk）
    fund_map: dict[str, dict] = {}
    for it in pool:
        if not isinstance(it, dict):
            continue
        code = str(it.get("c", "") or "").strip()
        if not code:
            continue
        fund_map[code] = {"fund": it.get("fund"), "fundamt": it.get("fundamt")}

    if not fund_map:
        logger.info("[fund_accumulation] date=%s pool 非空但无有效 code，0 行更新", d_iso)
        return {"status": "degraded", "date": d_iso, "n_updated": 0, "source": "em"}

    n = backfill_fund_only(d_iso, fund_map)
    logger.info("[fund_accumulation] date=%s UPDATE fund/fundamt %d 行（source=em）", d_iso, n)
    return {"status": "ok", "date": d_iso, "n_updated": n, "source": "em"}
