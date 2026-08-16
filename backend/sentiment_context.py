# -*- coding: utf-8 -*-
"""S063 T2：SentimentContext —— 情绪管线头部一次采集、逐级下传。

设计决策（spec §2.2 + HANDOFF 决策 2）：
- 盘前读 T-1 的 STI/weather_state，**不实时计算**（T-1 硬标准）。
- `build_context(decision_date)` 在管线头部构造一次，下传给
  PreMarketBriefing / resolve_thresholds / StrategyMatcher / PositionAdvisor /
  Funnel / IntradayMonitor。
- 天气计算复用 `routers.sentiment_weather._calculate_weather_state`（单一事实源），
  不在本模块重写——避免 8 维度→天气映射逻辑分叉。
- 战法适配复用 `limitup_strategy.calc_weather_fit`。
- 熔断状态复用 `routers.sentiment_weather.get_weather_fuse` 端点逻辑（同步函数调用）。

数据来源：`sti_timeline` 表 T-1 行（上一交易日）。首日或 DB 空 → 全 None，
WeatherDecisionBar 显示"情绪数据未取得"，阈值降级基数（spec §7 风险降级）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from limitup_sti.data import get_db, load_last_score
from limitup_sti.models import STIResult


@dataclass
class SentimentContext:
    """情绪管线头部上下文（T-1 硬标准）。

    一次采集、逐级下传；不可变（frozen=False 因 dataclass 默认，但调用方
    不应 mutate——如需修改建新实例）。
    """
    source_date: str | None            # T-1 日期（数据来源日）
    decision_date: str                 # T 日期（决策适用日）
    weather_state: str | None          # 晴天/阴天/暴风雨/极端反弹/未知
    sti_score: float | None            # T-1 STI 分数
    sti_phase: str | None              # T-1 STI 阶段
    fuse_state: dict[str, Any] | None  # 三条熔断规则状态
    allowed_styles: list[str] = field(default_factory=list)   # 今日允许的战法 code 列表
    forbidden_styles: list[str] = field(default_factory=list)  # 今日禁用的战法 code 列表
    composite_score: float | None = None  # 多因子综合分
    factors: dict[str, Any] | None = None   # 5 因子明细
    change_from_yesterday: float | None = None  # STI 较前日变化
    data_status: str = "ok"            # ok | missing（T-1 数据缺失）

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 安全结构（供简报响应/快照持久化）。"""
        return {
            "source_date": self.source_date,
            "decision_date": self.decision_date,
            "weather_state": self.weather_state,
            "sti_score": self.sti_score,
            "sti_phase": self.sti_phase,
            "fuse_state": self.fuse_state,
            "allowed_styles": self.allowed_styles,
            "forbidden_styles": self.forbidden_styles,
            "composite_score": self.composite_score,
            "factors": self.factors,
            "change_from_yesterday": self.change_from_yesterday,
            "data_status": self.data_status,
        }


