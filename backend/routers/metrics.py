"""
System performance metrics router.
"""
from fastapi import APIRouter, HTTPException
from typing import Any, Dict

from metrics_collector import collector

router = APIRouter(tags=["metrics"])


# ===========================================================================
# 性能三层拆分模型（PRD BLOCKER-3）
# ===========================================================================

class PerformanceTiers:
    """性能三层拆分"""

    # 第一层：数据获取层（目标 <8s）
    DATA_FETCH = {
        "target": 8.0,  # 秒
        "components": {
            "http_request": "并发批量请求（asyncio.gather）",
            "parsing": "增量解析，避免全量重处理",
            "caching": "TTL缓存 + 本地SQLite兜底",
        }
    }

    # 第二层：计算层（目标 <60s）
    COMPUTE = {
        "target": 60.0,  # 秒
        "components": {
            "gene_scoring": "五因子并行计算",
            "sti_calculation": "九维加权 + 百分位归一化",
            "recommendation": "推荐等级 + 仓位建议",
            "risk_assessment": "一日游风险 + 战法匹配",
        }
    }

    # 第三层：展示层（目标 <500ms）
    API_RESPONSE = {
        "target": 0.5,  # 秒
        "components": {
            "query": "数据库索引优化",
            "serialization": "Pydantic模型缓存",
            "transport": "HTTP/2 + gzip压缩",
        }
    }


# ===========================================================================
# 性能监控端点
# ===========================================================================

@router.get("/api/metrics/data_fetch")
def get_data_fetch_metrics() -> Dict[str, Any]:
    """数据获取层耗时指标。"""
    stats = collector.get_tier_stats("data_fetch")
    return {
        "tier": "data_fetch",
        "target": PerformanceTiers.DATA_FETCH["target"],
        "components": PerformanceTiers.DATA_FETCH["components"],
        "stats": stats,
        "status": "live" if stats["count"] > 0 else "no_data",
    }


@router.get("/api/metrics/compute")
def get_compute_metrics() -> Dict[str, Any]:
    """计算层耗时指标。"""
    stats = collector.get_tier_stats("compute")
    return {
        "tier": "compute",
        "target": PerformanceTiers.COMPUTE["target"],
        "components": PerformanceTiers.COMPUTE["components"],
        "stats": stats,
        "status": "live" if stats["count"] > 0 else "no_data",
    }


@router.get("/api/metrics/api_response")
def get_api_response_metrics() -> Dict[str, Any]:
    """API 响应耗时指标。"""
    stats = collector.get_tier_stats("api_response")
    return {
        "tier": "api_response",
        "target": PerformanceTiers.API_RESPONSE["target"],
        "components": PerformanceTiers.API_RESPONSE["components"],
        "stats": stats,
        "status": "live" if stats["count"] > 0 else "no_data",
    }


@router.get("/api/metrics/breakdown")
def get_performance_breakdown() -> Dict[str, Any]:
    """三层拆分详情。"""
    all_stats = collector.get_all_stats()
    return {
        "tiers": {
            "data_fetch": {**PerformanceTiers.DATA_FETCH, "stats": all_stats["data_fetch"]},
            "compute": {**PerformanceTiers.COMPUTE, "stats": all_stats["compute"]},
            "api_response": {**PerformanceTiers.API_RESPONSE, "stats": all_stats["api_response"]},
        },
        "summary": {
            "total_target": sum([
                PerformanceTiers.DATA_FETCH["target"],
                PerformanceTiers.COMPUTE["target"],
                PerformanceTiers.API_RESPONSE["target"],
            ]),
            "unit": "seconds",
            "total_samples": all_stats["total"]["count"],
        },
        "recent": collector.get_recent_samples(10),
        "status": "live" if all_stats["total"]["count"] > 0 else "no_data",
    }
