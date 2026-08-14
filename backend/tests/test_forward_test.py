# -*- coding: utf-8 -*-
"""S066 Phase 0e 前向测试框架测试。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.forward_test import (
    DailyRecommendation,
    ForwardTestResult,
    record_daily_recommendations,
    record_actual_returns,
    get_forward_test_summary,
    get_daily_recommendations,
    _ensure_table,
    _FORWARD_TEST_SQL,
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """每个测试用临时 DB 隔离。"""
    db_path = tmp_path / "test_forward.db"
    monkeypatch.setattr("strategies.forward_test._DB", str(db_path))
    _ensure_table()
    return str(db_path)


class TestEnsureTable:
    """幂等建表。"""

    def test_table_created(self, fresh_db):
        conn = sqlite3.connect(fresh_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert ("forward_test_records",) in tables
        conn.close()

    def test_idempotent(self, fresh_db):
        """多次调用不报错。"""
        _ensure_table()
        _ensure_table()
        conn = sqlite3.connect(fresh_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert ("forward_test_records",) in tables
        conn.close()

    def test_indexes_created(self, fresh_db):
        conn = sqlite3.connect(fresh_db)
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = [i[0] for i in indexes]
        assert "idx_forward_test_date" in index_names
        assert "idx_forward_test_code" in index_names
        conn.close()


class TestRecordDailyRecommendations:
    """每日推荐写入。"""

    def test_insert_recommendations(self, fresh_db):
        recs = [
            DailyRecommendation("2026-08-14", "000001", "测试A", "consecutive_relay", 85.0,
                                "晴天", 0.7, 3.5),
            DailyRecommendation("2026-08-14", "000002", "测试B", "dragon_head", 82.0,
                                "晴天", 0.7, 3.5),
        ]
        count = record_daily_recommendations("2026-08-14", recs)
        assert count == 2

        daily = get_daily_recommendations("2026-08-14")
        assert len(daily) == 2
        assert daily[0]["code"] == "000001"
        assert daily[0]["strategy_score"] == 85.0

    def test_upsert_idempotent(self, fresh_db):
        """同日同 code 重复写不重复。"""
        rec = DailyRecommendation("2026-08-14", "000001", "测试", "first_plate", 70.0)
        record_daily_recommendations("2026-08-14", [rec])
        record_daily_recommendations("2026-08-14", [rec])  # 重复
        daily = get_daily_recommendations("2026-08-14")
        assert len(daily) == 1

    def test_empty_recommendations(self, fresh_db):
        count = record_daily_recommendations("2026-08-14", [])
        assert count == 0

    def test_sorted_by_score_desc(self, fresh_db):
        """查询结果按策略分降序。"""
        recs = [
            DailyRecommendation("2026-08-14", "000001", "低分", "first_plate", 50.0),
            DailyRecommendation("2026-08-14", "000002", "高分", "first_plate", 90.0),
            DailyRecommendation("2026-08-14", "000003", "中分", "first_plate", 70.0),
        ]
        record_daily_recommendations("2026-08-14", recs)
        daily = get_daily_recommendations("2026-08-14")
        assert daily[0]["strategy_score"] == 90.0
        assert daily[1]["strategy_score"] == 70.0
        assert daily[2]["strategy_score"] == 50.0


class TestRecordActualReturns:
    """次日收益回填。"""

    def test_update_returns(self, fresh_db):
        rec = DailyRecommendation("2026-08-13", "000001", "测试", "first_plate", 70.0)
        record_daily_recommendations("2026-08-13", [rec])

        updated = record_actual_returns("2026-08-13", {
            "000001": {"return_open2close": 2.5, "return_close2close": 3.0, "next_pctChg": 3.0},
        })
        assert updated == 1

        daily = get_daily_recommendations("2026-08-13")
        assert daily[0]["return_open2close"] == 2.5
        assert daily[0]["is_win"] == 1

    def test_loss_marked_as_not_win(self, fresh_db):
        rec = DailyRecommendation("2026-08-13", "000001", "测试", "first_plate", 70.0)
        record_daily_recommendations("2026-08-13", [rec])

        record_actual_returns("2026-08-13", {
            "000001": {"return_open2close": -2.0, "return_close2close": -1.5, "next_pctChg": -1.5},
        })
        daily = get_daily_recommendations("2026-08-13")
        assert daily[0]["is_win"] == 0

    def test_missing_next_bar_stays_null(self, fresh_db):
        """缺收益的记录保持 NULL（不臆造）。"""
        rec = DailyRecommendation("2026-08-13", "000001", "测试", "first_plate", 70.0)
        record_daily_recommendations("2026-08-13", [rec])
        # 不回填收益
        daily = get_daily_recommendations("2026-08-13")
        assert daily[0]["return_open2close"] is None
        assert daily[0]["is_win"] == 0  # NULL 收益不算 win

    def test_nonexistent_code_no_update(self, fresh_db):
        updated = record_actual_returns("2026-08-13", {
            "999999": {"return_open2close": 2.0, "return_close2close": 2.0, "next_pctChg": 2.0},
        })
        assert updated == 0


class TestGetForwardTestSummary:
    """前向测试汇总。"""

    def test_empty_summary(self, fresh_db):
        """空表 → 未通过（样本不足）。"""
        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.total_days == 0
        assert result.passed is False
        assert "样本不足" in result.note or "无已结算" in result.note

    def test_pass_criteria_met(self, fresh_db):
        """胜率 >= 基准×0.8 + 样本充足 → 通过。"""
        # 造 25 天数据，每天 2 推荐，80% 胜率
        for day in range(25):
            date = f"2026-08-{day+1:02d}"
            recs = [
                DailyRecommendation(date, f"00000{day}1", "A", "first_plate", 70.0),
                DailyRecommendation(date, f"00000{day}2", "B", "first_plate", 75.0),
            ]
            record_daily_recommendations(date, recs)
            # 80% 胜率：4 赢 1 输
            returns = {
                f"00000{day}1": {"return_open2close": 2.0, "return_close2close": 2.0, "next_pctChg": 2.0},
                f"00000{day}2": {"return_open2close": -1.0 if day % 5 == 0 else 1.5,
                                 "return_close2close": -1.0, "next_pctChg": -1.0},
            }
            record_actual_returns(date, returns)

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.total_days >= 20
        assert result.win_rate >= 48.0  # 60% × 0.8
        assert result.passed is True

    def test_fail_low_winrate(self, fresh_db):
        """胜率 < 阈值 → 不通过。"""
        for day in range(25):
            date = f"2026-08-{day+1:02d}"
            recs = [DailyRecommendation(date, f"00000{day}1", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            # 全亏
            record_actual_returns(date, {
                f"00000{day}1": {"return_open2close": -2.0, "return_close2close": -2.0, "next_pctChg": -2.0},
            })

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.win_rate == 0.0
        assert result.passed is False
        assert "胜率" in result.note

    def test_fail_insufficient_days(self, fresh_db):
        """样本不足 20 天 → 不通过。"""
        for day in range(10):  # 只 10 天
            date = f"2026-08-{day+1:02d}"
            recs = [DailyRecommendation(date, f"00000{day}1", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            record_actual_returns(date, {
                f"00000{day}1": {"return_open2close": 2.0, "return_close2close": 2.0, "next_pctChg": 2.0},
            })

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.total_days == 10
        assert result.passed is False
        assert "样本不足" in result.note

    def test_consecutive_loss_tracked(self, fresh_db):
        """连续亏损笔数追踪。"""
        for day in range(10):
            date = f"2026-08-{day+1:02d}"
            recs = [DailyRecommendation(date, f"00000{day}1", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            record_actual_returns(date, {
                f"00000{day}1": {"return_open2close": -1.0, "return_close2close": -1.0, "next_pctChg": -1.0},
            })

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=5)
        assert result.consecutive_loss == 10  # 最近 10 笔全亏
