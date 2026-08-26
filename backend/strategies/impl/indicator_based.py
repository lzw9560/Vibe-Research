# -*- coding: utf-8 -*-
"""S086 B3：读 IndicatorSet K线派生因子的 2 个复杂战法（indicator_based）。

战法：weak_turn_strong / pattern_reversal（S081 PRD P2）。

5 因子硬阈值（≥4 命中输出），阈值探索性（外部 PRD 拍定，零数据支撑），进 config 可配。
derived 从 ctx.derived 读（不上提取数——调度器 _prepare_derived 已统一准备）。
match 条件/阈值/confidence 严格按 limitup_strategy.py:822-962 迁移，不改阈值。
"""
from __future__ import annotations

from strategies.strategy_base import (
    BaseStrategy, ConditionMatch, ConditionEval, StrategyMatchResult, make_data_unavailable_result, _round_to_tick_size,
)


def _get_pattern(ctx):
    """S094 R5 辅助：从 ctx.market_scan_ctx 取 PatternScan（S1 阶段涨停 pipeline 无此字段，None 降级）。"""
    msc = getattr(ctx, "market_scan_ctx", None)
    if not msc:
        return None
    return msc.get("pattern") if isinstance(msc, dict) else None


class WeakTurnStrongStrategy(BaseStrategy):
    """弱转强接力：5 因子硬阈值（lbc/broken/drop/lock/vol_ratio）≥4 命中。

    confidence=1.0（5 命中）/ 0.7（4 命中）；≤3 不输出。
    derived 从 ctx.derived 读（调度器 _prepare_derived 已 fallback 取 snapshots）。
    """

    code = "weak_turn_strong"
    name = "弱转强接力"

    def match(self, ctx) -> StrategyMatchResult:
        # S097：拆 C1-C5 五因子三态，≥4/5 命中 fired；R18 修 C4（last_lock_time[11:16]>="14:40"）
        pool_item = ctx.pool_item
        lbc_raw = pool_item.get("lbc") if pool_item else None  # None=数据缺失（pool_item 缺或 lbc 字段缺）
        hs = pool_item.get("hs") if pool_item else None  # 当日换手率

        # S070 R7 派生（broken_duration_min/max_drop_pct/last_lock_time）从 ctx.derived 读
        derived = ctx.derived or {}
        broken_duration_min = derived.get("broken_duration_min")
        max_drop_pct = derived.get("max_drop_pct")
        last_lock_time = derived.get("last_lock_time")

        # A5 vol_ratio_1d：当日换手 / 前日换手（从 indicators 读 prev_turnover_pct）
        indicators = ctx.indicators
        vol_ratio_1d = None
        if indicators is not None and hs is not None and hs > 0:
            prev_hs = getattr(indicators, "prev_turnover_pct", None)
            if prev_hs and prev_hs > 0:
                vol_ratio_1d = round(hs / prev_hs, 2)

        # A6 5 因子硬阈值（PRD §2.1，阈值探索性，进 config 可配）
        import config as _cfg_mod  # noqa: PLC0415
        _wts_cfg = getattr(_cfg_mod, "S081_WEAK_TURN_STRONG", None) or {}
        TH_LBC = _wts_cfg.get("limit_up_days_min", 1)
        TH_BROKEN = _wts_cfg.get("broken_duration_min", 20)
        TH_DROP = _wts_cfg.get("max_drop_pct", 5.0)
        TH_LOCK = _wts_cfg.get("last_lock_time", "14:40")
        TH_VOL_LO = _wts_cfg.get("vol_ratio_lo", 1.8)
        TH_VOL_HI = _wts_cfg.get("vol_ratio_hi", 3.0)

        conditions: list[ConditionEval] = []

        # C1 连板天数（pool_item 缺或 lbc None → data_unavailable，非臆造 lbc=0 miss；spec §7 不臆造）
        if lbc_raw is None:
            conditions.append(ConditionEval(
                condition_id="weak_turn_strong.c1", condition_name="连板天数",
                factor="lbc", threshold=f">= {TH_LBC}", actual_value=None,
                state="data_unavailable", description="连板天数(lbc)数据缺失"))
        else:
            lbc = int(lbc_raw)
            c1_hit = lbc >= TH_LBC
            conditions.append(ConditionEval(
                condition_id="weak_turn_strong.c1", condition_name="连板天数",
                factor="lbc", threshold=f">= {TH_LBC}", actual_value=f"lbc={lbc}",
                state="hit" if c1_hit else "miss",
                description=f"连板 {lbc} 日（阈值≥{TH_LBC}）"))

        # C2 炸板时长（None → data_unavailable，非 miss）
        if broken_duration_min is None:
            conditions.append(ConditionEval(
                condition_id="weak_turn_strong.c2", condition_name="炸板时长",
                factor="broken_duration_min", threshold=f">= {TH_BROKEN}", actual_value=None,
                state="data_unavailable", description="炸板时长数据缺失"))
        else:
            c2_hit = broken_duration_min >= TH_BROKEN
            conditions.append(ConditionEval(
                condition_id="weak_turn_strong.c2", condition_name="炸板时长",
                factor="broken_duration_min", threshold=f">= {TH_BROKEN}",
                actual_value=f"broken={broken_duration_min:.1f}min",
                state="hit" if c2_hit else "miss",
                description=f"炸板累计 {broken_duration_min:.1f} 分钟（阈值≥{TH_BROKEN}min）"))

        # C3 回撤幅度
        if max_drop_pct is None:
            conditions.append(ConditionEval(
                condition_id="weak_turn_strong.c3", condition_name="回撤幅度",
                factor="max_drop_pct", threshold=f">= {TH_DROP}", actual_value=None,
                state="data_unavailable", description="回撤幅度数据缺失"))
        else:
            c3_hit = max_drop_pct >= TH_DROP
            conditions.append(ConditionEval(
                condition_id="weak_turn_strong.c3", condition_name="回撤幅度",
                factor="max_drop_pct", threshold=f">= {TH_DROP}",
                actual_value=f"max_drop={max_drop_pct:.2f}%",
                state="hit" if c3_hit else "miss",
                description=f"炸板后回撤 {max_drop_pct:.2f}%（阈值≥{TH_DROP}%）"))

        # C4 尾盘封死（R18：last_lock_time[11:16] >= "14:40"，修旧 ISO 整串比较恒命中 bug）
        if last_lock_time is None:
            conditions.append(ConditionEval(
                condition_id="weak_turn_strong.c4", condition_name="尾盘封死",
                factor="last_lock_time", threshold=f">= {TH_LOCK}", actual_value=None,
                state="data_unavailable", description="尾盘封死时刻数据缺失"))
        else:
            lock_hm = last_lock_time[11:16] if len(last_lock_time) >= 16 else ""
            if not lock_hm:
                conditions.append(ConditionEval(
                    condition_id="weak_turn_strong.c4", condition_name="尾盘封死",
                    factor="last_lock_time", threshold=f">= {TH_LOCK}", actual_value=last_lock_time,
                    state="data_unavailable", description=f"封死时刻格式不完整：{last_lock_time}"))
            else:
                c4_hit = lock_hm >= TH_LOCK
                conditions.append(ConditionEval(
                    condition_id="weak_turn_strong.c4", condition_name="尾盘封死",
                    factor="last_lock_time", threshold=f">= {TH_LOCK}", actual_value=last_lock_time,
                    state="hit" if c4_hit else "miss",
                    description=f"最后封死 {lock_hm}（阈值≥{TH_LOCK}，{'尾盘封死' if c4_hit else '未尾盘封死'}）"))

        # C5 换手倍数
        if vol_ratio_1d is None:
            conditions.append(ConditionEval(
                condition_id="weak_turn_strong.c5", condition_name="换手倍数",
                factor="vol_ratio_1d", threshold=f"[{TH_VOL_LO},{TH_VOL_HI}]", actual_value=None,
                state="data_unavailable", description="换手倍数数据缺失"))
        else:
            c5_hit = TH_VOL_LO <= vol_ratio_1d <= TH_VOL_HI
            conditions.append(ConditionEval(
                condition_id="weak_turn_strong.c5", condition_name="换手倍数",
                factor="vol_ratio_1d", threshold=f"[{TH_VOL_LO},{TH_VOL_HI}]",
                actual_value=f"vol_ratio={vol_ratio_1d:.2f}",
                state="hit" if c5_hit else "miss",
                description=f"换手倍数 {vol_ratio_1d:.2f}（区间 {TH_VOL_LO}-{TH_VOL_HI}）"))

        hit_count = sum(1 for c in conditions if c.state == "hit")
        fired = hit_count >= 4
        confidence = (1.0 if hit_count == 5 else 0.7) if fired else None
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=len(conditions), fired=fired,
            fire_rule="≥4/5 命中", confidence=confidence, data_ok=True,
        )

    def compute_confidence(self, matches, ctx) -> float:
        # matches 长度 = 命中因子数（hit_count）；5 命中 high / 4 命中 medium
        return 1.0 if len(matches) == 5 else 0.7


