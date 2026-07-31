"""S007 契约层 — Quote 行情模型。

字段对齐 astock.tencent_quote 返回（§5.1 单位冻结约定）：
- price: 元
- change_pct: 百分数（如 2.34 表示 +2.34%）
- market_cap / float_market_cap: 元（派生 market_cap_yi 兼容展示）
- volume: 手
- turnover: 元
- updated_at: ISO 8601 + 08:00
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
    updated_at: str | None = None  # ISO+08:00

    @property
    def market_cap_yi(self) -> float | None:
        """总市值（亿元），展示层兼容属性。"""
        if self.market_cap is None:
            return None
        return self.market_cap / 1e8
