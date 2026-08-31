# -*- coding: utf-8 -*-
"""S061 预测账本测试。

覆盖：
- R1 数据层：migration 幂等 + 状态机
- R2 入账：幂等（同日同源同股一条）+ 手动录入端点
- R3 验证：hit/miss/voided 三态 + 幂等
- R4 统计：命中率分桶 + 样本不足标注
"""
from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import patch
from types import SimpleNamespace

import pytest
from datetime import datetime as _real_datetime


# S061 测试硬编码 stated_at="2026-08-01" + days=30 窗口；不冻 now 则 09-01 起
# 08-01 落 30 日窗外 → list_predictions 返空 → assert 崩。冻 now=2026-08-10 让
# 窗口数学日期无关（cutoff=07-11，08-01 在内；08-05 verify 日 ≤ due_date）。
_FROZEN_NOW = _real_datetime(2026, 8, 10, 12, 0, 0)


class _FrozenDatetime(_real_datetime):
    @classmethod
    def now(cls, tz=None):
        return _FROZEN_NOW


@pytest.fixture(autouse=True)
def _freeze_now(monkeypatch):
    """冻 prediction_ledger/prediction_verify 的 datetime.now → 测试日期无关。"""
    import prediction_ledger as pl
    import prediction_verify as pv
    monkeypatch.setattr(pl, "datetime", _FrozenDatetime)
    monkeypatch.setattr(pv, "datetime", _FrozenDatetime)


@pytest.fixture()
def tmp_db():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "test_pred.db")
    import prediction_ledger as pl
    pl._migrate_schema(db)
    yield db
    shutil.rmtree(tmp)


class TestR1DataLayer:
    """R1：数据层 + 状态机。"""

    def test_migration_idempotent(self, tmp_db):
        """重复跑迁移不报错、表存在。"""
        import prediction_ledger as pl
        pl._migrate_schema(tmp_db)  # 再跑一次
        import sqlite3
        conn = sqlite3.connect(tmp_db)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        conn.close()
        assert ("prediction_ledger",) in tables

    def test_status_transitions_pending_to_hit(self, tmp_db):
        import prediction_ledger as pl
        p = pl.Prediction(stated_at="2026-08-01", source="manual", code="600519")
        pid = pl.add_prediction(p, db_path=tmp_db)
        assert pid is not None
        ok = pl.verify_prediction(pid, 0.03, "hit", db_path=tmp_db)
        assert ok
        # 再验一次（幂等：已不是 pending）
        ok2 = pl.verify_prediction(pid, 0.05, "hit", db_path=tmp_db)
        assert not ok2

    def test_due_date_computation(self, tmp_db):
        import prediction_ledger as pl
        p = pl.Prediction(stated_at="2026-08-01", source="manual", code="000001", horizon=3)
        pid = pl.add_prediction(p, db_path=tmp_db)
        assert pid is not None
        # 查回 due_date
        preds = pl.list_predictions(days=30, db_path=tmp_db)
        assert len(preds) == 1
        # due_date 应该 > stated_at
        assert preds[0].due_date > "2026-08-01"


