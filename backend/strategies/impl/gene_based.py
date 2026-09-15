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

from strategies.strategy_base import (
    BaseStrategy, ConditionMatch, ConditionEval, StrategyMatchResult, make_data_unavailable_result,
)


def _get_pattern(ctx):
    """S094 R4 辅助：从 ctx.market_scan_ctx 取 PatternScan（S1 阶段涨停 pipeline 无此字段，None 降级）。"""
    msc = getattr(ctx, "market_scan_ctx", None)
    if not msc:
        return None
    return msc.get("pattern") if isinstance(msc, dict) else None


class FirstPlateStrategy(BaseStrategy):
    """首板挖掘：score≥40 ∧ 涨停频次≥6，confidence=动态 score/100（fa4514e 阈值校准，分位数支撑）。"""

    code = "first_plate"
    name = "首板挖掘"

    def match(self, ctx) -> StrategyMatchResult:
        # S097：拆 C1 基因合格 + C2 涨停频次，返 StrategyMatchResult（全量条件三态）
        # 阈值校准（2026-08-27，分位数支撑）：
        #   total_score 全量 P75=35.7 / qualify=1 子集 P25=52.4 → 阈值 40（全量 P75 与 qualify P25 之间）
        #   涨停频次 全量 P50=6.0 / qualify=1 子集 P50=14.0 → 阈值 6（全量 P50，筛掉 P50 以下低频次股）
        #   原阈值 60/20 远超历史 max（total_score max=70.6 但涨停当天 T+1 因子为 0 导致系统性偏低，
        #   实际 max 才 50.46；涨停频次 max=39 但 P95=18，阈值 20 几乎无人能过）
        gene = ctx.gene
        freq = gene.factors.get("涨停频次", 0)
        c1_hit = gene.total_score >= 40
        c2_hit = freq >= 6
        conditions = [
            ConditionEval(
                condition_id="first_plate.c1",
                condition_name="基因得分合格",
                factor="total_score",
                threshold=">= 40",
                actual_value=str(gene.total_score),
                state="hit" if c1_hit else "miss",
                description=f"基因得分 {gene.total_score}（阈值≥40，全量P75）",
            ),
            ConditionEval(
                condition_id="first_plate.c2",
                condition_name="涨停频次达标",
                factor="涨停频次",
                threshold=">= 6",
                actual_value=str(freq),
                state="hit" if c2_hit else "miss",
                description=f"涨停频次 {freq}（阈值≥6，全量P50）",
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

    def match(self, ctx) -> StrategyMatchResult:
        # S097：拆 C1 连板历史 + C2 封板能力，返 StrategyMatchResult（全量条件三态）
        gene = ctx.gene
        zt = gene.zt_count_250d
        seal = gene.factors.get("封板率", 0)
        c1_hit = zt >= 2
        c2_hit = seal >= 60
        conditions = [
            ConditionEval(
                condition_id="consecutive_relay.c1", condition_name="连板历史",
                factor="zt_count_250d", threshold=">= 2", actual_value=str(zt),
                state="hit" if c1_hit else "miss",
                description=f"250日涨停 {zt} 次（阈值≥2）",
            ),
            ConditionEval(
                condition_id="consecutive_relay.c2", condition_name="封板能力",
                factor="封板率", threshold=">= 60", actual_value=f"{seal:.1f}%",
                state="hit" if c2_hit else "miss",
                description=f"封板率 {seal:.1f}%（阈值≥60%）",
            ),
        ]
        hit_count = sum(1 for c in conditions if c.state == "hit")
        fired = c1_hit and c2_hit
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=len(conditions), fired=fired,
            fire_rule="全条件命中",
            confidence=min(seal / 100, 1.0) if fired else None, data_ok=True,
        )

    def compute_confidence(self, matches, ctx) -> float:
        return min(ctx.gene.factors.get("封板率", 0) / 100, 1.0)


class BreakResealStrategy(BaseStrategy):
    """炸板回封：3≤zt≤5 ∧ 封板率≥80%，confidence=固定 0.7（S053 黄金区）。"""

    code = "break_reseal"
    name = "炸板回封"

    def match(self, ctx) -> StrategyMatchResult:
        # S097：拆 C1 黄金区频次 [3,5] + C2 强封板≥80，返 StrategyMatchResult
        gene = ctx.gene
        zt = gene.zt_count_250d
        seal = gene.factors.get("封板率", 0)
        c1_hit = 3 <= zt <= 5
        c2_hit = seal >= 80
        conditions = [
            ConditionEval(
                condition_id="break_reseal.c1", condition_name="黄金区频次",
                factor="zt_count_250d", threshold="[3,5]", actual_value=str(zt),
                state="hit" if c1_hit else "miss",
                description=f"250日涨停 {zt} 次（黄金区 3-5）",
            ),
            ConditionEval(
                condition_id="break_reseal.c2", condition_name="强封板",
                factor="封板率", threshold=">= 80", actual_value=f"{seal:.1f}%",
                state="hit" if c2_hit else "miss",
                description=f"封板率 {seal:.1f}%（阈值≥80%）",
            ),
        ]
        hit_count = sum(1 for c in conditions if c.state == "hit")
        fired = c1_hit and c2_hit
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=len(conditions), fired=fired,
            fire_rule="全条件命中",
            confidence=0.7 if fired else None, data_ok=True,
        )

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

    def match(self, ctx) -> StrategyMatchResult:
        # S097 + S153 R5：C1 回调MA5 + C2 均线多头 + C3 缩量 vol_brk<1.0；无 pattern → data_ok=False
        pattern = _get_pattern(ctx)
        if pattern is None:
            return make_data_unavailable_result(self.code, self.name, [
                ("low_absorption.c1", "回调MA5", "ma5_proximity", "<= 3"),
                ("low_absorption.c2", "均线多头", "ma_bullish", "True"),
                ("low_absorption.c3", "缩量回调", "volume_breakout_ratio", "< 1.0"),
            ])
        ma5_prox = pattern.ma5_proximity
        ma_bull = pattern.ma_bullish
        vol_brk = pattern.volume_breakout_ratio
        if ma5_prox is None:
            c1_state, c1_desc, c1_val = "data_unavailable", "ma5_proximity 数据缺失", None
        elif ma5_prox <= 3:
            c1_state, c1_desc = "hit", f"ma5_proximity={ma5_prox:.2f}%（≤3%，回调至MA5）"
            c1_val = f"{ma5_prox:.2f}%"
        else:
            c1_state, c1_desc = "miss", f"ma5_proximity={ma5_prox:.2f}%（>3%，未回调至MA5）"
            c1_val = f"{ma5_prox:.2f}%"
        if ma_bull is None:
            c2_state, c2_desc, c2_val = "data_unavailable", "ma_bullish 数据缺失", None
        else:
            c2_state = "hit" if ma_bull else "miss"
            c2_desc = f"均线{'多头' if ma_bull else '非多头'}排列"
            c2_val = str(ma_bull)
        # S153 R5 C3：缩量回调（vol_brk<1.0=回调日量<5日均量，mirror of platform C2 放量>2）
        if vol_brk is None:
            c3_state, c3_desc, c3_val = "data_unavailable", "volume_breakout_ratio 数据缺失", None
        elif vol_brk < 1.0:
            c3_state, c3_desc = "hit", f"量比 {vol_brk:.2f}（<1.0，回调日缩量）"
            c3_val = f"{vol_brk:.2f}"
        else:
            c3_state, c3_desc = "miss", f"量比 {vol_brk:.2f}（≥1.0，未缩量）"
            c3_val = f"{vol_brk:.2f}"
        conditions = [
            ConditionEval(condition_id="low_absorption.c1", condition_name="回调MA5",
                factor="ma5_proximity", threshold="<= 3", actual_value=c1_val,
                state=c1_state, description=c1_desc),
            ConditionEval(condition_id="low_absorption.c2", condition_name="均线多头",
                factor="ma_bullish", threshold="True", actual_value=c2_val,
                state=c2_state, description=c2_desc),
            ConditionEval(condition_id="low_absorption.c3", condition_name="缩量回调",
                factor="volume_breakout_ratio", threshold="< 1.0", actual_value=c3_val,
                state=c3_state, description=c3_desc),
        ]
        hit_count = sum(1 for c in conditions if c.state == "hit")
        fired = c1_state == "hit" and c2_state == "hit" and c3_state == "hit"
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=len(conditions), fired=fired,
            fire_rule="全条件命中",
            confidence=0.5 if fired else None, data_ok=True,
        )

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

    def match(self, ctx) -> StrategyMatchResult:
        # S097：C1 N字区间 [2,10]；R14 去条件标签"放量"（condition_name="N字区间"，纯基因频次战法）
        gene = ctx.gene
        zt = gene.zt_count_250d
        c1_hit = 2 <= zt <= 10
        conditions = [
            ConditionEval(
                condition_id="n_shape_counterattack.c1", condition_name="N字区间",
                factor="zt_count_250d", threshold="[2,10]", actual_value=str(zt),
                state="hit" if c1_hit else "miss",
                description=f"250日涨停 {zt} 次（[2,10] 区间，N字反击历史）",
            ),
        ]
        hit_count = sum(1 for c in conditions if c.state == "hit")
        fired = c1_hit
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=len(conditions), fired=fired,
            fire_rule="全条件命中",
            confidence=0.5 if fired else None, data_ok=True,
        )

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

    def match(self, ctx) -> StrategyMatchResult:
        # S097 + S153 R4：C1 横盘≥5 + C2 放量突破>2 + C3 紧平台 amplitude≤6.0；无 pattern → data_ok=False
        pattern = _get_pattern(ctx)
        if pattern is None:
            return make_data_unavailable_result(self.code, self.name, [
                ("platform_breakout.c1", "横盘", "consolidation_days", ">= 5"),
                ("platform_breakout.c2", "放量突破", "volume_breakout_ratio", "> 2"),
                ("platform_breakout.c3", "紧平台", "consolidation_amplitude", "<= 6.0"),
            ])
        cons = pattern.consolidation_days
        vol_brk = pattern.volume_breakout_ratio
        cons_amp = pattern.consolidation_amplitude
        if cons is None:
            c1_state, c1_desc, c1_val = "data_unavailable", "consolidation_days 数据缺失", None
        elif cons >= 5:
            c1_state, c1_desc, c1_val = "hit", f"横盘 {cons} 日（≥5）", str(cons)
        else:
            c1_state, c1_desc, c1_val = "miss", f"横盘 {cons} 日（<5，未充分横盘）", str(cons)
        if vol_brk is None:
            c2_state, c2_desc, c2_val = "data_unavailable", "volume_breakout_ratio 数据缺失", None
        elif vol_brk > 2:
            c2_state, c2_desc = "hit", f"量比 {vol_brk:.2f}（>2，放量突破）"
            c2_val = f"{vol_brk:.2f}"
        else:
            c2_state, c2_desc = "miss", f"量比 {vol_brk:.2f}（≤2，未放量）"
            c2_val = f"{vol_brk:.2f}"
        # S153 R4 C3：紧平台（consolidation_amplitude≤6.0，预注册冻结值）
        if cons_amp is None:
            c3_state, c3_desc, c3_val = "data_unavailable", "consolidation_amplitude 数据缺失", None
        elif cons_amp <= 6.0:
            c3_state, c3_desc = "hit", f"振幅 {cons_amp:.2f}%（≤6.0，紧平台蓄势）"
            c3_val = f"{cons_amp:.2f}"
        else:
            c3_state, c3_desc = "miss", f"振幅 {cons_amp:.2f}%（>6.0，平台松散）"
            c3_val = f"{cons_amp:.2f}"
        conditions = [
            ConditionEval(condition_id="platform_breakout.c1", condition_name="横盘",
                factor="consolidation_days", threshold=">= 5", actual_value=c1_val,
                state=c1_state, description=c1_desc),
            ConditionEval(condition_id="platform_breakout.c2", condition_name="放量突破",
                factor="volume_breakout_ratio", threshold="> 2", actual_value=c2_val,
                state=c2_state, description=c2_desc),
            ConditionEval(condition_id="platform_breakout.c3", condition_name="紧平台",
                factor="consolidation_amplitude", threshold="<= 6.0", actual_value=c3_val,
                state=c3_state, description=c3_desc),
        ]
        hit_count = sum(1 for c in conditions if c.state == "hit")
        fired = c1_state == "hit" and c2_state == "hit" and c3_state == "hit"
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=len(conditions), fired=fired,
            fire_rule="全条件命中",
            confidence=0.5 if fired else None, data_ok=True,
        )

    def compute_confidence(self, matches, ctx) -> float:
        return 0.5

    def compute_volume_signal(self, ctx) -> bool | None:
        """S094 R4：平台突破 volume_breakout_ratio > 2（spec §3.R4）。"""
        pattern = _get_pattern(ctx)
        if pattern is None or pattern.volume_breakout_ratio is None:
            return None
        return pattern.volume_breakout_ratio > 2


