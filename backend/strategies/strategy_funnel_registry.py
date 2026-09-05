# -*- coding: utf-8 -*-
"""S066 §3-4 策略特定漏斗注册表 + 天气软标注 + 3 套权重策略分计算。

S086 重构：合并旧 STRATEGY_REGISTRY（dict，11 项）+ STRATEGY_FUNNEL_REGISTRY
（dataclass，10 项）为单一 ``STRATEGY_REGISTRY: list[StrategyConfig]``（12 项，
含 storm_reversal）。``STRATEGY_FUNNEL_REGISTRY`` 保留为别名（向后兼容 routers/strategy
+ test）。消灭 ``_MATCHED_STRATEGY_CODES`` 白名单与暴风雨硬开关（R3 全 allowed）。

核心架构：
- 单一注册表 ``StrategyConfig``（参数 + 指向 Strategy 实现），位于 strategy_base
- match 分发由 ``strategy_base.dispatch_match`` 调度器统一组装（不再 if/elif switch）
- 3 套权重（涨停类/非涨停类/暴风暴），不是 9 套——样本量不够支撑每策略单独估参
- 天气硬开关降级为软标注（grill Q7 + S086 R3：暴风雨不再 forbidden，全 allowed）

权重来源：.vibe-research/strategy_weights.json（Phase 0d 全样本回归定稿，非拍脑袋）。
权重加载失败 → 等权兜底（不崩，标注 fallback）。
"""
from __future__ import annotations

import json
import logging
import os
import dataclasses
from dataclasses import field
from pathlib import Path
from typing import Literal, Optional

# S086：数据结构上提到 strategy_base（单一事实源），本模块只组装注册表 + 权重 + 质量标准
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
    FirstPlateStrategy,
    LowAbsorptionStrategy,
    NShapeCounterattackStrategy,
    PatternReversalStrategy,
    PlatformBreakoutStrategy,
    ReversePackageStrategy,
    StormReversalStrategy,
    WeakTurnStrongStrategy,
)
from strategies.market_scan import _build_market_data  # S094 2b-i-c: market_scan check_quality 闸前移用

# spec §3: weights 由 Phase 0d 全样本回归定稿（.vibe-research/strategy_weights.json）
# 测试时 VR_DATA_DIR 指向临时目录（conftest），weights 不存在 → 等权兜底
_DATA_DIR = Path(os.environ.get("VR_DATA_DIR", "")) if os.environ.get("VR_DATA_DIR") else Path(__file__).resolve().parent.parent.parent / ".vibe-research"
_WEIGHTS_PATH = _DATA_DIR / "strategy_weights.json"
_WEIGHTS_CACHE: dict | None = None

# 向后兼容别名（旧 StrategyFunnelConfig → 新 StrategyConfig 超集）
StrategyFunnelConfig = StrategyConfig


# ===========================================================================
# 天气-策略推荐（spec §3.3，grill Q7 降级为软标注；S086 R3 暴风雨不再硬约束）
# ===========================================================================

# grill Q7 + S086 R3：天气硬开关降级为软标注（含暴风雨例外移除）
# 所有战法对所有天气可用，天气匹配的标注"推荐"（weather_recommended）。
# 理由：(1) T-1 天气不代表 T 日天气；(2) §13.0 验证天气路由无统计显著提升；
#       (3) 强约束导致 0 候选比无约束更有害。
WEATHER_RECOMMENDATION: dict[str, set[str]] = {
    "晴天":   {"consecutive_relay", "dragon_head", "platform_breakout"},
    "阴天":   {"first_plate", "break_reseal", "end_of_day_sneak"},
    "极端反弹": {"reverse_package"},
    "暴风雨": {"storm_reversal"},  # 软标注推荐（不再硬约束仓位=0）
    "未知":   set(),
}

# 向后兼容 alias（grill Q7 后应改用 WEATHER_RECOMMENDATION）
WEATHER_STRATEGY_MAP = {k: list(v) for k, v in WEATHER_RECOMMENDATION.items()}

FALLBACK_STRATEGIES: dict[str, list[str]] = {
    "晴天":   ["low_absorption"],
    "阴天":   ["low_absorption"],
    "极端反弹": [],
    "暴风雨": [],   # 暴风雨无 fallback——空仓也是策略
    "未知":   [],
}


