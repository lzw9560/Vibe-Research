"""
Health check router.
"""
from fastapi import APIRouter
from datetime import datetime
from typing import Any, Dict

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "ok": True,
        "service": "vibe-research-api",
        "version": "0.1.3"
    }


__all__ = ["router"]