class EndOfDaySneakStrategy(BaseStrategy):
    """尾盘偷袭：封板率≥40% ∧ 溢价率>15%，confidence=固定 0.4（fa4514e 阈值校准）。"""

    code = "end_of_day_sneak"
    name = "尾盘偷袭"

    def match(self, ctx) -> StrategyMatchResult:
        # S097：拆 C1 尾盘封板率≥40 + C2 溢价能力>15，返 StrategyMatchResult
        # 阈值校准（2026-08-27，分位数支撑）：
        #   封板率 全量 P75=83.5 → 阈值 40 合理（涨停股封板率天然高，40 筛掉低封板）
        #   次日溢价率 全量 P90=18.9 / qualify=1 子集 P25=30.1 → 阈值 15（全量 P75 与 qualify P25 之间）
        #   原阈值 >40 远超历史 P90（涨停当天 T+1 因子 max 才 30.06，几乎无人能过）
        gene = ctx.gene
        seal = gene.factors.get("封板率", 0)
        premium = gene.factors.get("次日溢价率", 0)
        c1_hit = seal >= 40
        c2_hit = premium > 15
        conditions = [
            ConditionEval(
                condition_id="end_of_day_sneak.c1", condition_name="尾盘封板",
                factor="封板率", threshold=">= 40", actual_value=f"{seal:.1f}%",
                state="hit" if c1_hit else "miss",
                description=f"封板率 {seal:.1f}%（阈值≥40%）",
            ),
            ConditionEval(
                condition_id="end_of_day_sneak.c2", condition_name="溢价能力",
                factor="次日溢价率", threshold="> 15", actual_value=f"{premium:.1f}%",
                state="hit" if c2_hit else "miss",
                description=f"次日溢价率 {premium:.1f}%（阈值>15%，全量P75）",
            ),
        ]
        hit_count = sum(1 for c in conditions if c.state == "hit")
        fired = c1_hit and c2_hit
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=len(conditions), fired=fired,
            fire_rule="全条件命中",
            confidence=0.4 if fired else None, data_ok=True,
        )

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

    def match(self, ctx) -> StrategyMatchResult:
        # S097：C1 板块领涨 sector_rank≤3。
        # 无 market_scan_ctx/pattern → data_ok=False 整战法降级（limitup 路径无 msc，不算逻辑过滤）；
        # pattern 存在但 sector_rank None → 字段级 data_unavailable（data_ok=True，非整战法降级，
        # 与 LowAbsorption/PlatformBreakout/StormReversal 的字段级降级一致）。
        msc = getattr(ctx, "market_scan_ctx", None) or {}
        pattern = msc.get("pattern") if isinstance(msc, dict) else None
        sector_rank = msc.get("sector_rank")
        if pattern is None:
            return make_data_unavailable_result(self.code, self.name, [
                ("dragon_head.c1", "板块领涨", "sector_rank", "<= 3"),
            ])
        if sector_rank is None:
            c1_state, c1_desc, c1_val, c1_hit = "data_unavailable", "sector_rank 数据缺失", None, False
        else:
            c1_hit = sector_rank <= 3
            c1_state = "hit" if c1_hit else "miss"
            c1_desc = f"板块内排名 {sector_rank}（阈值≤3，龙头地位）"
            c1_val = str(sector_rank)
        conditions = [
            ConditionEval(
                condition_id="dragon_head.c1", condition_name="板块领涨",
                factor="sector_rank", threshold="<= 3", actual_value=c1_val,
                state=c1_state, description=c1_desc,
            ),
        ]
        hit_count = sum(1 for c in conditions if c.state == "hit")
        fired = c1_hit
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=len(conditions), fired=fired,
            fire_rule="全条件命中",
            confidence=0.5 if fired else None, data_ok=True,
        )

    def compute_confidence(self, matches, ctx) -> float:
        return 0.5

    def compute_volume_signal(self, ctx) -> bool | None:
        """S094 R4：龙头成交额 > 10亿（spec §3.R4，换手>5% 用成交额代理）。"""
        pattern = _get_pattern(ctx)
        if pattern is None or pattern.amount_yi is None:
            return None
        return pattern.amount_yi > 10


