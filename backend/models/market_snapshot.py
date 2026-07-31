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


class IndustrySector(BaseModel):
    """行业板块涨跌统计（astock.industry_comparison 口径，S008 T13e 新增）。

    与 ``Sector`` 不同：Sector 是资金流口径（pct/net/inflow/outflow/firms），
    IndustrySector 是涨跌家数口径（change_pct/up_count/down_count）——
    数据源 industry_comparison，字段集不同，并列不互投。
    """

    model_config = ConfigDict(frozen=True)

    name: str
    change_pct: float | None = None  # 行业涨跌幅，百分数
    up_count: int | None = None  # 上涨家数
    down_count: int | None = None  # 下跌家数


class MarketSnapshot(BaseModel):
    """市场总览快照（情绪 + 板块）。"""

    model_config = ConfigDict(frozen=True)

    emotion: Emotion | None = None
    sectors: tuple[Sector, ...] = ()  # tuple 保 frozen 深度不可变
    updated: str | None = None  # ISO+08:00


class LianbanStock(BaseModel):
    """连板股榜原始行（客观榜单出口，非聚合情绪指标）。

    弱合规（CLAUDE.md §1）：私人助理场景下连板榜可如实呈现；与 ``Emotion`` 聚合
    分层——Emotion 留干净计数/比率，lianban_stocks 作为同响应的并列榜单出口。
    """

    model_config = ConfigDict(frozen=True)

    code: str
    name: str | None = None
    boards: int | None = None  # 连板数
    price: float | None = None
    pct: float | None = None  # 涨跌幅，百分数
    amount: float | None = None  # 成交额，元
    float_cap: float | None = None  # 流通市值，元
    industry: str | None = None


class EmotionResponse(BaseModel):
    """短线情绪响应：clean ``Emotion`` 聚合 + ``lianban_stocks`` 客观榜单并列出口。

    T10：``/api/market/emotion`` 返本模型。Emotion 子对象零个股名（聚合干净），
    lianban_stocks 同层暴露连板榜单（前端 DailyReview 消费）。
    """

    model_config = ConfigDict(frozen=True)

    emotion: Emotion
    lianban_stocks: tuple[LianbanStock, ...] = ()
    date: str | None = None
    lianban_count: int | None = None  # 2板+家数
    zb_count: int | None = None  # 炸板数
    yzt_count: int | None = None  # 昨涨停数


class ZTPoolItem(BaseModel):
    """涨停四池原始行（em_zt_topic_pool 单项，客观池出口）。

    S008 T13c 新增。字段对齐东财 push2ex 池返回（raw 键→model 字段）：
    - ``c``→code、``n``→name、``lbc``→boards（连板数）、``fbt``→seal_time（封板时间）、
      ``zbc``→broken_count（炸板次数）、``zje``→limit_price（涨停价）、``open``→open（开盘价）、
      ``seal_amount``→seal_amount（封单额，元）、``float_shares``→float_shares（流通盘，股）、
      ``prev_close``→prev_close（昨收价）、``zdp``→limit_pct（涨停涨幅）、``hybk``→industry（行业）。
    - ``pool_date``：合成字段，由 limitup_screener.service 注入（池日期），非东财原返回。
    与 ``LianbanStock`` 不同：LianbanStock 来自 market._emotion 连板榜（市值/涨跌幅口径），
    ZTPoolItem 来自涨停池（封单额/流通盘口径），两者并列、不互投。
    """

    model_config = ConfigDict(frozen=True)

    code: str
    name: str | None = None
    boards: float | None = None  # 连板数（lbc）
    seal_time: float | None = None  # 封板时间（fbt）
    broken_count: float | None = None  # 炸板次数（zbc）
    limit_price: float | None = None  # 涨停价（zje）
    open: float | None = None  # 开盘价
    seal_amount: float | None = None  # 封单额，元
    float_shares: float | None = None  # 流通盘，股
    prev_close: float | None = None  # 昨收价
    limit_pct: float | None = None  # 涨停涨幅（zdp）
    industry: str | None = None  # 行业（hybk）
    pool_date: str | None = None  # 合成：池日期（service 注入）
