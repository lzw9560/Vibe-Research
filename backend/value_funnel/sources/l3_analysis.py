"""S005 L3 精细分析骨架：对单只标的结构化要点（商业模式/护城河/财务/估值位置/风险）。

合规：估值位置只标位置不划买卖线；counter_arguments 反面论据占位（呈现正反两面）；
结论交用户 AI，系统只备数据与占位。
"""

from __future__ import annotations

from datetime import datetime

from .. import models


def build_analysis_skeleton(code: str, name: str = "") -> models.CompanyAnalysis:
    """构建 L3 精细分析骨架。客观数据系统填，结论留空交 AI。"""
    import astock

    fin = {}
    try:
        fin = astock.financials(code) or {}
    except Exception:
        fin = {}

    val = {}
    try:
        val = astock.valuation_percentile(code) or {}
    except Exception:
        val = {}

    # 财务摘要（客观事实）
    fin_sum = ""
    if fin:
        parts = []
        if fin.get("revenue"):
            parts.append(f"营收 {fin['revenue']}")
        if fin.get("net_profit"):
            parts.append(f"净利 {fin['net_profit']}")
        if fin.get("roe"):
            parts.append(f"ROE {fin['roe']}")
        if fin.get("gross_margin"):
            parts.append(f"毛利率 {fin['gross_margin']}")
        if fin.get("net_margin"):
            parts.append(f"净利率 {fin['net_margin']}")
        fin_sum = "；".join(parts) + (f"（{fin.get('period','')}）" if fin.get("period") else "")

    # 估值位置（只标位置不划买卖线）
    val_pos = ""
    if val:
        pe = val.get("pe_ttm") or {}
        pb = val.get("pb") or {}
        pct = pe.get("percentile")
        if pct is not None:
            val_pos = f"PE-TTM 处历史 {pct}% 分位"
        pbpct = pb.get("percentile")
        if pbpct is not None:
            val_pos += f"；PB 处 {pbpct}% 分位"

    # 商业模式（来自行业+名称，客观）
    industry = ""
    try:
        info = astock.individual_info(code) or {}
        industry = str(info.get("行业") or "")
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
