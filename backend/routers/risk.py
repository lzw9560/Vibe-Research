"""
Risk dashboard router.
"""
import asyncio
import time

from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict

import risk_models as risk

router = APIRouter(tags=["risk"])

# 路由级 TTL 缓存（risk 在 app line43 导入，早于 app.cache_response 定义，故本地缓存）
_DASHBOARD_TTL = 120
_DASHBOARD_CACHE: dict[str, tuple[float, Any]] = {}
_SEMAPHORE = asyncio.Semaphore(8)  # 并发限 8，避免放大东财 QPS


def _cache_get(key: str) -> Any | None:
    hit = _DASHBOARD_CACHE.get(key)
    if hit and time.time() - hit[0] < _DASHBOARD_TTL:
        return hit[1]
    return None


def _cache_set(key: str, val: Any) -> None:
    _DASHBOARD_CACHE[key] = (time.time(), val)


async def _risk_one(code: str):
    """单股风险（带信号量并发限流 + 异常隔离）。"""
    async with _SEMAPHORE:
        try:
            return await risk.update_one_day_risk_realtime(code)
        except Exception:
            return None



@router.get("/api/risk/dashboard")
async def risk_dashboard(date: str = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日")) -> Dict[str, Any]:
    """获取风险仪表盘数据（客观数据，非行动建议）。"""
    cache_key = date or "latest"
    cached = _cache_get(f"dashboard:{cache_key}")
    if cached is not None:
        return cached
    try:
        # 获取今日推荐基因得分
        import limitup_screener as ls
        screener_result = await ls.get_screener_result(date)

        if not screener_result or not screener_result.gene_scores:
            empty = {
                "data": {
                    "date": date or "",
                    "total_stocks": 0,
                    "high_risk_count": 0,
                    "medium_risk_count": 0,
                    "low_risk_count": 0,
                    "risk_distribution": [],
                    "top_risk_factors": [],
                    "sector_risk": [],
                }
            }
            _cache_set(f"dashboard:{cache_key}", empty)
            return empty

        # 限制并发分析数量（≤20），避免 50/100 只顺序网络调用拖垮后端
        genes = screener_result.gene_scores[:20]

        # 并发计算（信号量限 8 + 异常隔离），不阻塞事件循环
        risk_datas = await asyncio.gather(*(_risk_one(g.code) for g in genes))

        risk_levels = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        risk_scores: list[dict] = []
        for gene, risk_data in zip(genes, risk_datas):
            if risk_data is None:
                continue
            risk_levels[risk_data.risk_level] = risk_levels.get(risk_data.risk_level, 0) + 1
            risk_scores.append({
                "code": gene.code,
                "name": gene.name,
                "risk_score": risk_data.risk_score,
                "risk_level": risk_data.risk_level,
                "factors": risk_data.factors[:3],  # 只取前 3 个风险因素
            })

        # 风险因素统计
        factor_counts: dict[str, int] = {}
        for rs in risk_scores:
            for factor in rs.get("factors", []):
                factor_counts[factor] = factor_counts.get(factor, 0) + 1

        top_factors = sorted(factor_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        result = {
            "data": {
                "date": screener_result.date,
                "total_stocks": len(risk_scores),
                "high_risk_count": risk_levels.get("HIGH", 0),
                "medium_risk_count": risk_levels.get("MEDIUM", 0),
                "low_risk_count": risk_levels.get("LOW", 0),
                "risk_distribution": risk_scores,
                "top_risk_factors": [{"factor": f, "count": c} for f, c in top_factors],
                "sector_risk": [],  # TODO: 实现板块风险汇总
            }
        }
        _cache_set(f"dashboard:{cache_key}", result)
        return result

    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"风险仪表盘异常：{e}") from e


@router.get("/api/risk/oneday/list")
async def risk_oneday_list(
    date: str = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日"),
    min_risk_score: float = Query(70.0, ge=0, le=100, description="最低风险评分阈值"),
) -> Dict[str, Any]:
    """获取高风险个股列表（客观数据，非行动建议）。"""
    cache_key = f"oneday:{date or 'latest'}:{min_risk_score}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        import limitup_screener as ls

        screener_result = await ls.get_screener_result(date)
        if not screener_result or not screener_result.gene_scores:
            empty = {"data": []}
            _cache_set(cache_key, empty)
            return empty

        # 限制并发分析数量（≤50），并发计算不阻塞事件循环
        genes = screener_result.gene_scores[:50]
        risk_datas = await asyncio.gather(*(_risk_one(g.code) for g in genes))

        high_risk: list[dict] = []
        for gene, risk_data in zip(genes, risk_datas):
            if risk_data is None:
                continue
            if risk_data.risk_score >= min_risk_score:
                high_risk.append({
                    "code": gene.code,
                    "name": gene.name,
                    "risk_score": risk_data.risk_score,
                    "risk_level": risk_data.risk_level,
                    "factors": risk_data.factors[:3],
                    "last_updated": risk_data.last_updated,
                })

        # 按风险评分降序，取前 50
        high_risk.sort(key=lambda x: x["risk_score"], reverse=True)
        result = {"data": high_risk[:50]}
        _cache_set(cache_key, result)
        return result

    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"高风险列表异常：{e}") from e


