# -*- coding: utf-8 -*-
"""飞书推送 —— 盘前/盘中/盘后推送（节流 + 去重 + 教育性免责）。"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from config import default_config
from notification.notification_service import NotificationService

# 推送节流配置
_PUSH_THROTTLE = {
    "same_ticker_interval_sec": 300,
    "max_daily_per_ticker": 3,
    "max_daily_total": 20,
}

# 静默时段（不推送）
_QUIET_HOURS = default_config.PUSH_QUIET_HOURS

# 全局通知服务
_notification_service: NotificationService | None = None


def get_notification_service() -> NotificationService:
    """获取全局通知服务实例。"""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service


class FeishuNotifier:
    """飞书 Webhook 推送器。"""

    def __init__(self, webhook: str | None = None):
        self.webhook = webhook or os.getenv("VR_FEISHU_WEBHOOK", "")
        self._daily_count = 0
        self._ticker_last: dict[str, float] = {}

    def _check_throttle(self, ticker: str) -> bool:
        """检查是否允许推送（节流 + 静默时段）。"""
        now = time.time()
        hour = time.localtime(now).tm_hour
        if _QUIET_HOURS[0] <= hour or hour < _QUIET_HOURS[1]:
            return False

        if self._daily_count >= _PUSH_THROTTLE["max_daily_total"]:
            return False

        last = self._ticker_last.get(ticker, 0)
        if now - last < _PUSH_THROTTLE["same_ticker_interval_sec"]:
            return False

        return True

    def _mark_sent(self, ticker: str) -> None:
        """记录推送。"""
        self._daily_count += 1
        self._ticker_last[ticker] = time.time()

    async def push_card(self, card: dict[str, Any], ticker: str = "global") -> bool:
        """推送飞书卡片（interactive card 渲染）。"""
        if not self.webhook:
            return False
        if not self._check_throttle(ticker):
            return False

        try:
            import requests
            # 飞书 webhook interactive card payload（渲染卡片，非 JSON 文本）
            payload = {"msg_type": "interactive", "card": card}
            r = requests.post(self.webhook, json=payload, timeout=15)
            result = r.json()
            ok = result.get("code") == 0 or result.get("StatusCode") == 0 or result.get("status") == "success"
            if ok:
                self._mark_sent(ticker)
            return ok
        except Exception:
            return False

    async def push_text(self, text: str, ticker: str = "global") -> bool:
        """推送纯文本消息。"""
        card = {
            "header": {"title": {"tag": "plain_text", "content": "投研助手"}},
            "elements": [{"tag": "markdown", "content": text}],
        }
        return await self.push_card(card, ticker=ticker)


# 全局推送器
notifier = FeishuNotifier()


def build_daily_review_card(review: dict[str, Any]) -> dict[str, Any]:
    """构建每日复盘飞书卡片。"""
    market = review.get("market_overview", {})
    elements = [
        {
            "tag": "column_set",
            "columns": [
                {"tag": "column", "width": "weighted", "weight": 1,
                 "elements": [{"tag": "markdown", "content": f"**STI温度**: {market.get('sti_score', '-')} ({market.get('sti_phase', '-')})"}]},
                {"tag": "column", "width": "weighted", "weight": 1,
                 "elements": [{"tag": "markdown", "content": f"**涨停数**: {market.get('zt_count', '-')}"}]},
            ],
        },
        {"tag": "markdown", "content": "**板块轮动**"},
    ]

    for sector in review.get("sector_rotation", [])[:5]:
        elements.append(
            {"tag": "markdown", "content": f"  • {sector.get('sector')}: {sector.get('change_pct', 0):+.1f}% ({sector.get('rotation_signal', '-')})"}
        )

    elements.append({"tag": "markdown", "content": "**今日关注**"})
    for s in review.get("stocks", [])[:5]:
        elements.append(
            {"tag": "markdown", "content": f"  • {s.get('name')}({s.get('code')}): {s.get('gene_score', 0)}分 {s.get('recommendation_level', '-')}"}
        )

    elements.append(
        {"tag": "note", "content": "⚠️ 以上内容为历史统计特征分析，不代表未来行为。仅作研究参考，不构成投资建议。"}
    )

    return {
        "header": {"title": {"tag": "plain_text", "content": f"📊 {review.get('date')} 投研复盘"}, "template": "blue"},
        "elements": elements,
    }


def build_recommendation_card(rec: dict[str, Any]) -> dict[str, Any]:
    """构建推荐关注飞书卡片。"""
    elements = [
        {"tag": "markdown", "content": f"**基因得分**: {rec.get('gene_score', 0)}"},
        {"tag": "markdown", "content": f"**推荐等级**: {rec.get('level', '-')}"},
        {"tag": "markdown", "content": f"**研究仓位**: {rec.get('position_suggestion', '-')}"},
        {"tag": "markdown", "content": f"**逻辑**: {'; '.join(rec.get('reasoning', [])[:3])}"},
        {"tag": "markdown", "content": f"**风险**: {'; '.join(rec.get('risk_notes', [])[:3])}"},
        {"tag": "note", "content": "⚠️ 历史统计特征，不代表未来行为。仅作研究参考，不构成投资建议。"},
    ]

    return {
        "header": {"title": {"tag": "plain_text", "content": f"📊 研究关注: {rec.get('name', '-')}({rec.get('code', '-')})"}, "template": "green"},
        "elements": elements,
    }
