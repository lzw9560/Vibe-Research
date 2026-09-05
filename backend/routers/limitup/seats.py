"""
LimitUp seats router.
"""
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime
from typing import Any, Dict
from vr_paths import last_trading_date_str

router = APIRouter(tags=["limitup"])


@router.get("/api/limitup/seats/profiles")
async def get_seat_profiles() -> Dict[str, Any]:
    """获取所有席位画像"""
    try:
        import seat_engine as se
        engine = se.get_engine()
        raw = engine.get_all_seat_profiles()
        # Convert {name: profile} dict to {profiles: [...]} list format
        profiles = [{"name": name, **profile} for name, profile in raw.items()]
        return {"profiles": profiles, "total": len(profiles)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"席位画像获取失败: {str(e)}")


@router.get("/api/limitup/seats/profile/{seat_name:path}")
async def get_seat_profile(seat_name: str) -> Dict[str, Any]:
    """获取单个席位画像"""
    try:
        import seat_engine as se
        engine = se.get_engine()
        profile = engine.get_seat_profile(seat_name)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"席位 {seat_name} 不存在")
        return profile
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"席位画像获取失败: {str(e)}")


@router.get("/api/limitup/seats/consensus")
async def get_consensus_signal(
    stock_code: str = Query(..., description="股票代码"),
    trade_date: str = Query(None, description="交易日期 YYYY-MM-DD"),
) -> Dict[str, Any]:
    """获取某只股票的席位共识/分歧信号"""
    try:
        import seat_engine as se
        engine = se.get_engine()
        td = trade_date or last_trading_date_str()  # S149: 默认最近交易日（非今日），周末不静默空
        signal = engine.compute_consensus_signal(td, stock_code)
        if signal is None:
            return {"signal": None, "details": {}, "disclaimer": se.SEAT_DISCLAIMER}
        return signal
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"共识信号计算失败: {str(e)}")


@router.post("/api/limitup/seats/build")
async def trigger_build_profiles(lookback_days: int = Query(180, ge=30, le=365)) -> Dict[str, Any]:
    """触发席位画像冷启动构建"""
    try:
        import seat_engine as se
        engine = se.get_engine()
        result = engine.build_seat_profiles(lookback_days)
        return {"status": "ok", "profiles": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"席位画像构建失败: {str(e)}")


__all__ = ["router"]
