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

from strategies.strategy_base import BaseStrategy, ConditionMatch, ConditionEval, StrategyMatchResult


def _get_pattern(ctx):
    """S094 R4 辅助：从 ctx.market_scan_ctx 取 PatternScan（S1 阶段涨停 pipeline 无此字段，None 降级）。"""
    msc = getattr(ctx, "market_scan_ctx", None)
    if not msc:
        return None
    return msc.get("pattern") if isinstance(msc, dict) else None


class FirstPlateStrategy(BaseStrategy):
    """首板挖掘：score≥60 ∧ 涨停频次>20，confidence=动态 score/100。"""

    code = "first_plate"
    name = "首板挖掘"

    def match(self, ctx) -> StrategyMatchResult:
        # S097：拆 C1 基因合格 + C2 涨停频次，返 StrategyMatchResult（全量条件三态）
        gene = ctx.gene
        freq = gene.factors.get("涨停频次", 0)
        c1_hit = gene.total_score >= 60
        c2_hit = freq > 20
        conditions = [
            ConditionEval(
                condition_id="first_plate.c1",
                condition_name="基因得分合格",
                factor="total_score",
                threshold=">= 60",
                actual_value=str(gene.total_score),
                state="hit" if c1_hit else "miss",
                description=f"基因得分 {gene.total_score}（阈值≥60）",
            ),
            ConditionEval(
                condition_id="first_plate.c2",
                condition_name="涨停频次达标",
                factor="涨停频次",
                threshold="> 20",
                actual_value=str(freq),
                state="hit" if c2_hit else "miss",
                description=f"涨停频次 {freq}（阈值>20）",
            ),
        ]
        hit_count = sum(1 for c in conditions if c.state == "hit")
        fired = c1_hit and c2_hit
        return StrategyMatchResult(
            strategy_code=self.code,
            strategy_name=self.name,
            conditions=conditions,
            hit_count=hit_count,
            total_count=len(conditions),
            fired=fired,
            fire_rule="全条件命中",
            confidence=min(gene.total_score / 100, 1.0) if fired else None,
            data_ok=True,
        )

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
    """低吸龙头：ma5_proximity≤3（回调至MA5）∧ ma_bullish（多头），confidence=固定 0.5。

    S094 R10/T14：改读 PatternScan（不读 gene.total_score/次日溢价率）。阈值 ma5_proximity≤3
    与 check_quality_standards "回调至MA5"（close-MA5/MA5*100<3）一致；探索性，待回测调参。
    无 market_scan_ctx（limitup/match_strategies 路径）→ 不命中（R9 行为变化）。
    """

    code = "low_absorption"
    name = "低吸龙头"

    def match(self, ctx) -> list[ConditionMatch]:
        # S094 R10/T14：改读 PatternScan（ma5_proximity 回调至MA5 + ma_bullish 多头），不读 gene 因子
        pattern = _get_pattern(ctx)
        if pattern is None:
            return []
        ma5_prox = pattern.ma5_proximity
        ma_bull = pattern.ma_bullish
        if ma5_prox is None or ma5_prox > 3 or not ma_bull:
            return []
        return [ConditionMatch(
            condition="回调至MA5+均线多头",
            value=f"ma5_proximity={ma5_prox:.2f}%",
            description=f"策略逻辑上，股价回调至 5 日线附近（接近度 {ma5_prox:.2f}%，≤3%）且均线多头排列，存在低吸机会",
        )]

    def compute_confidence(self, matches, ctx) -> float:
        return 0.5

    def compute_volume_signal(self, ctx) -> bool | None:
        """S094 R4：低吸龙头成交额 > 5亿（spec §3.R4）。"""
        pattern = _get_pattern(ctx)
        if pattern is None or pattern.amount_yi is None:
            return None
        return pattern.amount_yi > 5


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
    """平台突破：consolidation_days≥5（横盘）∧ volume_breakout_ratio>2（放量突破），confidence=固定 0.5。

    S094 R10/T14：改读 PatternScan（不读 gene.total_score/涨停频次）。阈值横盘≥5 + 量比>2
    与 check_quality_standards "横盘≥5日"/"成交额放大2倍" 一致；探索性，待回测调参。
    无 market_scan_ctx（limitup/match_strategies 路径）→ 不命中（R9 行为变化）。
    """

    code = "platform_breakout"
    name = "平台突破"

    def match(self, ctx) -> list[ConditionMatch]:
        # S094 R10/T14：改读 PatternScan（consolidation_days 横盘≥5 + volume_breakout_ratio 放量>2），不读 gene 因子
        pattern = _get_pattern(ctx)
        if pattern is None:
            return []
        cons = pattern.consolidation_days
        vol_brk = pattern.volume_breakout_ratio
        if cons is None or cons < 5 or vol_brk is None or vol_brk <= 2:
            return []
        return [ConditionMatch(
            condition="横盘+放量突破",
            value=f"横盘{cons}日 量比{vol_brk:.2f}",
            description=f"策略逻辑上，横盘 {cons} 日（≥5）后今日放量突破（量比 {vol_brk:.2f}，>2）",
        )]

    def compute_confidence(self, matches, ctx) -> float:
        return 0.5

    def compute_volume_signal(self, ctx) -> bool | None:
        """S094 R4：平台突破 volume_breakout_ratio > 2（spec §3.R4）。"""
        pattern = _get_pattern(ctx)
        if pattern is None or pattern.volume_breakout_ratio is None:
            return None
        return pattern.volume_breakout_ratio > 2


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
    """龙头战法：板块内领涨（S094 R9 条件化——读 market_scan_ctx.sector_rank≤3 命中）。

    旧 S086 无条件放行（backtest sample_size=1）；S094 R9 删无条件放行：
    读 market_scan_ctx.sector_rank（板块内个股排名，T7）+ pattern（PatternScan），
    板块内排名≤3 才命中。无 market_scan_ctx（limitup/match_strategies 路径）→ 不命中
    （R9 行为变化：从无条件放行变永不命中——涨停股本不该命中非涨停龙头战法，方向对）。
    confidence=0.5（固定）；compute_volume_signal 读 market_scan_ctx.pattern.amount_yi>10亿。
    """

    code = "dragon_head"
    name = "龙头战法"

    def match(self, ctx) -> list[ConditionMatch]:
        # S094 R9：删无条件放行——读 market_scan_ctx（板块内排名≤3 + 有 PatternScan 才命中）。
        # 无 market_scan_ctx（limitup/match_strategies 路径）→ 不命中（R9 行为变化）。
        msc = getattr(ctx, "market_scan_ctx", None) or {}
        pattern = msc.get("pattern") if isinstance(msc, dict) else None
        sector_rank = msc.get("sector_rank")
        if pattern is None or sector_rank is None or sector_rank > 3:
            return []
        return [ConditionMatch(
            condition="板块内领涨",
            value=f"板块内排名={sector_rank}",
            description=f"策略逻辑上，该股板块内相对强度排名前 3（rank={sector_rank}），具备龙头地位",
        )]

    def compute_confidence(self, matches, ctx) -> float:
        return 0.5

    def compute_volume_signal(self, ctx) -> bool | None:
        """S094 R4：龙头成交额 > 10亿（spec §3.R4，换手>5% 用成交额代理）。"""
        pattern = _get_pattern(ctx)
        if pattern is None or pattern.amount_yi is None:
            return None
        return pattern.amount_yi > 10
