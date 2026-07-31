"""S007 契约层 — Quote 行情模型。

字段对齐 astock.tencent_quote 返回（§5.1 单位冻结约定）：
- price: 元
- change_pct: 百分数（如 2.34 表示 +2.34%）
- market_cap / float_market_cap: 元（派生 market_cap_yi 兼容展示）
- volume: 手
- turnover: 元
- updated_at: ISO 8601 + 08:00

注：``last_close``（昨收）为 S008 T1 加入的可选字段——前端 StockDeep「昨收」卡片消费，
原 raw 有此字段但初版 Quote 漏收。向后兼容（默认 None），不破坏既有消费者。

S008 T13a 再补 5 个可选字段（均向后兼容，默认 None）：
- ``open``（开盘价，元）—— bidding_monitor 竞价快照消费，原 raw 有、初版 Quote 漏收
- ``high`` / ``low``（最高 / 最低，元）—— 补齐 tencent raw 全字段
- ``vol_ratio``（量比）—— bidding_monitor + candidate_funnel/sources/activity 消费，
  原 raw 有、初版 Quote 漏收（plan-stage1 警告的丢字段风险项）
- ``pe_static``（静态 PE）—— 补齐 tencent raw 全字段
"""

from pydantic import BaseModel, ConfigDict

from models.enums import Market


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    market: Market
    name: str | None = None
    price: float | None
    change_pct: float | None = None
    change_amount: float | None = None
    volume: int | None = None  # 手
    turnover: float | None = None  # 元
    market_cap: float | None = None  # 元
    float_market_cap: float | None = None  # 元
    pe_ttm: float | None = None
    pb: float | None = None
    turnover_rate: float | None = None  # 百分数
    amplitude: float | None = None  # 百分数
    limit_up_price: float | None = None
    limit_down_price: float | None = None
    last_close: float | None = None  # 昨收（S008 T1 加，前端「昨收」卡片用）
    open: float | None = None  # 开盘价（S008 T13a 加，bidding_monitor 竞价快照用）
    high: float | None = None  # 最高（S008 T13a 补齐 raw 全字段）
    low: float | None = None  # 最低（S008 T13a 补齐 raw 全字段）
    vol_ratio: float | None = None  # 量比（S008 T13a 加，bidding_monitor/activity 用）
    pe_static: float | None = None  # 静态 PE（S008 T13a 补齐 raw 全字段）
    updated_at: str | None = None  # ISO+08:00

    @property
    def market_cap_yi(self) -> float | None:
        """总市值（亿元），展示层兼容属性。"""
        if self.market_cap is None:
            return None
        return self.market_cap / 1e8
