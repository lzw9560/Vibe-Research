# -*- coding: utf-8 -*-
"""S066 §16 执行与成本模型 + §15 组合级风控测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.execution_model import (
    compute_slippage,
    compute_transaction_cost,
    check_market_kill_switch,
    check_kill_criteria,
    check_portfolio_constraints,
    TransactionCost,
    MarketKillSwitch,
    KillCriteriaStatus,
    PortfolioConstraint,
    COMMISSION_RATE,
    STAMP_DUTY,
    SLIPPAGE_MIN,
    SLIPPAGE_COEFF,
    MAX_CONCURRENT_POSITIONS,
    MAX_SINGLE_POSITION,
    MAX_SECTOR_EXPOSURE,
    MIN_CASH_RESERVE,
    MAX_TOTAL_POSITION,
    KILL_STRATEGY_CONSECUTIVE_LOSS,
    KILL_PORTFOLIO_CONSECUTIVE_LOSS,
)


class TestDynamicSlippage:
    """动态滑点模型（spec §16.2）。"""

    def test_small_capital_hits_floor(self):
        """小资金 → 0.1% 下限主导。500万/8亿 = 0.000625 → 0.3%*0.000625=0.0019% → 取 0.1%。"""
        slip = compute_slippage(5_000_000, 800_000_000)
        assert slip == SLIPPAGE_MIN  # 0.001

    def test_large_capital_still_at_floor(self):
        """大资金 → 仍在下限。2亿/8亿 = 0.25 → 0.3%*0.25=0.075% → 取 0.1%。"""
        slip = compute_slippage(200_000_000, 800_000_000)
        assert slip == SLIPPAGE_MIN

    def test_huge_capital_exceeds_floor(self):
        """超大资金 → 超过下限。4亿/8亿 = 0.5 → 0.3%*0.5=0.15%。"""
        slip = compute_slippage(400_000_000, 800_000_000)
        assert slip > SLIPPAGE_MIN
        assert slip == 0.15 * 0.01  # SLIPPAGE_COEFF * 0.5

    def test_zero_daily_amount_returns_floor(self):
        """日成交额=0 → 取下限（防除零）。"""
        slip = compute_slippage(1_000_000, 0)
        assert slip == SLIPPAGE_MIN


class TestTransactionCost:
    """交易成本拆解。"""

    def test_round_trip_cost_components(self):
        """总成本 = 佣金双边 + 印花税 + 滑点双边。"""
        cost = compute_transaction_cost(1_000_000, 800_000_000)
        assert cost.commission > 0
        assert cost.stamp_duty > 0
        assert cost.slippage > 0
        assert cost.round_trip_cost == cost.commission + cost.stamp_duty + cost.slippage

    def test_stamp_duty_only_on_sell(self):
        """印花税只有卖出单边。"""
        cost = compute_transaction_cost(1_000_000, 800_000_000)
        expected_stamp = 1_000_000 * STAMP_DUTY
        assert cost.stamp_duty == round(expected_stamp, 2)

    def test_commission_both_sides(self):
        """佣金是买卖双边。"""
        cost = compute_transaction_cost(1_000_000, 800_000_000)
        expected_commission = 1_000_000 * COMMISSION_RATE * 2
        assert cost.commission == round(expected_commission, 2)


class TestMarketKillSwitch:
    """市场级熔断（spec §16.4）。"""

    def test_sh_drop_triggers(self):
        """上证跌幅 > 3% → 触发。"""
        indices = [
            {"name": "上证指数", "price": 3000, "change_pct": -3.5},
            {"name": "创业板指", "price": 2000, "change_pct": -2.0},
        ]
        result = check_market_kill_switch(indices)
        assert result.triggered is True
        assert "上证" in result.reason

    def test_gem_drop_triggers(self):
        """创业板跌幅 > 4% → 触发。"""
        indices = [
            {"name": "上证指数", "price": 3000, "change_pct": -1.0},
            {"name": "创业板指", "price": 2000, "change_pct": -4.5},
        ]
        result = check_market_kill_switch(indices)
        assert result.triggered is True
        assert "创业板" in result.reason

    def test_normal_market_no_trigger(self):
        """正常市场 → 不触发。"""
        indices = [
            {"name": "上证指数", "price": 3000, "change_pct": 0.5},
            {"name": "创业板指", "price": 2000, "change_pct": 1.2},
        ]
        result = check_market_kill_switch(indices)
        assert result.triggered is False

    def test_no_data_no_trigger(self):
        """无指数数据 → 不触发（不臆造）。"""
        result = check_market_kill_switch(None)
        assert result.triggered is False
        assert "未取得" in result.reason

    def test_empty_list_no_trigger(self):
        result = check_market_kill_switch([])
        assert result.triggered is False


class TestKillCriteria:
    """双层 kill criteria（spec §15.7）。"""

    def test_strategy_level_consecutive_loss(self):
        """策略级连亏 5 笔 → 停机。"""
        status = check_kill_criteria(consecutive_loss=5)
        assert status.strategy_killed is True
        assert "5" in status.strategy_reason

    def test_strategy_level_win_rate(self):
        """30 日胜率 < 45% → 停机。"""
        status = check_kill_criteria(consecutive_loss=0, rolling_30d_win_rate=0.40)
        assert status.strategy_killed is True
        assert "45%" in status.strategy_reason

    def test_portfolio_level_consecutive_loss(self):
        """组合级连亏 8 笔 → 停机。"""
        status = check_kill_criteria(
            consecutive_loss=0,
            portfolio_consecutive_loss=8,
        )
        assert status.portfolio_killed is True
        assert "8" in status.portfolio_reason

    def test_portfolio_level_drawdown(self):
        """最大回撤 > 15% → 停机。"""
        status = check_kill_criteria(
            consecutive_loss=0,
            max_drawdown=0.16,
        )
        assert status.portfolio_killed is True
        assert "15%" in status.portfolio_reason

    def test_no_trigger_within_limits(self):
        """正常范围内 → 不停机。"""
        status = check_kill_criteria(
            consecutive_loss=2,
            rolling_30d_win_rate=0.60,
            max_drawdown=0.05,
            portfolio_consecutive_loss=3,
        )
        assert status.strategy_killed is False
        assert status.portfolio_killed is False

    def test_both_levels_trigger(self):
        """双层同时触发。"""
        status = check_kill_criteria(
            consecutive_loss=6,
            portfolio_consecutive_loss=10,
            max_drawdown=0.20,
        )
        assert status.strategy_killed is True
        assert status.portfolio_killed is True


class TestPortfolioConstraints:
    """账户硬约束（spec §15.x）。"""

    def test_within_limits(self):
        """正常持仓 → 通过。"""
        positions = [
            {"code": "000001", "sector": "银行", "position_value": 50_000},
            {"code": "000002", "sector": "地产", "position_value": 30_000},
        ]
        result = check_portfolio_constraints(positions, 1_000_000)
        assert result.within_limits is True
        assert result.violations == []

    def test_too_many_positions(self):
        """持仓 > 5 只 → 违规。"""
        positions = [{"code": f"00000{i}", "sector": "测试", "position_value": 20_000} for i in range(6)]
        result = check_portfolio_constraints(positions, 1_000_000)
        assert result.within_limits is False
        assert any("6 只" in v for v in result.violations)

    def test_single_position_exceeds_10pct(self):
        """单股 > 10% → 违规。"""
        positions = [{"code": "000001", "sector": "银行", "position_value": 150_000}]
        result = check_portfolio_constraints(positions, 1_000_000)
        assert result.within_limits is False
        assert any("10%" in v for v in result.violations)

    def test_sector_exceeds_20pct(self):
        """单板块 > 20% → 违规。"""
        positions = [
            {"code": "000001", "sector": "银行", "position_value": 120_000},
            {"code": "000002", "sector": "银行", "position_value": 100_000},
        ]
        result = check_portfolio_constraints(positions, 1_000_000)
        assert result.within_limits is False
        assert any("银行" in v and "20%" in v for v in result.violations)

    def test_total_position_exceeds_30pct(self):
        """总仓位 > 30% → 违规。"""
        positions = [{"code": "000001", "sector": "银行", "position_value": 350_000}]
        result = check_portfolio_constraints(positions, 1_000_000)
        assert result.within_limits is False
        assert any("30%" in v for v in result.violations)

    def test_cash_below_30pct(self):
        """现金 < 30% → 违规。"""
        positions = [{"code": "000001", "sector": "银行", "position_value": 750_000}]
        result = check_portfolio_constraints(positions, 1_000_000)
        assert result.within_limits is False
        assert any("现金" in v for v in result.violations)

    def test_empty_portfolio_passes(self):
        """空仓 → 通过。"""
        result = check_portfolio_constraints([], 1_000_000)
        assert result.within_limits is True
        assert result.cash_reserve_pct == 1.0
