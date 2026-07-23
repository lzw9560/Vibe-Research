"""
Win rate router.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from win_rate_tracker import WinRateTracker, WinRateRecord, generate_strategy_adjustments, get_trends, get_sector_stats, get_strategy_stats

router = APIRouter(tags=["winrate"])
_logger = logging.getLogger(__name__)
_tracker = WinRateTracker()


@router.get("/api/winrate/stats")
async def winrate_stats(window_size: int = Query(20, ge=5, le=100)) -> Dict[str, Any]:
    """获取胜率统计。"""
    try:
        stats = _tracker.get_stats(window_size=window_size)
        return {
            "data": {
                "window_size": stats.window_size,
                "total_trades": stats.total_trades,
                "win_count": stats.win_count,
                "win_rate": stats.win_rate,
                "avg_return": stats.avg_return,
                "max_drawdown": stats.max_drawdown,
                "sharpe_ratio": stats.sharpe_ratio,
                "trend": stats.trend,
                "sector_breakdown": stats.sector_breakdown,
                "strategy_breakdown": stats.strategy_breakdown,
                "score_breakdown": stats.score_breakdown,
            }
        }
    except Exception as e:  # noqa: BLE001
        _logger.exception("胜率统计异常")
        raise HTTPException(502, "胜率统计异常，请稍后重试") from e


@router.get("/api/winrate/adjustments")
async def winrate_adjustments(window_size: int = Query(20, ge=5, le=100)) -> Dict[str, Any]:
    """获取策略调整建议。"""
    try:
        stats = _tracker.get_stats(window_size=window_size)
        adjustments = generate_strategy_adjustments(stats)
        return {"data": adjustments}
    except Exception as e:  # noqa: BLE001
        _logger.exception("策略调整建议异常")
        raise HTTPException(502, "策略调整建议异常，请稍后重试") from e


@router.get("/api/winrate/trends")
async def winrate_trends(window_size: int = Query(20, ge=5, le=100)) -> Dict[str, Any]:
    """获取胜率趋势图数据。"""
    try:
        trends = get_trends(window_size=window_size)
        return {"data": trends}
    except Exception as e:  # noqa: BLE001
        _logger.exception("胜率趋势异常")
        raise HTTPException(502, "胜率趋势异常，请稍后重试") from e


@router.get("/api/winrate/sector/{sector}")
async def winrate_sector(sector: str, window_size: int = Query(20, ge=5, le=100)) -> Dict[str, Any]:
    """获取板块胜率拆分。"""
    try:
        stats = get_sector_stats(sector=sector, window_size=window_size)
        return {"data": stats}
    except ValueError:
        raise HTTPException(404, {"detail": "Sector not found"})
    except Exception as e:  # noqa: BLE001
        _logger.exception("板块胜率异常")
        raise HTTPException(502, "板块胜率异常，请稍后重试") from e


@router.get("/api/winrate/strategy/{strategy}")
async def winrate_strategy(strategy: str, window_size: int = Query(20, ge=5, le=100)) -> Dict[str, Any]:
    """获取战法胜率拆分。"""
    try:
        stats = get_strategy_stats(strategy=strategy, window_size=window_size)
        return {"data": stats}
    except ValueError:
        raise HTTPException(404, {"detail": "Strategy not found"})
    except Exception as e:  # noqa: BLE001
        _logger.exception("战法胜率异常")
        raise HTTPException(502, "战法胜率异常，请稍后重试") from e


@router.post("/api/winrate/records")
async def add_winrate_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """录入交易记录（批量）。"""
    if not records:
        raise HTTPException(400, "records 不能为空")

    added: list[str] = []
    errors: list[dict] = []
    for idx, rec in enumerate(records):
        try:
            record = WinRateRecord(
                stock_code=str(rec.get("stock_code", "")).strip(),
                stock_name=str(rec.get("stock_name", "")).strip(),
                strategy_used=str(rec.get("strategy_used", "")).strip(),
                entry_date=str(rec.get("entry_date", "")).strip(),
                entry_price=float(rec.get("entry_price", 0)),
                exit_date=str(rec.get("exit_date", "")).strip(),
                exit_price=float(rec.get("exit_price", 0)),
                return_pct=float(rec.get("return_pct", 0)),
                is_win=bool(rec.get("is_win", False)),
                gene_score=float(rec.get("gene_score", 0) or 0),
                sti_label=str(rec.get("sti_label", "")).strip(),
                sector=str(rec.get("sector", "")).strip(),
            )
            if not record.stock_code or not record.entry_date or not record.exit_date:
                raise ValueError("stock_code / entry_date / exit_date 必填")
            _tracker.add_record(record)
            added.append(record.stock_code)
        except Exception as e:  # noqa: BLE001
            _logger.exception("录入交易记录异常，index=%s", idx)
            errors.append({"index": idx, "error": "record processing failed"})

    return {
        "data": {
            "added": added,
            "added_count": len(added),
            "errors": errors,
            "error_count": len(errors),
        }
    }


__all__ = ["router"]