def get_weather_recommendation(weather_state: str | None) -> set[str]:
    """天气推荐战法集合（软标注，不用于过滤候选）。"""
    if not weather_state:
        return set()
    return WEATHER_RECOMMENDATION.get(weather_state, set())


def get_strategies_for_weather(weather_state: str | None) -> tuple[list[str], list[str]]:
    """天气 → (主跑策略 codes, fallback 策略 codes)。

    S086 R3：暴风雨不再硬约束（全 allowed）；所有天气返回所有已注册战法（非空），
    fallback 恒为 []。天气推荐集合用 get_weather_recommendation() 查。
    """
    all_codes = [s.code for s in STRATEGY_REGISTRY]
    return (all_codes, [])


# ===========================================================================
# 策略注册表（单一 STRATEGY_REGISTRY：12 项，合并旧 dict + 旧 dataclass）
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

# S094 T11（spec §3.M）：12 战法按 funnel_type 归组——score_candidates 必填 funnel_type，
# 只跑该组的战法（limitup 7 / market_scan 5），二者不交叉（R7）。
# limitup：first_plate 首板 / consecutive_relay 连板 / break_reseal 炸板回封 /
#   n_shape_counterattack N字 / end_of_day_sneak 尾盘 / weak_turn_strong 弱转强 / storm_reversal 暴风暴
# market_scan：dragon_head 龙头 / low_absorption 低吸 / reverse_package 反包 /
#   platform_breakout 平台突破 / pattern_reversal 形态反包
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


# ===========================================================================
# 3 套权重策略分计算
# ===========================================================================

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


def compute_strategy_score(
    factors: dict[str, float],
    weight_set: str,
) -> tuple[float, dict[str, float]]:
    """按指定权重集计算策略分。

    factors: {factor_name: value}（来自 gene_scores，中文键名）
    weight_set: "limitup" / "non_limitup" / "storm_reversal"
    返回 (score, breakdown)。

    spec §4.1 涨停类：
        score = Σ(factor_value [× reverse ? (100-x) : x] × weight)
    反向因子（premium/freq）用 (100-value) 反转。

    权重加载失败 → 等权兜底（标注 fallback）。

    因子名映射：权重文件用英文键名（factor_seal_rate 等），
    gene_scores 用中文键名（封板率 等），需映射查值。
    """
    # 英文权重键 → 中文 gene_scores 键
    _FACTOR_NAME_MAP = {
        "factor_seal_rate": "封板率",
        "factor_red_rate": "红盘率",
        "factor_rebound_rate": "炸板后溢价",
        "factor_freq_score": "涨停频次",
        "factor_premium": "次日溢价率",
        "relative_strength": "相对强度",
        "ma_bullish": "均线多头",
        "volume_signal": "量能信号",
        "sector_strength": "板块强度",
    }
    ws = _get_weight_set(weight_set)
    weights = ws.get("weights", {})
    if not weights:
        # 等权兜底：所有因子等权 1/N
        if factors:
            n = len(factors)
            score = sum(factors.values()) / n
            breakdown = {k: v / n for k, v in factors.items()}
        else:
            score = 0.0
            breakdown = {}
        return round(score, 4), breakdown

    # S151 R2：评价层降权注入——gene-based 因子（封板率/红盘率/炸板后溢价/涨停频次/次日溢价率）
    # proxy 映射 gene composite rho≈0 → 推断无方向性 → ×0.1（indirect, 非 direct measurement, spec §E）
    # 非 gene 因子（相对强度/均线多头/量能信号/板块强度）×1.0
    _GENE_BASED_FACTORS = {
        "factor_seal_rate", "factor_red_rate", "factor_rebound_rate",
        "factor_freq_score", "factor_premium",
    }
    try:
        from candidate_funnel.evaluation import DIMENSION_LIFT_REGISTRY  # 懒导入避循环
        gene_multiplier = DIMENSION_LIFT_REGISTRY["gene_score"].weight_multiplier  # 0.1
    except Exception:  # noqa: BLE001 — import 失败降级默认（gene rho≈0 → ×0.1）
        gene_multiplier = 0.1
    total = 0.0
    breakdown = {}
    for factor_name, w_info in weights.items():
        w = w_info.get("weight", 0)
        reverse = w_info.get("reverse", False)
        # 英文权重键 → 中文 gene_scores 键映射
        cn_name = _FACTOR_NAME_MAP.get(factor_name, factor_name)
        val = factors.get(cn_name, 0)
        if reverse:
            val = 100 - val
        # S151 R2：gene-based 因子 ×0.1 proxy 降权，非 gene 因子 ×1.0
        multiplier = gene_multiplier if factor_name in _GENE_BASED_FACTORS else 1.0
        contribution = val * w * multiplier
        total += contribution
        breakdown[factor_name] = round(contribution, 4)

    return round(total, 4), breakdown


