"""
仓位建议引擎。

职责：
- 基于战法匹配结果 + 账户风险参数，给出建议仓位比例
- 输出入场价区间、止损、止盈、建议持仓天数
- 不输出具体股数/金额，仅输出比例，避免越权代客理财

S079 R7：新增 cap_by_market_phase 后处理，叠加在 advise_batch 输出之上。
"""
from __future__ import annotations

from typing import Any

from limitup_strategy import StrategySignal
from strategies.first_board_filter import PHASE_TO_CAP_TIER
from strategies.strategy_matcher import StrategyMatcher


class PositionSuggestion:
    """单只股票的仓位建议。"""

    def __init__(
        self,
        code: str,
        name: str,
        suggested_pct: float,
        confidence: str,
        entry_price_range: tuple[float, float],
        stop_loss: float,
        take_profit: float,
        matched_strategy: str,
        reasons: list[str],
    ) -> None:
        self.code = code
        self.name = name
        self.suggested_pct = suggested_pct
        self.confidence = confidence
        self.entry_price_range = entry_price_range
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.matched_strategy = matched_strategy
        self.reasons = reasons
        # S079 R7：仓位闸后处理标记（cap_by_market_phase 填充，默认空）
        self.market_phase: str | None = None
        self.market_phase_cap: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "suggested_pct": self.suggested_pct,
            "confidence": self.confidence,
            "entry_price_range": list(self.entry_price_range),
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "matched_strategy": self.matched_strategy,
            "reasons": self.reasons,
            "market_phase": self.market_phase,
            "market_phase_cap": self.market_phase_cap,
        }


class PositionAdvisor:
    """仓位建议引擎。"""

    def __init__(
        self,
        max_single_position: float = 0.3,
        max_total_position: float = 0.8,
        base_unit: float = 0.1,
    ) -> None:
        """
        Args:
            max_single_position: 单票最大仓位上限（默认 30%）
            max_total_position: 总仓位上限（默认 80%）
            base_unit: 仓位基础单位（默认 10%）
        """
        self.max_single_position = max_single_position
        self.max_total_position = max_total_position
        self.base_unit = base_unit
        self._matcher = StrategyMatcher()

    def advise(
        self, signal: StrategySignal, weather_state: str | None = None
    ) -> PositionSuggestion | None:
        """
        基于单条策略信号生成仓位建议。

        S086 R4：天气仓位软标注（不硬阻断）：
        - 暴风雨 → 仓位×0.3 建议（非强制，advice_note；不 return None 强制空仓）
        - 极端反弹 → 仓位上限降至 50%（半仓）
        - 晴天/阴天/未知 → 正常计算
        """
        if not signal or signal.confidence <= 0:
            return None

        # S086 R4：天气仓位软标注（不硬阻断）。暴风暴仓位×0.3 降为建议提示（非强制）。
        weather_cap = 1.0  # 默认不限制
        if weather_state == "暴风雨":
            weather_cap = 0.3  # 建议仓位×0.3（环境极端），不 return None 强制空仓
        if weather_state == "极端反弹":
            weather_cap = 0.5  # 仓位上限降至 50%

        # 置信度映射：high / medium / low
        if signal.confidence >= 0.7:
            confidence = "high"
            suggested_pct = min(self.base_unit * 2, self.max_single_position)
        elif signal.confidence >= 0.5:
            confidence = "medium"
            suggested_pct = self.base_unit
        else:
            confidence = "low"
            suggested_pct = self.base_unit * 0.5

        # 应用天气仓位上限
        suggested_pct = min(suggested_pct, self.max_single_position * weather_cap)

        # 入场价区间：以 entry_price 为中心 ±1%
        entry_low = round(signal.entry_price * 0.99, 2)
        entry_high = round(signal.entry_price * 1.01, 2)

        reasons = [
            f"战法「{signal.strategy_name}」匹配",
            f"信号强度 {signal.signal_strength}%",
            f"置信度映射 {signal.confidence_mapped_winrate:.0%}（非实测）",
        ]
        if weather_state and weather_state != "晴天":
            reasons.append(f"天气={weather_state}，仓位上限调整为 {int(weather_cap * 100)}%")
        if signal.matches:
            reasons.extend([m.description for m in signal.matches[:3]])

        return PositionSuggestion(
            code=signal.code,
            name=signal.name,
            suggested_pct=round(suggested_pct, 2),
            confidence=confidence,
            entry_price_range=(entry_low, entry_high),
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            matched_strategy=signal.strategy_name,
            reasons=reasons,
        )

    def advise_batch(
        self, signals: list[StrategySignal], weather_state: str | None = None
    ) -> list[PositionSuggestion]:
        """
        批量生成仓位建议，并按 suggested_pct 降序排列。
        """
        suggestions: list[PositionSuggestion] = []
        for signal in signals:
            suggestion = self.advise(signal, weather_state)
            if suggestion:
                suggestions.append(suggestion)
        suggestions.sort(key=lambda s: s.suggested_pct, reverse=True)
        return suggestions

    def summarize(self, suggestions: list[PositionSuggestion]) -> dict[str, Any]:
        """
        汇总仓位建议，返回总建议仓位、风险提示等。
        """
        total_pct = sum(s.suggested_pct for s in suggestions)
        return {
            "count": len(suggestions),
            "total_suggested_pct": round(total_pct, 2),
            "exceeds_limit": total_pct > self.max_total_position,
            "max_single_position": self.max_single_position,
            "max_total_position": self.max_total_position,
            "suggestions": [s.to_dict() for s in suggestions],
        }


