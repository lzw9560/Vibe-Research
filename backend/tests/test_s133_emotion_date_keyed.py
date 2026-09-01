# -*- coding: utf-8 -*-
"""S133 — _emotion date-keyed 缓存重构测试。

契约（spec §5）：
- ① date-keyed 不污染：_emotion('08-20') 后 _emotion('08-21') 命中不同 key，em_zt 各调一次 date 不同。
- ② 同日去重：_emotion('08-28') 5min 内连调两次 → em_zt 只调一次（缓存命中）。
- ③ get_short_term_emotion() 经 emotion:latest key 缓存（date=None）。
- ④ 透明性：monkeypatch market._emotion 仍可 patch（签名未变，缓存壳不挡 patch）。
"""
from __future__ import annotations

import pytest

import astock
import market


@pytest.fixture(autouse=True)
def _clear_cache():
    market._CACHE.clear()
    yield
    market._CACHE.clear()


def _patch_emotion_deps(monkeypatch):
    """mock _emotion_uncached 的外部依赖（em_zt/ths/_sentiment/is_trading_day）。"""
    calls: list[tuple] = []

    def fake_em_zt(method, date, sort, *args, **kw):
        calls.append((method, date))
        if method == "getTopicZTPool":
            return [{"c": "000001", "n": "股A", "lbc": 2, "p": 10000,
                     "zdp": 1000, "amount": 100000, "ltsz": 1e9, "hybk": "银行"}]
        return []  # 炸板/跌停/昨涨停空

    monkeypatch.setattr(astock, "em_zt_topic_pool", fake_em_zt)
    monkeypatch.setattr(astock, "ths_limit_up_pool", lambda d: [])
    monkeypatch.setattr(market, "_sentiment", lambda d: {})  # 避免 akshare
    monkeypatch.setattr("vr_paths.is_trading_day", lambda d: True)  # P0-2 放行
    return calls


def test_date_keyed_no_cross_day_pollution(monkeypatch):
    """① _emotion('08-20') 后 _emotion('08-21') 命中不同 key，em_zt 主源各调一次 date 不同。"""
    calls = _patch_emotion_deps(monkeypatch)

    r1 = market._emotion("2026-08-20")
    r2 = market._emotion("2026-08-21")

    zt_calls = [c for c in calls if c[0] == "getTopicZTPool"]
    assert len(zt_calls) == 2  # 各调一次（不命中彼此缓存）
    assert "20260820" in [c[1] for c in zt_calls]
    assert "20260821" in [c[1] for c in zt_calls]
    # 返回 date 字段正确（不跨日返旧）
    assert r1["date"] == "2026-08-20"
    assert r2["date"] == "2026-08-21"
    # 缓存 key 独立
    assert "emotion:2026-08-20" in market._CACHE
    assert "emotion:2026-08-21" in market._CACHE


def test_same_day_dedup(monkeypatch):
    """② _emotion('08-28') 5min 内连调两次 → em_zt 只调一次（缓存命中）。"""
    calls = _patch_emotion_deps(monkeypatch)

    market._emotion("2026-08-28")
    n_after_first = len(calls)
    market._emotion("2026-08-28")  # 命中缓存
    n_after_second = len(calls)

    assert n_after_second == n_after_first  # 第二次 0 新调用
    assert "emotion:2026-08-28" in market._CACHE


def test_get_short_term_emotion_uses_latest_key(monkeypatch):
    """③ get_short_term_emotion() 经 emotion:latest key 缓存（date=None auto-locate）。"""
    calls = _patch_emotion_deps(monkeypatch)

    r = market.get_short_term_emotion()
    assert "emotion:latest" in market._CACHE
    assert isinstance(r, dict)

    n_after_first = len(calls)
    market.get_short_term_emotion()  # 命中缓存
    assert len(calls) == n_after_first


def test_transparency_monkeypatch_emotion(monkeypatch):
    """④ monkeypatch market._emotion 仍可 patch（签名未变，缓存壳不挡 patch）。"""
    monkeypatch.setattr(market, "_emotion", lambda d=None: {"patched": True, "d": d})
    assert market._emotion("2026-08-20") == {"patched": True, "d": "2026-08-20"}
    assert market._emotion() == {"patched": True, "d": None}