def _cand_to_gene(cand: dict):
    """dict 候选 → GeneScore 适配（grill Q6：dispatch_match 需要 GeneScore）。

    字段映射经 limitup_screener/models.py GeneScore 定义核实。
    factors 优先取 cand["factors"]；total_score/zt_count_250d 同时回退到 factors 内同名键。
    wilson_adjusted/qualify/high_gene/last_zt_dates 用安全默认值——
    dispatch_match 只读 total_score/factors/zt_count_250d/code，不读这几项。
    """
    from limitup_screener.models import GeneScore

    factors = cand.get("factors", {}) or {}
    total = cand.get("total_score", factors.get("total_score", 0)) or 0
    zt_count = cand.get("zt_count_250d", factors.get("zt_count_250d", 0)) or 0
    return GeneScore(
        code=cand.get("code", ""),
        name=cand.get("name", ""),
        total_score=float(total),
        factors=factors,
        wilson_adjusted=float(total),
        qualify=total >= 50,
        high_gene=total >= 60,
        last_zt_dates=[],
        zt_count_250d=int(zt_count),
        data_source=cand.get("data_source", "eastmoney_live"),
        date=cand.get("date", ""),
    )


def _build_market_scan_factors(pattern, cand: dict, strat_code: str) -> dict:
    """S094 audit fix: market_scan 候选从 PatternScan + strat_code 建 factors dict（4 因子 0-100）。

    run_non_limitup_funnel（R27/T9-full）产 pattern（PatternScan）不产 factors dict →
    score_candidates 拿 cand["factors"]={} 空 → compute_strategy_score 全 0（非涨停侧 scoring 废）。
    此处补建：相对强度/均线多头/板块强度（candidate-level，compute_*_score）+
    量能信号（per-strategy，compute_volume_signal_score(pattern, strat_code)，R4 下沉 match 层算）。
    pattern None → 各因子降级 50（不臆造 0）。
    """
    from strategies.non_limitup_funnel import (  # 懒 import 防 circular
        compute_relative_strength_score, compute_ma_bullish_score,
        compute_volume_signal_score, compute_sector_strength_score,
    )
    sector_rank = cand.get("sector_rank")
    return {
        "相对强度": compute_relative_strength_score(pattern) if pattern is not None else 50.0,
        "均线多头": compute_ma_bullish_score(pattern) if pattern is not None else 50.0,
        "量能信号": compute_volume_signal_score(pattern, strat_code) if pattern is not None else 50.0,
        "板块强度": compute_sector_strength_score(sector_rank),
    }


