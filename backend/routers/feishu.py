"""
Feishu notifier router.
"""
from fastapi import APIRouter, HTTPException
from typing import Any, Dict

from feishu_notifier import notifier, build_daily_review_card, build_recommendation_card

router = APIRouter(tags=["feishu"])


@router.post("/api/push/test")
async def push_test() -> Dict[str, Any]:
    """测试推送连接。"""
    text = "投研助手推送测试：这是一条测试消息。\n⚠️ 历史统计特征，不代表未来行为。仅作研究参考，不构成投资建议。"
    ok = await notifier.push_text(text, ticker="test")
    return {"ok": ok}


@router.post("/api/push/daily-review")
async def push_daily_review(payload: Dict[str, Any]) -> Dict[str, Any]:
    """推送每日复盘卡片。"""
    card = build_daily_review_card(payload)
    ok = await notifier.push_card(card, ticker="daily_review")
    return {"ok": ok}


@router.post("/api/push/recommendation")
async def push_recommendation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """推送推荐关注卡片。"""
    card = build_recommendation_card(payload)
    ok = await notifier.push_card(card, ticker=payload.get("code", "recommendation"))
    return {"ok": ok}


__all__ = ["router"]
