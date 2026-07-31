"""Tests for predict/features/registry.py — T0 slice of S018.

Covers: FeatureSpec construction, register/get, stage filtering (look-ahead
guard), availability_offset check, and compliance_flag constraints.
"""

import pytest


def test_feature_spec_construction():
    from predict.features.registry import FeatureSpec

    spec = FeatureSpec(
        name="overnight_spx_ret",
        source="gstock",
        category="external",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="SPX overnight return",
    )
    assert spec.name == "overnight_spx_ret"
    assert spec.source == "gstock"
    assert spec.availability_offset == 1
    assert spec.stage == "s2"
    assert spec.compliance_flag == "ok"


def test_feature_spec_invalid_compliance_flag():
    from predict.features.registry import FeatureSpec

    with pytest.raises(ValueError, match="compliance_flag"):
        FeatureSpec(
            name="bad",
            source="test",
            category="test",
            availability_offset=0,
            stage="s1",
            compliance_flag="invalid",
            description="",
        )


def test_feature_spec_invalid_stage():
    from predict.features.registry import FeatureSpec

    with pytest.raises(ValueError, match="stage"):
        FeatureSpec(
            name="bad",
            source="test",
            category="test",
            availability_offset=0,
            stage="s5",
            compliance_flag="ok",
            description="",
        )


def test_registry_register_and_get():
    from predict.features.registry import Registry, FeatureSpec

    registry = Registry()
    spec = FeatureSpec(
        name="test_feat",
        source="test_src",
        category="test_cat",
        availability_offset=0,
        stage="s1",
        compliance_flag="ok",
        description="A test feature",
    )
    registry.register(spec)
    assert registry.get_by_name("test_feat") is spec
    assert registry.get_by_name("nonexistent") is None


def test_registry_list_for_stage_filters_unlocked():
    """Look-ahead guard: higher-stage features are invisible at lower stages."""
    from predict.features.registry import Registry, FeatureSpec

    registry = Registry()
    s1_feat = FeatureSpec(
        name="s1_feat", source="s", category="c",
        availability_offset=0, stage="s1",
        compliance_flag="ok", description="",
    )
    s2_feat = FeatureSpec(
        name="s2_feat", source="s", category="c",
        availability_offset=1, stage="s2",
        compliance_flag="ok", description="",
    )
    s3_feat = FeatureSpec(
        name="s3_feat", source="s", category="c",
        availability_offset=0, stage="s3",
        compliance_flag="ok", description="",
    )
    registry.register(s1_feat)
    registry.register(s2_feat)
    registry.register(s3_feat)

    # At s1, only s1 features are visible (look-ahead guard)
    s1_visible = registry.list_for_stage("s1")
    assert len(s1_visible) == 1
    assert s1_visible[0].name == "s1_feat"

    # At s2, s1 and s2 are visible
    s2_visible = registry.list_for_stage("s2")
    assert len(s2_visible) == 2
    assert set(f.name for f in s2_visible) == {"s1_feat", "s2_feat"}

    # At s3, s1, s2, s3 are visible
    s3_visible = registry.list_for_stage("s3")
    assert len(s3_visible) == 3

    # At s4, all visible
    s4_visible = registry.list_for_stage("s4")
    assert len(s4_visible) == 3


def test_registry_list_for_stage_aggregate_only_compliance():
    """aggregate_only compliance flag is preserved and recognizable."""
    from predict.features.registry import Registry, FeatureSpec

    registry = Registry()
    agg_feat = FeatureSpec(
        name="limitup_aggregate",
        source="limitup_sti",
        category="sentiment",
        availability_offset=0,
        stage="s1",
        compliance_flag="aggregate_only",
        description="Aggregate sentiment, no individual stock names",
    )
    registry.register(agg_feat)

    result = registry.list_for_stage("s1")
    assert len(result) == 1
    assert result[0].compliance_flag == "aggregate_only"
    assert result[0].name == "limitup_aggregate"


def test_registry_availability_offset_non_negative():
    """availability_offset must be >= 0."""
    from predict.features.registry import FeatureSpec

    with pytest.raises(ValueError, match="availability_offset"):
        FeatureSpec(
            name="bad",
            source="s",
            category="c",
            availability_offset=-1,
            stage="s1",
            compliance_flag="ok",
            description="",
        )


def test_registry_register_duplicate_raises():
    """Registering the same feature name twice raises KeyError."""
    from predict.features.registry import Registry, FeatureSpec

    registry = Registry()
    spec = FeatureSpec(
        name="dup", source="s", category="c",
        availability_offset=0, stage="s1",
        compliance_flag="ok", description="",
    )
    registry.register(spec)
    with pytest.raises(KeyError, match="already registered"):
        registry.register(spec)


def test_registry_list_for_stage_invalid_stage_raises():
    """list_for_stage with an invalid stage raises ValueError."""
    from predict.features.registry import Registry

    registry = Registry()
    with pytest.raises(ValueError, match="stage"):
        registry.list_for_stage("s5")


def test_list_for_head_stub_returns_all():
    """list_for_head is a stub returning all registered features for now."""
    from predict.features.registry import Registry, FeatureSpec

    registry = Registry()
    registry.register(
        FeatureSpec(
            name="f1", source="s", category="c",
            availability_offset=0, stage="s1",
            compliance_flag="ok", description="",
        )
    )
    registry.register(
        FeatureSpec(
            name="f2", source="s", category="c",
            availability_offset=1, stage="s2",
            compliance_flag="ok", description="",
        )
    )
    # list_for_head is a stub: returns all for now
    head_result = registry.list_for_head("short_sector")
    assert len(head_result) == 2
