# -*- coding: utf-8 -*-
"""test_tactics_trade_journal —— 实盘记录 + gap-through 止损测试（S235 T07 辅助）。

R6 关键：跳空穿仓按开盘价成交（不按止损价精确成交）+ 滑点 0.3%。
"""
from __future__ import annotations
import pytest

from tactics.trade_journal import (
    TradeJournal,
    calc_stop_loss,
    BUY_SLIPPAGE,
    SELL_SLIPPAGE,
)


@pytest.fixture
def journal(tmp_path):
    return TradeJournal(db_path=tmp_path / "journal.db")


# ---------------------------------------------------------------------------
# calc_stop_loss —— R6 gap-through 核心
# ---------------------------------------------------------------------------

def test_stop_loss_gap_through_worse_than_stop():
    # Arrange: entry=10, stop=-10% → 止损价 9.0；次日开盘 8.5（穿仓）
    # Act
    fill, kind = calc_stop_loss(10.0, -10, {"open_price": 8.5, "low_price": 8.3})
    # Assert: 按开盘价 8.5 成交（比止损价 9.0 更差）
    assert kind == "gap_through"
    assert fill == pytest.approx(8.5)


def test_stop_loss_normal_stop():
    # 盘中触及止损价：开盘 9.5（>止损价 9.0），最低 8.8（<=9.0）
    fill, kind = calc_stop_loss(10.0, -10, {"open_price": 9.5, "low_price": 8.8})
    assert kind == "normal_stop"
    assert fill == pytest.approx(9.0)


def test_stop_loss_no_stop():
    # 未触及：开盘 9.5，最低 9.2（都 > 9.0）
    fill, kind = calc_stop_loss(10.0, -10, {"open_price": 9.5, "low_price": 9.2})
    assert kind == "no_stop"
    assert fill is None


def test_stop_loss_no_data():
    fill, kind = calc_stop_loss(10.0, -10, {"low_price": 8.0})  # 缺 open_price
    assert kind == "no_data"
    assert fill is None


def test_stop_loss_zero_entry():
    assert calc_stop_loss(0, -10, {"open_price": 9}) == (None, "no_data")


def test_stop_loss_boundary_open_equals_stop():
    # 开盘价正好 = 止损价 9.0 → gap_through（<= 严格边界）
    fill, kind = calc_stop_loss(10.0, -10, {"open_price": 9.0, "low_price": 9.0})
    assert kind == "gap_through"
    assert fill == pytest.approx(9.0)


# ---------------------------------------------------------------------------
# TradeJournal —— 滑点 + 收益
# ---------------------------------------------------------------------------

def test_save_trade_applies_buy_slippage(journal):
    # Arrange/Act: 信号价 10.0
    tid = journal.save_trade(
        signal_id=1, code="603778", tactic="reversal", entry_price=10.0,
    )
    # Assert: fill_price = 10 × (1+0.003) = 10.03
    t = journal.get_trade(tid)
    assert t["fill_price"] == pytest.approx(10.03)
    assert t["slippage_pct"] == pytest.approx(BUY_SLIPPAGE)
    assert t["stop_price"] == pytest.approx(9.0)  # 10×0.9


def test_record_exit_applies_sell_slippage(journal):
    # Arrange: entry 10.0 → fill 10.03；exit 11.0 → sell_fill 11×0.997=10.967
    tid = journal.save_trade(
        signal_id=1, code="603778", tactic="reversal", entry_price=10.0,
    )
    # Act
    ret = journal.record_exit(tid, exit_price=11.0, exit_reason="profit", hold_days=3)
    # Assert: ret = (10.967 - 10.03) / 10.03 ≈ 0.0934（9.34%）
    assert ret == pytest.approx((11.0 * (1 - SELL_SLIPPAGE) - 10.0 * (1 + BUY_SLIPPAGE))
                                / (10.0 * (1 + BUY_SLIPPAGE)))
    assert journal.get_trade_pnl(tid) == pytest.approx(ret)


def test_get_trade_pnl_none_before_exit(journal):
    tid = journal.save_trade(
        signal_id=1, code="603778", tactic="reversal", entry_price=10.0,
    )
    assert journal.get_trade_pnl(tid) is None


def test_record_exit_missing_trade_raises(journal):
    with pytest.raises(ValueError):
        journal.record_exit(999, exit_price=11.0, exit_reason="x")


def test_stop_loss_worse_fill_lowers_return(journal):
    # 集成：gap-through 止损的实际收益比"按止损价成交"更差
    # entry 10 → fill 10.03；gap-through 8.5 → sell_fill 8.5×0.997=8.4745
    tid = journal.save_trade(
        signal_id=1, code="603778", tactic="reversal", entry_price=10.0,
    )
    t = journal.get_trade(tid)
    fill, _ = calc_stop_loss(t["fill_price"], -10, {"open_price": 8.5, "low_price": 8.3})
    ret = journal.record_exit(tid, exit_price=fill, exit_reason="gap_stop", hold_days=1)
    # 若按止损价 9.0×0.997=8.973 算，ret=(8.973-10.03)/10.03=-0.1052；
    # 按 gap 8.5×0.997=8.4745，ret≈-0.155（更差）—— R6 关键
    assert ret < -0.10  # 比按止损价的 -10.5% 更差（约 -15.5%）
