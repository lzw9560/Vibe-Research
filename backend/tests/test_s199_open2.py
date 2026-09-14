# -*- coding: utf-8 -*-
"""S199 open-2: Section C overlap fix + regime-stratified gap edge.

Two grill-recommended follow-up items from S199 verdict (needs-revision):

Test 1 — Section C overlap fix:
  Version B (direction-agnostic) raw group must not contain downward gaps.
  Bug: ``raw_b = raw_a`` reused the direction-aware no-gap set, which includes
  downward gaps (gap_a==0 but gap_b>0), causing them to appear in BOTH
  surv_b and raw_b — contaminating the lift.

Test 2 — regime-stratified gap edge:
  Gap edge lift (day_paired + permutation) within bull vs bear vs range.
  S198 gate tested bull/bear continuation rates, but S199 never ran
  regime-stratified lift for gap-as-selection-signal.

§44v2 compliance: day_clustered + permutation + Bonferroni + pre-window sanity.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import pytest

from tools.reconstruct_s194_signals import (
    encode_gap_direction_aware,
    encode_gap_direction_agnostic,
)


# ─── synthetic data helpers ──────────────────────────────────────────────


def _make_bars(d0: str, n_days: int, closes: list[float] | None = None) -> list[dict]:
    """Create n_days bars starting from d0 with given (or default) closes."""
    start = date.fromisoformat(d0)
    if closes is None:
        closes = [10.0 + 0.1 * i for i in range(n_days)]
    assert len(closes) >= n_days
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "close": c, "volume": 1000}
        for i, c in enumerate(closes[:n_days])
    ]


def _make_case(
    stock: str,
    entry_date: str,
    gross_return: float | None,
    gap_regime: str,
    gap_direction: str,
    arm: str = "breakout",
) -> dict:
    return {
        "stock": stock,
        "entry_date": entry_date,
        "gross_return": gross_return,
        "gap_regime": gap_regime,
        "gap_direction": gap_direction,
        "arm": arm,
    }


def _encode(data: list[dict]) -> list[dict]:
    """Add gap_a (direction-aware) and gap_b (direction-agnostic) to each case."""
    for d in data:
        d["gap_a"] = encode_gap_direction_aware(d["gap_regime"], d["gap_direction"])
        d["gap_b"] = encode_gap_direction_agnostic(d["gap_regime"])
    return data


def _make_get_bars(bars_map: dict[str, list[dict]]):
    """Create a get_bars callable from a {stock: bars} map."""
    def get_bars(code: str) -> list[dict]:
        return bars_map.get(code, [])
    return get_bars


# ─── Test 1: Section C overlap fix ────────────────────────────────────────


class TestSplitFwdReturnsNoOverlap:
    """Version B split must be disjoint — no case in both surv and raw.

    Bug (line 307 ``raw_b = raw_a``): direction-aware no-gap set (gap_a==0)
    includes downward gaps, which also have gap_b>0 (direction-agnostic keeps
    base score). So downward gaps contaminated BOTH surv_b and raw_b.
    """

    def test_gap_b_split_disjoint(self):
        """gap_b split: downward gap is in surv_b, NOT raw_b."""
        from tools.s199_s44_verify import split_fwd_returns

        bars = _make_bars("2026-01-01", 10)
        get_bars = _make_get_bars({"s1": bars, "s2": bars, "s3": bars})

        data = _encode([
            _make_case("s1", "2026-01-01", None, "趋势启动", "向上"),
            _make_case("s2", "2026-01-01", None, "趋势启动", "向下"),
            _make_case("s3", "2026-01-01", None, "无", "无"),
        ])
        # sanity: encodings
        assert data[0]["gap_b"] > 0   # upward → base kept
        assert data[1]["gap_b"] > 0   # downward → base kept (direction-agnostic!)
        assert data[1]["gap_a"] == 0  # downward → zeroed (direction-aware)
        assert data[2]["gap_b"] == 0  # no gap

        surv_b, raw_b, all_b = split_fwd_returns(data, "gap_b", 5, get_bars)

        # surv_b = gap_b > 0 = upward + downward = 2 cases
        assert len(surv_b["2026-01-01"]) == 2
        # raw_b = gap_b == 0 = no gap only = 1 case (NOT 2!)
        assert len(raw_b["2026-01-01"]) == 1
        # disjoint partition: surv + raw == all
        n_surv = sum(len(v) for v in surv_b.values())
        n_raw = sum(len(v) for v in raw_b.values())
        n_all = sum(len(v) for v in all_b.values())
        assert n_surv + n_raw == n_all, "overlap: surv+raw != all"

    def test_gap_a_split_disjoint(self):
        """gap_a split is already disjoint — sanity check (no bug here)."""
        from tools.s199_s44_verify import split_fwd_returns

        bars = _make_bars("2026-01-01", 10)
        get_bars = _make_get_bars({"s1": bars, "s2": bars, "s3": bars})

        data = _encode([
            _make_case("s1", "2026-01-01", None, "趋势启动", "向上"),
            _make_case("s2", "2026-01-01", None, "趋势启动", "向下"),
            _make_case("s3", "2026-01-01", None, "无", "无"),
        ])
        surv_a, raw_a, all_a = split_fwd_returns(data, "gap_a", 5, get_bars)

        # gap_a > 0 = upward only = 1
        assert len(surv_a["2026-01-01"]) == 1
        # gap_a == 0 = downward + no-gap = 2
        assert len(raw_a["2026-01-01"]) == 2
        n_surv = sum(len(v) for v in surv_a.values())
        n_raw = sum(len(v) for v in raw_a.values())
        n_all = sum(len(v) for v in all_a.values())
        assert n_surv + n_raw == n_all

    def test_gap_b_no_downward_in_raw(self):
        """Explicitly: downward gap case must NOT appear in raw_b."""
        from tools.s199_s44_verify import split_fwd_returns

        bars = _make_bars("2026-01-01", 10)
        get_bars = _make_get_bars({"down": bars, "none": bars})

        data = _encode([
            _make_case("down", "2026-01-01", None, "趋势启动", "向下"),
            _make_case("none", "2026-01-01", None, "无", "无"),
        ])
        surv_b, raw_b, _ = split_fwd_returns(data, "gap_b", 5, get_bars)

        # downward case (gap_b=0.9>0) → in surv_b
        assert "2026-01-01" in surv_b
        assert len(surv_b["2026-01-01"]) == 1
        # no-gap case (gap_b=0) → in raw_b
        assert "2026-01-01" in raw_b
        assert len(raw_b["2026-01-01"]) == 1
        # downward NOT in raw_b (the bug would put it there via raw_b=raw_a)
        assert len(raw_b["2026-01-01"]) == 1  # only no-gap, not downward


class TestSplitTradeReturnsNoOverlap:
    """Trade-level split (gross_return) must also be disjoint for gap_b."""

    def test_gap_b_trade_split_disjoint(self):
        from tools.s199_s44_verify import split_trade_returns

        data = _encode([
            _make_case("s1", "2026-01-01", 0.05, "趋势启动", "向上"),
            _make_case("s2", "2026-01-01", -0.03, "趋势启动", "向下"),
            _make_case("s3", "2026-01-01", 0.01, "无", "无"),
        ])
        surv_b, raw_b, all_b = split_trade_returns(data, "gap_b")

        assert len(surv_b["2026-01-01"]) == 2   # upward + downward
        assert len(raw_b["2026-01-01"]) == 1     # no-gap only
        n_surv = sum(len(v) for v in surv_b.values())
        n_raw = sum(len(v) for v in raw_b.values())
        n_all = sum(len(v) for v in all_b.values())
        assert n_surv + n_raw == n_all


# ─── Test 2: regime-stratified gap edge ──────────────────────────────────


class TestRegimeStratifiedLift:
    """Gap edge lift (day_paired + permutation) per regime (bull/bear/range)."""

    @staticmethod
    def _make_regime_data() -> tuple[list[dict], dict[str, str]]:
        """Create synthetic data spanning bull/bear/range regimes.

        4 days per regime, each day has 1 gap-present (upward) + 1 no-gap case.
        Uses shared bars so forward returns are deterministic.
        """
        bars = _make_bars("2026-01-01", 20)
        get_bars_fn = lambda code: bars  # noqa: E731
        regime_map: dict[str, str] = {}
        cases: list[dict] = []
        # 4 days bull (01-04), 4 days bear (05-08), 4 days range (09-12)
        regimes = [
            ("bull", ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            ("bear", ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]),
            ("range", ["2026-01-09", "2026-01-10", "2026-01-11", "2026-01-12"]),
        ]
        for tag, dates in regimes:
            for i, d in enumerate(dates):
                regime_map[d] = tag
                # gap-present case (upward trend-start)
                cases.append(_make_case(
                    f"{tag}_gap_{i}", d, 0.05 + 0.01 * i,
                    "趋势启动", "向上"))
                # no-gap case
                cases.append(_make_case(
                    f"{tag}_none_{i}", d, 0.02 - 0.01 * i,
                    "无", "无"))
        _encode(cases)
        return cases, regime_map

    def test_returns_all_regimes(self):
        """regime_stratified_lift returns bull/bear/range keys."""
        from tools.s199_s44_verify import regime_stratified_lift

        cases, regime_map = self._make_regime_data()
        bars = _make_bars("2026-01-01", 20)
        get_bars = _make_get_bars({c["stock"]: bars for c in cases})

        results = regime_stratified_lift(
            cases, "gap_a", regime_map, (5,), get_bars)

        assert "bull" in results
        assert "bear" in results
        assert "range" in results

    def test_each_regime_has_lift_and_perm_p(self):
        """Each regime's per-window result has lift, perm_p, n_days, surv_n, raw_n."""
        from tools.s199_s44_verify import regime_stratified_lift

        cases, regime_map = self._make_regime_data()
        bars = _make_bars("2026-01-01", 20)
        get_bars = _make_get_bars({c["stock"]: bars for c in cases})

        results = regime_stratified_lift(
            cases, "gap_a", regime_map, (5,), get_bars)

        for tag in ("bull", "bear", "range"):
            assert 5 in results[tag], f"{tag} missing window 5"
            r = results[tag][5]
            assert "lift" in r
            assert "perm_p" in r
            assert "n_days" in r
            assert "surv_n" in r
            assert "raw_n" in r

    def test_cases_split_by_regime_tag(self):
        """Cases with bull dates go to bull, bear dates to bear, etc."""
        from tools.s199_s44_verify import regime_stratified_lift

        cases, regime_map = self._make_regime_data()
        bars = _make_bars("2026-01-01", 20)
        get_bars = _make_get_bars({c["stock"]: bars for c in cases})

        results = regime_stratified_lift(
            cases, "gap_a", regime_map, (5,), get_bars)

        # 4 days per regime, each with 1 surv + 1 raw → surv_n=4, raw_n=4
        for tag in ("bull", "bear", "range"):
            r = results[tag][5]
            assert r["surv_n"] == 4, f"{tag} surv_n={r['surv_n']} (expected 4)"
            assert r["raw_n"] == 4, f"{tag} raw_n={r['raw_n']} (expected 4)"

    def test_untagged_cases_excluded(self):
        """Cases whose entry_date has no regime tag are excluded."""
        from tools.s199_s44_verify import regime_stratified_lift

        cases, regime_map = self._make_regime_data()
        # Add a case with an untagged date
        cases.append(_make_case(
            "extra", "2026-06-01", 0.05, "趋势启动", "向上"))
        _encode(cases)
        bars = _make_bars("2026-01-01", 40)
        get_bars = _make_get_bars({c["stock"]: bars for c in cases})

        results = regime_stratified_lift(
            cases, "gap_a", regime_map, (5,), get_bars)

        # extra case not in any regime
        total_surv = sum(
            results[t][5]["surv_n"] for t in ("bull", "bear", "range")
        )
        assert total_surv == 12  # 4 per regime × 3, extra excluded

    def test_trade_level_regime_stratified(self):
        """regime_stratified_trade_lift works on gross_return (no bars needed)."""
        from tools.s199_s44_verify import regime_stratified_trade_lift

        cases, regime_map = self._make_regime_data()
        results = regime_stratified_trade_lift(cases, "gap_a", regime_map)

        for tag in ("bull", "bear", "range"):
            assert "lift" in results[tag]
            assert "perm_p" in results[tag]
            assert results[tag]["surv_n"] == 4
            assert results[tag]["raw_n"] == 4