class FirstBoardLimitupStrategy(BaseStrategy):
    """S203 首板涨停（用户 brief：板块共振 + 封单精品门槛 + 板块内前 3）。

    区别 first_plate（首板挖掘 gene-based 涨停频次≥6）+ dragon_head（非涨停龙头追踪
    sector_rank≤3）：本战法是**涨停首板**——板块共振（zt_count_today≥2）+ 封单精品
    （seal_to_float_ratio≥0.5%）+ 龙头地位（sector_rank≤3）。

    ⚠️ 涨停 pipeline 当前不构造 market_scan_ctx（strategy_base.py:127 注明）→ 本战法
    在涨停路径 data_unavailable（不命中，非逻辑过滤）。wiring（涨停池 raw seal_to_float_ratio
    merge + sector_cycle zt_count_today 进 msc）待 G5/harness 或专门 wiring task。
    edge_type=selection（待验，§44v2 window sanity 后定，决策#7 verifier-side）。
    社区阈值（zt_count_today≥2 / seal≥0.5%）标 overfit 风险，须 sensitivity sweep（S204 R13）。
    """

    code = "first_board_limitup"
    name = "首板涨停"

    def match(self, ctx) -> StrategyMatchResult:
        msc = getattr(ctx, "market_scan_ctx", None) or {}
        pattern = msc.get("pattern") if isinstance(msc, dict) else None
        sector_rank = msc.get("sector_rank")
        zt_count_today = msc.get("zt_count_today")
        seal_to_float = msc.get("seal_to_float_ratio")

        # 无 msc 任一字段 → data_unavailable 整战法降级（涨停 pipeline 无 msc，诚实不臆造）
        if pattern is None and sector_rank is None and zt_count_today is None and seal_to_float is None:
            return make_data_unavailable_result(self.code, self.name, [
                ("first_board_limitup.c1", "龙头地位", "sector_rank", "<= 3"),
                ("first_board_limitup.c2", "板块共振", "zt_count_today", ">= 2"),
                ("first_board_limitup.c3", "封单精品", "seal_to_float_ratio", ">= 0.005"),
            ])

        # C1 龙头地位: high_gene=1（ctx.gene，涨停路径有）OR sector_rank≤3（msc，非涨停 funnel）
        # S203 wiring(a) phase 1：涨停路径 gene_obj 有 high_gene（无 sector_rank），C1 用 high_gene 兜底
        gene = getattr(ctx, "gene", None)
        high_gene = getattr(gene, "high_gene", None) if gene else None
        c1_hit = bool(high_gene) or (sector_rank is not None and sector_rank <= 3)
        if c1_hit:
            c1_state = "hit"
            c1_desc = f"high_gene={high_gene}, sector_rank={sector_rank}（龙头确认）"
            c1_val = f"hg={high_gene}, sr={sector_rank}"
        elif high_gene is None and sector_rank is None:
            c1_state, c1_desc, c1_val, c1_hit = "data_unavailable", "无 high_gene/sector_rank", None, False
        else:
            c1_state = "miss"
            c1_desc = f"high_gene={high_gene}, sector_rank={sector_rank}（非龙头）"
            c1_val = f"hg={high_gene}, sr={sector_rank}"
        # C2 板块共振 zt_count_today≥2（板块涨停家数，探索性门槛须 sweep）
        if zt_count_today is None:
            c2_state, c2_desc, c2_val, c2_hit = "data_unavailable", "zt_count_today 数据缺失", None, False
        else:
            c2_hit = zt_count_today >= 2
            c2_state = "hit" if c2_hit else "miss"
            c2_desc = f"板块涨停家数 {zt_count_today}（阈值≥2，板块共振）"
            c2_val = str(zt_count_today)
        # C3 封单精品 seal_to_float_ratio≥0.005（0.5%，社区阈值标 overfit 须 sweep）
        if seal_to_float is None:
            c3_state, c3_desc, c3_val, c3_hit = "data_unavailable", "seal_to_float_ratio 数据缺失", None, False
        else:
            c3_hit = seal_to_float >= 0.005
            c3_state = "hit" if c3_hit else "miss"
            c3_desc = f"封单/流通市值 {seal_to_float}（阈值≥0.005，精品封单）"
            c3_val = str(seal_to_float)

        conditions = [
            ConditionEval(condition_id="first_board_limitup.c1", condition_name="龙头地位",
                          factor="sector_rank", threshold="<= 3", actual_value=c1_val,
                          state=c1_state, description=c1_desc),
            ConditionEval(condition_id="first_board_limitup.c2", condition_name="板块共振",
                          factor="zt_count_today", threshold=">= 2", actual_value=c2_val,
                          state=c2_state, description=c2_desc),
            ConditionEval(condition_id="first_board_limitup.c3", condition_name="封单精品",
                          factor="seal_to_float_ratio", threshold=">= 0.005", actual_value=c3_val,
                          state=c3_state, description=c3_desc),
        ]
        hit_count = sum(1 for c in conditions if c.state == "hit")
        fired = c1_hit and c2_hit and c3_hit
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=len(conditions), fired=fired,
            fire_rule="全条件命中",
            confidence=0.6 if fired else None, data_ok=True,
        )

    def compute_confidence(self, matches, ctx) -> float:
        return 0.6


