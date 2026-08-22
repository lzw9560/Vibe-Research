# -*- coding: utf-8 -*-
"""S003 后端 API 缺陷修复 —— TDD 回归用例（离线）。

每个 fix 对应一条先写、先红的测试；实现后转绿。
约定：不联网（`-m "not live"`），数据层用 monkeypatch 打桩。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402

client = TestClient(app_module.app)


# ── T1（R2）: limitup_sti 导出 BEIJING_TZ ──────────────────────────


def test_limitup_sti_exports_beijing_tz():
    """limitup_sti 包必须导出公开 BEIJING_TZ（routers/sti.py:28 依赖）。"""
    import limitup_sti as sti

    assert hasattr(sti, "BEIJING_TZ"), "limitup_sti 未导出 BEIJING_TZ（routers/sti.py 会 AttributeError）"
    tz = sti.BEIJING_TZ
    now = datetime.now(tz)  # sti.py:28 用法
    assert now.tzinfo is tz


# ── T3（R4）: scheduled-tasks /types 路由顺序 ─────────────────────


def test_scheduled_tasks_types_route_not_shadowed():
    """/api/scheduled-tasks/types 不能被 /{task_id} 捕获（422），应返回 200+列表。"""
    res = client.get("/api/scheduled-tasks/types")
    assert res.status_code == 200, f"types 被 /{{task_id}} 捕获: {res.status_code} {res.text[:200]}"
    payload = res.json()
    data = payload.get("data", payload)
    assert isinstance(data, list) and len(data) > 0, f"应返回任务类型列表: {payload}"


# ── T4（R7）: recommendation 无数据返回 200+null ─────────────────


def test_recommendation_stock_missing_returns_200_null(monkeypatch):
    """个股无推荐时应 200+{"data": null}，而非 404（避免前端误判）。"""
    import recommendation_engine as re_mod

    async def _none(code, date=None):
        return None

    monkeypatch.setattr(re_mod, "get_recommendation", _none)
    res = client.get("/api/recommendation/600519")
    assert res.status_code == 200, f"无数据应 200 非 404: {res.status_code} {res.text[:200]}"
    assert res.json() == {"data": None}


# ── T2（R3）: limitup/metrics 用对 ScreenerResult 字段 ─────────────


def test_limitup_metrics_returns_200(monkeypatch):
    """/api/limitup/metrics 不再因 .candidates AttributeError 502。"""
    import astock
    import limitup_screener as ls
    from limitup_screener.models import GeneScore, ScreenerResult

    # 清模块级缓存，避免别的用例残留
    import routers.limitup.metrics as m
    m._METRICS_CACHE.clear()

    g = GeneScore(
        code="600519", name="贵州茅台", total_score=85.0,
        factors={}, wilson_adjusted=85.0, qualify=True, high_gene=True,
        last_zt_dates=[], zt_count_250d=3,
    )

    async def _fake_screener(date):
        return ScreenerResult(
            date=date or "2026-07-29",
            gene_scores=[g], qualified=[g], high_gene=[g],
            updated="2026-07-29 10:00", disclaimer="客观公开数据",
        )

    monkeypatch.setattr(ls, "get_screener_result", _fake_screener)
    monkeypatch.setattr(astock, "em_zt_topic_pool", lambda *a, **k: [])
    # 交易日守卫（日期语义完整性 P2）：测试在非交易日跑会被守卫拦截返空，
    # 但本测验证 ScreenerResult 字段映射逻辑，须放行（mock is_trading_day=True）。
    import routers.limitup.metrics as _metrics_mod
    monkeypatch.setattr(_metrics_mod, "is_trading_day", lambda d=None: True)

    res = client.get("/api/limitup/metrics")
    assert res.status_code == 200, f"metrics 502: {res.status_code} {res.text[:300]}"
    body = res.json()
    assert "gene_distribution" in body, f"缺 gene_distribution: {body}"
    assert body["avg_gene_score"] == 85.0


# ── T5–T7（R6）: astock disclosure/kline/finance 空返回守卫 ─────────


def test_disclosure_graceful_on_akshare_parse_error(monkeypatch):
    """akshare 内部抛 string indices must be integers → 端点 200+空，而非 502。"""
    import astock

    class _FakeAK:
        def stock_zh_a_disclosure_report_cninfo(self, symbol, market):
            raise TypeError("string indices must be integers")

    monkeypatch.setattr(astock, "_akshare", lambda: _FakeAK())
    res = client.get("/api/disclosure?code=600519")
    assert res.status_code == 200, f"disclosure 502: {res.status_code} {res.text[:200]}"
    assert res.json() == {"data": []}


def test_kline_graceful_on_mootdx_empty(monkeypatch):
    """mootdx bars() 抛 not enough values to unpack → 端点 200+空，而非 502。"""

    import astock

    class _FakeClient:
        def bars(self, symbol, category, offset):
            raise ValueError("not enough values to unpack (expected 2, got 0)")

    monkeypatch.setattr(astock, "_mootdx_client", lambda: _FakeClient())
    res = client.get("/api/kline?code=600519")
    assert res.status_code == 200, f"kline 502: {res.status_code} {res.text[:200]}"
    assert res.json() == {"data": []}


def test_finance_graceful_on_mootdx_empty(monkeypatch):
    """mootdx finance() 抛 not enough values to unpack → 端点 200+空，而非 502。"""
    import astock

    class _FakeClient:
        def finance(self, symbol):
            raise ValueError("not enough values to unpack (expected 2, got 0)")

    monkeypatch.setattr(astock, "_mootdx_client", lambda: _FakeClient())
    res = client.get("/api/finance?code=600519")
    assert res.status_code == 200, f"finance 502: {res.status_code} {res.text[:200]}"
    assert res.json() == {"data": {}}


def test_kline_finance_graceful_when_mootdx_factory_fails(monkeypatch):
    """_mootdx_client() 自身抛 ValueError（连不上 TDX）→ kline/finance 端点 200+空，非 502。"""
    import astock

    def _boom(*a, **k):
        raise ValueError("not enough values to unpack (expected 2, got 0)")

    monkeypatch.setattr(astock, "_mootdx_client", _boom)
    rk = client.get("/api/kline?code=600519")
    rf = client.get("/api/finance?code=600519")
    assert rk.status_code == 200 and rk.json() == {"data": []}, rk.text[:120]
    assert rf.status_code == 200 and rf.json() == {"data": {}}, rf.text[:120]


# ── 候选池漏斗：async 端点不得同步阻塞事件循环（live 验收发现） ──


def test_candidates_does_not_block_event_loop(monkeypatch):
    """/api/workflow/candidates 的 run_funnel 须走 to_thread，不得卡事件循环。"""
    import asyncio
    import time as _time

    import httpx
    from candidate_funnel import funnel as funnel_mod
    from unittest.mock import MagicMock

    app_module._RESPONSE_CACHE.clear()

    def slow_run(*a, **k):
        _time.sleep(0.3)  # 模拟漏斗的同步阻塞 I/O
        return MagicMock(final_candidates=[], layers=[])

    monkeypatch.setattr(funnel_mod, "run_funnel", slow_run)

    async def main():
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            async def probe():
                t0 = _time.perf_counter()
                r = await c.get("/api/sentiment/weather/pardon")
                return _time.perf_counter() - t0, r.status_code

            cand_task = asyncio.create_task(c.get("/api/workflow/candidates"))
            delay, st = await probe()
            try:
                await cand_task
            except Exception:
                pass
            return delay, st

    delay, st = asyncio.run(main())
    assert delay < 0.25, f"事件循环被 candidates 阻塞：probe 延迟 {delay:.2f}s"



# ── T9（R5）: kline_history 建表 + 缺表守卫 ───────────────────────


def test_kline_history_stats_empty_db_200(tmp_path, monkeypatch):
    """空库（无 kline 表）→ /api/kline-history/stats 返回 200，不再 502。"""
    import routers.kline_history as kh

    monkeypatch.setattr(kh, "KLINE_DB_PATH", str(tmp_path / "kh.db"))
    res = client.get("/api/kline-history/stats")
    assert res.status_code == 200, f"stats 502: {res.status_code} {res.text[:200]}"
    data = res.json()["data"]
    assert data["total_records"] == 0


def test_kline_history_code_with_data_200(tmp_path, monkeypatch):
    """/api/kline-history/{code} 有数据 → 200 + count。"""
    import routers.kline_history as kh

    db_path = str(tmp_path / "kh.db")
    monkeypatch.setattr(kh, "KLINE_DB_PATH", db_path)
    # 建表 + 插一行（_get_kline_db 会 CREATE TABLE IF NOT EXISTS）
    conn = kh._get_kline_db()
    conn.execute(
        "INSERT OR REPLACE INTO kline(code,name,date,open,close,high,low,volume,amount,fetched_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("600519", "贵州茅台", "2026-07-28", 1800.0, 1810.0, 1820.0, 1790.0, 1000.0, 1800000.0, "ts"),
    )
    conn.commit(); conn.close()

    res = client.get("/api/kline-history/600519")
    assert res.status_code == 200, f"kline-history/600519: {res.status_code} {res.text[:200]}"
    body = res.json()
    assert body["count"] == 1 and body["code"] == "600519"


# ── T11（R1）: risk 阻塞 I/O 不卡事件循环 ────────────────────────


def test_risk_does_not_block_event_loop(monkeypatch):
    """update_one_day_risk_realtime 的阻塞网络 I/O 必须走 to_thread，不得卡事件循环。"""
    import asyncio
    import time as _time

    import astock
    import limitup_screener as ls
    import risk_models

    # 模拟阻塞网络：dragon_tiger_board sleep 0.3s（dragon_tiger_risk + concentration 各调一次）
    def slow_dt(*a, **k):
        _time.sleep(0.3)
        return {"records": []}

    monkeypatch.setattr(astock, "dragon_tiger_board", slow_dt)

    async def _empty_screener(date=None):
        m = MagicMock()
        m.gene_scores = []
        return m

    monkeypatch.setattr(ls, "get_screener_result", _empty_screener)
    monkeypatch.setattr(risk_models, "_get_realtime_capital_flow", lambda code: {})

    try:
        import seat_engine as se

        monkeypatch.setattr(
            se, "get_engine",
            lambda: MagicMock(compute_consensus_signal=lambda *a, **k: None),
        )
    except Exception:
        pass

    async def probe():
        t0 = _time.perf_counter()
        await asyncio.sleep(0.05)
        return _time.perf_counter() - t0

    async def main():
        risk_task = asyncio.create_task(risk_models.update_one_day_risk_realtime("600519"))
        delay = await probe()
        await risk_task
        return delay

    delay = asyncio.run(main())
    # 若事件循环被同步 get_kline(0.3s×3) 阻塞，probe 会延迟 ≥0.3s；修复后应 ~0.05s
    assert delay < 0.25, f"事件循环被阻塞：probe 延迟 {delay:.2f}s（应 <0.25s）"


# ── T12（R1）: risk/dashboard 限 ≤20 + 并发 + 缓存 ────────────────


def test_risk_dashboard_caps_and_caches(monkeypatch):
    """/api/risk/dashboard：候选 ≤20 只、第二次命中缓存。"""
    from types import SimpleNamespace

    import limitup_screener as ls
    import risk_models as risk
    from limitup_screener.models import GeneScore, ScreenerResult

    # 清 app 路由缓存，避免用例间残留
    app_module._RESPONSE_CACHE.clear()
    import routers.risk as _rr
    _rr._DASHBOARD_CACHE.clear()

    genes = [
        GeneScore(code=f"60000{i}", name=f"股{i}", total_score=70.0,
                  factors={}, wilson_adjusted=70.0, qualify=True, high_gene=False,
                  last_zt_dates=[], zt_count_250d=0)
        for i in range(50)
    ]

    async def _scr(date=None):
        return ScreenerResult(date="2026-07-29", gene_scores=genes,
                             qualified=genes, high_gene=genes, updated="x", disclaimer="d")

    calls = {"n": 0}

    async def _fake_risk(code):
        calls["n"] += 1
        return SimpleNamespace(risk_score=50.0, risk_level="MEDIUM",
                               factors=["a", "b"], last_updated="t")

    monkeypatch.setattr(ls, "get_screener_result", _scr)
    monkeypatch.setattr(risk, "update_one_day_risk_realtime", _fake_risk)

    res = client.get("/api/risk/dashboard")
    assert res.status_code == 200, f"dashboard: {res.status_code} {res.text[:200]}"
    data = res.json()["data"]
    assert data["total_stocks"] <= 20, f"dashboard 应限 ≤20 只，实际 {data['total_stocks']}"
    first = calls["n"]
    assert first <= 20, f"调用 risk 次数应 ≤20，实际 {first}"

    res2 = client.get("/api/risk/dashboard")
    assert res2.status_code == 200
    assert calls["n"] == first, f"第二次应命中缓存不再调用 risk：{calls['n']} vs {first}"







