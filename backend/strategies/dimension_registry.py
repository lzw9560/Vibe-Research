# -*- coding: utf-8 -*-
"""S203 T1: Dragon Score 维度 registry（声明式，per-战法 config）。

per-战法参数差异 declared 非 ad-hoc（加新战法=加 config entry，不改 framework）。
关联设计：specs/_shared/dragon-score-dimension-registry.md。

5 共享维度（龙头打板专用，研究 workflow wc4q5d73o 证覆盖率仅 50-60%，
S205 5 战法须 per-战法维度集，本 registry 结构已支持——加维度加 config 不改 framework）。
DRY：与 strategies/funnel/scoring.py 14 维评分系统不同抽象层（scoring=候选筛选层
按市场档位分层；Dragon Score=战法级 ranking flat 先验权重标 overfit），共享数据源
（seal_to_float_ratio/zt_count_today）不共享逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Dimension:
    """维度定义（不可变）。"""

    name: str
    data_source: str  # module:function 或 table:column（已核实存在）
    normalization: str  # 归一化到 [0,1] 的方法
    sweep_range: tuple[float, ...]  # sensitivity sweep 值（S204 R13 sweep harness 用）
    overfit_risk: str  # high/medium/low
    applicable_战法: tuple[str, ...]  # 哪些战法用此维度（None=ALL）
    notes: str = ""


@dataclass(frozen=True)
class 战法ScoreConfig:
    """战法配置（不可变）。权重先验固定（非回测拟合，调权重=过拟合）。"""

    战法: str
    dimensions: tuple[str, ...]  # 用哪些维度（从 DIMENSION_REGISTRY 选）
    weights: dict[str, float]  # dim→权重，sum=1.0
    edge_type: str  # 标"待验"（决策#7 verifier-side，window sanity 后定不预设）
    sweep_params: dict[str, list[float]]  # param→range（sensitivity sweep）
    cost_model: str = "vibe_0.15"  # Vibe _cost_pct 0.15 round-trip（统一）


DIMENSION_REGISTRY: dict[str, Dimension] = {
    "板块强度": Dimension(
        name="板块强度",
        data_source="sector_cycle.py:165 zt_count_today + sector_divergence.py:130 calculate_sector_divergence",
        normalization="zt_count_today/全市场涨停均值封顶1.0",
        sweep_range=(2.0, 3.0, 5.0, 10.0),
        overfit_risk="medium",
        applicable_战法=("龙头首板", "接力", "一字竞价", "弱转强", "N字(部分)"),
        notes="板块共振是首板入场必要条件（用户放弃无板块效应秒板）",
    ),
    "封单强度": Dimension(
        name="封单强度",
        data_source="limitup_screener/models.py:50 seal_to_float_ratio + intraday_features.py seal_slope",
        normalization="seal_to_float_ratio/0.005 封顶1.0 + seal_slope 正则加分",
        sweep_range=(0.003, 0.005, 0.007, 0.010),
        overfit_risk="high",
        applicable_战法=("龙头首板", "接力", "一字竞价(改竞价口径)"),
        notes="非打板策略不适用（低吸/N字/形态反包须替换为回调支撑强度）",
    ),
    "量能确认": Dimension(
        name="量能确认",
        data_source="pattern_scan.py:49 volume_breakout_ratio + relay_vol_ratio(新增) + 换手率(涨停池 raw)",
        normalization="relay_vol_ratio/2.0 封顶1.0 + 换手率合理性扣分",
        sweep_range=(1.0, 1.5, 2.0, 2.5, 3.0),
        overfit_risk="high",
        applicable_战法=("龙头首板", "接力", "N字", "形态反包"),
        notes="一字竞价不适用（缩量是强信号非放量确认，逻辑冲突）",
    ),
    "情绪周期": Dimension(
        name="情绪周期",
        data_source="limitup_sti/models.py:63 STI score(5-phase+8维) + market.py:166 连板梯队",
        normalization="STI score/100",
        sweep_range=(),  # regime conditioner 非 sweep（须先验 STI phase 有 population edge）
        overfit_risk="extreme",
        applicable_战法=("ALL",),
        notes="退潮/高潮实测零天数据，MVP 用连续 score 不硬分三态标探索性",
    ),
    "技术形态": Dimension(
        name="技术形态",
        data_source="MA5/MA10(baostock) + K线形态吞没/上影(OHLCV) + pattern_scan shadow_length_pct + ma5_slope",
        normalization="MA 排列+形态命中数/3",
        sweep_range=(2.0, 3.0, 4.0, 5.0),  # 实体涨幅 X% + N日高点 lookback
        overfit_risk="medium",
        applicable_战法=("ALL",),
        notes="形态反包升至 25% 权重",
    ),
}

# S203 龙头 3 sub config（权重先验固定，标 overfit；sweep 后不调权重）
STRATEGY_CONFIGS: dict[str, 战法ScoreConfig] = {
    "龙头首板": 战法ScoreConfig(
        战法="龙头首板",
        dimensions=("板块强度", "封单强度", "量能确认", "情绪周期", "技术形态"),
        weights={"板块强度": 0.25, "封单强度": 0.25, "量能确认": 0.20, "情绪周期": 0.15, "技术形态": 0.15},
        edge_type="selection(待验)",  # window sanity 后定
        sweep_params={
            "seal_to_float_ratio": [0.003, 0.005, 0.007, 0.010],
            "relay_vol_ratio": [1.0, 1.5, 2.0, 2.5, 3.0],
            "sector_top_n": [1.0, 3.0, 5.0, 10.0],
        },
    ),
    "接力": 战法ScoreConfig(
        战法="接力",
        dimensions=("板块强度", "封单强度", "量能确认", "情绪周期", "技术形态"),
        weights={"板块强度": 0.25, "封单强度": 0.25, "量能确认": 0.20, "情绪周期": 0.15, "技术形态": 0.15},
        edge_type="selection(待验)",
        sweep_params={
            "seal_to_float_ratio": [0.003, 0.005, 0.007, 0.010],
            "relay_vol_ratio": [1.0, 1.5, 2.0, 2.5, 3.0],
            "lbc": [2.0, 3.0, 4.0],  # 当下连板数门槛（区别 zt_count_250d 历史频次）
        },
    ),
    "反包": 战法ScoreConfig(
        战法="反包",
        dimensions=("板块强度", "量能确认", "情绪周期", "技术形态"),  # 封单→技术形态（反包不靠封单靠吞没+均线）
        weights={"板块强度": 0.15, "量能确认": 0.20, "情绪周期": 0.15, "技术形态": 0.25, "反包确认强度": 0.25},
        edge_type="event(待验)",  # leader_drop_reversal 须 R11 drift 修正
        sweep_params={
            "leader_drop_pct": [0.05, 0.07, 0.10],
            "volume_breakout_ratio": [1.0, 1.2, 1.5, 2.0],
        },
    ),
}
