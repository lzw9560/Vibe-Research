"""
盘前工作流（08:00-09:30）。

职责：
1. 获取昨日涨停板数据 + 龙虎榜
2. 资金流向分析
3. 情绪周期计算
4. 候选池筛选（八项标准过滤）
5. 战法匹配（8大战法自动匹配）
6. 仓位建议
7. 生成盘前报告
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from limitup_screener.models import (
    GENE_HIGH_THRESHOLD,
    GENE_QUALIFY_THRESHOLD,
    GeneScore,
    ScreenerResult,
    compute_gene_score,
)
from limitup_screener.service import get_screener_result
from limitup_strategy import StrategySignal
from strategies.strategy_matcher import StrategyMatcher
from strategies.position_advisor import PositionAdvisor
from workflow_state_machine import WorkflowStatus, WorkflowStateMachine

logger = logging.getLogger(__name__)


@dataclass
class CandidatePool:
    """候选池。"""
    date: str
    candidates: list[GeneScore]
    strong_candidates: list[GeneScore]
    filtered_out: list[dict]
    sector_distribution: dict[str, int]


@dataclass
class StrategyMatch:
    """战法匹配结果。"""
    code: str
    name: str
    matched_strategies: list[StrategySignal]
    best_strategy: str
    confidence: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_pct: float
    reasons: list[str]


@dataclass
class PositionSuggestion:
    """仓位建议。"""
    code: str
    name: str
    suggested_pct: float
    confidence: str
    entry_price_range: tuple[float, float]
    stop_loss: float
    take_profit: float
    matched_strategy: str
    reasons: list[str]


@dataclass
class PreMarketReport:
    """盘前报告。"""
    date: str
    generated_at: str
    sentiment_index: float | None = None
    sentiment_phase: str | None = None
    candidates: list[GeneScore] = field(default_factory=list)
    strong_candidates: list[GeneScore] = field(default_factory=list)
    filtered_out: list[dict] = field(default_factory=list)
    strategy_matches: list[StrategyMatch] = field(default_factory=list)
    position_suggestions: list[PositionSuggestion] = field(default_factory=list)
    total_suggested_position: float = 0.0
    warnings: list[str] = field(default_factory=list)


class PreMarketWorkflow:
    """盘前工作流引擎。"""

    def __init__(self, date: str | None = None):
        self.date = date or self._resolve_date()
        self.state_machine = WorkflowStateMachine(WorkflowStatus.PENDING)
        self._strategy_matcher = StrategyMatcher()
        self._position_advisor = PositionAdvisor()

    def _resolve_date(self) -> str:
        """解析日期，回推到最近交易日。"""
        today = datetime.now().strftime("%Y-%m-%d")
        for back in range(5):
            d = (datetime.now() - timedelta(days=back)).strftime("%Y-%m-%d")
            # TODO: 接入交易日历
            return d
        return today

    async def run(self) -> PreMarketReport:
        """执行盘前工作流。"""
        report = PreMarketReport(date=self.date, generated_at=datetime.now().isoformat())

        # 1. 获取涨停池数据
        try:
            screener_result = await get_screener_result(self.date)
            report.candidates = screener_result.qualified
            report.strong_candidates = screener_result.high_gene
        except Exception as e:
            logger.exception("获取涨停池失败: date=%s", self.date)
            report.warnings.append(f"获取涨停池失败: {e}")
            return report

        # 2. 候选池筛选
        pool = self._build_candidate_pool(screener_result)
        report.candidates = pool.candidates
        report.strong_candidates = pool.strong_candidates
        report.filtered_out = pool.filtered_out

        # 3. 战法匹配（使用 StrategyMatcher）——匹配全部 qualified（S031 R15 去 [:20] 上限）
        for stock in pool.candidates:
            try:
                signals = self._strategy_matcher.match(stock)
                if signals:
                    best = signals[0]
                    match = StrategyMatch(
                        code=stock.code,
                        name=stock.name,
                        matched_strategies=signals,
                        best_strategy=best.strategy_name,
                        confidence="高" if best.confidence >= 0.7 else "中" if best.confidence >= 0.5 else "低",
                        entry_price=best.entry_price,
                        stop_loss=best.stop_loss,
                        take_profit=best.take_profit,
                        position_pct=0.0,
                        reasons=[m.description for m in best.matches[:3]],
                    )
                    report.strategy_matches.append(match)
            except Exception as e:
                logger.debug("个股策略分析跳过: %s %s", stock.code, e)

        # 4. 仓位建议（使用 PositionAdvisor）
        suggestions = self._position_advisor.advise_batch(
            [s for m in report.strategy_matches for s in m.matched_strategies]
        )
        report.position_suggestions = suggestions
        report.total_suggested_position = sum(p.suggested_pct for p in suggestions)

        # 5. 情绪周期（复用现有 STI）
        try:
            from limitup_sti.service import get_sti_latest
            sti = await get_sti_latest()
            if sti:
                report.sentiment_index = sti.get("score")
                report.sentiment_phase = sti.get("phase")
        except Exception as e:
            logger.debug("获取 STI 失败: %s", e)

        return report

    def _build_candidate_pool(self, screener_result: ScreenerResult) -> CandidatePool:
        """构建候选池。"""
        candidates = screener_result.qualified
        strong_candidates = screener_result.high_gene
        filtered_out: list[dict] = []

        # 八项标准过滤（简化版）
        for stock in screener_result.gene_scores:
            if stock not in candidates and stock not in strong_candidates:
                filtered_out.append({
                    "code": stock.code,
                    "name": stock.name,
                    "reason": "基因得分未达标",
                })

        sector_distribution: dict[str, int] = {}
        for stock in candidates:
            # TODO: 从数据中提取板块信息
            sector = "未知"
            sector_distribution[sector] = sector_distribution.get(sector, 0) + 1

        return CandidatePool(
            date=screener_result.date,
            candidates=candidates,
            strong_candidates=strong_candidates,
            filtered_out=filtered_out,
            sector_distribution=sector_distribution,
        )
