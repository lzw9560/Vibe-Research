"""
Market router.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict

import market
import gstock

router = APIRouter(tags=["market"])


@router.get("/api/market/overview")
def market_overview() -> Dict[str, Any]:
    """市场情绪 + 板块资金流（板块/大盘级，全站共享缓存 5 分钟）。"""
    try:
        return {"data": market.get_overview()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"市场总览异常：{e}") from e


@router.get("/api/market/emotion")
def market_emotion() -> Dict[str, Any]:
    """短线情绪：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数。

    含连板梯队个股清单（code/name/连板数等）——2026-07-05 起如实展示客观公开榜单（东财同款），
    只呈现事实，不附推荐/评分/预测/买卖时机。全站共享缓存 5 分钟。
    """
    try:
        return {"data": market.get_short_term_emotion()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"短线情绪异常：{e}") from e


@router.get("/api/market/turnover-top")
def market_turnover_top() -> Dict[str, Any]:
    """全市场成交额榜 Top20（客观公开榜单数据，非推荐/非预测/不评分）。全站共享缓存 5 分钟。"""
    try:
        return {"data": market.get_turnover_top()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"成交额榜异常：{e}") from e


@router.get("/api/global/indices")
def global_indices() -> Dict[str, Any]:
    """全球指数快照（道指 / 标普500 / 纳斯达克 / 恒生 / 恒生科技）—— A 股看隔夜外围脸色。缓存 5 分钟。"""
    try:
        return {"data": market.get_global_indices()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"全球指数异常：{e}") from e


@router.get("/api/global/stock")
def global_stock(symbol: str = Query(..., min_length=1, max_length=16)) -> Dict[str, Any]:
    """美股 / 港股个股聚合：行情 + 关键财务指标（东财域内源）。symbol 如 AAPL / BABA / 00700。"""
    try:
        data = gstock.us_hk_stock(symbol.strip())
        if not data:
            raise HTTPException(404, f"未找到美股/港股代码「{symbol}」")
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"美港股查询异常：{e}") from e


__all__ = ["router"]
