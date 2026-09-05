"""
Review router.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import os
import json
import asyncio
from datetime import datetime
from typing import Any, Dict

import limitup_screener as _ls
import daily_review as dr
from vr_paths import last_trading_date_str

router = APIRouter(tags=["review"])


# ---- Helpers ----

REVIEW_PARAMS_FILE = os.path.join(os.path.dirname(__file__), "..", "review_params.json")


def _load_review_params() -> Dict[str, Any]:
    try:
        with open(REVIEW_PARAMS_FILE) as f:
            return json.load(f)
    except Exception:
        return {
            "max_zt_stocks": os.getenv("REVIEW_MAX_ZT_STOCKS", "100"),
            "auction_top_n": os.getenv("REVIEW_AUCTION_TOP_N", "20"),
        }


def _save_review_params(params: Dict[str, Any]) -> None:
    with open(REVIEW_PARAMS_FILE, "w") as f:
        json.dump(params, f, indent=2)


# ---- Routes ----

@router.get("/api/review/daily")
async def get_daily_review(date: str = Query(None, description="交易日期 YYYY-MM-DD")) -> Dict[str, Any]:
    """
    获取指定日期的每日复盘报告。
    
    包含：市场情绪总结、板块热度排名、涨停股统计、昨日涨停表现、竞价回顾。
    """
    if date is None:
        date = last_trading_date_str()

    try:
        reviewer = dr.get_reviewer()
        # generate_review 同步打东财外部 API，阻塞事件循环 → 用 asyncio.to_thread 卸到线程池。
        # 参考 routers/strategy.py:72 既有模式。
        result = await asyncio.to_thread(reviewer.generate_review, date)
        return result.model_dump()
    except ValueError as e:
        # 非交易日/日期格式错误 → 422（客户端输入语义错，非服务器故障）
        # daily_review.generate_review 的交易日守门抛 ValueError，不应误报为 500。
        raise HTTPException(status_code=422, detail=f"复盘报告生成失败: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"复盘报告生成失败: {str(e)}")


@router.get("/api/review/daily/backfill")
async def backfill_review(start_date: str = Query(..., description="起始日期 YYYY-MM-DD"), end_date: str = Query(None, description="结束日期 YYYY-MM-DD，默认今天")) -> Dict[str, Any]:
    """
    复盘报告历史回填。
    """
    if end_date is None:
        end_date = datetime.now(_ls.BEIJING_TZ).strftime("%Y-%m-%d")
    
    try:
        reviewer = dr.get_reviewer()
        results = reviewer.backfill(start_date, end_date)
        return {
            "status": "ok",
            "count": len(results),
            "start_date": start_date,
            "end_date": end_date,
        }
    except ValueError as e:
        # 非交易日/日期格式错误 → 422（与 get_daily_review 一致）
        raise HTTPException(status_code=422, detail=f"复盘报告回填失败: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"复盘报告回填失败: {str(e)}")


@router.get("/api/review/params")
async def get_review_params() -> Dict[str, Any]:
    """获取复盘报告参数"""
    return _load_review_params()


class ReviewParamsBody(BaseModel):
    max_zt_stocks: int = Field(default=100, ge=10, le=500)
    auction_top_n: int = Field(default=20, ge=1, le=100)


@router.post("/api/review/params")
async def save_review_params(params: ReviewParamsBody) -> Dict[str, str]:
    """保存复盘报告参数"""
    _save_review_params(params.model_dump())
    return {"status": "ok"}


__all__ = ["router"]
