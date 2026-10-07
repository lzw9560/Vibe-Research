# -*- coding: utf-8 -*-
"""test_tactics_signal_store —— 信号+对照组落库测试（S235 T12）。AAA 结构。"""
from __future__ import annotations
import pytest

from tactics.signal_store import SignalStore


@pytest.fixture
def store(tmp_path):
    # tmp_path 隔离 db（conftest 也会重定向 VR_DATA_DIR，这里显式更干净）
    return SignalStore(db_path=tmp_path / "tactics_signals.db")


# ---------------------------------------------------------------------------
# signal 写入 + 读取
# ---------------------------------------------------------------------------

def test_save_and_get_signal(store):
    # Arrange
    factors = {"gap_pct": 3.0, "vol_ratio": 4.5}
    raw = {"auction": {"thscode": "603778", "open_price": 10.5}}
    # Act
    sid = store.save_signal(
        tactic="reversal", code="603778", score=72, is_triggered=True,
        factors_json=factors, raw_data_json=raw, entry_price=10.5,
    )
    # Assert: 单条写入，但 min_n=60 → underpowered 返空
    assert sid > 0
    assert store.get_signals(tactic="reversal", min_n=60) == []


def test_get_signals_passes_min_n_threshold(store):
    # Arrange: 写 60 条 signal
    for i in range(60):
        store.save_signal(
            tactic="tail_breakout", code=f"{600000+i}", score=60 + i % 20,
            is_triggered=True, factors_json={"i": i}, raw_data_json={},
        )
    # Act
    got = store.get_signals(tactic="tail_breakout", min_n=60)
    # Assert
    assert len(got) == 60
    assert all(r["tactic_name"] == "tail_breakout" for r in got)


def test_get_signals_below_min_n_returns_empty(store):
    # 59 条 < 60 → 空
    for i in range(59):
        store.save_signal(
            tactic="reversal", code=f"{600000+i}", score=60,
            is_triggered=True, factors_json={}, raw_data_json={},
        )
    assert store.get_signals(tactic="reversal", min_n=60) == []


def test_get_signals_filters_by_tactic(store):
    # 写 reversal 60 条 + tail_breakout 5 条
    for i in range(60):
        store.save_signal(
            tactic="reversal", code=f"{600000+i}", score=60,
            is_triggered=True, factors_json={}, raw_data_json={},
        )
    for i in range(5):
        store.save_signal(
            tactic="tail_breakout", code=f"{700000+i}", score=60,
            is_triggered=True, factors_json={}, raw_data_json={},
        )
    got = store.get_signals(tactic="reversal", min_n=60)
    assert len(got) == 60
    assert all(r["tactic_name"] == "reversal" for r in got)


# ---------------------------------------------------------------------------
# 对照组写入 + 读取 + seed 可复现
# ---------------------------------------------------------------------------

def test_save_control_group_basic(store):
    # Arrange: 信号标的 + 一池同市值段标的
    signal_code = "603778"
    all_stocks = [{"thscode": signal_code, "float_mv": 1e9}] + [
        {"thscode": f"{60000+i}", "float_mv": 1e9} for i in range(20)
    ]
    # Act
    ids = store.save_control_group(
        signal_code=signal_code, all_stocks=all_stocks, n=5, seed=42,
        tactic="reversal", factors_json={}, raw_data_json={},
    )
    # Assert: 5 条 control 落库
    assert len(ids) == 5


def test_control_group_seed_reproducible(store, tmp_path):
    # Arrange
    signal_code = "603778"
    all_stocks = [{"thscode": signal_code, "float_mv": 1e9}] + [
        {"thscode": f"{60000+i}", "float_mv": 1e9} for i in range(20)
    ]
    # Act: 同 seed 两次选取
    ids1 = store.save_control_group(
        signal_code=signal_code, all_stocks=all_stocks, n=5, seed=42,
        tactic="reversal",
    )
    # 第二次用新 store 同 db 验证选取的可复现性（同 seed 选同 5 只）
    store2 = SignalStore(db_path=store.db_path)
    ids2 = store2.save_control_group(
        signal_code=signal_code, all_stocks=all_stocks, n=5, seed=42,
        tactic="reversal",
    )
    # Assert: 两次选的 code 集合相同（seed 可复现）
    def _codes(ids):
        import sqlite3
        with sqlite3.connect(store.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT code FROM signals WHERE id IN ({})".format(
                    ",".join("?" * len(ids))
                ), ids
            ).fetchall()
            return sorted(r["code"] for r in rows)
    assert _codes(ids1) == _codes(ids2)


def test_control_group_same_mc_bucket(store):
    # Arrange: 信号 1e9，池里 1 个同段(1.5e9) + 1 个异段(1e11)
    signal_code = "603778"
    all_stocks = [
        {"thscode": signal_code, "float_mv": 1e9},
        {"thscode": "600001", "float_mv": 1.5e9},  # 同段（0.5-2x）
        {"thscode": "600002", "float_mv": 1e11},  # 异段
    ]
    # Act: n=5 但同段池只有 1 只
    ids = store.save_control_group(
        signal_code=signal_code, all_stocks=all_stocks, n=5, seed=1,
        tactic="reversal",
    )
    # Assert: 只选到同段的 1 只（异段被桶过滤）
    assert len(ids) == 1


def test_control_group_get_by_date(store):
    # Arrange: 写 3 条 control
    signal_code = "603778"
    all_stocks = [{"thscode": signal_code, "float_mv": 1e9}] + [
        {"thscode": f"{60000+i}", "float_mv": 1e9} for i in range(20)
    ]
    store.save_control_group(
        signal_code=signal_code, all_stocks=all_stocks, n=3, seed=1,
        tactic="reversal",
    )
    # Act: 查今天的对照组
    from datetime import date
    today = date.today().isoformat()
    got = store.get_control_group(today, "reversal")
    # Assert
    assert len(got) == 3
    assert all(r["record_type"] == "control" for r in got)


def test_signal_id_monotonic(store):
    # Arrange/Act
    id1 = store.save_signal(tactic="reversal", code="600001", score=60,
                            is_triggered=True, factors_json={}, raw_data_json={})
    id2 = store.save_signal(tactic="reversal", code="600002", score=60,
                            is_triggered=True, factors_json={}, raw_data_json={})
    # Assert
    assert id2 > id1
