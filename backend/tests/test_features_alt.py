# -*- coding: utf-8 -*-
"""S020 alt 特征注册单测：7 FeatureSpec 合法、注册可查、不入 head 子集（R10）。"""
from predict.features.alt import ALT_SPECS, register_alt
from predict.features.registry import Registry


def test_alt_specs_count_and_valid():
    assert len(ALT_SPECS) == 7


def test_alt_specs_construct_valid():
    """FeatureSpec __post_init__ 校验过（offset>=0, stage 合法, compliance_flag 合法）。"""
    for s in ALT_SPECS:
        assert s.source == "worldmonitor"
        assert s.category == "alt"
        assert s.stage == "s2"
        assert s.compliance_flag in ("ok", "aggregate_only")


def test_register_alt_makes_features_queryable():
    reg = Registry()
    register_alt(reg)
    for s in ALT_SPECS:
        assert reg.get_by_name(s.name) is s


def test_alt_not_in_head_subset():
    """R10: alt 特征不在任何 HEAD_FEATURE_SUBSETS（live 冒烟前）。"""
    from predict.feature_interface import HEAD_FEATURE_SUBSETS
    alt_names = {s.name for s in ALT_SPECS}
    for head, feats in HEAD_FEATURE_SUBSETS.items():
        assert not (alt_names & set(feats)), f"{head} 含 alt 特征（违反 R10）"
