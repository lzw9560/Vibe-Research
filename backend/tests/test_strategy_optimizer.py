import unittest
from unittest.mock import MagicMock

from strategies.strategy_optimizer import StrategyOptimizer
from win_rate_tracker import WinRateStats


class TestStrategyOptimizer(unittest.TestCase):
    def test_default_weight_when_no_stats(self):
        optimizer = StrategyOptimizer()
        optimizer._weights = {}
        assert optimizer.get_weight("unknown") == 1.0

    def test_reduce_weight_when_low_win_rate(self):
        optimizer = StrategyOptimizer()
        stats = WinRateStats(
            window_size=20,
            total_trades=10,
            win_count=3,
            win_rate=0.3,
            avg_return=-1.0,
            max_drawdown=5.0,
            sharpe_ratio=-0.5,
            trend="declining",
            sector_breakdown={},
            strategy_breakdown={"弱势战法": {"total": 10, "wins": 3}},
            score_breakdown={},
        )
        weights = optimizer._compute_weights(stats)
        assert weights["弱势战法"] == 0.6

    def test_increase_weight_when_high_win_rate(self):
        optimizer = StrategyOptimizer()
        stats = WinRateStats(
            window_size=20,
            total_trades=10,
            win_count=8,
            win_rate=0.8,
            avg_return=5.0,
            max_drawdown=2.0,
            sharpe_ratio=1.5,
            trend="improving",
            sector_breakdown={},
            strategy_breakdown={"强势战法": {"total": 10, "wins": 8}},
            score_breakdown={},
        )
        weights = optimizer._compute_weights(stats)
        assert weights["强势战法"] == 1.25

    def test_maintain_weight_when_medium_win_rate(self):
        optimizer = StrategyOptimizer()
        stats = WinRateStats(
            window_size=20,
            total_trades=10,
            win_count=5,
            win_rate=0.5,
            avg_return=1.0,
            max_drawdown=3.0,
            sharpe_ratio=0.5,
            trend="stable",
            sector_breakdown={},
            strategy_breakdown={"普通战法": {"total": 10, "wins": 5}},
            score_breakdown={},
        )
        weights = optimizer._compute_weights(stats)
        assert weights["普通战法"] == 1.0

    def test_adjustments_returns_empty_when_no_low_win_rate(self):
        optimizer = StrategyOptimizer()
        stats = WinRateStats(
            window_size=20,
            total_trades=10,
            win_count=8,
            win_rate=0.8,
            avg_return=5.0,
            max_drawdown=2.0,
            sharpe_ratio=1.5,
            trend="improving",
            sector_breakdown={},
            strategy_breakdown={"强势战法": {"total": 10, "wins": 8}},
            score_breakdown={},
        )
        adjustments = optimizer.adjustments(stats)
        assert adjustments == []

    def test_adjustments_returns_reduce_when_low_win_rate(self):
        optimizer = StrategyOptimizer()
        stats = WinRateStats(
            window_size=20,
            total_trades=10,
            win_count=3,
            win_rate=0.3,
            avg_return=-1.0,
            max_drawdown=5.0,
            sharpe_ratio=-0.5,
            trend="declining",
            sector_breakdown={},
            strategy_breakdown={"弱势战法": {"total": 10, "wins": 3}},
            score_breakdown={},
        )
        adjustments = optimizer.adjustments(stats)
        assert len(adjustments) == 1
        assert adjustments[0]["strategy"] == "弱势战法"
        assert adjustments[0]["action"] == "reduce"


if __name__ == "__main__":
    unittest.main()
