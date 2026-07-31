"""S007 契约层 — 公司基本面模型（财务/估值分位/公司信息）。

S008 T13d 新增。对齐 astock.financials / valuation_percentile / individual_info 返回：
- Financials：营收/净利/ROE/毛利率/净利率/报告期
- ValuationPercentile：PE-TTM / PB 历史分位（百分数）
- CompanyInfo：行业 / 上市日期

注：astock.financials 走 akshare（数值口径以 akshare 为准）；valuation_percentile
为东财 nested 结构 {pe_ttm:{percentile}, pb:{percentile}}；individual_info 为
akshare {行业, 上市时间, 上市日期}。mapper 集中字段抽取。
"""

from pydantic import BaseModel, ConfigDict


class Financials(BaseModel):
    """财务摘要（akshare 口径）。"""

    model_config = ConfigDict(frozen=True)

    revenue: float | None = None  # 营收
    net_profit: float | None = None  # 净利
    roe: float | None = None  # ROE
    gross_margin: float | None = None  # 毛利率
    net_margin: float | None = None  # 净利率
    period: str | None = None  # 报告期


class ValuationPercentile(BaseModel):
    """估值历史分位（百分数）。"""

    model_config = ConfigDict(frozen=True)

    pe_ttm_percentile: float | None = None  # PE-TTM 历史分位
    pb_percentile: float | None = None  # PB 历史分位


class CompanyInfo(BaseModel):
    """公司基本信息。"""

    model_config = ConfigDict(frozen=True)

    industry: str | None = None  # 行业
    listing_date: str | None = None  # 上市时间/上市日期


class ConceptBlock(BaseModel):
    """概念板块（astock.concept_blocks，S008 T13e 新增）。"""

    model_config = ConfigDict(frozen=True)

    name: str | None = None  # 概念板块名


class Announcement(BaseModel):
    """公司公告（astock.announcements，S008 T13e 新增）。

    与 ``News`` 不同：News 是新闻口径（content/source/keywords），
    Announcement 是公告口径（title/date/type）——字段集不同，并列不互投。
    """

    model_config = ConfigDict(frozen=True)

    title: str | None = None
    date: str | None = None
    type: str | None = None
