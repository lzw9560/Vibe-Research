# -*- coding: utf-8 -*-
"""S222 — regime-flip tripwire + hysteresis 测试。

验证：
- 3 天连续 bull → alert
- 单日 bull 后翻 range → skip
- range/bear → skip
- 数据不够（<3 天）→ skip
- compute_regime_labels 失败 → skip
"""
import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from scheduler.executors.signals import regime_flip_notify  # noqa: E402


@pytest.fixture
def patch_regime_map(monkeypatch):
    """注入 regime_map（{date: regime}）给 compute_regime_labels。"""
    def _patch(regime_map):
        def _fake_compute_regime_labels():
            return regime_map
        monkeypatch.setattr(
            "tools.gap_regime_stratified.compute_regime_labels",
            _fake_compute_regime_labels,
        )
        # signals.py 里 local import，patch 模块级
        import tools.gap_regime_stratified as grs
        monkeypatch.setattr(grs, "compute_regime_labels", _fake_compute_regime_labels)
    return _patch


@pytest.fixture
def patch_signals(monkeypatch):
    """注入 get_consecutive_relay_signals 返回值（patch signals.py 模块引用，非 signal_report）。"""
    def _patch(tradable=0, cap=1.0):
        def _fake_get_signals(_date):
            return {
                "filters": {"tradable": tradable, "exploratory": 8, "avoid": 0},
                "cap": {"effective": cap},
                "signals": [],
            }
        import scheduler.executors.signals as sig
        monkeypatch.setattr(sig, "get_consecutive_relay_signals", _fake_get_signals)
    return _patch


class TestRegimeFlip:
    def test_3_days_consecutive_bull_alerts(self, patch_regime_map, patch_signals):
        patch_regime_map({"2026-09-16": "bull", "2026-09-17": "bull", "2026-09-18": "bull"})
        patch_signals(tradable=5, cap=1.0)
        result = regime_flip_notify({"run_date": "2026-09-18"})
        assert result["status"] == "alerted"
        assert result["regime"] == "bull"
        assert result["tradable"] == 5
        assert result["cap"] == 1.0

    def test_single_bull_then_range_skips(self, patch_regime_map, patch_signals):
        patch_regime_map({"2026-09-16": "range", "2026-09-17": "bull", "2026-09-18": "range"})
        patch_signals()
        result = regime_flip_notify({"run_date": "2026-09-18"})
        assert result["status"] == "skip"
        assert "not_bull_or_unstable" in result["reason"]

    def test_range_skips(self, patch_regime_map, patch_signals):
        patch_regime_map({"2026-09-16": "range", "2026-09-17": "range", "2026-09-18": "range"})
        patch_signals()
        result = regime_flip_notify({"run_date": "2026-09-18"})
        assert result["status"] == "skip"

    def test_bear_skips(self, patch_regime_map, patch_signals):
        patch_regime_map({"2026-09-16": "bear", "2026-09-17": "bear", "2026-09-18": "bear"})
        patch_signals()
        result = regime_flip_notify({"run_date": "2026-09-18"})
        assert result["status"] == "skip"

    def test_insufficient_history_skips(self, patch_regime_map, patch_signals):
        patch_regime_map({"2026-09-17": "bull", "2026-09-18": "bull"})
        patch_signals()
        result = regime_flip_notify({"run_date": "2026-09-18"})
        assert result["status"] == "skip"
        assert result["reason"] == "insufficient_history"

    def test_regime_map_empty_skips(self, patch_regime_map, patch_signals):
        patch_regime_map({})
        patch_signals()
        result = regime_flip_notify({"run_date": "2026-09-18"})
        assert result["status"] == "skip"

    def test_compute_regime_labels_failure_skips(self, monkeypatch, patch_signals):
        def _raise():
            raise RuntimeError("compute failed")
        import tools.gap_regime_stratified as grs
        monkeypatch.setattr(grs, "compute_regime_labels", _raise)
        patch_signals()
        result = regime_flip_notify({"run_date": "2026-09-18"})
        assert result["status"] == "skip"
        assert result["reason"] == "regime_map_unavailable"

    def test_mixed_regimes_skips(self, patch_regime_map, patch_signals):
        """bull-bear-bull 不算稳定，skip。"""
        patch_regime_map({"2026-09-16": "bull", "2026-09-17": "bear", "2026-09-18": "bull"})
        patch_signals()
        result = regime_flip_notify({"run_date": "2026-09-18"})
        assert result["status"] == "skip"
