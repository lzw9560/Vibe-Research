# -*- coding: utf-8 -*-
"""S131 R4-R10 em_get 消费者诚实化测试。

钉死每条 confirmed_lying 的修复（scan wf_cad164bc-f17）：
- R4 concept_blocks / R5 em_zt_topic_pool / R6 market_turnover_rank / R7 sector_fund_flow /
  R8 industry_comparison / R10 lockup_expiry：raise_on_failure=True + 源断 → raise；
  默认 False → 原空返回（向后兼容，既有 [] mock 测试不破）。
- R8 默认失败 dict 带 data_status='missing'（/api/industry 透传可见源断）。
- R9 eastmoney_datacenter（S119 已落地）：raise_on_failure=True→raise；默认→[]。
- R10 fetch_share_unlock：源断→([], "missing")（区分"无解禁"([],"ok")）。

所有测试 mock ``eastmoney.em_get``（transport 层，防封路径不变），不联网。
对齐 S119 范式（test_data_honesty.py:555 同款断言结构）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import data.sources.eastmoney as eastmoney  # noqa: E402


def _boom(*a, **k):
    """模拟 em_get 源断（断连/限流/JSON 错统一 raise）。"""
    raise ConnectionError("em_get 源断")


# ===========================================================================
# R4 concept_blocks
# ===========================================================================

def test_r4_concept_blocks_raise_on_failure_true_raises(monkeypatch):
    """R4.3①：raise_on_failure=True + 源断 → raise（非吞成空 dict）。"""
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    with pytest.raises(ConnectionError):
        eastmoney.concept_blocks("600519", raise_on_failure=True)


def test_r4_concept_blocks_default_returns_empty_dict_backward_compat(monkeypatch):
    """R4.3②：默认 False + 源断 → 原空 dict（向后兼容，caller 当合法空消费）。"""
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    out = eastmoney.concept_blocks("600519")
    assert out == {"total": 0, "boards": [], "concept_tags": []}


# ===========================================================================
# R4 caller-side：承重 callers 传 raise_on_failure=True + 源断→兜底 firing
# （stock_financial:122→502 / catalyst:53→"板块未取得" / stock_data:231→None）
# ===========================================================================

def test_r4_caller_stock_financial_passes_raise_on_failure(monkeypatch):
    """R4.2 caller-side：stock_financial /api/blocks 传 raise_on_failure=True。

    concept_blocks swallow 时 try/except 不 fire（源断→空 dict 当合法空）；
    传 True 后源断 raise → try/except→502 fire（诚实化）。
    """
    import astock
    from routers.stock_financial import blocks, _DC_CACHE
    _DC_CACHE.clear()
    captured: dict = {}

    def _spy(code, **kw):
        captured.update(kw)
        return {"total": 1, "boards": [{"name": "白酒"}], "concept_tags": []}

    monkeypatch.setattr(astock, "concept_blocks", _spy)
    blocks(code="600519")
    assert captured.get("raise_on_failure") is True


def test_r4_caller_stock_financial_source_fail_returns_502(monkeypatch):
    """R4.2 caller-side：concept_blocks(raise_on_failure=True) 源断 raise → 502（非空 dict 当合法空）。"""
    import astock
    from fastapi import HTTPException
    from routers.stock_financial import blocks, _DC_CACHE
    _DC_CACHE.clear()

    def _boom(code, **kw):
        raise ConnectionError("em_get 源断")

    monkeypatch.setattr(astock, "concept_blocks", _boom)
    with pytest.raises(HTTPException) as exc_info:
        blocks(code="600519")
    assert exc_info.value.status_code == 502


def test_r4_caller_catalyst_passes_raise_on_failure(monkeypatch):
    """R4.2 caller-side：catalyst.fetch_catalyst 传 raise_on_failure=True。

    concept_blocks swallow 时 try/except 不 fire（源断→空 dict→{}→concepts=[]当合法空）；
    传 True 后源断 raise → try/except→"板块未取得" fire（诚实标 missing）。
    """
    import astock
    from candidate_funnel.sources import catalyst
    captured: dict = {}

    def _spy(code, **kw):
        captured.update(kw)
        return {"total": 1, "boards": [{"name": "白酒"}], "concept_tags": ["白酒"]}

    monkeypatch.setattr(astock, "concept_blocks", _spy)
    monkeypatch.setattr(astock, "announcements", lambda *a, **k: [])
    monkeypatch.setattr(catalyst, "fetch_sector_flow", lambda *a, **k: None)
    out = catalyst.fetch_catalyst(["600519"], "2026-07-30")
    assert captured.get("raise_on_failure") is True
    assert out["600519"]["concepts"] == ["白酒"]


def test_r4_caller_catalyst_source_fail_marks_missing(monkeypatch):
    """R4.2 caller-side：concept_blocks(raise_on_failure=True) 源断 raise → "板块未取得"（非空 concepts=[]）。"""
    import astock
    from candidate_funnel.sources import catalyst

    def _boom(code, **kw):
        raise ConnectionError("em_get 源断")

    monkeypatch.setattr(astock, "concept_blocks", _boom)
    monkeypatch.setattr(astock, "announcements", lambda *a, **k: [])
    monkeypatch.setattr(catalyst, "fetch_sector_flow", lambda *a, **k: None)
    out = catalyst.fetch_catalyst(["600519"], "2026-07-30")
    assert out["600519"]["missing"]["concepts"] == "板块未取得"


def test_r4_caller_stock_data_passes_raise_on_failure(monkeypatch):
    """R4.2 caller-side：stock_data /api/stock/{code}/deep 传 raise_on_failure=True。

    concept_blocks swallow 时 _safe_call 不 fire（源断→空 dict 当合法空）；
    传 True 后源断 raise → _safe_call catch → blocks=None（诚实标源断）。
    """
    import astock
    import asyncio
    from routers.stock_data import stock_deep
    captured: dict = {}

    def _spy(code, **kw):
        captured.update(kw)
        return {"total": 1, "boards": [{"name": "白酒"}], "concept_tags": ["白酒"]}

    monkeypatch.setattr(astock, "concept_blocks", _spy)
    # 其他取数函数 mock 成空，避免离线发真实请求（§1.2 防封底线）
    _noop = lambda *a, **k: None  # noqa: E731
    for fn in ("tencent_quote", "kline", "full_valuation", "valuation_percentile",
               "stock_fund_flow_120d", "dragon_tiger_board", "financials",
               "hot_concepts", "announcements", "eastmoney_reports"):
        monkeypatch.setattr(astock, fn, _noop)
    monkeypatch.setattr("routers.stock_data._limitup_analysis_sync", lambda c: None)
    result = asyncio.run(stock_deep("600519"))
    assert captured.get("raise_on_failure") is True
    assert result["data"]["blocks"]["boards"][0]["name"] == "白酒"


def test_r4_caller_stock_data_source_fail_returns_none(monkeypatch):
    """R4.2 caller-side：concept_blocks(raise_on_failure=True) 源断 raise → _safe_call catch → blocks=None（非空 dict）。"""
    import astock
    import asyncio
    from routers.stock_data import stock_deep

    def _boom(code, **kw):
        raise ConnectionError("em_get 源断")

    monkeypatch.setattr(astock, "concept_blocks", _boom)
    _noop = lambda *a, **k: None  # noqa: E731
    for fn in ("tencent_quote", "kline", "full_valuation", "valuation_percentile",
               "stock_fund_flow_120d", "dragon_tiger_board", "financials",
               "hot_concepts", "announcements", "eastmoney_reports"):
        monkeypatch.setattr(astock, fn, _noop)
    monkeypatch.setattr("routers.stock_data._limitup_analysis_sync", lambda c: None)
    result = asyncio.run(stock_deep("600519"))
    assert result["data"]["blocks"] is None


# ===========================================================================
# R5 em_zt_topic_pool
# ===========================================================================

def test_r5_em_zt_topic_pool_raise_on_failure_true_raises(monkeypatch):
    """R5.3①：raise_on_failure=True + 源断 → raise（让 get_with_fallback_meta 标 missing）。"""
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    with pytest.raises(ConnectionError):
        eastmoney.em_zt_topic_pool("getTopicZTPool", "20260901", raise_on_failure=True)


def test_r5_em_zt_topic_pool_default_returns_empty_backward_compat(monkeypatch):
    """R5.3②：默认 False + 源断 → []（向后兼容）。"""
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    assert eastmoney.em_zt_topic_pool("getTopicZTPool", "20260901") == []


def test_r5_em_zt_topic_pool_failure_not_cached(monkeypatch):
    """R5.3③：空不缓存逻辑不变——源断不写缓存（下次请求直接重试，不毒 24h）。

    extreme_market_detector:128 路径不被破坏（get_with_fallback_meta 仍可重试）。
    """
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    eastmoney._ztb_cache.clear()
    eastmoney.em_zt_topic_pool("getTopicZTPool", "20260901")
    # 失败/空都不写缓存
    assert ("getTopicZTPool", "20260901", "fbt:asc") not in eastmoney._ztb_cache


# ===========================================================================
# R5 caller-side：承重 callers 传 raise_on_failure=True + 源断→missing 传播
# topology callers (LadderEdgeProvider / build_board_ladder_tree) 在
# test_topology.py:test_ladder_provider_passes_raise_on_failure_true /
# test_board_ladder_passes_raise_on_failure_true / *_source_fail_propagates_to_empty 钉死。
# 以下为 limitup_screener _fetch_zt_next_pool caller-side 测试。
# ===========================================================================

def test_r5_caller_screener_fetch_zt_next_passes_raise_on_failure(monkeypatch):
    """R5.2 caller-side：limitup_screener _fetch_zt_next_pool 传 raise_on_failure=True。"""
    from limitup_screener import service as svc
    captured: dict = {}

    def _spy(endpoint, date, sort="fbt:asc", **kw):
        captured.update(kw)
        return [{"c": "001"}]

    monkeypatch.setattr(svc.astock, "em_zt_topic_pool", _spy)
    svc._fetch_zt_next_pool("20260901")
    assert captured.get("raise_on_failure") is True


def test_r5_caller_screener_source_fail_returns_empty(monkeypatch):
    """R5.2 caller-side：em_get 源断 → em_zt_topic_pool(raise_on_failure=True) raises
    → _fetch_zt_next_pool try/except 兜底 → []（下游 _compute_rebound_rate 标 missing）。
    """
    from limitup_screener import service as svc
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    eastmoney._ztb_cache.clear()
    result = svc._fetch_zt_next_pool("20260901")
    assert result == []


# ===========================================================================
# R6 market_turnover_rank
# ===========================================================================

def test_r6_market_turnover_rank_raise_on_failure_true_raises(monkeypatch):
    """R6.2①：双 host 均断 → raise_on_failure=True 时 raise（让 get_turnover_top 标 missing）。

    data_status='missing' 传播在 get_turnover_top/build（caller 侧，本 spec scope 外），
    本测钉死源端 raise 机制——caller 传 True 即可据 raise 标 missing（非合法空 []）。
    """
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    with pytest.raises(ConnectionError):
        eastmoney.market_turnover_rank(20, raise_on_failure=True)


def test_r6_market_turnover_rank_default_returns_empty_backward_compat(monkeypatch):
    """R6.2②：默认 False + 双 host 断 → []（向后兼容，test_s085 同款断言不破）。"""
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    assert eastmoney.market_turnover_rank(20) == []


# ===========================================================================
# R7 sector_fund_flow
# ===========================================================================

def test_r7_sector_fund_flow_raise_on_failure_true_raises(monkeypatch):
    """R7.2①：双 host 均断 → raise_on_failure=True 时 raise（让 _sectors/overview 标 missing）。"""
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    with pytest.raises(ConnectionError):
        eastmoney.sector_fund_flow(raise_on_failure=True)


def test_r7_sector_fund_flow_default_returns_empty_backward_compat(monkeypatch):
    """R7.2②：默认 False + 双 host 断 → []（向后兼容，test_s085_sector_fund_flow:71 不破）。"""
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    assert eastmoney.sector_fund_flow() == []


# ===========================================================================
# R8 industry_comparison
# ===========================================================================

def test_r8_industry_comparison_raise_on_failure_true_raises(monkeypatch):
    """R8.2①：raise_on_failure=True + 源断 → raise（让 sector_divergence 标 missing）。"""
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    with pytest.raises(ConnectionError):
        eastmoney.industry_comparison(raise_on_failure=True)


def test_r8_industry_comparison_default_missing_data_status(monkeypatch):
    """R8.2②：默认 False + 源断 → dict 带 data_status='missing'（/api/industry 透传可见源断）。

    对齐 sector_divergence.py:150-159 范式——失败 dict 加 data_status 让下游（stock_financial:158
    透传整个 dict）可见"源断"非"空排名"，不缓存空 top。
    """
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    out = eastmoney.industry_comparison()
    assert out["top"] == []
    assert out["bottom"] == []
    assert out["total"] == 0
    assert out["data_status"] == "missing"


def test_r8_failure_dict_not_cached_good_cache_preserved(monkeypatch, tmp_path):
    """R8 回归：industry_comparison 默认失败 dict 带 data_status='missing'，经
    get_with_fallback_meta 不缓存（_is_empty 认 data_status='missing' 为空），
    好缓存保留 + 响应降级到好缓存（stale），不覆盖。

    [fallback-empty-write-corrupts-snapshots] 同款防护——失败 dict 的 "missing"
    字符串使 dict 非空，旧 _is_empty 漏网 → save_cache 覆盖好缓存。修：_is_empty
    认 data_status='missing' dict 为空 → get_with_fallback_meta 不缓存 → 降级好缓存。

    模拟 sector_divergence.py:150-155 的真实调用链（fetch_fn = industry_comparison
    默认 raise_on_failure=False → 源断返失败 dict 非 raise）。
    """
    import fallback
    import astock

    # 独立缓存目录 + 干净内存缓存
    monkeypatch.setattr(fallback, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(fallback, "_MEM_CACHE", {})

    # 既有好缓存（前一天成功取数写的）
    good = {"top": [{"name": "白酒", "change_pct": 2.5, "rank": 1}],
            "bottom": [{"name": "房地产", "change_pct": -1.2, "rank": 100}],
            "total": 100}
    fallback.save_cache("industry_comparison:20260901", good)

    # 源断：em_get raise → industry_comparison 默认 swallow 返失败 dict（非 raise）
    monkeypatch.setattr(eastmoney, "em_get", _boom)

    # 模拟 sector_divergence 的调用链
    data, meta = fallback.get_with_fallback_meta(
        "industry_comparison:20260901",
        lambda: astock.industry_comparison(top_n=100),
        ttl=600,
        fallback_value={"top": [], "bottom": []},
    )

    # 好缓存未被失败 dict 覆盖
    assert fallback.load_cache("industry_comparison:20260901") == good
    # 降级到好缓存（stale）——非返失败 dict 当 live
    assert data == good
    assert meta["from_cache"] is True
    assert meta["is_stale"] is True


def test_r8_failure_no_cache_returns_fallback_missing(monkeypatch, tmp_path):
    """R8 无好缓存时源断 → 失败 dict 不缓存，返 fallback_value（无 data_status）。
    下游 sector_divergence._resolve_sector_provenance 据 meta+空板块标 missing。
    """
    import fallback
    import astock

    monkeypatch.setattr(fallback, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(fallback, "_MEM_CACHE", {})

    monkeypatch.setattr(eastmoney, "em_get", _boom)

    data, meta = fallback.get_with_fallback_meta(
        "industry_comparison:20260901",
        lambda: astock.industry_comparison(top_n=100),
        ttl=600,
        fallback_value={"top": [], "bottom": []},
    )

    # 无缓存 → 返 fallback_value（无 data_status，下游据空板块标 missing）
    assert data == {"top": [], "bottom": []}
    assert "data_status" not in data
    assert meta["from_cache"] is False
    assert meta["fetch_ok"] is True  # industry_comparison 内部 swallow，未 raise
    # 失败 dict 未写缓存
    assert fallback.load_cache("industry_comparison:20260901") is None


# ===========================================================================
# R9 eastmoney_datacenter（S119 已落地，此处钉死契约不回归）
# ===========================================================================

def test_r9_eastmoney_datacenter_raise_on_failure_true_raises(monkeypatch):
    """R9.2①：raise_on_failure=True + 源断 → raise（seat_engine/risk-trio 据此标 missing）。"""
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    with pytest.raises(ConnectionError):
        eastmoney.eastmoney_datacenter("RPT_LIFT_STAGE", raise_on_failure=True)


def test_r9_eastmoney_datacenter_default_swallows_backward_compat(monkeypatch):
    """R9.2②：默认 False + 源断 → []（向后兼容，margin_trading/lockup_expiry 等非承重 caller 不变）。"""
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    assert eastmoney.eastmoney_datacenter("RPT_LIFT_STAGE") == []


# ===========================================================================
# R10 lockup_expiry + fetch_share_unlock
# ===========================================================================

def test_r10_lockup_expiry_raise_on_failure_true_raises(monkeypatch):
    """R10.3①：lockup_expiry(raise_on_failure=True) + 源断 → raise（底层 eastmoney_datacenter 透传）。"""
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    with pytest.raises(ConnectionError):
        eastmoney.lockup_expiry("600519", raise_on_failure=True)


def test_r10_lockup_expiry_default_backward_compat(monkeypatch):
    """R10.3③：默认 False + 源断 → {"history":[],"upcoming":[]}（向后兼容）。"""
    monkeypatch.setattr(eastmoney, "em_get", _boom)
    out = eastmoney.lockup_expiry("600519")
    assert out == {"history": [], "upcoming": []}


def test_r10_fetch_share_unlock_source_fail_returns_empty_with_missing(monkeypatch):
    """R10.3②：fetch_share_unlock 源断 → ([], "missing")（区分"无解禁"vs"源断"）。

    lockup_expiry(raise_on_failure=True) 源断 raise → _impl catch → ([], "missing")。
    向后兼容入口 fetch_share_unlock(code) → []（不崩，build_event_context.extend 不破）。
    """
    import astock
    monkeypatch.setattr(astock, "lockup_expiry", _boom)
    from strategies.event_factors import fetch_share_unlock, fetch_share_unlock_with_status

    # status-aware：源断 → ([], "missing")
    events, status = fetch_share_unlock_with_status("600519")
    assert events == []
    assert status == "missing"

    # 向后兼容入口：源断 → []（不崩）
    assert fetch_share_unlock("600519") == []


def test_r10_fetch_share_unlock_no_upcoming_returns_ok(monkeypatch):
    """R10 补充：成功但无 upcoming → ([], "ok")（真无解禁，非源断）——与源断 missing 区分。"""
    import astock
    monkeypatch.setattr(
        astock, "lockup_expiry",
        lambda *a, **k: {"history": [], "upcoming": []},
    )
    from strategies.event_factors import fetch_share_unlock_with_status, fetch_share_unlock

    events, status = fetch_share_unlock_with_status("600519")
    assert events == []
    assert status == "ok"

    # 向后兼容入口：无解禁 → []
    assert fetch_share_unlock("600519") == []


def test_r10_build_event_context_source_fail_propagates_missing(monkeypatch):
    """R10 链闭合：build_event_context 调 fetch_share_unlock_with_status →
    源断 status='missing' 透传到 EventContext.lockup_data_status（非当合法空 ok）。

    之前 build_event_context 调 backward-compat fetch_share_unlock → [] 状态被丢弃，
    源断与"无解禁"不可分（advEastmoney + critic：R10 chain broken）。现已修。
    """
    import astock
    monkeypatch.setattr(astock, "lockup_expiry", _boom)
    from strategies.event_factors import build_event_context

    # 其余源 stub 为空，隔离解禁源
    monkeypatch.setattr("strategies.event_factors.fetch_earnings_forecast", lambda c: [])
    monkeypatch.setattr("strategies.event_factors.fetch_shareholder_change", lambda c: [])
    monkeypatch.setattr("strategies.event_factors.check_ex_dividend", lambda c, d, **kw: (False, "无"))

    ctx = build_event_context("600519")
    assert ctx.events == []                    # 不崩
    assert ctx.lockup_data_status == "missing"  # 源断标 missing，非当合法空 ok


def test_r10_build_event_context_no_upcoming_propagates_ok(monkeypatch):
    """R10 链闭合：成功但无解禁 → EventContext.lockup_data_status='ok'（真无解禁）。"""
    import astock
    monkeypatch.setattr(
        astock, "lockup_expiry",
        lambda *a, **k: {"history": [], "upcoming": []},
    )
    from strategies.event_factors import build_event_context

    monkeypatch.setattr("strategies.event_factors.fetch_earnings_forecast", lambda c: [])
    monkeypatch.setattr("strategies.event_factors.fetch_shareholder_change", lambda c: [])
    monkeypatch.setattr("strategies.event_factors.check_ex_dividend", lambda c, d, **kw: (False, "无"))

    ctx = build_event_context("600519")
    assert ctx.events == []
    assert ctx.lockup_data_status == "ok"       # 真无解禁，非源断
