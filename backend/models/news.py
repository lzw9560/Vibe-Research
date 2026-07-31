"""S007 契约层 — News 新闻模型。

字段对齐 astock.stock_news 返回（akshare stock_news_em）：
- title: 新闻标题
- content: 新闻内容
- publish_time: 发布时间
- source: 文章来源
- keywords: 关键词（逗号分隔）
"""

from pydantic import BaseModel, ConfigDict

from models.enums import Market


class News(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    market: Market
    title: str | None = None  # 新闻标题
    content: str | None = None  # 新闻内容
    publish_time: str | None = None  # 发布时间
    source: str | None = None  # 文章来源
    keywords: str | None = None  # 关键词，可逗号串