def _detect_leader_drop_reversal(bars):
    """S203 T5：从 baostock bars 检测龙头大跌反包（T-1 大跌 + T 吞没 + 放量）。

    bars: list of {date, open, high, low, close, volume}（按 date asc）。None/不足 → 全 data_unavailable。
    大跌从 close/open 差复算（不依赖 pctChg 字段，R14 注入前可用）。
    返 (c2_drop_hit, c3_engulf_hit, c4_volume_hit, descriptions)。
    """
    if not bars or len(bars) < 2:
        return None, None, None, ["bars 不足/缺失"]
    prev = bars[-2]  # T-1 大跌日
    curr = bars[-1]  # T 反包日
    try:
        # C2 T-1 大跌: prev.close 相对 prev.open 跌 ≥7%（日内大跌，从 close 复算不依赖 pctChg）
        # round 4 位避 float 噪声（-7% 算成 -0.06999 → round -0.07 精确）
        drop_pct = round((float(prev["close"]) - float(prev["open"])) / float(prev["open"]), 4)
        c2_hit = drop_pct <= -0.07
        c2_desc = f"T-1 日内跌幅 {drop_pct*100:.1f}%（阈值≤-7%，龙头大跌）"
        # C3 T 吞没: curr.close ≥ prev.open（吞没前日阴线）AND curr.open ≤ prev.close（低开反包）
        c3_hit = (float(curr["close"]) >= float(prev["open"])
                  and float(curr["open"]) <= float(prev["close"]))
        c3_desc = (f"T close {curr['close']} ≥ T-1 open {prev['open']}（吞没）且 "
                   f"T open {curr['open']} ≤ T-1 close {prev['close']}（低开反包）")
        # C4 放量: curr.volume / prev.volume ≥ 1.2
        prev_vol = float(prev.get("volume", 0))
        curr_vol = float(curr.get("volume", 0))
        c4_hit = (prev_vol > 0 and curr_vol / prev_vol >= 1.2)
        c4_desc = f"T 量比 {curr_vol/prev_vol:.2f}（阈值≥1.2，爆量反包）" if prev_vol > 0 else "T-1 volume=0 无法算量比"
        return c2_hit, c3_hit, c4_hit, [c2_desc, c3_desc, c4_desc]
    except (TypeError, ValueError, ZeroDivisionError, KeyError) as e:
        return None, None, None, [f"bars 解析失败: {e}"]


