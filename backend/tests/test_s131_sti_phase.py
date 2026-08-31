# -*- coding: utf-8 -*-
"""S131 R2.3：get_current_sti_phase 返 (phase, status) + _merge_data_status 含 sti。

锁住（spec §3 R2.3）：
- ①except → (None, "missing") + warning；
- ②成功 → (phase, "ok")；
- ③merge 含 sti → sti missing 时 data_status=missing。

对齐 S129 trio test 范式（monkeypatch + asyncio.run + AAA），mock
limitup_sti.get_sti_engine 返假 engine/_get_db，不依赖 live DB。
"""
import asyncio
import logging
import types

import risk_models


# ── R2.3 ①：except → (None, "missing") + warning ─────────────────────────

def test_r2_sti_phase_exception_returns_missing_with_warning(monkeypatch, caplog):
    # Arrange：limitup_sti.get_sti_engine 抛 RuntimeError（模拟 DB/源断）
    import limitup_sti
    def _boom():
        raise RuntimeError("sti DB offline")
    monkeypatch.setattr(limitup_sti, "get_sti_engine", _boom)
    # Act
    phase, status = asyncio.run(risk_models.get_current_sti_phase())
    # Assert
    assert phase is None
    assert status == "missing"
    # warning 被记（risk_models logger）
    assert any(
        "get_current_sti_phase" in r.message and "missing" in r.message
        for r in caplog.records
    )


# ── R2.3 ②：成功 → (phase, "ok") ────────────────────────────────────────

def test_r2_sti_phase_success_returns_phase_ok(monkeypatch):
    # Arrange：假 engine → 假 db → fetchone 返 {"phase": "EXPANSION"}
    import limitup_sti
    fake_row = {"phase": "EXPANSION"}
    fake_db = types.SimpleNamespace(
        execute=lambda sql: types.SimpleNamespace(fetchone=lambda: fake_row)
    )
    fake_engine = types.SimpleNamespace(_get_db=lambda: fake_db)
    monkeypatch.setattr(limitup_sti, "get_sti_engine", lambda: fake_engine)
    # Act
    phase, status = asyncio.run(risk_models.get_current_sti_phase())
    # Assert
    assert phase == "EXPANSION"
    assert status == "ok"


def test_r2_sti_phase_success_no_row_returns_none_ok(monkeypatch):
    # Arrange：查询成功但无 row（合法空=未初始化）
    import limitup_sti
    fake_db = types.SimpleNamespace(
        execute=lambda sql: types.SimpleNamespace(fetchone=lambda: None)
    )
    fake_engine = types.SimpleNamespace(_get_db=lambda: fake_db)
    monkeypatch.setattr(limitup_sti, "get_sti_engine", lambda: fake_engine)
    # Act
    phase, status = asyncio.run(risk_models.get_current_sti_phase())
    # Assert：合法空 → (None, "ok")（非 missing，查询未失败）
    assert phase is None
    assert status == "ok"


# ── R2.3 ③：merge 含 sti → sti missing 时 data_status=missing ───────────

def test_r2_merge_data_status_sti_missing_raises_composite():
    # Arrange：8 态全 ok，仅 sti missing
    # Act
    status = risk_models._merge_data_status(
        "ok", "ok", "ok", "ok", "ok",
        "ok", "ok", "ok", "missing"  # 9th = sti_status
    )
    # Assert：sti missing 抬 data_status=missing
    assert status == "missing"


def test_r2_merge_data_status_sti_ok_all_ok():
    # Arrange：9 态全 ok（含 sti）
    # Act
    status = risk_models._merge_data_status(
        "ok", "ok", "ok", "ok", "ok",
        "ok", "ok", "ok", "ok"
    )
    # Assert
    assert status == "ok"


def test_r2_merge_data_status_sti_degraded_raises_composite():
    # Arrange：8 态全 ok，仅 sti degraded
    # Act
    status = risk_models._merge_data_status(
        "ok", "ok", "ok", "ok", "ok",
        "ok", "ok", "ok", "degraded"
    )
    # Assert：sti degraded 抬 data_status=degraded
    assert status == "degraded"