# 全局单例
advisor = PositionAdvisor()


# ===========================================================================
# S079 R7：仓位闸后处理（cap_by_market_phase）
# ===========================================================================

# R7.1 三状态 cap 映射
# 绿（活跃/亢奋）= 1.0  → 不放宽，只收紧（不顶掉 weather_cap 或 max_total_position）
# 黄（普通）   = 0.5
# 红（冰点/红期）= 0.2
MARKET_PHASE_CAP: dict[str, float] = {
    "green": 1.0,
    "yellow": 0.5,
    "red": 0.2,
}


def cap_by_market_phase(
    positions: list[PositionSuggestion],
    phase: str,
    max_single_position: float = 0.3,
    max_total_position: float = 0.8,
) -> list[PositionSuggestion]:
    """S079 R7 仓位闸后处理。

    叠加在 PositionAdvisor.advise_batch 输出之上。每个 position.suggested_pct 已
    经过 weather_cap 处理（advise_batch 内部 advise 的 weather 熔断）。

    叠加代数（spec R7.1）：
        final_cap = min(weather_cap, market_phase_cap, max_total_position)

    其中：
      - weather_cap：既有，advise_batch 输出的 suggested_pct 已应用 weather_cap
      - market_phase_cap：新增，绿=1.0（不放宽）/黄=0.5/红=0.2
      - max_total_position：既有 0.8 硬上限

    绿档不放宽原则（R7.2）：market_phase_cap 绿档=1.0，
        market_phase_cap_result = min(suggested_pct, max_single_position * 1.0)
        = min(suggested_pct, max_single_position)
      不会超过既有单票上限，只收紧不放宽。

    互斥说明（R7.3）：同一情绪现象（大面股爆炸≈暴风雨）可能同时触发
      weather 熔断和 market_phase 熔断，取 min() 不冲突（取最严）。

    时序用途（R8，文档层声明）：
      STI 是 T-1 盘后总结（limitup_sti 8 维度加权 → 4 天气），用于 advise 的
      weather_state 参数；_market_phase 是 T+1 盘前仓位闸因子，用于本函数的
      phase 参数。两者时序用途不同，不引入新概念，不替代 STI。

    Args:
        positions: advise_batch 返回的 PositionSuggestion 列表
        phase: _market_phase 返回的字符串（冰点/普通/活跃/亢奋/红期）
        max_single_position: 单票仓位上限（默认 0.3，与 PositionAdvisor 默认一致）
        max_total_position: 总仓位硬上限（默认 0.8，与 PositionAdvisor 默认一致）

    Returns:
        仓位上限叠加处理后的 PositionSuggestion 列表（原地修改 + 返回）
    """
    # R7.1 三状态映射 + 未知 phase 降级 yellow（保守）
    tier = PHASE_TO_CAP_TIER.get(phase, "yellow")
    market_phase_cap = MARKET_PHASE_CAP[tier]

    for pos in positions:
        # pos.suggested_pct 已经过 weather_cap 处理（advise_batch 输出）
        weather_cap_result = pos.suggested_pct

        # market_phase_cap 叠加：min(suggested_pct, max_single_position * market_phase_cap)
        market_phase_cap_result = min(
            pos.suggested_pct,
            max_single_position * market_phase_cap,
        )

        # R7.1 叠加代数：final_cap = min(weather_cap, market_phase_cap, max_total_position)
        final_pct = min(
            weather_cap_result,
            market_phase_cap_result,
            max_total_position,
        )
        pos.suggested_pct = round(final_pct, 2)

        # R7 标记仓位闸信息（供前端展示）
        pos.market_phase = phase
        pos.market_phase_cap = market_phase_cap

    return positions
