# -*- coding: utf-8 -*-
"""S086 B2：读 pool_item 涨停池原始字段的战法（pool_based）。

战法：storm_reversal（封板时间≤10:30，读 pool_item["fbt"]）。

旧 storm_reversal 不在 STRATEGY_REGISTRY、无 match 分支、"无条件放行"——
spec §2.1/§5.4/A9 将其定性为 bug（其真实条件是封板时间≤10:30），
本实现补 match 分支，读 pool_item["fbt"]。
"""
from __future__ import annotations

from strategies.strategy_base import BaseStrategy, ConditionMatch


# 封板时间阈值：≤10:30（数字 103000，涨停池 fbt 字段 92500-145000）
_STORM_SEAL_TIME_MAX = 103000


class StormReversalStrategy(BaseStrategy):
    """暴风雨逆势涨停：封板时间≤10:30（pool_item["fbt"]≤103000），confidence=固定 0.7。"""

    code = "storm_reversal"
    name = "暴风雨逆势涨停"

    def match(self, ctx) -> list[ConditionMatch]:
        pi = ctx.pool_item
        if not pi:
            return []
        fbt = pi.get("fbt")
        # fbt 为数字（92500-145000）；防御字符串/None
        try:
            if fbt is None or float(fbt) > _STORM_SEAL_TIME_MAX:
                return []
        except (TypeError, ValueError):
            return []
        return [ConditionMatch(
            condition="封板时间≤10:30",
            value=f"首封时间 {fbt}",
            description="策略逻辑上，该股早盘（≤10:30）封板，暴风雨天逆势涨停特征",
        )]

    def compute_confidence(self, matches, ctx) -> float:
        return 0.7
