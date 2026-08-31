# -*- coding: utf-8 -*-
"""候选池竞价监控 —— 仅对前日推荐的候选池标的进行竞价跟踪，9:25 最终确认推送。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import astock
import limitup_screener as ls
from data.mappers import quote_from_tencent
from limitup_sti import get_sti_engine


@dataclass
class AuctionSignal:
    """集合竞价信号。"""
    code: str
    name: str
    open_premium: float
    auction_amount: float
    volume_ratio: float
    cancel_rate: float
    market_cap_tier: str
    signal_type: str
    confidence: float
    reasoning: list[str]


# 不同市值的竞价金额阈值
_AUCTION_THRESHOLDS = {
    "small":  {"amount_min": 3_000_000,  "volume_ratio_min": 3.0},
    "mid":    {"amount_min": 10_000_000, "volume_ratio_min": 2.5},
    "large":  {"amount_min": 30_000_000, "volume_ratio_min": 2.0},
}


def _market_cap_tier(market_cap: float) -> str:
    if market_cap < 50_0000_000:
        return "small"
    if market_cap < 200_0000_000:
        return "mid"
    return "large"


async def build_auction_watchlist(limit: int = 20) -> list[str]:
    """构建竞价监控候选池（来自前一交易日的推荐基因得分）。

    竞价监控应在盘前使用前一交易日的 screener 结果构建 watchlist，
    避免当日 screener 尚未预计算时返回空列表。
    """
    try:
        from limitup_screener import public_get_cache, public_get_cache_ttl, public_resolve_date, public_load_gene_scores
        from limitup_screener.service import _COMPUTING
        from datetime import timedelta

        # 使用前一交易日日期
        target_date = await public_resolve_date(None)
        # 简单回退一天（实际应使用交易日历，此处简化）
        prev_dt = datetime.strptime(target_date, "%Y%m%d") - timedelta(days=1)
        prev_date = prev_dt.strftime("%Y%m%d")
        cache_key = f"limitup_screener_{prev_date}"
        now = time.time()

        # 正在计算中：不等待，直接返回空
        if cache_key in _COMPUTING:
            return []

        # 内存缓存命中
        _CACHE = public_get_cache()
        _CACHE_TTL = public_get_cache_ttl()
        hit = _CACHE.get(cache_key)
        if hit and now - hit[0] < _CACHE_TTL:
            result = hit[1]
            if result and result.gene_scores:
                return [g.code for g in result.gene_scores[:limit]]

        # 数据库预计算结果（快速路径）
        display_prev = prev_date[:4] + "-" + prev_date[4:6] + "-" + prev_date[6:]
        db_scores = public_load_gene_scores(display_prev)
        if db_scores:
            return [g.code for g in db_scores[:limit]]

        return []
    except Exception:
        return []


async def fetch_auction_snapshot_batch(codes: list[str]) -> list[dict]:
    """批量获取竞价快照（接入腾讯实时行情）。"""
    try:
        quotes = astock.tencent_quote(codes)
    except Exception as exc:  # noqa: BLE001
        # 行情接口失败时降级为空快照，避免监控链路整体中断
        return [
            {
                "code": code,
                "open_premium": 0.0,
                "auction_amount": 0.0,
                "volume_ratio": 0.0,
                "cancel_rate": 0.0,
                "market_cap": 0.0,
            }
            for code in codes
        ]

    snapshots: list[dict] = []
    for code in codes:
        # 经 mapper 拿 Quote 模型：单位已统一（turnover/market_cap 均为元），
        # 消除写死 amount_wan*1e4 / mcap_yi*1e8 换算与字段丢失风险（plan-stage1 警告项）。
        model = quote_from_tencent(code, quotes.get(code, {}))
        # S128 R1：不 or 0 反吞 S121 None-contract（mappers:82-85 last_close/open/market_cap
        # "0 永不合法"→None）。critical 字段 None=quote 失败→标 degraded，analyze 不生成信号。
        last_close = model.last_close
        open_price = model.open
        market_cap = model.market_cap
        quote_ok = last_close is not None and open_price is not None and market_cap is not None
        if quote_ok:
            open_premium = ((open_price - last_close) / last_close) if last_close else 0.0
        else:
            open_premium = None
        stock_name = model.name or code

        snapshots.append(
            {
                "code": code,
                "name": stock_name,
                "open_premium": open_premium,
                "auction_amount": model.turnover,  # None per S121 mappers:73（degraded 路径不用）
                "volume_ratio": model.vol_ratio,  # 0 合法但 None on missing
                "cancel_rate": 0.0,  # 腾讯行情不含撤单率
                "market_cap": market_cap,
                "data_status": "ok" if quote_ok else "degraded",
            }
        )
    return snapshots


def analyze_final_auction(snapshots: list[dict]) -> list[AuctionSignal]:
    """分析最终竞价快照，生成信号。"""
    signals = []
    for snap in snapshots:
        code = snap.get("code", "")
        name = snap.get("name", code)
        # S128 R1：degraded（quote 失败，critical 字段 None）→ 不生成信号（不喂 0 触发
        # "缩量平开"/错 tier "爆量高开"），返 "无信号" + reason。
        if snap.get("data_status") == "degraded":
            signals.append(AuctionSignal(
                code=code, name=name, open_premium=0.0, auction_amount=0.0,
                volume_ratio=0.0, cancel_rate=0.0, market_cap_tier="unknown",
                signal_type="无信号", confidence=0.0,
                reasoning=["行情取数失败（degraded），不生成竞价信号"],
            ))
            continue
        open_premium = snap.get("open_premium") or 0
        amount = snap.get("auction_amount") or 0
        volume_ratio = snap.get("volume_ratio") or 0
        cancel_rate = snap.get("cancel_rate") or 0
        market_cap = snap.get("market_cap") or 0

        tier = _market_cap_tier(market_cap)
        threshold = _AUCTION_THRESHOLDS.get(tier, _AUCTION_THRESHOLDS["mid"])

        reasoning = []
        signal_type = "无信号"

        # 爆量高开
        if (
            open_premium >= 0.02
            and amount >= threshold["amount_min"]
            and volume_ratio >= threshold["volume_ratio_min"]
        ):
            signal_type = "爆量高开"
            reasoning.append("竞价成交额显著放大")
            reasoning.append("量比高于阈值")
            confidence = 0.8
        # 缩量平开
        elif open_premium < 0.01 and volume_ratio < 1.0:
            signal_type = "缩量平开"
            reasoning.append("竞价量能不足")
            confidence = 0.3
        # 异常撤单
        elif cancel_rate > 0.25:
            signal_type = "异常撤单"
            reasoning.append(f"撤单率{cancel_rate:.1%}，高于正常水平")
            confidence = 0.2
        else:
            confidence = 0.1

        signals.append(
            AuctionSignal(
                code=code,
                name=name,
                open_premium=open_premium,
                auction_amount=amount,
                volume_ratio=volume_ratio,
                cancel_rate=cancel_rate,
                market_cap_tier=tier,
                signal_type=signal_type,
                confidence=confidence,
                reasoning=reasoning,
            )
        )
    return signals


async def monitor_auction() -> list[AuctionSignal] | None:
    """候选池竞价监控（9:15-9:25 每 10 秒采样，9:25 最终确认）。"""
    watchlist = await build_auction_watchlist()
    if not watchlist:
        return None

    # 采样（实际应在 9:15-9:25 循环采样）
    snapshots = await fetch_auction_snapshot_batch(watchlist)

    # 最终确认
    signals = analyze_final_auction(snapshots)
    return [s for s in signals if s.signal_type != "无信号"]
