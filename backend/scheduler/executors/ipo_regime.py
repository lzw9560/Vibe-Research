# -*- coding: utf-8 -*-
"""S245 打新 regime 监控——破发率/首日涨幅/IPO 节奏 转弱 alert。

6专家panel(wb8nifjg8)第三步:打新是当前系统最大 surviving edge(14.72% > 512890 13.47%),
BUT S243 只筛个股 PE 红线没盯 regime(最大引擎没仪表盘)。explore_ipo_underpricing.py 验证
4 段断代 regime 依赖:S4 当前破发 0.57% + 首日 median +199.8%(异常 favorable),S3 破发潮 22%。
yield 腰斩只需 regime 一转。本 executor weekly 算 rolling 90 天 regime health,2/3 触发转弱 alert。

详见 specs/S245-ipo-regime-monitor/spec.md。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from circuit_breaker import get_breaker
from scheduler.executors.signals import _send_text_notification

logger = logging.getLogger("vibe-research")

LOOKBACK_DAYS = 90
# regime 转弱阈值(基于 explore_ipo_underpricing.py 4 段断代)
BREAK_RATE_CUT = 0.10  # 破发率 >10%(S4 当前 0.57%,S3 破发潮 22%)
FIRST_DAY_MEDIAN_CUT = 50.0  # 首日 median <50%(S4 +199.8%,S3 +39%)
IPO_PER_WEEK_CUT = 5.0  # IPO >5/周(S4 ~2/周,S3 ~6/周)
TRIGGER_THRESHOLD = 2  # 2/3 触发(避免单指标噪声)


def get_ipo_regime_health() -> dict[str, Any]:
    """拉 stock_xgsglb_em 近 90 天已上市新股,算 regime health。

    走 circuit_breaker 防封(复用 akshare_yield 模式)。
    返回 {n_recent, break_rate, first_day_median_pct, ipo_per_week, triggers, regime}。
    """
    breaker = get_breaker("eastmoney")
    if not breaker.allow_request():
        return {"error": "breaker open"}
    try:
        import akshare as ak  # noqa: PLC0415
        df = ak.stock_xgsglb_em()
        breaker.record_success()
    except Exception as e:  # noqa: BLE001
        breaker.record_failure()
        logger.warning("[ipo_regime] fetch err: %s", repr(e)[:120])
        return {"error": f"fetch err: {repr(e)[:80]}"}

    df["上市日期"] = pd.to_datetime(df["上市日期"], errors="coerce")
    df["涨幅"] = pd.to_numeric(df["涨幅"], errors="coerce")
    cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)
    # 近 90 天已上市(涨幅非 NaN = 已上市,排除待上市)
    recent = df[(df["上市日期"] >= cutoff) & df["涨幅"].notna()].copy()
    if len(recent) < 10:
        return {"error": "sample too small", "n": len(recent)}

    break_rate = float((recent["涨幅"] < 0).mean())
    first_day_median = float(recent["涨幅"].median())  # % 单位
    ipo_per_week = len(recent) / (LOOKBACK_DAYS / 7)

    triggers = 0
    t_break = break_rate > BREAK_RATE_CUT
    t_median = first_day_median < FIRST_DAY_MEDIAN_CUT
    t_ipo = ipo_per_week > IPO_PER_WEEK_CUT
    if t_break:
        triggers += 1
    if t_median:
        triggers += 1
    if t_ipo:
        triggers += 1

    return {
        "n_recent": len(recent),
        "break_rate": break_rate,
        "first_day_median_pct": first_day_median,
        "ipo_per_week": round(ipo_per_week, 1),
        "triggers": triggers,
        "trigger_flags": {"break": t_break, "median": t_median, "ipo": t_ipo},
        "regime": "weak" if triggers >= TRIGGER_THRESHOLD else "normal",
    }


def ipo_regime_monitor(payload: dict[str, Any]) -> dict[str, Any]:
    """weekly 打新 regime 监控:2/3 触发转弱 alert,正常 skip 不打扰。"""
    health = get_ipo_regime_health()
    if health.get("error"):
        return {"status": "skip", "reason": health["error"]}

    if health["regime"] == "normal":
        return {
            "status": "skip",
            "regime": "normal",
            "triggers": health["triggers"],
            "break_rate": health["break_rate"],
            "first_day_median_pct": health["first_day_median_pct"],
            "ipo_per_week": health["ipo_per_week"],
            "reason": f"{health['triggers']}/3 触发,regime 正常(<{TRIGGER_THRESHOLD} 阈值)",
        }

    flags = health["trigger_flags"]
    text = (
        f"【打新 regime 转弱 alert】{health['triggers']}/3 触发\n"
        f"  破发率: {health['break_rate']*100:.1f}% ({'🔴触发' if flags['break'] else '正常'}, >{BREAK_RATE_CUT*100:.0f}% 阈值)\n"
        f"  首日 median: {health['first_day_median_pct']:.1f}% ({'🔴触发' if flags['median'] else '正常'}, <{FIRST_DAY_MEDIAN_CUT:.0f}% 阈值)\n"
        f"  IPO/周: {health['ipo_per_week']:.1f} ({'🔴触发' if flags['ipo'] else '正常'}, >{IPO_PER_WEEK_CUT:.0f} 阈值)\n"
        f"  近 {LOOKBACK_DAYS} 天 {health['n_recent']} 只已上市新股\n"
        f"操作:严筛/降参与(S243 红线发行PE/行业PE>1.5 跳过),regime 转弱打新 yield 可能腰斩(S3 破发潮 22%)\n"
        f"非自动交易,用户手动决策——S245(6专家panel第三步)"
    )
    _send_text_notification(text)
    return {"status": "sent", "regime": "weak", **health}