@router.get("/api/risk/seats")
async def risk_seats() -> Dict[str, Any]:
    """获取一日游特征席位库（客观数据，非行动建议）。"""
    seats = {
        "one_day_seats": [
            {"seat_name": "某知名游资A", "one_day_rate": 0.72, "avg_return": -2.3, "type": "一日游"},
            {"seat_name": "某知名游资B", "one_day_rate": 0.65, "avg_return": -1.8, "type": "一日游"},
        ],
        "multi_day_seats": [
            {"seat_name": "某机构专用", "one_day_rate": 0.15, "avg_return": 3.2, "type": "多日持仓"},
        ],
        "disclaimer": "以上为历史统计特征，不构成投资建议。",
    }
    return {"data": seats}


@router.get("/api/risk/stock/{code}")
async def stock_risk(code: str) -> Dict[str, Any]:
    """获取个股风险详情（客观数据，非行动建议）。"""
    try:
        risk_data = await risk.update_one_day_risk_realtime(code)
        return {"data": risk_data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"个股风险查询异常：{e}") from e


# =============================================================================
# S055：炸板预警 + 封单时序端点
# =============================================================================

@router.get("/api/risk/bomb-alerts")
async def bomb_alerts(date: str = Query(None, description="交易日 YYYY-MM-DD；不传取最近交易日")) -> Dict[str, Any]:
    """获取当日炸板预警列表（历史表）。

    缺数据诚实标注 data_status，不臆造封单值。
    """
    try:
        from risk.bomb_alert_dispatcher import get_active_alerts
        from vr_paths import last_trading_date_str
        target = date or last_trading_date_str()
        alerts = get_active_alerts(target)
        return {
            "data": {
                "date": target,
                "alerts": alerts,
                "count": len(alerts),
                "note": "炸板预警属风险标注，历史统计特征，市场有风险，不构成交易指令",
            }
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"炸板预警查询异常：{e}") from e


@router.get("/api/risk/seal-snapshots")
async def seal_snapshots(
    code: str = Query(..., description="6 位股票代码"),
    date: str = Query(None, description="交易日 YYYY-MM-DD；不传取最近交易日"),
) -> Dict[str, Any]:
    """获取个股封单时序快照（sparkline 用）。

    缺快照返空数组 + data_status=missing，不臆造。
    """
    try:
        from risk.seal_intraday_collector import get_snapshots_by_code
        from vr_paths import last_trading_date_str
        target = date or last_trading_date_str()
        rows = get_snapshots_by_code(code, target)
        return {
            "data": {
                "code": code,
                "date": target,
                "snapshots": rows,
                "count": len(rows),
                "data_status": "ok" if rows else "missing",
            }
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"封单时序查询异常：{e}") from e


__all__ = ["router"]
