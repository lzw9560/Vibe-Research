"""
Portfolio router.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Dict

import portfolio as pf

router = APIRouter(tags=["portfolio"])


class HoldingIn(BaseModel):
    code: str
    shares: float
    cost: float


class CloseIn(BaseModel):
    code: str
    date: str
    price: float
    shares: float
    cost: float


@router.get("/api/portfolio")
async def portfolio_get() -> Dict[str, Any]:
    """持仓 + 实时盈亏（浮动盈亏红涨绿跌）。"""
    try:
        return {"data": await pf.get_portfolio()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"持仓读取异常：{e}") from e


@router.post("/api/portfolio/holding")
async def portfolio_add(h: HoldingIn) -> Dict[str, Any]:
    """加一笔持仓（同代码按加权平均成本合并）。存本地，不上传。"""
    code = (h.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    if h.shares <= 0:
        raise HTTPException(400, "数量必须大于 0")
    # 成本价不限正负：融券 / 返息 / 摊薄后为负成本等情形按结果计算，用户想怎么输就怎么输。
    return {"data": await pf.add_holding(code, h.shares, h.cost)}


@router.delete("/api/portfolio/holding")
async def portfolio_remove(code: str = Query(...)) -> Dict[str, Any]:
    return {"data": await pf.remove_holding(code.strip())}


@router.post("/api/portfolio/close")
async def portfolio_close(c: CloseIn) -> Dict[str, Any]:
    """记一笔已清仓（已实现盈亏）。存本地。"""
    code = (c.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    if c.price <= 0 or c.shares <= 0:
        raise HTTPException(400, "清仓价与股数必须大于 0")
    # 买入成本不限正负（同持仓录入）：按 (清仓价 - 成本) × 股数 的结果计算已实现盈亏。
    date = (c.date or "").strip()
    if not date:
        raise HTTPException(400, "请填清仓日期")
    from datetime import datetime
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "清仓日期格式应为 YYYY-MM-DD") from None
    return {"data": await pf.close_position(code, date, c.price, c.shares, c.cost)}


@router.delete("/api/portfolio/close")
async def portfolio_close_remove(index: int = Query(...)) -> Dict[str, Any]:
    return {"data": await pf.remove_closed(index)}


@router.post("/api/portfolio/refresh")
async def portfolio_refresh() -> Dict[str, Any]:
    """手动刷新：立即重拉行情算盈亏。"""
    try:
        return {"data": await pf.get_portfolio()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"刷新失败：{e}") from e


__all__ = ["router"]