class LeaderDropReversalStrategy(BaseStrategy):
    """S203 T5：龙头大跌反包（用户 brief：龙头大跌触发量化止损后筹码真空，5/10 日均线爆量反包吞没阴线）。

    区别 reverse_package（炸板后反包 open_count≥2）+ pattern_reversal（长上影后反包）：
    本战法是**龙头大跌后反包**——T-1 日大跌≥7% + T 日吞没前日阴线 + 放量≥1.2x +
    龙头确认（gene.high_gene=1 或 msc.sector_rank≤3）。

    ⚠️ ctx 无 bars 字段（strategy_base StrategyMatchContext 只有 code/gene/market_scan_ctx）→
    bars 须从 msc.bars 读（涨停 pipeline 当前不构造 msc.bars → data_unavailable）。
    大跌从 close/open 差复算（不依赖 pctChg，R14 注入前可用）。edge_type=event（待验，
    §44v2 须 R11 event_drift 修正才 verdict 可靠——G2 T5b 已 done）。
    """

    code = "leader_drop_reversal"
    name = "龙头大跌反包"

    def match(self, ctx) -> StrategyMatchResult:
        msc = getattr(ctx, "market_scan_ctx", None) or {}
        gene = getattr(ctx, "gene", None)
        bars = msc.get("bars") if isinstance(msc, dict) else None
        high_gene = getattr(gene, "high_gene", None) if gene else None
        sector_rank = msc.get("sector_rank") if isinstance(msc, dict) else None

        # 无 bars + 无龙头确认 → data_unavailable 整战法降级
        if bars is None and high_gene is None and sector_rank is None:
            return make_data_unavailable_result(self.code, self.name, [
                ("leader_drop_reversal.c1", "龙头确认", "high_gene/sector_rank", "high_gene=1 or sector_rank<=3"),
                ("leader_drop_reversal.c2", "T-1 大跌", "bars close/open", "<= -7%"),
                ("leader_drop_reversal.c3", "T 吞没", "bars close/open", "curr.close>=prev.open & curr.open<=prev.close"),
                ("leader_drop_reversal.c4", "放量", "bars volume", ">= 1.2x"),
            ])

        # C1 龙头确认: high_gene=1 或 sector_rank≤3
        if high_gene is None and sector_rank is None:
            c1_state, c1_desc, c1_val, c1_hit = "data_unavailable", "无 high_gene/sector_rank", None, False
        else:
            c1_hit = (high_gene == 1) or (sector_rank is not None and sector_rank <= 3)
            c1_state = "hit" if c1_hit else "miss"
            c1_desc = f"high_gene={high_gene}, sector_rank={sector_rank}（龙头确认）"
            c1_val = f"hg={high_gene}, sr={sector_rank}"

        # C2/C3/C4 bars 检测
        c2_hit, c3_hit, c4_hit, bars_descs = _detect_leader_drop_reversal(bars)
        if c2_hit is None:
            c2_state = c3_state = c4_state = "data_unavailable"
            c2_val = c3_val = c4_val = None
            c2_desc = c3_desc = c4_desc = bars_descs[0] if bars_descs else "bars 缺失"
        else:
            c2_state = "hit" if c2_hit else "miss"
            c3_state = "hit" if c3_hit else "miss"
            c4_state = "hit" if c4_hit else "miss"
            c2_desc, c3_desc, c4_desc = bars_descs[0], bars_descs[1], bars_descs[2]
            c2_val = c3_val = c4_val = "见 desc"

        conditions = [
            ConditionEval(condition_id="leader_drop_reversal.c1", condition_name="龙头确认",
                          factor="high_gene/sector_rank", threshold="hg=1 or sr<=3", actual_value=c1_val,
                          state=c1_state, description=c1_desc),
            ConditionEval(condition_id="leader_drop_reversal.c2", condition_name="T-1 大跌",
                          factor="bars close/open", threshold="<= -7%", actual_value=c2_val,
                          state=c2_state, description=c2_desc),
            ConditionEval(condition_id="leader_drop_reversal.c3", condition_name="T 吞没",
                          factor="bars close/open", threshold="curr.close>=prev.open & curr.open<=prev.close",
                          actual_value=c3_val, state=c3_state, description=c3_desc),
            ConditionEval(condition_id="leader_drop_reversal.c4", condition_name="放量",
                          factor="bars volume", threshold=">= 1.2x", actual_value=c4_val,
                          state=c4_state, description=c4_desc),
        ]
        hit_count = sum(1 for c in conditions if c.state == "hit")
        fired = all(c.state == "hit" for c in conditions)
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=len(conditions), fired=fired,
            fire_rule="全条件命中",
            confidence=0.55 if fired else None, data_ok=True,
        )

    def compute_confidence(self, matches, ctx) -> float:
        return 0.55


