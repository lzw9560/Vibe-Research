"""
LimitUp screener router.
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Any, Dict

import limitup_screener as ls
from routers.common import _load_limitup_params, _save_limitup_params

router = APIRouter(tags=["limitup"])


class LimitUpParamsBody(BaseModel):
    gene_qualify_threshold: float = Field(default=50, ge=0, le=100)
    gene_high_threshold: float = Field(default=75, ge=0, le=100)
    lookback_days: int = Field(default=252, ge=1, le=365)


@router.get("/api/limitup/screener")
async def limitup_screener(date: str = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日")) -> Dict[str, Any]:
    """获取今日/指定日期的全市场涨停股基因得分（客观数据，非行动建议）。"""
    try:
        result = await ls.get_screener_result(date)
        return {"data": result}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"涨停基因选股器异常：{e}") from e


@router.get("/api/limitup/screener/params")
async def get_limitup_screener_params() -> Dict[str, Any]:
    """获取当前打板策略参数"""
    return _load_limitup_params()


@router.post("/api/limitup/screener/params")
async def save_limitup_screener_params(params: LimitUpParamsBody) -> Dict[str, str]:
    """保存打板策略参数"""
    # 更新模块级变量
    ls.GENE_QUALIFY_THRESHOLD = params.gene_qualify_threshold
    ls.GENE_HIGH_THRESHOLD = params.gene_high_threshold
    ls.LOOKBACK_DAYS = params.lookback_days
    # 持久化到文件
    _save_limitup_params(params.model_dump())
    return {"status": "ok"}


@router.post("/api/limitup/screener/trigger")
async def trigger_screener() -> Dict[str, str]:
    """手动触发今日基因得分预计算（后台异步执行）。"""
    import asyncio
    import threading
    try:
        date_str = datetime.now().strftime("%Y-%m-%d")
        thread = threading.Thread(
            target=lambda: asyncio.run(ls.precompute_daily_async(date_str)),
            daemon=True,
        )
        thread.start()
        return {"status": "started", "date": date_str}
    except Exception as e:
        raise HTTPException(500, f"触发预计算失败：{e}") from e


__all__ = ["router"]
