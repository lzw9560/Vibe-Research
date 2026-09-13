# -*- coding: utf-8 -*-
"""S199 TDD: direction-aware gap regime encoding (A-share long-only).

S194 F1 ablation found gap signal no_contribution (delta_ic≈0, p=0.33).
Root cause diagnosed (S193 R5 v2): direction-agnostic scalar encoding
(GAP_REGIME_ENCODE drops direction). A-share long-only (§1.1) → downward
regimes are not tradeable, but direction-agnostic encoding feeds them as
if they were upward, diluting upward edge.

Version A = direction-aware: regime_score × direction_weight
  (up→full score, down→0, none→neutral 1.0)
Version B = direction-agnostic (old, for A/B comparison control)
"""
from __future__ import annotations

import pytest

from tools.reconstruct_s194_signals import (
    GAP_REGIME_BASE_SCORE,
    DIRECTION_WEIGHT,
    encode_gap_direction_aware,
    encode_gap_direction_agnostic,
)


class TestDirectionWeight:
    """A-share long-only direction weighting (§1.1: short-selling restricted)."""

    def test_up_full_score(self):
        """向上 → 1.0 (tradeable long)."""
        assert DIRECTION_WEIGHT["向上"] == 1.0

    def test_down_zero(self):
        """向下 → 0.0 (not tradeable, short restricted → zero contribution)."""
        assert DIRECTION_WEIGHT["向下"] == 0.0

    def test_none_neutral(self):
        """无 → 1.0 (no gap = neutral, doesn't zero out the base score)."""
        assert DIRECTION_WEIGHT["无"] == 1.0


class TestEncodeDirectionAware:
    """Version A: regime_score × direction_weight."""

    def test_upward_breakout_full_score(self):
        """趋势启动 + 向上 → 0.9 × 1.0 = 0.9 (full bullish breakout signal)."""
        score = encode_gap_direction_aware("趋势启动", "向上")
        assert score == pytest.approx(0.9)

    def test_downward_breakout_zeroed(self):
        """反转 + 向下 → 0.5 × 0.0 = 0.0 (bearish reversal, not tradeable long-only).

        This is the KEY fix: direction-agnostic gives 0.5, direction-aware gives 0.
        """
        score = encode_gap_direction_aware("反转", "向下")
        assert score == pytest.approx(0.0)

    def test_upward_continuation_full_score(self):
        """趋势中继 + 向上 → 0.7 × 1.0 = 0.7."""
        score = encode_gap_direction_aware("趋势中继", "向上")
        assert score == pytest.approx(0.7)

    def test_downward_continuation_zeroed(self):
        """趋势中继 + 向下 → 0.7 × 0.0 = 0.0 (bearish continuation, not tradeable)."""
        score = encode_gap_direction_aware("趋势中继", "向下")
        assert score == pytest.approx(0.0)

    def test_upward_exhaustion_full_score(self):
        """动能延续 + 向上 → 0.5 × 1.0 = 0.5 (S198 flip: continuation not reversal)."""
        score = encode_gap_direction_aware("动能延续", "向上")
        assert score == pytest.approx(0.5)

    def test_downward_exhaustion_zeroed(self):
        """动能延续 + 向下 → 0.5 × 0.0 = 0.0 (bearish exhaustion, not tradeable long)."""
        score = encode_gap_direction_aware("动能延续", "向下")
        assert score == pytest.approx(0.0)

    def test_upward_noise_partial_score(self):
        """噪声 + 向上 → 0.1 × 1.0 = 0.1."""
        score = encode_gap_direction_aware("噪声", "向上")
        assert score == pytest.approx(0.1)

    def test_downward_noise_zeroed(self):
        """噪声 + 向下 → 0.1 × 0.0 = 0.0."""
        score = encode_gap_direction_aware("噪声", "向下")
        assert score == pytest.approx(0.0)

    def test_no_gap_neutral(self):
        """无 + 无 → 0.0 × 1.0 = 0.0 (no gap = zero signal, not inflated)."""
        score = encode_gap_direction_aware("无", "无")
        assert score == pytest.approx(0.0)

    def test_unknown_direction_defaults_zero(self):
        """Unknown direction → conservative 0.0 (don't feed untradeable signal)."""
        score = encode_gap_direction_aware("趋势启动", "sideways")
        assert score == pytest.approx(0.0)

    def test_unknown_regime_defaults_zero(self):
        """Unknown regime → 0.0."""
        score = encode_gap_direction_aware("nonexistent", "向上")
        assert score == pytest.approx(0.0)


class TestEncodeDirectionAgnostic:
    """Version B: old direction-agnostic encoding (control group)."""

    def test_trend_start_ignores_direction(self):
        """趋势启动 → 0.9 regardless of direction (old behavior)."""
        assert encode_gap_direction_agnostic("趋势启动") == pytest.approx(0.9)
        assert encode_gap_direction_agnostic("趋势启动") == pytest.approx(0.9)

    def test_reversal_keeps_score(self):
        """反转 → 0.5 regardless of direction (old behavior, the bug)."""
        assert encode_gap_direction_agnostic("反转") == pytest.approx(0.5)

    def test_continuation_keeps_score(self):
        """趋势中继 → 0.7 regardless of direction."""
        assert encode_gap_direction_agnostic("趋势中继") == pytest.approx(0.7)

    def test_no_gap_zero(self):
        """无 → 0.0."""
        assert encode_gap_direction_agnostic("无") == pytest.approx(0.0)

    def test_unknown_regime_zero(self):
        """Unknown regime → 0.0."""
        assert encode_gap_direction_agnostic("nonexistent") == pytest.approx(0.0)


class TestABComparison:
    """Prove edge (if any) comes from direction-aware encoding, not other changes."""

    def test_upward_identical_across_versions(self):
        """For upward gaps, A and B should give identical scores (direction weight=1.0)."""
        for regime in ["趋势启动", "动能延续", "趋势中继", "噪声", "反转"]:
            a = encode_gap_direction_aware(regime, "向上")
            b = encode_gap_direction_agnostic(regime)
            assert a == pytest.approx(b), f"regime={regime}: A={a} B={b} should match for 向上"

    def test_downward_diverges(self):
        """For downward gaps, A should be 0 while B keeps the base score."""
        for regime in ["反转", "动能延续", "趋势中继", "噪声"]:
            a = encode_gap_direction_aware(regime, "向下")
            b = encode_gap_direction_agnostic(regime)
            assert a == 0.0, f"regime={regime}: A should be 0 for 向下"
            assert b > 0.0, f"regime={regime}: B should be >0 (old behavior)"
