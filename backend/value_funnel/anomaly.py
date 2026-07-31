# -*- coding: utf-8 -*-
"""S017 P1-c 财报异常五信号检测（排雷层）。

移植自 ai-berkshire earnings-review skill §4.2「异常信号检测」：
  1. 应收账款增速 > 收入增速（可能在塞渠道）
  2. 存货增速 > 收入增速（可能在积压）
  3. 经营现金流 < 净利润且差距扩大（利润质量存疑）
  4. 资本化开支突然增加（可能在美化利润）
  5. 非经常性收益占比突然上升

纯函数、无网络、可复算。输入 ``FinancialPeriod`` 序列（升序，[-1]=当期、[-2]=上期），
至少 2 期方可判定"增速/扩大/突增"；不足则该信号标 inapplicable，不臆造。

合规：只给客观可复现的异常**提示**（evidence 记取数+口径），不输出"造假"判断、
不剔除标的——触发≠造假，最终认定交用户 AI。与 value_funnel/quality.py 同属排雷层。
"""
from __future__ import annotations

from typing import Optional

from models.financials import FinancialPeriod

from . import models


# ── 阈值（客观可调常量，evidence 记口径）──────────────────────────────────
CAPEX_SPIKE_RATIO = 1.5       # 资本开支同比 > 1.5× 视为突增
NONRECURRING_SPIKE_RATIO = 1.5  # 非经常性占比 同比上升 > 1.5× 视为突增
NONRECURRING_MIN_SHARE = 0.05   # 非经常占比 > 5% 才视为非平凡（过滤噪声）


# ── 工具 ────────────────────────────────────────────────────────────────

def _growth(curr: float | None, prior: float | None) -> float | None:
    """同比增速（小数）：(curr − prior) / |prior|。prior=0/None → None。"""
    if curr is None or prior is None or prior == 0:
        return None
    return (curr - prior) / abs(prior)


def _share(numer: float | None, denom: float | None) -> float | None:
    """占比（小数）：numer / |denom|。denom=0/None → None。"""
    if numer is None or denom is None or denom == 0:
        return None
    return numer / abs(denom)


def _signal(idx: int, name: str) -> models.AnomalySignal:
    return models.AnomalySignal(index=idx, name=name)


# ── 五信号 ──────────────────────────────────────────────────────────────

def _sig1_channel_stuffing(curr: FinancialPeriod, prior: FinancialPeriod) -> models.AnomalySignal:
    """应收账款增速 > 收入增速（塞渠道）。"""
    s = _signal(1, "应收增速>营收增速")
    ar_g = _growth(curr.accounts_receivable, prior.accounts_receivable)
    rev_g = _growth(curr.revenue, prior.revenue)
    if ar_g is None or rev_g is None:
        s.inapplicable, s.inapplicable_reason = True, "应收/营收数据不足"
        s.evidence = "应收账款或营收缺值，无法算同比增速"
        return s
    triggered = ar_g > rev_g and ar_g > 0
    s.triggered = triggered
    s.severity = "warn" if triggered else "info"
    s.evidence = (f"应收增速={ar_g*100:.1f}% 营收增速={rev_g*100:.1f}% "
                  f"{'（应收快于营收）' if triggered else ''}")
    return s


def _sig2_inventory_piling(curr: FinancialPeriod, prior: FinancialPeriod) -> models.AnomalySignal:
    """存货增速 > 收入增速（积压）。"""
    s = _signal(2, "存货增速>营收增速")
    inv_g = _growth(curr.inventory, prior.inventory)
    rev_g = _growth(curr.revenue, prior.revenue)
    if inv_g is None or rev_g is None:
        s.inapplicable, s.inapplicable_reason = True, "存货/营收数据不足"
        s.evidence = "存货或营收缺值，无法算同比增速"
        return s
    triggered = inv_g > rev_g and inv_g > 0
    s.triggered = triggered
    s.severity = "warn" if triggered else "info"
    s.evidence = (f"存货增速={inv_g*100:.1f}% 营收增速={rev_g*100:.1f}% "
                  f"{'（存货快于营收）' if triggered else ''}")
    return s


def _sig3_earnings_quality(curr: FinancialPeriod, prior: FinancialPeriod) -> models.AnomalySignal:
    """经营现金流 < 净利润 且 差距扩大（利润质量存疑）。

    gap = NI − OCF（>0 表示利润未收回现金）；触发需 OCF<NI 当期且 gap 当期 > 上期。
    """
    s = _signal(3, "经营现金流<净利且差距扩大")
    if (curr.operating_cash_flow is None or curr.net_profit is None
            or prior.operating_cash_flow is None or prior.net_profit is None):
        s.inapplicable, s.inapplicable_reason = True, "现金流/净利数据不足"
        s.evidence = "经营现金流或净利润缺值，无法判利润质量"
        return s
    gap_curr = curr.net_profit - curr.operating_cash_flow
    gap_prior = prior.net_profit - prior.operating_cash_flow
    ocf_lt_ni = curr.operating_cash_flow < curr.net_profit
    widening = gap_curr > gap_prior
    triggered = ocf_lt_ni and widening
    s.triggered = triggered
    s.severity = "high" if triggered else "info"
    s.evidence = (f"当期 OCF={curr.operating_cash_flow:.0f} NI={curr.net_profit:.0f} "
                  f"gap={gap_curr:.0f}（上期 gap={gap_prior:.0f}）"
                  f"{'；OCF<NI 且 gap 扩大' if triggered else ''}")
    return s


