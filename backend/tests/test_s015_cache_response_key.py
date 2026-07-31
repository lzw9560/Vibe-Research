# -*- coding: utf-8 -*-
"""S015 R5 —— cache_response 缓存键修复回归（离线）。

旧键 ``f"{func.__name__}:{...kwargs...}"`` 未含 args，不同 code 在位置
调用路径下会撞缓存；新键以 args + kwargs（或 Request.path + query）稳定
序列化后取 md5，保证不同 code/date → 不同键。
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    app_module._RESPONSE_CACHE.clear()
    yield
    app_module._RESPONSE_CACHE.clear()


def test_cache_key_differs_by_kwarg_code():
    """不同 code（kwargs）应产生不同缓存键。"""
    captured = []

    def _make(func):
        @app_module.cache_response(ttl=300)
        async def endpoint(code: str, date: str | None = None):
            captured.append(code)
            return {"code": code}
        return endpoint

    ep = _make(lambda code: None)

    r1 = asyncio.run(ep(code="000001"))
    r2 = asyncio.run(ep(code="000002"))
    assert r1 == {"code": "000001"}
    assert r2 == {"code": "000002"}
    # 两个不同 code 应缓存到两个不同键
    assert len(app_module._RESPONSE_CACHE) == 2


def test_cache_key_differs_by_positional_code():
    """旧键忽略 args：位置调用不同 code 会撞键；新键应区分。"""
    calls = []

    @app_module.cache_response(ttl=300)
    async def endpoint(code: str):
        calls.append(code)
        return {"code": code}

    asyncio.run(endpoint("600000"))
    asyncio.run(endpoint("000001"))
    assert len(app_module._RESPONSE_CACHE) == 2, "位置参数不同 code 应生成不同键"
    assert calls == ["600000", "000001"]


def test_cache_hit_within_ttl():
    """同参数第二次应命中缓存，不再次调用底层函数。"""
    invocations = []

    @app_module.cache_response(ttl=300)
    async def endpoint(code: str):
        invocations.append(code)
        return {"v": code}

    asyncio.run(endpoint(code="000001"))
    asyncio.run(endpoint(code="000001"))
    assert invocations == ["000001"]  # 第二次命中缓存


def test_cache_key_stable_for_same_params():
    """相同参数多次调用只产生一个键。"""
    @app_module.cache_response(ttl=300)
    async def endpoint(code: str, date: str | None = None):
        return {"code": code, "date": date}

    asyncio.run(endpoint(code="000001", date="2026-07-31"))
    asyncio.run(endpoint(code="000001", date="2026-07-31"))
    assert len(app_module._RESPONSE_CACHE) == 1


def test_cache_key_helper_directly():
    """直接验证 _cache_key 对 args/kwargs 的区分。"""
    async def fn(code, date=None):
        return None

    k1 = app_module._cache_key(fn, (), {"code": "000001", "date": None})
    k2 = app_module._cache_key(fn, (), {"code": "000002", "date": None})
    k3 = app_module._cache_key(fn, (), {"code": "000001", "date": "2026-07-31"})
    assert k1 != k2
    assert k1 != k3
    # 相同输入 → 相同键（稳定）
    assert k1 == app_module._cache_key(fn, (), {"code": "000001", "date": None})
