# -*- coding: utf-8 -*-
"""S203 T7: intraday_loss_breaker test（TDD）。

验证吃大面 enforce：单笔>5% 禁加仓 / 合计>8% 禁开新仓 / 四层乘积 intraday_mult / 冷却。
"""
from __future__ import annotations

import pytest

from risk.intraday_loss_breaker import (
    LossBreakerState,
    SINGLE_LOSS_BLOCK_PCT,
    TOTAL_ACCOUNT_BLOCK_PCT,
    compute_final_size,
    evaluate_loss_breaker,
    intraday_multiplier,
)


def test_single_loss_5pct_block_add():
    """单笔浮亏>5% → is_blocked_add=True（该 code 禁加仓）。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", realized_loss_pct=-6.0, total_account_loss_pct=-2.0)
    assert s.is_blocked_add is True  # 6%>5%
    assert s.is_blocked_new is False  # 2%<8%


def test_single_loss_below_5pct_no_block():
    """单笔浮亏<5% → 不禁。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", realized_loss_pct=-4.0, total_account_loss_pct=-2.0)
    assert s.is_blocked_add is False
    assert s.is_blocked_new is False


def test_total_account_8pct_block_new():
    """合计>8% → is_blocked_new=True（全账户禁开新仓+冷却）。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", realized_loss_pct=-3.0, total_account_loss_pct=-9.0)
    assert s.is_blocked_new is True  # 9%>8%
    assert s.is_blocked_add is False  # 3%<5%


def test_both_block():
    """单笔>5% + 合计>8% → 双 block。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", realized_loss_pct=-7.0, total_account_loss_pct=-10.0)
    assert s.is_blocked_add is True
    assert s.is_blocked_new is True


def test_intraday_multiplier_block_new_zero():
    """is_blocked_new → intraday_mult=0（全账户熔断优先）。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", -3.0, -9.0)
    assert intraday_multiplier(s) == 0.0


def test_intraday_multiplier_block_add_zero():
    """is_blocked_add（无 block_new）→ intraday_mult=0（该 code 禁加仓）。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", -6.0, -2.0)
    assert intraday_multiplier(s) == 0.0


def test_intraday_multiplier_pass():
    """无 block → intraday_mult=1.0（放行）。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", -2.0, -1.0)
    assert intraday_multiplier(s) == 1.0


def test_final_size_four_layer_product():
    """四层乘积 final_size = arm × portfolio × lift × intraday。"""
    assert compute_final_size(100, 0.8, 0.5, 1.0) == 40.0  # 100*0.8*0.5*1
    assert compute_final_size(100, 0.8, 0.5, 0.0) == 0.0  # intraday 0 → 0 禁交易
    assert compute_final_size(100, 0.0, 0.5, 1.0) == 0.0  # portfolio 0 → 0


def test_loss_breaker_state_immutable():
    """LossBreakerState frozen dataclass。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", -6.0, -2.0)
    with pytest.raises(Exception):
        s.is_blocked_add = False  # frozen


def test_thresholds_constants():
    """阈值常量（5% / 8%）。"""
    assert SINGLE_LOSS_BLOCK_PCT == 5.0
    assert TOTAL_ACCOUNT_BLOCK_PCT == 8.0


def test_positive_loss_no_block():
    """正收益（盈利）→ 不 block（loss_pct 正数）。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", realized_loss_pct=2.0, total_account_loss_pct=1.0)
    assert s.is_blocked_add is False  # abs(2)<5
    assert s.is_blocked_new is False
