# -*- coding: utf-8 -*-
"""S203 T7 模板：封成比监控预警（Vibe 侧可做）。

轮询 em_get 涨停池取 seal_amount + amount 算封成比 < 5% → 预警封单不足。
不像 board_hit_trigger 需 L2 实时——涨停池 snapshot 有 seal_amount + amount 字段，
Vibe 侧走 em_get 限流（不裸调 requests，防封 IP 底线）即可实现。

逻辑：
1. em_get 涨停池 snapshot（getTopicZTPool）取当日涨停股 + seal_amount + amount
2. 算封成比 = seal_amount / amount
3. 封成比 < 5% → 预警（封单薄，炸板风险高）
4. 可选：推送通知/写日志

依赖（Vibe 侧可做）：
- em_get 涨停池 snapshot（astock.em_zt_topic_pool，走 em_get 防封）
- 路由级 cache_response(ttl) 限流（涨停四池 24h 缓存约定）
"""
from __future__ import annotations

from dataclasses import dataclass


#: 封成比预警阈值（< 5% 预警封单不足）
SEAL_RATIO_ALERT_THRESHOLD: float = 0.05


@dataclass(frozen=True)
class SealRatioAlert:
    """封成比预警（不可变）。"""

    code: str
    trade_date: str
    seal_amount: float  # 封单量（元）
    amount: float  # 成交额（元）
    seal_ratio: float  # 封成比
    is_thin_seal: bool  # 封成比 < 5%（炸板风险）


def compute_seal_ratio(seal_amount: float, amount: float) -> float:
    """封成比 = seal_amount / amount（纯函数，amount=0 返 0.0 不报错）。"""
    if amount <= 0:
        return 0.0
    return seal_amount / amount


def evaluate_seal_ratio(
    code: str,
    trade_date: str,
    seal_amount: float,
    amount: float,
) -> SealRatioAlert:
    """评估封成比预警（纯函数，不臆造）。

    is_thin_seal = seal_ratio < SEAL_RATIO_ALERT_THRESHOLD（封单薄，炸板风险高）
    """
    ratio = compute_seal_ratio(seal_amount, amount)
    is_thin = ratio < SEAL_RATIO_ALERT_THRESHOLD
    return SealRatioAlert(
        code=code,
        trade_date=trade_date,
        seal_amount=seal_amount,
        amount=amount,
        seal_ratio=ratio,
        is_thin_seal=is_thin,
    )


def fetch_zt_pool_snapshot(trade_date: str) -> list[dict]:
    """取涨停池 snapshot（Vibe 侧可做，走 em_get 防封）。

    实现时调 astock.em_zt_topic_pool("getTopicZTPool", date_fmt, "fbt:asc")
    （参考 routers/limitup/metrics.py:68，走 em_get 限流不裸调 requests）。
    返涨停股列表，每项含 code/seal_amount/amount 字段。

    ⚠️ 必须走 em_get（backend/data/transport.py 限流/熔断/代理），不裸调 requests。
    """
    # 实现时：from astock import em_zt_topic_pool
    # return em_zt_topic_pool("getTopicZTPool", trade_date, "fbt:asc")
    raise NotImplementedError("实现时接 astock.em_zt_topic_pool（走 em_get 防封）")


def scan_thin_seal_stocks(trade_date: str) -> list[SealRatioAlert]:
    """扫描涨停池封单薄的股（Vibe 侧可做）。

    取涨停池 snapshot → 逐股算封成比 → < 5% 预警。
    """
    pool = fetch_zt_pool_snapshot(trade_date)
    alerts = []
    for item in pool:
        alert = evaluate_seal_ratio(
            code=item.get("code", ""),
            trade_date=trade_date,
            seal_amount=float(item.get("seal_amount", 0) or 0),
            amount=float(item.get("amount", 0) or 0),
        )
        if alert.is_thin_seal:
            alerts.append(alert)
    return alerts
