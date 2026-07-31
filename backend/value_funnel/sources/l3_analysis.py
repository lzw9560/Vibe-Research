"""S005 L3 精细分析骨架：对单只标的结构化要点（商业模式/护城河/财务/估值位置/风险）。

合规：估值位置只标位置不划买卖线；counter_arguments 反面论据占位（呈现正反两面）；
结论交用户 AI，系统只备数据与占位。
"""

from __future__ import annotations

from datetime import datetime

from models import Financials, ValuationPercentile

from .. import models


def build_analysis_skeleton(code: str, name: str = "") -> models.CompanyAnalysis:
    """构建 L3 精细分析骨架。客观数据系统填，结论留空交 AI。"""
    import astock
    from data.mappers import (
        company_info_from_individual_info,
        financials_from_dict,
        valuation_percentile_from_dict,
    )

    fin = Financials()
    try:
        fin = financials_from_dict(astock.financials(code) or {})
    except Exception:
        pass

    val = ValuationPercentile()
    try:
        val = valuation_percentile_from_dict(astock.valuation_percentile(code) or {})
    except Exception:
        pass

    # 财务摘要（客观事实）
    fin_sum = ""
    parts = []
    if fin.revenue is not None:
        parts.append(f"营收 {fin.revenue}")
    if fin.net_profit is not None:
        parts.append(f"净利 {fin.net_profit}")
    if fin.roe is not None:
        parts.append(f"ROE {fin.roe}")
    if fin.gross_margin is not None:
        parts.append(f"毛利率 {fin.gross_margin}")
    if fin.net_margin is not None:
        parts.append(f"净利率 {fin.net_margin}")
    fin_sum = "；".join(parts) + (f"（{fin.period}）" if fin.period else "")

    # 估值位置（只标位置不划买卖线）
    val_pos = ""
    if val.pe_ttm_percentile is not None:
        val_pos = f"PE-TTM 处历史 {val.pe_ttm_percentile}% 分位"
    if val.pb_percentile is not None:
        val_pos += f"；PB 处 {val.pb_percentile}% 分位"

    # 商业模式（来自行业+名称，客观）
    industry = ""
    try:
        info = company_info_from_individual_info(astock.individual_info(code) or {})
        industry = info.industry or ""
    except Exception:
        pass
    biz = f"{name or code}（{industry}）" if industry else (name or code)

    return models.CompanyAnalysis(
        code=code,
        name=name or code,
        business_model=biz,
        moat_evidence="（见 L2 护城河代理信号；综合判断交 AI）",
        financials_summary=fin_sum or "（财务数据未取得）",
        valuation_position=val_pos or "（估值分位未取得）",
        risks=["（待 AI 补：行业/竞争/财务/监管风险）"],
        counter_arguments=["（待 AI 补：反面论据）"],
        as_of=datetime.now(),
    )
