from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from post_market_workflow import SettlementResult


@dataclass
class SettlementInput:
    """结算输入"""
    code: str
    name: str
    strategy: str
    entry_price: float
    exit_price: float
    position_pct: float = 0.0
    signal_date: str | None = None
    settle_date: str | None = None


class SettlementEngine:
    """自动结算引擎"""

    def __init__(self) -> None:
        self.results: list[SettlementResult] = []

    def settle(self, item: SettlementInput) -> SettlementResult:
        """结算单条推荐"""
        signal_date = item.signal_date or str(date.today())
        settle_date = item.settle_date or str(date.today())
        return_pct = ((item.exit_price - item.entry_price) / item.entry_price) * 100 if item.entry_price else 0.0
        win = return_pct > 0
        hold_days = (
            datetime.strptime(settle_date, "%Y-%m-%d").toordinal()
            - datetime.strptime(signal_date, "%Y-%m-%d").toordinal()
            if signal_date and settle_date
            else 0
        )
        result = SettlementResult(
            code=item.code,
            name=item.name,
            date=settle_date,
            buy_price=item.entry_price,
            sell_price=item.exit_price,
            return_pct=return_pct,
            won=win,
            hold_days=hold_days,
            strategy_used=item.strategy,
        )
        self.results.append(result)
        return result

    def batch_settle(self, items: list[SettlementInput]) -> list[SettlementResult]:
        """批量结算"""
        return [self.settle(item) for item in items]

    def win_rate(self, strategy: str | None = None, window: int = 20) -> float:
        """计算胜率"""
        results = self.results
        if strategy:
            results = [r for r in results if r.strategy_used == strategy]
        windowed = results[-window:]
        if not windowed:
            return 0.0
        return sum(1 for r in windowed if r.won) / len(windowed)

    def summary(self) -> dict[str, Any]:
        """结算摘要"""
        if not self.results:
            return {"count": 0, "win_rate": 0.0}
        return {
            "count": len(self.results),
            "win_rate": self.win_rate(),
            "avg_return": sum(r.return_pct for r in self.results) / len(self.results),
        }
