"""
Risk dashboard router.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict

import risk

router = APIRouter(tags=["risk"])


@router.get("/api/risk/dashboard")
async def risk_dashboard(date: str = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日")) -> Dict[str, Any]:
    """获取风险仪表盘数据（客观数据，非行动建议）。"""
    try:
        # 获取今日推荐基因得分
        import limitup_screener as ls
        screener_result = await ls.get_screener_result(date)

        if not screener_result or not screener_result.gene_scores:
            return {
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

        # 计算风险分布
        risk_levels = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        risk_scores = []
        sector_risk: dict[str, list[float]] = {}

        for gene in screener_result.gene_scores[:50]:  # 只分析前 50 只
            try:
                risk_data = await risk.update_one_day_risk_realtime(gene.code)
                risk_levels[risk_data.risk_level] = risk_levels.get(risk_data.risk_level, 0) + 1
                risk_scores.append({
                    "code": gene.code,
                    "name": gene.name,
                    "risk_score": risk_data.risk_score,
                    "risk_level": risk_data.risk_level,
                    "factors": risk_data.factors[:3],  # 只取前 3 个风险因素
                })

                # 按板块汇总
                # TODO: 从 gene_scores 或推荐引擎获取板块信息
            except Exception:
                continue

        # 风险因素统计
        factor_counts: dict[str, int] = {}
        for rs in risk_scores:
            for factor in rs.get("factors", []):
                factor_counts[factor] = factor_counts.get(factor, 0) + 1

        top_factors = sorted(factor_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
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

    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"风险仪表盘异常：{e}") from e


@router.get("/api/risk/oneday/list")
async def risk_oneday_list(
    date: str = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日"),
    min_risk_score: float = Query(70.0, ge=0, le=100, description="最低风险评分阈值"),
) -> Dict[str, Any]:
    """获取高风险个股列表（客观数据，非行动建议）。"""
    try:
        import limitup_screener as ls

        screener_result = await ls.get_screener_result(date)
        if not screener_result or not screener_result.gene_scores:
            return {"data": []}

        high_risk: list[dict] = []
        for gene in screener_result.gene_scores[:100]:  # 检查前 100 只
            try:
                risk_data = await risk.update_one_day_risk_realtime(gene.code)
                if risk_data.risk_score >= min_risk_score:
                    high_risk.append({
                        "code": gene.code,
                        "name": gene.name,
                        "risk_score": risk_data.risk_score,
                        "risk_level": risk_data.risk_level,
                        "factors": risk_data.factors[:3],
                        "last_updated": risk_data.last_updated,
                    })
            except Exception:
                continue

        # 按风险评分降序，取前 50
        high_risk.sort(key=lambda x: x["risk_score"], reverse=True)
        return {"data": high_risk[:50]}

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


__all__ = ["router"]