def _load_t1_sti_row(decision_date: str) -> dict[str, Any] | None:
    """从 sti_timeline 读 T-1 行（date < decision_date 的最近一行）。

    STI 盘后定时任务（T3）确保 T-1 行已计算并持久化。
    首日或 DB 空 → None。
    """
    try:
        db = get_db()
        row = db.execute(
            "SELECT * FROM sti_timeline "
            "WHERE date < ? AND score IS NOT NULL "
            "ORDER BY date DESC LIMIT 1",
            (decision_date,),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def _empty_context(decision_date: str) -> SentimentContext:
    """T-1 数据缺失时的降级 context（全 None，阈值降级基数）。"""
    return SentimentContext(
        source_date=None,
        decision_date=decision_date,
        weather_state=None,
        sti_score=None,
        sti_phase=None,
        fuse_state=None,
        allowed_styles=[],
        forbidden_styles=[],
        composite_score=None,
        factors=None,
        change_from_yesterday=None,
        data_status="missing",
    )


def build_context(decision_date: str) -> SentimentContext:
    """构造 SentimentContext（管线头部一次采集）。

    Args:
        decision_date: T 日期（决策适用日，YYYY-MM-DD）

    Returns:
        SentimentContext：source_date=T-1，weather_state 基于 T-1 STI 算出。
        T-1 数据缺失 → 全 None 降级 context。
    """
    t1_row = _load_t1_sti_row(decision_date)
    if t1_row is None:
        return _empty_context(decision_date)

    source_date = t1_row["date"]
    sti_score = float(t1_row["score"]) if t1_row["score"] is not None else None
    sti_phase = t1_row["phase"]
    change = float(t1_row["change_from_yesterday"]) if t1_row["change_from_yesterday"] else None

    # 复用 sentiment_weather 的天气计算（单一事实源，避免映射分叉）
    weather_state, composite_score, factors = _compute_weather_from_row(t1_row, sti_score)

    # 战法适配度：遍历 8 战法，标注允许/禁用
    allowed, forbidden = _compute_allowed_styles(weather_state)

    # 熔断状态（复用 sentiment_weather 同步逻辑）
    fuse_state = _compute_fuse_state(weather_state)

    return SentimentContext(
        source_date=source_date,
        decision_date=decision_date,
        weather_state=weather_state,
        sti_score=sti_score,
        sti_phase=sti_phase,
        fuse_state=fuse_state,
        allowed_styles=allowed,
        forbidden_styles=forbidden,
        composite_score=composite_score,
        factors=factors,
        change_from_yesterday=change,
        data_status="ok",
    )


def _compute_weather_from_row(
    t1_row: dict[str, Any], sti_score: float | None
) -> tuple[str | None, float | None, dict[str, Any] | None]:
    """复用 sentiment_weather 的多因子天气计算，但只读 T-1 行（不重新查 DB）。

    sentiment_weather 的 _calculate_risk_score 等函数各自查 latest 行——这里
    我们已有 T-1 行，直接就地算，避免 5 次重复 DB 查询。
    """
    if sti_score is None:
        return None, None, None

    try:
        from routers.sentiment_weather import _calculate_weather_state
    except Exception:
        return None, None, None

    def _safe_float(v: Any, default: float = 0.0) -> float:
        try:
            return float(v) if v is not None else default
        except (ValueError, TypeError):
            return default

    limit_down = _safe_float(t1_row.get("dimension_limit_down_count"))
    seal_rate = _safe_float(t1_row.get("dimension_seal_rate"), 50.0)
    max_boards = _safe_float(t1_row.get("dimension_max_boards"))
    ad_ratio = _safe_float(t1_row.get("dimension_advance_decline_ratio"), 1.0)
    limit_up = _safe_float(t1_row.get("dimension_limit_up_count"))

    # 风险指标（0-100，越高=风险越低）——对齐 _calculate_risk_score
    risk = 100 - (
        min(limit_down * 2, 30)
        + max(0, 30 - seal_rate)
        + max(0, 20 - max_boards * 5)
    )
    risk_score = max(0.0, min(100.0, risk))

    # 板块持续性 —— 对齐 _calculate_sector_continuity
    sector_continuity = min(100.0, max(0.0, ad_ratio * 30))

    # 资金动量 —— 对齐 _calculate_capital_momentum
    net = limit_up - limit_down
    capital_momentum = max(0.0, min(100.0, 50 + net * 1.5 + (seal_rate - 50) * 0.3))

    # 舆情情绪 —— 对齐 _calculate_public_sentiment
    public_sentiment = min(100.0, max(0.0, (ad_ratio * 20) + (seal_rate * 0.3) + (limit_up - limit_down) * 2))

    weather = _calculate_weather_state(
        sti_score, risk_score, sector_continuity, capital_momentum, public_sentiment
    )

    factors = {
        "sti": {"score": sti_score, "weight": 0.40, "name": "STI 情绪温度"},
        "risk": {"score": round(risk_score, 1), "weight": 0.20, "name": "风险指标"},
        "sector_continuity": {"score": round(sector_continuity, 1), "weight": 0.25, "name": "板块持续性"},
        "capital_momentum": {"score": round(capital_momentum, 1), "weight": 0.10, "name": "资金动量"},
        "public_sentiment": {"score": round(public_sentiment, 1), "weight": 0.05, "name": "舆情情绪"},
    }

    return (
        weather.get("weather_state"),
        weather.get("composite_score"),
        factors,
    )


def _compute_allowed_styles(weather_state: str | None) -> tuple[list[str], list[str]]:
    """遍历 8 战法，标注允许/禁用。

    grill Q7：天气硬开关降级为软标注——所有战法都 allowed（不强禁），暴风雨唯一例外。
    天气推荐集合通过 WEATHER_RECOMMENDATION 查（前端用 weather_recommended 标注）。
    weather_state 为 None/未知 → 全 allowed。
    """
    try:
        from limitup_strategy import STRATEGY_REGISTRY
    except Exception:
        return [], []

    all_codes = [s["code"] for s in STRATEGY_REGISTRY]

    # grill Q7：暴风雨仍硬约束——只允许 storm_reversal，其余 forbidden
    if weather_state == "暴风雨":
        return ["storm_reversal"], [c for c in all_codes if c != "storm_reversal"]

    # 其他天气：全 allowed，不强禁（天气推荐用 WEATHER_RECOMMENDATION 软标注）
    return all_codes, []


def _compute_fuse_state(weather_state: str | None) -> dict[str, Any]:
    """复用 sentiment_weather 熔断逻辑（R1 仓位熔断：暴风雨→triggered）。

    不调 HTTP 端点（避免请求开销），直接复用 get_weather_fuse 的判定逻辑。
    返回 {fuse_state, weather_state, rules} 结构。
    """
    r1_triggered = weather_state == "暴风雨"
    rules = [
        {
            "id": "position_fuse",
            "name": "仓位熔断",
            "current_state": "triggered" if r1_triggered else "normal",
            "weather_state": weather_state or "未知",
            "is_triggered": r1_triggered,
        },
        {
            "id": "cancel_fuse",
            "name": "撤单熔断",
            "current_state": "待S055",
            "is_triggered": False,
        },
        {
            "id": "next_day_exit",
            "name": "次日强制离场",
            "current_state": "待触发",
            "is_triggered": False,
        },
    ]
    any_triggered = any(r.get("is_triggered") for r in rules)
    return {
        "fuse_state": "triggered" if any_triggered else "normal",
        "weather_state": weather_state or "未知",
        "rules": rules,
    }
