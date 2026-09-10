# -*- coding: utf-8 -*-
"""推荐引擎 —— 基因得分 → 推荐等级 → 仓位建议（教育研究式口吻）。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List

from limitup_screener import GeneScore, get_screener_result, GENE_HIGH_THRESHOLD, GENE_QUALIFY_THRESHOLD
from limitup_sti import get_sti_engine
from config import default_config


class RecommendationLevel(str, Enum):
    """推荐等级 — 基于基因得分的教育研究式分级。"""
    HIGH_QUALITY = "高质量关注"
    MEDIUM_QUALITY = "中等质量关注"
    LOW_QUALITY = "低质量关注"
    AVOID = "策略逻辑上回避"


# AVOID 触发条件（量化判定，避免主观判断）
AVOID_CONDITIONS = {
    "seal_break_streak": 3,         # 近3日连续炸板（≥3次炸板）
    "gene_score_decay_pct": 30,     # 基因得分连续5日衰减 ≥ 30%
    "open_premium_negative_avg": -3, # 近5日平均开盘溢价 < -3%
    "extreme_sti_phase": ["冰点"],   # STI处于冰点阶段时整体回避
}

# 仓位建议百分比（研究参考，非交易指令）
POSITION_SUGGESTIONS = {
    RecommendationLevel.HIGH_QUALITY: {"research_position": "10-15%", "logic": "基因得分高，历史统计表现优秀"},
    RecommendationLevel.MEDIUM_QUALITY: {"research_position": "5-10%", "logic": "基因得分中等，需结合其他因素"},
    RecommendationLevel.LOW_QUALITY: {"research_position": "0-5%", "logic": "基因得分低，仅作观察"},
    RecommendationLevel.AVOID: {"research_position": "0%", "logic": "触发AVOID量化条件，历史统计特征极差"},
}


@dataclass
class StockRecommendation:
    """个股推荐结果（教育研究式，非交易建议）。"""
    code: str
    name: str
    gene_score: float
    industry_normalized: float
    level: RecommendationLevel
    position_suggestion: str
    reasoning: List[str]
    risk_notes: List[str]
    factor_breakdown: dict


def _check_avoid_conditions(gene: GeneScore, sti_phase: str | None) -> tuple[bool, str]:
    """检查是否触发 AVOID 条件。"""
    # STI 冰点回避
    if sti_phase in AVOID_CONDITIONS["extreme_sti_phase"]:
        return True, f"STI处于{sti_phase}阶段，历史统计特征显示该阶段整体胜率偏低"

    # 基因得分连续衰减（简化：当前得分 vs Wilson调整后得分）
    decay_pct = (gene.wilson_adjusted - gene.total_score) / max(gene.total_score, 1) * 100
    if decay_pct >= AVOID_CONDITIONS["gene_score_decay_pct"]:
        return True, f"基因得分衰减{decay_pct:.1f}%，超过{AVOID_CONDITIONS['gene_score_decay_pct']}%阈值"

    # 炸板率过高（简化：用封板率反向判断）
    seal_rate = gene.factors.get("封板率", 100)
    if seal_rate < 30:
        return True, f"封板率仅{seal_rate:.1f}%，涨停稳固性不足"

    return False, ""


def _build_reasoning(gene: GeneScore, level: RecommendationLevel) -> List[str]:
    """生成推荐理由（教育性表述）。"""
    reasons: List[str] = []

    if level == RecommendationLevel.HIGH_QUALITY:
        reasons.append(f"从历史统计角度看，该标的基因得分为{gene.total_score}，属于较高水平")
        reasons.append("历史统计特征显示，高基因股票在涨停后次日溢价的概率较高")
        if gene.factors.get("次日溢价率", 0) > 60:
            reasons.append(f"次日溢价率因子表现较好({gene.factors['次日溢价率']:.1f}%)")
        if gene.factors.get("封板率", 0) > 60:
            reasons.append(f"封板率因子表现较好({gene.factors['封板率']:.1f}%)")
    elif level == RecommendationLevel.MEDIUM_QUALITY:
        reasons.append(f"从历史统计角度看，该标的基因得分为{gene.total_score}，处于中等区间")
        reasons.append("历史统计特征显示，该类股票具备一定的涨停后溢价能力，但需结合其他因素综合评估")
    elif level == RecommendationLevel.LOW_QUALITY:
        reasons.append(f"从历史统计角度看，该标的基因得分为{gene.total_score}，低于合格阈值")
        reasons.append("历史统计特征显示，该类股票的涨停后溢价概率相对较低，建议仅作观察")
    else:
        reasons.append("该标的触发多项量化回避条件")
        reasons.append("从历史统计角度看，当前参与的风险收益比不佳")

    return reasons


def _build_risk_notes(gene: GeneScore, level: RecommendationLevel) -> List[str]:
    """生成风险提示。"""
    notes: List[str] = []

    if gene.factors.get("炸板后溢价", 0) < 0:
        notes.append("炸板后溢价因子为负，历史统计显示炸板后次日表现偏弱")

    if gene.factors.get("涨停频次", 0) < 20:
        notes.append("涨停频次较低，历史统计显示资金关注度一般")

    if level in (RecommendationLevel.LOW_QUALITY, RecommendationLevel.AVOID):
        notes.append("基因得分偏低，历史统计特征显示上涨概率相对较低")

    if not notes:
        notes.append("仍需关注市场整体情绪变化及个股资金流动态")

    return notes


async def get_recommendation(code: str, date: str | None = None) -> StockRecommendation | None:
    """获取个股推荐（教育研究式，非交易建议）。"""
    result = await get_screener_result(date)
    if not result or not result.gene_scores:
        return None

    gene = None
    for g in result.gene_scores:
        if g.code == code:
            gene = g
            break

    if gene is None:
        return None

    # 获取 STI 阶段
    sti_phase = None
    try:
        engine = get_sti_engine()
        db = engine._get_db()
        row = db.execute(
            "SELECT phase FROM sti_timeline WHERE phase IS NOT NULL ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if row:
            sti_phase = row["phase"]
    except Exception:
        pass

    # 检查 AVOID 条件
    avoid, reason = _check_avoid_conditions(gene, sti_phase)
    if avoid:
        level = RecommendationLevel.AVOID
    elif gene.total_score >= default_config.RECOMMEND_HIGH_THRESHOLD:
        level = RecommendationLevel.HIGH_QUALITY
    elif gene.total_score >= default_config.RECOMMEND_MEDIUM_THRESHOLD:
        level = RecommendationLevel.MEDIUM_QUALITY
    else:
        level = RecommendationLevel.LOW_QUALITY

    # 行业归一化（简化：以当前得分作为相对表现，实际应计算行业中位数）
    industry_normalized = min(gene.total_score, 100.0)

    # 仓位建议
    pos = POSITION_SUGGESTIONS.get(level, {"research_position": "0%", "logic": ""})
    position_suggestion = pos["research_position"]

    # 理由与风险
    reasoning = _build_reasoning(gene, level)
    risk_notes = _build_risk_notes(gene, level)

    return StockRecommendation(
        code=code,
        name=gene.name,
        gene_score=gene.total_score,
        industry_normalized=industry_normalized,
        level=level,
        position_suggestion=position_suggestion,
        reasoning=reasoning,
        risk_notes=risk_notes,
        factor_breakdown=gene.factors,
    )


async def get_today_recommendations(limit: int = 20) -> List[StockRecommendation]:
    """获取当日推荐清单（含 LOW_QUALITY 观察池）。"""
    result = await get_screener_result()
    if not result or not result.gene_scores:
        return []

    recs: List[StockRecommendation] = []
    for g in result.gene_scores:
        rec = await get_recommendation(g.code, result.date)
        if rec:
            recs.append(rec)

    # 按基因得分降序
    recs.sort(key=lambda r: r.gene_score, reverse=True)
    return recs[:limit]


# ===========================================================================
# S175 R9 — 多臂推荐（honest_label + 读 PaperPortfolio.equity() sizing，R9↔R10 接线 SH1）
# ===========================================================================
# 诚实承认：当前仅 floor 1 臂 actionable，breakout/limitup/trend/gap 返静态 honest_label
# 卡非动态信号——为 1 actionable 臂建多臂框架是用户拉回的取舍，3/4 槽位是空标签（留插槽
# 等 conditioning harness）。gene-only legacy（上方）§44 falsified，保留但标证否。

from enum import Enum


class ArmHonestLabel(str, Enum):
    """多臂诚实标签（grill C7：falsified ≠ weak ≠ 待复验）。"""
    EXTERNALLY_VALIDATED = "externally_validated"  # 外部文献验证（floor 红利低波 9-12% 三重定论，非本系统 §44）
    SECTION44_FALSIFIED = "§44_falsified"  # §44 证否（breakout selection 无 edge）
    MOCK_NOT_READY = "mock_not_ready"  # signal 生成器未建（limitup/trend）
    DEAD_ARM = "dead_arm"  # falsified dead（gap，不推荐）


#: floor-heavy ETF 配比（spec §5.4 portfolio overlay deferred，取下限 50%）
FLOOR_ALLOCATION: float = 0.5


@dataclass
class MultiArmRecommendation:
    """多臂推荐结果——各臂 honest_label + sizing（floor actionable 读 equity）。"""
    arm: str
    honest_label: ArmHonestLabel
    action_type: str  # "batch_buy" | "paper_track" | "none"
    code: str | None = None
    name: str | None = None
    sizing_suggestion: str | None = None
    coverage_rate: float | None = None
    days_tracked: int | None = None
    validated: bool = False
    note: str = ""


def get_multi_arm_recommendations(
    paper_portfolio: "object | None" = None,
    journal: "object | None" = None,
) -> List[MultiArmRecommendation]:
    """多臂推荐——各臂 honest_label，floor actionable + 读 PaperPortfolio.equity() sizing。

    R9↔R10 接线（SH1 fix）：floor 仓位 sizing 读 PaperPortfolio.equity()（非空转）。
    breakout=§44_falsified 非 weak signal 非 underpowered_tracking（grill C7）。
    gap dead_arm 不推荐（gate）。limitup/trend mock_not_ready。
    """
    from engine.paper_portfolio import PaperPortfolio  # noqa: PLC0415
    from engine.trade_journal import TradeJournal  # noqa: PLC0415

    pp = paper_portfolio or PaperPortfolio()
    tj = journal or TradeJournal()
    equity = pp.equity()
    recs: List[MultiArmRecommendation] = []

    # floor：ETF 512890 批次计划（actionable，externally_validated）+ equity sizing
    try:
        from strategies.index_replication_floor import (  # noqa: PLC0415
            build_position_batches, ETF_CODE,
        )
        batches = build_position_batches(one_shot=True)
        n_batches = max(len(batches), 1)
        # S180 R4: floor_size 读 PaperPortfolio.final_size 含 lift cap（floor N/A→1.0，接口接线）
        floor_gross = equity * FLOOR_ALLOCATION
        floor_size = pp.final_size("floor", floor_gross / n_batches)
        recs.append(MultiArmRecommendation(
            arm="floor", honest_label=ArmHonestLabel.EXTERNALLY_VALIDATED,
            action_type="batch_buy", code=ETF_CODE, name="红利低波 ETF",
            sizing_suggestion=f"每批 ≈{floor_size:.0f} CNY（equity {equity:.0f} × {FLOOR_ALLOCATION} / {n_batches} 批）",
            coverage_rate=1.0, validated=True,
            note="外部三重定论 9-12%（学术+卖方+指数），非本系统 §44 验证；长线 buy+hold",
        ))
    except Exception as e:  # noqa: BLE001
        recs.append(MultiArmRecommendation(
            arm="floor", honest_label=ArmHonestLabel.MOCK_NOT_READY,
            action_type="none", note=f"floor 未就绪: {e}",
        ))

    # breakout：§44_falsified paper-only（不推荐真金）
    try:
        agg = tj.aggregate_by_arm()
        bo_stats = agg.get("breakout", {})
        recs.append(MultiArmRecommendation(
            arm="breakout", honest_label=ArmHonestLabel.SECTION44_FALSIFIED,
            action_type="paper_track",
            coverage_rate=bo_stats.get("coverage_rate") if isinstance(bo_stats, dict) else None,
            days_tracked=bo_stats.get("n_days", 0) if isinstance(bo_stats, dict) else 0,
            validated=False,
            note="§44 selection 已证否（S168 12 harness 全 falsified）无 selection edge；"
                 "盘中 conditioning 未测——paper tracking 非 weak 非 underpowered_tracking",
        ))
    except Exception as e:  # noqa: BLE001
        recs.append(MultiArmRecommendation(
            arm="breakout", honest_label=ArmHonestLabel.SECTION44_FALSIFIED,
            action_type="paper_track", note=f"stats 不可得: {e}",
        ))

    # limitup/trend：mock_not_ready
    for arm in ("limitup", "trend"):
        recs.append(MultiArmRecommendation(
            arm=arm, honest_label=ArmHonestLabel.MOCK_NOT_READY,
            action_type="none", validated=False,
            note=f"{arm} signal 生成器未建（mock_entry=10.0 硬编），等 conditioning harness",
        ))

    # gap：dead_arm（不推荐）
    recs.append(MultiArmRecommendation(
        arm="gap", honest_label=ArmHonestLabel.DEAD_ARM,
        action_type="none", validated=False,
        note="gap §44 falsified（成本假象 net -0.48% t=-3.79），is_dead_arm=1 不推荐；"
             "审计走 tools/s44_gap_run_60d.py",
    ))

    return recs
