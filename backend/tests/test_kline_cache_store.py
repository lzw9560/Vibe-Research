# -*- coding: utf-8 -*-
"""kline_cache_store 单元测试（SQLite per-code 查，替代全量 JSON load 2.19GB 常驻）。

验证：
- get_bars per-code 查（存在/不存在/损坏）
- upsert_bars 增量更新（INSERT OR REPLACE 覆盖）
- upsert_many 批量写
- get_all_codes 全量 code 列表
- load_all 全量读（offline 兼容）
- invalidate 清 connection

测试隔离：conftest.py VR_DATA_DIR → tmp_path，SQLite 在 tmp_path。
"""
from __future__ import annotations

from engine import kline_cache_store


import pytest


@pytest.fixture(autouse=True)
def _isolate_vr_data_dir(monkeypatch, tmp_path):
    """每测试独立 VR_DATA_DIR（tmp_path）+ 清 conn，防生产 SQLite 污染 + 跨测串扰。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    kline_cache_store.invalidate()
    yield
    kline_cache_store.invalidate()


def test_get_bars_missing_code_returns_empty() -> None:
    """code 不存在返 []（不臆造）。"""
    assert kline_cache_store.get_bars("999999") == []


def test_upsert_then_get_bars() -> None:
    """upsert 后 get_bars 返写入 bars。"""
    bars = [{"date": "2026-01-01", "open": 10.0, "close": 10.5}]
    kline_cache_store.upsert_bars("000001", bars)
    got = kline_cache_store.get_bars("000001")
    assert got == bars


def test_upsert_overwrites() -> None:
    """INSERT OR REPLACE：同 code 二次 upsert 覆盖。"""
    kline_cache_store.upsert_bars("000002", [{"date": "2026-01-01", "close": 10}])
    kline_cache_store.upsert_bars("000002", [{"date": "2026-01-02", "close": 11}])
    got = kline_cache_store.get_bars("000002")
    assert len(got) == 1
    assert got[0]["date"] == "2026-01-02"


def test_get_all_codes() -> None:
    """get_all_codes 返所有 code。"""
    kline_cache_store.upsert_bars("000003", [{"date": "2026-01-01", "close": 10}])
    kline_cache_store.upsert_bars("000001", [{"date": "2026-01-01", "close": 10}])
    codes = kline_cache_store.get_all_codes()
    assert "000001" in codes
    assert "000003" in codes


def test_load_all() -> None:
    """load_all 返全量 dict（offline 兼容）。"""
    kline_cache_store.upsert_bars("000004", [{"date": "2026-01-01", "close": 10}])
    all_data = kline_cache_store.load_all()
    assert "000004" in all_data
    assert all_data["000004"][0]["close"] == 10


def test_invalidate_clears_conn() -> None:
    """invalidate 后 connection 清空，重新查仍可读（重建 conn）。"""
    kline_cache_store.upsert_bars("000005", [{"date": "2026-01-01", "close": 10}])
    kline_cache_store.invalidate()
    assert kline_cache_store._conn is None
    assert kline_cache_store.get_bars("000005")[0]["close"] == 10


def test_upsert_many_batch() -> None:
    """upsert_many 批量写。"""
    items = [
        ("000006", [{"date": "2026-01-01", "close": 10}]),
        ("000007", [{"date": "2026-01-01", "close": 11}]),
    ]
    n = kline_cache_store.upsert_many(items)
    assert n == 2
    assert kline_cache_store.get_bars("000006")[0]["close"] == 10
    assert kline_cache_store.get_bars("000007")[0]["close"] == 11


def test_get_bars_after_invalidate_reads_fresh() -> None:
    """invalidate 后 get_bars 读最新 upsert 数据（WAL + 重建 conn）。"""
    kline_cache_store.upsert_bars("000008", [{"date": "2026-01-01", "close": 10}])
    kline_cache_store.invalidate()
    kline_cache_store.upsert_bars("000008", [{"date": "2026-01-02", "close": 20}])
    got = kline_cache_store.get_bars("000008")
    assert got[0]["date"] == "2026-01-02"
