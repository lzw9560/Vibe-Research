# -*- coding: utf-8 -*-
"""TDD tests for S168 _s44_wire.wire_verdict (AAA pattern). RED -> GREEN."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from tools import _s44_wire


@dataclass(frozen=True)
class _FakeVerdict:
    status: str = "underpowered"
    edge_type: str = "selection"
    selection_lift: Optional[float] = 0.5
    n: int = 100
    days_robust: int = 30
    note: str = "underpowered: days_robust=30<60 (R6 gate)"


def test_wire_verdict_calls_verify_and_persists(monkeypatch, tmp_path):
    """wire_verdict 调 verify → _verdict_to_dict → Recorder.save → lineage.record,
    返 Verdict。mock 各组件，断言调用参数正确。"""
    # Arrange——mock verify 返固定 Verdict
    captured = {"verify": None, "recorder_save": None, "lineage": None}

    def _fake_verify(**kwargs):
        captured["verify"] = kwargs
        return _FakeVerdict()

    class _FakeRecorder:
        def save(self, **kwargs):
            captured["recorder_save"] = kwargs
            return "rec_2026_test"

    def _fake_lineage_record(**kwargs):
        captured["lineage"] = kwargs

    monkeypatch.setattr(_s44_wire, "verify", _fake_verify)
    monkeypatch.setattr(_s44_wire, "Recorder", _FakeRecorder)
    monkeypatch.setattr(_s44_wire, "lineage_record", _fake_lineage_record)

    # Act
    v = _s44_wire.wire_verdict(
        line_id="test_line",
        returns=[0.01, -0.02, 0.03, 0.005, -0.01],
        edge_type="selection",
        frozen_commit="abc1234",
        dates=["d1", "d2", "d3", "d4", "d5"],
        survivors_by_day={"d1": [0.01], "d2": [-0.02]},
        universe_by_day={"d1": [0.01, -0.02], "d2": [-0.02, 0.03]},
        n_comparisons=1,
        round_trip_cost=0.70,
        script="tools/test_lift.py",
        params={"arm": "test"},
    )

    # Assert——verify 调用参数正确
    assert captured["verify"]["edge_type"] == "selection"
    assert captured["verify"]["n_trials"] == 1
    assert captured["verify"]["frozen_commit"] == "abc1234"
    assert captured["verify"]["round_trip_cost"] == 0.70
    # data_snapshot_id (R7) = frozen[:8]:line_id:sha256(returns)[:12]
    assert captured["verify"]["data_snapshot_id"].startswith("abc1234:test_line:")

    # Recorder.save 落 return_series + verdict dict + data_snapshot_id
    assert captured["recorder_save"]["return_series"] == [0.01, -0.02, 0.03, 0.005, -0.01]
    assert captured["recorder_save"]["frozen_commit"] == "abc1234"
    assert captured["recorder_save"]["data_snapshot_id"] == captured["verify"]["data_snapshot_id"]
    assert captured["recorder_save"]["verdict"]["status"] == "underpowered"  # _verdict_to_dict 转 dict

    # lineage.record 调用
    assert captured["lineage"]["artifact_id"] == "verifier:test_line"
    assert captured["lineage"]["commit"] == "abc1234"

    # 返 Verdict（调用方可读 status/note）
    assert v.status == "underpowered"
    assert "underpowered" in v.note


def test_wire_verdict_lineage_failure_non_fatal(monkeypatch):
    """lineage sidecar——record 抛异常不阻塞 verdict（validate_or_reject 同模式）。"""
    monkeypatch.setattr(_s44_wire, "verify", lambda **kw: _FakeVerdict())

    class _FakeRecorder:
        def save(self, **kw):
            return "rec_test"

    def _failing_lineage(**kw):
        raise RuntimeError("lineage disk full")

    monkeypatch.setattr(_s44_wire, "Recorder", _FakeRecorder)
    monkeypatch.setattr(_s44_wire, "lineage_record", _failing_lineage)

    # Act——不 raise（sidecar 吞异常）
    v = _s44_wire.wire_verdict(
        line_id="test_lineage_fail",
        returns=[0.01, 0.02],
        edge_type="event",
        frozen_commit="deadbee",
    )
    # Assert——verdict 仍返（lineage 失败不阻塞）
    assert v.status == "underpowered"


def test_verdict_to_dict_converts_numpy_scalars():
    """_verdict_to_dict 把 numpy scalars 转 native Python（json-serializable）。"""
    import json
    import numpy as np

    @dataclass(frozen=True)
    class _V:
        val: object = np.float64(0.5)
        n: object = np.int64(100)

    d = _s44_wire._verdict_to_dict(_V())
    # json.dumps 不报（numpy → native）
    s = json.dumps(d)
    assert json.loads(s)["val"] == 0.5
    assert json.loads(s)["n"] == 100
