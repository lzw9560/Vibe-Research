"""
STI (Sentiment Temperature Index) router.
"""
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime
from typing import Any, Dict, List

import limitup_sti as ls_sti

router = APIRouter(tags=["sti"])


@router.get("/api/market/sti/latest")
def get_sti_latest(date: str = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最新")) -> Dict[str, Any]:
    """获取最新 STI 情绪温度（含八维明细）。"""
    try:
        engine = ls_sti.get_sti_engine()
        if date:
            result = engine.precompute_daily(date)
        else:
            # 查数据库最新一条
            db = engine._get_db()
            row = db.execute(
                "SELECT * FROM sti_timeline ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if row is None:
                # 表为空，尝试计算今天的
                today = datetime.now(ls_sti.BEIJING_TZ).strftime("%Y-%m-%d")
                result = engine.precompute_daily(today)
            else:
                from datetime import datetime as _dt
                db_score = float(row["score"]) if row["score"] is not None else None
                default_dims = (
                    float(row["dimension_limit_up_count"]) if row["dimension_limit_up_count"] else 0,
                    float(row["dimension_seal_rate"]) if row["dimension_seal_rate"] else 0,
                    float(row["dimension_promotion_rate"]) if row["dimension_promotion_rate"] else 0,
                )
                is_default = (
                    db_score == 50.0
                    and default_dims == (50.0, 80.0, 30.0)
                )
                if is_default:
                    today = row["date"]
                    result = engine.precompute_daily(today)
                else:
                    result = ls_sti.STIResult(
                        date=row["date"],
                        score=db_score,
                        phase=ls_sti.STIPhase(row["phase"]) if row["phase"] else None,
                        dimensions=ls_sti.STIDimension(
                            limit_up_count=default_dims[0],
                            limit_down_count=float(row["dimension_limit_down_count"]) if row["dimension_limit_down_count"] else 0,
                            seal_rate=default_dims[1],
                            advance_decline_ratio=float(row["dimension_advance_decline_ratio"]) if row["dimension_advance_decline_ratio"] else 0,
                            promotion_rate=default_dims[2],
                            prev_zt_performance=float(row["dimension_prev_zt_performance"]) if row["dimension_prev_zt_performance"] else 0,
                            max_boards=float(row["dimension_max_boards"]) if row["dimension_max_boards"] else 0,
                            market_factor=float(row["market_factor"]) if row["market_factor"] else 1.0,
                        ),
                        source_ok=bool(row["source_ok"]) if row["source_ok"] is not None else True,
                        confidence=row["confidence"] or "high",
                        change_from_yesterday=float(row["change_from_yesterday"]) if row["change_from_yesterday"] else 0.0,
                        data_updated=row["data_updated"],
                    )
        return {"data": result.model_dump()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"STI 查询异常：{e}") from e


@router.get("/api/market/sti/timeline")
def get_sti_timeline(days: int = Query(30, ge=1, le=365)) -> Dict[str, Any]:
    """获取 STI 时间线（用于前端趋势图）。"""
    try:
        db = ls_sti.get_sti_engine()._get_db()
        rows = db.execute(
            "SELECT date, score, phase, change_from_yesterday FROM sti_timeline "
            "WHERE score IS NOT NULL ORDER BY date DESC LIMIT ?",
            (days,),
        ).fetchall()
        # 过滤掉 scheduler 写入的默认值 50.0（维度全是固定默认值）
        default_dates = set()
        for r in rows:
            s = float(r["score"]) if r["score"] else None
            if s == 50.0:
                default_dates.add(r["date"])
        if default_dates:
            engine = ls_sti.get_sti_engine()
            for d in default_dates:
                engine.precompute_daily(d)
        timeline: List[Dict[str, Any]] = [
            {
                "date": r["date"],
                "score": round(float(r["score"]), 2) if r["score"] else None,
                "phase": r["phase"],
                "change_from_yesterday": round(float(r["change_from_yesterday"]), 2) if r["change_from_yesterday"] else None,
            }
            for r in rows[::-1]  # 升序
        ]
        return {"data": timeline}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"STI 时间线异常：{e}") from e


__all__ = ["router"]
