# -*- coding: utf-8 -*-
"""S203 wiring(a) phase 2 test: _build_limitup_msc 接 bars（baostock cache）+ lbc（涨停池 raw）。

验证：
- _build_limitup_msc 从 baostock cache 取该 code 最近 2 bars（T-1+T）填 msc.bars
- _build_limitup_msc 透传 lbc 参数填 msc.lbc
- phase 1 键（seal/zt_count_today/high_gene/sector_rank）不被破坏（首板涨停 no regression）
- _get_lbc_for_code 从涨停池 raw ZTPoolItem.boards 取 lbc（per-date 缓存复用）
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import limitup_strategy as lstrat
from limitup_strategy import _build_limitup_msc, _get_lbc_for_code, _get_recent_bars


def _gene(code="000001", industry="", high_gene=False, seal_to_float_ratio=0.0):
    return SimpleNamespace(
        code=code, industry=industry, high_gene=high_gene,
        seal_to_float_ratio=seal_to_float_ratio,
    )


def _bar(date, close, volume, open_=None):
    o = open_ if open_ is not None else close
    return {"date": date, "open": o, "high": close, "low": o, "close": close, "volume": volume, "amount": 0}


# ---------------------------------------------------------------------------
# _get_recent_bars: baostock cache module-level（加载一次，per-code 查）
# ---------------------------------------------------------------------------

def test_get_recent_bars_last_two(monkeypatch):
    """cache 有 3 bars → 返尾部 2 bars（T-1+T，date asc）。"""
    import engine.bars_provider as bp
    bars = [_bar("2026-09-10", 9.0, 100), _bar("2026-09-11", 9.5, 120), _bar("2026-09-12", 10.0, 150)]
    monkeypatch.setattr(bp, "_load_cache", lambda: {"000001": bars})
    got = _get_recent_bars("000001")
    assert got == bars[-2:]


def test_get_recent_bars_two_exactly(monkeypatch):
    """cache 恰 2 bars → 返全部 2 bars。"""
    import engine.bars_provider as bp
    bars = [_bar("2026-09-11", 9.5, 120), _bar("2026-09-12", 10.0, 150)]
    monkeypatch.setattr(bp, "_load_cache", lambda: {"000001": bars})
    got = _get_recent_bars("000001")
    assert got == bars


def test_get_recent_bars_code_missing(monkeypatch):
    """cache 无该 code → None（诚实降级，不臆造）。"""
    import engine.bars_provider as bp
    monkeypatch.setattr(bp, "_load_cache", lambda: {"999999": []})
    assert _get_recent_bars("000001") is None


def test_get_recent_bars_insufficient(monkeypatch):
    """cache 仅 1 bar → None（不足 2 bars 无法算量比/吞没）。"""
    import engine.bars_provider as bp
    monkeypatch.setattr(bp, "_load_cache", lambda: {"000001": [_bar("2026-09-12", 10.0, 150)]})
    assert _get_recent_bars("000001") is None


def test_get_recent_bars_empty(monkeypatch):
    """cache 该 code 为空 list → None。"""
    import engine.bars_provider as bp
    monkeypatch.setattr(bp, "_load_cache", lambda: {"000001": []})
    assert _get_recent_bars("000001") is None


def test_get_recent_bars_load_failure(monkeypatch):
    """_load_cache 异常 → None（不崩，降级）。"""
    import engine.bars_provider as bp

    def _boom():
        raise RuntimeError("disk gone")
    monkeypatch.setattr(bp, "_load_cache", _boom)
    assert _get_recent_bars("000001") is None


# ---------------------------------------------------------------------------
# _build_limitup_msc: bars + lbc + phase1 不破
# ---------------------------------------------------------------------------

def test_build_msc_includes_bars(monkeypatch):
    """msc.bars = baostock cache 尾部 2 bars。"""
    import engine.bars_provider as bp
    bars = [_bar("2026-09-11", 9.5, 120), _bar("2026-09-12", 10.0, 150)]
    monkeypatch.setattr(bp, "_load_cache", lambda: {"000001": bars})
    msc = _build_limitup_msc(_gene("000001"), "2026-09-14", lbc=2)
    assert msc["bars"] == bars


def test_build_msc_includes_lbc(monkeypatch):
    """msc.lbc 透传 lbc 参数。"""
    import engine.bars_provider as bp
    monkeypatch.setattr(bp, "_load_cache", lambda: {})
    msc = _build_limitup_msc(_gene("000001"), "2026-09-14", lbc=3)
    assert msc["lbc"] == 3


def test_build_msc_lbc_default_none(monkeypatch):
    """未传 lbc → msc.lbc=None（诚实，不臆造 0）。"""
    import engine.bars_provider as bp
    monkeypatch.setattr(bp, "_load_cache", lambda: {})
    msc = _build_limitup_msc(_gene("000001"), "2026-09-14")
    assert msc["lbc"] is None


def test_build_msc_bars_none_when_missing(monkeypatch):
    """cache 无该 code → msc.bars=None（反包/接力 C2 data_unavailable 降级）。"""
    import engine.bars_provider as bp
    monkeypatch.setattr(bp, "_load_cache", lambda: {})
    msc = _build_limitup_msc(_gene("000001"), "2026-09-14", lbc=2)
    assert msc["bars"] is None
    assert msc["lbc"] == 2  # lbc 仍有（独立来源）


def test_build_msc_preserves_phase1_keys(monkeypatch):
    """phase 2 不破 phase 1：seal/zt_count_today/high_gene/sector_rank 仍在。"""
    import engine.bars_provider as bp
    monkeypatch.setattr(bp, "_load_cache", lambda: {})
    msc = _build_limitup_msc(
        _gene("000001", industry="电子", high_gene=True, seal_to_float_ratio=0.006),
        "2026-09-14", lbc=2,
    )
    assert msc["seal_to_float_ratio"] == 0.006
    assert msc["high_gene"] is True
    assert msc["sector_rank"] is None
    assert "zt_count_today" in msc  # gene_scores.db 查（测试环境 db 可能空→0，键在即可）


def test_build_msc_keys_complete(monkeypatch):
    """msc 含 phase1 + phase2 全键。"""
    import engine.bars_provider as bp
    monkeypatch.setattr(bp, "_load_cache", lambda: {})
    msc = _build_limitup_msc(_gene("000001"), "2026-09-14", lbc=2)
    for k in ("seal_to_float_ratio", "zt_count_today", "high_gene", "sector_rank", "bars", "lbc"):
        assert k in msc, f"missing key {k}"


# ---------------------------------------------------------------------------
# _get_lbc_for_code: 涨停池 raw lbc + per-date 缓存
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_lbc_cache():
    """每测清 _LBC_CACHE，隔离缓存行为。"""
    lstrat._LBC_CACHE.clear()
    yield
    lstrat._LBC_CACHE.clear()


def test_get_lbc_for_code_from_pool(monkeypatch):
    """涨停池 raw ZTPoolItem.boards → lbc。"""
    calls = []

    async def fake_fetch(date):
        calls.append(date)
        return ([SimpleNamespace(code="000001", boards=2)], [], [])

    monkeypatch.setattr("limitup_screener.public_fetch_zt_pool", fake_fetch)
    lbc = asyncio.run(_get_lbc_for_code("000001", "2026-09-14"))
    assert lbc == 2
    assert calls == ["20260914"]  # YYYY-MM-DD → YYYYMMDD


def test_get_lbc_for_code_not_in_pool(monkeypatch):
    """code 不在涨停池 → None（诚实降级）。"""
    async def fake_fetch(date):
        return ([SimpleNamespace(code="999999", boards=3)], [], [])
    monkeypatch.setattr("limitup_screener.public_fetch_zt_pool", fake_fetch)
    assert asyncio.run(_get_lbc_for_code("000001", "2026-09-14")) is None


def test_get_lbc_for_code_boards_none_defaults_zero(monkeypatch):
    """ZTPoolItem.boards=None → lbc=0（or 0 兜底）。"""
    async def fake_fetch(date):
        return ([SimpleNamespace(code="000001", boards=None)], [], [])
    monkeypatch.setattr("limitup_screener.public_fetch_zt_pool", fake_fetch)
    assert asyncio.run(_get_lbc_for_code("000001", "2026-09-14")) == 0


def test_get_lbc_for_code_cached(monkeypatch):
    """per-date 缓存：同 date 2 次调用只拉 1 次。"""
    calls = []

    async def fake_fetch(date):
        calls.append(date)
        return ([SimpleNamespace(code="000001", boards=2)], [], [])

    monkeypatch.setattr("limitup_screener.public_fetch_zt_pool", fake_fetch)
    asyncio.run(_get_lbc_for_code("000001", "2026-09-14"))
    asyncio.run(_get_lbc_for_code("000002", "2026-09-14"))  # 同 date 复用缓存
    assert len(calls) == 1


def test_get_lbc_for_code_fetch_failure(monkeypatch):
    """public_fetch_zt_pool 抛异常 → lbc=None（不崩，降级）。"""
    async def fake_fetch(date):
        raise RuntimeError("network gone")
    monkeypatch.setattr("limitup_screener.public_fetch_zt_pool", fake_fetch)
    assert asyncio.run(_get_lbc_for_code("000001", "2026-09-14")) is None
