# -*- coding: utf-8 -*-
"""Alt feature specs — S020 worldmonitor 派生特征（另类/地缘/商品维度）。

7 特征来自 worldmonitor（CII 31 国不稳定指数、热点升级、干散货航运压力、关税压力、
商品油/铜、DXY 交叉验证）。**不替代** S019 Fred 对美债/DXY 的主源地位——wm_dxy 仅
cross-check Fred dxy，不作主源。

合成分（CII/热点/航运/关税）标 ``compliance_flag="aggregate_only"``（worldmonitor 合成，
作输入之一不作唯一依据）；公开 feed（商品油/铜/DXY）标 ``"ok"``。

按 S020 R10 纪律：**live 冒烟通过前不加入** ``HEAD_FEATURE_SUBSETS``。``availability_offset``
占位 1（s2），待 live 冒烟后定（先注册存在性，不影响模型栈）。
"""
from __future__ import annotations

from predict.features.registry import FeatureSpec, Registry

# ── Module-level immutable spec declarations ────────────────────────

ALT_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="wm_cii_global",
        source="worldmonitor",
        category="alt",
        availability_offset=1,
        stage="s2",
        compliance_flag="aggregate_only",
        description="worldmonitor CII 31 国不稳定指数（合成分），cross-check 全球风险情绪",
    ),
    FeatureSpec(
        name="wm_hotspot_escalation",
        source="worldmonitor",
        category="alt",
        availability_offset=1,
        stage="s2",
        compliance_flag="aggregate_only",
        description="worldmonitor 热点升级信号（合成分），地缘风险外生因子",
    ),
    FeatureSpec(
        name="wm_dry_bulk_stress",
        source="worldmonitor",
        category="alt",
        availability_offset=1,
        stage="s2",
        compliance_flag="aggregate_only",
        description="worldmonitor 干散货航运压力（BDI + 港口拥堵合成分），全球贸易活力代理",
    ),
    FeatureSpec(
        name="wm_tariff_stress",
        source="worldmonitor",
        category="alt",
        availability_offset=1,
        stage="s2",
        compliance_flag="aggregate_only",
        description="worldmonitor 关税趋势压力（合成分），贸易政策外生因子",
    ),
    FeatureSpec(
        name="wm_commodity_oil",
        source="worldmonitor",
        category="alt",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="worldmonitor 原油价格（公开 feed），通胀/成本端外生因子",
    ),
    FeatureSpec(
        name="wm_commodity_copper",
        source="worldmonitor",
        category="alt",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="worldmonitor 铜价（公开 feed），全球工业需求代理",
    ),
    FeatureSpec(
        name="wm_dxy",
        source="worldmonitor",
        category="alt",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="worldmonitor 美元指数（公开 feed），cross-check Fred dxy（S019 主源），非主源",
    ),
)


# ── Registration ────────────────────────────────────────────────────


def register_alt(registry: Registry) -> None:
    """Register alt FeatureSpecs into the given Registry.

    Per S020 R10: these features are NOT added to any HEAD_FEATURE_SUBSET
    until live smoke passes (``availability_offset`` 待 live 后定）。
    """
    for spec in ALT_SPECS:
        registry.register(spec)
