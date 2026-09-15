# -*- coding: utf-8 -*-
"""S204 R13 T13: sensitivity_sweep harness——社区参数 data-snooping 检测。

grep 'sweep|sensitivity' tools/*_lift.py 全空确认 harness 不存在——本模块新建。

overfit 检测（registry §5）：
- edge（robust_edge）仅单一 v 且邻近无 → overfit（data-snooped，block production）
- edge 在多个邻近 v 都成立 → 稳健（非 overfit）
- 无 v 出 edge → 无 selection edge（不进融合，§44v2 不外推）

K 冻结 pre-registration（§44v2 rule③）：sweep 总次数 = Σ(len(values) per param per 战法)
计入 Bonferroni K（split_into_subphases G2 T6 split，K>8 拆≤8）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

#: §44 robust_edge 判定（verifier verdict status）
_ROBUST_EDGE: str = "robust_edge"


@dataclass(frozen=True)
class SweepResult:
    """单参数值 sweep 结果（不可变）。"""

    param: str
    value: float
    verdict: str  # verifier status（robust_edge/underpowered/falsified/exploratory/not_validated）
    lift: float
    n: int


@dataclass(frozen=True)
class SweepReport:
    """参数 sweep 报告（不可变）。overfit/robust 标志。"""

    战法: str
    param: str
    results: tuple[SweepResult, ...]
    overfit_flag: bool  # True = edge 仅单一 v 邻近无（data-snooped）→ block production
    robust_flag: bool  # True = edge 多邻近 v 稳健
    no_edge_flag: bool  # True = 无 v 出 edge（不进融合）


def _edge_count(results: tuple[SweepResult, ...]) -> int:
    """edge（robust_edge verdict）计数。"""
    return sum(1 for r in results if r.verdict == _ROBUST_EDGE)


def sweep_param(
    战法: str,
    param: str,
    values: list[float],
    verdict_fn: Callable[[float], tuple[str, float, int]],
) -> SweepReport:
    """对单参数 sweep（每值跑 verify），检测 overfit。

    Args:
        战法: 战法名。
        param: 参数名（如 seal_to_float_ratio）。
        values: 参数值列表（如 [0.003, 0.005, 0.007, 0.010]）。
        verdict_fn: ``value -> (verdict_status, lift, n)`` callback（caller 跑 verify
            或 wire_verdict，返 verdict 三元组）。

    Returns:
        SweepReport（overfit_flag / robust_flag / no_edge_flag）。

    overfit：edge（robust_edge）仅 1 个 v，邻近无 edge → data-snooped block。
    robust：edge ≥2 个 v（多邻近）→ 稳健。
    no_edge：0 个 v 出 edge → 无 selection edge 不进融合。
    """
    results = tuple(
        SweepResult(param=param, value=v, verdict=verdict_fn(v)[0],
                    lift=verdict_fn(v)[1], n=verdict_fn(v)[2])
        for v in values
    )
    edge_count = _edge_count(results)
    overfit = edge_count == 1  # 仅单一 v 有 edge（邻近无）
    robust = edge_count >= 2  # 多邻近 v 有 edge
    no_edge = edge_count == 0  # 无 v 出 edge
    return SweepReport(
        战法=战法, param=param, results=results,
        overfit_flag=overfit, robust_flag=robust, no_edge_flag=no_edge,
    )


def sweep_k_count(sweep_reports: list[SweepReport]) -> int:
    """sweep 总次数 = Σ(len(results) per report)——计入 Bonferroni K（§44v2 rule③）。

    K>8 → split_into_subphases（G2 T6）拆≤8 子 phase。
    """
    return sum(len(r.results) for r in sweep_reports)


@dataclass(frozen=True)
class FrozenK:
    """K 冻结 pre-registration（§44v2 rule③，防后调 cherry-pick K）。

    首次入库冻结 K，后续 K 变 → rejected（防调 K 让结果好看）。
    """

    k: int
    frozen_at: str
    sweep_count: int  # sweep 总次数
