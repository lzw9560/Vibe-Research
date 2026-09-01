# -*- coding: utf-8 -*-
"""S139（s066 task 039）：sector_phase 候选卡纯 LABEL 接线测。

覆盖：有 hybk→标注 / 无 pool_item→None / sector_cycle 失败→None。
纯 LABEL，不改策略分（§5.4 Q2 修饰方向被驳→降级纯 LABEL）。
"""
from __future__ import annotations

from candidate_funnel.diagnosis import build_diagnosis_card
from candidate_funnel.models import IndicatorSet, BaseThreshold
from strategies.sector_cycle import SectorPhase


def _ind():
    return IndicatorSet(code="600519", name="茅台")


def test_sector_phase_labeled_when_pool_item_has_hybk(monkeypatch):
    """A1：pool_item 含 hybk → sector_phase 标注（纯 LABEL，phase/stay_days/...）。"""
    sp = SectorPhase(industry="电力", count_today=3, count_avg_3d=1.0,
                     momentum=2.0, phase="发酵", modifier=1.0,
                     phase_note="连续在榜", stay_days=4)
    monkeypatch.setattr("strategies.sector_cycle.analyze_sector_phase",
                        lambda d, i: sp)
    card = build_diagnosis_card(
        code="600519", name="茅台", ind=_ind(), eff=BaseThreshold(),
        pool_item={"hybk": "电力"}, trade_date="2026-08-28",
    )
    assert card.sector_phase is not None
    assert card.sector_phase["phase"] == "发酵"
    assert card.sector_phase["industry"] == "电力"
    assert card.sector_phase["stay_days"] == 4
    assert card.sector_phase["momentum"] == 2.0


def test_sector_phase_none_when_no_pool_item():
    """A2：pool_item=None → sector_phase=None（非涨停股无行业标注）。"""
    card = build_diagnosis_card(
        code="X", name="X", ind=_ind(), eff=BaseThreshold(), pool_item=None,
    )
    assert card.sector_phase is None


def test_sector_phase_none_on_sector_cycle_failure(monkeypatch):
    """A3：analyze_sector_phase raise → sector_phase=None（不臆造）。"""
    def _boom(d, i):
        raise RuntimeError("sector_cycle 挂")
    monkeypatch.setattr("strategies.sector_cycle.analyze_sector_phase", _boom)
    card = build_diagnosis_card(
        code="X", name="X", ind=_ind(), eff=BaseThreshold(),
        pool_item={"hybk": "电力"}, trade_date="2026-08-28",
    )
    assert card.sector_phase is None  # 失败降级不臆造
