# -*- coding: utf-8 -*-
"""Smoke test: coach/review endpoint alive（catch grep-blind 误删复现，v6.5 P1 #8）。

v5 误删 coach/review router（commit 75a898a，grep /api/coach /api/review 漏 hook 名
useCoachStatus/useReviewParams→api.ts→path）——v6 恢复（96e750c + M3）但无 endpoint smoke，
同样 grep-blind 洞还在。本 test 调 TestClient 确认 4 endpoint 非 404（200 或 502 数据异常）。

教训：删 router 前必核前端 hook→api.ts→path 全链（v6 教训固化）。
"""
import pytest
from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)


@pytest.mark.parametrize("path", [
    "/api/coach/status",
    "/api/coach/timetable",
    "/api/review/params",
    "/api/review/daily",
])
def test_coach_review_endpoint_alive(path):
    """coach/review endpoint 非 404——catch grep-blind 误删复现（v5 75a898a 教训）。"""
    r = client.get(path)
    assert r.status_code in (200, 502), (
        f"{path} → {r.status_code}（应 200 或 502 数据异常，非 404 误删——v5 75a898a grep-blind 教训）"
    )
