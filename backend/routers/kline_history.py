"""历史K线数据路由 —— 暴露批量拉取的K线数据。"""
from fastapi import APIRouter, HTTPException, Path, Query
import sqlite3
import time as _time
from pathlib import Path as _Path
from typing import Any, Dict

from routers.common import _DB_LOCK, _get_db

router = APIRouter(tags=["kline-history"])


def _get_kline_db() -> sqlite3.Connection:
    """获取历史K线数据库连接。"""
    db_path = _Path(__file__).parent / ".." / "data" / "kline_history.db"
    conn = sqlite3.connect(str(db_path.resolve()))
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/api/kline-history/{code}")
def kline_history(
    code: str = Path(..., description="6位股票代码"),
    start_date: str | None = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
) -> Dict[str, Any]:
    """查询个股历史K线数据（过去90日+）。"""
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是6位数字")

    try:
        with _DB_LOCK:
            conn = _get_kline_db()
            query = "SELECT * FROM kline WHERE code=? AND open > 0"
            params: list[Any] = [code]

            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)

            query += " ORDER BY date DESC"
            rows = conn.execute(query, params).fetchall()
            data = [dict(r) for r in rows]
            conn.close()

            if not data:
                return {"data": [], "code": code, "count": 0}

            return {
                "data": data,
                "code": code,
                "name": data[0].get("name", ""),
                "count": len(data),
            }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"历史K线查询异常: {e}") from e


@router.get("/api/kline-history/stats")
def kline_stats() -> Dict[str, Any]:
    """获取历史K线数据的统计信息。"""
    try:
        with _DB_LOCK:
            conn = _get_kline_db()
            stats = conn.execute(
                "SELECT COUNT(DISTINCT code) as stocks, MIN(date) as first_date, "
                "MAX(date) as last_date, COUNT(*) as total_records "
                "FROM kline WHERE open > 0"
            ).fetchone()
            conn.close()

            return {
                "stocks": stats["stocks"],
                "first_date": stats["first_date"],
                "last_date": stats["last_date"],
                "total_records": stats["total_records"],
            }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"统计查询异常: {e}") from e


__all__ = ["router"]
