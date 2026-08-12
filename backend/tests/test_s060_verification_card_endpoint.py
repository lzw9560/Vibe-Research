# -*- coding: utf-8 -*-
"""S060 端点测试：verification-card 端点。"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_vc_db(tmp_path, monkeypatch):
    db_path = tmp_path / "verification_card.db"
    import workflow.verification_card as vc
    monkeypatch.setattr(vc, "_DB_PATH", str(db_path))
    vc.run_migrations()
    return str(db_path)


class TestVerificationCardEndpoint:
    def test_empty_when_no_conditions(self, isolated_vc_db):
        import app as appmod
        client = TestClient(appmod.app)
        r = client.get("/api/workflow/verification-card")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["count"] == 0
        assert data["conditions"] == []

    def test_returns_conditions_after_generate(self, isolated_vc_db, monkeypatch):
        # 先生成条件
        from workflow.verification_card import generate_and_save
        emo = {"date": "2026-08-12", "zt_count": 58, "break_rate": 0.15,
               "max_boards": 3, "seal_rate": 0.85, "promotion_rate": 0.4, "yzt_count": 99}
        generate_and_save(emo, "2026-08-12")

        # 查询
        from vr_paths import last_trading_date_str
        import app as appmod
        client = TestClient(appmod.app)
        r = client.get("/api/workflow/verification-card", params={"date": "2026-08-12"})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] >= 5
        assert "status_summary" in data

    def test_generate_endpoint(self, isolated_vc_db, monkeypatch):
        import app as appmod
        import market

        # mock market._emotion
        def _fake_emotion(date):
            return {"date": date, "zt_count": 58, "break_rate": 0.15,
                    "max_boards": 3, "seal_rate": 0.85, "promotion_rate": 0.4, "yzt_count": 99}
        monkeypatch.setattr(market, "_emotion", _fake_emotion)

        client = TestClient(appmod.app)
        r = client.post("/api/workflow/verification-card/generate", params={"date": "2026-08-12"})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["generated"] >= 5

    def test_generate_endpoint_empty_emotion(self, isolated_vc_db, monkeypatch):
        import app as appmod
        import market

        monkeypatch.setattr(market, "_emotion", lambda d: {})

        client = TestClient(appmod.app)
        r = client.post("/api/workflow/verification-card/generate", params={"date": "2026-08-12"})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["generated"] == 0

    def test_verify_endpoint(self, isolated_vc_db, monkeypatch):
        # 先生成
        from workflow.verification_card import generate_and_save
        emo = {"date": "2026-08-11", "zt_count": 58, "break_rate": 0.15,
               "max_boards": 3, "seal_rate": 0.85, "promotion_rate": 0.4, "yzt_count": 99}
        generate_and_save(emo, "2026-08-11")

        # mock market._emotion 返回 T+1 数据
        import market
        import app as appmod

        def _fake_emotion(date):
            # T+1 涨停 130（>58×1.2=69.6 → met_up）
            return {"date": date, "zt_count": 130, "break_rate": 0.10,
                    "max_boards": 4, "seal_rate": 0.90, "promotion_rate": 0.50, "yzt_count": 58}
        monkeypatch.setattr(market, "_emotion", _fake_emotion)

        client = TestClient(appmod.app)
        r = client.post("/api/workflow/verification-card/verify")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["verified"] >= 5
