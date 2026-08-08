"""
盘后工作流（15:00-22:00）。

职责：
1. 自动结算前日推荐
2. LLM 复盘分析
3. 胜率更新
4. 参数优化
5. 生成次日策略
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SettlementResult:
    """结算结果。"""
    code: str
    name: str
    date: str
    buy_price: float
    sell_price: float
    return_pct: float
    won: bool
    hold_days: int
    strategy_used: str


@dataclass
class PostMarketReport:
    """盘后报告。"""
    date: str
    generated_at: str
    settlements: list[SettlementResult] = field(default_factory=list)
    win_rate: float = 0.0
    total_return: float = 0.0
    llm_review: str = ""
    sentiment_evolution: str = ""
    sector_rotation: str = ""
    next_day_strategy: str = ""
    next_day_candidates: list[Any] = field(default_factory=list)
    adjustments: list[str] = field(default_factory=list)


class PostMarketWorkflow:
    """盘后工作流引擎。"""

    def __init__(self, date: str | None = None):
        self.date = date or datetime.now().strftime("%Y-%m-%d")

    async def run(self) -> PostMarketReport:
        """执行盘后工作流。"""
        report = PostMarketReport(date=self.date, generated_at=datetime.now().isoformat())

        # 1. 自动结算前日推荐
        report.settlements = await self._settle_recommendations()

        # 2. 更新胜率
        report.win_rate = self._calculate_win_rate(report.settlements)
        report.total_return = sum(s.return_pct for s in report.settlements)

        # 3. LLM 复盘
        report.llm_review = await self._generate_llm_review(report)

        # 4. 生成次日策略
        report.next_day_strategy = await self._generate_next_day_strategy()

        # 5. 策略参数优化
        report.adjustments = self._optimize_strategies(report.settlements)

        return report

    async def _settle_recommendations(self) -> list[SettlementResult]:
        """结算前日推荐。"""
        # stub: 未实现，见 S036（端点 /workflow/post-market、/workflow/settle 已 early return，不触达本桩）
        # TODO: 从数据库读取前日推荐
        # TODO: 获取次日实际行情
        # TODO: 计算收益率
        return []

    def _calculate_win_rate(self, settlements: list[SettlementResult]) -> float:
        """计算胜率。"""
        if not settlements:
            return 0.0
        won = sum(1 for s in settlements if s.won)
        return round(won / len(settlements) * 100, 1)

    async def _generate_llm_review(self, report: PostMarketReport) -> str:
        """生成 LLM 复盘分析。"""
        # stub: 未实现，见 S036（端点 /workflow/post-market 已 early return，不触达本桩）
        # TODO: 接入 LLM 生成复盘报告
        return "盘后复盘功能待实现"

    async def _generate_next_day_strategy(self) -> str:
        """生成次日策略。"""
        # stub: 未实现，见 S036（端点 /workflow/post-market 已 early return，不触达本桩）
        # TODO: 基于今日数据生成次日策略
        return "次日策略待实现"

    def _optimize_strategies(self, settlements: list[SettlementResult]) -> list[str]:
        """策略参数优化。"""
        adjustments: list[str] = []

        if not settlements:
            return adjustments

        win_rate = self._calculate_win_rate(settlements)

        # 胜率 < 40% → 提高评分门槛
        if win_rate < 40:
            adjustments.append("整体胜率偏低，建议提高评分门槛至 70 分")

        # 近 10 笔胜率 < 30% → 降低仓位
        recent = settlements[-10:]
        recent_win_rate = self._calculate_win_rate(recent)
        if recent_win_rate < 30:
            adjustments.append("近 10 笔胜率偏低，建议降低仓位至 50%")

        return adjustments
