# -*- coding: utf-8 -*-
"""S085 B2 — seat_detail 子对象单测。

验证 DiagnosisCard 加 seat_detail 子对象（聚合 only）：
  - {buy_one_ratio, seat_type_summary, score_modifier, data_status}
  - build_diagnosis_card 从 seat_engine.compute_consensus_signal + hot_money_seats.compute_seat_risk_factor 取数
  - 无龙虎榜/取数失败 → None 降级（守不臆造）

合规 S018 R11：不放个体席位名/花名，只放聚合分类（一日游/接力型/机构...）。
零承重：seat 数据不影响 capped/胜率/结算（final_candidates 仍是唯一承重出口）。
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from candidate_funnel.diagnosis import build_diagnosis_card
from candidate_funnel.models import BaseThreshold, DiagnosisCard, IndicatorSet
from candidate_funnel.thresholds import EIGHT_STANDARD_CAP_THRESHOLD


def _mk_ind() -> IndicatorSet:
    return IndicatorSet(code="600519", name="贵州茅台", float_market_cap=2.0e12)


def test_diagnosis_card_has_seat_detail_field_default_none():
    # Act
    card = DiagnosisCard(
        code="600519", name="贵州茅台", indicators=_mk_ind(),
        activity=..., stabilization=..., as_of=datetime.now(),
    ) if False else None  # placeholder—activity/stabilization 必填，走 build_diagnosis_card 更直接
    # 直接验字段存在+默认 None
    # Act
    card = build_diagnosis_card(
        "600519", "贵州茅台", _mk_ind(), BaseThreshold(), market_ctx=None,
        as_of=datetime.now(),
    )
    # Assert
    assert hasattr(card, "seat_detail")
    assert card.seat_detail is None  # 默认 None（无 trade_date / 无龙虎榜降级）


def test_seat_detail_none_when_no_trade_date():
    """build_diagnosis_card 开 with_seat_detail 但不传 trade_date → seat_detail=None（不臆造）。"""
    # Act
    card = build_diagnosis_card(
        "600519", "贵州茅台", _mk_ind(), BaseThreshold(), market_ctx=None,
        as_of=datetime.now(), with_seat_detail=True,
    )
    # Assert
    assert card.seat_detail is None


def test_seat_detail_skipped_in_bulk_path():
    """bulk 漏斗路径 with_seat_detail=False（默认）→ 即便传 trade_date 也不取数（perf 保护）。"""
    with patch("seat_engine.service.get_engine") as ge:
        ge.return_value.compute_consensus_signal.return_value = {"details": {"buy_one_ratio": 1.0}}
        # Act — 默认 with_seat_detail=False
        card = build_diagnosis_card(
            "600519", "贵州茅台", _mk_ind(), BaseThreshold(), market_ctx=None,
            as_of=datetime.now(), trade_date="2026-08-18",
        )
    # Assert — bulk 跳过，不触发任何 datacenter 调用
    assert card.seat_detail is None
    assert not ge.return_value.compute_consensus_signal.called


def test_seat_detail_populated_when_consensus_available():
    """compute_consensus_signal 返回有效 details → seat_detail 填聚合字段。"""
    consensus = {
        "signal": "多资金共识",
        "details": {
            "date": "2026-08-18",
            "stock_code": "600519",
            "buy_seats": [{"name": "席位A", "buy_amt": 100.0, "sell_amt": 0.0, "net": 100.0, "seat_type": "接力型"}],
            "sell_seats": [],
            "buy_seat_types": ["接力型"],
            "sell_seat_types": [],
            "institution_buy_amt": 0.0,
            "institution_sell_amt": 0.0,
            "total_buy_amount": 100.0,
            "buy_one_ratio": 1.0,
        },
        "disclaimer": "x",
    }
    from strategies.hot_money_seats import SeatRiskFactor
    seat_risk = SeatRiskFactor(
        day_trip_ratio=0.0, relay_ratio=1.0, institution_ratio=0.0,
        score_modifier=1.0, risk_label="低风险", mutation_alert=False,
    )
    with patch("seat_engine.service.get_engine") as ge, \
            patch("strategies.hot_money_seats.compute_seat_risk_factor") as csrf:
        ge.return_value.compute_consensus_signal.return_value = consensus
        csrf.return_value = seat_risk
        # Act
        card = build_diagnosis_card(
            "600519", "贵州茅台", _mk_ind(), BaseThreshold(), market_ctx=None,
            as_of=datetime.now(), trade_date="2026-08-18", with_seat_detail=True,
        )
    # Assert — 聚合 only，无个体席位名/花名（守 S018 R11）
    assert card.seat_detail is not None
    assert card.seat_detail["buy_one_ratio"] == 1.0
    assert card.seat_detail["score_modifier"] == 1.0
    assert card.seat_detail["risk_label"] == "低风险"
    assert "buy_seat_types" in card.seat_detail  # 聚合类型列表
    # 不含个体席位名（S018 R11）
    sd_dump = str(card.seat_detail)
    assert "席位A" not in sd_dump, "聚合层不得泄漏个体席位名"


def test_seat_detail_none_when_consensus_returns_none():
    """非涨停股/无龙虎榜 → compute_consensus_signal 返 None → seat_detail=None（不臆造）。"""
    with patch("seat_engine.service.get_engine") as ge, \
            patch("strategies.hot_money_seats.compute_seat_risk_factor") as csrf:
        ge.return_value.compute_consensus_signal.return_value = None
        csrf.return_value = None
        # Act
        card = build_diagnosis_card(
            "600519", "贵州茅台", _mk_ind(), BaseThreshold(), market_ctx=None,
            as_of=datetime.now(), trade_date="2026-08-18", with_seat_detail=True,
        )
    # Assert
    assert card.seat_detail is None


def test_seat_detail_marks_data_status_on_fetch_exception():
    """取数异常 → seat_detail=None（不臆造，异常吞到日志层，不冒泡破坏 card 构造）。"""
    with patch("seat_engine.service.get_engine") as ge, \
            patch("strategies.hot_money_seats.compute_seat_risk_factor") as csrf:
        ge.return_value.compute_consensus_signal.side_effect = RuntimeError("boom")
        csrf.return_value = None
        # Act — 不应抛
        card = build_diagnosis_card(
            "600519", "贵州茅台", _mk_ind(), BaseThreshold(), market_ctx=None,
            as_of=datetime.now(), trade_date="2026-08-18", with_seat_detail=True,
        )
    # Assert
    assert card.seat_detail is None
