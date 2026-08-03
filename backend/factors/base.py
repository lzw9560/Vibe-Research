# -*- coding: utf-8 -*-
"""选股因子接口（S023）。

选股因子与工作流解耦：两套选股标准（旧 limitup_screener + 新 candidate_funnel）
作为可插拔组件并存，工作流/盘前简报调因子注册表，不绑死某一标准。

合规：因子只输出客观候选 + 命中规则依据，不输出买卖方向/参考价位（参考价位属研究模式 spec）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# 复用 P1 漏斗的 FunnelLayer（旧因子单层包装，漏斗原生多层）
from candidate_funnel.models import FunnelLayer


@dataclass
class Candidate:
    """因子产出的候选标的（带来源与依据链）。"""

    code: str
    name: str
    source_factor_id: str  # 来自哪个因子
    source_layer: str  # 来自哪层（漏斗层 id 或旧因子单层标签）
    hit_rules: list[str] = field(default_factory=list)  # 命中规则（可复现依据）
    detail: dict[str, Any] = field(default_factory=dict)  # 因子特有（战法/仓位/指标取值）


@dataclass
class FactorResult:
    """因子产出结果。"""

    factor_id: str
    factor_name: str
    candidates: list[Candidate]
    layers: list[FunnelLayer]  # 旧因子单层包装；漏斗原生多层
    config: dict[str, Any] = field(default_factory=dict)  # 阈值/参数 + data_status + reason
    as_of: str = ""  # 取数时点（ISO）
    data_date: str = ""  # 数据日期（非交易时段=上一交易日）

    @property
    def data_status(self) -> str:
        """数据状态：ok / 未取得。取不到时 config['data_status'] 标记。"""
        return self.config.get("data_status", "ok")


class SelectionFactor(Protocol):
    """选股因子接口：可插拔组件，工作流按 id 调用。"""

    factor_id: str

    def fetch(self, date: str, config: dict[str, Any] | None = None) -> FactorResult:
        """采集候选。date 为目标交易日；非交易时段由实现内部转上一交易日。"""
        ...

    def describe(self) -> dict[str, Any]:
        """因子说明：怎么选的、用哪些维度（供前端展示）。"""
        ...
