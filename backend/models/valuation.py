"""S007 契约层 — Valuation 估值模型。

字段对齐 astock.full_valuation / tencent_quote 真实返回（§5.1 单位冻结约定）：
- price: 元
- market_cap: 元（来自 tencent_quote mcap_yi * 1e8）
- pe_ttm / pb / ps_ttm / peg / forward_pe / consensus_eps / cagr_pct / digest_years:
  来自 full_valuation 计算或 tencent_quote 原始字段
- dividend_yield: 百分数（如 1.35 表示 1.35%）
- updated_at: ISO 8601 + 08:00
"""

from pydantic import BaseModel, ConfigDict

from models.enums import Market


class Valuation(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    market: Market
    name: str | None = None
    price: float | None = None  # 元
    market_cap: float | None = None  # 元
    pe_ttm: float | None = None
    pb: float | None = None
    ps_ttm: float | None = None
    pcf_ttm: float | None = None  # S106：hithink 补（东财结构性缺）
    dividend_yield: float | None = None  # 百分数
    peg: float | None = None
    forward_pe: float | None = None
    consensus_eps: float | None = None
    cagr_pct: float | None = None  # 百分数
    digest_years: float | None = None
    analyst_count: int | None = None
    updated_at: str | None = None  # ISO+08:00
    discrepancy: list[dict] | None = None  # S106：cross_validate 仲裁结果透传（[{field,verdict,deviation_pct}]）
    data_status: str | None = None  # S131 R3：PS/PCF 源断标 'hithink_unavailable'（非"无估值"），mapper 透传
