# -*- coding: utf-8 -*-
"""S086 B2：读 pool_item 涨停池原始字段的战法（pool_based）。

战法：storm_reversal（封板时间≤10:30，读 pool_item["fbt"]）。

旧 storm_reversal 不在 STRATEGY_REGISTRY、无 match 分支、"无条件放行"——
spec §2.1/§5.4/A9 将其定性为 bug（其真实条件是封板时间≤10:30），
本实现补 match 分支，读 pool_item["fbt"]。
"""
from __future__ import annotations

from strategies.strategy_base import (
    BaseStrategy, ConditionMatch, ConditionEval, StrategyMatchResult, make_data_unavailable_result,
)


# 封板时间阈值：≤10:30（数字 103000，涨停池 fbt 字段 92500-145000）
_STORM_SEAL_TIME_MAX = 103000


class StormReversalStrategy(BaseStrategy):
    """暴风雨逆势涨停：封板时间≤10:30（pool_item["fbt"]≤103000），confidence=固定 0.7。"""

    code = "storm_reversal"
    name = "暴风雨逆势涨停"

    def match(self, ctx) -> StrategyMatchResult:
        # S097：C1 早盘封板 fbt<=103000；无 pool_item → data_ok=False 整战法降级
        pi = ctx.pool_item
        if not pi:
            return make_data_unavailable_result(self.code, self.name, [
                ("storm_reversal.c1", "早盘封板", "fbt", "<= 103000"),
            ])
        fbt = pi.get("fbt")
        # fbt 为数字（92500-145000）；防御字符串/None
        if fbt is None:
            c1_state, c1_desc, c1_val = "data_unavailable", "封板时间(fbt)数据缺失", None
        else:
            try:
                fbt_num = float(fbt)
                if fbt_num <= _STORM_SEAL_TIME_MAX:
                    c1_state, c1_desc, c1_val = "hit", f"首封时间 {fbt}（≤10:30，早盘封板）", str(fbt)
                else:
                    c1_state, c1_desc, c1_val = "miss", f"首封时间 {fbt}（>10:30，非早盘封板）", str(fbt)
            except (TypeError, ValueError):
                c1_state, c1_desc, c1_val = "data_unavailable", f"封板时间格式异常：{fbt}", None
        conditions = [ConditionEval(
            condition_id="storm_reversal.c1", condition_name="早盘封板",
            factor="fbt", threshold="<= 103000", actual_value=c1_val,
            state=c1_state, description=c1_desc,
        )]
        fired = c1_state == "hit"
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=(1 if fired else 0), total_count=1, fired=fired,
            fire_rule="全条件命中",
            confidence=0.7 if fired else None, data_ok=True,
        )

    def compute_confidence(self, matches, ctx) -> float:
        return 0.7
