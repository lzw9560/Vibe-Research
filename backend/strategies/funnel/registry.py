# -*- coding: utf-8 -*-
"""策略注册表 + 权重加载。

单一 ``STRATEGY_REGISTRY: list[StrategyConfig]``（15 项，含 storm_reversal）。
``STRATEGY_FUNNEL_REGISTRY`` 保留为别名（向后兼容 routers/strategy + test）。

权重来源：.vibe-research/strategy_weights.json（Phase 0d 全样本回归定稿，非拍脑袋）。
权重加载失败 → 等权兜底（不崩，标注 fallback）。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from strategies.strategy_base import (
    PositionParams,
    QualityCheck,
    StrategyConfig,
    StrategyContext,
    StrategyMatchResult,
    _prepare_derived,
    _prepare_pool_item,
    dispatch_match,
)
from strategies.impl import (
    BreakResealStrategy,
    ConsecutiveRelayStrategy,
    DragonHeadStrategy,
    EndOfDaySneakStrategy,
    FirstBoardLimitupStrategy,
    FirstPlateStrategy,
    LeaderDropReversalStrategy,
    LowAbsorptionStrategy,
    NShapeCounterattackStrategy,
    PatternReversalStrategy,
    PlatformBreakoutStrategy,
    Relay23Strategy,
    ReversePackageStrategy,
    StormReversalStrategy,
    WeakTurnStrongStrategy,
)

# spec §3: weights 由 Phase 0d 全样本回归定稿（.vibe-research/strategy_weights.json）
# 测试时 VR_DATA_DIR 指向临时目录（conftest），weights 不存在 → 等权兜底
_DATA_DIR = Path(os.environ.get("VR_DATA_DIR", "")) if os.environ.get("VR_DATA_DIR") else Path(__file__).resolve().parent.parent.parent / ".vibe-research"
_WEIGHTS_PATH = _DATA_DIR / "strategy_weights.json"
_WEIGHTS_CACHE: dict | None = None

# 向后兼容别名（旧 StrategyFunnelConfig → 新 StrategyConfig 超集）
StrategyFunnelConfig = StrategyConfig


# ===========================================================================
# 策略注册表（单一 STRATEGY_REGISTRY：15 项，合并旧 dict + 旧 dataclass）
# ===========================================================================

STRATEGY_REGISTRY: list[StrategyConfig] = [
    # --- 涨停类（weight_set=limitup）---
    StrategyConfig(
        code="first_plate",
        name="首板挖掘",
        strategy_impl=FirstPlateStrategy(),
        stop_loss_pct=-3.0, take_profit_pct=8.0, max_hold_days=3,
        funnel_type="limitup", weight_set="limitup",
        weather_regimes=["阴天"], is_primary=True, fallback=False,
        entry_type="次日竞价/开盘确认后",
        entry_condition="首次涨停+基因得分≥40+涨停频次≥6",
        stop_loss_condition="跌破前日收盘价-3%",
        take_profit_condition="涨至+5%~+10%后回落",
        exit_condition="持仓3日未盈利或触发止损/止盈",
        aliases=["首板", "首次涨停"],
        quality_standards=[
            QualityCheck("开板次数", True, "封板稳定性，反复开板说明抛压大"),
            QualityCheck("封板时间≤10:30", True, "尾盘封板不算首板质量"),
        ],
    ),
    StrategyConfig(
        code="first_board_limitup",
        name="首板涨停",
        strategy_impl=FirstBoardLimitupStrategy(),
        stop_loss_pct=-5.0, take_profit_pct=10.0, max_hold_days=3,
        funnel_type="limitup", weight_set="limitup",
        weather_regimes=["晴天"], is_primary=True, fallback=False,
        entry_type="次日竞价/开盘确认后",
        entry_condition="板块共振(zt_count_today≥2)+封单≥0.5%+龙头(high_gene/sector_rank≤3)",
        stop_loss_condition="跌破5日均线-5%",
        take_profit_condition="涨至+8%~+12%后回落",
        exit_condition="持仓3日未盈利或触发止损/止盈",
        aliases=["首板涨停", "板块共振首板"],
        quality_standards=[
            QualityCheck("板块涨停家数≥2", True, "板块共振，避无板块效应秒板"),
            QualityCheck("封单/流通市值≥0.5%", True, "精品封单门槛"),
        ],
    ),
    StrategyConfig(
        code="leader_drop_reversal",
        name="龙头大跌反包",
        strategy_impl=LeaderDropReversalStrategy(),
        stop_loss_pct=-3.0, take_profit_pct=6.0, max_hold_days=1,
        funnel_type="limitup", weight_set="limitup",
        weather_regimes=["极端反弹"], is_primary=False, fallback=False,
        entry_type="次日竞价/开盘确认后",
        entry_condition="龙头大跌≥7%+吞没前日阴线+放量≥1.2x（⚠️占位：phase 2 bars wiring 待，当前 data_unavailable 不 fire）",
        stop_loss_condition="跌破入场价-3%",
        take_profit_condition="涨至+4%~+6%后回落",
        exit_condition="T+1 严格卖出或触发止损/止盈",
        aliases=["龙头大跌反包", "反包板"],
        quality_standards=[
            QualityCheck("龙头确认(high_gene)", True, "核心龙头大跌后反包"),
            QualityCheck("T-1大跌≥7%", True, "龙头大跌触发量化止损割肉筹码真空"),
        ],
    ),
    StrategyConfig(
        code="consecutive_relay",
        name="连板接力",
        strategy_impl=ConsecutiveRelayStrategy(),
        stop_loss_pct=-5.0, take_profit_pct=12.0, max_hold_days=2,
        funnel_type="limitup", weight_set="limitup",
        weather_regimes=["晴天", "未知"], is_primary=True, fallback=False,
        entry_type="连板次日竞价确认",
        entry_condition="250日涨停≥2+封板率≥60%",
        stop_loss_condition="跌破前日收盘价",
        take_profit_condition="涨至+8%~+15%后回落",
        exit_condition="连板高度≥3板或触发止损/止盈",
        aliases=["连板", "接力"],
        quality_standards=[
            QualityCheck("连板数≥2", True, "入场条件（连板接力定义）"),
            QualityCheck("封板率≥80%", True, "封板决心"),
        ],
    ),
    StrategyConfig(
        code="relay_23",
        name="接力二三板",
        strategy_impl=Relay23Strategy(),
        stop_loss_pct=-5.0, take_profit_pct=12.0, max_hold_days=2,
        funnel_type="limitup", weight_set="limitup",
        weather_regimes=["晴天"], is_primary=False, fallback=False,
        entry_type="次日竞价/开盘确认后",
        entry_condition="当下连板 lbc≥2+量比[1.5,2.5](放量不爆量)+Dragon Score(占位待接线)",
        stop_loss_condition="跌破前日收盘价-5%",
        take_profit_condition="涨至+8%~+12%后回落",
        exit_condition="连板高度≥3板或触发止损/止盈",
        aliases=["接力二三", "二板接力", "三板接力"],
        note="S203：当下连板接力（lbc 区别 consecutive_relay 历史频次）；Dragon Score C3 占位待 dimension_registry 接线，当前不阻塞 fire",
        quality_standards=[
            QualityCheck("当下连板≥2", True, "接力定义（lbc≥2 非历史频次）"),
            QualityCheck("量比[1.5,2.5]", True, "放量不爆量，接力健康区"),
        ],
    ),
    StrategyConfig(
        code="break_reseal",
        name="炸板回封",
        strategy_impl=BreakResealStrategy(),
        stop_loss_pct=-3.0, take_profit_pct=6.0, max_hold_days=1,
        funnel_type="limitup", weight_set="limitup",
        weather_regimes=["阴天", "极端反弹"], is_primary=True, fallback=False,
        entry_type="回封确认后",
        entry_condition="250日涨停∈[3,5]+封板率≥80%",
        stop_loss_condition="跌破回封价",
        take_profit_condition="涨至+5%~+8%后回落",
        exit_condition="当日收盘前未回封或触发止损/止盈",
        aliases=["回封", "炸板回封"],
        note="S053 R3：match 门槛与注册表统一为封板率≥80%（zt_count 3-5 黄金区 89.5% 命中率，19 样本）",
        quality_standards=[
            QualityCheck("开板次数≥1", True, "炸板回封定义需要至少一次开板"),
            QualityCheck("封板率≥80%", True, "回封后封板强度（S053 数据证据统一到 80%）"),
        ],
    ),
    # --- 非涨停类（weight_set=non_limitup）---
    StrategyConfig(
        code="low_absorption",
        name="低吸龙头",
        strategy_impl=LowAbsorptionStrategy(),
        stop_loss_pct=-5.0, take_profit_pct=10.0, max_hold_days=5,
        funnel_type="market_scan", weight_set="non_limitup",
        weather_regimes=["晴天", "阴天"], is_primary=False, fallback=True,
        entry_type="回调至5日均线附近",
        entry_condition="回调MA5(ma5_proximity≤3%)+均线多头(ma_bullish=True)",
        stop_loss_condition="跌破10日均线",
        take_profit_condition="涨至+8%~+12%后回落",
        exit_condition="跌破10日线或持仓5日未盈利",
        aliases=["低吸", "龙头低吸"],
        quality_standards=[
            QualityCheck("回调至MA5", True, "低吸入场点"),
        ],
    ),
    StrategyConfig(
        code="reverse_package",
        name="反包战法",
        strategy_impl=ReversePackageStrategy(),
        stop_loss_pct=-3.0, take_profit_pct=6.0, max_hold_days=1,  # S062：严格 T+1
        funnel_type="market_scan", weight_set="non_limitup",
        weather_regimes=["极端反弹"], is_primary=True, fallback=False,
        entry_type="次日竞价/开盘买入（前日反包确认）",
        entry_condition="前日真炸板（炸板池 open_count≥2 含 code）；旧 fanbao 五条件（T-2/T-3涨停/成交额>15亿/均线多头等）为历史参考，未接入 match",
        stop_loss_condition="跌破前日最低价",
        take_profit_condition="涨至+5%~+8%后回落",
        exit_condition="T+1 卖出纪律（不扛票）或触发止损/止盈",
        aliases=["反包", "地天板"],
        activation_note=None,  # S086 D1：数据已就绪，清过时 activation_note
        quality_standards=[
            QualityCheck("T-1未涨停", True, "反包定义"),
            QualityCheck("成交额>15亿", True, "反包需流动性"),
            QualityCheck("均线多头", False, "加分项"),
        ],
    ),
    StrategyConfig(
        code="n_shape_counterattack",
        name="N字反击",
        strategy_impl=NShapeCounterattackStrategy(),
        stop_loss_pct=-3.0, take_profit_pct=8.0, max_hold_days=3,
        funnel_type="limitup", weight_set="limitup",
        weather_regimes=["晴天", "极端反弹"], is_primary=False, fallback=True,
        entry_type="回调企稳后放量",
        entry_condition="250日涨停∈[2,10]（N字区间，纯基因频次）",
        stop_loss_condition="跌破回调低点",
        take_profit_condition="涨至+5%~+10%后回落",
        exit_condition="未出现放量反弹或触发止损/止盈",
        aliases=["N字", "反击"],
        note="归入涨停类权重集（spec §4.4）",
        quality_standards=[
            QualityCheck("2日内涨停", True, "N字形态需要前置涨停"),
        ],
    ),
    StrategyConfig(
        code="platform_breakout",
        name="平台突破",
        strategy_impl=PlatformBreakoutStrategy(),
        stop_loss_pct=-5.0, take_profit_pct=12.0, max_hold_days=7,
        funnel_type="market_scan", weight_set="non_limitup",
        weather_regimes=["晴天"], is_primary=True, fallback=False,
        entry_type="突破确认后",
        entry_condition="横盘≥5日+成交量放大2倍(量比>2)",
        stop_loss_condition="跌破平台上沿",
        take_profit_condition="涨至+8%~+15%后回落",
        exit_condition="突破失败回落或触发止损/止盈",
        aliases=["突破", "平台"],
        quality_standards=[
            QualityCheck("横盘≥5日", True, "平台定义"),
            QualityCheck("成交额放大2倍", True, "突破放量"),
        ],
    ),
    StrategyConfig(
        code="end_of_day_sneak",
        name="尾盘偷袭",
        strategy_impl=EndOfDaySneakStrategy(),
        stop_loss_pct=-2.0, take_profit_pct=4.0, max_hold_days=1,
        funnel_type="limitup", weight_set="limitup",
        weather_regimes=["阴天"], is_primary=True, fallback=False,
        entry_type="尾盘封板确认",
        entry_condition="封板率≥40%+次日溢价率>15%",
        stop_loss_condition="跌破封板价",
        take_profit_condition="涨至+3%~+5%后回落",
        exit_condition="未封板或触发止损/止盈",
        aliases=["尾盘", "偷袭"],
        quality_standards=[
            QualityCheck("封板时间>14:30", True, "尾盘专属，早盘封板不算"),
            QualityCheck("量比>2", True, "尾盘急拉需放量"),
        ],
    ),
    StrategyConfig(
        code="dragon_head",
        name="龙头战法",
        strategy_impl=DragonHeadStrategy(),
        stop_loss_pct=-5.0, take_profit_pct=15.0, max_hold_days=5,
        funnel_type="market_scan", weight_set="non_limitup",
        weather_regimes=["晴天", "阴天"], is_primary=True, fallback=False,
        entry_type="板块启动期龙头确认",
        entry_condition="板块内个股排名≤3(sector_rank)",
        stop_loss_condition="跌破5日均线",
        take_profit_condition="涨至+10%~+15%后回落",
        exit_condition="板块退潮或触发止损/止盈",
        aliases=["龙头", "龙头股"],
        quality_standards=[
            QualityCheck("板块领涨", True, "龙头定义"),
            QualityCheck("换手>5%", True, "龙头活跃度"),
        ],
    ),
    # --- S081 PRD P2 战法（弱转强接力 + 形态反包，dict 侧注册，探索性阈值）---
    StrategyConfig(
        code="weak_turn_strong",
        name="弱转强接力",
        strategy_impl=WeakTurnStrongStrategy(),
        stop_loss_pct=-5.0, take_profit_pct=10.0, max_hold_days=2,
        funnel_type="limitup", weight_set="limitup",
        weather_regimes=["晴天", "极端反弹"], is_primary=True, fallback=False,
        entry_type="次日竞价确认后",
        entry_condition="连板≥1(lbc)+炸板≥20min+回撤≥5%+尾盘封死≥14:40+换手1.8-3.0倍(≥4/5命中)",
        stop_loss_condition="跌破前日收盘价-5%",
        take_profit_condition="涨至+5%~+10%后回落",
        exit_condition="持仓2日未盈利或触发止损/止盈",
        aliases=["弱转强", "分歧转一致"],
        note="S081：PRD 阈值探索性（外部拍定，零数据支撑），因子依赖 S070 R7 派生（60s 粒度近似）",
    ),
    StrategyConfig(
        code="pattern_reversal",
        name="形态反包",
        strategy_impl=PatternReversalStrategy(),
        stop_loss_pct=-4.0, take_profit_pct=12.0, max_hold_days=3,
        funnel_type="market_scan", weight_set="non_limitup",
        weather_regimes=["晴天", "阴天"], is_primary=True, fallback=False,
        entry_type="次日突破昨日最高价确认",
        entry_condition="上影线≥4%+放量(今量/前5日均量)≥1.2+5日线向上(≥2/3命中)",
        stop_loss_condition="跌破前日最低价",
        take_profit_condition="涨至+8%~+12%后回落",
        exit_condition="突破失败回落或触发止损/止盈",
        aliases=["反包", "长上影洗盘修复"],
        note="S081：PRD 阈值探索性，因子来自涨停池+K线（不依赖 S070 R7）",
    ),
    # --- 暴风雨逆势涨停子策略（S086 R3：纳入 match，条件=封板≤10:30）---
    StrategyConfig(
        code="storm_reversal",
        name="暴风雨逆势涨停",
        strategy_impl=StormReversalStrategy(),
        stop_loss_pct=-3.0, take_profit_pct=10.0, max_hold_days=1,
        position_scale=0.3,  # S086 R4：仓位×0.3 降为建议（position_advisor 软标注，不强制）
        funnel_type="limitup", weight_set="storm_reversal",
        weather_regimes=["暴风雨"], is_primary=True, fallback=False,
        entry_type="早盘封板确认",
        entry_condition="早盘封板(首封≤10:30,fbt)；暴风雨天/逆势为软标注非命中",
        stop_loss_condition="跌破封板价",
        take_profit_condition="涨至+5%~+10%后回落",
        exit_condition="次日开盘清仓或触发止损/止盈",
        aliases=["暴风雨逆势", "逆势涨停"],
        note="暴风雨天推荐主跑策略，仓位×0.3（环境极端，建议非强制）",
        quality_standards=[
            QualityCheck("封板时间≤10:30", True, "暴风雨天尾盘涨停不算逆势"),
        ],
    ),
]

# 向后兼容别名：旧 STRATEGY_FUNNEL_REGISTRY 消费方（routers/strategy.py / test）零改动
STRATEGY_FUNNEL_REGISTRY: list[StrategyConfig] = STRATEGY_REGISTRY

# S094 T11（spec §3.M）：15 战法按 funnel_type 归组——score_candidates 必填 funnel_type，
# 只跑该组的战法（limitup 7 / market_scan 5），二者不交叉（R7）。
# 注：S203 新增 first_board_limitup/leader_drop_reversal/relay_23 虽 funnel_type=limitup，
# 但不入此列表——它们读 msc（bars/lbc/seal/zt_count），由 get_strategy_signals 的
# _build_limitup_msc 构造、走 dispatch_match 全注册表路径 fire，不经 candidate funnel。
STRATEGIES_BY_FUNNEL_TYPE: dict[str, list[str]] = {
    "limitup": [
        "first_plate", "consecutive_relay", "break_reseal", "n_shape_counterattack",
        "end_of_day_sneak", "weak_turn_strong", "storm_reversal",
    ],
    "market_scan": [
        "dragon_head", "low_absorption", "reverse_package", "platform_breakout", "pattern_reversal",
    ],
}


def get_strategy_config(code: str) -> StrategyConfig | None:
    """按 code 查策略配置。"""
    return next((s for s in STRATEGY_REGISTRY if s.code == code), None)


def _load_weights() -> dict:
    """加载 strategy_weights.json（Phase 0d 定稿）。失败返空 dict（等权兜底）。"""
    global _WEIGHTS_CACHE
    if _WEIGHTS_CACHE is not None:
        return _WEIGHTS_CACHE
    try:
        _WEIGHTS_CACHE = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        _WEIGHTS_CACHE = {}
    return _WEIGHTS_CACHE


def _get_weight_set(weight_set_name: str) -> dict:
    """取某套权重。不存在返空 dict。"""
    data = _load_weights()
    return data.get("weight_sets", {}).get(weight_set_name, {})
