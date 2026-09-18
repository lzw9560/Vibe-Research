# -*- coding: utf-8 -*-
"""S218 P0-2: daily regime/sentiment hard-stop gate tests.

Tests verify three hard-stop conditions:
1. non-bull regime (bear/range) -> 0 tradable (already in C1, verify via 3-bucket)
2. sentiment retreat (storm) -> 0 tradable even in bull
3. regime cache stale (>T-1) -> 0 tradable (untrusted regime label)

Also verifies:
- sentiment hard-stop reuses compute_weather_snapshot (no recomputation)
- no regression in C1 daily_report
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# -- fixtures ----------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_deps(monkeypatch, tmp_path):
    """Mock all external dependencies."""
    monkeypatch.setattr(
        "pre_limitup_scanner.scan_consecutive_relay",
        MagicMock(return_value=[
            {"code": "000001", "lbc": 2},
            {"code": "000002", "lbc": 3},
        ]),
    )
    monkeypatch.setattr(
        "candidate_funnel.evaluation.lift_for_arm",
        MagicMock(return_value=(0.75, "bull validated")),
    )
    monkeypatch.setattr(
        "ai.tools.stock_tools.query_quote",
        MagicMock(return_value={
            "000001": {"name": "PingAn Bank", "close": 12.34},
            "000002": {"name": "Vanke A", "close": 15.67},
        }),
    )
    monkeypatch.setattr(
        "engine.bars_provider.KlineCacheBarsProvider",
        lambda: MagicMock(return_value=[
            {"date": "2026-09-18", "open": 12.30, "close": 12.34, "high": 12.40, "low": 12.20, "pctChg": 0.32},
        ]),
    )
    monkeypatch.setattr(
        "engine.bar_utils.is_unbuyable_next_bar",
        MagicMock(return_value=False),
    )

    # Default regime: bull (so regime hard-stop does not trigger by default)
    monkeypatch.setattr(
        "tools.gap_regime_stratified.compute_regime_labels",
        MagicMock(return_value={"2026-09-18": "bull"}),
    )
    # Default sentiment: sunny (so sentiment hard-stop does not trigger by default;
    # individual storm/exception tests override this)
    monkeypatch.setattr(
        "routers.sentiment_weather.compute_weather_snapshot",
        MagicMock(return_value={
            "weather_state": "晴天",
            "composite_score": 78.0,
            "data_status": "ok",
        }),
    )
    # Default regime cache: fresh (today, so cache-stale hard-stop does not
    # trigger by default; individual stale tests override this)
    _today = datetime.now().strftime("%Y-%m-%d")
    monkeypatch.setattr(
        "tools.signal_report._load_regime_cache",
        lambda: {_today: {"close": 3500.0, "ma20": 3520.0, "regime": "bull"}},
    )


# -- Test 1: non-bull regime -> 0 tradable -----------------------------------

class TestRegimeNonBullZeroTradable:
    """Verify bear/range regime forces all signals to exploratory."""

    def test_bear_regime_zero_tradable(self, monkeypatch):
        """Bear regime: all signals go exploratory (0 tradable)."""
        monkeypatch.setattr(
            "tools.gap_regime_stratified.compute_regime_labels",
            MagicMock(return_value={"2026-09-18": "bear"}),
        )
        monkeypatch.setattr(
            "candidate_funnel.evaluation.lift_for_arm",
            MagicMock(return_value=(0.5, "bear underpowered")),
        )
        from tools.signal_report import get_consecutive_relay_signals

        result = get_consecutive_relay_signals("2026-09-18")

        assert result["filters"]["tradable"] == 0
        assert result["filters"]["exploratory"] == 2
        assert result["filters"]["avoid"] == 0
        assert result["regime"]["current"] == "bear"

    def test_range_regime_zero_tradable(self, monkeypatch):
        """Range regime: all signals go exploratory (0 tradable)."""
        monkeypatch.setattr(
            "tools.gap_regime_stratified.compute_regime_labels",
            MagicMock(return_value={"2026-09-18": "range"}),
        )
        monkeypatch.setattr(
            "candidate_funnel.evaluation.lift_for_arm",
            MagicMock(return_value=(0.5, "range underpowered")),
        )
        from tools.signal_report import get_consecutive_relay_signals

        result = get_consecutive_relay_signals("2026-09-18")

        assert result["filters"]["tradable"] == 0
        assert result["filters"]["exploratory"] == 2
        assert result["filters"]["avoid"] == 0
        assert result["regime"]["current"] == "range"

    def test_bull_regime_has_tradable(self, monkeypatch):
        """Bull regime: signals can be tradable (baseline check)."""
        from tools.signal_report import get_consecutive_relay_signals

        result = get_consecutive_relay_signals("2026-09-18")

        # Should have tradable since bull + not unbuyable + no hard-stop
        assert result["filters"]["tradable"] == 2
        assert result["filters"]["exploratory"] == 0
        assert result["filters"]["avoid"] == 0


# -- Test 2: sentiment retreat (storm) -> 0 tradable ------------------------

class TestSentimentRetreatZeroTradable:
    """Verify sentiment storm forces 0 tradable even in bull regime."""

    def test_sentiment_storm_zero_tradable_in_bull(self, monkeypatch):
        """Storm sentiment in bull: 0 tradable, all exploratory."""
        def mock_compute_weather_snapshot(date):
            return {
                "date": date,
                "weather_state": "暴风雨",
                "composite_score": 15.0,
                "data_status": "ok",
            }

        monkeypatch.setattr(
            "routers.sentiment_weather.compute_weather_snapshot",
            mock_compute_weather_snapshot,
        )
        from tools.signal_report import get_consecutive_relay_signals

        result = get_consecutive_relay_signals("2026-09-18")

        # Even in bull, sentiment storm -> 0 tradable
        assert result["filters"]["tradable"] == 0
        assert result["filters"]["exploratory"] == 2
        assert result["filters"]["avoid"] == 0
        # hardstop reason should mention sentiment
        assert result["hardstop"]["active"] is True
        assert "sentiment_hardstop" in (result["hardstop"]["reason"] or "")
        # Every signal should have the hardstop_reason
        for sig in result["signals"]:
            assert sig["bucket"] == "exploratory"
            assert "sentiment_hardstop" in (sig.get("hardstop_reason") or "")

    def test_sentiment_sunny_has_tradable(self, monkeypatch):
        """Sunny sentiment: normal operation, tradable in bull."""
        def mock_compute_weather_snapshot(date):
            return {
                "date": date,
                "weather_state": "晴天",
                "composite_score": 78.0,
                "data_status": "ok",
            }

        monkeypatch.setattr(
            "routers.sentiment_weather.compute_weather_snapshot",
            mock_compute_weather_snapshot,
        )
        from tools.signal_report import get_consecutive_relay_signals

        result = get_consecutive_relay_signals("2026-09-18")

        # Sunny + bull -> tradable
        assert result["filters"]["tradable"] == 2
        assert result["filters"]["exploratory"] == 0
        assert result["hardstop"]["active"] is False


# -- Test 3: regime cache stale -> 0 tradable -----------------------------

class TestRegimeCacheStaleZeroTradable:
    """Verify stale regime cache forces 0 tradable."""

    def test_regime_cache_stale_zero_tradable(self, monkeypatch, tmp_path):
        """Stale cache (>T-1): 0 tradable, all exploratory."""
        # Create a stale cache (3 days old)
        stale_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        cache_data = {stale_date: {"close": 3500.0, "ma20": 3520.0}}

        # Patch _load_regime_cache to return stale data
        monkeypatch.setattr(
            "tools.signal_report._load_regime_cache",
            lambda: cache_data,
        )
        from tools.signal_report import get_consecutive_relay_signals

        result = get_consecutive_relay_signals("2026-09-18")

        # Stale cache -> 0 tradable
        assert result["filters"]["tradable"] == 0
        assert result["filters"]["exploratory"] == 2
        assert result["filters"]["avoid"] == 0
        # hardstop reason should mention stale
        assert result["hardstop"]["active"] is True
        assert "regime_cache_stale" in (result["hardstop"]["reason"] or "")

    def test_regime_cache_fresh_has_tradable(self, monkeypatch):
        """Fresh cache: normal operation."""
        # Fresh cache (today)
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {today: {"close": 3500.0, "ma20": 3520.0}}

        monkeypatch.setattr(
            "tools.signal_report._load_regime_cache",
            lambda: cache_data,
        )
        from tools.signal_report import get_consecutive_relay_signals

        result = get_consecutive_relay_signals("2026-09-18")

        # Fresh cache + bull -> tradable
        assert result["filters"]["tradable"] == 2
        assert result["filters"]["exploratory"] == 0
        assert result["hardstop"]["active"] is False


# -- Test 4: sentiment hard-stop reuses compute_weather_snapshot -----------

class TestSentimentHardstopReusesSentimentWeather:
    """Verify sentiment hard-stop reuses existing compute_weather_snapshot."""

    def test_no_recomputation_reuses_compute_weather_snapshot(self, monkeypatch):
        """Sentiment hard-stop calls compute_weather_snapshot directly."""
        call_log = []

        def mock_compute_weather_snapshot(date):
            call_log.append(date)
            return {
                "date": date,
                "weather_state": "暴风雨",
                "composite_score": 15.0,
                "data_status": "ok",
            }

        monkeypatch.setattr(
            "routers.sentiment_weather.compute_weather_snapshot",
            mock_compute_weather_snapshot,
        )
        from tools.signal_report import get_consecutive_relay_signals

        get_consecutive_relay_signals("2026-09-18")

        # Should call compute_weather_snapshot once with target_date
        assert len(call_log) == 1
        assert call_log[0] == "2026-09-18"

    def test_sentiment_exception_does_not_crash(self, monkeypatch):
        """Sentiment service exception: degraded but not crashed."""
        def mock_compute_weather_snapshot(date):
            raise RuntimeError("DB connection lost")

        monkeypatch.setattr(
            "routers.sentiment_weather.compute_weather_snapshot",
            mock_compute_weather_snapshot,
        )
        from tools.signal_report import get_consecutive_relay_signals

        # Should not raise, falls back to normal operation
        result = get_consecutive_relay_signals("2026-09-18")

        # Still works, just no sentiment hard-stop
        assert result["filters"]["tradable"] == 2
        assert result["hardstop"]["active"] is False


# -- Test 5: combined gates ------------------------------------------------

class TestCombinedGates:
    """Multiple gates: any trigger -> hard-stop."""

    def test_sentiment_and_stale_cache_combined(self, monkeypatch):
        """Both sentiment storm + stale cache: hard-stop with sentiment reason."""
        def mock_compute_weather_snapshot(date):
            return {
                "date": date,
                "weather_state": "暴风雨",
                "composite_score": 15.0,
                "data_status": "ok",
            }

        monkeypatch.setattr(
            "routers.sentiment_weather.compute_weather_snapshot",
            mock_compute_weather_snapshot,
        )
        # Stale cache
        stale_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        cache_data = {stale_date: {"close": 3500.0, "ma20": 3520.0}}
        monkeypatch.setattr(
            "tools.signal_report._load_regime_cache",
            lambda: cache_data,
        )
        from tools.signal_report import get_consecutive_relay_signals

        result = get_consecutive_relay_signals("2026-09-18")

        # Both triggers, but sentiment takes priority (first in elif chain)
        assert result["filters"]["tradable"] == 0
        assert result["filters"]["exploratory"] == 2
        assert result["hardstop"]["active"] is True
        assert "sentiment_hardstop" in (result["hardstop"]["reason"] or "")
