# -*- coding: utf-8 -*-
"""TDD tests for regime_stratified_reverse_package_lift harness (AAA pattern).

RED -> GREEN.  Same pattern as first_board_limitup harness but for
reverse_package (zhaban fanbao = failed-seal reversal).  Verifies the
harness uses the correct line_id prefix and script path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from tools import regime_stratified_reverse_package_lift as harness


@dataclass(frozen=True)
class _FakeVerdict:
    status: str = "underpowered"
    edge_type: str = "event"
    selection_lift: Optional[float] = None
    n: int = 50
    days_robust: int = 10
    note: str = "underpowered: days_robust=10<60 (R6 gate)"


def _make_synthetic_data(n_days_per_regime: int = 20, picks_per_day: int = 3):
    """Generate synthetic returns / dates / regime_map (same as first_board test)."""
    dates: list[str] = []
    returns: list[float] = []
    regime_map: dict[str, str] = {}

    for i in range(n_days_per_regime):
        d = f"2026-04-{i + 1:02d}"
        for _ in range(picks_per_day):
            dates.append(d)
            returns.append(0.015)
        regime_map[d] = "bull"

    for i in range(n_days_per_regime):
        d = f"2026-05-{i + 1:02d}"
        for _ in range(picks_per_day):
            dates.append(d)
            returns.append(-0.012)
        regime_map[d] = "bear"

    for i in range(n_days_per_regime):
        d = f"2026-06-{i + 1:02d}"
        for _ in range(picks_per_day):
            dates.append(d)
            returns.append(0.002)
        regime_map[d] = "range"

    return returns, dates, regime_map


# -- Tests --


def test_run_produces_verdict_per_regime(monkeypatch):
    """Harness stratifies synthetic returns by regime -> wire_verdict per regime."""
    # Arrange
    returns, dates, regime_map = _make_synthetic_data()
    calls: list[dict] = []

    def _fake_wire_verdict(**kwargs):
        calls.append(kwargs)
        return _FakeVerdict()

    monkeypatch.setattr(harness, "wire_verdict", _fake_wire_verdict)

    # Act
    results = harness.run(
        returns=returns,
        dates=dates,
        regime_map=regime_map,
    )

    # Assert -- 3 regimes each with verdict
    assert set(results.keys()) == {"bull", "bear", "range"}
    for tag in ("bull", "bear", "range"):
        r = results[tag]
        assert r["n_picks"] == 60
        assert r["verdict_status"] == "underpowered"

    # 3 wire_verdict calls with reverse_package line_id prefix
    assert len(calls) == 3
    line_ids = [c["line_id"] for c in calls]
    assert "reverse_package_regime:bull" in line_ids
    assert "reverse_package_regime:bear" in line_ids
    assert "reverse_package_regime:range" in line_ids


def test_run_passes_n_comparisons_4_per_family(monkeypatch):
    """n_comparisons=4 per family (K=4, decision #9; total K=12 split 3 families)."""
    # Arrange
    returns, dates, regime_map = _make_synthetic_data(n_days_per_regime=5)
    calls: list[dict] = []

    def _fake_wire_verdict(**kwargs):
        calls.append(kwargs)
        return _FakeVerdict()

    monkeypatch.setattr(harness, "wire_verdict", _fake_wire_verdict)

    # Act
    harness.run(returns=returns, dates=dates, regime_map=regime_map)

    # Assert -- each call has n_comparisons=4
    assert len(calls) == 3
    for call in calls:
        assert call["n_comparisons"] == 4
        assert call["edge_type"] == "event"


def test_run_skips_regime_with_too_few_picks(monkeypatch):
    """Regime with < 2 picks -> skipped, no wire_verdict call for that regime."""
    # Arrange
    returns = [0.01, -0.02, 0.03]
    dates = ["d1", "d1", "d2"]
    regime_map = {"d1": "bull", "d2": "bear"}  # range has 0 picks
    calls: list[dict] = []

    def _fake_wire_verdict(**kwargs):
        calls.append(kwargs)
        return _FakeVerdict()

    monkeypatch.setattr(harness, "wire_verdict", _fake_wire_verdict)

    # Act
    results = harness.run(
        returns=returns,
        dates=dates,
        regime_map=regime_map,
    )

    # Assert -- range skipped, bear skipped (1 pick), bull verdict (2 picks)
    assert results["range"]["n_picks"] == 0
    assert results["range"]["verdict_status"] == "skipped"
    assert results["bear"]["n_picks"] == 1
    assert results["bear"]["verdict_status"] == "skipped"
    assert results["bull"]["n_picks"] == 2
    assert len(calls) == 1
    assert calls[0]["line_id"] == "reverse_package_regime:bull"


def test_run_returns_empty_when_regime_map_empty(monkeypatch):
    """Empty regime_map -> returns empty dict."""
    # Arrange
    monkeypatch.setattr(harness, "wire_verdict", lambda **kw: _FakeVerdict())

    # Act
    results = harness.run(
        returns=[0.01, 0.02],
        dates=["d1", "d2"],
        regime_map={},
    )

    # Assert
    assert results == {}


def test_run_uses_event_edge_type(monkeypatch):
    """edge_type='event' -- tests group return > 0 per regime (not selection lift)."""
    # Arrange
    returns, dates, regime_map = _make_synthetic_data(n_days_per_regime=3)
    calls: list[dict] = []

    def _fake_wire_verdict(**kwargs):
        calls.append(kwargs)
        return _FakeVerdict()

    monkeypatch.setattr(harness, "wire_verdict", _fake_wire_verdict)

    # Act
    harness.run(returns=returns, dates=dates, regime_map=regime_map)

    # Assert
    assert len(calls) == 3
    for call in calls:
        assert call["edge_type"] == "event"
        assert call.get("survivors_by_day") is None
        assert call.get("universe_by_day") is None
