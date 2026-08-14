# -*- coding: utf-8 -*-
"""S066 §9 游资席位分析测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.hot_money_seats import (
    SeatProfile,
    SeatRiskFactor,
    _classify_seat,
    build_seat_profiles,
    merge_with_presets,
    detect_behavior_mutation,
    compute_seat_risk_factor,
    DAY_TRIP_SELL_RATE_MIN,
    RELAY_SELL_RATE_MAX,
    APPEARANCE_MIN,
    MUTATION_THRESHOLD,
)


class TestClassifySeat:
    """席位分类阈值（spec §9.3）。"""

    def test_day_trip_high_sell_rate(self):
        """next_day_sell_rate >= 0.7 → 一日游。"""
        seat_type, conf = _classify_seat(0.8, 5)
        assert seat_type == "一日游"

    def test_relay_low_sell_rate(self):
        """next_day_sell_rate <= 0.3 → 接力型。"""
        seat_type, conf = _classify_seat(0.2, 5)
        assert seat_type == "接力型"

    def test_mixed_middle_range(self):
        """0.3 < rate < 0.7 → 混合型。"""
        seat_type, conf = _classify_seat(0.5, 5)
        assert seat_type == "混合型"

    def test_insufficient_appearances(self):
        """appearance_count < 3 → 样本不足。"""
        seat_type, conf = _classify_seat(0.9, 2)
        assert seat_type == "样本不足"

    def test_boundary_0_7_is_day_trip(self):
        """边界 0.7 → 一日游（>=）。"""
        seat_type, _ = _classify_seat(DAY_TRIP_SELL_RATE_MIN, 5)
        assert seat_type == "一日游"

    def test_boundary_0_3_is_relay(self):
        """边界 0.3 → 接力型（<=）。"""
        seat_type, _ = _classify_seat(RELAY_SELL_RATE_MAX, 5)
        assert seat_type == "接力型"


class TestBuildSeatProfiles:
    """60 日龙虎榜聚合画像。"""

    def test_aggregates_buy_and_sell_dates(self):
        """正确聚合买入日和卖出日。"""
        billboard = [
            {"OPERATEDEPT_NAME": "席位A", "TRADE_DATE": "2026-08-01", "side": "buy", "NET": 100, "SECURITY_CODE": "000001"},
            {"OPERATEDEPT_NAME": "席位A", "TRADE_DATE": "2026-08-01", "side": "sell", "NET": -50, "SECURITY_CODE": "000001"},
            {"OPERATEDEPT_NAME": "席位A", "TRADE_DATE": "2026-08-04", "side": "buy", "NET": 200, "SECURITY_CODE": "000001"},
            {"OPERATEDEPT_NAME": "席位A", "TRADE_DATE": "2026-08-05", "side": "sell", "NET": -100, "SECURITY_CODE": "000001"},
        ]
        profiles = build_seat_profiles(billboard)
        assert len(profiles) == 1
        p = profiles[0]
        assert p.seat_name == "席位A"
        assert p.appearance_count == 4

    def test_no_buy_records_marks_insufficient(self):
        """只有卖方记录 → 标注"无买入记录"。"""
        billboard = [
            {"OPERATEDEPT_NAME": "纯卖席位", "TRADE_DATE": "2026-08-01", "side": "sell", "NET": -100, "SECURITY_CODE": "000001"},
        ]
        profiles = build_seat_profiles(billboard)
        assert profiles[0].seat_type == "样本不足"
        assert "无买入记录" in profiles[0].note

    def test_empty_billboard_returns_empty(self):
        profiles = build_seat_profiles([])
        assert profiles == []

    def test_next_day_sell_rate_calculation(self):
        """T 买入后 T+1 在卖方榜出现 → next_day_sell_rate 计算。"""
        # 席位 A 在 08-01 买入，08-02 卖出 → next_day_sell_rate = 1.0
        billboard = [
            {"OPERATEDEPT_NAME": "席位A", "TRADE_DATE": "2026-08-01", "side": "buy", "NET": 100, "SECURITY_CODE": "000001"},
            {"OPERATEDEPT_NAME": "席位A", "TRADE_DATE": "2026-08-02", "side": "sell", "NET": -50, "SECURITY_CODE": "000001"},
        ]
        profiles = build_seat_profiles(billboard)
        # appearance_count=2 < 3 → 样本不足，但 sell_rate 应=1.0
        assert profiles[0].next_day_sell_rate == 1.0


class TestMergeWithPresets:
    """预设画像合并（spec §9.3.1）。"""

    def test_data_overrides_preset(self):
        """数据画像覆盖预设标签。"""
        data_profiles = [
            SeatProfile("拉萨天团系预设席位", "接力型", 0.2, 5, "medium", "data"),
        ]
        merged = merge_with_presets(data_profiles)
        # 数据画像应保留
        data_p = [p for p in merged if p.source == "data"]
        assert any(p.seat_name == "拉萨天团系预设席位" for p in data_p)

    def test_preset_only_seats_preserved(self):
        """预设中有但数据中没有的席位 → 保留预设标签。"""
        data_profiles: list[SeatProfile] = []
        merged = merge_with_presets(data_profiles)
        preset_seats = [p for p in merged if p.source == "preset"]
        assert len(preset_seats) > 0
        # 机构专用应保留
        assert any(p.seat_name == "机构专用" for p in preset_seats)

    def test_preset_conflict_data_wins(self):
        """数据与预设冲突 → 以数据为准。"""
        # 预设中"拉萨天团系"是"一日游"
        # 数据显示它变成"接力型"
        data_profiles = [
            SeatProfile("东方财富证券股份有限公司拉萨团结路第二证券营业部",
                       "接力型", 0.2, 10, "medium", "data", "预设标签已被数据修正"),
        ]
        merged = merge_with_presets(data_profiles)
        p = next(p for p in merged if p.source == "data")
        assert p.seat_type == "接力型"


class TestDetectBehaviorMutation:
    """行为突变检测（spec §9.3）。"""

    def test_mutation_detected_high_deviation(self):
        """偏差 > 30% → 标注突变。"""
        baseline = [SeatProfile("席位A", "一日游", 0.8, 10, "medium", "data")]
        recent = [SeatProfile("席位A", "接力型", 0.2, 5, "low", "data")]
        mutations = detect_behavior_mutation(recent, baseline)
        assert "席位A" in mutations
        assert mutations["席位A"]["alert"] is True
        assert mutations["席位A"]["deviation"] > MUTATION_THRESHOLD

    def test_no_mutation_small_deviation(self):
        """偏差 < 30% → 无突变。"""
        baseline = [SeatProfile("席位A", "一日游", 0.7, 10, "medium", "data")]
        recent = [SeatProfile("席位A", "一日游", 0.75, 5, "medium", "data")]
        mutations = detect_behavior_mutation(recent, baseline)
        # deviation = 0.05/0.7 = 0.071 < 0.30
        assert "席位A" not in mutations or mutations["席位A"].get("alert") is False or len(mutations) == 0

    def test_insufficient_baseline_skipped(self):
        """基线 appearance_count < 3 → 跳过。"""
        baseline = [SeatProfile("席位A", "一日游", 0.8, 2, "low", "data")]
        recent = [SeatProfile("席位A", "接力型", 0.2, 5, "low", "data")]
        mutations = detect_behavior_mutation(recent, baseline)
        assert len(mutations) == 0

    def test_zero_baseline_rate_skipped(self):
        """基线 rate=0 → 跳过（除零）。"""
        baseline = [SeatProfile("席位A", "接力型", 0.0, 10, "medium", "data")]
        recent = [SeatProfile("席位A", "一日游", 0.8, 5, "medium", "data")]
        mutations = detect_behavior_mutation(recent, baseline)
        assert len(mutations) == 0


class TestComputeSeatRiskFactor:
    """策略分接入（spec §9.4）。"""

    def test_no_billboard_data_returns_no_data(self, monkeypatch):
        """无龙虎榜数据 → 无数据标签，modifier=1.0。"""
        monkeypatch.setattr("strategies.hot_money_seats.fetch_billboard_for_date", lambda d: [])
        monkeypatch.setattr("strategies.hot_money_seats.load_aggregate_profiles", lambda: [])
        result = compute_seat_risk_factor("000001", "2026-08-14")
        assert result.risk_label == "无数据"
        assert result.score_modifier == 1.0
        assert result.day_trip_ratio == 0.0

    def test_high_day_trip_ratio_reduces_score(self, monkeypatch):
        """一日游占比 > 0.5 → 策略分 ×0.7。"""
        billboard = [
            {"SECURITY_CODE": "000001", "OPERATEDEPT_NAME": "拉萨席位", "NET": 1000000, "side": "buy"},
            {"SECURITY_CODE": "000001", "OPERATEDEPT_NAME": "拉萨席位", "NET": 500000, "side": "buy"},
        ]
        monkeypatch.setattr("strategies.hot_money_seats.fetch_billboard_for_date", lambda d: billboard)
        profiles = [SeatProfile("拉萨席位", "一日游", 0.8, 10, "medium", "data")]
        monkeypatch.setattr("strategies.hot_money_seats.load_aggregate_profiles", lambda: profiles)
        result = compute_seat_risk_factor("000001", "2026-08-14")
        assert result.day_trip_ratio > 0.5
        assert result.score_modifier == 0.7
        assert "高风险" in result.risk_label

    def test_medium_day_trip_ratio(self, monkeypatch):
        """一日游占比 0.2-0.5 → 策略分 ×0.9（接力支撑叠加后 ×0.95）。"""
        # 一日游 300 + 接力型 700 → day_trip_ratio = 0.3, relay_ratio = 0.7 > 0.3
        billboard = [
            {"SECURITY_CODE": "000001", "OPERATEDEPT_NAME": "一日游席位", "NET": 300, "side": "buy"},
            {"SECURITY_CODE": "000001", "OPERATEDEPT_NAME": "接力席位", "NET": 700, "side": "buy"},
        ]
        monkeypatch.setattr("strategies.hot_money_seats.fetch_billboard_for_date", lambda d: billboard)
        profiles = [
            SeatProfile("一日游席位", "一日游", 0.8, 10, "medium", "data"),
            SeatProfile("接力席位", "接力型", 0.2, 10, "medium", "data"),
        ]
        monkeypatch.setattr("strategies.hot_money_seats.load_aggregate_profiles", lambda: profiles)
        result = compute_seat_risk_factor("000001", "2026-08-14")
        assert 0.2 < result.day_trip_ratio <= 0.5
        # 中风险 ×0.9 + 接力支撑 +0.05 = 0.95
        assert result.score_modifier == 0.95
        assert "中风险" in result.risk_label

    def test_relay_support_adds_bonus(self, monkeypatch):
        """接力型净买入 > 30% → 策略分 +0.05（接力支撑）。"""
        # 接力型 800 + 一日游 200 → relay_ratio = 0.8 > 0.3
        billboard = [
            {"SECURITY_CODE": "000001", "OPERATEDEPT_NAME": "接力席位", "NET": 800, "side": "buy"},
            {"SECURITY_CODE": "000001", "OPERATEDEPT_NAME": "一日游席位", "NET": 200, "side": "buy"},
        ]
        monkeypatch.setattr("strategies.hot_money_seats.fetch_billboard_for_date", lambda d: billboard)
        profiles = [
            SeatProfile("接力席位", "接力型", 0.2, 10, "medium", "data"),
            SeatProfile("一日游席位", "一日游", 0.8, 10, "medium", "data"),
        ]
        monkeypatch.setattr("strategies.hot_money_seats.load_aggregate_profiles", lambda: profiles)
        result = compute_seat_risk_factor("000001", "2026-08-14")
        assert result.relay_ratio > 0.3
        assert "接力支撑" in result.risk_label

    def test_mutation_alert_propagates(self, monkeypatch):
        """行为突变标注传播到风险因子。"""
        billboard = [
            {"SECURITY_CODE": "000001", "OPERATEDEPT_NAME": "突变席位", "NET": 1000, "side": "buy"},
        ]
        monkeypatch.setattr("strategies.hot_money_seats.fetch_billboard_for_date", lambda d: billboard)
        profiles = [SeatProfile("突变席位", "一日游", 0.8, 10, "medium", "data")]
        monkeypatch.setattr("strategies.hot_money_seats.load_aggregate_profiles", lambda: profiles)
        mutations = {"突变席位": {"note": "行为变化：60日 rate=0.80 → 5日=0.20", "alert": True}}
        result = compute_seat_risk_factor("000001", "2026-08-14", profiles, mutations)
        assert result.mutation_alert is True
        assert "行为变化" in result.mutation_note
