# -*- coding: utf-8 -*-
"""S205 T1: 5 战法 per-战法维度集（7 新维度 + 5 战法 config）。

扩展 S203 DIMENSION_REGISTRY（加 7 新维度 + 5 共享英文 alias）+ STRATEGY_CONFIGS（5 战法）。
dragon_score composite 调 DIMENSION_REGISTRY[dim_name]——英文 key 匹配。

5 战法：一字竞价/弱转强/N字反击/低吸龙头/形态反包（spec §5.1 grill 修正后）。
7 新维度：auction_signal/expectation_gap_reversal/volume_rhythm/pullback_structure/
leader_identity/pullback_rhythm/reversal_confirm（data_source 声明现有或可复算，不臆造）。

auction_signal BLOCKER：A 股竞价历史数据无免费源（Tushare/hithink 付费；
akshare/腾讯/新浪 实时竞价无历史）→ compute_auction_signal 标 BLOCKER skipif。
"""
from __future__ import annotations

from strategies.dimension_registry import (  # noqa: F401
    DIMENSION_REGISTRY,
    STRATEGY_CONFIGS,
    Dimension,
    战法ScoreConfig,
)

# 7 新维度（英文 key，per-战法特有）
_S205_NEW_DIMS: dict[str, Dimension] = {
    "auction_signal": Dimension(
        name="auction_signal",
        data_source="BLOCKER: Tushare stk_auction/hithink 付费；akshare/腾讯/新浪 无历史竞价——compute skipif",
        normalization="竞价量比/竞价额/订单失衡 0-1（BLOCKER 无源→0.0）",
        sweep_range=(2.0, 3.0, 5.0, 7.0),
        overfit_risk="high",
        applicable_战法=("一字竞价",),
        notes="BLOCKER: A 股竞价历史数据无免费源。compute_auction_signal skipif 返 0.0",
    ),
    "expectation_gap_reversal": Dimension(
        name="expectation_gap_reversal",
        data_source="pattern_scan_s205.py:compute_expectation_gap_reversal（T-1 close + T open 差代理；无竞价量用开盘量比）",
        normalization="竞价高开% + 开盘量比 0-1",
        sweep_range=(1.0, 1.5, 2.0, 2.5, 3.0),
        overfit_risk="medium",
        applicable_战法=("弱转强",),
        notes="预期差反包：T-1 close + T open 差代理（无竞价量免费源用开盘量比）",
    ),
    "volume_rhythm": Dimension(
        name="volume_rhythm",
        data_source="pattern_scan_s205.py:compute_volume_rhythm（首板倍量→缩量→再放量三段，baostock volume）",
        normalization="三段量比连续性评分 0-1",
        sweep_range=(1.0, 1.5, 2.0, 2.5),
        overfit_risk="medium",
        applicable_战法=("N字反击",),
        notes="量能节奏：首板倍量→缩量→再放量三段连续性",
    ),
    "pullback_structure": Dimension(
        name="pullback_structure",
        data_source="pattern_scan_s205.py:compute_pullback（回调深度比/天数/不破首板起涨点，baostock OHLCV）",
        normalization="回调深度合理度 0-1（20-30% 最佳，过深/过浅扣分）",
        sweep_range=(10.0, 20.0, 30.0),
        overfit_risk="medium",
        applicable_战法=("N字反击",),
        notes="回调结构：深度 20-30% + 不破首板起涨点",
    ),
    "leader_identity": Dimension(
        name="leader_identity",
        data_source="pattern_scan_s205.py:compute_leader_identity（sector_rank≤3 + lbc≥2 + high_gene，涨停池 raw + gene_scores）",
        normalization="龙头确认综合 0-1",
        sweep_range=(2.0, 3.0, 5.0),
        overfit_risk="medium",
        applicable_战法=("低吸龙头",),
        notes="龙头确认：sector_rank≤3/lbc≥2/high_gene 综合",
    ),
    "pullback_rhythm": Dimension(
        name="pullback_rhythm",
        data_source="pattern_scan_s205.py:compute_pullback_rhythm（距上次涨停3-5日 + 回调幅度20-30% + 第一次回调，baostock）",
        normalization="回调节奏合理度 0-1",
        sweep_range=(3.0, 5.0, 10.0),
        overfit_risk="medium",
        applicable_战法=("低吸龙头",),
        notes="回调节奏：距上次涨停 3-5 日 + 第一次回调",
    ),
    "reversal_confirm": Dimension(
        name="reversal_confirm",
        data_source="pattern_scan_s205.py:compute_reversal_confirm（close 突破上影中点 + 吞没 + 放量，baostock OHLCV）",
        normalization="反包确认综合 0-1",
        sweep_range=(3.0, 4.0, 5.0, 6.0),
        overfit_risk="medium",
        applicable_战法=("形态反包",),
        notes="反包确认：close 突破上影中点 + 吞没 + 放量",
    ),
}

