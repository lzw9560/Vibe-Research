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

def test_ping_healthchecks_empty_url(monkeypatch):
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


# ─── _builtin_retry 降级路径（tenacity 不可用时）───

def test_builtin_retry_success():
    """_builtin_retry 首次成功不重试。"""
    from feishu.client import _builtin_retry
    calls = []
    @_builtin_retry(max_attempts=3, waits=(0.01, 0.01, 0.01))
    def fn():
        calls.append(True)
        return "ok"
    assert fn() == "ok"
    assert len(calls) == 1


def test_builtin_retry_retries_then_success(monkeypatch):
    """_builtin_retry 失败后重试成功。"""
    from feishu.client import _builtin_retry
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = []
    @_builtin_retry(max_attempts=3, waits=(0.01, 0.01, 0.01), exceptions=(ValueError,))
    def fn():
        calls.append(True)
        if len(calls) < 2:
            raise ValueError("retry me")
        return "ok"
    assert fn() == "ok"
    assert len(calls) == 2


def test_builtin_retry_exhausted(monkeypatch):
    """_builtin_retry 重试耗尽后 raise 最后异常。"""
    from feishu.client import _builtin_retry
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = []
    @_builtin_retry(max_attempts=3, waits=(0.01, 0.01, 0.01), exceptions=(ValueError,))
    def fn():
        calls.append(True)
        raise ValueError("always fail")
    with pytest.raises(ValueError, match="always fail"):
        fn()
    assert len(calls) == 3


def test_builtin_retry_non_matching_exception(monkeypatch):
    """_builtin_retry 不匹配的异常类型不重试，直接抛。"""
    from feishu.client import _builtin_retry
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = []
    @_builtin_retry(max_attempts=3, waits=(0.01, 0.01, 0.01), exceptions=(ValueError,))
    def fn():
        calls.append(True)
        raise TypeError("not retried")
    with pytest.raises(TypeError):
        fn()
    assert len(calls) == 1


def test_build_send_retry_fallback(monkeypatch):
    """tenacity 不可用时走 _builtin_retry 降级。"""
    import feishu.client as client_mod
    monkeypatch.setattr(client_mod, "_HAS_TENACITY", False)
    retry = client_mod._build_send_retry()
    assert callable(retry)


def test_ping_healthchecks_empty_url(monkeypatch):
    """HEALTHCHECKS_URL 为空时直接 return。"""
    monkeypatch.setattr("feishu.client.HEALTHCHECKS_URL", "")
    from feishu.client import ping_healthchecks
    ping_healthchecks(True, "test")
    ping_healthchecks(False, "test")


# ─── _load_env 边界 ───

def test_load_env_no_env_file(monkeypatch, tmp_path):
    """.env 不存在时 _load_env 直接 return。"""
    from pathlib import Path as _Path
    monkeypatch.setattr("feishu.client.Path", lambda *a: tmp_path / "nonexistent.env")
    from feishu.client import _load_env
    _load_env()  # 不应抛异常


# ─── _builtin_retry unreachable 路径 ───

def test_builtin_retry_unreachable(monkeypatch):
    """_builtin_retry max_attempts=0 时走 unreachable 路径。"""
    from feishu.client import _builtin_retry
    monkeypatch.setattr("time.sleep", lambda s: None)
    @_builtin_retry(max_attempts=0, waits=(0.01,), exceptions=(ValueError,))
    def fn():
        return "ok"
    # max_attempts=0 → for loop 不执行 → last_exc=None → raise RuntimeError
    with pytest.raises(RuntimeError, match="unreachable"):
        fn()


# ─── tenacity import 降级路径 ───

def test_tenacity_import_fail_falls_back(monkeypatch):
    """tenacity 不可用时走 _builtin_retry 降级。"""
    import builtins
    import importlib
    import feishu.client as client_mod
    # 清除 tenacity 缓存让 import 失败
    for mod in list(__import__("sys").modules.keys()):
        if "tenacity" in mod:
            monkeypatch.delitem(__import__("sys").modules, mod, raising=False)
    real_import = builtins.__import__
    def _fail_tenacity(name, *args, **kwargs):
        if "tenacity" in name:
            raise ImportError("mocked: tenacity unavailable")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", _fail_tenacity)
    # 重新 import client 模块让 L50-59 重新执行
    importlib.reload(client_mod)
    assert client_mod._HAS_TENACITY is False
    # 恢复
    importlib.reload(client_mod)