class PatternReversalStrategy(BaseStrategy):
    """形态反包（长上影洗盘修复）：S094 R5 改读 PatternScan 3 字段（不读 ctx.indicators）。

    spec §3.L ora-7 N2：5 因子→3 字段删减——删"未封涨停"（涨停判定在战法 match 层
    用 pool_item.lbc/zbc，不在形态因子层）+ 删"最高≥7%"（与上影≥4% 语义重叠，保留
    上影更精确）。放量口径变更：今量/昨量≥1.2 → 今量/前5日均量≥1.2（volume_breakout_ratio，
    前5日均量比昨量更稳定，阈值 1.2 沿用保守值，实现后回测验证调参）。
    "突破昨日最高"形态作废（spec §3.R5 明确）。

    3 字段阈值：shadow_length_pct>=4 + volume_breakout_ratio>=1.2 + ma5_slope>0。
    confidence=1.0（3 命中）/ 0.7（2 命中）；<2 不输出。
    override compute_entry_price 返回 pool_item.p+0.01。
    """

    code = "pattern_reversal"
    name = "形态反包"

    def match(self, ctx) -> StrategyMatchResult:
        # S097：拆 C1-C3 三因子三态，≥2/3 命中 fired；无 pattern → data_ok=False 整战法降级
        pattern = _get_pattern(ctx)
        if pattern is None:
            # S1 阶段涨停 pipeline 无 market_scan_ctx → 整战法降级（data_unavailable，不臆造）
            return make_data_unavailable_result(self.code, self.name, [
                ("pattern_reversal.c1", "上影线", "shadow_length_pct", ">= 4"),
                ("pattern_reversal.c2", "放量", "volume_breakout_ratio", ">= 1.2"),
                ("pattern_reversal.c3", "5日线向上", "ma5_slope", "> 0"),
            ], fire_rule="≥2/3 命中")

        shadow_length_pct = getattr(pattern, "shadow_length_pct", None)
        volume_breakout_ratio = pattern.volume_breakout_ratio
        ma5_slope = getattr(pattern, "ma5_slope", None)

        # 3 字段阈值（spec §3.R5/L：shadow>=4 / vol_ratio>=1.2 / ma5_slope>0）
        TH_SHADOW = 4.0
        TH_VOL_RATIO = 1.2

        # C1 上影线
        if shadow_length_pct is None:
            c1_state, c1_desc, c1_val = "data_unavailable", "上影线数据缺失", None
        else:
            c1_hit = shadow_length_pct >= TH_SHADOW
            c1_state = "hit" if c1_hit else "miss"
            c1_desc = f"上影线 {shadow_length_pct:.2f}%（阈值≥{TH_SHADOW}%，{'长上影洗盘修复' if c1_hit else '上影不足'}）"
            c1_val = f"{shadow_length_pct:.2f}%"
        # C2 放量
        if volume_breakout_ratio is None:
            c2_state, c2_desc, c2_val = "data_unavailable", "放量数据缺失", None
        else:
            c2_hit = volume_breakout_ratio >= TH_VOL_RATIO
            c2_state = "hit" if c2_hit else "miss"
            c2_desc = f"今量/前5日均量={volume_breakout_ratio:.2f}（阈值≥{TH_VOL_RATIO}）"
            c2_val = f"{volume_breakout_ratio:.2f}"
        # C3 5日线向上
        if ma5_slope is None:
            c3_state, c3_desc, c3_val = "data_unavailable", "5日线斜率数据缺失", None
        else:
            c3_hit = ma5_slope > 0
            c3_state = "hit" if c3_hit else "miss"
            c3_desc = f"5日均线斜率 {ma5_slope:.6f}（{'向上' if c3_hit else '非向上'}）"
            c3_val = f"{ma5_slope:.6f}"

        conditions = [
            ConditionEval(condition_id="pattern_reversal.c1", condition_name="上影线",
                factor="shadow_length_pct", threshold=f">= {TH_SHADOW}", actual_value=c1_val,
                state=c1_state, description=c1_desc),
            ConditionEval(condition_id="pattern_reversal.c2", condition_name="放量",
                factor="volume_breakout_ratio", threshold=f">= {TH_VOL_RATIO}", actual_value=c2_val,
                state=c2_state, description=c2_desc),
            ConditionEval(condition_id="pattern_reversal.c3", condition_name="5日线向上",
                factor="ma5_slope", threshold="> 0", actual_value=c3_val,
                state=c3_state, description=c3_desc),
        ]
        hit_count = sum(1 for c in conditions if c.state == "hit")
        fired = hit_count >= 2
        confidence = (1.0 if hit_count == 3 else 0.7) if fired else None
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=len(conditions), fired=fired,
            fire_rule="≥2/3 命中", confidence=confidence, data_ok=True,
        )

    def compute_confidence(self, matches, ctx) -> float:
        # 3 命中 high / 2 命中 medium
        return 1.0 if len(matches) == 3 else 0.7

    def compute_entry_price(self, ctx) -> float:
        """R2/C7：触发价 = tick 对齐的（涨停价 pool_item.p + 0.01）；
        pool_item 缺失时 fallback gene.total_score（价格代理，调度器加标注）。"""
        if ctx.pool_item and ctx.pool_item.get("p"):
            return _round_to_tick_size(float(ctx.pool_item["p"]) + 0.01)
        return round(float(ctx.gene.total_score), 2)
