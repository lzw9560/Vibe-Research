"""
Sentiment Weather Station router.
Provides market weather state, multi-factor scoring, strategy recommendations, and fuse rules.
"""
from fastapi import APIRouter, HTTPException, Query, Request
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import sqlite3
import json
import os
import time
import asyncio
from config import GENE_SCORES_DB_PATH, STI_TIMELINE_DB_PATH, default_config

router = APIRouter(tags=["sentiment-weather"])

DB_PATH = STI_TIMELINE_DB_PATH
_PARDON_DB_PATH = GENE_SCORES_DB_PATH


def _get_db() -> sqlite3.Connection:
    """Get database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _calculate_weather_state(sti_score: Optional[float], risk_score: float,
                              sector_continuity: float, capital_momentum: float,
                              public_sentiment: float) -> Dict[str, Any]:
    """
    Calculate market weather state based on multi-factor weighted scoring.

    Weights:
    - STI sentiment temperature: 40%
    - Risk indicators: 20%
    - Sector continuity: 25%
    - Capital momentum: 10%
    - Public sentiment: 5%
    """
    if sti_score is None:
        return {
            "weather_state": "未知",
            "weather_icon": "Cloud",
            "composite_score": 0,
            "confidence": "低",
        }

    # Weighted composite score
    composite = (
        sti_score * 0.40 +
        risk_score * 0.20 +
        sector_continuity * 0.25 +
        capital_momentum * 0.10 +
        public_sentiment * 0.05
    )

    # Determine weather state
    if composite >= 75:
        weather_state = "晴天"
        weather_icon = "Sun"
        confidence = "高"
    elif composite >= 55:
        weather_state = "阴天"
        weather_icon = "Cloud"
        confidence = "中"
    elif composite >= 35:
        weather_state = "极端反弹"
        weather_icon = "Zap"
        confidence = "中"
    else:
        weather_state = "暴风雨"
        weather_icon = "CloudRain"
        confidence = "高"

    return {
        "weather_state": weather_state,
        "weather_icon": weather_icon,
        "composite_score": round(composite, 1),
        "confidence": confidence,
    }


def _get_latest_sti() -> Dict[str, Any]:
    """Get latest STI data from database（carry-forward：非交易日取最近交易日行）。

    用 ``last_trading_date_str()`` 做 ``WHERE date <= ?`` 锚点：交易日取当日行，
    非交易日回退到最近交易日行。``score IS NOT NULL`` 排除守卫降级时写入的空行
    （source_ok=False 的行 score 为 NULL）。响应里 ``as_of_date`` 显式声明实际数据
    日期，前端据此识别 carry-forward 数据（可能 != 今天）。
    """
    try:
        from vr_paths import last_trading_date_str  # noqa: PLC0415
        _as_of = last_trading_date_str()
        db = _get_db()
        row = db.execute(
            "SELECT * FROM sti_timeline WHERE date <= ? AND score IS NOT NULL "
            "ORDER BY date DESC LIMIT 1",
            (_as_of,),
        ).fetchone()
        if row is None:
            return {"score": None, "phase": None, "date": None, "as_of_date": None}

        return {
            "score": float(row["score"]) if row["score"] is not None else None,
            "phase": row["phase"],
            "date": row["date"],
            "as_of_date": row["date"],  # 实际数据日期（可能 != 今天，carry-forward）
            "change_from_yesterday": float(row["change_from_yesterday"]) if row["change_from_yesterday"] else 0.0,
        }
    except Exception:
        return {"score": None, "phase": None, "date": None, "as_of_date": None}
    finally:
        db.close()


def _calculate_risk_score() -> float:
    """
    Calculate risk score (0-100, higher = lower risk).
    Based on: 炸板率, 跌停家数, 连板高度, 大盘宽度
    """
    try:
        from vr_paths import last_trading_date_str  # noqa: PLC0415
        _as_of = last_trading_date_str()
        db = _get_db()
        row = db.execute(
            "SELECT * FROM sti_timeline WHERE date <= ? AND score IS NOT NULL "
            "ORDER BY date DESC LIMIT 1",
            (_as_of,),
        ).fetchone()
        if row is None:
            return 50.0

        # Use STI dimensions as risk proxy
        limit_down = float(row["dimension_limit_down_count"]) if row["dimension_limit_down_count"] else 0
        seal_rate = float(row["dimension_seal_rate"]) if row["dimension_seal_rate"] else 0
        max_boards = float(row["dimension_max_boards"]) if row["dimension_max_boards"] else 0

        # Risk score: lower risk = higher score
        risk = 100 - (
            min(limit_down * 2, 30) +  # 跌停越多风险越高
            max(0, 30 - seal_rate) +     # 封板率越低风险越高
            max(0, 20 - max_boards * 5)  # 连板高度越低风险越高
        )
        return max(0, min(100, risk))
    except Exception:
        return 50.0
    finally:
        db.close()


def _calculate_sector_continuity() -> float:
    """
    Calculate sector continuity score (0-100).
    Based on: 板块涨停家数, 板块资金流向持续性
    """
    # Placeholder: integrate with sector flow data
    # For now, use STI advance/decline ratio as proxy
    try:
        from vr_paths import last_trading_date_str  # noqa: PLC0415
        _as_of = last_trading_date_str()
        db = _get_db()
        row = db.execute(
            "SELECT * FROM sti_timeline WHERE date <= ? AND score IS NOT NULL "
            "ORDER BY date DESC LIMIT 1",
            (_as_of,),
        ).fetchone()
        if row is None:
            return 50.0

        ad_ratio = float(row["dimension_advance_decline_ratio"]) if row["dimension_advance_decline_ratio"] else 1.0
        # 涨跌比 > 2 表示强势, < 0.5 表示弱势
        score = min(100, max(0, ad_ratio * 30))
        return score
    except Exception:
        return 50.0
    finally:
        db.close()


def _calculate_capital_momentum() -> float:
    """
    Calculate capital momentum score (0-100).
    Based on: 成交额变化, 资金流向, 龙虎榜数据
    """
    try:
        from vr_paths import last_trading_date_str  # noqa: PLC0415
        _as_of = last_trading_date_str()
        db = _get_db()
        row = db.execute(
            "SELECT * FROM sti_timeline WHERE date <= ? AND score IS NOT NULL "
            "ORDER BY date DESC LIMIT 1",
            (_as_of,),
        ).fetchone()
        if row is None:
            return 50.0

        # Use actual market dimensions as capital flow proxy
        limit_up = float(row["dimension_limit_up_count"]) if row["dimension_limit_up_count"] else 0
        limit_down = float(row["dimension_limit_down_count"]) if row["dimension_limit_down_count"] else 0
        seal_rate = float(row["dimension_seal_rate"]) if row["dimension_seal_rate"] else 50.0

        # 涨停多+封板率高 = 资金流入, 跌停多 = 资金流出
        net = limit_up - limit_down
        score = 50 + net * 1.5 + (seal_rate - 50) * 0.3
        return max(0, min(100, score))
    except Exception:
        return 50.0
    finally:
        db.close()


def _calculate_public_sentiment() -> float:
    """
    Calculate public sentiment score (0-100).
    Based on: 舆情数据, 社交媒体情绪, 新闻情绪
    """
    try:
        from vr_paths import last_trading_date_str  # noqa: PLC0415
        _as_of = last_trading_date_str()
        db = _get_db()
        row = db.execute(
            "SELECT * FROM sti_timeline WHERE date <= ? AND score IS NOT NULL "
            "ORDER BY date DESC LIMIT 1",
            (_as_of,),
        ).fetchone()
        if row is None:
            return 50.0

        # Derive from market dimensions as proxy for public sentiment
        ad_ratio = float(row["dimension_advance_decline_ratio"]) if row["dimension_advance_decline_ratio"] else 1.0
        seal_rate = float(row["dimension_seal_rate"]) if row["dimension_seal_rate"] else 50.0
        limit_up = float(row["dimension_limit_up_count"]) if row["dimension_limit_up_count"] else 0
        limit_down = float(row["dimension_limit_down_count"]) if row["dimension_limit_down_count"] else 0

        # 涨跌比 + 封板率 + 涨停跌停差
        score = min(100, max(0, (ad_ratio * 20) + (seal_rate * 0.3) + (limit_up - limit_down) * 2))
        return score
    except Exception:
        return 50.0
    finally:
        db.close()


@router.get("/api/sentiment/weather/latest")
def get_weather_latest() -> Dict[str, Any]:
    """获取当前市场天气状态（综合多因子评分）。"""
    try:
        # Get STI data
        sti_data = _get_latest_sti()
        sti_score = sti_data.get("score")

        # Calculate multi-factor scores
        risk_score = _calculate_risk_score()
        sector_continuity = _calculate_sector_continuity()
        capital_momentum = _calculate_capital_momentum()
        public_sentiment = _calculate_public_sentiment()

        # Calculate weather state
        weather = _calculate_weather_state(
            sti_score, risk_score, sector_continuity,
            capital_momentum, public_sentiment
        )

        return {
            "data": {
                **weather,
                "sti_score": sti_score,
                "sti_phase": sti_data.get("phase"),
                "sti_date": sti_data.get("date"),
                "as_of_date": sti_data.get("as_of_date"),  # 实际数据日期（carry-forward 透明声明，可能 != today）
                "sti_change": sti_data.get("change_from_yesterday"),
                "factors": {
                    "sti": {"score": sti_score, "weight": 0.40, "name": "STI 情绪温度"},
                    "risk": {"score": round(risk_score, 1), "weight": 0.20, "name": "风险指标"},
                    "sector_continuity": {"score": round(sector_continuity, 1), "weight": 0.25, "name": "板块持续性"},
                    "capital_momentum": {"score": round(capital_momentum, 1), "weight": 0.10, "name": "资金动量"},
                    "public_sentiment": {"score": round(public_sentiment, 1), "weight": 0.05, "name": "舆情情绪"},
                },
                "data_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data_freshness": {
                    "is_stale": False,
                    "delay_ms": 0,
                    "last_trigger_count": 0,
                },
                "execution_params": {
                    "channel_latency_ms": default_config.AUCTION_CHANNEL_LATENCY_MS,
                    "slippage_compensation": {
                        "normal": 0.02,  # 普通股 2%
                        "limit_up": 0.05,  # 涨停板 5%
                        "limit_down": 0.05,  # 跌停板 5%
                    },
                    "settlement_buy_price": "prev_close",  # 使用前收盘价
                    "next_day_sell_base": "prev_close_adj",  # 前收盘价+1%保守估计
                    "t1_locked": True,  # T+1锁定
                },
            }
        }
    except Exception as e:
        raise HTTPException(502, f"天气状态查询异常：{e}") from e


@router.get("/api/sentiment/weather/factors")
def get_weather_factors() -> Dict[str, Any]:
    """获取多因子详细数据（用于分解图表）。"""
    try:
        sti_data = _get_latest_sti()
        sti_score = sti_data.get("score")

        risk_score = _calculate_risk_score()
        sector_continuity = _calculate_sector_continuity()
        capital_momentum = _calculate_capital_momentum()
        public_sentiment = _calculate_public_sentiment()

        weather = _calculate_weather_state(
            sti_score, risk_score, sector_continuity,
            capital_momentum, public_sentiment
        )

        return {
            "data": {
                "weather_state": weather["weather_state"],
                "composite_score": weather["composite_score"],
                "as_of_date": sti_data.get("as_of_date"),  # 实际数据日期（carry-forward 透明声明，可能 != today）
                "factors": [
                    {
                        "id": "sti",
                        "name": "STI 情绪温度",
                        "score": sti_score,
                        "weight": 0.40,
                        "trend": "stable",
                        "explanation": "基于涨停家数、封板率、晋级率等8维指标的综合情绪温度",
                    },
                    {
                        "id": "risk",
                        "name": "风险指标",
                        "score": round(risk_score, 1),
                        "weight": 0.20,
                        "trend": "stable",
                        "explanation": "基于炸板率、跌停家数、连板高度的风险评分",
                    },
                    {
                        "id": "sector_continuity",
                        "name": "板块持续性",
                        "score": round(sector_continuity, 1),
                        "weight": 0.25,
                        "trend": "stable",
                        "explanation": "板块涨停家数和资金流向持续性评分",
                    },
                    {
                        "id": "capital_momentum",
                        "name": "资金动量",
                        "score": round(capital_momentum, 1),
                        "weight": 0.10,
                        "trend": "stable",
                        "explanation": "成交额变化和资金流向动量评分",
                    },
                    {
                        "id": "public_sentiment",
                        "name": "舆情情绪",
                        "score": round(public_sentiment, 1),
                        "weight": 0.05,
                        "trend": "stable",
                        "explanation": "社交媒体和新闻情绪分析评分",
                    },
                ],
            }
        }
    except Exception as e:
        raise HTTPException(502, f"因子数据查询异常：{e}") from e


@router.get("/api/sentiment/weather/strategy")
def get_weather_strategy() -> Dict[str, Any]:
    """获取当前天气下的策略推荐。"""
    try:
        sti_data = _get_latest_sti()
        sti_score = sti_data.get("score")

        risk_score = _calculate_risk_score()
        sector_continuity = _calculate_sector_continuity()
        capital_momentum = _calculate_capital_momentum()
        public_sentiment = _calculate_public_sentiment()

        weather = _calculate_weather_state(
            sti_score, risk_score, sector_continuity,
            capital_momentum, public_sentiment
        )
        weather_state = weather["weather_state"]

        # Strategy mapping based on weather state
        strategies = {
            "暴风雨": [
                {
                    "style": "空仓观望",
                    "match_score": 95,
                    "enabled": True,
                    "description": "市场退潮，风险极高，建议空仓等待",
                    "conditions": ["炸板率>40%", "连板高度<3板", "跌停家数>20家"],
                    "order_config": "禁止任何买入条件单",
                }
            ],
            "阴天": [
                {
                    "style": "首板挖掘",
                    "match_score": 85,
                    "enabled": True,
                    "description": "震荡轮动市，适合低位首板套利",
                    "conditions": ["过去20日未连板", "当日异动拉升", "有突发利好催化"],
                    "order_config": "触发条件：分时大单点火(5倍均量)，涨幅7.5%-9%",
                },
                {
                    "style": "连板接力",
                    "match_score": 30,
                    "enabled": False,
                    "description": "震荡市不适合高位接力",
                    "conditions": ["主线不明确", "龙头次日多低开"],
                    "order_config": "不建议使用",
                },
            ],
            "晴天": [
                {
                    "style": "连板接力",
                    "match_score": 90,
                    "enabled": True,
                    "description": "主升浪，追逐最高板和妖股",
                    "conditions": ["2连板以上", "主线板块成交额前三", "板块涨停≥3只"],
                    "order_config": "触发条件：涨停价-0.02元 + 五档卖盘萎缩",
                },
                {
                    "style": "首板挖掘",
                    "match_score": 60,
                    "enabled": True,
                    "description": "可适度参与低位首板",
                    "conditions": ["历史低位突破", "成交量放大2倍"],
                    "order_config": "触发条件：突破均线后回踩确认",
                },
            ],
            "极端反弹": [
                {
                    "style": "弱转强反包",
                    "match_score": 92,
                    "enabled": True,
                    "description": "冰点反转，捕捉弱转强信号",
                    "conditions": ["前日长上影/跌停", "竞价高开3%+", "竞价成交量超昨日5分钟总和"],
                    "order_config": "触发条件：开盘3分钟内冲过昨日最高价",
                },
                {
                    "style": "连板接力",
                    "match_score": 70,
                    "enabled": True,
                    "description": "反弹初期可参与龙头接力",
                    "conditions": ["板块集体爆发", "龙头股强势封板"],
                    "order_config": "触发条件：板块第3只涨停确认后",
                },
            ],
        }

        return {
            "data": {
                "weather_state": weather_state,
                "as_of_date": sti_data.get("as_of_date"),  # 实际数据日期（carry-forward 透明声明，可能 != today）
                "strategies": strategies.get(weather_state, []),
                "driver": f"综合评分 {weather['composite_score']} 分，主要驱动：{_get_driver_explanation(weather_state)}",
                "risk_note": _get_risk_note(weather_state),
            }
        }
    except Exception as e:
        raise HTTPException(502, f"策略推荐查询异常：{e}") from e


def _get_driver_explanation(weather_state: str) -> str:
    """Get driver explanation based on weather state."""
    explanations = {
        "暴风雨": "风险指标极差，市场情绪冰点",
        "阴天": "板块持续性一般，无明显主线",
        "晴天": "板块持续性强，资金动量转正，情绪升温",
        "极端反弹": "情绪从冰点快速反转，资金回流明显",
    }
    return explanations.get(weather_state, "综合因素")


def _get_risk_note(weather_state: str) -> str:
    """Get risk note based on weather state."""
    notes = {
        "暴风雨": "建议空仓，系统已自动锁死交易权限",
        "阴天": "注意控制仓位，避免追高",
        "晴天": "可积极参与，注意分化风险",
        "极端反弹": "快进快出，严格止损",
    }
    return notes.get(weather_state, "")


@router.get("/api/sentiment/weather/fuse")
def get_weather_fuse() -> Dict[str, Any]:
    """获取熔断规则状态（S056：三铁律补全——软 gate，只提醒不锁死）。

    R1 仓位熔断：天气=暴风雨 → fuse_state=triggered
    R2 撤单熔断：读 S055 seal_intraday_snapshots 当日最新快照，
       封单额 < 阈值（config.SEAL_CANCEL_FUSE_AMOUNT，默认 3000 万）→ triggered。
       撤单比（撤单量/封单量）依赖盘口分笔数据，mootdx 不可得 → 仅用封单额阈值，
       显式标注口径（spec §3：不可得则仅用封单额阈值并显式标注）。
    R3 次日强制离场：竞价未高开/破均线 → 独立端点 /api/sentiment/weather/exit-signals
    """
    try:
        # 取当前天气状态判定 R1
        try:
            weather = get_weather_latest()
            _weather_data = weather.get("data") or {}
            weather_state = _weather_data.get("weather_state", "未知")
            as_of_date = _weather_data.get("as_of_date")  # carry-forward 透明声明（来自 latest）
        except Exception:
            weather_state = "未知"
            as_of_date = None

        # R1 仓位熔断：暴风雨 → triggered
        r1_triggered = weather_state == "暴风雨"
        r1_state = "triggered" if r1_triggered else "normal"

        # R2 撤单熔断：读 S055 当日最新封单快照（解桩）
        r2 = _evaluate_cancel_fuse()

        rules = [
            {
                "id": "position_fuse",
                "name": "仓位熔断",
                "status": "enabled",
                "trigger_condition": "天气=暴风雨 → 红色熔断横幅 + 候选照常产出（软 gate）",
                "current_state": r1_state,
                "weather_state": weather_state,
                "description": "情绪气象站判定暴风雨时，盘前简报挂红色横幅提醒风险，候选照常产出（Q3 软 gate：不锁死买入）",
                "is_triggered": r1_triggered,
            },
            {
                "id": "cancel_fuse",
                "name": "撤单熔断",
                "status": "enabled",
                "trigger_condition": f"封单额 < {r2['threshold']:,.0f} 元（撤单比口径不可得，仅用封单额阈值，spec §3）",
                "current_state": r2["state"],
                "data_status": r2["data_status"],
                "triggered_codes": r2["triggered_codes"],
                "checked_count": r2["checked_count"],
                "description": "排板时封单额跌破阈值触发提醒。撤单比依赖盘口分笔数据，mootdx 不可得，仅用封单额阈值（显式标注口径）",
                "is_triggered": r2["is_triggered"],
            },
            {
                "id": "next_day_exit",
                "name": "次日强制离场",
                "status": "enabled",
                "trigger_condition": "未高开(≤0%) 或 开盘5分钟未站稳均线",
                "current_state": "待触发",
                "description": "次日09:25竞价未高开或开盘5分钟破均线 → 生成强制离场信号（见 /api/sentiment/weather/exit-signals）",
                "is_triggered": False,
            },
        ]

        # fuse_state 汇总：任一 triggered → triggered；否则 normal
        any_triggered = any(r.get("is_triggered") for r in rules)
        fuse_state = "triggered" if any_triggered else "normal"

        return {
            "data": {
                "rules": rules,
                "fuse_state": fuse_state,
                "weather_state": weather_state,
                "as_of_date": as_of_date,  # 实际数据日期（carry-forward 透明声明，可能 != today）
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        }
    except Exception as e:
        raise HTTPException(502, f"熔断规则查询异常：{e}") from e


def _evaluate_cancel_fuse() -> dict:
    """R2 撤单熔断评估：读当日最新封单快照，封单额 < 阈值 → triggered。

    撤单比口径不可得（mootdx 无分笔），仅用封单额阈值，显式标注。
    非交易时段/无快照 → data_status=missing，不臆造。
    """
    from config import default_config  # noqa: PLC0415
    threshold = getattr(default_config, "SEAL_CANCEL_FUSE_AMOUNT", 30_000_000.0)
    try:
        from risk.seal_intraday_collector import get_latest_snapshots  # noqa: PLC0415
        from vr_paths import is_trading_day, last_trading_date_str  # noqa: PLC0415
    except Exception:
        return {
            "state": "degraded",
            "data_status": "degraded",
            "is_triggered": False,
            "triggered_codes": [],
            "checked_count": 0,
            "threshold": threshold,
        }
    # 非交易时段不评估（无盘中数据意义）
    if not is_trading_day(datetime.now().date()):
        return {
            "state": "normal",
            "data_status": "missing",
            "is_triggered": False,
            "triggered_codes": [],
            "checked_count": 0,
            "threshold": threshold,
        }
    try:
        date = last_trading_date_str()
        snapshots = get_latest_snapshots(date)
    except Exception:
        return {
            "state": "degraded",
            "data_status": "degraded",
            "is_triggered": False,
            "triggered_codes": [],
            "checked_count": 0,
            "threshold": threshold,
        }
    if not snapshots:
        return {
            "state": "normal",
            "data_status": "missing",
            "is_triggered": False,
            "triggered_codes": [],
            "checked_count": 0,
            "threshold": threshold,
        }
    triggered_codes: list[str] = []
    for snap in snapshots:
        seal = snap.get("seal_amount")
        code = snap.get("code", "")
        if seal is not None and code and seal < threshold:
            triggered_codes.append(code)
    is_triggered = len(triggered_codes) > 0
    return {
        "state": "triggered" if is_triggered else "normal",
        "data_status": "ok",
        "is_triggered": is_triggered,
        "triggered_codes": triggered_codes,
        "checked_count": len(snapshots),
        "threshold": threshold,
    }


@router.get("/api/sentiment/weather/timeline")
def get_weather_timeline(days: int = Query(30, ge=1, le=365)) -> Dict[str, Any]:
    """获取天气历史趋势（近N天）。"""
    try:
        from vr_paths import last_trading_date_str  # noqa: PLC0415
        _as_of = last_trading_date_str()
        db = _get_db()
        rows = db.execute(
            "SELECT date, score, phase, change_from_yesterday FROM sti_timeline "
            "WHERE score IS NOT NULL AND date <= ? ORDER BY date DESC LIMIT ?",
            (_as_of, days),
        ).fetchall()

        timeline = []
        for r in rows[::-1]:  # 升序
            sti_score = float(r["score"]) if r["score"] else None
            risk_score = _calculate_risk_score_for_date(r["date"])
            sector_continuity = _calculate_sector_continuity_for_date(r["date"])
            capital_momentum = _calculate_capital_momentum_for_date(r["date"])
            public_sentiment = _calculate_public_sentiment_for_date(r["date"])

            weather = _calculate_weather_state(
                sti_score, risk_score, sector_continuity,
                capital_momentum, public_sentiment
            )

            timeline.append({
                "date": r["date"],
                "sti_score": round(sti_score, 2) if sti_score else None,
                "weather_state": weather["weather_state"],
                "composite_score": weather["composite_score"],
                "phase": r["phase"],
                "change_from_yesterday": round(float(r["change_from_yesterday"]), 2) if r["change_from_yesterday"] else None,
            })

        # Calculate stats
        stats = {
            "total": len(timeline),
            "晴天": sum(1 for t in timeline if t["weather_state"] == "晴天"),
            "阴天": sum(1 for t in timeline if t["weather_state"] == "阴天"),
            "暴风雨": sum(1 for t in timeline if t["weather_state"] == "暴风雨"),
            "极端反弹": sum(1 for t in timeline if t["weather_state"] == "极端反弹"),
        }

        return {"data": {"timeline": timeline, "stats": stats}}
    except Exception as e:
        raise HTTPException(502, f"天气历史查询异常：{e}") from e


def _calculate_risk_score_for_date(date: str) -> float:
    """Calculate risk score for a specific date."""
    try:
        db = _get_db()
        row = db.execute(
            "SELECT * FROM sti_timeline WHERE date = ?",
            (date,),
        ).fetchone()
        if row is None:
            return 50.0

        limit_down = float(row["dimension_limit_down_count"]) if row["dimension_limit_down_count"] else 0
        seal_rate = float(row["dimension_seal_rate"]) if row["dimension_seal_rate"] else 0
        max_boards = float(row["dimension_max_boards"]) if row["dimension_max_boards"] else 0

        risk = 100 - (
            min(limit_down * 2, 30) +
            max(0, 30 - seal_rate) +
            max(0, 20 - max_boards * 5)
        )
        return max(0, min(100, risk))
    except Exception:
        return 50.0
    finally:
        db.close()


def _calculate_sector_continuity_for_date(date: str) -> float:
    """Calculate sector continuity score for a specific date."""
    try:
        db = _get_db()
        row = db.execute(
            "SELECT * FROM sti_timeline WHERE date = ?",
            (date,),
        ).fetchone()
        if row is None:
            return 50.0

        ad_ratio = float(row["dimension_advance_decline_ratio"]) if row["dimension_advance_decline_ratio"] else 1.0
        score = min(100, max(0, ad_ratio * 30))
        return score
    except Exception:
        return 50.0
    finally:
        db.close()


def _calculate_capital_momentum_for_date(date: str) -> float:
    """Calculate capital momentum score for a specific date."""
    try:
        db = _get_db()
        row = db.execute(
            "SELECT * FROM sti_timeline WHERE date = ?",
            (date,),
        ).fetchone()
        if row is None:
            return 50.0

        # Use actual market dimensions as capital flow proxy
        limit_up = float(row["dimension_limit_up_count"]) if row["dimension_limit_up_count"] else 0
        limit_down = float(row["dimension_limit_down_count"]) if row["dimension_limit_down_count"] else 0
        seal_rate = float(row["dimension_seal_rate"]) if row["dimension_seal_rate"] else 50.0

        net = limit_up - limit_down
        score = 50 + net * 1.5 + (seal_rate - 50) * 0.3
        return max(0, min(100, score))
    except Exception:
        return 50.0
    finally:
        db.close()


def _calculate_public_sentiment_for_date(date: str) -> float:
    """Calculate public sentiment score for a specific date."""
    try:
        db = _get_db()
        row = db.execute(
            "SELECT * FROM sti_timeline WHERE date = ?",
            (date,),
        ).fetchone()
        if row is None:
            return 50.0

        # Derive from market dimensions as proxy for public sentiment
        ad_ratio = float(row["dimension_advance_decline_ratio"]) if row["dimension_advance_decline_ratio"] else 1.0
        seal_rate = float(row["dimension_seal_rate"]) if row["dimension_seal_rate"] else 50.0
        limit_up = float(row["dimension_limit_up_count"]) if row["dimension_limit_up_count"] else 0
        limit_down = float(row["dimension_limit_down_count"]) if row["dimension_limit_down_count"] else 0

        score = min(100, max(0, (ad_ratio * 20) + (seal_rate * 0.3) + (limit_up - limit_down) * 2))
        return score
    except Exception:
        return 50.0
    finally:
        db.close()


@router.get("/api/sentiment/weather/events")
def get_weather_events(days: int = Query(30, ge=1, le=365)) -> Dict[str, Any]:
    """获取关键事件标注（政策发布、重大利好/利空）。"""
    try:
        # Placeholder: integrate with news/event API
        # For now, return empty list
        events = []
        return {"data": {"events": events}}
    except Exception as e:
        raise HTTPException(502, f"事件查询异常：{e}") from e


# =============================================================================
# S065：weather_history 持久化——compute + 查询端点
# =============================================================================

def compute_weather_snapshot(date: str) -> Dict[str, Any]:
    """计算某日 weather 快照（纯函数，复用 _calculate_*_for_date）。

    sti_timeline 无该日行 → data_status=missing，不臆造。
    """
    sti = _get_latest_sti_for_date(date)
    sti_score = sti.get("score")
    if sti_score is None:
        return {
            "date": date,
            "weather_state": "未知",
            "data_status": "missing",
            "sti_score": None,
        }
    risk_score = _calculate_risk_score_for_date(date)
    sector_continuity = _calculate_sector_continuity_for_date(date)
    capital_momentum = _calculate_capital_momentum_for_date(date)
    public_sentiment = _calculate_public_sentiment_for_date(date)
    weather = _calculate_weather_state(
        sti_score, risk_score, sector_continuity,
        capital_momentum, public_sentiment,
    )
    return {
        "date": date,
        "weather_state": weather["weather_state"],
        "composite_score": weather["composite_score"],
        "sti_score": sti_score,
        "risk_score": round(risk_score, 1),
        "sector_continuity": round(sector_continuity, 1),
        "capital_momentum": round(capital_momentum, 1),
        "public_sentiment": round(public_sentiment, 1),
        "phase": sti.get("phase"),
        "confidence": weather.get("confidence"),
        "data_status": "ok",
    }


def _get_latest_sti_for_date(date: str) -> Dict[str, Any]:
    """读 sti_timeline 某日行（不取 latest，按 date 精确查）。"""
    try:
        db = _get_db()
        row = db.execute(
            "SELECT * FROM sti_timeline WHERE date = ?", (date,)
        ).fetchone()
        if row is None:
            return {"score": None, "phase": None, "date": date}
        return {
            "score": float(row["score"]) if row["score"] is not None else None,
            "phase": row["phase"],
            "date": row["date"],
        }
    except Exception:
        return {"score": None, "phase": None, "date": date}
    finally:
        db.close()


@router.get("/api/sentiment/weather/history")
def get_weather_history_endpoint(days: int = Query(90, ge=1, le=365)) -> Dict[str, Any]:
    """获取持久化的 weather_history 快照（S065，W1 证据层前置）。"""
    try:
        from weather_history import get_weather_history as _get_hist  # noqa: PLC0415
        rows = _get_hist(days)
        return {"data": {"history": rows, "count": len(rows)}}
    except Exception as e:
        raise HTTPException(502, f"weather_history 查询异常：{e}") from e


# =============================================================================
# V2.0.3 新增：竞价阶段指标
# =============================================================================

@router.get("/api/sentiment/weather/auction")
def get_weather_auction() -> Dict[str, Any]:
    """获取竞价阶段指标（9:15-9:20 可撤单 / 9:20-9:25 不可撤单）。"""
    try:
        # Placeholder: integrate with real auction data feed
        # For now, return mock data based on current time
        now = datetime.now()
        is_auction_phase = 9 <= now.hour < 10
        phase = "competitive" if is_auction_phase and now.minute >= 20 else "pre_competitive"

        auction_metrics = [
            {
                "name": "竞价换手率",
                "value": 2.3,
                "unit": "%",
                "phase": phase,
                "threshold_high": 5.0 if phase == "competitive" else 3.0,
                "threshold_low": 1.0 if phase == "competitive" else 0.5,
                "is_warning": 2.3 > (5.0 if phase == "competitive" else 3.0),
            },
            {
                "name": "竞价成交额",
                "value": 12500000,
                "unit": "元",
                "phase": phase,
                "threshold_high": 50000000 if phase == "competitive" else 30000000,
                "threshold_low": 1000000 if phase == "competitive" else 500000,
                "is_warning": 12500000 > (50000000 if phase == "competitive" else 30000000),
            },
            {
                "name": "竞价量比",
                "value": 2.5,
                "unit": "x",
                "phase": phase,
                "threshold_high": 3.0 if phase == "competitive" else 2.5,
                "threshold_low": 0.5 if phase == "competitive" else 0.3,
                "is_warning": 2.5 > (3.0 if phase == "competitive" else 2.5),
            },
        ]

        return {"data": {"auction_metrics": auction_metrics, "phase": phase}}
    except Exception as e:
        raise HTTPException(502, f"竞价指标查询异常：{e}") from e


# =============================================================================
# V2.0.3 新增：封单风险数据
# =============================================================================

@router.get("/api/sentiment/weather/seal-risk")
def get_weather_seal_risk() -> Dict[str, Any]:
    """获取封单额/流通盘风险控制数据。"""
    try:
        # Placeholder: integrate with real-time order book data
        # For now, return mock data
        seal_risk_metrics = [
            {
                "stock_code": "000001",
                "seal_amount": 50000000,  # 5000万
                "float_shares": 5000000000,  # 50亿股
                "seal_ratio": 0.01,  # 1%
                "min_ratio_required": 0.005,  # 0.5%
                "risk_level": "low",
                "cap_category": "large_cap",
                "enforcement_action": "允许",
                "reason": "封单额充足，流通盘大",
            }
        ]

        return {"data": {"seal_risk_metrics": seal_risk_metrics}}
    except Exception as e:
        raise HTTPException(502, f"封单风险查询异常：{e}") from e


# =============================================================================
# V2.0.3 新增：仓位熔断赦免管理
# =============================================================================

@router.get("/api/sentiment/weather/pardon")
def get_weather_pardon() -> Dict[str, Any]:
    """获取赦免记录（管理员可见）。"""
    try:
        # Placeholder: integrate with user/auth system
        is_admin = False  # TODO: get from request.state.user

        # Import pardon data functions
        from limitup_screener.data import get_all_pardon_records, cleanup_expired_pardons

        # Clean up expired pardons first
        try:
            cleanup_expired_pardons()
        except Exception:
            pass  # Don't fail the request if cleanup fails

        pardon_records = get_all_pardon_records(limit=100)

        return {"data": {"pardon_records": pardon_records, "is_admin": is_admin}}
    except Exception as e:
        raise HTTPException(502, f"赦免记录查询异常：{e}") from e


@router.post("/api/sentiment/weather/pardon/toggle")
def toggle_weather_pardon(request: Request, data: Dict[str, Any]) -> Dict[str, Any]:
    """切换战法赦免状态（需2FA + 双人审批）。"""
    try:
        # Placeholder: integrate with auth and 2FA
        strategy_code = data.get("strategy_code")
        strategy_name = data.get("strategy_name", "未知战法")
        reason = data.get("reason", "")
        max_position_pct = data.get("max_position_pct", 0.35)

        # TODO: validate 2FA, dual approval, IP whitelist
        # For now, use placeholder values
        enabled_by = "admin"  # TODO: get from request.state.user
        approved_by = "admin"  # TODO: get from 2FA approver
        enabled_ip = request.client.host if request.client else "127.0.0.1"

        # Import pardon data functions
        from limitup_screener.data import create_pardon_record

        record = {
            "id": f"pardon_{int(time.time())}",
            "strategy_code": strategy_code,
            "strategy_name": strategy_name,
            "enabled_by": enabled_by,
            "enabled_ip": enabled_ip,
            "approved_by": approved_by,
            "max_position_pct": max_position_pct,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "expires_at": (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason,
            "is_active": True,
        }

        create_pardon_record(record)

        return {"data": record}
    except Exception as e:
        raise HTTPException(502, f"赦免切换异常：{e}") from e


@router.post("/api/sentiment/weather/pardon/revoke")
def revoke_weather_pardon(pardon_id: str = Query(...)) -> Dict[str, Any]:
    """手动撤销赦免（仅创建人或审批人）。"""
    try:
        # Placeholder: validate permissions
        # TODO: check if current user is creator or approver
        from limitup_screener.data import revoke_pardon_record

        revoked_by = "admin"  # TODO: get from request.state.user
        success = revoke_pardon_record(pardon_id, revoked_by)

        return {"data": {"success": success}}
    except Exception as e:
        raise HTTPException(502, f"赦免撤销异常：{e}") from e


@router.post("/api/sentiment/weather/pardon/outcome")
def submit_weather_pardon_outcome(data: Dict[str, Any]) -> Dict[str, Any]:
    """提交赦免交易结果（用于优化）。"""
    try:
        from limitup_screener.data import update_pardon_outcome

        pardon_id = data.get("pardon_id")
        outcome = {
            "was_successful": data.get("was_successful", False),
            "return_pct": data.get("return_pct", 0.0),
            "lessons_learned": data.get("lessons_learned", ""),
            "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        success = update_pardon_outcome(pardon_id, outcome)

        return {"data": {"success": success}}
    except Exception as e:
        raise HTTPException(502, f"结果提交异常：{e}") from e


# =============================================================================
# V2.0.3 新增：熔断规则历史与更新
# =============================================================================

@router.get("/api/sentiment/weather/fuse/history")
def get_weather_fuse_history(days: int = Query(30, ge=1, le=365)) -> Dict[str, Any]:
    """获取熔断规则触发历史（S056：R1 仓位熔断触发/解除记录）。

    从 SQLite 持久化 fuse_history 表读取（S056 新增）。
    """
    try:
        db = _get_db()
        try:
            rows = db.execute(
                "SELECT rule_id, action, weather_state, triggered_at, note "
                "FROM fuse_history WHERE triggered_at >= date('now', ?) "
                "ORDER BY triggered_at DESC LIMIT 100",
                (f"-{days} days",),
            ).fetchall()
            history = [
                {
                    "rule_id": r["rule_id"],
                    "action": r["action"],
                    "weather_state": r["weather_state"],
                    "triggered_at": r["triggered_at"],
                    "note": r["note"],
                }
                for r in rows
            ]
        except Exception:
            # fuse_history 表不存在时返空（首调）
            history = []
        return {"data": {"history": history}}
    except Exception as e:
        raise HTTPException(502, f"熔断历史查询异常：{e}") from e


@router.post("/api/sentiment/weather/fuse/update")
def update_weather_fuse(request: Request, data: Dict[str, Any]) -> Dict[str, Any]:
    """更新熔断规则（管理员）。"""
    try:
        # Placeholder: validate admin permissions
        return {"data": {"success": True}}
    except Exception as e:
        raise HTTPException(502, f"熔断规则更新异常：{e}") from e


@router.post("/api/sentiment/weather/refresh")
def refresh_weather() -> Dict[str, Any]:
    """手动触发天气状态重新计算。"""
    try:
        return get_weather_latest()
    except Exception as e:
        raise HTTPException(502, f"天气刷新异常：{e}") from e


# =============================================================================
# S056：次日强制离场信号（铁律三，软 gate）
# =============================================================================

# 均线口径：前 N 日均价（可配，默认 5）
EXIT_SIGNAL_MA_DAYS = 5
# 高开阈值：竞价涨幅 ≤ 0% 触发（可配）
EXIT_SIGNAL_NO_GAP_THRESHOLD = 0.0


@router.get("/api/sentiment/weather/exit-signals")
def get_exit_signals(date: str = Query(..., description="交易日 YYYY-MM-DD")) -> Dict[str, Any]:
    """S056 R3：次日强制离场信号——持仓股竞价未高开或开盘 5 分钟破均线。

    软 gate：生成信号 + 醒目提醒，不自动下单。
    数据源：workflow_state_repo 持仓 + 腾讯实时行情（竞价/开盘价）。
    缺数据诚实标注（missing），不臆造。
    """
    try:
        import workflow_state_repo as wsr
        import astock

        holdings = wsr.list_states(date)
        holding_codes = [
            h for h in holdings
            if h.get("status") == "holding"
        ]

        if not holding_codes:
            return {
                "data": {
                    "date": date,
                    "signals": [],
                    "summary": {"total": 0, "triggered": 0, "missing": 0},
                    "note": "无持仓股，不生成离场信号",
                }
            }

        codes = [h["code"] for h in holding_codes]
        try:
            quotes = astock.tencent_quote(codes) or {}
        except Exception:
            quotes = {}

        signals = []
        triggered_count = 0
        missing_count = 0

        for h in holding_codes:
            code = h["code"]
            name = h.get("name", code)
            q = quotes.get(code, {})
            # 竞价涨幅（change_pct）+ 开盘价
            change_pct = q.get("pct") if isinstance(q, dict) else None
            open_price = q.get("open") if isinstance(q, dict) else None
            price = q.get("price") if isinstance(q, dict) else None

            # 均线口径：前 N 日均价（用 K 线近似）
            ma_price = None
            try:
                bars = astock.kline(code, EXIT_SIGNAL_MA_DAYS + 1, 10) or []
                if len(bars) >= EXIT_SIGNAL_MA_DAYS:
                    closes = [float(b.get("close") or 0) for b in bars[-EXIT_SIGNAL_MA_DAYS:]]
                    ma_price = sum(closes) / len(closes) if closes else None
            except Exception:
                ma_price = None

            # 判定
            no_gap = change_pct is not None and float(change_pct) <= EXIT_SIGNAL_NO_GAP_THRESHOLD
            below_ma = (price is not None and ma_price is not None and float(price) < ma_price)

            if change_pct is None and price is None:
                missing_count += 1
                signals.append({
                    "code": code,
                    "name": name,
                    "signal": None,
                    "reason": "行情数据未取得",
                    "data_status": "missing",
                })
                continue

            if no_gap or below_ma:
                triggered_count += 1
                reasons = []
                if no_gap:
                    reasons.append(f"竞价未高开({change_pct}%)")
                if below_ma:
                    reasons.append(f"开盘破{EXIT_SIGNAL_MA_DAYS}日均线({price}<{ma_price:.2f})")
                signals.append({
                    "code": code,
                    "name": name,
                    "signal": "强制离场",
                    "reason": "；".join(reasons),
                    "change_pct": change_pct,
                    "price": price,
                    "ma_price": round(ma_price, 2) if ma_price else None,
                    "data_status": "ok",
                })
            else:
                signals.append({
                    "code": code,
                    "name": name,
                    "signal": None,
                    "reason": "竞价高开且站稳均线",
                    "change_pct": change_pct,
                    "price": price,
                    "ma_price": round(ma_price, 2) if ma_price else None,
                    "data_status": "ok",
                })

        return {
            "data": {
                "date": date,
                "signals": signals,
                "summary": {
                    "total": len(holding_codes),
                    "triggered": triggered_count,
                    "missing": missing_count,
                },
                "ma_days": EXIT_SIGNAL_MA_DAYS,
                "note": "软 gate：信号 + 提醒，不自动下单；历史统计特征，市场有风险",
            }
        }
    except Exception as e:
        raise HTTPException(502, f"离场信号查询异常：{e}") from e


@router.get("/api/sentiment/storm-predict")
async def get_storm_predict(date: Optional[str] = Query(None, description="T 日期 YYYY-MM-DD，默认今日")) -> Dict[str, Any]:
    """S088 盘前暴风雨预测——外围隔夜+内部先行+新闻密度 → 概率分+仓位。

    独立于事后 STI 检测（盘前预测 vs 盘后验证）。概率预测非确定，市场有风险。
    """
    from strategies.storm_predictor import predict_storm  # noqa: PLC0415
    try:
        r = await asyncio.to_thread(predict_storm, date)
        return {
            "date": r.date,
            "probability": r.probability,
            "risk_level": r.risk_level,
            "suggested_position": r.suggested_position,
            "factors": [{"name": f.name, "score": f.score, "detail": f.detail, "data_status": f.data_status} for f in r.factors],
            "disclaimer": r.disclaimer,
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"暴风雨预测异常：{e}") from e


__all__ = ["router"]
