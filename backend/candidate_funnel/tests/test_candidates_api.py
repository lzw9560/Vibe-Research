# -*- coding: utf-8 -*-
"""候选池 API 路由测试（S002 E1-E8，TDD RED）。

mock funnel.run_funnel / diagnose，经 TestClient 验证 6 端点 + config 持久 + 缓存。
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import app as app_module
from candidate_funnel import funnel as funnel_mod
from candidate_funnel.models import (
    ActivityAssessment,
    ActivityTier,
    DiagnosisCard,
    FunnelLayer,
    FunnelResult,
    IndicatorSet,
    StabilizationSignals,
    ThresholdConfig,
)

client = TestClient(app_module.app)


def _card(code="600519") -> DiagnosisCard:
    return DiagnosisCard(
        code=code, name="贵州茅台",
        indicators=IndicatorSet(code=code, name="贵州茅台", turnover_pct=25.0),
        activity=ActivityAssessment(tier=ActivityTier.HOT, rules_applied=["换手>=20%"]),
        stabilization=StabilizationSignals(),
        risk_flags=[], as_of=datetime(2026, 7, 28, 9, 0),
    )


def _funnel_result() -> FunnelResult:
    return FunnelResult(
        run_id="run-2026-07-28-all", date="2026-07-28",
        layers=[FunnelLayer(layer_id="R1", name="宽源", as_of=datetime(2026, 7, 28, 9, 0),
                            input_count=3, output_count=2, filtered_out=[], output_codes=["600519"])],
        final_candidates=[_card()], threshold_config=ThresholdConfig(mode="manual"),
        sentiment_phase="晴天", as_of=datetime(2026, 7, 28, 9, 0),
    )


class TestCandidatesRoutes(unittest.TestCase):
    def setUp(self):
        self._funnel = mock.patch.object(funnel_mod, "run_funnel", return_value=_funnel_result())
        self._diag = mock.patch.object(funnel_mod, "diagnose", return_value=_card())
        self._funnel.start(); self._diag.start()
        self.addCleanup(self._funnel.stop); self.addCleanup(self._diag.stop)

    def test_post_funnel(self):
        r = client.post("/api/workflow/candidates/funnel", params={"stage": "all", "date": "2026-07-28"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["run_id"], "run-2026-07-28-all")

    def test_get_candidates(self):
        r = client.get("/api/workflow/candidates", params={"date": "2026-07-28"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(len(data) >= 1)
        self.assertEqual(data[0]["code"], "600519")

    def test_get_diagnosis_card(self):
        r = client.get("/api/workflow/candidates/600519/diagnosis")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["code"], "600519")

    def test_get_funnel_layers(self):
        r = client.get("/api/workflow/funnel/layers", params={"run_id": "run-2026-07-28-all"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]["layer_id"], "R1")

    def test_put_then_get_config(self):
        put = client.put("/api/workflow/funnel/config", json={"mode": "manual"})
        self.assertEqual(put.status_code, 200)
        get = client.get("/api/workflow/funnel/config")
        self.assertEqual(get.status_code, 200)
        self.assertEqual(get.json()["config"]["mode"], "manual")

    def test_get_config_returns_sources(self):
        get = client.get("/api/workflow/funnel/config")
        self.assertEqual(get.status_code, 200)
        self.assertIn("sources", get.json())


class TestCacheAndAuth(unittest.TestCase):
    def test_cached_get_idempotent(self):
        with mock.patch.object(funnel_mod, "run_funnel", return_value=_funnel_result()):
            r1 = client.get("/api/workflow/candidates", params={"date": "2026-07-28"})
            r2 = client.get("/api/workflow/candidates", params={"date": "2026-07-28"})
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r1.json(), r2.json())


if __name__ == "__main__":
    unittest.main()
