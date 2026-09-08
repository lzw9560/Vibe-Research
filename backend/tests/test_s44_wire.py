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


# ── S171 R3: 月度参数透传（step/walk_train/walk_test/window_sanity）──────────


def test_wire_verdict_passes_step_and_walk_params_to_verify(monkeypatch):
    """S171 R3: wire_verdict 透传 step/walk_train/walk_test/window_sanity 给 verify。

    月度 harness 必传——verify 默认 step=20（日步长）+ walk_train=100/walk_test=20
    是日频默认，月度数据用默认→walk_forward OOS 失效（60 月仅 0 窗口）。
    S171 月度须传 step=12/walk_train=36/walk_test=12。
    """
    captured = {"verify": None}

    def _fake_verify(**kwargs):
        captured["verify"] = kwargs
        return _FakeVerdict()

    monkeypatch.setattr(_s44_wire, "verify", _fake_verify)
    monkeypatch.setattr(_s44_wire, "Recorder", type("R", (), {"save": lambda self, **k: "rec"}))
    monkeypatch.setattr(_s44_wire, "lineage_record", lambda **kw: None)

    # Act——传月度参数
    _s44_wire.wire_verdict(
        line_id="monthly_line",
        returns=[0.01] * 5,
        edge_type="selection",
        frozen_commit="abc1234",
        survivors_by_day={"d1": [0.01]},
        universe_by_day={"d1": [0.01, 0.02]},
        window_sanity={"path": {"mean": 0.01, "winrate": 0.6, "base_rate": 0.5}},
        walk_train=36,
        walk_test=12,
        step=12,
    )
    # Assert——4 个月度参数都透传给 verify
    assert captured["verify"]["step"] == 12
    assert captured["verify"]["walk_train"] == 36
    assert captured["verify"]["walk_test"] == 12
    assert captured["verify"]["window_sanity"]["path"]["mean"] == 0.01


def test_wire_verdict_omits_new_params_when_none_for_backward_compat(monkeypatch):
    """S171 R3 向后兼容：14 个旧 harness 不传新参数→wire_verdict 不透传给
    verify→verify 用自身日频默认（walk_train=100/walk_test=20/step=20）。

    关键：wire_verdict 条件透传（None 不传），非 None-override——否则 verify
    的 int 默认被 None 覆盖致 walk_forward_oos(surv,univ,None,None) 崩。
    """
    captured = {"verify": None}

    def _fake_verify(**kwargs):
        captured["verify"] = kwargs
        return _FakeVerdict()

    monkeypatch.setattr(_s44_wire, "verify", _fake_verify)
    monkeypatch.setattr(_s44_wire, "Recorder", type("R", (), {"save": lambda self, **k: "rec"}))
    monkeypatch.setattr(_s44_wire, "lineage_record", lambda **kw: None)

    # Act——旧 harness 风格，不传新参数
    _s44_wire.wire_verdict(
        line_id="legacy_line",
        returns=[0.01] * 5,
        edge_type="selection",
        frozen_commit="abc1234",
    )
    # Assert——新参数未传给 verify（verify 用自身默认，非 None-override）
    assert "step" not in captured["verify"]
    assert "walk_train" not in captured["verify"]
    assert "walk_test" not in captured["verify"]
    assert "window_sanity" not in captured["verify"]


def test_wire_verdict_stores_methodology_params_for_reproduce(monkeypatch):
    """S171 R3 reproduce：wire_verdict 存 step/walk_*/window_sanity 到 recorder
    params，reproduce_verdict 用 inspect.signature(verify) 白名单重建 verify_kwargs
    时才能 re-pass——否则 reproduce 用默认 step=20 ≠ 原录 step=12 verdict→mismatch。

    criterion a（verdict-reproducibility）：同 params + 同 series → 同 Verdict。
    """
    captured = {"verify": None, "recorder_save": None}

    def _fake_verify(**kwargs):
        captured["verify"] = kwargs
        return _FakeVerdict()

    monkeypatch.setattr(_s44_wire, "verify", _fake_verify)
    monkeypatch.setattr(_s44_wire, "Recorder", type("R", (), {"save": lambda self, **k: captured.__setitem__("recorder_save", k) or "rec"}))
    monkeypatch.setattr(_s44_wire, "lineage_record", lambda **kw: None)

    _s44_wire.wire_verdict(
        line_id="monthly_repro",
        returns=[0.01] * 5,
        edge_type="selection",
        frozen_commit="abc1234",
        survivors_by_day={"d1": [0.01]},
        universe_by_day={"d1": [0.01, 0.02]},
        walk_train=36,
        walk_test=12,
        step=12,
        window_sanity={"path": {"mean": 0.01, "winrate": 0.6, "base_rate": 0.5}},
    )
    # Assert——方法论参数存入 recorder params（reproduce_verdict 能读到）
    stored = captured["recorder_save"]["params"]
    assert stored["step"] == 12
    assert stored["walk_train"] == 36
    assert stored["walk_test"] == 12
    assert stored["window_sanity"]["path"]["mean"] == 0.01


def test_wire_verdict_legacy_no_methodology_params_in_recorder(monkeypatch):
    """S171 R3 向后兼容：旧 harness 不传→recorder params 不含新键（保旧记录干净）。"""
    captured = {"recorder_save": None}
    monkeypatch.setattr(_s44_wire, "verify", lambda **kw: _FakeVerdict())
    monkeypatch.setattr(_s44_wire, "Recorder", type("R", (), {"save": lambda self, **k: captured.__setitem__("recorder_save", k) or "rec"}))
    monkeypatch.setattr(_s44_wire, "lineage_record", lambda **kw: None)

    _s44_wire.wire_verdict(
        line_id="legacy_no_step",
        returns=[0.01] * 5,
        edge_type="event",
        frozen_commit="abc1234",
    )
    stored = captured["recorder_save"]["params"]
    assert "step" not in stored
    assert "walk_train" not in stored
    assert "walk_test" not in stored
    assert "window_sanity" not in stored
