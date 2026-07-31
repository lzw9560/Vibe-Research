"""Tests for backend/predict/features/fund_flow.py — S018 fund-flow feature specs.

TDD: (a)-(g) covering FeatureSpec construction, registration, look-ahead guard,
and pure computation functions (accumulate_main_net, NorthFlowSegmenter,
sector_rotation_speed).

All tests are offline (no network calls).
"""

import pytest


# ── (a) 7 个 FeatureSpec 构造合法 ─────────────────────────────────


def _fund_flow_specs():
    """Return the FUND_FLOW_SPECS tuple from the module under test."""
    from predict.features.fund_flow import FUND_FLOW_SPECS
    return FUND_FLOW_SPECS


def test_feature_specs_valid():
    """7 个 FeatureSpec 构造合法，offset/stage/compliance_flag 校验通过。"""
    from predict.features.fund_flow import FUND_FLOW_SPECS

    assert len(FUND_FLOW_SPECS) == 7
    names = {s.name for s in FUND_FLOW_SPECS}
    assert names == {
        "main_net_5d",
        "dt_hot_money_relay",
        "seal_fund_strength",
        "northbound_net_segmented",
        "margin_balance_change",
        "sector_flow_rotation",
        "block_trade_discount",
    }
    for spec in FUND_FLOW_SPECS:
        assert spec.category == "fund_flow"
        assert spec.availability_offset == 1
        assert spec.stage == "s1"
        assert "T+1" in spec.description and "S1" in spec.description


def test_feature_specs_compliance_flags():
    """seal_fund_strength 是 aggregate_only，其余是 ok。"""
    from predict.features.fund_flow import FUND_FLOW_SPECS

    compliance_map = {s.name: s.compliance_flag for s in FUND_FLOW_SPECS}
    assert compliance_map["seal_fund_strength"] == "aggregate_only"
    for name, flag in compliance_map.items():
        if name != "seal_fund_strength":
            assert flag == "ok", f"{name} should be 'ok'"


# ── (b) register_fund_flow 注册成功，get_by_name 能取回 ────────────


def test_register_fund_flow_registers_all_seven():
    """register_fund_flow 把 7 个 spec 注册进新 Registry 实例。"""
    from predict.features.fund_flow import register_fund_flow, FUND_FLOW_SPECS
    from predict.features.registry import Registry

    registry = Registry()
    register_fund_flow(registry)

    for spec in FUND_FLOW_SPECS:
        assert registry.get_by_name(spec.name) is spec


# ── (c) 重复注册同名 raise KeyError ─────────────────────────────────


def test_register_fund_flow_duplicate_raises():
    """重复注册同名 feature 时 Registry 抛 KeyError。"""
    from predict.features.fund_flow import register_fund_flow
    from predict.features.registry import Registry

    registry = Registry()
    register_fund_flow(registry)
    with pytest.raises(KeyError, match="already registered"):
        register_fund_flow(registry)


# ── (d) list_for_stage look-ahead 防护 ──────────────────────────────


def test_list_for_stage_s1_includes_all_seven():
    """list_for_stage('s1') 包含全部 7 个 fund_flow 特征。"""
    from predict.features.fund_flow import register_fund_flow
    from predict.features.registry import Registry

    registry = Registry()
    register_fund_flow(registry)
    s1_names = {s.name for s in registry.list_for_stage("s1")}
    assert s1_names == {
        "main_net_5d",
        "dt_hot_money_relay",
        "seal_fund_strength",
        "northbound_net_segmented",
        "margin_balance_change",
        "sector_flow_rotation",
        "block_trade_discount",
    }


def test_list_for_stage_s1_count_seven():
    """list_for_stage('s1') 返回 7 个 fund_flow 特征。"""
    from predict.features.fund_flow import register_fund_flow
    from predict.features.registry import Registry

    registry = Registry()
    register_fund_flow(registry)
    s1_specs = registry.list_for_stage("s1")
    assert len(s1_specs) == 7


# ── (e) accumulate_main_net ─────────────────────────────────────────


def test_accumulate_main_net_normal():
    """正常累计 5 日主力净流入。"""
    from predict.features.fund_flow import accumulate_main_net

    assert accumulate_main_net([1.0, 2.0, 3.0, 4.0, 5.0]) == 15.0


