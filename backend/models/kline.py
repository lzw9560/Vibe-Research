"""S007 契约层 — KLine K线模型。

字段对齐 astock.kline 真实返回（§5.1 单位冻结约定）：
- KLineBar.open / close / high / low: 元
- KLineBar.volume: 成交手数（或股数，与 astock 原始口径一致）
- KLineBar.turnover: 元
- KLineBar.amplitude: 百分数（如 3.03 表示 3.03%）
- KLineBar.date: ISO 8601 日期格式（YYYY-MM-DD）

KLine 模型聚合单只股票的 K 线序列（bars），兼容前端图表组件消费。

S008 T13b 契约放宽（向后兼容）：``date`` / ``open`` / ``high`` / ``low`` / ``close``
由 required 改为 optional（默认 ``None``）。原因：astock.kline（mootdx 源）真实返回
及测试 fixture 可能为部分 bar（仅 close+amount，缺 OHLC/date 之一）；required 模型
无法建模此类部分 bar，迁移 kline 消费者（risk_models/backtest_lite）时会被卡住。
改 optional 后，缺字段=``None``（诚实「无数据」），不臆造 0；消费者按需 filter None。
既有提供全字段的 KLine 构造不受影响。
"""

from pydantic import BaseModel, ConfigDict

from models.enums import Market


class KLineBar(BaseModel):
    """单根 K 线数据（OHLCV）。"""

    model_config = ConfigDict(frozen=True)

    date: str | None = None  # YYYY-MM-DD（S008 T13b 放宽为可选）
    open: float | None = None  # 元（S008 T13b 放宽为可选）
    close: float | None = None  # 元（S008 T13b 放宽为可选）
    high: float | None = None  # 元（S008 T13b 放宽为可选）
    low: float | None = None  # 元（S008 T13b 放宽为可选）
    volume: int | None = None  # 手
    turnover: float | None = None  # 元
    amplitude: float | None = None  # 百分数


class KLine(BaseModel):
    """单只股票 K 线序列。"""

    model_config = ConfigDict(frozen=True)

    code: str
    market: Market
    bars: tuple[KLineBar, ...] = ()  # tuple 保证 frozen 模型的深度不可变
