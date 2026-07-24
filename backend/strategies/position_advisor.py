"""
仓位建议引擎。

职责：
- 基于战法匹配结果 + 账户风险参数，给出建议仓位比例
- 输出入场价区间、止损、止盈、建议持仓天数
- 不输出具体股数/金额，仅输出比例，避免越权代客理财
"""
from __future__ import annotations

from typing import Any

from limitup_strategy import StrategySignal
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

    def advise(self, signal: StrategySignal) -> PositionSuggestion | None:
        """
        基于单条策略信号生成仓位建议。
        """
        if not signal or signal.confidence <= 0:
            return None

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

        # 入场价区间：以 entry_price 为中心 ±1%
        entry_low = round(signal.entry_price * 0.99, 2)
        entry_high = round(signal.entry_price * 1.01, 2)

        reasons = [
            f"战法「{signal.strategy_name}」匹配",
            f"信号强度 {signal.signal_strength}%",
            f"历史胜率 {signal.historical_win_rate:.0%}",
        ]
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
        self, signals: list[StrategySignal]
    ) -> list[PositionSuggestion]:
        """
        批量生成仓位建议，并按 suggested_pct 降序排列。
        """
        suggestions: list[PositionSuggestion] = []
        for signal in signals:
            suggestion = self.advise(signal)
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
