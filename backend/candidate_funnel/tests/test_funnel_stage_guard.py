# -*- coding: utf-8 -*-
"""S044 阶段6 单测：stage 映射 + look-ahead 防护（missing 保留不引入未来信息）。"""
from candidate_funnel.funnel import _STAGE_MAP, _filter_r2
from candidate_funnel.models import BaseThreshold, ThresholdConfig
from candidate_funnel.thresholds import resolve_thresholds


class TestStageMap:
    def test_pre_market映射s1(self):
        assert _STAGE_MAP["pre_market"] == "s1"

    def test_auction映射s3(self):
        assert _STAGE_MAP["auction"] == "s3"

    def test_未知stage默认s1(self):
        assert _STAGE_MAP.get("unknown", "s1") == "s1"


class TestLookAheadGuard:
    def test_北向missing保留不过滤(self):
        """availability_offset=1 的北向缺数据 → 标 missing 保留，不引入未来信息。"""
        eff = resolve_thresholds(
            ThresholdConfig(mode="manual", base=BaseThreshold(northbound_abs_min=500.0)), None)
        fund = {"000001": {"northbound": None}}  # missing（如近期北向停更）
        kept, filt = _filter_r2(["000001"], {"000001": {"name": "x", "turnover_pct": 10.0}}, eff, fund)
        assert kept == ["000001"]  # missing 保留
        assert filt == []

    def test_registry_list_for_stage_s1含fund_flow特征(self):
        """list_for_stage('s1') 返回 s1 特征（look-ahead 防护可复用）。"""
        from predict.features.registry import Registry
        from predict.features.fund_flow import register_fund_flow
        reg = Registry()
        register_fund_flow(reg)
        names = {s.name for s in reg.list_for_stage("s1")}
        assert "northbound_net_segmented" in names
        assert "dt_hot_money_relay" in names
