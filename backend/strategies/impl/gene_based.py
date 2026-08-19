# -*- coding: utf-8 -*-
"""S086 B1：只读 gene 因子的 7+1 个简单战法（gene_based）。

战法：first_plate / consecutive_relay / break_reseal / low_absorption /
n_shape_counterattack / platform_breakout / end_of_day_sneak / dragon_head。

match 条件/阈值/confidence 严格按 limitup_strategy.py:725-816 既有分支迁移，不改阈值。
low_absorption 在旧 STRATEGY_REGISTRY（dict）与 STRATEGY_FUNNEL_REGISTRY（dataclass）
均有注册且 match 分支存在（:754-761），spec A2 要求合并后 12 项，故归入本文件
（implementation-prompt B1 的"7 个"为 off-by-one 遗漏，详见 S086 核实记录）。
"""
from __future__ import annotations

from strategies.strategy_base import BaseStrategy, ConditionMatch


class FirstPlateStrategy(BaseStrategy):
    """首板挖掘：score≥60 ∧ 涨停频次>20，confidence=动态 score/100。"""

    code = "first_plate"
    name = "首板挖掘"

    def match(self, ctx) -> list[ConditionMatch]:
        gene = ctx.gene
        if gene.total_score >= 60 and gene.factors.get("涨停频次", 0) > 20:
            return [ConditionMatch(
                condition="首次涨停+基因合格",
                value=f"基因得分 {gene.total_score}",
                description="策略逻辑上，该股符合首板挖掘的基因门槛",
            )]
        return []

    def compute_confidence(self, matches, ctx) -> float:
        return min(ctx.gene.total_score / 100, 1.0)


class ConsecutiveRelayStrategy(BaseStrategy):
    """连板接力：zt≥2 ∧ 封板率≥60%，confidence=动态 封板率/100。"""

    code = "consecutive_relay"
    name = "连板接力"

    def match(self, ctx) -> list[ConditionMatch]:
        gene = ctx.gene
        if gene.zt_count_250d >= 2 and gene.factors.get("封板率", 0) >= 60:
            return [ConditionMatch(
                condition="连板+封板强度",
                value=f"涨停次数 {gene.zt_count_250d}",
                description="策略逻辑上，该股具备连板接力的历史统计特征",
            )]
        return []

    def compute_confidence(self, matches, ctx) -> float:
        return min(ctx.gene.factors.get("封板率", 0) / 100, 1.0)


class BreakResealStrategy(BaseStrategy):
    """炸板回封：3≤zt≤5 ∧ 封板率≥80%，confidence=固定 0.7（S053 黄金区）。"""

    code = "break_reseal"
    name = "炸板回封"

    def match(self, ctx) -> list[ConditionMatch]:
        gene = ctx.gene
        # S053 R3：match 改 zt_count_250d 黄金区 [3,5] + 封板率>=80
        # 数据证据：zt_count 3-5 区间 89.5% 命中率（19 条样本），6+ 衰减，11+ 反亏
        seal = gene.factors.get("封板率", 0)
        if 3 <= gene.zt_count_250d <= 5 and seal >= 80:
            return [ConditionMatch(
                condition="炸板回封+历史封板能力",
                value=f"zt_count_250d={gene.zt_count_250d} 封板率{seal:.1f}%",
                description=(
                    f"策略逻辑上，该股 250 日涨停 {gene.zt_count_250d} 次"
                    f"（黄金区 3-5），历史封板能力强且未过劳"
                ),
            )]
        return []

    def compute_confidence(self, matches, ctx) -> float:
        return 0.7


class LowAbsorptionStrategy(BaseStrategy):
    """低吸龙头：score≥65 ∧ 溢价率>50%，confidence=固定 0.5。"""

    code = "low_absorption"
    name = "低吸龙头"

    def match(self, ctx) -> list[ConditionMatch]:
        gene = ctx.gene
        premium = gene.factors.get("次日溢价率", 0)
        if gene.total_score >= 65 and premium > 50:
            return [ConditionMatch(
                condition="龙头回调+资金关注",
                value=f"次日溢价率 {premium:.1f}%",
                description="策略逻辑上，该股属于高关注度标的，存在回调低吸机会",
            )]
        return []

    def compute_confidence(self, matches, ctx) -> float:
        return 0.5


class NShapeCounterattackStrategy(BaseStrategy):
    """N字反击：2≤zt≤10，confidence=固定 0.5（S053 移除矛盾门槛）。"""

    code = "n_shape_counterattack"
    name = "N字反击"

    def match(self, ctx) -> list[ConditionMatch]:
        gene = ctx.gene
        # S053 修复：移除矛盾的"涨停频次>30"门槛（与 zt_count_250d<=10 互斥）
        if 2 <= gene.zt_count_250d <= 10:
            return [ConditionMatch(
                condition="N字形态+放量",
                value=f"zt_count_250d={gene.zt_count_250d}",
                description=(
                    f"策略逻辑上，该股 250 日涨停 {gene.zt_count_250d} 次"
                    f"（[2,10] 区间，有过涨停历史但未过频），呈现 N 字反击的历史统计特征"
                ),
            )]
        return []

    def compute_confidence(self, matches, ctx) -> float:
        return 0.5


class PlatformBreakoutStrategy(BaseStrategy):
    """平台突破：score≥60 ∧ 涨停频次>40，confidence=固定 0.5。"""

    code = "platform_breakout"
    name = "平台突破"

    def match(self, ctx) -> list[ConditionMatch]:
        gene = ctx.gene
        if gene.total_score >= 60 and gene.factors.get("涨停频次", 0) > 40:
            return [ConditionMatch(
                condition="平台整理+突破",
                value=f"基因得分 {gene.total_score}",
                description="策略逻辑上，该股具备平台突破的量价特征",
            )]
        return []

    def compute_confidence(self, matches, ctx) -> float:
        return 0.5


class EndOfDaySneakStrategy(BaseStrategy):
    """尾盘偷袭：封板率≥40% ∧ 溢价率>40%，confidence=固定 0.4。"""

    code = "end_of_day_sneak"
    name = "尾盘偷袭"

    def match(self, ctx) -> list[ConditionMatch]:
        gene = ctx.gene
        seal = gene.factors.get("封板率", 0)
        if seal >= 40 and gene.factors.get("次日溢价率", 0) > 40:
            return [ConditionMatch(
                condition="尾盘封板",
                value=f"封板率 {seal:.1f}%",
                description="策略逻辑上，该股存在尾盘偷袭的统计特征",
            )]
        return []

    def compute_confidence(self, matches, ctx) -> float:
        return 0.4


class DragonHeadStrategy(BaseStrategy):
    """龙头战法：无条件放行（spec B1.7/§5.4，match 返回单条"无条件"+ confidence=0.5）。

    旧 match_strategies 无 dragon_head 分支（永不命中，backtest sample_size=0），
    spec §2.1 将"无 match 条件"列为 bug 不是设计；本实现显式无条件放行，
    令 score_candidates 的 dragon_head 过滤豁免与 dispatch 输出一致。
    """

    code = "dragon_head"
    name = "龙头战法"

    def match(self, ctx) -> list[ConditionMatch]:
        return [ConditionMatch(
            condition="无条件放行",
            value="龙头战法",
            description="策略逻辑上，该股作为板块龙头，具备龙头战法的统计特征（无条件放行）",
        )]

    def compute_confidence(self, matches, ctx) -> float:
        return 0.5