def test_accumulate_main_net_with_none():
    """含 None 时跳过 None 继续累计。"""
    from predict.features.fund_flow import accumulate_main_net

    assert accumulate_main_net([1.0, None, 3.0, None, 5.0]) == 9.0


def test_accumulate_main_net_all_none():
    """全 None 返回 None。"""
    from predict.features.fund_flow import accumulate_main_net

    assert accumulate_main_net([None, None, None, None, None]) is None


def test_accumulate_main_net_empty():
    """空 list 返回 None。"""
    from predict.features.fund_flow import accumulate_main_net

    assert accumulate_main_net([]) is None


# ── (f) NorthFlowSegmenter ──────────────────────────────────────────


def test_northflow_segmenter_pre_change():
    """变更前日期 → pre_change。"""
    from predict.features.fund_flow import NorthFlowSegmenter

    seg = NorthFlowSegmenter()
    assert seg.segment("2024-08-18") == "pre_change"


def test_northflow_segmenter_post_change():
    """变更后日期 → post_change。"""
    from predict.features.fund_flow import NorthFlowSegmenter

    seg = NorthFlowSegmenter()
    assert seg.segment("2024-08-20") == "post_change"


def test_northflow_segmenter_change_day():
    """变更日当天 → post_change。"""
    from predict.features.fund_flow import NorthFlowSegmenter

    seg = NorthFlowSegmenter()
    assert seg.segment("2024-08-19") == "post_change"


def test_northflow_segmenter_is_realtime_allowed():
    """is_realtime_allowed：变更前 True，变更后 False。"""
    from predict.features.fund_flow import NorthFlowSegmenter

    seg = NorthFlowSegmenter()
    assert seg.is_realtime_allowed("2024-08-18") is True
    assert seg.is_realtime_allowed("2024-08-19") is False
    assert seg.is_realtime_allowed("2024-08-20") is False


def test_northflow_segmenter_can_cross_segment():
    """can_cross_segment：同段 True，跨段 False。"""
    from predict.features.fund_flow import NorthFlowSegmenter

    seg = NorthFlowSegmenter()
    assert seg.can_cross_segment("2024-08-18", "2024-08-17") is True
    assert seg.can_cross_segment("2024-08-20", "2024-08-21") is True
    assert seg.can_cross_segment("2024-08-18", "2024-08-20") is False
    assert seg.can_cross_segment("2024-08-20", "2024-08-18") is False


# ── (g) sector_rotation_speed ──────────────────────────────────────


def test_sector_rotation_speed_same_ranking():
    """今日与昨日排名相同 → 0.0。"""
    from predict.features.fund_flow import sector_rotation_speed

    today = [
        {"name": "半导体", "net": 10.0},
        {"name": "新能源", "net": 5.0},
        {"name": "医药", "net": 1.0},
    ]
    prev = [
        {"name": "半导体", "net": 8.0},
        {"name": "新能源", "net": 4.0},
        {"name": "医药", "net": 2.0},
    ]
    result = sector_rotation_speed(today, prev)
    assert result == 0.0


def test_sector_rotation_speed_changed_ranking():
    """排名变动 → 正数。"""
    from predict.features.fund_flow import sector_rotation_speed

    today = [
        {"name": "半导体", "net": 10.0},
        {"name": "新能源", "net": 5.0},
        {"name": "医药", "net": 1.0},
    ]
    prev = [
        {"name": "医药", "net": 8.0},
        {"name": "新能源", "net": 4.0},
        {"name": "半导体", "net": 2.0},
    ]
    result = sector_rotation_speed(today, prev)
    assert result is not None
    assert result > 0.0


def test_sector_rotation_speed_empty():
    """空输入 → None。"""
    from predict.features.fund_flow import sector_rotation_speed

    assert sector_rotation_speed([], []) is None


def test_sector_rotation_speed_none_input():
    """None 输入 → None。"""
    from predict.features.fund_flow import sector_rotation_speed

    assert sector_rotation_speed(None, None) is None


def test_sector_rotation_speed_mismatched_sectors():
    """板块列表不匹配 → None。"""
    from predict.features.fund_flow import sector_rotation_speed

    today = [
        {"name": "半导体", "net": 10.0},
        {"name": "新能源", "net": 5.0},
    ]
    prev = [
        {"name": "半导体", "net": 8.0},
        {"name": "新能源", "net": 4.0},
        {"name": "医药", "net": 2.0},
    ]
    assert sector_rotation_speed(today, prev) is None