class TestR2Ingestion:
    """R2：入账幂等 + 手动录入端点。"""

    def test_ingestion_idempotent(self, tmp_db):
        """同日同源同股只一条。"""
        import prediction_ledger as pl
        p = pl.Prediction(stated_at="2026-08-01", source="funnel_candidate",
                           code="600519", signal_ref="funnel:final")
        id1 = pl.add_prediction(p, db_path=tmp_db)
        id2 = pl.add_prediction(p, db_path=tmp_db)  # 重复
        assert id1 is not None
        assert id2 is None  # OR IGNORE 忽略
        preds = pl.list_predictions(days=30, db_path=tmp_db)
        assert len(preds) == 1

    def test_different_sources_same_code_ok(self, tmp_db):
        """同日同股不同 source 可各一条。"""
        import prediction_ledger as pl
        p1 = pl.Prediction(stated_at="2026-08-01", source="funnel_candidate", code="600519")
        p2 = pl.Prediction(stated_at="2026-08-01", source="strategy_hit", code="600519")
        id1 = pl.add_prediction(p1, db_path=tmp_db)
        id2 = pl.add_prediction(p2, db_path=tmp_db)
        assert id1 is not None and id2 is not None
        assert id1 != id2

    def test_manual_endpoint(self, tmp_db):
        """POST /api/prediction-ledger 手动录入。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers import prediction_ledger_router as r
        import prediction_ledger as pl
        r.pl.WINRATE_DB_PATH = tmp_db

        app = FastAPI()
        app.include_router(r.router)
        client = TestClient(app)

        resp = client.post("/api/prediction-ledger", json={
            "stated_at": "2026-08-01", "code": "600519", "name": "茅台",
            "source": "manual", "horizon": 1,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # 幂等
        resp2 = client.post("/api/prediction-ledger", json={
            "stated_at": "2026-08-01", "code": "600519", "name": "茅台",
            "source": "manual", "horizon": 1,
        })
        assert resp2.json()["status"] == "duplicate"

        # 非法 source
        resp3 = client.post("/api/prediction-ledger", json={
            "stated_at": "2026-08-01", "code": "000001", "source": "bogus",
        })
        assert resp3.status_code == 400


class TestR3Verification:
    """R3：到期验证三态 + 幂等。"""

    def test_verify_hit_miss_voided(self, tmp_db):
        import prediction_ledger as pl
        import prediction_verify as pv
        p1 = pl.Prediction(stated_at="2026-08-01", source="manual", code="600519", horizon=1)
        p2 = pl.Prediction(stated_at="2026-08-01", source="manual", code="000001", horizon=1)
        p3 = pl.Prediction(stated_at="2026-08-01", source="manual", code="002", horizon=1)
        id1 = pl.add_prediction(p1, db_path=tmp_db)
        id2 = pl.add_prediction(p2, db_path=tmp_db)
        id3 = pl.add_prediction(p3, db_path=tmp_db)

        with patch("prediction_verify._calc_actual_return") as mock:
            mock.side_effect = lambda code, stated, h: (
                0.03 if code == "600519" else
                (-0.02 if code == "000001" else None)
            )
            r = pv.verify_due_predictions("2026-08-05", db_path=tmp_db)

        assert r["hit"] == 1
        assert r["miss"] == 1
        assert r["voided"] == 1

    def test_verify_idempotent(self, tmp_db):
        import prediction_ledger as pl
        import prediction_verify as pv
        p = pl.Prediction(stated_at="2026-08-01", source="manual", code="600519", horizon=1)
        pid = pl.add_prediction(p, db_path=tmp_db)

        with patch("prediction_verify._calc_actual_return") as mock:
            mock.return_value = 0.03
            r1 = pv.verify_due_predictions("2026-08-05", db_path=tmp_db)
            r2 = pv.verify_due_predictions("2026-08-05", db_path=tmp_db)

        assert r1["verified"] == 1
        assert r2["verified"] == 0  # 已验证不再重写


class TestR4Stats:
    """R4：命中率统计 + 样本不足标注。"""

    def test_hit_rate_buckets(self, tmp_db):
        import prediction_ledger as pl
        for code in ["001", "002", "003"]:
            p = pl.Prediction(stated_at="2026-08-01", source="manual", code=code, horizon=1)
            pl.add_prediction(p, db_path=tmp_db)
        # 手动验证两条
        preds = pl.list_predictions(days=30, db_path=tmp_db)
        pl.verify_prediction(preds[0].id, 0.03, "hit", db_path=tmp_db)
        pl.verify_prediction(preds[1].id, -0.02, "miss", db_path=tmp_db)

        stats = pl.compute_hit_rate(days=30, db_path=tmp_db)
        assert len(stats) == 1
        s = stats[0]
        assert s["source"] == "manual"
        assert s["hit"] == 1
        assert s["miss"] == 1
        assert s["hit_rate"] == 0.5
        assert s["sample_sufficient"] is False  # verified=2 < 10

    def test_ledger_endpoint(self, tmp_db):
        """GET /api/prediction-ledger 返列表 + 统计。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers import prediction_ledger_router as r
        r.pl.WINRATE_DB_PATH = tmp_db

        app = FastAPI()
        app.include_router(r.router)
        client = TestClient(app)

        client.post("/api/prediction-ledger", json={
            "stated_at": "2026-08-01", "code": "600519", "source": "manual", "horizon": 1,
        })
        resp = client.get("/api/prediction-ledger?days=30")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        assert isinstance(body["stats"], list)
        assert "历史统计特征" in body["disclaimer"]
