# -*- coding: utf-8 -*-
"""S017 P1-c 数据交叉验证误差门控（库版本）。

落地 financial-data skill 的交叉验证契约：每个关键财务数据须多源对照，
误差≤1% 取主源、1-5% 标记差异、>5% 重大差异须查原始财报。纯函数、无网络、可复算。

与 ``tools/financial_rigor.py`` 的关系：financial_rigor 是 **CLI 验算工具**
（Decimal 精确十进制，供人工复算 / report_audit 准出），本模块是**数据层库**
（float，供 data pipeline 在取数时自动门控）。两者阈值一致（1%/5%），口径同源：
误差率 = |主源 − 副源| / |主源| × 100%，主源为零则不除零（返 None，不臆造）。

合规：只判定客观数值差异、给采用值，不输出"哪个源对"的主观结论；>5% 不采用
任一值（adopted=None），强制回原始财报核实——不臆造、不静默吞差异。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Verdict(Enum):
    """交叉验证结论档位（误差门控）。"""

    CONSISTENT = "consistent"              # ≤1%：多源一致，取主源
    DIFFERENCE = "difference"              # 1-5%：存在差异，取主源但标记
    MAJOR_DIFFERENCE = "major_difference"  # >5%：重大差异，不采用，须查原始财报
    SINGLE_SOURCE = "single_source"        # 仅一个有效源，采用该源
    UNKNOWN = "unknown"                    # 全部缺失，无法判定


# 误差门控阈值（百分数），与 financial-data skill + tools/financial_rigor.py 一致
CONSISTENT_THRESHOLD_PCT = 1.0   # ≤1% → 一致
DIFFERENCE_THRESHOLD_PCT = 5.0   # 1-5% → 差异；>5% → 重大差异


@dataclass(frozen=True)
class ValidationResult:
    """单字段交叉验证结果。"""

    field: str                              # 字段名（如 revenue/roe）
    verdict: Verdict
    adopted_value: float | None = None      # 采用值（MAJOR_DIFFERENCE/UNKNOWN 时 None）
    adopted_source: str | None = None       # 主源名（首个有效源）
    max_deviation_pct: float | None = None  # 主源 vs 最大偏差源的误差百分数
    sources: dict[str, float | None] | None = None  # 原始各源值（可观测）


def error_rate_pct(primary: float, secondary: float | None) -> float | None:
    """主源 vs 副源误差百分数 = |primary − secondary| / |primary| × 100。

    主源为 0（分母为零）→ 返 None（不除零、不臆造）。副源 None → None。
    与 ``tools.financial_rigor.pct_deviation`` 同口径（此处 float，库内集成用）。
    """
    if primary is None or primary == 0 or secondary is None:
        return None
    return abs(primary - secondary) / abs(primary) * 100.0


def _first_valid(values: dict[str, float | None]) -> tuple[str, float] | None:
    """首个有效（非 None）源 —— 主源。dict 保持插入序，调用方控制优先级。"""
    for src, v in values.items():
        if v is not None:
            return src, float(v)
    return None


def _max_deviation(primary: float, values: dict[str, float | None]) -> float | None:
    """主源 vs 其余各源的最大误差百分数。仅一个有效源 → None。"""
    dev: float | None = None
    for v in values.values():
        if v is None:
            continue
        d = error_rate_pct(primary, v)
        if d is not None and (dev is None or d > dev):
            dev = d
    return dev


def cross_validate(field: str, values: dict[str, float | None]) -> ValidationResult:
    """多源交叉验证单字段，按误差门控定档。

    ``values`` 为 {源名: 值或 None}，**插入序即优先级**（首个有效源 = 主源）。
    返回 :class:`ValidationResult`。

    规则（financial-data skill）：
      - ≤1% → CONSISTENT，取主源
      - 1-5% → DIFFERENCE，取主源但标记
      - >5% → MAJOR_DIFFERENCE，adopted=None（不采用，须查原始财报）
      - 仅一个有效源 → SINGLE_SOURCE，取该源
      - 全 None → UNKNOWN
    """
    primary = _first_valid(values)
    if primary is None:
        return ValidationResult(field=field, verdict=Verdict.UNKNOWN, sources=dict(values))

    src_name, val = primary
    n_valid = sum(1 for v in values.values() if v is not None)
    if n_valid == 1:
        return ValidationResult(
            field=field, verdict=Verdict.SINGLE_SOURCE,
            adopted_value=val, adopted_source=src_name,
            sources=dict(values),
        )

    dev = _max_deviation(val, values)
    # dev is None 仅当除主源外全 None——已被 n_valid==1 分支拦截；此处 dev 必非 None
    dev_f = dev if dev is not None else 0.0
    if dev_f <= CONSISTENT_THRESHOLD_PCT:
        verdict = Verdict.CONSISTENT
    elif dev_f <= DIFFERENCE_THRESHOLD_PCT:
        verdict = Verdict.DIFFERENCE
    else:
        verdict = Verdict.MAJOR_DIFFERENCE

    adopted = None if verdict is Verdict.MAJOR_DIFFERENCE else val
    return ValidationResult(
        field=field, verdict=verdict,
        adopted_value=adopted, adopted_source=src_name,
        max_deviation_pct=dev_f, sources=dict(values),
    )
