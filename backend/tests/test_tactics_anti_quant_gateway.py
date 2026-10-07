# -*- coding: utf-8 -*-
"""test_tactics_anti_quant_gateway —— 反量化三防线测试（S235 T11）。AAA 结构。"""
from __future__ import annotations
import pytest

from tactics.anti_quant_gateway import AntiQuantGateway


@pytest.fixture
def gw():
    return AntiQuantGateway()


# ---------------------------------------------------------------------------
# 防线1：竞价假抢筹（量比断崖）
# ---------------------------------------------------------------------------

def test_auction_fake_cliff_drop(gw):
    # Arrange: 早量 10000，晚量 4000（< 5000）→ 断崖
    live_1 = {"volume": 10000}
    live_2 = {"volume": 4000}
    # Act / Assert
    assert gw.check_auction_fake(live_1, live_2) is True


def test_auction_fake_no_cliff(gw):
    # 晚量 6000 > 早量×0.5=5000 → 非假抢筹
    live_1 = {"volume": 10000}
    live_2 = {"volume": 6000}
    assert gw.check_auction_fake(live_1, live_2) is False


def test_auction_fake_zero_early_returns_false(gw):
    # 早量 0 → 无法判定
    assert gw.check_auction_fake({"volume": 0}, {"volume": 100}) is False


def test_auction_fake_exactly_half_boundary(gw):
    # 晚量 = 早量×0.5（边界，< 严格，故 5000 不算）
    live_1 = {"volume": 10000}
    live_2 = {"volume": 5000}
    assert gw.check_auction_fake(live_1, live_2) is False


# ---------------------------------------------------------------------------
# 防线2：尾盘小单偷袭
# ---------------------------------------------------------------------------

def test_tail_fake_thin_stock(gw):
    # 成交额 3000万 < 5000万 → True
    assert gw.check_tail_fake({"amount": 3e7}) is True


def test_tail_fake_normal_stock(gw):
    # 成交额 8000万 → False
    assert gw.check_tail_fake({"amount": 8e7}) is False


def test_tail_fake_zero_amount_no_flag(gw):
    # 0 成交额（停牌）→ 不判偷袭
    assert gw.check_tail_fake({"amount": 0}) is False


def test_tail_fake_boundary_5e7(gw):
    # 边界：正好 5000万 不算（< 严格）
    assert gw.check_tail_fake({"amount": 5e7}) is False


# ---------------------------------------------------------------------------
# 防线3：对倒检测（均单价偏差）
# ---------------------------------------------------------------------------

def test_wash_trading_normal(gw):
    # close=10, vol=1e7, amount=1e8 → 均单价=10，偏差=0 → False
    snap = {"close_price": 10, "volume": 1e7, "amount": 1e8}
    assert gw.check_wash_trading(snap) is False


def test_wash_trading_deviation_above_5pct(gw):
    # close=10, vol=1e7, amount=1.1e8 → 均单价=11，偏差=10% → True
    snap = {"close_price": 10, "volume": 1e7, "amount": 1.1e8}
    assert gw.check_wash_trading(snap) is True


def test_wash_trading_deviation_below(gw):
    # close=10, vol=1e7, amount=1.04e8 → 均单价=10.4，偏差=4% → False
    snap = {"close_price": 10, "volume": 1e7, "amount": 1.04e8}
    assert gw.check_wash_trading(snap) is False


def test_wash_trading_zero_volume_no_flag(gw):
    assert gw.check_wash_trading({"close_price": 10, "volume": 0, "amount": 1e8}) is False


# ---------------------------------------------------------------------------
# any_blocked 聚合
# ---------------------------------------------------------------------------

def test_any_blocked_clean(gw):
    # close=10, vol=1e7, amount=1e8 → 均单价=10=close（wash 不拦）；auction 晚量 8000>5000（不拦）
    snap = {"close_price": 10, "volume": 1e7, "amount": 1e8}
    assert gw.any_blocked(snap, {"volume": 10000}, {"volume": 8000}) is False


def test_any_blocked_by_wash(gw):
    snap = {"close_price": 10, "volume": 1e7, "amount": 1.2e8}  # 均单价12，偏差20%
    assert gw.any_blocked(snap) is True


def test_any_blocked_by_auction(gw):
    # snap wash-clean + auction 断崖（晚量 3000 < 5000）
    snap = {"close_price": 10, "volume": 1e7, "amount": 1e8}
    assert gw.any_blocked(snap, {"volume": 10000}, {"volume": 3000}) is True
