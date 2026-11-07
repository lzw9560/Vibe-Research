# -*- coding: utf-8 -*-
"""test_client.py — send_feishu mock 测试。

测试覆盖：
- 发送成功（飞书返回 code=0）
- 发送失败（飞书返回非零 code）
- 网络异常重试（urlopen 抛 OSError）→ 重试耗尽后返回 False
- WEBHOOK 未设置 → 直接返回 False
- ping_healthchecks 被调用（成功/失败路径）

用 monkeypatch mock urllib.request.urlopen + client 内部 ping。
重试退避通过 monkeypatch sleep 加速（避免测试等待 1+2+4=7s）。
"""
from __future__ import annotations

import io
import json
from unittest.mock import MagicMock

import pytest

from feishu import client


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """所有 time.sleep 立即返回，避免重试退避拖慢测试。"""
    monkeypatch.setattr(client.time, "sleep", lambda *_a, **_kw: None)


@pytest.fixture(autouse=True)
def _ensure_webhook(monkeypatch):
    """测试默认注入一个假 WEBHOOK，避免触发"未设置"早退。"""
    monkeypatch.setattr(client, "WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/test-token")
    monkeypatch.setattr(client, "HEALTHCHECKS_URL", "")  # 默认不 ping，单独测


def _make_urlopen_response(payload: dict):
    """构造一个 context manager mock，模拟 urllib.request.urlopen 的返回。"""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    cm.read = MagicMock(return_value=json.dumps(payload).encode("utf-8"))
    return cm


# ─── 成功路径 ───

def test_send_success(monkeypatch):
    """飞书返回 code=0 → send_feishu 返回 True。"""
    urlopen_mock = MagicMock(return_value=_make_urlopen_response({"code": 0, "msg": "ok"}))
    monkeypatch.setattr("urllib.request.urlopen", urlopen_mock)

    ping_mock = MagicMock()
    monkeypatch.setattr(client, "ping_healthchecks", ping_mock)

    ok = client.send_feishu({"header": {}, "elements": []}, mode="test")
    assert ok is True
    assert urlopen_mock.call_count == 1  # 成功不重试
    ping_mock.assert_called_once_with(True, "test")


def test_success_with_statuscode_field(monkeypatch):
    """飞书旧版返回 StatusCode=0 也算成功。"""
    monkeypatch.setattr("urllib.request.urlopen",
                        MagicMock(return_value=_make_urlopen_response({"StatusCode": 0})))
    monkeypatch.setattr(client, "ping_healthchecks", MagicMock())
    ok = client.send_feishu({}, mode="test")
    assert ok is True


# ─── 失败路径（飞书返回非零，不重试） ───

def test_send_feishu_nonzero_code(monkeypatch):
    """飞书返回非零 code → send_feishu 返回 False，不重试。"""
    urlopen_mock = MagicMock(return_value=_make_urlopen_response({"code": 19021, "msg": "token invalid"}))
    monkeypatch.setattr("urllib.request.urlopen", urlopen_mock)
    ping_mock = MagicMock()
    monkeypatch.setattr(client, "ping_healthchecks", ping_mock)

    ok = client.send_feishu({}, mode="test")
    assert ok is False
    # 飞书业务层失败不重试（只重试网络异常）
    assert urlopen_mock.call_count == 1
    ping_mock.assert_called_once_with(False, "test")


# ─── 网络异常重试 ───

def test_send_retry_on_network_error(monkeypatch):
    """网络异常（OSError）→ 重试 3 次后返回 False。"""
    urlopen_mock = MagicMock(side_effect=OSError("connection refused"))
    monkeypatch.setattr("urllib.request.urlopen", urlopen_mock)
    monkeypatch.setattr(client, "ping_healthchecks", MagicMock())

    ok = client.send_feishu({}, mode="test")
    assert ok is False
    # 重试 3 次（内置/tenacity stop_after_attempt(3)）
    assert urlopen_mock.call_count == 3


def test_send_retry_then_success(monkeypatch):
    """前两次网络异常，第三次成功 → 返回 True，共调用 3 次。"""
    success_resp = _make_urlopen_response({"code": 0})
    urlopen_mock = MagicMock(side_effect=[OSError("fail1"), OSError("fail2"), success_resp])
    monkeypatch.setattr("urllib.request.urlopen", urlopen_mock)
    monkeypatch.setattr(client, "ping_healthchecks", MagicMock())

    ok = client.send_feishu({}, mode="test")
    assert ok is True
    assert urlopen_mock.call_count == 3