# 5 共享维度英文 alias（= S203 中文同 data_source，S205 战法用英文 key）
_S205_SHARED_ALIAS: dict[str, Dimension] = {
    "emotion_cycle": Dimension(
        name="emotion_cycle",
        data_source="limitup_sti/models.py:63 STI score(5-phase+8维) + market.py:166 连板梯队",
        normalization="STI score/100",
        sweep_range=(),
        overfit_risk="extreme",
        applicable_战法=("ALL",),
        notes="= 情绪周期 英文 alias（S205 战法用英文 key）",
    ),
    "tech_pattern": Dimension(
        name="tech_pattern",
        data_source="MA5/MA10(baostock) + K线形态吞没/上影(OHLCV) + pattern_scan shadow_length_pct + ma5_slope",
        normalization="MA 排列+形态命中数/3",
        sweep_range=(2.0, 3.0, 4.0, 5.0),
        overfit_risk="medium",
        applicable_战法=("ALL",),
        notes="= 技术形态 英文 alias",
    ),
    "sector_strength": Dimension(
        name="sector_strength",
        data_source="sector_cycle.py:165 zt_count_today + sector_divergence.py:130 calculate_sector_divergence",
        normalization="zt_count_today/全市场涨停均值封顶1.0",
        sweep_range=(2.0, 3.0, 5.0, 10.0),
        overfit_risk="medium",
        applicable_战法=("ALL",),
        notes="= 板块强度 英文 alias",
    ),
    "volume_confirm": Dimension(
        name="volume_confirm",
        data_source="pattern_scan.py:49 volume_breakout_ratio + 换手率(涨停池 raw)",
        normalization="relay_vol_ratio/2.0 封顶1.0",
        sweep_range=(1.0, 1.5, 2.0, 2.5, 3.0),
        overfit_risk="high",
        applicable_战法=("ALL",),
        notes="= 量能确认 英文 alias",
    ),
    "seal_strength_auction": Dimension(
        name="seal_strength_auction",
        data_source="limitup_screener/models.py:50 seal_to_float_ratio（竞价口径）",
        normalization="seal_to_float_ratio/0.005 封顶1.0",
        sweep_range=(0.003, 0.005, 0.007, 0.010),
        overfit_risk="high",
        applicable_战法=("一字竞价",),
        notes="= 封单强度 竞价口径 alias",
    ),
    "volume_reversal": Dimension(
        name="volume_reversal",
        data_source="pattern_scan.py:49 volume_breakout_ratio（反转口径：缩量→放量反转）",
        normalization="量能反转 0-1",
        sweep_range=(1.0, 1.5, 2.0, 2.5),
        overfit_risk="high",
        applicable_战法=("低吸龙头",),
        notes="= 量能确认 反转口径 alias",
    ),
    "sector_strength_alt": Dimension(
        name="sector_strength_alt",
        data_source="sector_cycle.py sector_rank（改口径：板块内 rank 非 zt_count）",
        normalization="sector_rank≤3 命中 0-1",
        sweep_range=(2.0, 3.0, 5.0),
        overfit_risk="medium",
        applicable_战法=("低吸龙头",),
        notes="= 板块强度 改口径 alias（sector_rank 非 zt_count）",
    ),
}

