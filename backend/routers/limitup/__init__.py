"""
LimitUp router package.
"""
from fastapi import APIRouter

from . import screener, analysis, auction, seats, metrics

router = APIRouter(tags=["limitup"])

# 子路由聚合
router.include_router(screener.router)
router.include_router(analysis.router)
router.include_router(auction.router)
router.include_router(seats.router)
router.include_router(metrics.router)

__all__ = ["router", "screener", "analysis", "auction", "seats", "metrics"]
