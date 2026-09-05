"""
LimitUp auction router.
"""
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, Dict

import limitup_screener as _ls
import auction_screener as asc
from vr_paths import last_trading_date_str
from routers.common import load_json_params, save_json_params

router = APIRouter(tags=["limitup"])


@router.get("/api/limitup/auction/top")
async def get_auction_top(date: str = Query(None, description="交易日期 YYYY-MM-DD"), n: int = Query(50, ge=1, le=100, description="返回候选股数量")) -> Dict[str, Any]:
    """
    获取指定日期的竞价爆量 TOP N 候选股。
    
    盘后批量分析涨停池数据，生成次日竞价预案。
    非实时扫描，而是历史竞价模式回放 + 次日预案生成。
    """
    if date is None:
        # S149 修复：默认最近交易日（非今日）——周末/节假日/盘前今日无竞价数据→空。
        date = last_trading_date_str()
    
    try:
        screener = asc.get_screener()
        result = screener.analyze(date)
        # 截取前 N 只
        result.candidates = result.candidates[:n]
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"竞价选股分析失败: {str(e)}") from e


@router.get("/api/limitup/auction/backfill")
async def backfill_auction(start_date: str = Query(..., description="起始日期 YYYY-MM-DD"), end_date: str = Query(None, description="结束日期 YYYY-MM-DD，默认今天")) -> Dict[str, Any]:
    """
    竞价选股历史回填。
    """
    if end_date is None:
        end_date = datetime.now(_ls.BEIJING_TZ).strftime("%Y-%m-%d")
    
    try:
        screener = asc.get_screener()
        results = screener.backfill(start_date, end_date)
        return {
            "status": "ok",
            "count": len(results),
            "start_date": start_date,
            "end_date": end_date,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"竞价选股回填失败: {str(e)}") from e


# ---- 竞价选股参数 ----

import os


AUCTION_PARAMS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "auction_params.json")
_AUCTION_PARAMS_DEFAULTS = {
    "min_gene_score": os.getenv("AUCTION_MIN_GENE_SCORE", "50"),
    "min_zt_count": os.getenv("AUCTION_MIN_ZT_COUNT", "2"),
    "top_n": os.getenv("AUCTION_TOP_N", "50"),
}


class AuctionParamsBody(BaseModel):
    min_gene_score: float = Field(default=50, ge=0, le=100)
    min_zt_count: int = Field(default=2, ge=0, le=20)
    top_n: int = Field(default=50, ge=1, le=100)


@router.get("/api/limitup/auction/params")
async def get_auction_params() -> Dict[str, Any]:
    """获取竞价选股参数"""
    return load_json_params(AUCTION_PARAMS_FILE, _AUCTION_PARAMS_DEFAULTS)


@router.post("/api/limitup/auction/params")
async def save_auction_params(params: AuctionParamsBody) -> Dict[str, str]:
    """保存竞价选股参数"""
    save_json_params(AUCTION_PARAMS_FILE, params.model_dump())
    return {"status": "ok"}


__all__ = ["router"]
