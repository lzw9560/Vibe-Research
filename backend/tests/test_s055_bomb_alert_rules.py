# -*- coding: utf-8 -*-
"""S055 T3：炸板预警规则引擎单测（合成时序）。

六条规则各覆盖触发/不触发/缺数据三态。
"""

from datetime import datetime, timedelta

import pytest

from risk.bomb_alert_rules import (
    C1_SEAL_DROP_RATIO_5MIN,
    C2_DEGRADED_SEAL_DROP_RATIO,
    C4_INDEX_DROP_5MIN,
    C6_SEAL_TO_FLOAT_RATIO_MIN,
    check_all_rules,
    check_c1_seal_drop_5min,
    check_c2_degraded_seal_drop,
    check_c3_sector_leader_broken,
    check_c4_index_drop_5min,
    check_c5_reopen_unsealed,
    check_c6_seal_below_float_ratio,
)


_NOW = datetime(2026, 8, 11, 10, 30)


def _snap(ts_min: float, seal: float | None = None, open_count: float | None = None,
          float_cap: float | None = None, idx: float | None = None) -> dict:
    """构造快照。ts_min = 相对 _NOW 的分钟偏移。"""
    return {
        "ts": (_NOW - timedelta(minutes=ts_min)).isoformat() if ts_min > 0 else _NOW.isoformat(),
        "seal_amount": seal,
        "open_count": open_count,
        "float_market_cap": float_cap,
        "index_5min_change": idx,
    }


class TestC1SealDrop5Min:
    def test_triggered_when_drop_above_30pct(self):
        snaps = [_snap(5, seal=1e8), _snap(0, seal=0.6e8)]  # 减 40%
        r = check_c1_seal_drop_5min(snaps, "000001", "测试", _NOW)
        assert r.triggered is True
        assert r.alert is not None
        assert r.alert.alert_level == "yellow"

    def test_not_triggered_when_drop_below_30pct(self):
        snaps = [_snap(5, seal=1e8), _snap(0, seal=0.8e8)]  # 减 20%
        r = check_c1_seal_drop_5min(snaps, "000001", "测试", _NOW)
        assert r.triggered is False

    def test_missing_when_insufficient_snapshots(self):
        r = check_c1_seal_drop_5min([_snap(0, seal=1e8)], "000001", "测试", _NOW)
        assert r.triggered is False
        assert r.data_status == "missing"

    def test_missing_when_no_old_snapshot(self):
        snaps = [_snap(1, seal=1e8), _snap(0, seal=0.5e8)]  # 只 1 分钟前
        r = check_c1_seal_drop_5min(snaps, "000001", "测试", _NOW)
        assert r.data_status == "missing"


class TestC2DegradedSealDrop:
    def test_triggered_when_drop_above_50pct(self):
        snaps = [_snap(5, seal=1e8), _snap(0, seal=0.4e8)]  # 减 60%
        r = check_c2_degraded_seal_drop(snaps, "000001", "测试", _NOW)
        assert r.triggered is True
        assert "降级" in r.alert.condition

    def test_not_triggered_below_50pct(self):
        snaps = [_snap(5, seal=1e8), _snap(0, seal=0.6e8)]  # 减 40%
        r = check_c2_degraded_seal_drop(snaps, "000001", "测试", _NOW)
        assert r.triggered is False


class TestC3SectorLeaderBroken:
    def test_triggered_when_in_zb_pool(self):
        snaps = [_snap(0, seal=1e8)]
        r = check_c3_sector_leader_broken(snaps, "000001", "测试", {"000001"}, _NOW)
        assert r.triggered is True
        assert r.alert.alert_level == "red"

    def test_not_triggered_when_not_in_zb_pool(self):
        snaps = [_snap(0, seal=1e8)]
        r = check_c3_sector_leader_broken(snaps, "000001", "测试", {"600519"}, _NOW)
        assert r.triggered is False

    def test_missing_when_zb_pool_empty(self):
        r = check_c3_sector_leader_broken([], "000001", "测试", set(), _NOW)
        assert r.data_status == "missing"


class TestC4IndexDrop5Min:
    def test_triggered_when_index_drops_above_0_5pct(self):
        snaps = [_snap(0, idx=-0.6)]
        r = check_c4_index_drop_5min(snaps, "000001", "测试", _NOW)
        assert r.triggered is True
        assert r.alert.alert_level == "red"

    def test_not_triggered_when_index_stable(self):
        snaps = [_snap(0, idx=-0.2)]
        r = check_c4_index_drop_5min(snaps, "000001", "测试", _NOW)
        assert r.triggered is False

    def test_missing_when_no_index_data(self):
        snaps = [_snap(0)]
        r = check_c4_index_drop_5min(snaps, "000001", "测试", _NOW)
        assert r.data_status == "missing"


class TestC5ReopenUnsealed:
    def test_triggered_when_open_3min_unsealed(self):
        snaps = [_snap(4, open_count=1), _snap(3, open_count=1), _snap(0, open_count=1)]
        r = check_c5_reopen_unsealed(snaps, "000001", "测试", _NOW)
        assert r.triggered is True
        assert r.alert.alert_level == "red"

    def test_not_triggered_when_resealed(self):
        snaps = [_snap(4, open_count=1), _snap(0, open_count=0)]  # 已回封
        r = check_c5_reopen_unsealed(snaps, "000001", "测试", _NOW)
        assert r.triggered is False

    def test_not_triggered_when_no_open(self):
        snaps = [_snap(4, open_count=0), _snap(0, open_count=0)]
        r = check_c5_reopen_unsealed(snaps, "000001", "测试", _NOW)
        assert r.triggered is False

    def test_missing_when_no_open_count(self):
        snaps = [_snap(0)]
        r = check_c5_reopen_unsealed(snaps, "000001", "测试", _NOW)
        assert r.data_status == "missing"


class TestC6SealBelowFloatRatio:
    def test_triggered_when_seal_below_0_3pct(self):
        snaps = [_snap(0, seal=1e6, float_cap=1e9)]  # 0.1% < 0.3%
        r = check_c6_seal_below_float_ratio(snaps, "000001", "测试", _NOW)
        assert r.triggered is True
        assert r.alert.alert_level == "red"

    def test_not_triggered_when_seal_above_0_3pct(self):
        snaps = [_snap(0, seal=5e6, float_cap=1e9)]  # 0.5% > 0.3%
        r = check_c6_seal_below_float_ratio(snaps, "000001", "测试", _NOW)
        assert r.triggered is False

    def test_missing_when_no_seal_or_float(self):
        snaps = [_snap(0)]
        r = check_c6_seal_below_float_ratio(snaps, "000001", "测试", _NOW)
        assert r.data_status == "missing"


class TestCheckAllRules:
    def test_all_six_rules_checked(self):
        snaps = [_snap(5, seal=1e8, open_count=0, float_cap=1e9, idx=0.0),
                 _snap(0, seal=0.6e8, open_count=0, float_cap=1e9, idx=0.0)]
        results = check_all_rules(snaps, "000001", "测试", set(), _NOW)
        assert len(results) == 6
        rule_ids = [r.rule_id for r in results]
        assert rule_ids == ["C1", "C2", "C3", "C4", "C5", "C6"]

    def test_missing_data_does_not_trigger(self):
        snaps = [_snap(0)]  # 只一条，缺大多字段
        results = check_all_rules(snaps, "000001", "测试", set(), _NOW)
        for r in results:
            assert r.triggered is False  # 缺数据不触发
