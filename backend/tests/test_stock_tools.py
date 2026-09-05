# -*- coding: utf-8 -*-
"""S154 T6.1 query_intraday_features 工具测试。

覆盖：
- A1 有数据 → 返 list，每行含 last_lock_time/broken_duration_min/note="辅助非 edge"
- A2 无数据 → 返 [] 不臆造
- A3 fresh env 表不存在（OperationalError）→ 返 [] 不抛
"""
from __future__ import annotations

import sqlite3

from ai.tools.stock_tools import query_intraday_features


class _FakeRow:
    """sqlite3.Row 替身（支持 ["col"] 索引 + keys()）。"""
    def __init__(self, d: dict):
        self._d = d

    def __getitem__(self, k):
        return self._d[k]

    def keys(self):
        return list(self._d.keys())


class _FakeConn:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def execute(self, q, params):
        class _R:
            def fetchall(_self):
                return [_FakeRow(r) for r in self._rows]
        return _R()

    def close(self):
        pass


def test_query_intraday_features_returns_data_with_note(monkeypatch):  # A1
    rows = [
        {"date": "2026-09-04", "last_lock_time": "09:35:00", "broken_duration_min": 0.0,
         "max_drop_pct": 0.0, "limit_price": 11.15, "data_status": "ok"},
        {"date": "2026-09-03", "last_lock_time": "10:15:00", "broken_duration_min": 5.0,
         "max_drop_pct": 1.2, "limit_price": 9.8, "data_status": "ok"},
    ]
    monkeypatch.setattr("risk.seal_intraday_collector._get_conn", lambda: _FakeConn(rows))
    out = query_intraday_features("002820", days=5)
    assert len(out) == 2
    assert out[0]["date"] == "2026-09-04"
    assert out[0]["last_lock_time"] == "09:35:00"
    assert out[0]["broken_duration_min"] == 0.0
    assert "辅助非 edge" in out[0]["note"]
    assert "0.7843" in out[0]["note"]  # §44 H2 verdict 数字


def test_query_intraday_features_empty_no_data(monkeypatch):  # A2
    monkeypatch.setattr("risk.seal_intraday_collector._get_conn", lambda: _FakeConn([]))
    out = query_intraday_features("000001", days=5)
    assert out == []  # 无预采集不臆造


def test_query_intraday_features_fresh_env_table_missing(monkeypatch):  # A3
    def _boom():
        raise sqlite3.OperationalError("no such table: seal_derived_features")
    monkeypatch.setattr("risk.seal_intraday_collector._get_conn", _boom)
    out = query_intraday_features("000001", days=5)
    assert out == []  # fresh env 表不存在不抛，返 []


def test_query_intraday_features_registered_in_registry():
    """R1：工具在 registry 注册（chat.TOOLS + MCP 自动获）。"""
    from ai.tools import registry
    assert "query_intraday_features" in registry.tool_names()
