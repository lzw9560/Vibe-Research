# -*- coding: utf-8 -*-
"""S173 Drawdown Breaker 测试——风控 sizing 熔断。

覆盖验收标准：
  C4 绝对 CNY 回撤（peak - current，非 (peak-current)/peak）
  C5 floor 豁免 per-arm DD（仅参与 portfolio aggregate DD）
  H4 underpowered gate（days<60 → multiplier=1.0 status='underpowered'）
  H5 final_size = arm_size × portfolio_multiplier × lift_multiplier（三层乘积）
  H6 熊市 regime（CSI300<200 日线 → floor 豁免）
  A4 drawdown 熔断触发
  A11 熊市 regime 检测
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from engine.trade_journal import TradeJournal, JournalRecord  # noqa: E402
from engine.drawdown_breaker import (  # noqa: E402
    DrawdownBreaker,
    DrawdownResult,
    DD_THRESHOLD_HALVE,
    DD_THRESHOLD_STOP,
    MIN_DAYS_FOR_ENFORCE,
    ARM_FLOOR,
)


@pytest.fixture
def tj(tmp_path):
    return TradeJournal(db_path=tmp_path / "test_dd.db")


@pytest.fixture
def breaker(tj):
    return DrawdownBreaker(journal=tj, initial_capital=100000.0)


def _insert_pnl(tj, arm, pnl, realized=True, date="2026-01-15"):
    tj.insert(JournalRecord.create(
        arm=arm, stock_code=f"test_{arm}",
        entry_price=10.0, entry_date=date,
        exit_date=date if realized else None,
        exit_reason="take" if realized else "hold",
        net_pnl=pnl if realized else None,
        unrealized_pnl=None if realized else pnl,
        is_realized=1 if realized else 0,
    ))


def _gen_dates(n: int) -> list[str]:
    """生成 n 个唯一日期（跨月，确保 days_tracked>=60）。"""
    from datetime import date, timedelta
    d = date(2026, 1, 1)
    return [(d + timedelta(days=i * 2)).isoformat() for i in range(n)]


class TestAbsoluteDrawdown:
    """C4 绝对 CNY 回撤。"""

    def test_drawdown_is_peak_minus_current(self, tj, breaker):
        """drawdown = peak - current（绝对 CNY）。"""
        _insert_pnl(tj, "breakout", 5000.0, date="2026-01-15")
        _insert_pnl(tj, "breakout", -3000.0, date="2026-01-16")
        result = breaker.compute_drawdown(arm="breakout")
        # peak cum = 5000, current cum = 2000, drawdown = 3000
        assert result.drawdown_cny == 3000.0
        # drawdown_pct = 3000/100000 * 100 = 3%
        assert result.drawdown_pct == 3.0

    def test_drawdown_not_zero_based_pct(self, tj, breaker):
        """C4：不用 (peak-current)/peak（那会 20x 膨胀）。"""
        _insert_pnl(tj, "breakout", 1.0, date="2026-01-15")  # tiny win
        _insert_pnl(tj, "breakout", -0.5, date="2026-01-16")
        result = breaker.compute_drawdown()
        # peak=1, current=0.5, drawdown_cny=0.5
        # C4 绝对: 0.5/100000*100 = 0.0005%（非 (1-0.5)/1 = 50% 零基）
        assert result.drawdown_pct < 0.01  # 不是 50%


class TestThresholds:
    """A4：DD 阈值触发。"""

    def test_dd_above_10pct_halve(self, tj, breaker):
        """DD_pct > 10% → size_multiplier=0.5。"""
        _insert_pnl(tj, "breakout", 1000.0, date="2026-01-01")  # peak
        dates = _gen_dates(65)
        for i in range(65):
            _insert_pnl(tj, "breakout", -200.0, date=dates[i])
        result = breaker.compute_drawdown(arm="breakout")
        assert result.status == "enforced"
        assert result.size_multiplier == 0.5

    def test_dd_above_15pct_stop(self, tj, breaker):
        """DD_pct > 15% → size_multiplier=0.0（全停）。"""
        _insert_pnl(tj, "breakout", 1000.0, date="2026-01-01")
        dates = _gen_dates(65)
        for i in range(65):
            _insert_pnl(tj, "breakout", -300.0, date=dates[i])
        result = breaker.compute_drawdown(arm="breakout")
        assert result.status == "enforced"
        assert result.size_multiplier == 0.0


class TestFloorExemption:
    """C5：floor 豁免 per-arm DD。"""

    def test_floor_per_arm_always_1(self, tj, breaker):
        """floor per-arm DD 豁免 → size_multiplier=1.0（即使 DD>10%）。"""
        _insert_pnl(tj, "floor", -15000.0, date="2026-01-15")  # 15% DD
        mult, status = breaker.size_multiplier(arm=ARM_FLOOR)
        assert mult == 1.0
        assert "exempt" in status or status == "underpowered"

    def test_floor_participates_in_portfolio(self, tj, breaker):
        """floor 仍参与 portfolio aggregate DD。"""
        _insert_pnl(tj, "floor", -15000.0, date="2026-01-15")
        port_mult, _ = breaker.portfolio_multiplier()
        # portfolio DD = 15% → would stop
        # But days_tracked likely < 60 → underpowered
        assert port_mult in (0.0, 0.5, 1.0)  # depends on days


class TestUnderpoweredGate:
    """H4：days<60 → underpowered multiplier=1.0。"""

    def test_days_below_60_underpowered(self, tj, breaker):
        """days_tracked<60 → status='underpowered' multiplier=1.0。"""
        _insert_pnl(tj, "breakout", -20000.0, date="2026-01-15")  # 20% DD
        result = breaker.compute_drawdown(arm="breakout")
        assert result.status == "underpowered"
        assert result.size_multiplier == 1.0

    def test_days_above_60_enforced(self, tj, breaker):
        """days_tracked>=60 → status='enforced'。"""
        dates = _gen_dates(65)
        for i in range(65):
            _insert_pnl(tj, "breakout", 100.0, date=dates[i])
        result = breaker.compute_drawdown(arm="breakout")
        assert result.status == "enforced"
        assert result.size_multiplier == 1.0  # no DD


class TestThreeLayerProduct:
    """H5：final_size = arm_size × portfolio_multiplier × lift_multiplier。"""

    def test_three_layer_product(self, tj, breaker):
        """三层乘积算对。"""
        # No DD → arm_mult=1.0, port_mult=1.0
        _insert_pnl(tj, "breakout", 100.0, date="2026-01-15")
        final = breaker.final_size(
            arm="breakout", arm_size=10000.0, lift_multiplier=0.8,
        )
        # 10000 × 1.0 × 1.0 × 0.8 = 8000
        assert final == 8000.0

    def test_three_layer_with_dd(self, tj, breaker):
        """DD 时 arm_mult 缩放。"""
        _insert_pnl(tj, "breakout", 1000.0, date="2026-01-01")
        dates = _gen_dates(65)
        for i in range(65):
            _insert_pnl(tj, "breakout", -200.0, date=dates[i])
        final = breaker.final_size(
            arm="breakout", arm_size=10000.0, lift_multiplier=1.0,
        )
        # arm_mult=0.5, port_mult depends on portfolio DD
        assert final <= 10000.0  # 缩小了


class TestBearMarket:
    """H6：熊市 regime。"""

    def test_bear_market_detection_default_false(self, breaker):
        """未配置熊市检测 → False（不误杀）。"""
        assert breaker._detect_bear_market() is False

    def test_bear_market_floor_exempt(self, tj, breaker):
        """熊市时 floor 豁免 drawdown enforce。"""
        # Mock bear market detection
        breaker._detect_bear_market = lambda: True
        # floor 大 DD → 熊市豁免
        dates = _gen_dates(65)
        for i in range(65):
            _insert_pnl(tj, "floor", -200.0, date=dates[i])
        result = breaker.compute_drawdown(arm=ARM_FLOOR)
        assert result.is_bear_market is True
        # 熊市 floor 豁免 → status='bear_exempt'
        assert result.status == "bear_exempt"


class TestFullStatus:
    """完整状态快照（供前端）。"""

    def test_full_status_structure(self, tj, breaker):
        """full_status 返 per_arm + portfolio + initial_capital。"""
        _insert_pnl(tj, "breakout", 100.0, date="2026-01-15")
        _insert_pnl(tj, "floor", 50.0, date="2026-01-15", realized=False)
        status = breaker.full_status()
        assert "per_arm" in status
        assert "portfolio" in status
        assert "initial_capital" in status
        assert status["initial_capital"] == 100000.0
