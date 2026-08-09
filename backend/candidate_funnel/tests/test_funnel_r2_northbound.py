# -*- coding: utf-8 -*-
"""S044 阶段5 单测：北向进 R2 非方向占位过滤（R5）+ BaseThreshold 字段 + 透传。"""
from candidate_funnel.funnel import _filter_r2
from candidate_funnel.models import BaseThreshold, IndicatorSet, ThresholdConfig
from candidate_funnel.thresholds import resolve_thresholds


def _eff(northbound_abs_min: float = 0.0) -> BaseThreshold:
    """manual 模式生效阈值（base.model_copy 透传 northbound_abs_min）。"""
    base = BaseThreshold(northbound_abs_min=northbound_abs_min)
    return resolve_thresholds(ThresholdConfig(mode="manual", base=base), None)


def _act(c: str, turnover: float = 10.0) -> dict:
    return {c: {"name": c, "turnover_pct": turnover}}


class TestFilterR2Northbound:
    def test_nb缺失_保留不过滤(self):
        eff = _eff(500.0)
        fund = {"000001": {"northbound": None}}
        kept, filt = _filter_r2(["000001"], _act("000001"), eff, fund)
        assert kept == ["000001"]
        assert filt == []

    def test_nb有值小于阈值_过滤(self):
        eff = _eff(500.0)
        fund = {"000001": {"northbound": 100.0}}
        kept, filt = _filter_r2(["000001"], _act("000001"), eff, fund)
        assert kept == []
        assert filt[0].code == "000001"
        assert "北向" in filt[0].reason

    def test_nb有值大于等于阈值_保留(self):
        eff = _eff(500.0)
        fund = {"000001": {"northbound": 600.0}}
        kept, _filt = _filter_r2(["000001"], _act("000001"), eff, fund)
        assert kept == ["000001"]

    def test_nb负值绝对值小于阈值_过滤(self):
        # 非方向口径：abs(-100)=100 < 500 → 过滤（不分正负）
        eff = _eff(500.0)
        fund = {"000001": {"northbound": -100.0}}
        kept, filt = _filter_r2(["000001"], _act("000001"), eff, fund)
        assert kept == []
        assert filt[0].code == "000001"

    def test_默认阈值0_有北向即保留(self):
        eff = _eff(0.0)
        fund = {"000001": {"northbound": 1.0}}
        kept, _filt = _filter_r2(["000001"], _act("000001"), eff, fund)
        assert kept == ["000001"]

    def test_无fund参数_向后兼容(self):
        eff = _eff(500.0)
        # 不传 fund（旧调用面）→ northbound 缺失 → 保留
        kept, _filt = _filter_r2(["000001"], _act("000001"), eff)
        assert kept == ["000001"]

    def test_换手冷股先于北向过滤(self):
        # 换手低于冷档直接过滤，不进北向判断
        eff = _eff(500.0)
        fund = {"000001": {"northbound": 1.0}}
        kept, filt = _filter_r2(["000001"], _act("000001", turnover=1.0), eff, fund)
        assert kept == []
        assert "换手" in filt[0].reason


class TestThresholdField:
    def test_BaseThreshold默认0(self):
        assert BaseThreshold().northbound_abs_min == 0.0

    def test_eff透传northbound_abs_min(self):
        assert _eff(500.0).northbound_abs_min == 500.0
        assert _eff(0.0).northbound_abs_min == 0.0

    def test_IndicatorSet_relay字段默认None(self):
        ind = IndicatorSet(code="000001", name="test")
        assert ind.dragon_tiger_hot_money_relay is None