def _sig4_capex_spike(curr: FinancialPeriod, prior: FinancialPeriod) -> models.AnomalySignal:
    """资本化开支突然增加（>1.5× 上期，可能在美化利润）。"""
    s = _signal(4, "资本开支突增")
    if curr.capex is None or prior.capex is None:
        s.inapplicable, s.inapplicable_reason = True, "资本开支数据不足"
        s.evidence = "capex 缺值，无法算同比"
        return s
    if prior.capex <= 0:
        s.inapplicable, s.inapplicable_reason = True, "上期 capex≤0 基准不可比"
        s.evidence = f"上期 capex={prior.capex}≤0，突增倍数不可比"
        return s
    ratio = curr.capex / prior.capex
    triggered = ratio > CAPEX_SPIKE_RATIO
    s.triggered = triggered
    s.severity = "warn" if triggered else "info"
    s.evidence = f"capex {curr.capex:.0f} / 上期 {prior.capex:.0f} = {ratio:.2f}×（>{CAPEX_SPIKE_RATIO}×为突增）"
    return s


def _sig5_nonrecurring_spike(curr: FinancialPeriod, prior: FinancialPeriod) -> models.AnomalySignal:
    """非经常性收益占比突然上升。

    non_recurring = net_profit − net_profit_excluding_nonrecurring；
    share = non_recurring / |net_profit|；触发需 share 当期 > 上期×1.5 且 > 5%。
    """
    s = _signal(5, "非经常性收益占比上升")
    if (curr.net_profit is None or curr.net_profit_excluding_nonrecurring is None
            or prior.net_profit is None or prior.net_profit_excluding_nonrecurring is None):
        s.inapplicable, s.inapplicable_reason = True, "非经常性损益数据不足"
        s.evidence = "net_profit 或扣非净利缺值，无法算非经常占比"
        return s
    nr_curr = curr.net_profit - curr.net_profit_excluding_nonrecurring
    nr_prior = prior.net_profit - prior.net_profit_excluding_nonrecurring
    share_curr = _share(nr_curr, curr.net_profit)
    share_prior = _share(nr_prior, prior.net_profit)
    if share_curr is None or share_prior is None:
        s.inapplicable, s.inapplicable_reason = True, "净利为 0 占比不可比"
        s.evidence = "净利为 0，非经常占比不可算"
        return s
    rising = share_curr > share_prior * NONRECURRING_SPIKE_RATIO
    material = share_curr > NONRECURRING_MIN_SHARE
    triggered = rising and material
    s.triggered = triggered
    s.severity = "high" if triggered else "info"
    s.evidence = (f"非经常占比 当期={share_curr*100:.1f}% 上期={share_prior*100:.1f}%"
                  f"（>{NONRECURRING_SPIKE_RATIO}× 且>{NONRECURRING_MIN_SHARE*100:.0f}%为突增）")
    return s


# ── 编排 ────────────────────────────────────────────────────────────────

def detect_anomalies(periods: list[FinancialPeriod]) -> models.AnomalyAssessment:
    """财报异常五信号检测。

    ``periods`` 升序（旧→新），至少 2 期；[-1]=当期、[-2]=上期作对照基准。
    不足 2 期 → 各信号标 inapplicable（不臆造）。返回 :class:`AnomalyAssessment`。
    """
    if len(periods) < 2:
        sig = _signal(0, "数据不足")
        sig.inapplicable, sig.inapplicable_reason = True, "财务期数<2，无法同比"
        sig.evidence = f"仅 {len(periods)} 期，需≥2 期对照"
        # 五信号全标 inapplicable
        sigs = []
        for i, name in enumerate(["应收增速>营收增速", "存货增速>营收增速",
                                  "经营现金流<净利且差距扩大", "资本开支突增",
                                  "非经常性收益占比上升"], start=1):
            m = models.AnomalySignal(index=i, name=name, inapplicable=True,
                                     inapplicable_reason="财务期数<2")
            sigs.append(m)
        return models.AnomalyAssessment(signals=sigs, triggered_count=0)

    curr, prior = periods[-1], periods[-2]
    signals = [
        _sig1_channel_stuffing(curr, prior),
        _sig2_inventory_piling(curr, prior),
        _sig3_earnings_quality(curr, prior),
        _sig4_capex_spike(curr, prior),
        _sig5_nonrecurring_spike(curr, prior),
    ]
    triggered = sum(1 for s in signals if s.triggered)
    return models.AnomalyAssessment(
        signals=signals,
        triggered_count=triggered,
        period=curr.period,
        prior_period=prior.period,
    )