class Relay23Strategy(BaseStrategy):
    """S203 T6：接力二三板（当下连板 lbc≥2 + 量比 [1.5,2.5] + Dragon Score 占位）。

    区别 consecutive_relay（gene-based 250 日涨停频次≥2 + 封板率≥60%，历史频次口径）：
    本战法是**当下连板接力**——当日涨停池 lbc≥2（区别历史频次）+ T 量比 1.5-2.5x
    （放量但不爆量，接力健康区：缩量<1.5 无人接力，爆量>2.5 抛压过重）+ Dragon Score
    （占位，dimension_registry 已建结构但未接线生产 compute，当前 data_unavailable）。

    C3 Dragon Score 标占位——dimension_registry（5 维 + 接力 config）结构已落，dragon_score
    composite 0-100 compute 待接线。当前 C3=data_unavailable **不阻塞 fire**：fire=C1+C2
    命中，C3 为标注维度待接（区别 LowAbsorption C3 缩量 data_unavailable 阻塞 fire——彼为
    数据缺失，此处为功能占位）。
    edge_type=selection(待验，§44v2 window sanity 后定)。社区阈值（lbc≥2 / 量比 [1.5,2.5]）
    标 overfit 风险，须 sensitivity sweep（S204 R13，dimension_registry sweep_range 已声明）。
    """

    code = "relay_23"
    name = "接力二三板"

    @staticmethod
    def _eval_vol_ratio(bars):
        """C2 量比 = T.volume / T-1.volume（bars 尾部 2 根，date asc）。

        返 (ratio, state, desc, val, hit)。bars 不足/字段缺失/prev_vol=0 → data_unavailable。
        """
        if not bars or len(bars) < 2:
            return None, "data_unavailable", "bars 不足/缺失，无法算量比", None, False
        prev, curr = bars[-2], bars[-1]
        try:
            prev_vol = float(prev.get("volume", 0))
            curr_vol = float(curr.get("volume", 0))
        except (TypeError, ValueError, KeyError):
            return None, "data_unavailable", "volume 字段解析失败", None, False
        if prev_vol <= 0:
            return None, "data_unavailable", "T-1 volume=0 无法算量比", None, False
        ratio = round(curr_vol / prev_vol, 4)
        hit = 1.5 <= ratio <= 2.5
        state = "hit" if hit else "miss"
        desc = f"T 量比 {ratio:.2f}（区间 [1.5, 2.5]，接力健康区）"
        return ratio, state, desc, f"{ratio:.2f}", hit

    def match(self, ctx) -> StrategyMatchResult:
        msc = getattr(ctx, "market_scan_ctx", None) or {}
        lbc = msc.get("lbc")
        bars = msc.get("bars")

        # 无 lbc + 无 bars → 整战法 data_unavailable（涨停 pipeline 未构造 msc 时诚实降级）
        if lbc is None and bars is None:
            return make_data_unavailable_result(self.code, self.name, [
                ("relay_23.c1", "当下连板", "lbc", ">= 2"),
                ("relay_23.c2", "量比健康区", "bars volume ratio", "[1.5, 2.5]"),
                ("relay_23.c3", "Dragon Score", "dimension_registry", "占位待接线"),
            ])

        # C1 当下连板 lbc≥2（涨停池 raw lbc，区别 consecutive_relay 的 250 日历史频次）
        if lbc is None:
            c1_state, c1_desc, c1_val, c1_hit = "data_unavailable", "lbc 数据缺失", None, False
        else:
            c1_hit = lbc >= 2
            c1_state = "hit" if c1_hit else "miss"
            c1_desc = f"当下连板 {lbc}（阈值≥2，接力二三板）"
            c1_val = str(lbc)

        # C2 量比 [1.5, 2.5]（T/T-1 volume，放量但不爆量）
        _ratio, c2_state, c2_desc, c2_val, c2_hit = self._eval_vol_ratio(bars)

        # C3 Dragon Score 占位（dimension_registry 接线待，当前 data_unavailable 不阻塞 fire）
        c3_state, c3_desc, c3_val = "data_unavailable", "Dragon Score 占位（dimension_registry 接线待）", None

        conditions = [
            ConditionEval(condition_id="relay_23.c1", condition_name="当下连板",
                          factor="lbc", threshold=">= 2", actual_value=c1_val,
                          state=c1_state, description=c1_desc),
            ConditionEval(condition_id="relay_23.c2", condition_name="量比健康区",
                          factor="bars volume ratio", threshold="[1.5, 2.5]", actual_value=c2_val,
                          state=c2_state, description=c2_desc),
            ConditionEval(condition_id="relay_23.c3", condition_name="Dragon Score",
                          factor="dimension_registry", threshold="占位待接线", actual_value=c3_val,
                          state=c3_state, description=c3_desc),
        ]
        hit_count = sum(1 for c in conditions if c.state == "hit")
        # C3 占位 data_unavailable 不阻塞——fire = C1+C2 命中（Dragon Score 接线后改为全条件）
        fired = c1_hit and c2_hit
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=len(conditions), fired=fired,
            fire_rule="C1+C2 命中（C3 Dragon Score 占位待接线）",
            confidence=0.5 if fired else None, data_ok=True,
        )

    def compute_confidence(self, matches, ctx) -> float:
        return 0.5
