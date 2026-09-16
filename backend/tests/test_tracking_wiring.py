# -*- coding: utf-8 -*-
"""S204 T9: 多日跟踪查询 API 接线测试。

验证 GET /api/tracking/pool + /api/tracking/{code}/snapshots 端点接线（tracking_pool_repo 已 import 时建表）。
"""
from fastapi.testclient import TestClient

import app as app_mod  # noqa: E402

client = TestClient(app_mod.app)


def test_tracking_pool_endpoint_returns_count():
    """GET /api/tracking/pool → 200 + count/tracks/status 字段（默认 status='tracking'）。"""
    r = client.get("/api/tracking/pool")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "count" in data
    assert "tracks" in data
    assert data["status"] == "tracking"


def test_tracking_pool_status_query_param():
    """GET /api/tracking/pool?status=admit → status 字段跟随查询参数。"""
    r = client.get("/api/tracking/pool?status=admit")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "admit"


def test_tracking_snapshots_endpoint():
    """GET /api/tracking/{code}/snapshots → 200 + code/snapshots 字段（空池也合法）。"""
    r = client.get("/api/tracking/600000/snapshots")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["code"] == "600000"
    assert "snapshots" in data
    assert "count" in data
