"""S216 P2: 量化模型 M2/M4 endpoint。

M2 /api/expectation-gap — 预期差（复用 pattern_scan_s205.compute_expectation_gap_reversal）
M4 /api/transport/em-health — em_get 防封健康度（复用 circuit_breaker.list_breakers）

守工程底线：不臆造（缺数据返 data_status=empty）/ 私有数据不进 / em_get 防封（M4 只报状态不裸调）。
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query
from vr_paths import last_trading_date_str

router = APIRouter(tags=["quant"])


@router.get("/api/expectation-gap")
def expectation_gap(
    code: str = Query(..., description="6 位股票代码"),
    date: str = Query(None, description="交易日 YYYY-MM-DD；不传取最近交易日"),
) -> Dict[str, Any]:
    """M2 预期差：T-1 close + T open 差（高开%）+ 开盘量比代理。

    复用 strategies.pattern_scan_s205.compute_expectation_gap_reversal（S205 维度函数）。
    返 score ∈ [0,1] + gap_pct + vol_ratio + data_status。
    缺数据（bars 不足/计算异常）返 score=0.0 + data_status，不臆造。
    """
    target = date or last_trading_date_str()
    try:
        from engine.bars_provider import KlineCacheBarsProvider
        from strategies.pattern_scan_s205 import compute_expectation_gap_reversal

        bars = KlineCacheBarsProvider()(code)
        if not bars or len(bars) < 2:
            return {
                "data": {
                    "code": code,
                    "date": target,
                    "score": 0.0,
                    "gap_pct": None,
                    "vol_ratio": None,
                    "data_status": "empty",
                    "note": "bars 不足 2 根，无法算预期差",
                }
            }
        score = compute_expectation_gap_reversal(code, target, bars=bars)
        gap_pct: float | None = None
        vol_ratio: float | None = None
        d_idx = next(
            (i for i, b in enumerate(bars) if str(b.get("date", ""))[:10] == target),
            None,
        )
        if d_idx is not None and d_idx >= 1:
            prev_close = bars[d_idx - 1].get("close")
            open_price = bars[d_idx].get("open")
            prev_vol = bars[d_idx - 1].get("volume")
            cur_vol = bars[d_idx].get("volume")
            if prev_close and open_price:
                try:
                    gap_pct = (float(open_price) - float(prev_close)) / float(prev_close) * 100
                    vol_ratio = (
                        float(cur_vol) / float(prev_vol)
                        if prev_vol and float(prev_vol) > 0
                        else None
                    )
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
        return {
            "data": {
                "code": code,
                "date": target,
                "score": round(score, 4),
                "gap_pct": round(gap_pct, 2) if gap_pct is not None else None,
                "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
                "data_status": "ok" if score > 0 else "empty",
            }
        }
    except Exception as e:  # noqa: BLE001 — honest 降级，前端显 empty 非 crash
        return {
            "data": {
                "code": code,
                "date": target,
                "score": 0.0,
                "gap_pct": None,
                "vol_ratio": None,
                "data_status": "error",
                "note": f"计算异常: {e}",
            }
        }


@router.get("/api/transport/em-health")
def em_health() -> Dict[str, Any]:
    """M4 em_get 防封健康度：circuit_breaker 各 breaker 状态。

    复用 circuit_breaker.list_breakers()（transport.py 防封底线）。
    返 per-breaker {state, failure_count} + all_healthy + data_status。
    """
    try:
        from circuit_breaker import list_breakers

        breakers = list_breakers()
        if not breakers:
            return {
                "data": {
                    "breakers": {},
                    "all_healthy": True,
                    "data_status": "empty",
                    "note": "无 circuit_breaker 注册",
                }
            }
        details = {
            name: {
                "state": br.peek_state().value,
                "failure_count": br.failure_count,
            }
            for name, br in breakers.items()
        }
        any_open = any(d["state"] == "open" for d in details.values())
        em_details = {
            k: v for k, v in details.items() if "eastmoney" in k or "em" in k
        }
        return {
            "data": {
                "breakers": details,
                "em_breakers": em_details or None,
                "all_healthy": not any_open,
                "data_status": "ok",
            }
        }
    except Exception as e:  # noqa: BLE001
        return {
            "data": {
                "breakers": {},
                "all_healthy": False,
                "data_status": "error",
                "note": f"circuit_breaker 查询异常: {e}",
            }
        }


__all__ = ["router"]
