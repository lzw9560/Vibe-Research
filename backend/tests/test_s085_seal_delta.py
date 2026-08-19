# -*- coding: utf-8 -*-
"""S085 B3 — seal_delta 透传单测。

bug：IndicatorSet 无 seal_delta 字段；intraday_features 表有 seal_delta 列（migration
20260818-002:13，persist_trajectory 写，compute_trajectory 算）但**无 reader**（只写不读孤儿）。
修复：(1) IndicatorSet 加 seal_delta 字段；(2) collector 加 get_trajectory_result 读表；
(3) derived_source.fetch_derived 调 reader，seal_delta 塞 derived dict；(4) funnel mutate ind.seal_delta。

承重：seal_delta 当前不进 capped/胜率/结算（无消费方 → dead field，像 A7，review LOW）。
价值 = 为未来消费方预留（补真缺口：seal_delta 从只写变可读+透传）。
"""
from __future__ import annotations

from candidate_funnel.sources import derived_source
from risk import seal_intraday_collector as col


class _FakeRow:
    def __init__(self, d): self._d = d
    def __getitem__(self, k): return self._d.get(k)
    def keys(self): return self._d.keys()


class _FakeConn:
    def __init__(self, row): self._row = row
    def execute(self, q, params=()): return type("R", (), {"fetchone": lambda s: self._row})()
    def close(self): pass


def test_get_trajectory_result_reads_seal_delta(monkeypatch):
    """get_trajectory_result 读 intraday_features 表返 seal_delta（修只写不读孤儿）。"""
    monkeypatch.setattr(col, "_get_conn", lambda: _FakeConn(_FakeRow({"seal_delta": 1.5, "data_status": "ok"})))
    r = col.get_trajectory_result("600519", "2026-08-18")
    assert r is not None
    assert r["seal_delta"] == 1.5


def test_get_trajectory_result_none_when_no_row(monkeypatch):
    """无行（未预采集）→ None（不臆造）。"""
    monkeypatch.setattr(col, "_get_conn", lambda: _FakeConn(None))
    assert col.get_trajectory_result("600519", "2026-08-18") is None


def test_get_trajectory_result_none_on_db_error(monkeypatch):
    """DB 未就绪/fresh env 未迁移（OperationalError）→ None（不抛，不臆造）。"""
    import sqlite3
    class _ErrConn:
        def execute(self, q, params=()): raise sqlite3.OperationalError("no such table")
        def close(self): pass
    monkeypatch.setattr(col, "_get_conn", lambda: _ErrConn())
    assert col.get_trajectory_result("600519", "2026-08-18") is None


def test_fetch_derived_includes_seal_delta(monkeypatch):
    """fetch_derived 把 seal_delta 塞进 derived dict（透传到 card.derived）。"""
    monkeypatch.setattr(col, "get_derived_result",
                        lambda code, date: {"last_lock_time": "0930", "broken_duration_min": 0,
                                            "max_drop_pct": 0.0, "limit_price": 10.0,
                                            "granularity_note": "60s", "data_status": "ok"})
    monkeypatch.setattr(col, "get_trajectory_result",
                        lambda code, date: {"seal_delta": 2.3, "data_status": "ok"})
    derived = derived_source.fetch_derived("600519", "2026-08-18")
    assert derived is not None
    assert derived["seal_delta"] == 2.3
    # 原 R7 字段不丢
    assert derived["last_lock_time"] == "0930"


def test_fetch_derived_seal_delta_none_when_trajectory_missing(monkeypatch):
    """trajectory 未预采集（get_trajectory_result None）→ derived 无 seal_delta 键或 None（不臆造）。"""
    monkeypatch.setattr(col, "get_derived_result",
                        lambda code, date: {"last_lock_time": "0930", "broken_duration_min": 0,
                                            "max_drop_pct": 0.0, "limit_price": 10.0,
                                            "granularity_note": "60s", "data_status": "ok"})
    monkeypatch.setattr(col, "get_trajectory_result", lambda code, date: None)
    derived = derived_source.fetch_derived("600519", "2026-08-18")
    assert derived is not None
    assert derived.get("seal_delta") is None


def test_indicatorset_has_seal_delta_field():
    """IndicatorSet 加 seal_delta 字段（默认 None，向后兼容）。"""
    from candidate_funnel.models import IndicatorSet
    assert "seal_delta" in IndicatorSet.model_fields
    ind = IndicatorSet(code="600519", name="X")
    assert ind.seal_delta is None
