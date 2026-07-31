"""Tests for predict/feature_interface.py — S018 T12 integration with S017.

Covers: build_default_registry, HEAD_FEATURE_SUBSETS, list_available_features,
get_features (stub DataFrame with correct schema), and look-ahead guard.
"""

from __future__ import annotations

import pandas as pd
import pytest

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def registry():
    """Fresh registry for each test (no _DEFAULT_REGISTRY cache pollution)."""
    from predict.feature_interface import Registry, build_default_registry

    # Use a fresh registry by directly building
    return build_default_registry()


# ── (a) Registry construction and total count ───────────────────────


def test_build_default_registry_returns_registry():
    from predict.feature_interface import build_default_registry
    from predict.features.registry import Registry

    reg = build_default_registry()
    assert isinstance(reg, Registry)


def test_registry_total_features(registry):
    # Total = external 4 + fund_flow 7 + behavior 5 + sentiment 2 + calendar 3 + text 1 + macro 2 + alt 7 = 31
    all_features = registry.list_for_stage("s3")
    assert len(all_features) == 31


# ── (b) Stage filtering (look-ahead guard) ─────────────────────────


def test_list_for_stage_s1_count(registry):
    # s1: fund_flow 7 + behavior 4 (s1 only) + sentiment 2 + text 1 = 14
    s1_features = registry.list_for_stage("s1")
    assert len(s1_features) == 14


def test_list_for_stage_s2_count(registry):
    # s2: s1 14 + external 4 + calendar 3 + macro 2 + alt 7 = 30
    s2_features = registry.list_for_stage("s2")
    assert len(s2_features) == 30


def test_list_for_stage_s3_count(registry):
    # s3: s2 30 + auction_signal (s3) = 31
    s3_features = registry.list_for_stage("s3")
    assert len(s3_features) == 31


# ── (c) HEAD_FEATURE_SUBSETS definitions ────────────────────────────


def test_short_sector_subset_has_23_features():
    from predict.feature_interface import HEAD_FEATURE_SUBSETS

    assert len(HEAD_FEATURE_SUBSETS["short_sector"]) == 23


def test_mid_long_subset_has_7_features():
    from predict.feature_interface import HEAD_FEATURE_SUBSETS

    assert len(HEAD_FEATURE_SUBSETS["mid_long"]) == 7


def test_short_sector_excludes_auction_signal():
    from predict.feature_interface import HEAD_FEATURE_SUBSETS

    assert "auction_signal" not in HEAD_FEATURE_SUBSETS["short_sector"]


def test_mid_long_subset_composition():
    from predict.feature_interface import HEAD_FEATURE_SUBSETS

    mid_long = HEAD_FEATURE_SUBSETS["mid_long"]
    expected_names = {
        "limitup_emotion",
        "sector_divergence",
        "overnight_spx_ret",
        "overnight_ndx_ret",
        "overnight_hstech_ret",
        "overnight_a50_ret",
        "news_emotion",
    }
    assert set(mid_long) == expected_names


# ── (d) list_available_features for short_sector / s1 ───────────────


def test_list_available_features_short_sector_s1_excludes_external_and_calendar():
    from predict.feature_interface import list_available_features

    features = list_available_features("short_sector", "s1")
    for name in features:
        assert not name.startswith("overnight_")
        assert name not in ("is_holiday", "is_delivery_day", "meeting_dummy")


def test_list_available_features_short_sector_s1_includes_fund_flow():
    from predict.feature_interface import list_available_features

    features = list_available_features("short_sector", "s1")
    assert "main_net_5d" in features
    assert "dt_hot_money_relay" in features
    assert "seal_fund_strength" in features
    assert "northbound_net_segmented" in features
    assert "margin_balance_change" in features
    assert "sector_flow_rotation" in features
    assert "block_trade_discount" in features


def test_list_available_features_short_sector_s1_includes_behavior_s1():
    from predict.feature_interface import list_available_features

    features = list_available_features("short_sector", "s1")
    assert "short_term_reversal" in features
    assert "abnormal_turnover" in features
    assert "yesterday_limit_today" in features
    assert "day_trip_risk" in features


def test_list_available_features_short_sector_s1_includes_sentiment():
    from predict.feature_interface import list_available_features

    features = list_available_features("short_sector", "s1")
    assert "limitup_emotion" in features
    assert "sector_divergence" in features


def test_list_available_features_short_sector_s1_includes_text():
    from predict.feature_interface import list_available_features

    features = list_available_features("short_sector", "s1")
    assert "news_emotion" in features


def test_list_available_features_short_sector_s1_excludes_auction_signal():
    from predict.feature_interface import list_available_features

    features = list_available_features("short_sector", "s1")
    assert "auction_signal" not in features


# ── (e) list_available_features for short_sector / s2 ─────────────


def test_list_available_features_short_sector_s2_includes_external():
    from predict.feature_interface import list_available_features

    features = list_available_features("short_sector", "s2")
    assert "overnight_spx_ret" in features
    assert "overnight_ndx_ret" in features
    assert "overnight_hstech_ret" in features
    assert "overnight_a50_ret" in features


def test_list_available_features_short_sector_s2_includes_calendar():
    from predict.feature_interface import list_available_features

    features = list_available_features("short_sector", "s2")
    assert "is_holiday" in features
    assert "is_delivery_day" in features
    assert "meeting_dummy" in features


# ── (f) Unknown head raises KeyError ────────────────────────────────


def test_list_available_features_unknown_head_raises_keyerror():
    from predict.feature_interface import list_available_features

    with pytest.raises(KeyError):
        list_available_features("unknown_head", "s1")


# ── (g) get_features returns empty DataFrame with correct schema ──────


def test_get_features_short_sector_s1_schema():
    from predict.feature_interface import get_features, list_available_features

    df = get_features("short_sector", "s1", "2026-07-29")
    expected_cols = list_available_features("short_sector", "s1")

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == expected_cols
    assert len(df) == 0


def test_get_features_mid_long_s2_schema():
    from predict.feature_interface import get_features, list_available_features

    df = get_features("mid_long", "s2", "2026-07-29")
    expected_cols = list_available_features("mid_long", "s2")

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == expected_cols
    assert len(df) == 0


# ── (h) Column order stability ─────────────────────────────────────


def test_get_features_column_order_is_stable():
    from predict.feature_interface import get_features

    df1 = get_features("short_sector", "s1", "2026-07-29")
    df2 = get_features("short_sector", "s1", "2026-07-30")
    assert list(df1.columns) == list(df2.columns)

    df3 = get_features("mid_long", "s2", "2026-07-29")
    df4 = get_features("mid_long", "s2", "2026-07-30")
    assert list(df3.columns) == list(df4.columns)
