"""S028 修复单测：limitup_screener 因子三态文案 / 漏斗 R3 name 回退 / trigger 端点。

无网络、快、确定。覆盖 spec A1/A2/A3。
"""
# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ===========================================================================
# R3：漏斗 name 回退（funnel._resolve_name / _filter_r3）
# ===========================================================================

def test_resolve_name_falls_back_to_genes():
    """auction/catalyst 无 name 时回退到 genes，不退化成 code。"""
    from candidate_funnel.funnel import _resolve_name

    genes = {"603106": {"name": "恒银科技"}}
    activity: dict[str, dict] = {}
    auction = {"603106": {"auction_open_pct": 1.2}}  # 有竞价数据但无 name
    catalyst: dict[str, dict] = {}

    name = _resolve_name("603106", genes, activity, auction, catalyst)
    assert name == "恒银科技"
    assert name != "603106"  # 不退化成 code


def test_resolve_name_all_missing_returns_code():
    from candidate_funnel.funnel import _resolve_name

    assert _resolve_name("000001", {}, {}, {}, {}) == "000001"


def test_filter_r3_filtered_out_uses_resolved_name():
    """R3 被过滤项 name 也应回退到 genes/activity，不再裸 code。"""
    from candidate_funnel.funnel import _filter_r3

    genes = {"603106": {"name": "恒银科技"}, "002425": {"name": "凯撒文化"}}
    activity: dict[str, dict] = {}
    auction = {"603106": {"auction_open_pct": 1.2}}  # 保留（有竞价）
    catalyst: dict[str, dict] = {}

    kept, filtered = _filter_r3(["603106", "002425"], auction, catalyst, genes, activity)
    assert kept == ["603106"]  # 有竞价异动 → 保留
    assert len(filtered) == 1
    assert filtered[0].code == "002425"
    assert filtered[0].name == "凯撒文化"  # 回退到 genes，非 code
    assert filtered[0].reason == "无竞价异动/公告催化"


def test_filter_r3_passed_kept_name_not_degraded():
    """端到端：R3 保留项经 _resolve_name 取名（与 R3 passed 同链）。"""
    from candidate_funnel.funnel import _resolve_name, _filter_r3

    genes = {"603106": {"name": "恒银科技"}}
    auction = {"603106": {"auction_open_pct": 1.2, "name": None}}
    kept, _ = _filter_r3(["603106"], auction, {}, genes, {})
    assert kept == ["603106"]
    # 模拟 R3 passed 的 name 解析
    assert _resolve_name(kept[0], genes, {}, auction, {}) == "恒银科技"


# ===========================================================================
# R1：涨停基因因子 data_status 三态（LimitupScreenerFactor.fetch）
# ===========================================================================

def _make_factor_with_report(report: Any):
    """构造 LimitupScreenerFactor，monkeypatch PreMarketWorkflow 返回指定 report。"""
    import pre_market_workflow as pmw
    from factors.limitup_screener_factor import LimitupScreenerFactor

    class _StubWorkflow:
        def __init__(self, date: str | None = None):
            self.date = date

        async def run(self):
            return report

    original = pmw.PreMarketWorkflow
    pmw.PreMarketWorkflow = _StubWorkflow  # type: ignore[assignment]
    try:
        return LimitupScreenerFactor()
    finally:
        # 恢复（factor fetch 内部 from-import 会读此属性）
        pass  # 测试内每个用例独立设置，末尾统一恢复见 fixture


@pytest.fixture
def restore_workflow():
    import pre_market_workflow as pmw
    original = getattr(pmw, "PreMarketWorkflow", None)
    yield
    if original is not None:
        pmw.PreMarketWorkflow = original  # type: ignore[assignment]


def _run_factor(report: Any):
    """跑 fetch 并返回 FactorResult。"""
    import pre_market_workflow as pmw

    class _Stub:
        def __init__(self, date=None):
            self.date = date

        async def run(self):
            return report

    pmw.PreMarketWorkflow = _Stub  # type: ignore[assignment]
    from factors.limitup_screener_factor import LimitupScreenerFactor
    return LimitupScreenerFactor().fetch("2026-08-06")


