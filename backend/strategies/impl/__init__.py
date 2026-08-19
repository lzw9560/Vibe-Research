# -*- coding: utf-8 -*-
"""S086 战法实现包（impl/）：按数据依赖维度分 4 文件，共 12 个 Strategy 实现。

- gene_based（8）：first_plate / consecutive_relay / break_reseal / low_absorption /
  n_shape_counterattack / platform_breakout / end_of_day_sneak / dragon_head
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
    FirstPlateStrategy,
    LowAbsorptionStrategy,
    NShapeCounterattackStrategy,
    PlatformBreakoutStrategy,
)
from strategies.impl.pool_based import StormReversalStrategy
from strategies.impl.indicator_based import (
    PatternReversalStrategy,
    WeakTurnStrongStrategy,
)
from strategies.impl.db_based import ReversePackageStrategy

__all__ = [
    "FirstPlateStrategy",
    "ConsecutiveRelayStrategy",
    "BreakResealStrategy",
    "LowAbsorptionStrategy",
    "NShapeCounterattackStrategy",
    "PlatformBreakoutStrategy",
    "EndOfDaySneakStrategy",
    "DragonHeadStrategy",
    "StormReversalStrategy",
    "WeakTurnStrongStrategy",
    "PatternReversalStrategy",
    "ReversePackageStrategy",
]
