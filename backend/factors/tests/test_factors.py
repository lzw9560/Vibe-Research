# -*- coding: utf-8 -*-
"""两套因子适配层单测（S023 B4）。

用 mock 验证适配结构，不依赖真实数据采集（live 测试另跑）。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch, MagicMock

from candidate_funnel.models import (
    ActivityAssessment,
    ActivityTier,
    DiagnosisCard,
    FilterRecord,
    FunnelLayer,
    FunnelResult,
    IndicatorSet,
    StabilizationSignals,
    ThresholdConfig,
)
from factors import registry
from factors.candidate_funnel_factor import CandidateFunnelFactor, FACTOR_ID as CF_ID
from factors.limitup_screener_factor import LimitupScreenerFactor, FACTOR_ID as LS_ID


def setup_function():
    registry._registry.clear()
    import factors.registry as _reg_mod
    _reg_mod._defaults_registered = False


# ---------- CandidateFunnelFactor ----------


def _fake_diagnosis_card(code="600519", name="贵州茅台") -> DiagnosisCard:
    return DiagnosisCard(
        code=code,
        name=name,
        indicators=IndicatorSet(code=code, name=name),
        activity=ActivityAssessment(
            tier=ActivityTier.ACTIVE,
            rules_applied=["换手>=8.0%", "量比>=2.0"],
        ),
        stabilization=StabilizationSignals(),
        risk_flags=[],
        as_of=datetime.now(),
    )


def _fake_funnel_result(candidates=None) -> FunnelResult:
    return FunnelResult(
        run_id="test",
        date="2026-08-01",
        layers=[
            FunnelLayer(
                layer_id="R1", name="宽源", as_of=datetime.now(),
                input_count=99, output_count=50, filtered_out=[], output_codes=[],
            )
        ],
        final_candidates=candidates or [],
        threshold_config=ThresholdConfig(),
        sentiment_phase="阴天",
        as_of=datetime.now(),
    )


def test_candidate_funnel_factor_fetch_with_candidates():
    card = _fake_diagnosis_card()
    with patch("factors.candidate_funnel_factor.funnel_mod.run_funnel", return_value=_fake_funnel_result([card])):
        f = CandidateFunnelFactor()
        r = f.fetch("2026-08-03")
    assert r.factor_id == CF_ID
    assert len(r.candidates) == 1
    c = r.candidates[0]
    assert c.code == "600519"
    assert c.source_factor_id == CF_ID
    assert c.source_layer == "final"
    assert "换手>=8.0%" in c.hit_rules
    assert c.detail["activity_tier"] == "ActivityTier.ACTIVE"
    assert len(r.layers) == 1
    assert r.data_date == "2026-08-03"
    assert r.data_status == "ok"


def test_candidate_funnel_factor_empty_candidates_marks_ok():
    with patch("factors.candidate_funnel_factor.funnel_mod.run_funnel", return_value=_fake_funnel_result([])):
        f = CandidateFunnelFactor()
        r = f.fetch("2026-08-03")
    assert r.candidates == []
    assert r.data_status == "ok"
    assert "非采集失败" in r.config["reason"]


def test_candidate_funnel_factor_describe():
    d = CandidateFunnelFactor().describe()
    assert d["name"]
    assert len(d["维度"]) >= 5


# ---------- LimitupScreenerFactor ----------


def _fake_gene_score(code="000001", name="平安银行", score=85.0):
    gs = MagicMock()
    gs.code = code
    gs.name = name
    gs.gene_score = score
    return gs


def _fake_pre_market_report(candidates=None, strong=None):
    report = MagicMock()
    report.candidates = candidates or []
    report.strong_candidates = strong or []
    report.strategy_matches = []
    report.sentiment_index = 50.0
    report.sentiment_phase = "neutral"
    report.generated_at = "2026-08-02T10:00:00"
    report.date = "2026-08-01"
    return report


def test_limitup_screener_factor_fetch_with_candidates():
    gs = _fake_gene_score()
    report = _fake_pre_market_report(candidates=[gs])
    with patch("pre_market_workflow.PreMarketWorkflow") as Pmw:
        wf = MagicMock()
        wf.run = MagicMock(return_value=_async_return(report))
        Pmw.return_value = wf
        f = LimitupScreenerFactor()
        r = f.fetch("2026-08-03")
    assert r.factor_id == LS_ID
    assert len(r.candidates) == 1
    c = r.candidates[0]
    assert c.code == "000001"
    assert c.source_factor_id == LS_ID
    assert c.source_layer == "八项标准"
    assert c.detail["gene_score"] == 85.0
    assert len(r.layers) == 3  # S031 R14：打分→战法→仓位 三层
    assert r.layers[0].layer_id == "LS-1"
    assert r.data_status == "ok"


def test_limitup_screener_factor_empty_marks_missing():
    report = _fake_pre_market_report(candidates=[], strong=[])
    with patch("pre_market_workflow.PreMarketWorkflow") as Pmw:
        wf = MagicMock()
        wf.run = MagicMock(return_value=_async_return(report))
        Pmw.return_value = wf
        f = LimitupScreenerFactor()
        r = f.fetch("2026-08-03")
    assert r.candidates == []
    assert r.layers[0].data_status == "未取得"


def test_limitup_screener_factor_describe():
    d = LimitupScreenerFactor().describe()
    assert d["name"]
    assert "涨停基因" in d["name"]


# ---------- register_default_factors ----------


def test_register_default_factors_idempotent():
    registry.register_default_factors()
    n1 = len(registry.get_all_factors())
    registry.register_default_factors()
    n2 = len(registry.get_all_factors())
    assert n1 == 2
    assert n2 == 2  # 幂等


def _async_return(val):
    """包装成 awaitable（PreMarketWorkflow.run 是 async）。"""

    async def _coro():
        return val

    return _coro()
