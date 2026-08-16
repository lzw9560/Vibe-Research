"""
Strategy router.
"""
import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

import limitup_strategy as lstrat

router = APIRouter(tags=["strategy"])


@router.get("/api/strategy/signals/{code}")
async def strategy_signals(code: str, date: str = Query(None, description="日期，格式 YYYY-MM-DD")) -> Dict[str, Any]:
    """获取个股战法匹配信号。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        signals = await lstrat.get_strategy_signals(code, date)
        return {
            "data": [
                {
                    "code": s.code,
                    "name": s.name,
                    "strategy_name": s.strategy_name,
                    "strategy_code": s.strategy_code,
                    "score": s.score,
                    "signal_strength": s.signal_strength,
                    "confidence": s.confidence,
                    "entry_price": s.entry_price,
                    "entry_condition": s.entry_condition,
                    "entry_type": s.entry_type,
                    "stop_loss": s.stop_loss,
                    "stop_loss_condition": s.stop_loss_condition,
                    "take_profit": s.take_profit,
                    "take_profit_condition": s.take_profit_condition,
                    "max_hold_days": s.max_hold_days,
                    "exit_condition": s.exit_condition,
                    "historical_win_rate": s.historical_win_rate,
                    "historical_avg_return": s.historical_avg_return,
                    "sample_size": s.sample_size,
                    "risk_reward_ratio": s.risk_reward_ratio,
                    "reasoning": s.reasoning,
                    "risk_notes": s.risk_notes,
                }
                for s in signals
            ]
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"战法信号异常：{e}") from e


@router.get("/api/strategy/registry")
async def strategy_registry() -> Dict[str, Any]:
    """获取战法库定义。"""
    try:
        registry = lstrat.get_strategy_registry()
        return {"data": registry}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"战法库获取异常：{e}") from e


@router.get("/api/strategy/backtest")
async def strategy_backtest(lookback_days: int = Query(60, ge=1, le=365)) -> Dict[str, Any]:
    """S031 R20/R22：按战法历史回测——8 战法各返 {win_rate, avg_return, sample_size, available_days}。

    只读 DB gene_scores + astock.kline（mootdx 本地），不触发 em_get；结果 12h 缓存。
    客观历史统计特征，市场有风险。
    """
    from strategies.strategy_backtest import run_strategy_backtest
    results = await asyncio.to_thread(run_strategy_backtest, lookback_days)
    return {
        "disclaimer": "历史统计特征，市场有风险，不构成投资建议。",
        "available_days": results[0].available_days if results else 0,
        "data": [
            {
                "strategy": r.strategy_name,
                "strategy_code": r.strategy_code,
                "win_rate": r.win_rate,
                "avg_return": r.avg_return,
                "sample_size": r.sample_size,
                "available_days": r.available_days,
                "note": next((s.get("note", "") for s in __import__("limitup_strategy").STRATEGY_REGISTRY if s["code"] == r.strategy_code), ""),
            }
            for r in results
        ],
    }


@router.get("/api/strategy/backtest/trades")
async def strategy_backtest_trades(
    strategy_code: str = Query(..., description="战法代码"),
    lookback_days: int = Query(60, ge=1, le=365),
) -> Dict[str, Any]:
    """S049 D8：某战法回溯交易明细懒加载——trades 含 date/code/name（前端战法展开回溯明细）。

    只跑 DB 已有日（R21 防封）；available_days 如实标样本天数。
    客观历史统计特征，市场有风险。
    """
    from strategies.strategy_backtest import list_trades
    result = await asyncio.to_thread(list_trades, strategy_code, lookback_days)
    return {
        "disclaimer": "历史统计特征，市场有风险。",
        "strategy_code": result["strategy_code"],
        "trades": result["trades"],
        "available_days": result["available_days"],
        "lookback_days": result["lookback_days"],
    }


# ===========================================================================
# S066 §3 策略特定漏斗（天气硬开关 + 3 套权重 + 质量标准）
# ===========================================================================

@router.get("/api/strategy/funnel/weather-map")
async def get_weather_strategy_map() -> Dict[str, Any]:
    """S066 §3.3 天气-策略推荐映射表（grill Q7：降级为软标注）。

    返回各天气状态对应的推荐策略 + fallback 策略。
    grill Q7 后所有非暴风雨战法对所有天气可用，此处返回的映射仅作
    "推荐标注"用途（weather_recommended），不再过滤候选。暴风雨仍硬约束。
    """
    from strategies.strategy_funnel_registry import (
        WEATHER_STRATEGY_MAP,
        WEATHER_RECOMMENDATION,
        FALLBACK_STRATEGIES,
    )
    return {
        "data": {
            "weather_strategy_map": WEATHER_STRATEGY_MAP,  # 向后兼容字段
            "weather_recommendation": {k: sorted(v) for k, v in WEATHER_RECOMMENDATION.items()},
            "fallback_strategies": FALLBACK_STRATEGIES,
        }
    }


@router.get("/api/strategy/funnel/strategies")
async def get_funnel_strategies() -> Dict[str, Any]:
    """S066 §3.2 策略特定漏斗注册表（10 策略 + storm_reversal）。

    返回每个策略的完整配置：funnel_type / weight_set / weather_regimes /
    position_params / quality_standards。
    """
    from strategies.strategy_funnel_registry import STRATEGY_FUNNEL_REGISTRY
    return {
        "data": [
            {
                "code": s.code,
                "name": s.name,
                "funnel_type": s.funnel_type,
                "weight_set": s.weight_set,
                "weather_regimes": s.weather_regimes,
                "is_primary": s.is_primary,
                "fallback": s.fallback,
                "position_params": {
                    "stop_loss_pct": s.position_params.stop_loss_pct,
                    "take_profit_pct": s.position_params.take_profit_pct,
                    "max_hold_days": s.position_params.max_hold_days,
                    "position_scale": s.position_params.position_scale,
                },
                "quality_standards": [
                    {"name": q.name, "required": q.required, "description": q.description}
                    for q in s.quality_standards
                ],
                "note": s.note,
                "activation_note": s.activation_note,
            }
            for s in STRATEGY_FUNNEL_REGISTRY
        ]
    }


@router.get("/api/strategy/funnel/calendar-factor")
async def get_calendar_factor(
    date: str = Query(..., description="信号日期 YYYY-MM-DD"),
) -> Dict[str, Any]:
    """S066 §6 日历因子仓位乘数。

    返回 (仓位乘数, 原因)：周五×0.7 / 节前末日×0.3 / 节前3日×0.5 / 周四×1.0。
    """
    from strategies.calendar_factor import calendar_factor
    mult, reason = calendar_factor(date)
    return {
        "data": {
            "date": date,
            "position_multiplier": mult,
            "reason": reason,
        }
    }


@router.get("/api/strategy/funnel/sector-cycle")
async def get_sector_cycle(
    date: str = Query(..., description="交易日 YYYY-MM-DD"),
    industry: str = Query(..., description="板块/行业名"),
) -> Dict[str, Any]:
    """S066 §5 板块周期分析（3 日时序阶段分类）。

    返回板块在周期中的位置：启动/发酵/高潮/退潮/冷门/无历史 + 修饰系数。
    """
    from strategies.sector_cycle import analyze_sector_phase
    result = analyze_sector_phase(date, industry)
    if result is None:
        return {"data": None, "note": "板块无历史数据"}
    return {
        "data": {
            "industry": result.industry,
            "count_today": result.count_today,
            "count_avg_3d": result.count_avg_3d,
            "momentum": result.momentum,
            "phase": result.phase,
            "modifier": result.modifier,
            "phase_note": result.phase_note,
        }
    }


@router.get("/api/strategy/funnel/market-kill-switch")
async def get_market_kill_switch() -> Dict[str, Any]:
    """S066 §16.4 市场级熔断检查。

    上证跌幅 > 3% / 创业板跌幅 > 4% → 不开新仓。
    无指数数据不触发（不臆造）。
    """
    from strategies.execution_model import check_market_kill_switch
    import astock
    indices = astock.index_quote()
    result = check_market_kill_switch(indices)
    return {
        "data": {
            "triggered": result.triggered,
            "reason": result.reason,
            "sh_change_pct": result.sh_change_pct,
            "gem_change_pct": result.gem_change_pct,
        }
    }


@router.get("/api/strategy/funnel/forward-test")
async def get_forward_test_summary_endpoint(
    benchmark_win_rate: float = Query(60.0, description="Phase 0b benchmark_A（信息字段，非门）"),
    min_days: int = Query(20, ge=1, le=60, description="最少交易日数"),
) -> Dict[str, Any]:
    """S066 Phase 0e 前向测试汇总（paper trading 结果，§44 合规）。

    通过标准（spec §13 ① / §44 数据支撑优先）：
    - total_days >= min_days（20 交易日）
    - win_rate >= §13.0 绝对 60%（非 benchmark×0.8 弱 degradation）
    - lift = strategy_winrate / random_baseline_winrate >= 2.0（§44：lift<2x=噪声）
    - random_baseline 已回填（universe_returns 非空，否则无法算 lift → 不通过）
    - 无崩溃（consecutive_loss < 8，kill criteria 未触发）

    前向测试期间不投真金。20 天运行需日历时间积累。
    """
    from strategies.forward_test import get_forward_test_summary
    result = get_forward_test_summary(benchmark_win_rate, min_days)
    return {
        "data": {
            "total_days": result.total_days,
            "total_recommendations": result.total_recommendations,
            "settled_count": result.settled_count,
            "win_count": result.win_count,
            "win_rate": result.win_rate,
            "avg_return": result.avg_return,
            "pass_threshold": result.pass_threshold,
            "passed": result.passed,
            "consecutive_loss": result.consecutive_loss,
            "random_baseline_win_rate": result.random_baseline_win_rate,
            "random_settled": result.random_settled,
            "lift": result.lift,
            "strategy_ci": list(result.strategy_ci),
            "random_ci": list(result.random_ci),
            "is_exploratory": result.is_exploratory,
            "universe_coverage": list(result.universe_coverage),
            "benchmark_win_rate": result.benchmark_win_rate,
            "note": result.note,
        },
        "disclaimer": "前向测试（paper trading），不投真金。历史统计特征，市场有风险。",
    }


@router.get("/api/strategy/funnel/forward-test/{signal_date}")
async def get_forward_test_daily(
    signal_date: str,
) -> Dict[str, Any]:
    """S066 Phase 0e 某信号日前向测试推荐明细。"""
    from strategies.forward_test import get_daily_recommendations
    records = get_daily_recommendations(signal_date)
    return {
        "data": records,
        "count": len(records),
    }


__all__ = ["router"]
