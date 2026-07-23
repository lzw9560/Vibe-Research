"""
Watchlist router.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import sqlite3
from typing import Any, Dict

from routers.common import _DB_LOCK, _get_db

router = APIRouter(tags=["watchlist"])


class WatchlistCodesIn(BaseModel):
    codes: list[str]


def _ensure_watchlist_table() -> None:
    """确保 watchlist 表存在。"""
    db = _get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist (
            code TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_watchlist_created_at
            ON watchlist (created_at)
        """
    )
    db.commit()


@router.get("/api/watchlist")
def watchlist_get() -> Dict[str, Any]:
    """获取自选股列表"""
    try:
        with _DB_LOCK:
            _ensure_watchlist_table()
            db = _get_db()
            rows = db.execute("SELECT code FROM watchlist ORDER BY created_at").fetchall()
            return {"codes": [r["code"] for r in rows]}
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            raise HTTPException(503, "数据库忙，请稍后重试") from e
        raise HTTPException(502, f"自选股查询异常：{e}") from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"自选股查询异常：{e}") from e


@router.post("/api/watchlist")
def watchlist_add(body: WatchlistCodesIn) -> Dict[str, Any]:
    """批量添加自选股（去重插入）"""
    try:
        with _DB_LOCK:
            _ensure_watchlist_table()
            db = _get_db()
            codes = list(dict.fromkeys(c.strip() for c in body.codes if c.strip()))  # 去重保序
            added = 0
            for code in codes:
                if not code.isdigit() or len(code) != 6:
                    continue
                try:
                    db.execute("INSERT INTO watchlist (code) VALUES (?)", (code,))
                    added += 1
                except sqlite3.IntegrityError:
                    pass  # 已存在，跳过
            db.commit()
            total = db.execute("SELECT COUNT(*) AS cnt FROM watchlist").fetchone()["cnt"]
            return {"added": added, "total": total}
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            raise HTTPException(503, "数据库忙，请稍后重试") from e
        raise HTTPException(502, f"自选股添加异常：{e}") from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"自选股添加异常：{e}") from e


@router.delete("/api/watchlist/{code}")
def watchlist_delete(code: str) -> Dict[str, Any]:
    """删除自选股"""
    try:
        with _DB_LOCK:
            _ensure_watchlist_table()
            db = _get_db()
            db.execute("DELETE FROM watchlist WHERE code=?", (code,))
            db.commit()
            return {"ok": True}
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            raise HTTPException(503, "数据库忙，请稍后重试") from e
        raise HTTPException(502, f"自选股删除异常：{e}") from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"自选股删除异常：{e}") from e


__all__ = ["router"]