def _aggregate_strategy_funnels(
    funnel_registry: list[StrategyConfig],
    cand_match_results: list[tuple[dict, dict[str, StrategyMatchResult]]],
) -> dict[str, dict]:
    """S097 R10：每战法跨候选批次聚合 StrategyFunnelSummary。

    每条件 input_count=评估候选数 / passed_count=hit 数 / data_unavailable_count=数据缺数 /
    pass_rate；candidates 存每候选条件命中标记（hit/miss/data_unavailable 三态）。
    data_ok=False 的战法（无 pattern/DB 等）→ 该候选 conditions 全 data_unavailable，
    独立统计不算逻辑过滤（R7），避免数据缺失误显为「过滤掉 X 只」。
    """
    summaries: dict[str, dict] = {}
    for cfg in funnel_registry:
        cond_specs: list[tuple[str, str, str, str]] = []
        per_cond_hit: dict[str, int] = {}
        per_cond_du: dict[str, int] = {}
        fired_count = 0
        cand_marks: list[dict] = []
        for cand, results_by_code in cand_match_results:
            r = results_by_code.get(cfg.code)
            if r is None:
                cand_marks.append({
                    "code": cand.get("code", ""), "name": cand.get("name", ""),
                    "fired": False, "conditions": [],
                })
                continue
            if not cond_specs:
                cond_specs = [(c.condition_id, c.condition_name, c.factor, c.threshold)
                              for c in r.conditions]
            if r.fired:
                fired_count += 1
            cand_marks.append({
                "code": cand.get("code", ""), "name": cand.get("name", ""),
                "fired": r.fired,
                "conditions": [{"condition_id": c.condition_id, "state": c.state}
                               for c in r.conditions],
            })
            for c in r.conditions:
                if c.state == "hit":
                    per_cond_hit[c.condition_id] = per_cond_hit.get(c.condition_id, 0) + 1
                elif c.state == "data_unavailable":
                    per_cond_du[c.condition_id] = per_cond_du.get(c.condition_id, 0) + 1
        total = len(cand_match_results)
        conditions_agg = []
        for cid, cname, factor, threshold in cond_specs:
            passed = per_cond_hit.get(cid, 0)
            du = per_cond_du.get(cid, 0)
            conditions_agg.append({
                "condition_id": cid, "condition_name": cname,
                "factor": factor, "threshold": threshold,
                "input_count": total, "passed_count": passed,
                "data_unavailable_count": du,
                "pass_rate": round(passed / total, 4) if total else 0.0,
            })
        summaries[cfg.code] = {
            "strategy_code": cfg.code, "strategy_name": cfg.name,
            "fired_count": fired_count, "total_count": total,
            "conditions": conditions_agg, "candidates": cand_marks,
        }
    return summaries


