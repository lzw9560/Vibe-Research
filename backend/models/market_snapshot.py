"""S007 契约层 — MarketSnapshot 市场快照模型。

合规重点：Emotion 聚合情绪不含个股名字段（零个股名红线）。
字段对齐 market.get_overview() / market._emotion() 返回：
- Emotion: 连板梯队 / 涨停家数 / 跌停家数 / 封板率 / 炸板率 / 晋级率
- Sector: 行业资金流（name / pct / net / inflow / outflow / firms）
"""

from pydantic import BaseModel, ConfigDict


class Emotion(BaseModel):
    """短线情绪聚合指标（零个股名）。"""

    model_config = ConfigDict(frozen=True)

    max_boards: int | None = None  # 最高连板
    limit_up_count: int | None = None  # 涨停家数
    limit_down_count: int | None = None  # 跌停家数
    seal_rate: float | None = None  # 封板率（百分数）
    broken_rate: float | None = None  # 炸板率
    advance_rate: float | None = None  # 晋级率
    ladder: tuple[dict, ...] = ()  # 连板梯队，每项 {boards,count}，tuple 保深度不可变


class Sector(BaseModel):
    """行业资金流（板块级）。"""

    model_config = ConfigDict(frozen=True)

    name: str
    pct: float | None = None  # 行业涨跌幅，百分数
    net: float | None = None  # 净额，元
    inflow: float | None = None
    outflow: float | None = None
    firms: int | None = None


class MarketSnapshot(BaseModel):
    """市场总览快照（情绪 + 板块）。"""

    model_config = ConfigDict(frozen=True)

    emotion: Emotion | None = None
    sectors: tuple[Sector, ...] = ()  # tuple 保 frozen 深度不可变
    updated: str | None = None  # ISO+08:00