def test_send_retry_timeout_error(monkeypatch):
    """TimeoutError 也是网络异常 → 重试 3 次。"""
    urlopen_mock = MagicMock(side_effect=TimeoutError("read timeout"))
    monkeypatch.setattr("urllib.request.urlopen", urlopen_mock)
    monkeypatch.setattr(client, "ping_healthchecks", MagicMock())

    ok = client.send_feishu({}, mode="test")
    assert ok is False
    assert urlopen_mock.call_count == 3


def test_non_network_exception_no_retry(monkeypatch):
    """非网络异常（如 ValueError）不重试，直接返回 False。"""
    urlopen_mock = MagicMock(side_effect=ValueError("unexpected"))
    monkeypatch.setattr("urllib.request.urlopen", urlopen_mock)
    monkeypatch.setattr(client, "ping_healthchecks", MagicMock())

    ok = client.send_feishu({}, mode="test")
    assert ok is False
    assert urlopen_mock.call_count == 1  # 不重试


# ─── WEBHOOK 未设置 ───

def test_no_webhook_returns_false(monkeypatch):
    """WEBHOOK 为空 → 直接返回 False，不发起请求。"""
    monkeypatch.setattr(client, "WEBHOOK", "")
    urlopen_mock = MagicMock()
    monkeypatch.setattr("urllib.request.urlopen", urlopen_mock)
    ping_mock = MagicMock()
    monkeypatch.setattr(client, "ping_healthchecks", ping_mock)

    ok = client.send_feishu({}, mode="test")
    assert ok is False
    urlopen_mock.assert_not_called()
    ping_mock.assert_called_once_with(False, "test")


# ─── ping_healthchecks ───

def test_ping_healthchecks_no_url(monkeypatch):
    """HEALTHCHECKS_URL 为空 → 不发请求。"""
    monkeypatch.setattr(client, "HEALTHCHECKS_URL", "")
    urlopen_mock = MagicMock()
    monkeypatch.setattr("urllib.request.urlopen", urlopen_mock)
    client.ping_healthchecks(True, "test")
    urlopen_mock.assert_not_called()


def test_ping_healthchecks_success(monkeypatch):
    """成功 ping → urlopen 调用 URL（不带 /fail）。"""
    monkeypatch.setattr(client, "HEALTHCHECKS_URL", "https://hc.example.com/push-token")
    urlopen_mock = MagicMock()
    monkeypatch.setattr("urllib.request.urlopen", urlopen_mock)
    client.ping_healthchecks(True, "test")
    urlopen_mock.assert_called_once()
    call_args = urlopen_mock.call_args
    req = call_args[0][0]
    assert "fail" not in req.full_url
    assert "push-token" in req.full_url


def test_ping_healthchecks_failure(monkeypatch):
    """失败 ping → urllib 调用 URL + /fail。"""
    monkeypatch.setattr(client, "HEALTHCHECKS_URL", "https://hc.example.com/push-token/")
    urlopen_mock = MagicMock()
    monkeypatch.setattr("urllib.request.urlopen", urlopen_mock)
    client.ping_healthchecks(False, "test")
    urlopen_mock.assert_called_once()
    req = urlopen_mock.call_args[0][0]
    assert "/fail" in req.full_url


def test_ping_healthchecks_silent_on_error(monkeypatch):
    """ping 自身失败 → 静默，不抛异常。"""
    monkeypatch.setattr(client, "HEALTHCHECKS_URL", "https://hc.example.com/token")
    monkeypatch.setattr("urllib.request.urlopen",
                        MagicMock(side_effect=OSError("network down")))
    # 不应抛异常
    client.ping_healthchecks(True, "test")


# ─── payload 结构 ───

def test_payload_structure(monkeypatch):
    """验证发送的 payload 是 {msg_type, card} 结构。"""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["data"] = json.loads(req.data.decode("utf-8"))
        captured["headers"] = dict(req.header_items())
        return _make_urlopen_response({"code": 0})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(client, "ping_healthchecks", MagicMock())

    card = {"header": {"title": {"tag": "plain_text", "content": "test"}}}
    client.send_feishu(card, mode="test")

    assert captured["data"]["msg_type"] == "interactive"
    assert captured["data"]["card"] == card
    assert captured["headers"]["Content-type"] == "application/json"
