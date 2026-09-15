# -*- coding: utf-8 -*-
"""S204 T13: sensitivity_sweep test（TDD）。

验证 overfit 检测（edge 仅单 v → overfit / 多邻近 → 稳健 / 无 → 无 edge）+ K 冻结。
"""
from __future__ import annotations

import pytest

from tools.sensitivity_sweep import (
    FrozenK,
    SweepReport,
    SweepResult,
    sweep_k_count,
    sweep_param,
)


def _verdict_fn_factory(per_value_verdicts: dict[float, tuple[str, float, int]]):
    """构造 verdict_fn：value -> (status, lift, n)。"""
    def fn(v: float):
        return per_value_verdicts.get(v, ("exploratory", 1.0, 100))
    return fn


def test_overfit_single_value_edge():
    """edge（robust_edge）仅 v=0.007，邻近无 → overfit_flag=True, robust=False。"""
    verdicts = {
        0.003: ("exploratory", 1.2, 100),
        0.005: ("exploratory", 1.5, 100),
        0.007: ("robust_edge", 2.5, 100),  # 仅此有 edge
        0.010: ("exploratory", 1.1, 100),
    }
    report = sweep_param("龙头首板", "seal_to_float_ratio", [0.003, 0.005, 0.007, 0.010], _verdict_fn_factory(verdicts))
    assert report.overfit_flag is True  # 仅单 v edge → overfit
    assert report.robust_flag is False
    assert report.no_edge_flag is False
    assert len(report.results) == 4


def test_robust_multi_value_edge():
    """edge 在 v=0.005 + 0.007 都成立 → robust_flag=True, overfit=False。"""
    verdicts = {
        0.003: ("exploratory", 1.2, 100),
        0.005: ("robust_edge", 2.3, 100),
        0.007: ("robust_edge", 2.5, 100),  # 多邻近 edge
        0.010: ("exploratory", 1.1, 100),
    }
    report = sweep_param("龙头首板", "seal_to_float_ratio", [0.003, 0.005, 0.007, 0.010], _verdict_fn_factory(verdicts))
    assert report.robust_flag is True
    assert report.overfit_flag is False


def test_no_edge_any_value():
    """所有 v 无 robust_edge → no_edge_flag=True（不进融合）。"""
    verdicts = {v: ("exploratory", 1.0 + 0.1 * i, 100) for i, v in enumerate([0.003, 0.005, 0.007, 0.010])}
    report = sweep_param("龙头首板", "seal_to_float_ratio", [0.003, 0.005, 0.007, 0.010], _verdict_fn_factory(verdicts))
    assert report.no_edge_flag is True
    assert report.overfit_flag is False
    assert report.robust_flag is False


def test_sweep_result_immutable():
    """SweepResult frozen dataclass。"""
    r = SweepResult("seal_to_float_ratio", 0.005, "robust_edge", 2.3, 100)
    with pytest.raises(Exception):
        r.value = 0.007  # frozen


def test_sweep_report_immutable():
    """SweepReport frozen dataclass。"""
    report = sweep_param("龙头", "p", [1.0], _verdict_fn_factory({1.0: ("exploratory", 1.0, 100)}))
    with pytest.raises(Exception):
        report.overfit_flag = True  # frozen


def test_sweep_k_count():
    """sweep 总次数 = Σ(len(results))。"""
    r1 = sweep_param("龙头", "p1", [1.0, 2.0, 3.0], _verdict_fn_factory({1.0: ("exploratory", 1, 100), 2.0: ("exploratory", 1, 100), 3.0: ("exploratory", 1, 100)}))
    r2 = sweep_param("龙头", "p2", [1.0, 2.0], _verdict_fn_factory({1.0: ("exploratory", 1, 100), 2.0: ("exploratory", 1, 100)}))
    assert sweep_k_count([r1, r2]) == 5  # 3 + 2


def test_frozen_k_immutable():
    """FrozenK frozen dataclass。"""
    fk = FrozenK(k=12, frozen_at="2026-09-15", sweep_count=12)
    assert fk.k == 12
    with pytest.raises(Exception):
        fk.k = 15  # frozen


def test_sweep_empty_values():
    """空 values → 空 results, no flags。"""
    report = sweep_param("龙头", "p", [], _verdict_fn_factory({}))
    assert report.results == ()
    assert report.overfit_flag is False
    assert report.robust_flag is False
    assert report.no_edge_flag is True  # 0 edges → no_edge
