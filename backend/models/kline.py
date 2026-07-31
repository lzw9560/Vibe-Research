"""S007 契约层 — KLine K线模型。

字段对齐 astock.kline 真实返回（§5.1 单位冻结约定）：
- KLineBar.open / close / high / low: 元
- KLineBar.volume: 成交手数（或股数，与 astock 原始口径一致）
- KLineBar.turnover: 元
- KLineBar.amplitude: 百分数（如 3.03 表示 3.03%）
- KLineBar.date: ISO 8601 日期格式（YYYY-MM-DD）

KLine 模型聚合单只股票的 K 线序列（bars），兼容前端图表组件消费。
"""

from pydantic import BaseModel, ConfigDict

from models.enums import Market


class KLineBar(BaseModel):
    """单根 K 线数据（OHLCV）。"""

    model_config = ConfigDict(frozen=True)

    date: str  # YYYY-MM-DD
    open: float  # 元
    close: float  # 元
    high: float  # 元
    low: float  # 元
    volume: int | None = None  # 手
    turnover: float | None = None  # 元
    amplitude: float | None = None  # 百分数


class KLine(BaseModel):
    """单只股票 K 线序列。"""

    model_config = ConfigDict(frozen=True)

    code: str
    market: Market
    bars: tuple[KLineBar, ...] = ()  # tuple 保证 frozen 模型的深度不可变
