"""Tests for predict.labels — S017 T1 label construction.

Covers LabelConfig frozen dataclass and build_label / build_labels_series
pure functions.
"""

from __future__ import annotations

import pytest

from predict.labels import (
    MID_HORIZON_DAYS,
    SHORT_HORIZON_DAYS,
    LabelConfig,
    build_label,
    build_labels_series,
)


# ── (a) LabelConfig ────────────────────────────────────────────────────

def test_labelconfig_valid() -> None:
    c = LabelConfig(target="sector_idx", horizon="short", direction="up")
    assert c.target == "sector_idx"
    assert c.horizon == "short"
    assert c.direction == "up"


def test_labelconfig_invalid_horizon() -> None:
    with pytest.raises(ValueError):
        LabelConfig(target="sector_idx", horizon="long", direction="up")


def test_labelconfig_invalid_direction() -> None:
    with pytest.raises(ValueError):
        LabelConfig(target="600001.SH", horizon="short", direction="sideways")


def test_labelconfig_default_direction() -> None:
    c = LabelConfig(target="600001.SH", horizon="short")
    assert c.direction == "up"


# ── (b) constants ────────────────────────────────────────────────────

def test_horizon_constants() -> None:
    assert SHORT_HORIZON_DAYS == 3
    assert MID_HORIZON_DAYS == 20


# ── (c) build_label ────────────────────────────────────────────────────

def test_build_label_up_positive() -> None:
    # prices rise over 3 days: 100 -> 101 -> 102 -> 103
    prices = [100.0, 101.0, 102.0, 103.0]
    config = LabelConfig(target="sector_idx", horizon="short", direction="up")
    assert build_label(prices, config) == 1


def test_build_label_up_negative() -> None:
    # prices fall over 3 days: 100 -> 99 -> 98 -> 97
    prices = [100.0, 99.0, 98.0, 97.0]
    config = LabelConfig(target="sector_idx", horizon="short", direction="up")
    assert build_label(prices, config) == 0


def test_build_label_down_positive() -> None:
    # prices rise -> down direction should label as 0 (upward is bad for down)
    prices = [100.0, 101.0, 102.0, 103.0]
    config = LabelConfig(target="sector_idx", horizon="short", direction="down")
    assert build_label(prices, config) == 0


def test_build_label_down_negative() -> None:
    # prices fall -> down direction should label as 1 (downward is good for down)
    prices = [100.0, 99.0, 98.0, 97.0]
    config = LabelConfig(target="sector_idx", horizon="short", direction="down")
    assert build_label(prices, config) == 1


def test_build_label_mid_horizon() -> None:
    # 20-day horizon: need 21 prices, last > first => 1
    prices = [100.0] + [100.0 + i for i in range(1, 21)]  # 21 items, last=120
    config = LabelConfig(target="sector_idx", horizon="mid", direction="up")
    assert build_label(prices, config) == 1


# ── (d) build_label boundary: future_return == 0 ─────────────────────

def test_build_label_up_zero_return() -> None:
    # prices flat over horizon => return == 0 => label 0 for up
    prices = [100.0, 101.0, 99.0, 100.0]
    config = LabelConfig(target="sector_idx", horizon="short", direction="up")
    assert build_label(prices, config) == 0


def test_build_label_down_zero_return() -> None:
    # prices flat => return == 0 => label 0 for down (not strictly < 0)
    prices = [100.0, 101.0, 102.0, 102.0]
    config = LabelConfig(target="sector_idx", horizon="short", direction="down")
    assert build_label(prices, config) == 0


# ── (e) build_labels_series ──────────────────────────────────────────

def test_build_labels_series_basic() -> None:
    # 5 prices: ascending except last dip
    prices = [100.0, 101.0, 102.0, 103.0, 102.0]
    config = LabelConfig(target="sector_idx", horizon="short", direction="up")
    labels = build_labels_series(prices, config)
    # For short=3, first 3 labels are None, then from index 3 onward
    assert len(labels) == len(prices)
    assert labels[0] is None
    assert labels[1] is None
    assert labels[2] is None
    # index 3: compare prices[3]=103 vs prices[0]=100 => up => 1
    assert labels[3] == 1
    # index 4: compare prices[4]=102 vs prices[1]=101 => up => 1
    assert labels[4] == 1


def test_build_labels_series_with_dips() -> None:
    prices = [100.0, 102.0, 101.0, 100.0, 99.0]
    config = LabelConfig(target="sector_idx", horizon="short", direction="up")
    labels = build_labels_series(prices, config)
    assert len(labels) == len(prices)
    assert labels[0] is None
    assert labels[1] is None
    assert labels[2] is None
    # index 3: prices[3]=100 vs prices[0]=100 => 0 => 0
    assert labels[3] == 0
    # index 4: prices[4]=99 vs prices[1]=102 => down => 0
    assert labels[4] == 0


# ── (f) edge cases ───────────────────────────────────────────────────

def test_build_label_insufficient_prices() -> None:
    prices = [100.0, 101.0]  # need 4 for short=3
    config = LabelConfig(target="sector_idx", horizon="short", direction="up")
    assert build_label(prices, config) is None


def test_build_labels_series_empty() -> None:
    labels = build_labels_series([], LabelConfig(target="x", horizon="short"))
    assert labels == []


def test_build_labels_series_insufficient() -> None:
    prices = [100.0, 101.0]
    config = LabelConfig(target="x", horizon="short", direction="up")
    labels = build_labels_series(prices, config)
    assert labels == [None, None]


def test_build_label_exact_length() -> None:
    # exactly 4 prices for short=3
    prices = [100.0, 101.0, 102.0, 103.0]
    config = LabelConfig(target="x", horizon="short", direction="up")
    assert build_label(prices, config) == 1
