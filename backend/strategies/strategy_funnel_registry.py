# -*- coding: utf-8 -*-
"""S066 §3-4 策略特定漏斗注册表 + 天气硬开关 + 3 套权重策略分计算。

核心架构变更（spec §3）：
- 旧 STRATEGY_REGISTRY 是 list[dict]，calc_weather_fit 是**软过滤**（降权不屏蔽）
- 新 STRATEGY_FUNNEL_REGISTRY 是 dataclass 列表，WEATHER_STRATEGY_MAP 是**硬开关**
  （不适配天气的策略不跑，不是降权）
- 3 套权重（涨停类/非涨停类/暴风暴），不是 9 套——样本量不够支撑每策略单独估参

权重来源：.vibe-research/strategy_weights.json（Phase 0d 全样本回归定稿，非拍脑袋）。
权重加载失败 → 等权兜底（不崩，标注 fallback）。

与旧 limitup_strategy.STRATEGY_REGISTRY 的关系：
- 旧 registry 保留（match_strategies 仍用），本模块是**新增层**不是替换
- 新 registry 的策略 code 与旧 registry 对齐（first_plate/consecutive_relay/...）
- 前端候选卡片逐步切到新 registry 的策略分排序
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

# spec §3: weights 由 Phase 0d 全样本回归定稿（.vibe-research/strategy_weights.json）
# 测试时 VR_DATA_DIR 指向临时目录（conftest），weights 不存在 → 等权兜底
_DATA_DIR = Path(os.environ.get("VR_DATA_DIR", "")) if os.environ.get("VR_DATA_DIR") else Path(__file__).resolve().parent.parent.parent / ".vibe-research"
_WEIGHTS_PATH = _DATA_DIR / "strategy_weights.json"
_WEIGHTS_CACHE: dict | None = None


# ===========================================================================
# 数据结构
# ===========================================================================

@dataclass(frozen=True)
class PositionParams:
    """止损/止盈/最大持有期。"""
    stop_loss_pct: float       # 止损百分比（负数，如 -3.0 = -3%）
    take_profit_pct: float      # 止盈百分比（正数，如 +8.0 = +8%）
    max_hold_days: int          # 最大持有天数
    position_scale: float = 1.0  # 仓位缩放（暴风暴 x0.3）


@dataclass(frozen=True)
class QualityCheck:
    """策略特定质量标准项。"""
    name: str                   # 检查项名称
    required: bool              # True=硬标准（不过滤掉），False=展示项
    description: str = ""       # 说明


@dataclass(frozen=True)
class StrategyFunnelConfig:
    """策略特定漏斗配置（spec §3.2）。"""
    code: str                                   # first_plate / consecutive_relay / ...
    name: str                                   # 首板挖掘 / 连板接力 / ...
    funnel_type: Literal["limitup", "market_scan"]
    weight_set: str                             # limitup / non_limitup / storm_reversal
    weather_regimes: list[str]                  # 适配天气
    is_primary: bool                            # 天气匹配时是否主跑
    fallback: bool                              # 主跑无候选时是否尝试
    position_params: PositionParams
    quality_standards: list[QualityCheck] = field(default_factory=list)
    note: str = ""
    activation_note: Optional[str] = None  # 激活状态注记，非空表示该战法当前不可用（如"待 S055 激活"）


# ===========================================================================
# 天气-策略推荐（spec §3.3，grill Q7 降级为软标注）
# ===========================================================================

# grill Q7：天气硬开关降级为软标注（暴风雨除外）
# 旧 WEATHER_STRATEGY_MAP 是强约束（不允许的战法直接过滤）
# 新 WEATHER_RECOMMENDATION 是软标注（所有战法可用，天气匹配的标注"推荐"）
# 理由：(1) T-1 天气不代表 T 日天气；(2) §13.0 验证天气路由无统计显著提升；
#       (3) 强约束导致 0 候选比无约束更有害。暴风雨是唯一例外——保留硬约束（仓位=0）。
WEATHER_RECOMMENDATION: dict[str, set[str]] = {
    "晴天":   {"consecutive_relay", "dragon_head", "platform_breakout"},
    "阴天":   {"first_plate", "break_reseal", "end_of_day_sneak"},
    "极端反弹": {"reverse_package"},
    "暴风雨": {"storm_reversal"},  # 唯一硬约束：仓位=0
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
    """grill Q7：天气推荐战法集合（软标注）。暴风雨仍硬约束。

    返回的集合仅用于在候选上标注 weather_recommended=True/False，
    不用于过滤候选（所有战法对所有非暴风雨天气可用）。
    """
    if not weather_state:
        return set()
    return WEATHER_RECOMMENDATION.get(weather_state, set())


def get_strategies_for_weather(weather_state: str | None) -> tuple[list[str], list[str]]:
    """天气 → (主跑策略 codes, fallback 策略 codes)。

    grill Q7：暴风雨仍硬约束（只 storm_reversal）；其他天气返回所有战法
    （不强过滤）。天气推荐集合用 get_weather_recommendation() 查。

    返回的 primary_codes 对非暴风雨天气恒为所有已注册战法（非空），
    fallback 恒为 []。暴风雨返回 (["storm_reversal"], [])。
    """
    if weather_state == "暴风雨":
        return (["storm_reversal"], [])
    # 其他天气：所有战法都可用（不强过滤）
    all_codes = [s.code for s in STRATEGY_FUNNEL_REGISTRY]
    return (all_codes, [])


# ===========================================================================
# 策略注册表
# ===========================================================================

STRATEGY_FUNNEL_REGISTRY: list[StrategyFunnelConfig] = [
    # --- 涨停类（weight_set=limitup）---
    StrategyFunnelConfig(
        code="first_plate",
        name="首板挖掘",
        funnel_type="limitup",
        weight_set="limitup",
        weather_regimes=["阴天", "未知"],
        is_primary=True,
        fallback=False,
        position_params=PositionParams(-3.0, 8.0, 3),
        quality_standards=[
            QualityCheck("开板次数", True, "封板稳定性，反复开板说明抛压大"),
            QualityCheck("封板时间≤10:30", True, "尾盘封板不算首板质量"),
        ],
    ),
    StrategyFunnelConfig(
        code="consecutive_relay",
        name="连板接力",
        funnel_type="limitup",
        weight_set="limitup",
        weather_regimes=["晴天", "未知"],
        is_primary=True,
        fallback=False,
        position_params=PositionParams(-5.0, 12.0, 2),
        quality_standards=[
            QualityCheck("连板数≥2", True, "入场条件（连板接力定义）"),
            QualityCheck("封板率≥80%", True, "封板决心"),
        ],
    ),
    StrategyFunnelConfig(
        code="break_reseal",
        name="炸板回封",
        funnel_type="limitup",
        weight_set="limitup",
        weather_regimes=["阴天", "极端反弹"],
        is_primary=True,
        fallback=False,
        position_params=PositionParams(-3.0, 6.0, 1),
        quality_standards=[
            QualityCheck("开板次数≥1", True, "炸板回封定义需要至少一次开板"),
            QualityCheck("封板率≥80%", True, "回封后封板强度（S053 数据证据统一到 80%）"),
        ],
        note="S053 R3：match 门槛与注册表统一为封板率≥80%（zt_count 3-5 黄金区 89.5% 命中率，19 样本）",
    ),
    StrategyFunnelConfig(
        code="end_of_day_sneak",
        name="尾盘偷袭",
        funnel_type="limitup",
        weight_set="limitup",
        weather_regimes=["阴天"],
        is_primary=True,
        fallback=False,
        position_params=PositionParams(-2.0, 4.0, 1),
        quality_standards=[
            QualityCheck("封板时间>14:30", True, "尾盘专属，早盘封板不算"),
            QualityCheck("量比>2", True, "尾盘急拉需放量"),
        ],
    ),
    StrategyFunnelConfig(
        code="n_shape_counterattack",
        name="N字反击",
        funnel_type="limitup",
        weight_set="limitup",
        weather_regimes=["晴天", "极端反弹"],
        is_primary=False,
        fallback=True,
        position_params=PositionParams(-3.0, 8.0, 3),
        quality_standards=[
            QualityCheck("2日内涨停", True, "N字形态需要前置涨停"),
        ],
        note="归入涨停类权重集（spec §4.4）",
    ),
    # --- 非涨停类（weight_set=non_limitup）---
    StrategyFunnelConfig(
        code="low_absorption",
        name="低吸龙头",
        funnel_type="market_scan",
        weight_set="non_limitup",
        weather_regimes=["晴天", "阴天"],
        is_primary=False,
        fallback=True,
        position_params=PositionParams(-5.0, 10.0, 5),
        quality_standards=[
            QualityCheck("回调至MA5", True, "低吸入场点"),
        ],
    ),
    StrategyFunnelConfig(
        code="reverse_package",
        name="反包战法",
        funnel_type="market_scan",
        weight_set="non_limitup",
        weather_regimes=["极端反弹"],
        is_primary=True,
        fallback=False,
        position_params=PositionParams(-3.0, 6.0, 1),
        quality_standards=[
            QualityCheck("T-1未涨停", True, "反包定义"),
            QualityCheck("成交额>15亿", True, "反包需流动性"),
            QualityCheck("均线多头", False, "加分项"),
        ],
        activation_note="待 S055 激活（seal_intraday.db 无 open_count>=2 数据）",
    ),
    StrategyFunnelConfig(
        code="platform_breakout",
        name="平台突破",
        funnel_type="market_scan",
        weight_set="non_limitup",
        weather_regimes=["晴天"],
        is_primary=True,
        fallback=False,
        position_params=PositionParams(-5.0, 12.0, 7),
        quality_standards=[
            QualityCheck("横盘≥5日", True, "平台定义"),
            QualityCheck("成交额放大2倍", True, "突破放量"),
        ],
    ),
    StrategyFunnelConfig(
        code="dragon_head",
        name="龙头战法",
        funnel_type="market_scan",
        weight_set="non_limitup",
        weather_regimes=["晴天", "阴天"],
        is_primary=True,
        fallback=False,
        position_params=PositionParams(-5.0, 15.0, 5),
        quality_standards=[
            QualityCheck("板块领涨", True, "龙头定义"),
            QualityCheck("换手>5%", True, "龙头活跃度"),
        ],
    ),
    # --- 暴风雨逆势涨停子策略 ---
    StrategyFunnelConfig(
        code="storm_reversal",
        name="暴风雨逆势涨停",
        funnel_type="limitup",
        weight_set="storm_reversal",
        weather_regimes=["暴风雨"],
        is_primary=True,
        fallback=False,
        position_params=PositionParams(-3.0, 10.0, 1, position_scale=0.3),  # 仓位 x0.3
        quality_standards=[
            QualityCheck("封板时间≤10:30", True, "暴风雨天尾盘涨停不算逆势"),
        ],
        note="暴风雨天唯一主跑策略，仓位 x0.3（环境极端）",
    ),
]


def get_strategy_config(code: str) -> StrategyFunnelConfig | None:
    """按 code 查策略配置。"""
    return next((s for s in STRATEGY_FUNNEL_REGISTRY if s.code == code), None)


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

    factors: {factor_name: value}（来自 gene_scores）
    weight_set: "limitup" / "non_limitup" / "storm_reversal"
    返回 (score, breakdown)。

    spec §4.1 涨停类：
        score = Σ(factor_value [× reverse ? (100-x) : x] × weight)
    反向因子（premium/freq）用 (100-value) 反转。

    权重加载失败 → 等权兜底（标注 fallback）。
    """
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

    total = 0.0
    breakdown = {}
    for factor_name, w_info in weights.items():
        w = w_info.get("weight", 0)
        reverse = w_info.get("reverse", False)
        val = factors.get(factor_name, 0)
        if reverse:
            val = 100 - val
        contribution = val * w
        total += contribution
        breakdown[factor_name] = round(contribution, 4)

    return round(total, 4), breakdown


