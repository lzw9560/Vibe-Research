# -*- coding: utf-8 -*-
"""S051 D2：阈值保存 sanity 警告单测。

gene_high_threshold/qualify 超近 30 日 MAX(total_score) → 响应带 warnings。
越界返 warning + 正常保存成功；不越界无 warning；查询失败不阻塞保存。
"""
from __future__ import annotations

from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.limitup.screener import router, _check_threshold_sanity, LimitUpParamsBody


def _app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_high_threshold_above_max_returns_warning():
    """high=80 > 近 30 日最高分 70.63 → warnings 含 high_gene 提醒。"""
    body = LimitUpParamsBody(gene_qualify_threshold=50, gene_high_threshold=80, lookback_days=252)
    with mock.patch("limitup_screener.data.get_db") as m_db:
        m_db.return_value.execute.return_value.fetchone.return_value = {"mx": 70.63}
        warnings = _check_threshold_sanity(body)
    assert len(warnings) == 1
    assert "high_gene 将恒为空" in warnings[0]
    assert "80" in warnings[0]
    assert "70.63" in warnings[0]


def test_qualify_above_max_returns_warning():
    """qualify=75 > 最高分 70.63 → warnings 含 qualify 提醒。"""
    body = LimitUpParamsBody(gene_qualify_threshold=75, gene_high_threshold=80, lookback_days=252)
    with mock.patch("limitup_screener.data.get_db") as m_db:
        m_db.return_value.execute.return_value.fetchone.return_value = {"mx": 70.63}
        warnings = _check_threshold_sanity(body)
    assert len(warnings) == 2  # qualify + high 都越界


def test_no_warning_when_below_max():
    """high=60 ≤ 最高分 70.63 → 无 warning。"""
    body = LimitUpParamsBody(gene_qualify_threshold=50, gene_high_threshold=60, lookback_days=252)
    with mock.patch("limitup_screener.data.get_db") as m_db:
        m_db.return_value.execute.return_value.fetchone.return_value = {"mx": 70.63}
        warnings = _check_threshold_sanity(body)
    assert warnings == []


def test_db_failure_returns_no_warning():
    """DB 查询失败 → 不阻塞，返空 warnings。"""
    body = LimitUpParamsBody(gene_qualify_threshold=50, gene_high_threshold=80, lookback_days=252)
    with mock.patch("limitup_screener.data.get_db", side_effect=RuntimeError("db locked")):
        warnings = _check_threshold_sanity(body)
    assert warnings == []


def test_save_endpoint_returns_warnings(monkeypatch):
    """POST /api/limitup/screener/params 越界 → 响应含 warnings + status=ok。"""
    # 隔离：不真写文件 + 不真改模块变量
    import limitup_screener as ls
    monkeypatch.setattr(ls, "GENE_QUALIFY_THRESHOLD", 50)
    monkeypatch.setattr(ls, "GENE_HIGH_THRESHOLD", 60)
    monkeypatch.setattr(ls, "LOOKBACK_DAYS", 252)
    monkeypatch.setattr("routers.limitup.screener._save_limitup_params", lambda p: None)

    client = TestClient(_app())
    with mock.patch("limitup_screener.data.get_db") as m_db:
        m_db.return_value.execute.return_value.fetchone.return_value = {"mx": 70.63}
        resp = client.post("/api/limitup/screener/params", json={
            "gene_qualify_threshold": 50, "gene_high_threshold": 80, "lookback_days": 252,
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "warnings" in body
    assert any("high_gene" in w for w in body["warnings"])


def test_save_endpoint_no_warnings_when_sane(monkeypatch):
    """POST 越界阈值=60 ≤ max → 无 warnings 键。"""
    import limitup_screener as ls
    monkeypatch.setattr(ls, "GENE_QUALIFY_THRESHOLD", 50)
    monkeypatch.setattr(ls, "GENE_HIGH_THRESHOLD", 60)
    monkeypatch.setattr(ls, "LOOKBACK_DAYS", 252)
    monkeypatch.setattr("routers.limitup.screener._save_limitup_params", lambda p: None)

    client = TestClient(_app())
    with mock.patch("limitup_screener.data.get_db") as m_db:
        m_db.return_value.execute.return_value.fetchone.return_value = {"mx": 70.63}
        resp = client.post("/api/limitup/screener/params", json={
            "gene_qualify_threshold": 50, "gene_high_threshold": 60, "lookback_days": 252,
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "warnings" not in body  # 无越界不返 warnings 键（向后兼容）
