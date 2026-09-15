# -*- coding: utf-8 -*-
"""S086 战法实现包（impl/）：按数据依赖维度分 4 文件，共 15 个 Strategy 实现。

- gene_based（11）：first_plate / consecutive_relay / break_reseal / low_absorption /
  n_shape_counterattack / platform_breakout / end_of_day_sneak / dragon_head
  + first_board_limitup（S203 首板涨停，板块共振+封单精品）/ leader_drop_reversal（S203 龙头大跌反包）
  / relay_23（S203 接力二三板，当下连板 lbc≥2+量比[1.5,2.5]+Dragon Score 占位）
- pool_based（1）：storm_reversal
- indicator_based（2）：weak_turn_strong / pattern_reversal
- db_based（1）：reverse_package
"""
from __future__ import annotations

from strategies.impl.gene_based import (
    BreakResealStrategy,
    ConsecutiveRelayStrategy,
    DragonHeadStrategy,
    EndOfDaySneakStrategy,
    FirstBoardLimitupStrategy,
    FirstPlateStrategy,
    LeaderDropReversalStrategy,
    LowAbsorptionStrategy,
    NShapeCounterattackStrategy,
    PlatformBreakoutStrategy,
    Relay23Strategy,
)
from strategies.impl.pool_based import StormReversalStrategy
from strategies.impl.indicator_based import (
    PatternReversalStrategy,
    WeakTurnStrongStrategy,
)
from strategies.impl.db_based import ReversePackageStrategy

__all__ = [
    "FirstPlateStrategy",
    "FirstBoardLimitupStrategy",
    "ConsecutiveRelayStrategy",
    "BreakResealStrategy",
    "LowAbsorptionStrategy",
    "NShapeCounterattackStrategy",
    "PlatformBreakoutStrategy",
    "EndOfDaySneakStrategy",
    "DragonHeadStrategy",
    "LeaderDropReversalStrategy",
    "Relay23Strategy",
    "StormReversalStrategy",
    "WeakTurnStrongStrategy",
    "PatternReversalStrategy",
    "ReversePackageStrategy",
]