def score_candidates(
    candidates: list[dict],
    weather_state: str | None,
    funnel_type: str,  # S094 R7/T11: 必填 limitup|market_scan（无默认，防 None=全跑 crash，brief 拍板 #3）
    trade_date: str | None = None,
    pool_item_map: dict[str, dict] | None = None,
) -> list[dict]:
    """天气软标注 + 策略分排序 → 候选列表。

    candidates: [{code, name, factors: {seal_rate, premium, ...}, ...}]
    返回：[{code, name, strategy_code, strategy_name, score, breakdown, ...}]

    trade_date: S073 §9.4 游资席位画像接线（可选）；传则 batch 取当日龙虎榜 + per-cand
    compute_seat_risk_factor 修饰策略分（画像未建→modifier 1.0 降级标注）；不传则不接。

    pool_item_map: S086 R7/C8——{code: 涨停池原始 dict（含 fbt/lbc/zdp/p/...）}，
    供调度器构造 StrategyContext.pool_item（storm_reversal 读 fbt；PRD 战法读 lbc/zdp/p）。
    不传（默认 None）→ pool_item=None 降级，storm_reversal/PRD 战法不命中（既有战法不受影响），
    入场价 fallback gene.total_score + "价格代理" 标注（A7）。

    流程（spec §3.1）：
    1. 天气 → 主跑策略组（R3 全 allowed，含暴风雨）+ fallback
    2. 每个候选调 dispatch_match 算命中的战法 signals（match 过滤闭环，无白名单）
    3. 命中战法用其 weight_set 计算策略分
    4. 按策略分降序排序

    grill Q6（match 过滤闭环）：dispatch_match 只返回 match 命中的战法 signals，
    matched_codes 即过滤结果（消灭旧 _MATCHED_STRATEGY_CODES 白名单）。
    """
    # S094 T11：funnel_type 必填——只跑该 funnel_type 的战法（limitup 7 / market_scan 5，不交叉）。
    # R9 行为变化面：limitup 路径不再跑 market_scan 战法（dragon_head/low_absorption/platform_breakout/
    # reverse_package/pattern_reversal 从"可能命中"变"永不命中"——涨停股本不该命中非涨停战法，方向对）。
    if funnel_type not in STRATEGIES_BY_FUNNEL_TYPE:
        return [{
            "strategy_code": "none",
            "note": f"未知 funnel_type={funnel_type}（必填 limitup|market_scan）",
            "strategy_score": 0, "strategy": "无符合条件标的", "factors": {},
        }]
    funnel_codes = set(STRATEGIES_BY_FUNNEL_TYPE[funnel_type])
    funnel_registry = [cfg for cfg in STRATEGY_REGISTRY if cfg.code in funnel_codes]
    primary_codes, _ = get_strategies_for_weather(weather_state)
    primary_codes = [c for c in primary_codes if c in funnel_codes]  # T11: 只本 funnel_type
    # 天气推荐集合（软标注）——用于在候选上标 weather_recommended=True/False
    recommendation = get_weather_recommendation(weather_state)

    # S073 §9.4 游资席位画像接线（batch billboard + profiles；画像未建→load_aggregate_profiles 返空→modifier 1.0 降级）
    # S123 R2.4：切 _meta，partial fetch 标 degraded（live 承重链，不喂残缺数据当完整用）
    seat_profiles = None
    billboard = None
    if trade_date:
        try:
            from strategies.hot_money_seats import (
                compute_seat_risk_factor,
                load_aggregate_profiles,
                fetch_billboard_for_date_meta,
            )
            seat_profiles = load_aggregate_profiles()
            _bb_meta = fetch_billboard_for_date_meta(trade_date)
            if not (_bb_meta["buy_ok"] and _bb_meta["sell_ok"]):
                logging.getLogger(__name__).warning(
                    "score_candidates billboard %s 残缺（buy_ok=%s, sell_ok=%s）"
                    "→ seat risk 用可用 rows 降级",
                    trade_date, _bb_meta["buy_ok"], _bb_meta["sell_ok"],
                )
            billboard = _bb_meta["rows"]
        except Exception:
            seat_profiles = None
            billboard = None

    scored: list[dict] = []
    cand_match_results: list[tuple[dict, dict[str, StrategyMatchResult]]] = []
    for cand in candidates:
        factors = cand.get("factors", {})
        # grill Q6：dict → GeneScore 适配（dispatch_match 的入参类型）
        gene = _cand_to_gene(cand)
        code = cand.get("code", "")
        # S086 R7：从 pool_item_map 构造 ctx.pool_item；derived 走调度器统一 fallback
        pool_item = _prepare_pool_item(pool_item_map, code)
        derived = _prepare_derived(None, code)
        # S094 T10：market_scan 分支构造 market_scan_ctx（4 战法读 PatternScan 始生效，R6）
        market_scan_ctx = None
        if funnel_type == "market_scan":
            _pat = cand.get("pattern")
            market_scan_ctx = {
                "pattern": _pat,
                "sector_rank": cand.get("sector_rank"),
                "rel_strength_vs_sector": getattr(_pat, "relative_strength", None) if _pat is not None else None,
            }
        ctx = StrategyContext(
            code=code, gene=gene, pool_item=pool_item,
            indicators=None, derived=derived, weather_state=weather_state,
            market_scan_ctx=market_scan_ctx,
        )
        # S097：直接调 impl.match 收集全量 StrategyMatchResult（含 fired=False/data_unavailable，
        # 供批次聚合；不经 dispatch_match——后者跳过 fired=False 不够漏斗统计）
        results_by_code: dict[str, StrategyMatchResult] = {}
        for _cfg in funnel_registry:
            try:
                _r = _cfg.strategy_impl.match(ctx)
            except Exception:  # noqa: BLE001 - 单战法异常不阻断
                continue
            if isinstance(_r, StrategyMatchResult):
                results_by_code[_cfg.code] = _r
        cand_match_results.append((cand, results_by_code))
        matched_codes = {c for c, r in results_by_code.items() if r.fired}
        for strat_code in primary_codes:
            cfg = get_strategy_config(strat_code)
            if cfg is None:
                continue
            # S086 R3/C2：暴风雨守卫已删——storm_reversal 可在任意天气评分（若 fbt 命中）
            # grill Q6 match 过滤：仅对 dispatch 命中的战法打分（matched_codes 即过滤结果）
            if strat_code not in matched_codes:
                continue
            # S094 R27: market_scan check_quality 闸前移（硬剔除，不丢 S075 底线）
            if funnel_type == "market_scan":
                market_data = _build_market_data(cand.get("pattern"), cand)
                if not passes_hard_standards(check_quality_standards({"code": code}, strat_code, market_data)):
                    continue
            # S094 audit fix: market_scan 候选无 factors dict（run_non_limitup_funnel 产 pattern 不产 factors）
            # → 从 PatternScan+strat_code 建 per-strategy factors（量能信号 per-strategy R4），否则 score=0.0
            _factors_for_score = _build_market_scan_factors(cand.get("pattern"), cand, strat_code) if funnel_type == "market_scan" else factors
            score, breakdown = compute_strategy_score(_factors_for_score, cfg.weight_set)
            # S073 §9.4 游资画像修饰（画像未建→modifier 1.0 不扣分，标 risk_label）
            seat_risk = None
            if trade_date and billboard is not None:
                try:
                    seat_risk = compute_seat_risk_factor(cand.get("code", ""), trade_date, seat_profiles, None, billboard)
                    score = round(score * seat_risk.score_modifier, 4)
                except Exception:
                    seat_risk = None
            # S097：从 StrategyMatchResult 取 confidence/signal_strength；volume_signal 下沉 match 层
            _r = results_by_code.get(strat_code)
            _confidence = _r.confidence if _r else None
            _signal_strength = int((_r.confidence or 0) * 100) if _r else None
            _volume_signal = cfg.strategy_impl.compute_volume_signal(ctx) if _r else None
            scored.append({
                **{k: v for k, v in cand.items() if k not in ("bars", "pattern")},  # S094 audit: strip heavy bars/pattern（不进 briefing JSON，前端 NonLimitupLane 只用 code/name/sector/strategy_score）
                "strategy_code": cfg.code,
                "strategy_name": cfg.name,
                "strategy_score": score,
                "score_breakdown": breakdown,
                "confidence": _confidence,  # S094 R12: 复用 dispatch_match compute_confidence（不派生 strategy_score/100）
                "signal_strength": _signal_strength,
                "funnel_type": cfg.funnel_type,
                "position_params": dataclasses.asdict(cfg.position_params),
                "weather_recommended": strat_code in recommendation,  # grill Q7：天气推荐标注（软标注）
                "volume_signal": _volume_signal,  # S094 R4：per-strategy 量能信号（None=未计算/涨停 pipeline 降级）
                "hot_money_seat_risk": (
                    {
                        "day_trip_ratio": seat_risk.day_trip_ratio,
                        "relay_ratio": seat_risk.relay_ratio,
                        "risk_label": seat_risk.risk_label,
                        "score_modifier": seat_risk.score_modifier,
                    }
                    if seat_risk else None
                ),
            })

    # S097 R10/R17：批次聚合 StrategyFunnelSummary（每战法跨候选 input/passed/data_unavailable/
    # pass_rate + 候选命中标记），回填 scored 每项 strategy_funnel
    summaries = _aggregate_strategy_funnels(funnel_registry, cand_match_results)
    for s in scored:
        s["strategy_funnel"] = summaries.get(s.get("strategy_code"))

    scored.sort(key=lambda x: x.get("strategy_score", 0), reverse=True)
    if not scored:
        # grill Q5：诚实标注 0 输出原因（不掩盖数据缺失）
        if not candidates:
            note = "当日涨停池无数据"
        elif weather_state == "极端反弹":
            note = "炸板池数据缺失（S055 采集未完成）或昨日无 open_count>=2 的票"
        else:
            note = f"候选股因子值不满足 {', '.join(primary_codes)} 的入场条件"
        return [{
            "strategy_code": "none",
            "note": note,
            "strategy_score": 0,
            "strategy": "无符合条件标的",
            "factors": {},
        }]
    return scored


