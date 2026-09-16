# -*- coding: utf-8 -*-
"""S204 T8 R3 enforce 测试——§44v2 verdict 定期 enforce 降级。

days_robust 跨 60 天阈 → lift_to_multiplier 升降级 + write_override 刷新。
非 arm 级 dimension（gene_score/turnover 等无 arm 映射）→ 保持 frozen 不重算。
当前 forward_test ~20 天 → skip all underpowered（接线建好待 ≥60 天 bite）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestR3EnforceRegistration:
    """T8 接线：seed task + executor 注册。"""

    def test_seed_has_r3_enforce_task(self):
        """seed.py 源码含 task_type='r3_enforce' + payload enforce=True（静态确认）。"""
        seed_path = backend_dir / "scheduler" / "seed.py"
        src = seed_path.read_text(encoding="utf-8")
        assert 'task_type="r3_enforce"' in src, "seed.py 应含 task_type='r3_enforce'"
        assert '"enforce": True' in src, "r3_enforce payload 应含 enforce=True"
        assert "threshold_days" in src, "payload 应含 threshold_days"

    def test_executor_r3_enforce_registered(self):
        """TaskExecutor._executors dict 含 'r3_enforce' key + callable。"""
        from scheduler.executors import TaskExecutor
        ex = TaskExecutor()
        assert "r3_enforce" in ex._executors, "_executors 应含 r3_enforce"
        assert callable(ex._executors["r3_enforce"]), "r3_enforce 应 callable"

    def test_execute_r3_enforce_delegates_to_backtest(self, monkeypatch):
        """_execute_r3_enforce 委托 backtest.r3_enforce。"""
        from scheduler.executors import TaskExecutor
        captured = {}

        def fake_r3(payload):
            captured["payload"] = payload
            return {"status": "ok", "delegated": True}

        monkeypatch.setattr("scheduler.executors.backtest.r3_enforce", fake_r3)
        ex = TaskExecutor()
        result = ex._execute_r3_enforce({"threshold_days": 60})
        assert result["delegated"] is True
        assert captured["payload"]["threshold_days"] == 60


def _make_fake_journal(records_by_arm: dict[str, list] | None = None,
                       default_records: list | None = None):
    """造 fake TradeJournal——query_records 按 arm 返不同 records（closure）。"""
    class FakeJournal:
        def __init__(self, db_path=None):
            self.db_path = db_path
        def query_records(self, arm=None, is_realized=None, is_dead_arm=0, limit=5000):
            if records_by_arm and arm in records_by_arm:
                return records_by_arm[arm]
            return default_records or []
    return FakeJournal


class TestR3EnforceLogic:
    """r3_enforce 逻辑：arm 级 vs 非 arm 级 + days_robust 阈值。"""

    def test_skips_underpowered(self, monkeypatch):
        """arm days<60 → skipped_underpowered，不调 write_override。"""
        from scheduler.executors import backtest
        # 30 distinct exit_date（<60）
        records = [SimpleNamespace(exit_date=f"2026-01-{i:02d}") for i in range(1, 31)]
        FakeJournal = _make_fake_journal(default_records=records)
        monkeypatch.setattr("engine.trade_journal.TradeJournal", FakeJournal)

        write_calls = []
        monkeypatch.setattr("candidate_funnel.lift_override.write_override",
            lambda *a, **kw: write_calls.append(a) or {})

        result = backtest.r3_enforce({"threshold_days": 60})

        assert result["status"] == "ok"
        assert len(result["enforced"]) == 0, f"<60d 应 skip 不 enforce，got {len(result['enforced'])}"
        assert len(result["skipped_underpowered"]) > 0, "应记 skipped_underpowered"
        assert write_calls == [], f"<60d 不应调 write_override，got {len(write_calls)} calls"

    def test_enforces_at_60_days(self, monkeypatch):
        """arm days≥60 → 调 lift_to_multiplier + write_override（enforced 非空）。"""
        from scheduler.executors import backtest
        # 70 distinct exit_date（≥60）
        records = [SimpleNamespace(exit_date=f"2026-01-{i:02d}") for i in range(1, 71)]
        FakeJournal = _make_fake_journal(default_records=records)
        monkeypatch.setattr("engine.trade_journal.TradeJournal", FakeJournal)

        write_calls = []
        monkeypatch.setattr("candidate_funnel.lift_override.write_override",
            lambda *a, **kw: write_calls.append(a[0] if a else "") or {})

        result = backtest.r3_enforce({"threshold_days": 60})

        assert result["status"] == "ok"
        assert len(result["enforced"]) > 0, "≥60d 应 enforce"
        assert len(write_calls) > 0, "应调 write_override"
        # arm 级 dimension 至少含 breakout/trend_swing/post_first_board 之一
        enforced_ids = {e["dimension_id"] for e in result["enforced"]}
        assert ({"breakout", "trend_swing", "post_first_board"} & enforced_ids), \
            f"应 enforce arm 级 dimension，got {enforced_ids}"

    def test_non_arm_dim_skipped(self, monkeypatch):
        """gene_score/turnover 非 arm 级 → skipped_non_arm 含，不重算 days。"""
        from scheduler.executors import backtest
        # 0 records（arm 级 skip underpowered）+ 非 arm 级应 skipped_non_arm
        FakeJournal = _make_fake_journal(default_records=[])
        monkeypatch.setattr("engine.trade_journal.TradeJournal", FakeJournal)
        monkeypatch.setattr("candidate_funnel.lift_override.write_override",
            lambda *a, **kw: {})

        result = backtest.r3_enforce({"threshold_days": 60})

        # gene_score/turnover/sector_heat 非arm级 → skipped_non_arm
        assert "gene_score" in result["skipped_non_arm"], "gene_score 非 arm 级应 skip"
        assert "turnover" in result["skipped_non_arm"], "turnover 非 arm 级应 skip"
        # vol_surge_ref 是 _ref → 跳过（不在 non_arm）
        assert "vol_surge_ref" not in result["skipped_non_arm"], "_ref 应跳过"

    def test_ref_dim_excluded(self, monkeypatch):
        """_ref 维度（vol_surge_ref）完全跳过（不 enforce 不 skip_non_arm）。"""
        from scheduler.executors import backtest
        FakeJournal = _make_fake_journal(default_records=[])
        monkeypatch.setattr("engine.trade_journal.TradeJournal", FakeJournal)
        monkeypatch.setattr("candidate_funnel.lift_override.write_override",
            lambda *a, **kw: {})

        result = backtest.r3_enforce({"threshold_days": 60})

        all_dims = (set(result["enforced"]) |
                    {e["dimension_id"] for e in result["enforced"]} |
                    set(result["skipped_non_arm"]) |
                    {e["dimension_id"] for e in result["skipped_underpowered"]})
        assert "vol_surge_ref" not in all_dims, "_ref 应完全跳过"

    def test_returns_summary_and_threshold(self, monkeypatch):
        """return 含 summary + threshold_days。"""
        from scheduler.executors import backtest
        FakeJournal = _make_fake_journal(default_records=[])
        monkeypatch.setattr("engine.trade_journal.TradeJournal", FakeJournal)
        monkeypatch.setattr("candidate_funnel.lift_override.write_override",
            lambda *a, **kw: {})

        result = backtest.r3_enforce({"threshold_days": 60})

        assert "summary" in result
        assert "R3 enforce" in result["summary"]
        assert result["threshold_days"] == 60
        # summary 含三计数
        assert "enforced" in result["summary"]
        assert "underpowered" in result["summary"]
        assert "non-arm" in result["summary"]
