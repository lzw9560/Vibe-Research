# -*- coding: utf-8 -*-
"""S204 R11 T5b: event_drift test（TDD）。

验证 event edge drift 修正：两样本（event vs universe）减市场 drift，
牛市假阳性（event_mean>0 但 drift_adjusted≤0）被识别。
"""
from __future__ import annotations

import numpy as np
import pytest

from s44_verifier.event_drift import EventDriftResult, adjust_event_drift


def test_event_drift_two_sample():
    """event edge 算 universe + 两样本（event_mean vs universe_mean），非单样本 mean>0。"""
    event = [0.01, 0.02, 0.015]  # event_mean ≈ 0.015
    universe = {
        "2026-01-01": [0.005, 0.004, 0.006],
        "2026-01-02": [0.005, 0.005, 0.005],
    }  # univ_mean ≈ 0.005
    r = adjust_event_drift(event, universe)
    assert abs(r.event_mean - 0.015) < 0.001
    assert abs(r.universe_mean - 0.005) < 0.001
    assert abs(r.drift_adjusted_mean - 0.01) < 0.001  # 0.015 - 0.005
    assert r.is_drift_inflated is False  # drift_adjusted>0, real edge


def test_drift_inflated_bull_market():
    """牛市 event_mean>0 但 drift_adjusted≤0 → is_drift_inflated=True（假阳性）。"""
    event = [0.005, 0.006, 0.004]  # event_mean ≈ 0.005
    universe = {"2026-01-01": [0.008, 0.007, 0.009]}  # univ_mean ≈ 0.008 > event
    r = adjust_event_drift(event, universe)
    assert r.event_mean > 0
    assert r.drift_adjusted_mean <= 0  # 0.005 - 0.008 < 0
    assert r.is_drift_inflated is True  # drift 假阳性


def test_no_drift_bear_market():
    """熊市 drift_adjusted>0 → 真 event edge（event 比市场强）。"""
    event = [0.005, 0.004, 0.006]
    universe = {"2026-01-01": [-0.002, -0.003, -0.001]}  # univ negative
    r = adjust_event_drift(event, universe)
    assert r.drift_adjusted_mean > 0  # event positive, univ negative
    assert r.is_drift_inflated is False


def test_no_universe_returns_none():
    """无 universe_by_day → universe_mean=None, drift_adjusted=None（caller 回退单样本）。"""
    event = [0.01, 0.02]
    r = adjust_event_drift(event, None)
    assert r.universe_mean is None
    assert r.drift_adjusted_mean is None
    assert r.is_drift_inflated is False
    assert abs(r.event_mean - 0.015) < 0.001


def test_empty_universe_returns_none():
    """空 universe_by_day → 同 None（caller 回退单样本）。"""
    r = adjust_event_drift([0.01], {})
    assert r.universe_mean is None
    assert r.drift_adjusted_mean is None


def test_event_drift_immutable():
    """EventDriftResult frozen dataclass。"""
    r = adjust_event_drift([0.01], {"d": [0.005]})
    assert isinstance(r, EventDriftResult)
    with pytest.raises(Exception):
        r.event_mean = 0.0  # frozen, should raise FrozenInstanceError


def test_nan_returns_ignored():
    """event_returns 含 NaN 被忽略（不污染 mean）。"""
    event = [0.01, np.nan, 0.02, np.nan]  # 有效 [0.01, 0.02]
    universe = {"d": [0.005, 0.005]}
    r = adjust_event_drift(event, universe)
    assert abs(r.event_mean - 0.015) < 0.001  # (0.01+0.02)/2
