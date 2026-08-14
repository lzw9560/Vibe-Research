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
from typing import Literal

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


# ===========================================================================
# 天气-策略硬开关（spec §3.3）
# ===========================================================================

WEATHER_STRATEGY_MAP: dict[str, list[str]] = {
    "晴天":   ["consecutive_relay", "dragon_head", "platform_breakout"],
    "阴天":   ["first_plate", "break_reseal", "end_of_day_sneak"],
    "极端反弹": ["reverse_package", "break_reseal", "n_shape_counterattack"],
    "暴风雨": ["storm_reversal"],   # 逆势涨停子策略，仓位 x0.3
    "未知":   ["first_plate", "consecutive_relay"],  # 保守降级
}

FALLBACK_STRATEGIES: dict[str, list[str]] = {
    "晴天":   ["low_absorption"],
    "阴天":   ["low_absorption"],
    "极端反弹": [],
    "暴风雨": [],   # 暴风雨无 fallback——空仓也是策略
    "未知":   [],
}


def get_strategies_for_weather(weather_state: str | None) -> tuple[list[str], list[str]]:
    """天气硬开关：返回 (主跑策略 codes, fallback 策略 codes)。

    weather_state 为 None/未知 → 保守降级（首板+连板）。
    """
    if not weather_state or weather_state not in WEATHER_STRATEGY_MAP:
        weather_state = "未知"
    primary = WEATHER_STRATEGY_MAP.get(weather_state, [])
    fallback = FALLBACK_STRATEGIES.get(weather_state, [])
    return primary, fallback


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
            QualityCheck("封板率≥60%", True, "回封后封板强度"),
        ],
        note="60日无信号：炸板后溢价因子疑似缺供（S053 查因中）",
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


def score_candidates(
    candidates: list[dict],
    weather_state: str | None,
) -> list[dict]:
    """天气硬开关 + 策略分排序 → 候选列表。

    candidates: [{code, name, factors: {seal_rate, premium, ...}, ...}]
    返回：[{code, name, strategy_code, strategy_name, score, breakdown, ...}]

    流程（spec §3.1）：
    1. 天气 → 主跑策略组 + fallback
    2. 每个主跑策略用其 weight_set 计算策略分
    3. 按策略分降序排序
    4. fallback 策略仅在主跑无候选时尝试（本函数返回主跑结果，fallback 由调用方决定）
    """
    primary_codes, _ = get_strategies_for_weather(weather_state)
    if not primary_codes:
        primary_codes = WEATHER_STRATEGY_MAP["未知"]

    scored: list[dict] = []
    for cand in candidates:
        factors = cand.get("factors", {})
        for strat_code in primary_codes:
            cfg = get_strategy_config(strat_code)
            if cfg is None:
                continue
            # 暴风雨逆势只取暴风雨日涨停股（spec §3.2）
            if cfg.code == "storm_reversal" and weather_state != "暴风雨":
                continue
            score, breakdown = compute_strategy_score(factors, cfg.weight_set)
            scored.append({
                **cand,
                "strategy_code": cfg.code,
                "strategy_name": cfg.name,
                "strategy_score": score,
                "score_breakdown": breakdown,
                "funnel_type": cfg.funnel_type,
                "position_params": cfg.position_params,
            })

    scored.sort(key=lambda x: x.get("strategy_score", 0), reverse=True)
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
