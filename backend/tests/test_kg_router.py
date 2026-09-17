"""S216 P1 kg router test——/api/kg/* 三 endpoint 复用 kg_tools。

守工程底线：缺数据返空 + data_status='empty' 不臆造；私有数据不进 endpoint；
实体不存在 404 不臆造关系。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_mod  # noqa: E402

client = TestClient(app_mod.app)


def test_kg_entities_returns_list(monkeypatch):
    """entity_type=stock 返实体列表 + data_status=ok。"""
    def fake_entities(entity_type, filter_field="", filter_value=""):
        return [{"_path": "stocks/600519.md", "_filename": "600519", "name": "贵州茅台"}]
    monkeypatch.setattr("ai.tools.kg_tools.query_kg_entities", fake_entities)
    r = client.get("/api/kg/entities", params={"entity_type": "stock"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["entity_type"] == "stock"
    assert d["count"] == 1
    assert d["data_status"] == "ok"
    assert d["entities"][0]["_filename"] == "600519"


def test_kg_entities_empty(monkeypatch):
    """缺数据返空 list + data_status='empty'，不臆造假实体。"""
    monkeypatch.setattr("ai.tools.kg_tools.query_kg_entities", lambda *a, **k: [])
    r = client.get("/api/kg/entities", params={"entity_type": "nonexistent"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["count"] == 0
    assert d["data_status"] == "empty"
    assert d["entities"] == []


def test_kg_inbox(monkeypatch):
    """/api/kg/inbox 调 query_kg_entities('inbox') 返 M7 待审队列。"""
    captured = {}
    def fake_inbox(entity_type, filter_field="", filter_value=""):
        captured["entity_type"] = entity_type
        return [{"_path": "inbox/pending-1.md", "_filename": "pending-1"}]
    monkeypatch.setattr("ai.tools.kg_tools.query_kg_entities", fake_inbox)
    r = client.get("/api/kg/inbox")
    assert r.status_code == 200
    d = r.json()["data"]
    assert captured["entity_type"] == "inbox"
    assert d["count"] == 1
    assert d["data_status"] == "ok"
    assert "M7" in d["note"]


def test_kg_inbox_empty(monkeypatch):
    """inbox 无待审返空 + data_status=empty 不臆造。"""
    monkeypatch.setattr("ai.tools.kg_tools.query_kg_entities", lambda *a, **k: [])
    r = client.get("/api/kg/inbox")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["count"] == 0
    assert d["data_status"] == "empty"


def test_kg_flow_returns_relations(monkeypatch):
    """/api/kg/flow 返实体关系列表。"""
    def fake_relations(code, entity_type="stock"):
        return {"entity": code, "entity_type": entity_type, "path": "stocks/600519.md",
                "relations": [{"target": "strategies/龙头首板", "link": "[[龙头首板]]"}],
                "total": 1}
    monkeypatch.setattr("ai.tools.kg_tools.query_kg_relations", fake_relations)
    r = client.get("/api/kg/flow", params={"entity_code": "600519", "entity_type": "stock"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["entity"] == "600519"
    assert d["total"] == 1
    assert d["relations"][0]["target"] == "strategies/龙头首板"


def test_kg_flow_404_unknown(monkeypatch):
    """实体不存在返 404，不臆造关系。"""
    monkeypatch.setattr("ai.tools.kg_tools.query_kg_relations",
                        lambda *a, **k: {"error": "实体 notfound 不存在"})
    r = client.get("/api/kg/flow", params={"entity_code": "notfound"})
    assert r.status_code == 404


def test_no_private_data_in_response(monkeypatch):
    """返值无私有数据（持仓/研报/API key）——守私有数据隔离底线。"""
    monkeypatch.setattr("ai.tools.kg_tools.query_kg_entities",
                        lambda *a, **k: [{"_path": "stocks/x.md", "_filename": "x"}])
    r = client.get("/api/kg/entities", params={"entity_type": "stock"})
    body = r.text
    for secret in ["api_key", "API_KEY", "position", "holding", "研报"]:
        assert secret not in body, f"私有数据 {secret} 泄漏: {body}"