def test_factor_status_no_qualified(restore_workflow):
    """R1：screener 成功但 0 合格 → data_status='无合格标的'，reason 含扫描数与阈值。"""
    from pre_market_workflow import PreMarketReport

    # 79 只全未达标 → filtered_out 非空、candidates 空、warnings 空
    filtered_out = [{"code": str(i), "name": f"股{i}", "reason": "基因得分未达标"} for i in range(79)]
    report = PreMarketReport(
        date="2026-08-06",
        generated_at="2026-08-06T22:03:00",
        filtered_out=filtered_out,
    )  # candidates/strong_candidates 默认空，warnings 默认空

    fr = _run_factor(report)

    assert fr.candidates == []
    # S031 R14：data_status/reason 迁移到 L1（原 fr.data_status / fr.config['reason'] 已移）
    assert fr.layers[0].data_status == "无合格标的"
    reason = fr.layers[0].data_reason or ""
    assert "79" in reason, f"reason 应含扫描数 79: {reason}"
    assert "60" in reason, f"reason 应含阈值 60: {reason}"
    assert fr.config.get("scanned_count") == 79
    # 不再出现误导文案
    assert "预计算可能未执行" not in reason


def test_factor_status_screener_failed(restore_workflow):
    """R1：screener 异常/超时 → data_status='未取得'，保留预计算提示。"""
    from pre_market_workflow import PreMarketReport

    report = PreMarketReport(
        date="2026-08-06",
        generated_at="2026-08-06T22:03:00",
        warnings=["获取涨停池失败: timeout"],
    )  # filtered_out 空、candidates 空

    fr = _run_factor(report)

    assert fr.candidates == []
    assert fr.layers[0].data_status == "未取得"
    assert "预计算可能未执行" in (fr.layers[0].data_reason or "")


def test_factor_status_no_data(restore_workflow):
    """R1：非交易日/无涨停股数据 → data_status='未取得'，reason='今日无涨停股数据'。"""
    from pre_market_workflow import PreMarketReport

    report = PreMarketReport(date="2026-08-06", generated_at="2026-08-06T22:03:00")

    fr = _run_factor(report)

    assert fr.candidates == []
    assert fr.layers[0].data_status == "未取得"
    assert fr.layers[0].data_reason == "今日无涨停股数据"


# ===========================================================================
# R4：因子层 conditions
# ===========================================================================

def test_factor_layer_has_conditions(restore_workflow):
    """R4：三层 FunnelLayer 各带 conditions（L1 五维+阈值；L2 战法；L3 仓位）。S031 R14。"""
    from pre_market_workflow import PreMarketReport

    report = PreMarketReport(date="2026-08-06", generated_at="2026-08-06T22:03:00")
    fr = _run_factor(report)

    assert len(fr.layers) == 3  # S031 R14：打分→战法→仓位 三层
    l1, l2, l3 = fr.layers
    # L1 打分：五维 + 合格阈值 + 高基因
    joined1 = " ".join(l1.conditions or [])
    assert "次日溢价率" in joined1
    assert "合格阈值" in joined1
    assert "高基因" in joined1
    # L2 战法
    assert "战法" in " ".join(l2.conditions or [])
    # L3 仓位
    assert "仓位" in " ".join(l3.conditions or [])


# ===========================================================================
# R2：trigger 端点不再 500
# ===========================================================================

def test_trigger_endpoint_returns_started(monkeypatch):
    """R2：POST /api/limitup/screener/trigger 返回 200 {status:started}（不再 NameError 500）。"""
    import limitup_screener as ls

    async def _fake_precompute(date_str: str):
        return None

    monkeypatch.setattr(ls, "precompute_daily_async", _fake_precompute)

    from routers.limitup import screener as scr

    app = FastAPI()
    app.include_router(scr.router)
    client = TestClient(app)

    resp = client.post("/api/limitup/screener/trigger")
    assert resp.status_code == 200, f"trigger 应 200，实际 {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["status"] == "started"
    assert "date" in body
