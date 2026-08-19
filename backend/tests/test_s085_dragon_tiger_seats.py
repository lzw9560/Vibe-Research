# -*- coding: utf-8 -*-
"""S085 A2 — dragon_tiger seats 透传单测。

验证：DragonTiger 模型加 buy_seats/sell_seats（默认空 tuple，向后兼容）；
mappers.dragon_tiger_from_dict 透传 raw['seats']→新字段，且不破坏 records/institution_net 既有映射。
零承重：institution_net 消费方（fund_flow.py:49→R2 因子 / first_board_filter.py:979 dim7）保持不变（见 核实报告.md A2）。
"""
from __future__ import annotations

from data.mappers import dragon_tiger_from_dict
from models.seat import DragonTiger, DragonTigerRecord, Seat


def test_dragon_tiger_has_seats_fields_default_empty():
    # Act
    dt = DragonTiger()
    # Assert
    assert hasattr(dt, "buy_seats")
    assert hasattr(dt, "sell_seats")
    assert dt.buy_seats == ()
    assert dt.sell_seats == ()


def test_seat_model_carries_name_buy_sell_net():
    # Act
    s = Seat(name="华泰证券深圳益田路荣超商务中心", buy_amt=1.2, sell_amt=0.0, net=1.2)
    # Assert
    assert s.name.startswith("华泰证券")
    assert s.buy_amt == 1.2
    assert s.sell_amt == 0.0
    assert s.net == 1.2


def test_mapper_passes_through_seats():
    """raw['seats']（buy/sell 各 TOP5，name/buy_amt/sell_amt/net 万元）→ DragonTiger.buy_seats/sell_seats。"""
    # Arrange
    raw = {
        "records": [{"net_buy": 1234.5}],
        "seats": {
            "buy": [
                {"name": "买方席位A", "buy_amt": 100.0, "sell_amt": 10.0, "net": 90.0},
                {"name": "买方席位B", "buy_amt": 50.0, "sell_amt": 5.0, "net": 45.0},
            ],
            "sell": [
                {"name": "卖方席位C", "buy_amt": 8.0, "sell_amt": 80.0, "net": -72.0},
            ],
        },
        "institution": {"buy_amt": 0.0, "sell_amt": 200.0, "net_amt": -200.0},
    }
    # Act
    dt = dragon_tiger_from_dict(raw)
    # Assert — seats 透传
    assert len(dt.buy_seats) == 2
    assert dt.buy_seats[0].name == "买方席位A"
    assert dt.buy_seats[0].buy_amt == 100.0
    assert dt.buy_seats[1].net == 45.0
    assert len(dt.sell_seats) == 1
    assert dt.sell_seats[0].name == "卖方席位C"
    assert dt.sell_seats[0].net == -72.0
    # 向后兼容 — records / institution_net 不变
    assert len(dt.records) == 1
    assert dt.records[0].net_buy == 1234.5
    assert dt.institution_net == -200.0


def test_mapper_seats_missing_defaults_empty():
    """raw 无 seats 键（旧格式/未上榜）→ buy_seats/sell_seats 空 tuple，不崩。"""
    # Arrange
    raw = {"records": [], "institution": {"net_amt": None}}
    # Act
    dt = dragon_tiger_from_dict(raw)
    # Assert
    assert dt.buy_seats == ()
    assert dt.sell_seats == ()
    assert dt.institution_net is None


def test_mapper_records_institution_net_unchabled_by_seats_addition():
    """A2 新增 seats 不改 records/institution_net 既有映射（消费方血脉保护）。"""
    # Arrange — 两条 records + institution net_amt
    raw = {
        "records": [{"net_buy": 10.0}, {"net_buy": 20.0}],
        "seats": {"buy": [{"name": "X", "buy_amt": 1.0, "sell_amt": 0.0, "net": 1.0}], "sell": []},
        "institution": {"net_amt": 999.9},
    }
    # Act
    dt = dragon_tiger_from_dict(raw)
    # Assert
    assert tuple(r.net_buy for r in dt.records) == (10.0, 20.0)
    assert dt.institution_net == 999.9


def test_seat_model_is_frozen():
    """DragonTiger frozen=True，Seat 须同 frozen（不可变，防隐式副作用）。"""
    s = Seat(name="X", buy_amt=1.0, sell_amt=0.0, net=1.0)
    try:
        s.buy_amt = 2.0  # type: ignore[misc]
        assert False, "frozen model 应禁止赋值"
    except Exception:
        pass
