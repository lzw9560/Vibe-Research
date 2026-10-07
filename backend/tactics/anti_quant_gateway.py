# -*- coding: utf-8 -*-
"""anti_quant_gateway —— 反量化拦截网关（S235 T04）。

三道防线，任一命中→信号压制（不推送，仍落库标 suppressed）：
1. check_auction_fake：竞价假抢筹——09:20 后（不可撤单阶段）量比断崖。
   早量高、晚量塌 = 早量是 09:20 前可撤单的假挂单。
2. check_tail_fake：尾盘小单偷袭——成交额<5000万，流动性过薄易被操纵。
3. check_wash_trading：对倒检测——均单价（成交额/成交量）偏离收盘价>5%，
   暗示匹配撮合的对倒单拉量不拉价。

阈值来源：spec §2.3 标"社区经验参数"，探索性。
"""
from __future__ import annotations

# 09:20 后量比断崖阈值：晚量 < 早量 × 0.5 → 判假抢筹
AUCTION_FAKE_RATIO = 0.5
# 尾盘小单偷袭阈值：成交额 < 5000 万
TAIL_FAKE_AMOUNT = 5e7
# 对倒检测阈值：均单价偏离收盘价 > 5%
WASH_DEVIATION = 0.05


class AntiQuantGateway:
    """反量化三防线。无状态，可独立调用。"""

    def check_auction_fake(self, live_1: dict, live_2: dict) -> bool:
        """防线1：竞价假抢筹。

        live_1=09:21 快照（早），live_2=09:23 快照（晚，09:20 后不可撤单）。
        晚量 < 早量 × 0.5 → 早量是 09:20 前可撤单的假挂单，判 True。
        早量<=0（无早量）→ 无法判定，返 False。
        """
        v1 = float(live_1.get("volume", 0) or 0)
        v2 = float(live_2.get("volume", 0) or 0)
        if v1 <= 0:
            return False
        return v2 < v1 * AUCTION_FAKE_RATIO

    def check_tail_fake(self, snapshot: dict) -> bool:
        """防线2：尾盘小单偷袭——成交额<5000万。

        0 成交额（停牌/无数据）不判为偷袭（返 False，由上游 halted 检查处理）。
        """
        amt = float(snapshot.get("amount", 0) or 0)
        return 0 < amt < TAIL_FAKE_AMOUNT

    def check_wash_trading(self, snapshot: dict) -> bool:
        """防线3：对倒检测——均单价偏离收盘价>5%。

        均单价 = 成交额 / 成交量。偏离 = |均单价 - 收盘价| / 收盘价。
        成交量<=0 或 收盘价<=0 → 无法计算，返 False。
        """
        amt = float(snapshot.get("amount", 0) or 0)
        vol = float(snapshot.get("volume", 0) or 0)
        close = float(snapshot.get("close_price", 0) or 0)
        if vol <= 0 or close <= 0:
            return False
        avg_price = amt / vol
        deviation = abs(avg_price - close) / close
        return deviation > WASH_DEVIATION

    def any_blocked(self, snapshot: dict, live_1: dict | None = None, live_2: dict | None = None) -> bool:
        """三防线任一命中→True（信号应压制）。

        便于上游一次性检查。auction 防线需要 live_1/live_2，未传则跳过。
        """
        if live_1 is not None and live_2 is not None:
            if self.check_auction_fake(live_1, live_2):
                return True
        if self.check_tail_fake(snapshot):
            return True
        if self.check_wash_trading(snapshot):
            return True
        return False
