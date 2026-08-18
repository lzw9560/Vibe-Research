# -*- coding: utf-8 -*-
"""S070 C9：R1 trajectory + R7 派生计算单测（纯函数，不依赖网络）。

覆盖（AC1/AC6/AC7）：
- compute_trajectory：空/单点/正常/缺 seal_amount
- _linear_regression_slope：递增/递减/单点
- compute_derived_features：
  - 空时序
  - 全程封死（open_count 全 0）→ last_lock_time=末 ts, broken=0
  - 全程炸板（open_count 全 >0）→ last_lock_time=None, broken=全程分钟数
  - 中间炸板（0→1→0）→ last_lock_time=最后封死 ts, broken=炸板区间
  - low_price 全缺 → max_drop_pct=None, degraded
  - limit_pct 缺 → 退回首价近似, degraded
  - max_drop_pct 计算正确性（手算对照）
- persist_trajectory / persist_derived_features：UPSERT 幂等
- granularity_note 固定"60s粒度近似"（AC7）
"""
import sqlite3
from datetime import datetime

import pytest


def _snap(ts: str, seal_amount=None, open_count=0, low_price=None,
          limit_pct=None, price=None):
    """构造单条快照 dict（字段对齐 seal_intraday_snapshots 表）。"""
    return {
        "ts": ts, "seal_amount": seal_amount, "open_count": open_count,
        "low_price": low_price, "limit_pct": limit_pct, "price": price,
    }


def _make_snaps(seals, open_counts=None, low_prices=None, limit_pct=10.0, price=11.0):
    """批量构造时序：seals[i] 对应 ts=i 分钟。open_counts/low_prices 缺省=全 0。"""
    n = len(seals)
    open_counts = open_counts or [0] * n
    low_prices = low_prices or [None] * n
    return [
        _snap(ts=f"2026-08-11T09:{25 + i:02d}:00",
              seal_amount=seals[i], open_count=open_counts[i],
              low_price=low_prices[i], limit_pct=limit_pct, price=price)
        for i in range(n)
    ]


# ============================================================
# _linear_regression_slope
# ============================================================