def _cand_to_gene(cand: dict):
    """dict 候选 → GeneScore 适配（grill Q6：match_strategies 需要 GeneScore）。

    字段映射经 limitup_screener/models.py:33 GeneScore 定义核实。
    factors 优先取 cand["factors"]；total_score/zt_count_250d 同时回退到 factors 内同名键。
    wilson_adjusted/qualify/high_gene/last_zt_dates 用安全默认值——
    match_strategies 只读 total_score/factors/zt_count_250d/code，不读这几项。
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


def score_candidates(
    candidates: list[dict],
    weather_state: str | None,
    trade_date: str | None = None,
) -> list[dict]:
    """天气硬开关 + 策略分排序 → 候选列表。

    candidates: [{code, name, factors: {seal_rate, premium, ...}, ...}]
    返回：[{code, name, strategy_code, strategy_name, score, breakdown, ...}]

    trade_date: S073 §9.4 游资席位画像接线（可选）；传则 batch 取当日龙虎榜 + per-cand
    compute_seat_risk_factor 修饰策略分（画像未建→modifier 1.0 降级标注）；不传则不接。

    流程（spec §3.1）：
    1. 天气 → 主跑策略组 + fallback
    2. 每个主跑策略用其 weight_set 计算策略分
    3. 按策略分降序排序
    4. fallback 策略仅在主跑无候选时尝试（本函数返回主跑结果，fallback 由调用方决定）

    grill Q6（match 过滤闭环）：对每个候选×策略，先调
    limitup_strategy.match_strategies 检查是否满足入场条件；不满足则该策略
    不打分、不返回。避免前端看到"算分了但不满足入场条件"的脏数据。
    """
    primary_codes, _ = get_strategies_for_weather(weather_state)
    # grill Q7：非暴风雨天气 primary_codes 恒为所有已注册战法（非空），
    # 暴风雨恒为 ["storm_reversal"]；不再需要未知降级 fallback。
    # 天气推荐集合（软标注）——用于在候选上标 weather_recommended=True/False，
    # 不用于过滤候选。
    recommendation = get_weather_recommendation(weather_state)

    # S073 §9.4 游资席位画像接线（batch billboard + profiles；画像未建→load_aggregate_profiles 返空→modifier 1.0 降级）
    seat_profiles = None
    billboard = None
    if trade_date:
        try:
            from strategies.hot_money_seats import compute_seat_risk_factor, load_aggregate_profiles, fetch_billboard_for_date
            seat_profiles = load_aggregate_profiles()
            billboard = fetch_billboard_for_date(trade_date)
        except Exception:
            seat_profiles = None
            billboard = None

    scored: list[dict] = []
    # match_strategies 实际处理入场条件的策略 code 集合（取自 limitup_strategy.STRATEGY_REGISTRY
    # 的 if/elif 分支覆盖）。dragon_head 在 registry 但无 match 分支；storm_reversal
    # 不在 registry。这两个策略无入场条件可过滤，按"无条件"处理（不阻断），避免
    # 晴天(dragon_head 主跑)/暴风雨(storm_reversal 独跑)被 match 闭环误杀成永远空集。
    _MATCHED_STRATEGY_CODES = {
        "first_plate", "consecutive_relay", "break_reseal", "low_absorption",
        "reverse_package", "n_shape_counterattack", "platform_breakout",
        "end_of_day_sneak",
    }
    for cand in candidates:
        factors = cand.get("factors", {})
        # grill Q6：dict → GeneScore 适配（match_strategies 的入参类型）
        gene = _cand_to_gene(cand)
        # 延迟 import：limitup_strategy 顶层 import astock，避免本模块加载时
        # 强制拉起 astock 依赖链（测试/conftest 与 forward_test 已含 backend 于 sys.path）
        from limitup_strategy import match_strategies
        # 对每只候选一次性算出所有命中的战法 signals，内循环按 strat_code 查表
        try:
            signals = match_strategies(cand.get("code", ""), gene)
            matched_codes = {s.strategy_code for s in signals}
        except Exception:
            matched_codes = set()  # match 失败按"不命中"处理，不阻断整体打分
        for strat_code in primary_codes:
            cfg = get_strategy_config(strat_code)
            if cfg is None:
                continue
            # 暴风雨逆势只取暴风雨日涨停股（spec §3.2）
            if cfg.code == "storm_reversal" and weather_state != "暴风雨":
                continue
            # grill Q6：match 过滤——不满足入场条件的候选×策略不打分、不返回。
            # 仅对 match_strategies 有入场条件分支的策略过滤；无分支的策略
            # （dragon_head/storm_reversal）按"无条件"放行，避免误杀。
            if strat_code in _MATCHED_STRATEGY_CODES and strat_code not in matched_codes:
                continue
            score, breakdown = compute_strategy_score(factors, cfg.weight_set)
            # S073 §9.4 游资画像修饰（画像未建→modifier 1.0 不扣分，标 risk_label）
            seat_risk = None
            if trade_date and billboard is not None:
                try:
                    seat_risk = compute_seat_risk_factor(cand.get("code", ""), trade_date, seat_profiles, None, billboard)
                    score = round(score * seat_risk.score_modifier, 4)
                except Exception:
                    seat_risk = None
            scored.append({
                **cand,
                "strategy_code": cfg.code,
                "strategy_name": cfg.name,
                "strategy_score": score,
                "score_breakdown": breakdown,
                "funnel_type": cfg.funnel_type,
                "position_params": cfg.position_params,
                "weather_recommended": strat_code in recommendation,  # grill Q7：天气推荐标注（软标注）
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
