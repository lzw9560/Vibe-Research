"""
LimitUp screener router.
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Any, Dict, List

import limitup_screener as ls
from routers.common import _load_limitup_params, _save_limitup_params

router = APIRouter(tags=["limitup"])


class LimitUpParamsBody(BaseModel):
    gene_qualify_threshold: float = Field(default=50, ge=0, le=100)
    gene_high_threshold: float = Field(default=60, ge=0, le=100)
    lookback_days: int = Field(default=252, ge=1, le=365)


def _check_threshold_sanity(params: LimitUpParamsBody) -> List[str]:
    """S051 D2：阈值越界 sanity 警告——查 gene_scores 近 30 日 MAX(total_score)。

    阈值 > 近 30 日最高分 → 对应标志恒为空（用户设了不可达阈值）。
    返回 warnings 列表（空=无警告）；查询失败返空（不阻塞保存）。
    """
    warnings: List[str] = []
    try:
        from limitup_screener.data import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT MAX(total_score) as mx FROM gene_scores "
            "WHERE date >= date('now', '-30 days')"
        ).fetchone()
        conn.close()
        max_score = row["mx"] if row and row["mx"] is not None else None
        if max_score is not None:
            if params.gene_high_threshold > max_score:
                warnings.append(
                    f"高基因阈值 {params.gene_high_threshold} 高于近 30 日最高分 {max_score}，"
                    f"high_gene 将恒为空"
                )
            if params.gene_qualify_threshold > max_score:
                warnings.append(
                    f"合格阈值 {params.gene_qualify_threshold} 高于近 30 日最高分 {max_score}，"
                    f"qualify 将恒为空"
                )
    except Exception:
        pass  # 查询失败不阻塞保存（无 DB / 空表等）
    return warnings


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
async def save_limitup_screener_params(params: LimitUpParamsBody) -> Dict[str, Any]:
    """保存打板策略参数（S051 D2：响应带 warnings——阈值越界提醒，不阻塞保存）。"""
    # 更新模块级变量
    ls.GENE_QUALIFY_THRESHOLD = params.gene_qualify_threshold
    ls.GENE_HIGH_THRESHOLD = params.gene_high_threshold
    ls.LOOKBACK_DAYS = params.lookback_days
    # 持久化到文件
    _save_limitup_params(params.model_dump())
    # S051 D2：阈值越界 sanity 警告
    warnings = _check_threshold_sanity(params)
    out: Dict[str, Any] = {"status": "ok"}
    if warnings:
        out["warnings"] = warnings
    return out


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
