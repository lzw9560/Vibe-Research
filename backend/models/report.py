"""S007 契约层 — Report 研报模型。

字段对齐 astock.eastmoney_reports 返回（§5.1 单位冻结约定）：
- target_price: 元
- publish_date: YYYY-MM-DD
- report_type: 由 ratingName 映射（买入/增持/中性/减持/卖出）
"""

from pydantic import BaseModel, ConfigDict

from models.enums import Market, ReportType


class Report(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    market: Market
    title: str | None = None
    org: str | None = None  # 机构
    researcher: str | None = None
    publish_date: str | None = None  # YYYY-MM-DD
    report_type: ReportType | None = None  # 由 ratingName 映射
    rating_change: str | None = None  # ratingChangeName
    target_price: float | None = None  # 元
    eps_forecast: float | None = None
    updated_at: str | None = None  # ISO+08:00