# ===========================================================================
# 质量标准检查
# ===========================================================================

def check_quality_standards(
    candidate: dict,
    strategy_code: str,
    market_data: dict | None = None,
) -> list[dict]:
    """检查策略特定质量标准（spec §7）。

    返回 [{name, passed, required, description}]。
    missing 数据标 "数据不足"（不作为硬标准，spec §7.1）。

    market_data: {seal_time, open_count, seal_amount, float_market_cap, ...}
    缺字段 → 该标准标 missing=True 不通过硬过滤。
    """
    cfg = get_strategy_config(strategy_code)
    if not cfg:
        return []

    results = []
    md = market_data or {}
    for std in cfg.quality_standards:
        passed = False
        missing = False
        detail = ""

        if std.name == "开板次数" or std.name == "开板次数≥1":
            oc = md.get("open_count")
            if oc is None:
                missing = True
            elif strategy_code == "break_reseal" or std.name == "开板次数≥1":
                passed = oc >= 1  # 炸板回封需要至少一次开板
            else:
                passed = oc <= 1
            detail = f"开板次数={oc}" if oc is not None else "数据不足"

        elif std.name == "封板时间≤10:30":
            st = md.get("seal_time")
            if st is None:
                missing = True
            else:
                passed = st <= "10:30"
            detail = f"封板时间={st}" if st else "数据不足"

        elif std.name == "封板时间>14:30":
            st = md.get("seal_time")
            if st is None:
                missing = True
            else:
                passed = st > "14:30"
            detail = f"封板时间={st}" if st else "数据不足"

        elif std.name == "连板数≥2":
            lb = md.get("consecutive_boards")
            if lb is None:
                missing = True
            else:
                passed = lb >= 2
            detail = f"连板数={lb}" if lb is not None else "数据不足"

        elif std.name == "封板率≥80%":
            sr = md.get("seal_rate")
            if sr is None:
                missing = True
            else:
                passed = sr >= 80
            detail = f"封板率={sr}" if sr is not None else "数据不足"

        elif std.name == "封板率≥60%":
            sr = md.get("seal_rate")
            if sr is None:
                missing = True
            else:
                passed = sr >= 60
            detail = f"封板率={sr}" if sr is not None else "数据不足"

        elif std.name == "量比>2":
            vr = md.get("vol_ratio")
            if vr is None:
                missing = True
            else:
                passed = vr > 2
            detail = f"量比={vr}" if vr is not None else "数据不足"

        elif std.name == "T-1未涨停":
            t1_zt = md.get("t1_limit_up")
            if t1_zt is None:
                missing = True
            else:
                passed = not t1_zt
            detail = "T-1涨停" if t1_zt else "T-1未涨停"

        elif std.name == "成交额>15亿":
            amt = md.get("amount_yi")
            if amt is None:
                missing = True
            else:
                passed = amt > 15
            detail = f"成交额={amt}亿" if amt is not None else "数据不足"

        elif std.name == "均线多头":
            ma5 = md.get("ma5")
            ma10 = md.get("ma10")
            ma20 = md.get("ma20")
            if None in (ma5, ma10, ma20):
                missing = True
            else:
                passed = ma5 > ma10 > ma20
            detail = f"MA5={ma5}/MA10={ma10}/MA20={ma20}"

        elif std.name == "横盘≥5日":
            consolidation = md.get("consolidation_days")
            if consolidation is None:
                missing = True
            else:
                passed = consolidation >= 5
            detail = f"横盘{consolidation}日" if consolidation is not None else "数据不足"

        elif std.name == "成交额放大2倍":
            vol_breakout = md.get("vol_breakout_ratio")
            if vol_breakout is None:
                missing = True
            else:
                passed = vol_breakout >= 2
            detail = f"量比放大{vol_breakout}倍" if vol_breakout is not None else "数据不足"

        elif std.name == "板块领涨":
            sector_rank = md.get("sector_rank")
            if sector_rank is None:
                missing = True
            else:
                passed = sector_rank <= 3  # TOP-3 板块
            detail = f"板块排名={sector_rank}" if sector_rank is not None else "数据不足"

        elif std.name == "换手>5%":
            turnover = md.get("turnover_rate")
            if turnover is None:
                missing = True
            else:
                passed = turnover > 5
            detail = f"换手={turnover}%" if turnover is not None else "数据不足"

        elif std.name == "回调至MA5":
            ma5 = md.get("ma5")
            close = md.get("close")
            if None in (ma5, close):
                missing = True
            else:
                passed = abs(close - ma5) / ma5 * 100 < 3  # 接近 MA5
            detail = f"close={close}/MA5={ma5}"

        elif std.name == "2日内涨停":
            recent_zt = md.get("recent_zt_days", 0)
            if recent_zt is None:
                missing = True
            else:
                passed = recent_zt >= 1
            detail = f"近{recent_zt}日涨停"

        else:
            missing = True
            detail = "未实现检查逻辑"

        results.append({
            "name": std.name,
            "passed": passed,
            "required": std.required,
            "missing": missing,
            "description": std.description,
            "detail": detail,
        })

    return results


def passes_hard_standards(quality_results: list[dict]) -> bool:
    """是否通过所有硬标准（required=True 且无 missing）。

    spec §7.1：missing 率 > 50% 的标准标注"数据不足，不作为硬标准"。
    本函数对 missing 的标准不阻断（不作为硬标准）。
    """
    for r in quality_results:
        if r["required"] and not r["missing"] and not r["passed"]:
            return False
    return True
