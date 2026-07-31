"""Tests for predict.heads — S017 T2 head interface scaffolding.

All four heads are interface-only (NotImplementedError) except for
property/attribute inspection.
"""

from __future__ import annotations

import pytest

from predict.feature_interface import HEAD_FEATURE_SUBSETS
from predict.heads import (
    Head,
    MidSectorHead,
    MidStockHead,
    ShortSectorHead,
    ShortStockHead,
)


# ── (a) subclass instantiation + name + feature_subset type ──────────────

def test_short_sector_head_instance() -> None:
    h = ShortSectorHead()
    assert h.name == "short_sector"
    assert isinstance(h.feature_subset, tuple)


def test_short_stock_head_instance() -> None:
    h = ShortStockHead()
    assert h.name == "short_stock"
    assert isinstance(h.feature_subset, tuple)


def test_mid_sector_head_instance() -> None:
    h = MidSectorHead()
    assert h.name == "mid_sector"
    assert isinstance(h.feature_subset, tuple)


def test_mid_stock_head_instance() -> None:
    h = MidStockHead()
    assert h.name == "mid_stock"
    assert isinstance(h.feature_subset, tuple)


# ── (b) ShortSectorHead.feature_subset from HEAD_FEATURE_SUBSETS ───────

def test_short_sector_feature_subset() -> None:
    h = ShortSectorHead()
    expected = HEAD_FEATURE_SUBSETS["short_sector"]
    assert h.feature_subset == expected
    # sanity: known count from current feature_interface
    assert len(h.feature_subset) == len(expected)
    # should not contain auction_signal (s3-only, not in short_sector subset)
    assert "auction_signal" not in h.feature_subset
    # should contain fund_flow features
    assert any("fund" in f for f in h.feature_subset)


# ── (c) train/predict/evaluate raise NotImplementedError ────────────────

def test_short_sector_head_train_raises() -> None:
    h = ShortSectorHead()
    with pytest.raises(NotImplementedError):
        h.train(None, None)


def test_short_sector_head_predict_raises() -> None:
    h = ShortSectorHead()
    with pytest.raises(NotImplementedError):
        h.predict("s1", "2026-07-29")


def test_short_sector_head_evaluate_raises() -> None:
    h = ShortSectorHead()
    with pytest.raises(NotImplementedError):
        h.evaluate()


def test_mid_sector_head_methods_raise() -> None:
    h = MidSectorHead()
    with pytest.raises(NotImplementedError):
        h.train(None, None)
    with pytest.raises(NotImplementedError):
        h.predict("s1", "2026-07-29")
    with pytest.raises(NotImplementedError):
        h.evaluate()


# ── (d) ShortStockHead / MidStockHead  raise NotImplementedError ───────

def test_short_stock_head_methods_raise() -> None:
    h = ShortStockHead()
    with pytest.raises(NotImplementedError):
        h.train(None, None)
    with pytest.raises(NotImplementedError):
        h.predict("s1", "2026-07-29")
    with pytest.raises(NotImplementedError):
        h.evaluate()


def test_mid_stock_head_methods_raise() -> None:
    h = MidStockHead()
    with pytest.raises(NotImplementedError):
        h.train(None, None)
    with pytest.raises(NotImplementedError):
        h.predict("s1", "2026-07-29")
    with pytest.raises(NotImplementedError):
        h.evaluate()


# ── (e) Head ABC cannot be instantiated directly ──────────────────────

def test_head_abstract_cannot_instantiate() -> None:
    with pytest.raises(TypeError):
        Head()  # type: ignore[abstract]
