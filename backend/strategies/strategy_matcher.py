"""
战法匹配引擎。

职责：
- 对候选池中的股票，逐只匹配 8 大战法
- 返回匹配结果、置信度、入场/止损/止盈建议
- 与现有 limitup_strategy.py 的 STRATEGY_REGISTRY / match_strategies 对齐
"""
from __future__ import annotations

from typing import Any

from limitup_strategy import (
    STRATEGY_REGISTRY,
    StrategySignal,
    match_strategies,
    get_strategy_registry,
)
from limitup_screener.models import GeneScore


class StrategyMatcher:
    """战法匹配引擎。"""

    def __init__(self) -> None:
        self._registry = STRATEGY_REGISTRY
        self._registry_cache: list[dict] | None = None

    @property
    def registry(self) -> list[dict]:
        """获取战法注册表（带缓存）。"""
        if self._registry_cache is None:
            self._registry_cache = get_strategy_registry()
        return self._registry_cache

    def match(self, gene: GeneScore) -> list[StrategySignal]:
        """
        对单只股票匹配所有适用战法。

        直接复用 limitup_strategy.match_strategies，保持策略逻辑单一事实来源。
        """
        return match_strategies(gene.code, gene)

    def match_batch(self, genes: list[GeneScore]) -> dict[str, list[StrategySignal]]:
        """
        批量匹配，返回 {code: signals}。
        """
        results: dict[str, list[StrategySignal]] = {}
        for gene in genes:
            results[gene.code] = self.match(gene)
        return results

    def get_best_strategy(self, gene: GeneScore) -> StrategySignal | None:
        """获取匹配度最高的战法信号（按 risk_reward_ratio * historical_win_rate 排序）。"""
        signals = self.match(gene)
        if not signals:
            return None
        return signals[0]

    def get_strategy_by_code(self, code: str) -> dict | None:
        """按 code 获取战法定义。"""
        for s in self.registry:
            if s["code"] == code:
                return s
        return None

    def list_strategies(self) -> list[dict]:
        """列出所有可用战法。"""
        return self.registry

    def clear_cache(self) -> None:
        """清除注册表缓存（战法定义更新后调用）。"""
        self._registry_cache = None


# 全局单例
matcher = StrategyMatcher()
