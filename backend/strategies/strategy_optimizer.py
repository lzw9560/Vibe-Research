"""
策略自动优化器。

职责：
- 根据 WinRateTracker 的统计数据，自动调整各战法的权重
- 胜率<50% 的战法降权，胜率>60% 的战法升权
- 输出可用于 StrategyMatcher 的权重映射
"""
from __future__ import annotations

from typing import Any

from config import WINRATE_DB_PATH
from win_rate_tracker import WinRateTracker, WinRateStats


class StrategyOptimizer:
    """策略自动优化器。"""

    def __init__(self, db_path: str = WINRATE_DB_PATH) -> None:
        self._tracker = WinRateTracker(db_path=db_path)
        self._weights: dict[str, float] = {}

    def load_weights(self) -> dict[str, float]:
        """从胜率统计中加载策略权重。"""
        stats = self._tracker.get_stats(window_size=20)
        self._weights = self._compute_weights(stats)
        return self._weights

    def get_weight(self, strategy_code: str) -> float:
        """获取指定策略的当前权重。"""
        if not self._weights:
            self.load_weights()
        return self._weights.get(strategy_code, 1.0)

    def _compute_weights(self, stats: WinRateStats) -> dict[str, float]:
        """根据胜率统计计算策略权重。"""
        weights: dict[str, float] = {}
        for strategy, data in stats.strategy_breakdown.items():
            total = data.get("total", 0)
            wins = data.get("wins", 0)
            win_rate = wins / total if total else 0.5

            if win_rate < 0.5:
                weight = max(0.5, win_rate / 0.5)
            elif win_rate > 0.6:
                weight = min(1.5, 0.6 / win_rate + 0.5)
            else:
                weight = 1.0

            weights[strategy] = round(weight, 2)
        return weights

    def adjustments(self, stats: WinRateStats | None = None) -> list[dict[str, Any]]:
        """获取策略调整建议。"""
        if stats is None:
            stats = self._tracker.get_stats(window_size=20)
        adjustments: list[dict[str, Any]] = []
        for strategy, data in stats.strategy_breakdown.items():
            total = data.get("total", 0)
            wins = data.get("wins", 0)
            win_rate = wins / total if total else 0.0
            if total >= 3 and win_rate < 0.5:
                adjustments.append({
                    "strategy": strategy,
                    "win_rate": round(win_rate, 2),
                    "action": "reduce" if win_rate < 0.35 else "maintain",
                    "reason": f"近{total}笔胜率{win_rate:.1%}，低于50%阈值",
                })
        return adjustments


# 全局单例
strategy_optimizer = StrategyOptimizer()
