# -*- coding: utf-8 -*-
"""S086 B3：读 IndicatorSet K线派生因子的 2 个复杂战法（indicator_based）。

战法：weak_turn_strong / pattern_reversal（S081 PRD P2）。

5 因子硬阈值（≥4 命中输出），阈值探索性（外部 PRD 拍定，零数据支撑），进 config 可配。
derived 从 ctx.derived 读（不上提取数——调度器 _prepare_derived 已统一准备）。
match 条件/阈值/confidence 严格按 limitup_strategy.py:822-962 迁移，不改阈值。
"""
from __future__ import annotations

from strategies.strategy_base import BaseStrategy, ConditionMatch, _round_to_tick_size


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
    """形态反包：5 因子硬阈值（close/high/shadow/vol/ma5）≥4 命中。

    confidence=1.0（5 命中）/ 0.7（4 命中）；override compute_entry_price 返回 pool_item.p+0.01。
    因子来自涨停池（zdp）+ K线扩展（indicators），不依赖 S070 R7。
    """

    code = "pattern_reversal"
    name = "形态反包"

    def match(self, ctx) -> list[ConditionMatch]:
        pool_item = ctx.pool_item
        close_pct = pool_item.get("zdp") if pool_item else None

        max_high_pct = None
        shadow_length_pct = None
        ma_5_status = None
        volume_1d = None
        volume_2d = None

        # K线派生因子从 indicators 读（消除重复取数）
        indicators = ctx.indicators
        if indicators is not None:
            max_high_pct = getattr(indicators, "max_high_pct", None)
            shadow_length_pct = getattr(indicators, "shadow_length_pct", None)
            ma_5_status = getattr(indicators, "ma_5_status", None)
            # S084 R4.3：volume 从 indicators.amount_yi/prev_amount_yi 算放量比
            _amt_1d = getattr(indicators, "amount_yi", None)
            _amt_2d = getattr(indicators, "prev_amount_yi", None)
            if _amt_1d is not None and _amt_2d is not None and _amt_2d > 0:
                volume_1d = _amt_1d
                volume_2d = _amt_2d

        # B6 5 因子硬阈值（PRD §2.2，阈值探索性）
        import config as _cfg_mod  # noqa: PLC0415
        _pr_cfg = getattr(_cfg_mod, "S081_PATTERN_REVERSAL", None) or {}
        TH_CLOSE = _pr_cfg.get("close_pct_max", 9.5)
        TH_HIGH = _pr_cfg.get("max_high_pct_min", 7.0)
        TH_SHADOW = _pr_cfg.get("shadow_length_pct_min", 4.0)
        TH_VOL_RATIO = _pr_cfg.get("volume_ratio_min", 1.2)
        TH_MA5 = _pr_cfg.get("ma_5_status", "Upward")

        f1 = close_pct is not None and close_pct < TH_CLOSE
        f2 = max_high_pct is not None and max_high_pct >= TH_HIGH
        f3 = shadow_length_pct is not None and shadow_length_pct >= TH_SHADOW
        f4 = (volume_1d is not None and volume_2d is not None
              and volume_2d > 0 and volume_1d > volume_2d * TH_VOL_RATIO)
        f5 = ma_5_status == TH_MA5
        hit_count = sum([f1, f2, f3, f4, f5])

        if hit_count < 4:
            return []

        matches: list[ConditionMatch] = []
        if f1:
            matches.append(ConditionMatch(
                condition="收盘涨幅未封涨停", value=f"close_pct={close_pct:.2f}%",
                description=f"策略逻辑上，收盘涨幅 {close_pct:.2f}%（阈值<{TH_CLOSE}%）",
            ))
        if f2:
            matches.append(ConditionMatch(
                condition="最高涨幅达标", value=f"max_high={max_high_pct:.2f}%",
                description=f"策略逻辑上，最高涨幅 {max_high_pct:.2f}%（阈值≥{TH_HIGH}%）",
            ))
        if f3:
            matches.append(ConditionMatch(
                condition="上影线达标", value=f"shadow={shadow_length_pct:.2f}%",
                description=f"策略逻辑上，上影线 {shadow_length_pct:.2f}%（阈值≥{TH_SHADOW}%）",
            ))
        if f4:
            matches.append(ConditionMatch(
                condition="放量达标", value=f"vol_ratio={volume_1d / volume_2d:.2f}",
                description=f"策略逻辑上，今日量/前日量={volume_1d / volume_2d:.2f}（阈值≥{TH_VOL_RATIO}）",
            ))
        if f5:
            matches.append(ConditionMatch(
                condition="5日线向上", value=f"ma_5={ma_5_status}",
                description=f"策略逻辑上，5日均线 {ma_5_status}（阈值={TH_MA5}）",
            ))
        return matches

    def compute_confidence(self, matches, ctx) -> float:
        return 1.0 if len(matches) == 5 else 0.7

    def compute_entry_price(self, ctx) -> float:
        """R2/C7：触发价 = tick 对齐的（涨停价 pool_item.p + 0.01）；
        pool_item 缺失时 fallback gene.total_score（价格代理，调度器加标注）。"""
        if ctx.pool_item and ctx.pool_item.get("p"):
            return _round_to_tick_size(float(ctx.pool_item["p"]) + 0.01)
        return round(float(ctx.gene.total_score), 2)
