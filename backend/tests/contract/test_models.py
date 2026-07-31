"""S007 契约层 R5-R6 — baseline 文件回放契约测试。

区别于 test_models_contract.py 的内联 dict，这里聚焦**从真实 fallback JSON
文件加载捕获形状，验证映射函数 → model_validate → model_dump 的 round-trip 正确性**。

标记：
  - 所有测试均离线（`-m "not live"`），不触网。
  - `frozen` 属性验证模型不可变。
  - `missing_value` 验证缺失字段映射后为 None 而非 0。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from models import FundFlow
from models.enums import Market

from .baseline_replay import map_capital_flow_to_fundflow, map_dragon_tiger_to_seat_records


DATA_DIR = Path(__file__).parent.parent.parent / "data" / "fallback"


# ── Helpers ────────────────────────────────────────────────────────────────


def _load_fallback(filename: str) -> dict | list:
    """加载 fallback JSON 并返回其 data 字段内容。

    部分 fallback 文件含 GBK 编码字符（dragon_tiger 的 reason 字段），
    使用 errors='replace' 避免解码失败。
    """
    text = (DATA_DIR / filename).read_text(encoding="utf-8", errors="replace")
    raw = json.loads(text)
    return raw.get("data", raw)


# ── R5 · FundFlow baseline 回放 ────────────────────────────────────────────


class TestFundFlowBaseline:
    def test_600722_empty_data_maps_to_empty_list(self):
        """capital_flow_600722.json data 为空列表，映射应产出空列表不抛。"""
        data = _load_fallback("capital_flow_600722.json")
        assert data == []
        result = [map_capital_flow_to_fundflow(item, code="600722", market="A") for item in data]
        assert result == []

    def test_605162_first_bar_validate_ok(self):
        """capital_flow_605162.json 首行经映射后能 model_validate 进 FundFlow。"""
        data = _load_fallback("capital_flow_605162.json")
        assert isinstance(data, list) and len(data) > 0
        first = data[0]
        mapped = map_capital_flow_to_fundflow(first, code="605162", market="A")
        ff = FundFlow.model_validate(mapped)
        assert ff.code == "605162"
        assert ff.market == Market.A
        assert ff.date == "2026-01-27"
        assert ff.main_net == -2878962.0
        assert ff.super_large_net == -668657.0
        assert ff.large_net == -2210305.0
        assert ff.medium_net == 853488.0
        assert ff.small_net == 2025474.0

    def test_605162_last_bar_validate_ok(self):
        """capital_flow_605162.json 末行经映射后能 model_validate 进 FundFlow。"""
        data = _load_fallback("capital_flow_605162.json")
        assert isinstance(data, list) and len(data) > 0
        last = data[-1]
        mapped = map_capital_flow_to_fundflow(last, code="605162", market="A")
        ff = FundFlow.model_validate(mapped)
        assert ff.code == "605162"
        assert ff.market == Market.A
        assert ff.date == "2026-07-28"

    def test_round_trip_consistency(self):
        """fallback → mapped → model_validate → model_dump，关键字段值一致。"""
        data = _load_fallback("capital_flow_605162.json")
        assert isinstance(data, list) and len(data) > 0
        first = data[0]
        mapped = map_capital_flow_to_fundflow(first, code="605162", market="A")
        ff = FundFlow.model_validate(mapped)
        dumped = ff.model_dump()
        assert dumped["code"] == "605162"
        assert dumped["market"] == "A"
        assert dumped["date"] == first["date"]
        assert dumped["main_net"] == first["main_net"]
        assert dumped["super_large_net"] == first["super_net"]
        assert dumped["large_net"] == first["large_net"]
        assert dumped["medium_net"] == first["mid_net"]
        assert dumped["small_net"] == first["small_net"]

    def test_frozen_cannot_mutate(self):
        """baseline 回放出的 FundFlow 实例赋值属性应 raise ValidationError。"""
        data = _load_fallback("capital_flow_605162.json")
        first = data[0]
        mapped = map_capital_flow_to_fundflow(first, code="605162", market="A")
        ff = FundFlow.model_validate(mapped)
        with pytest.raises(ValidationError):
            ff.main_net = 0.0

    def test_missing_fields_map_to_none(self):
        """原始行缺失字段时，映射后对应值为 None，不偷偷填 0。"""
        raw = {"date": "2026-01-27", "main_net": 100.0}
        mapped = map_capital_flow_to_fundflow(raw, code="000001", market="A")
        assert mapped["super_large_net"] is None
        assert mapped["large_net"] is None
        assert mapped["medium_net"] is None
        assert mapped["small_net"] is None
        # 仍可 validate（FundFlow 可选字段默认 None）
        ff = FundFlow.model_validate(mapped)
        assert ff.super_large_net is None


# ── R6 · DragonTiger / seat_records baseline 回放 ──────────────────────────


class TestDragonTigerBaseline:
    def test_600722_empty_seats_maps_to_empty_records(self):
        """dragon_tiger_600722.json seats.buy/seats.sell 为空，映射产出空列表。"""
        data = _load_fallback("dragon_tiger_600722.json")
        assert isinstance(data, dict)
        seats = data.get("seats", {})
        records = map_dragon_tiger_to_seat_records(seats)
        assert records == []

    def test_605162_seats_shape_compatible(self):
        """dragon_tiger_605162.json seats 结构能映射为 seat_records 不抛。"""
        data = _load_fallback("dragon_tiger_605162.json")
        assert isinstance(data, dict)
        seats = data.get("seats", {})
        records = map_dragon_tiger_to_seat_records(seats)
        assert len(records) == 10  # 5 buy + 5 sell
        for rec in records:
            assert "name" in rec
            assert "buy_amt" in rec
            assert "sell_amt" in rec
            assert "net" in rec
            assert "side" in rec
            assert "hold_days" in rec
        buy_records = [r for r in records if r["side"] == "buy"]
        sell_records = [r for r in records if r["side"] == "sell"]
        assert len(buy_records) == 5
        assert len(sell_records) == 5
        assert buy_records[0]["name"] is not None
        assert buy_records[0]["buy_amt"] > 0

    def test_605162_buy_first_record_fields(self):
        """验证首条 buy 记录字段映射正确。"""
        data = _load_fallback("dragon_tiger_605162.json")
        seats = data.get("seats", {})
        records = map_dragon_tiger_to_seat_records(seats)
        buy_records = [r for r in records if r["side"] == "buy"]
        first = buy_records[0]
        assert first["name"] is not None
        assert first["buy_amt"] > 0
        assert first["sell_amt"] == 0.0
        assert first["net"] > 0
        assert first["side"] == "buy"
        assert first["hold_days"] is None

    def test_605162_sell_first_record_fields(self):
        """验证首条 sell 记录字段映射正确。"""
        data = _load_fallback("dragon_tiger_605162.json")
        seats = data.get("seats", {})
        records = map_dragon_tiger_to_seat_records(seats)
        sell_records = [r for r in records if r["side"] == "sell"]
        first = sell_records[0]
        assert first["name"] is not None
        assert first["buy_amt"] == 0.0
        assert first["sell_amt"] > 0
        assert first["net"] < 0
        assert first["side"] == "sell"
        assert first["hold_days"] is None

    def test_seat_records_with_empty_dict(self):
        """传入空 dict 应产出空列表，不抛。"""
        records = map_dragon_tiger_to_seat_records({})
        assert records == []

    def test_seat_records_with_list(self):
        """传入 list（异常情况）应产出空列表，不抛。"""
        records = map_dragon_tiger_to_seat_records([])
        assert records == []

    def test_seat_records_with_none(self):
        """传入 None（异常情况）应产出空列表，不抛。"""
        records = map_dragon_tiger_to_seat_records(None)  # type: ignore[arg-type]
        assert records == []
