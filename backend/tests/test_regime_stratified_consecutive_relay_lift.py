# -*- coding: utf-8 -*-
"""TDD tests for regime_stratified_consecutive_relay_lift harness (AAA pattern).

RED -> GREEN.  Tests harness stratifies synthetic returns by MA20 3-way regime
(bull/bear/range), wires per-regime verdict via wire_verdict (n_comparisons=4
per family, K=12 split 3 family each K=4<=8 decision #9), skips small-n
regimes, and returns structured results.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from tools import regime_stratified_consecutive_relay_lift as harness


@dataclass(frozen=True)
class _FakeVerdict:
    status: str = "underpowered"
    edge_type: str = "event"
    selection_lift: Optional[float] = None
    n: int = 50
    days_robust: int = 10
    note: str = "underpowered: days_robust=10<60 (R6 gate)"


def _make_synthetic_data(n_days_per_regime: int = 20, picks_per_day: int = 3):
    """Generate synthetic returns / dates / regime_map.

    n_days_per_regime days x 3 regimes x picks_per_day picks per day.
    Bull: positive mean; bear: negative mean; range: near-zero mean.
    """
    dates: list[str] = []
    returns: list[float] = []
    regime_map: dict[str, str] = {}

    for i in range(n_days_per_regime):
        d = f"2026-01-{i + 1:02d}"
        for _ in range(picks_per_day):
            dates.append(d)
            returns.append(0.01)
        regime_map[d] = "bull"

    for i in range(n_days_per_regime):
        d = f"2026-02-{i + 1:02d}"
        for _ in range(picks_per_day):
            dates.append(d)
            returns.append(-0.01)
        regime_map[d] = "bear"

    for i in range(n_days_per_regime):
        d = f"2026-03-{i + 1:02d}"
        for _ in range(picks_per_day):
            dates.append(d)
            returns.append(0.001)
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
        assert r["n_picks"] == 60  # 20 days x 3 picks
        assert r["verdict_status"] == "underpowered"

    # 3 wire_verdict calls
    assert len(calls) == 3
    line_ids = [c["line_id"] for c in calls]
    assert "consecutive_relay_regime:bull" in line_ids
    assert "consecutive_relay_regime:bear" in line_ids
    assert "consecutive_relay_regime:range" in line_ids


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

    # Assert -- range skipped (0 picks), bear skipped (1 pick), bull verdict (2 picks)
    assert results["range"]["n_picks"] == 0
    assert results["range"]["verdict_status"] == "skipped"
    assert results["bear"]["n_picks"] == 1
    assert results["bear"]["verdict_status"] == "skipped"
    assert results["bull"]["n_picks"] == 2
    # only bull has >=2 picks -> 1 wire_verdict call
    assert len(calls) == 1
    assert calls[0]["line_id"] == "consecutive_relay_regime:bull"


def test_run_returns_empty_when_regime_map_empty(monkeypatch):
    """Empty regime_map -> returns empty dict, no wire_verdict calls."""
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


def test_run_includes_regime_stats(monkeypatch):
    """Results include per-regime stats (n_picks, n_days, net_mean_pct, win_rate)."""
    # Arrange
    returns, dates, regime_map = _make_synthetic_data(n_days_per_regime=5)
    monkeypatch.setattr(harness, "wire_verdict", lambda **kw: _FakeVerdict())

    # Act
    results = harness.run(returns=returns, dates=dates, regime_map=regime_map)

    # Assert -- stats fields present
    for tag in ("bull", "bear", "range"):
        r = results[tag]
        assert "n_picks" in r
        assert "n_days" in r
        assert "net_mean_pct" in r
        assert "win_rate" in r
        assert "day_clustered_t_stat" in r
    # bull positive, bear negative
    assert results["bull"]["net_mean_pct"] is not None
    assert results["bull"]["net_mean_pct"] > 0
    assert results["bear"]["net_mean_pct"] < 0


def test_run_uses_event_edge_type(monkeypatch):
    """edge_type='event' (not selection) -- tests group return > 0 per regime."""
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
        # event edge does NOT pass survivors_by_day / universe_by_day
        assert call.get("survivors_by_day") is None
        assert call.get("universe_by_day") is None


def test_run_passes_filtered_universe_by_day_per_regime(monkeypatch):
    """S210 T2: run() 传 universe_by_day → per regime wire_verdict 收到 filtered（同 regime days）。

    drift fix：event edge 也传 universe_by_day，per regime filter 同 regime days
    让 drift fix 控 regime-specific drift。
    """
    returns, dates, regime_map = _make_synthetic_data(n_days_per_regime=20, picks_per_day=3)
    universe_global = {d: [0.001] for d in regime_map}  # 1 gap per regime day

    captured: dict = {}

    def _fake_wire(line_id, **kwargs):
        captured[line_id] = kwargs.get("universe_by_day")
        return _FakeVerdict()

    monkeypatch.setattr(harness, "wire_verdict", _fake_wire)

    harness.run(
        returns=returns, dates=dates, regime_map=regime_map,
        universe_by_day=universe_global,
    )

    # bull wire_verdict 收到 bull days only (2026-01-*)
    bull_universe = captured.get("consecutive_relay_regime:bull")
    assert bull_universe is not None
    assert all(d.startswith("2026-01") for d in bull_universe)
    assert len(bull_universe) == 20  # 20 bull days
    # bear 收到 bear days (2026-02-*)
    bear_universe = captured.get("consecutive_relay_regime:bear")
    assert all(d.startswith("2026-02") for d in bear_universe)
    # range 收到 range days (2026-03-*)
    range_universe = captured.get("consecutive_relay_regime:range")
    assert all(d.startswith("2026-03") for d in range_universe)


def test_run_universe_by_day_none_backward_compat(monkeypatch):
    """S210 T2: universe_by_day=None → wire_verdict 收到 None（向后兼容，drift None）。"""
    returns, dates, regime_map = _make_synthetic_data(n_days_per_regime=20, picks_per_day=3)
    captured: dict = {}

    def _fake_wire(line_id, **kwargs):
        captured[line_id] = kwargs.get("universe_by_day")
        return _FakeVerdict()

    monkeypatch.setattr(harness, "wire_verdict", _fake_wire)

    harness.run(returns=returns, dates=dates, regime_map=regime_map)  # universe_by_day=None

    for tag in ("bull", "bear", "range"):
        assert captured[f"consecutive_relay_regime:{tag}"] is None
