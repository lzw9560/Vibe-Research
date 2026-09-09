# -*- coding: utf-8 -*-
"""S172 index_replication_floor 单测——分批建仓 + 周报 + atomic write + 私有数据隔离。

离线：monkeypatch fetch_etf_quote + tracking_error_report 截断网络，零 akshare 调用。
VR_DATA_DIR 隔离（monkeypatch.setenv tmp_path，test_journal 模式）。
"""
from __future__ import annotations

import json

import pytest


# ---- fixtures ----

@pytest.fixture
def floor(tmp_path, monkeypatch):
    """每个用例独立 VR_DATA_DIR + 零网络。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    # 重新 import 使 _FLOOR_DIR / _BATCHES_PATH 指向 tmp_path
    import importlib
    import strategies.index_replication_floor as mod
    importlib.reload(mod)
    monkeypatch.setattr(mod, "fetch_etf_quote", lambda code: {
        "code": code, "name": "mock", "price": 1.5, "change_pct": 0.5,
    })
    monkeypatch.setattr(mod, "tracking_error_report",
                        lambda etf, idx, **kw: {"etf_code": etf, "windows": {},
                          "asof_date": "2026-09-09"})
    return mod


# ============================ R4: build_position_batches ============================

class TestBuildPositionBatches:
    def test_5_batches_equal_split(self, floor):
        plan = floor.build_position_batches(total=100000, n_batches=5, interval_days=7)
        assert len(plan) == 5
        assert plan[0]["amount"] == 20000
        assert plan[-1]["amount"] == 20000  # 整除无 remainder
        assert plan[0]["status"] == "planned"
        # 日期递增（间隔 7 交易日）
        assert plan[1]["date"] != plan[0]["date"]

    def test_unequal_split_remainder_to_last(self, floor):
        # 100003 / 5 = 20000 r3 → 前 4 批 20000，末批 20003
        plan = floor.build_position_batches(total=100003, n_batches=5, interval_days=7)
        assert len(plan) == 5
        assert plan[0]["amount"] == 20000
        assert plan[-1]["amount"] == 20003

    def test_one_shot_single_batch(self, floor):
        plan = floor.build_position_batches(total=100000, one_shot=True)
        assert len(plan) == 1
        assert plan[0]["amount"] == 100000
        assert plan[0]["status"] == "planned"


# ============================ record_batch + hold_status ============================

class TestRecordAndHold:
    def test_record_and_read(self, floor):
        floor.record_batch(0, "2026-09-10", 1.20, 16000, 19200.0)
        floor.record_batch(1, "2026-09-17", 1.25, 16000, 20000.0)
        status = floor.hold_status()
        assert status["n_filled"] == 2
        assert status["total_shares"] == 32000
        assert status["total_cost"] == 39200.0
        assert abs(status["avg_cost"] - 39200.0 / 32000) < 1e-6

    def test_record_overwrites_same_idx(self, floor):
        floor.record_batch(0, "2026-09-10", 1.20, 16000, 19200.0)
        floor.record_batch(0, "2026-09-11", 1.30, 15000, 19500.0)  # 覆盖
        status = floor.hold_status()
        assert status["n_filled"] == 1
        assert status["total_shares"] == 15000

    def test_hold_status_empty_when_no_batches(self, floor):
        status = floor.hold_status()
        assert status["n_filled"] == 0
        assert status["total_shares"] == 0
        assert status["avg_cost"] == 0.0

    def test_batches_json_not_in_git(self, floor, tmp_path):
        """A8：私有数据写入 .vibe-research/，不进 git。"""
        floor.record_batch(0, "2026-09-10", 1.20, 10000, 12000.0)
        batches_path = tmp_path / "etf_floor" / "batches.json"
        assert batches_path.exists()
        data = json.loads(batches_path.read_bytes())
        assert data[0]["batch_idx"] == 0
        assert data[0]["status"] == "filled"


# ============================ R5: weekly_report ============================

class TestWeeklyReport:
    def test_report_fields_complete(self, floor):
        floor.record_batch(0, "2026-09-10", 1.20, 10000, 12000.0)
        rpt = floor.weekly_report()
        assert rpt["etf_code"] == "512890"
        assert rpt["asof_price"] == 1.5  # mock quote
        assert rpt["total_shares"] == 10000
        assert rpt["market_value"] == 15000.0  # 10000 * 1.5
        assert rpt["cost_basis"] == 12000.0
        assert rpt["unrealized_pnl"] == 3000.0  # 15000 - 12000
        assert "tracking_error" in rpt
        assert "risk_disclaimer" in rpt

    def test_report_with_no_holdings(self, floor):
        rpt = floor.weekly_report()
        assert rpt["total_shares"] == 0
        assert rpt["market_value"] == 0.0
        assert rpt["unrealized_pnl"] == 0.0


# ============================ R6: 无 stop/take ============================

class TestNoStopTake:
    def test_no_stop_loss_logic(self, floor):
        """A6：grep 源码确认无 stop/take 触发逻辑。"""
        import inspect
        src = inspect.getsource(floor)
        # 无 stop_loss / take_profit / stop/take 触发逻辑
        assert "stop_loss" not in src.lower()
        assert "take_profit" not in src.lower()
        assert "stop_loss" not in src
        assert "take_profit" not in src
