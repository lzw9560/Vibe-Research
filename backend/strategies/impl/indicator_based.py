# -*- coding: utf-8 -*-
"""S086 B3：读 IndicatorSet K线派生因子的 2 个复杂战法（indicator_based）。

战法：weak_turn_strong / pattern_reversal（S081 PRD P2）。

5 因子硬阈值（≥4 命中输出），阈值探索性（外部 PRD 拍定，零数据支撑），进 config 可配。
derived 从 ctx.derived 读（不上提取数——调度器 _prepare_derived 已统一准备）。
match 条件/阈值/confidence 严格按 limitup_strategy.py:822-962 迁移，不改阈值。
"""
from __future__ import annotations

from strategies.strategy_base import BaseStrategy, ConditionMatch, _round_to_tick_size


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

    def match(self, ctx) -> list[ConditionMatch]:
        pool_item = ctx.pool_item
        lbc = int(pool_item.get("lbc") or 0) if pool_item else 0
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

        f1 = lbc >= TH_LBC
        f2 = broken_duration_min is not None and broken_duration_min >= TH_BROKEN
        f3 = max_drop_pct is not None and max_drop_pct >= TH_DROP
        f4 = last_lock_time is not None and last_lock_time >= f"2026-01-01T{TH_LOCK}"
        f5 = vol_ratio_1d is not None and TH_VOL_LO <= vol_ratio_1d <= TH_VOL_HI
        hit_count = sum([f1, f2, f3, f4, f5])

        if hit_count < 4:
            return []

        matches: list[ConditionMatch] = []
        if f1:
            matches.append(ConditionMatch(
                condition="连板天数达标", value=f"lbc={lbc}",
                description=f"策略逻辑上，连板 {lbc} 日（阈值≥{TH_LBC}）",
            ))
        if f2:
            matches.append(ConditionMatch(
                condition="炸板时长达标", value=f"broken={broken_duration_min:.1f}min",
                description=f"策略逻辑上，炸板累计 {broken_duration_min:.1f} 分钟（阈值≥{TH_BROKEN}min，60s粒度近似）",
            ))
        if f3:
            matches.append(ConditionMatch(
                condition="回撤幅度达标", value=f"max_drop={max_drop_pct:.2f}%",
                description=f"策略逻辑上，炸板后回撤 {max_drop_pct:.2f}%（阈值≥{TH_DROP}%）",
            ))
        if f4:
            matches.append(ConditionMatch(
                condition="尾盘封死达标", value=f"last_lock={last_lock_time}",
                description=f"策略逻辑上，最后封死时刻 {last_lock_time}（阈值≥{TH_LOCK}）",
            ))
        if f5:
            matches.append(ConditionMatch(
                condition="换手倍数达标", value=f"vol_ratio={vol_ratio_1d:.2f}",
                description=f"策略逻辑上，换手倍数 {vol_ratio_1d:.2f}（区间 {TH_VOL_LO}-{TH_VOL_HI}）",
            ))
        return matches

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

    def match(self, ctx) -> list[ConditionMatch]:
        # S094 R5：改读 PatternScan（不读 ctx.indicators）
        pattern = _get_pattern(ctx)
        if pattern is None:
            # S1 阶段涨停 pipeline 无 market_scan_ctx → 不命中（诚实降级，不臆造）
            return []

        shadow_length_pct = getattr(pattern, "shadow_length_pct", None)
        volume_breakout_ratio = pattern.volume_breakout_ratio
        ma5_slope = getattr(pattern, "ma5_slope", None)

        # 3 字段阈值（spec §3.R5/L：shadow>=4 / vol_ratio>=1.2 / ma5_slope>0）
        TH_SHADOW = 4.0
        TH_VOL_RATIO = 1.2

        f1 = shadow_length_pct is not None and shadow_length_pct >= TH_SHADOW
        f2 = volume_breakout_ratio is not None and volume_breakout_ratio >= TH_VOL_RATIO
        f3 = ma5_slope is not None and ma5_slope > 0
        hit_count = sum([f1, f2, f3])

        if hit_count < 2:
            return []

        matches: list[ConditionMatch] = []
        if f1:
            matches.append(ConditionMatch(
                condition="上影线达标", value=f"shadow={shadow_length_pct:.2f}%",
                description=f"策略逻辑上，上影线 {shadow_length_pct:.2f}%（阈值≥{TH_SHADOW}%，长上影洗盘修复形态）",
            ))
        if f2:
            matches.append(ConditionMatch(
                condition="放量达标", value=f"vol_ratio={volume_breakout_ratio:.2f}",
                description=f"策略逻辑上，今量/前5日均量={volume_breakout_ratio:.2f}（阈值≥{TH_VOL_RATIO}）",
            ))
        if f3:
            matches.append(ConditionMatch(
                condition="5日线向上", value=f"ma5_slope={ma5_slope:.6f}",
                description="策略逻辑上，5日均线斜率向上（ma5_slope>0）",
            ))
        return matches

    def compute_confidence(self, matches, ctx) -> float:
        # 3 命中 high / 2 命中 medium
        return 1.0 if len(matches) == 3 else 0.7

    def compute_entry_price(self, ctx) -> float:
        """R2/C7：触发价 = tick 对齐的（涨停价 pool_item.p + 0.01）；
        pool_item 缺失时 fallback gene.total_score（价格代理，调度器加标注）。"""
        if ctx.pool_item and ctx.pool_item.get("p"):
            return _round_to_tick_size(float(ctx.pool_item["p"]) + 0.01)
        return round(float(ctx.gene.total_score), 2)
