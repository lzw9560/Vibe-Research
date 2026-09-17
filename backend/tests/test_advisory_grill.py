"""S216 Advisory 顾问团 grill-me 后端集成 test。

6-lens prompt 构建 + LLM 调用 mock + 缺 LLM 返 missing + 非法 JSON 返 raw。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient

import app  # noqa: E402


client = TestClient(app.app)


def test_build_grill_prompt_has_6_lenses():
    """6-lens prompt 含全部 6 视角（方法论/数据/过拟合/执行/风险/一致性）。"""
    from routers.advisory import _build_grill_prompt, _LENS_NAMES
    messages = _build_grill_prompt("价值溢价", "低 PE vs 高 PE 月度调仓")
    assert len(messages) == 2  # system + user
    user_content = messages[1]["content"]
    for name in _LENS_NAMES:
        assert name in user_content, f"缺 lens: {name}"
    assert "价值溢价" in user_content
    assert "低 PE vs 高 PE 月度调仓" in user_content


def test_grill_no_topic_returns_400():
    """topic 必填——空 topic 返 400。"""
    r = client.post("/api/advisory/grill", json={"topic": "", "context": "x"})
    assert r.status_code == 400


def test_grill_missing_llm_config_returns_missing(monkeypatch):
    """缺 VR_LLM_* 配置返 data_status=missing 不臆造。"""
    import chat
    monkeypatch.setattr(chat, "_get_env_llm_config", lambda: {
        "baseURL": "", "apiKey": "", "model": ""
    })
    r = client.post("/api/advisory/grill", json={"topic": "价值溢价", "context": "test"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["data_status"] == "missing"
    assert "VR_LLM" in data["note"]
    assert data["lenses"] == []


def test_grill_parses_llm_json(monkeypatch):
    """LLM 返合法 JSON → lenses/synthesis 解析。"""
    import chat
    monkeypatch.setattr(chat, "_get_env_llm_config", lambda: {
        "baseURL": "http://x", "apiKey": "k", "model": "m"
    })
    fake_llm_result = {
        "choices": [{
            "message": {
                "content": '{"lenses": [{"name": "methodology", "verdict": "pass", "evidence": "方法对"}], "synthesis": "5 pass 1 warn 可推进"}'
            }
        }]
    }
    monkeypatch.setattr(chat, "_call_llm", lambda cfg, msg, use_tools: fake_llm_result)
    r = client.post("/api/advisory/grill", json={"topic": "价值溢价", "context": "低 PE 月度"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["data_status"] == "ok"
    assert len(data["lenses"]) == 1
    assert data["lenses"][0]["name"] == "methodology"
    assert data["lenses"][0]["verdict"] == "pass"
    assert "可推进" in data["synthesis"]
    assert data["topic"] == "价值溢价"


def test_grill_raw_content_when_invalid_json(monkeypatch):
    """LLM 返非 JSON → raw_content 供人工核 不臆造结构。"""
    import chat
    monkeypatch.setattr(chat, "_get_env_llm_config", lambda: {
        "baseURL": "http://x", "apiKey": "k", "model": "m"
    })
    fake_llm_result = {
        "choices": [{
            "message": {
                "content": "这不是 JSON，是自由文本分析..."
            }
        }]
    }
    monkeypatch.setattr(chat, "_call_llm", lambda cfg, msg, use_tools: fake_llm_result)
    r = client.post("/api/advisory/grill", json={"topic": "价值溢价", "context": "x"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["data_status"] == "ok"
    assert data["lenses"] == []
    assert data["raw_content"] == "这不是 JSON，是自由文本分析..."
    assert "人工核" in data["note"]


def test_grill_uses_tools_false(monkeypatch):
    """grill 调 _call_llm 传 use_tools=False（不挂 chat.TOOLS，纯 prompt）。"""
    import chat
    monkeypatch.setattr(chat, "_get_env_llm_config", lambda: {
        "baseURL": "http://x", "apiKey": "k", "model": "m"
    })
    captured: dict = {}
    fake_llm_result = {"choices": [{"message": {"content": '{"lenses":[],"synthesis":null}'}}]}

    def fake_call(cfg, msg, use_tools):
        captured["use_tools"] = use_tools
        captured["messages"] = msg
        return fake_llm_result

    monkeypatch.setattr(chat, "_call_llm", fake_call)
    client.post("/api/advisory/grill", json={"topic": "x", "context": "y"})
    assert captured["use_tools"] is False
    assert len(captured["messages"]) == 2  # system + user
