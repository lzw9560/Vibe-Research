# -*- coding: utf-8 -*-
"""因子适配层单测（limitup_screener）。

用 mock 验证适配结构，不依赖真实数据采集（live 测试另跑）。
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from factors import registry
from factors.limitup_screener_factor import LimitupScreenerFactor, FACTOR_ID as LS_ID


def setup_function():
    registry._registry.clear()
    import factors.registry as _reg_mod
    _reg_mod._defaults_registered = False


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
    # α（grill）：candidate_funnel 因子冗余——漏斗层由 _build_funnel_layers 单一产出
    # （routers/workflow.py），前端 PreMarketBriefing.tsx:246 跳过其因子卡，故从默认注册
    # 移除；漏斗数据不丢（final_candidates/funnel_layers 不变），仅去重复表示。
    assert n1 == 1
    assert n2 == 1  # 幂等
    assert {f.factor_id for f in registry.get_all_factors()} == {"limitup_screener"}
    assert registry.get_factor("candidate_funnel") is None  # 不再注册


def _async_return(val):
    """包装成 awaitable（PreMarketWorkflow.run 是 async）。"""

    async def _coro():
        return val

    return _coro()
