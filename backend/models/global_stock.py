# -*- coding: utf-8 -*-
"""S007 契约层 — 美港股全局个股模型（T9）。

``GlobalStock`` 是 gstock.us_hk_stock 的响应契约：行情走扁平 ``Quote``（S007），
关键财务指标走 ``GlobalMetrics``（韩股 metrics=None）。嵌套 quote→扁平 Quote 是
T9 的核心；metrics 是财务基本面（非行情），独立子模型保留，不入 Quote。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from models.quote import Quote


class GlobalMetrics(BaseModel):
    """美港股关键财务指标（东财 datacenter GMAININDICATOR）。韩股无此数据。"""

    model_config = ConfigDict(frozen=True)

    report_date: str | None = None
    revenue: float | None = None  # 营业总收入
    revenue_yoy: float | None = None  # 同比
    net_profit: float | None = None  # 归母净利润
    eps: float | None = None  # 基本每股收益
    roe: float | None = None  # ROE
    gross_margin: float | None = None  # 毛利率
    net_margin: float | None = None  # 净利率
    debt_ratio: float | None = None  # 资产负债率


class GlobalStock(BaseModel):
    """美港股个股：扁平 Quote + 财务指标（韩股仅行情）。"""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str | None = None
    market: str | None = None  # 原始标签 NASDAQ/NYSE/US/HK/KR（展示用）
    quote: Quote
    metrics: GlobalMetrics | None = None