class TestLinearRegressionSlope:
    def test_increasing(self):
        from strategies.intraday_features import _linear_regression_slope
        assert _linear_regression_slope([1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_decreasing(self):
        from strategies.intraday_features import _linear_regression_slope
        assert _linear_regression_slope([3.0, 2.0, 1.0]) == pytest.approx(-1.0)

    def test_single_point_returns_zero(self):
        from strategies.intraday_features import _linear_regression_slope
        assert _linear_regression_slope([5.0]) == 0.0

    def test_empty_returns_zero(self):
        from strategies.intraday_features import _linear_regression_slope
        assert _linear_regression_slope([]) == 0.0

    def test_flat_returns_zero(self):
        from strategies.intraday_features import _linear_regression_slope
        assert _linear_regression_slope([5.0, 5.0, 5.0]) == 0.0


# ============================================================
# compute_trajectory（R1）
# ============================================================

class TestComputeTrajectory:
    def test_empty_snapshots_missing(self):
        from strategies.intraday_features import compute_trajectory
        traj = compute_trajectory([])
        assert traj["data_status"] == "missing"
        assert traj["seal_delta"] is None
        assert traj["seal_max"] is None
        assert traj["snapshot_count"] == 0

    def test_all_seal_amount_missing(self):
        from strategies.intraday_features import compute_trajectory
        snaps = [_snap(ts=f"2026-08-11T09:{25+i:02d}:00") for i in range(5)]
        traj = compute_trajectory(snaps)
        assert traj["data_status"] == "missing"
        assert traj["seal_delta"] is None
        assert traj["snapshot_count"] == 5  # 快照数仍记

    def test_single_point_degraded(self):
        from strategies.intraday_features import compute_trajectory
        snaps = _make_snaps([1e8])
        traj = compute_trajectory(snaps)
        assert traj["seal_delta"] == 0.0  # 单点 delta=0
        assert traj["seal_slope"] == 0.0
        assert traj["seal_max"] == 1e8
        assert traj["seal_min"] == 1e8
        assert traj["data_status"] == "degraded"  # <10

    def test_normal_10_points_ok(self):
        from strategies.intraday_features import compute_trajectory
        seals = [1e8, 1.2e8, 1.5e8, 1.3e8, 1.6e8, 1.4e8, 1.7e8, 1.5e8, 1.8e8, 2.0e8]
        snaps = _make_snaps(seals)
        traj = compute_trajectory(snaps)
        assert traj["data_status"] == "ok"  # >=10
        assert traj["seal_delta"] == 1.0e8  # 末-首 = 2.0e8 - 1.0e8
        assert traj["seal_max"] == 2.0e8
        assert traj["seal_min"] == 1.0e8
        assert traj["snapshot_count"] == 10
        assert traj["seal_slope"] > 0  # 递增趋势

    def test_declining_slope_negative(self):
        from strategies.intraday_features import compute_trajectory
        seals = [2.0e8, 1.8e8, 1.5e8, 1.3e8, 1.0e8] * 2  # 10 点递减
        snaps = _make_snaps(seals)
        traj = compute_trajectory(snaps)
        assert traj["seal_slope"] < 0  # 衰减


# ============================================================
# compute_derived_features（R7）
# ============================================================

class TestComputeDerivedFeatures:
    def test_empty_snapshots_missing(self):
        from strategies.intraday_features import compute_derived_features
        d = compute_derived_features([])
        assert d["data_status"] == "missing"
        assert d["last_lock_time"] is None
        assert d["broken_duration_min"] is None
        assert d["max_drop_pct"] is None
        assert d["limit_price"] is None
        assert d["granularity_note"] == "60s粒度近似"  # AC7

    def test_all_locked_last_lock_time_is_last_ts(self):
        """全程封死（open_count 全 0）→ last_lock_time=末 ts, broken=0。"""
        from strategies.intraday_features import compute_derived_features
        snaps = _make_snaps([1e8] * 10, open_counts=[0] * 10,
                            low_prices=[10.5] * 10, limit_pct=10.0, price=11.0)
        d = compute_derived_features(snaps)
        assert d["last_lock_time"] == snaps[-1]["ts"]
        assert d["broken_duration_min"] == 0.0  # 全程封死，无炸板
        assert d["data_status"] == "ok"

    def test_all_broken_last_lock_time_none(self):
        """全程炸板（open_count 全 >0）→ last_lock_time=None, broken=全程分钟数。"""
        from strategies.intraday_features import compute_derived_features
        snaps = _make_snaps([1e8] * 8, open_counts=[1] * 8,
                            low_prices=[10.5] * 8, limit_pct=10.0, price=11.0)
        d = compute_derived_features(snaps)
        assert d["last_lock_time"] is None  # 从未封死
        assert d["broken_duration_min"] == 8.0  # 8 个快照都炸板 = 8 分钟

    def test_middle_break_last_lock_time_correct(self):
        """中间炸板（0→1→0）→ last_lock_time=最后封死 ts, broken=炸板区间分钟数。"""
        from strategies.intraday_features import compute_derived_features
        # 5 点：封-封-炸-封-封（open_count: 0,0,1,0,0）
        snaps = _make_snaps([1e8] * 5, open_counts=[0, 0, 1, 0, 0],
                            low_prices=[10.5] * 5, limit_pct=10.0, price=11.0)
        d = compute_derived_features(snaps)
        assert d["last_lock_time"] == snaps[4]["ts"]  # 最后一个 open_count==0
        assert d["broken_duration_min"] == 1.0  # 只 1 个 open_count>0

    def test_max_drop_pct_calculation(self):
        """max_drop_pct 手算：涨停价=11/(1+0.1)=10, min_low=9.5 → (10-9.5)/10*100=5.0。"""
        from strategies.intraday_features import compute_derived_features
        snaps = _make_snaps([1e8] * 5, open_counts=[0] * 5,
                            low_prices=[10.0, 9.8, 9.5, 9.7, 9.6],  # min=9.5
                            limit_pct=10.0, price=11.0)  # 涨停价=11/1.1=10
        d = compute_derived_features(snaps)
        # limit_price = 11.0 / (1 + 10/100) = 10.0
        assert d["limit_price"] == pytest.approx(10.0)
        # max_drop_pct = (10.0 - 9.5) / 10.0 * 100 = 5.0
        assert d["max_drop_pct"] == pytest.approx(5.0)

    def test_max_drop_pct_none_when_low_price_missing(self):
        """low_price 全缺 → max_drop_pct=None, degraded。"""
        from strategies.intraday_features import compute_derived_features
        snaps = _make_snaps([1e8] * 5, open_counts=[0] * 5,
                            low_prices=[None] * 5, limit_pct=10.0, price=11.0)
        d = compute_derived_features(snaps)
        assert d["max_drop_pct"] is None
        assert d["data_status"] == "degraded"

    def test_limit_price_degraded_when_limit_pct_missing(self):
        """limit_pct 缺 → 退回首价近似, degraded。"""
        from strategies.intraday_features import compute_derived_features
        snaps = _make_snaps([1e8] * 5, open_counts=[0] * 5,
                            low_prices=[10.5] * 5, limit_pct=None, price=11.0)
        d = compute_derived_features(snaps)
        assert d["limit_price"] == 11.0  # 退回首价
        assert d["data_status"] == "degraded"

    def test_granularity_note_always_present(self):
        """AC7：granularity_note 固定 '60s粒度近似'，无论数据有无。"""
        from strategies.intraday_features import compute_derived_features
        d_empty = compute_derived_features([])
        d_full = compute_derived_features(_make_snaps([1e8] * 10))
        assert d_empty["granularity_note"] == "60s粒度近似"
        assert d_full["granularity_note"] == "60s粒度近似"


# ============================================================
# persist_trajectory / persist_derived_features（UPSERT 幂等）
# ============================================================

@pytest.fixture
def isolated_features_db(tmp_path, monkeypatch):
    """临时 seal_intraday.db + 触发迁移（含 intraday_features + seal_derived_features）。"""
    db_path = tmp_path / "seal_intraday.db"
    monkeypatch.setattr("risk.seal_intraday_collector._DB_PATH", str(db_path))
    monkeypatch.setattr("risk.seal_intraday_collector.SEAL_INTRADAY_DB_PATH", str(db_path))
    from risk.seal_intraday_collector import run_migrations
    run_migrations()
    return str(db_path)


class TestPersist:
    def test_persist_trajectory_upsert_idempotent(self, isolated_features_db):
        from strategies.intraday_features import compute_trajectory, persist_trajectory
        snaps = _make_snaps([1e8, 1.2e8, 1.5e8] + [1.3e8] * 7)  # 10 点
        traj = compute_trajectory(snaps)

        conn = sqlite3.connect(isolated_features_db)
        try:
            persist_trajectory("2026-08-11", "000001", "平安银行", traj, conn)
            conn.commit()
            # 二次写入（UPSERT）不报错、覆盖
            persist_trajectory("2026-08-11", "000001", "平安银行", traj, conn)
            conn.commit()
            cnt = conn.execute(
                "SELECT COUNT(*) FROM intraday_features WHERE date='2026-08-11' AND code='000001'"
            ).fetchone()[0]
            assert cnt == 1  # 不重复
        finally:
            conn.close()

    def test_persist_derived_features_upsert_idempotent(self, isolated_features_db):
        from strategies.intraday_features import compute_derived_features, persist_derived_features
        snaps = _make_snaps([1e8] * 5, open_counts=[0, 0, 1, 0, 0],
                            low_prices=[10.5] * 5, limit_pct=10.0, price=11.0)
        derived = compute_derived_features(snaps)

        conn = sqlite3.connect(isolated_features_db)
        try:
            persist_derived_features("2026-08-11", "000001", "平安银行", derived, conn)
            conn.commit()
            persist_derived_features("2026-08-11", "000001", "平安银行", derived, conn)
            conn.commit()
            cnt = conn.execute(
                "SELECT COUNT(*) FROM seal_derived_features WHERE date='2026-08-11' AND code='000001'"
            ).fetchone()[0]
            assert cnt == 1
            # granularity_note 落库（AC7）
            note = conn.execute(
                "SELECT granularity_note FROM seal_derived_features WHERE date='2026-08-11' AND code='000001'"
            ).fetchone()[0]
            assert note == "60s粒度近似"
        finally:
            conn.close()