# 加到 DIMENSION_REGISTRY（dragon_score composite 认英文 key）
DIMENSION_REGISTRY.update(_S205_NEW_DIMS)
DIMENSION_REGISTRY.update(_S205_SHARED_ALIAS)

# 5 战法 STRATEGY_CONFIGS（英文维度名，weights sum=1.0，edge_type 待验）
_S205_CONFIGS: dict[str, 战法ScoreConfig] = {
    "一字竞价": 战法ScoreConfig(
        战法="一字竞价",
        dimensions=("auction_signal", "seal_strength_auction", "emotion_cycle", "tech_pattern"),
        weights={"auction_signal": 0.30, "seal_strength_auction": 0.25, "emotion_cycle": 0.20, "tech_pattern": 0.25},
        edge_type="待验(event 候选)",
        sweep_params={"auction_open_pct": [2.0, 3.0, 5.0, 7.0], "seal_to_float_ratio": [0.003, 0.005, 0.007, 0.010]},
    ),
    "弱转强": 战法ScoreConfig(
        战法="弱转强",
        dimensions=("expectation_gap_reversal", "volume_confirm", "emotion_cycle", "tech_pattern", "sector_strength"),
        weights={"expectation_gap_reversal": 0.25, "volume_confirm": 0.20, "emotion_cycle": 0.25, "tech_pattern": 0.20, "sector_strength": 0.10},
        edge_type="待验(overnight_gap 候选)",
        sweep_params={"auction_vol_ratio": [1.0, 1.5, 2.0, 2.5, 3.0], "turnover_pct": [5.0, 10.0, 15.0, 20.0]},
    ),
    "N字反击": 战法ScoreConfig(
        战法="N字反击",
        dimensions=("volume_rhythm", "pullback_structure", "tech_pattern", "emotion_cycle", "sector_strength"),
        weights={"volume_rhythm": 0.30, "pullback_structure": 0.25, "tech_pattern": 0.25, "emotion_cycle": 0.10, "sector_strength": 0.10},
        edge_type="待验(selection 候选)",
        sweep_params={"three_stage_vol_ratio": [1.0, 1.5, 2.0, 2.5], "pullback_depth": [10.0, 20.0, 30.0], "pullback_days": [1.0, 2.0, 3.0]},
    ),
    "低吸龙头": 战法ScoreConfig(
        战法="低吸龙头",
        dimensions=("tech_pattern", "leader_identity", "pullback_rhythm", "volume_reversal", "emotion_cycle", "sector_strength_alt"),
        weights={"tech_pattern": 0.30, "leader_identity": 0.20, "pullback_rhythm": 0.20, "volume_reversal": 0.15, "emotion_cycle": 0.10, "sector_strength_alt": 0.05},
        edge_type="待验(path 候选)",
        sweep_params={"ma_pullback": [5.0, 10.0, 20.0], "pullback_amplitude": [10.0, 20.0, 30.0]},
    ),
    "形态反包": 战法ScoreConfig(
        战法="形态反包",
        dimensions=("tech_pattern", "volume_confirm", "reversal_confirm", "emotion_cycle", "sector_strength"),
        weights={"tech_pattern": 0.25, "volume_confirm": 0.20, "reversal_confirm": 0.25, "emotion_cycle": 0.15, "sector_strength": 0.15},
        edge_type="待验(event 候选)",
        sweep_params={"upper_shadow_pct": [3.0, 4.0, 5.0, 6.0], "volume_mult": [1.0, 1.5, 2.0, 2.5]},
    ),
}
STRATEGY_CONFIGS.update(_S205_CONFIGS)


def get_s205_config(战法: str) -> 战法ScoreConfig | None:
    """查 S205 战法 config（per-战法维度集）。未声明返 None。"""
    return _S205_CONFIGS.get(战法)


__all__ = [
    "DIMENSION_REGISTRY",
    "STRATEGY_CONFIGS",
    "_S205_NEW_DIMS",
    "_S205_SHARED_ALIAS",
    "_S205_CONFIGS",
    "get_s205_config",
]
