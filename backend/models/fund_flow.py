"""S007 契约层 — FundFlow 资金流模型。

字段对齐 astock.stock_fund_flow_120d / fallback JSON 真实返回（§5.1 单位冻结约定）：
- main_net / super_large_net / large_net / medium_net / small_net: 元
"""

from pydantic import BaseModel, ConfigDict

from models.enums import Market


class FundFlow(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    market: Market
    date: str | None = None
    main_net: float | None = None  # 主力净流入，元
    super_large_net: float | None = None  # 超大单
    large_net: float | None = None  # 大单
    medium_net: float | None = None  # 中单
    small_net: float | None = None  # 小单
