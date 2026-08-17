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
    record_universe_returns,
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
    """前向测试汇总（§44 60日复验窗口三态：validated | 未 validated | 探索性）。"""

    def test_empty_summary(self, fresh_db):
        """空表 → 未通过（样本不足，探索性 n<30）。"""
        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.total_days == 0
        assert result.passed is False
        assert result.validation_status == "探索性"  # n<30 优先
        assert "样本不足" in result.note or "无已结算" in result.note

    def test_pass_criteria_met(self, fresh_db):
        """§44 通过：picks 胜率>=60% + universe 胜率低 → lift>=2x。"""
        for day in range(25):
            date = f"2026-08-{day+1:02d}"
            # picks：2/天，80% 胜率（pick1 全赢，pick2 day>=15 输）
            recs = [
                DailyRecommendation(date, f"00{day}01", "A", "first_plate", 80.0),
                DailyRecommendation(date, f"00{day}02", "B", "consecutive_relay", 70.0),
            ]
            record_daily_recommendations(date, recs)
            pick2_ret = 2.0 if day < 15 else -1.0
            record_actual_returns(date, {
                f"00{day}01": {"return_open2close": 2.0, "return_close2close": 2.0, "next_pctChg": 2.0},
                f"00{day}02": {"return_open2close": pick2_ret, "return_close2close": pick2_ret, "next_pctChg": pick2_ret},
            })
            # universe：10/天，30% 胜率（3 赢 7 输）
            uni = {}
            for i in range(10):
                win = i < 3
                r = 2.0 if win else -1.0
                uni[f"1{day}0{i}"] = {"return_open2close": r, "return_close2close": r, "next_pctChg": r}
            record_universe_returns(date, uni)

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.total_days >= 20
        assert result.win_rate == 80.0  # 40/50
        assert result.random_baseline_win_rate == 30.0  # 75/250
        assert result.lift >= 2.0  # 2.67
        assert result.passed is True
        assert result.validation_status == "validated"  # lift>=2 + winrate>=60 + n>=30

    def test_fail_no_edge(self, fresh_db):
        """§44 核心：picks 高胜率但 universe 同样高 → lift<2x → 不通过（不优于随机）。"""
        for day in range(25):
            date = f"2026-08-{day+1:02d}"
            recs = [DailyRecommendation(date, f"00{day}01", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            # picks 80% 胜率（day%5==0 输）
            r = 2.0 if day % 5 != 0 else -1.0
            record_actual_returns(date, {
                f"00{day}01": {"return_open2close": r, "return_close2close": r, "next_pctChg": r},
            })
            # universe 也 80%（4/5 赢）→ lift 1.0x 噪声
            uni = {}
            for i in range(5):
                win = i != 0
                rr = 2.0 if win else -1.0
                uni[f"1{day}0{i}"] = {"return_open2close": rr, "return_close2close": rr, "next_pctChg": rr}
            record_universe_returns(date, uni)

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.win_rate >= 60.0  # 胜率够高
        assert result.lift < 2.0  # 但 lift<2x
        assert result.passed is False
        assert result.validation_status == "探索性"  # s_settled=25<30 优先于未 validated
        assert "噪声" in result.note or "重叠" in result.note

    def test_fail_no_universe(self, fresh_db):
        """无 universe_returns → 无法算 lift → 不通过（诚实：不能伪造 lift）。"""
        for day in range(25):
            date = f"2026-08-{day+1:02d}"
            recs = [DailyRecommendation(date, f"00{day}01", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            record_actual_returns(date, {
                f"00{day}01": {"return_open2close": 2.0, "return_close2close": 2.0, "next_pctChg": 2.0},
            })
            # 不回填 universe

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.random_settled == 0
        assert result.lift == 0.0
        assert result.passed is False
        assert "无随机基准" in result.note

    def test_fail_low_winrate(self, fresh_db):
        """胜率 < §13.0 门槛 60% → 不通过。"""
        for day in range(25):
            date = f"2026-08-{day+1:02d}"
            recs = [DailyRecommendation(date, f"00{day}01", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            record_actual_returns(date, {
                f"00{day}01": {"return_open2close": -2.0, "return_close2close": -2.0, "next_pctChg": -2.0},
            })
            # universe 也全亏（排除 lift 干扰，专注 winrate<60）
            uni = {f"1{day}0{i}": {"return_open2close": -1.0, "return_close2close": -1.0, "next_pctChg": -1.0}
                   for i in range(5)}
            record_universe_returns(date, uni)

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.win_rate == 0.0
        assert result.passed is False
        assert "胜率" in result.note

    def test_fail_insufficient_days(self, fresh_db):
        """样本不足 20 天 → 不通过。"""
        for day in range(10):  # 只 10 天
            date = f"2026-08-{day+1:02d}"
            recs = [DailyRecommendation(date, f"00{day}01", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            record_actual_returns(date, {
                f"00{day}01": {"return_open2close": 2.0, "return_close2close": 2.0, "next_pctChg": 2.0},
            })

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.total_days == 10
        assert result.passed is False
        assert "样本不足" in result.note

    def test_consecutive_loss_tracked(self, fresh_db):
        """连续亏损笔数追踪。"""
        for day in range(10):
            date = f"2026-08-{day+1:02d}"
            recs = [DailyRecommendation(date, f"00{day}01", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            record_actual_returns(date, {
                f"00{day}01": {"return_open2close": -1.0, "return_close2close": -1.0, "next_pctChg": -1.0},
            })

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=5)
        assert result.consecutive_loss == 10  # 最近 10 笔全亏

    def test_low_coverage_flags_partial_sample(self, fresh_db):
        """116 诚实层：picks 收益覆盖低（settled<<total）→ note 标'部分样本'。"""
        for day in range(25):
            date = f"2026-08-{day+1:02d}"
            recs = [
                DailyRecommendation(date, f"00{day}01", "A", "first_plate", 70.0),
                DailyRecommendation(date, f"00{day}02", "B", "first_plate", 75.0),
            ]
            record_daily_recommendations(date, recs)
            if day < 5:  # 仅前 5 日回填（10/50 settled）
                record_actual_returns(date, {
                    f"00{day}01": {"return_open2close": 2.0, "return_close2close": 2.0, "next_pctChg": 2.0},
                    f"00{day}02": {"return_open2close": 1.0, "return_close2close": 1.0, "next_pctChg": 1.0},
                })
            # universe 全覆盖（排除无基准 note 干扰）
            uni = {f"1{day}0{i}": {"return_open2close": 1.0, "return_close2close": 1.0, "next_pctChg": 1.0}
                   for i in range(5)}
            record_universe_returns(date, uni)

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.settled_count == 10
        assert result.total_recommendations == 50
        assert "覆盖低" in result.note

    def test_not_validated_lift_below_2x_with_n_ge_30(self, fresh_db):
        """§44 60日复验窗口：n>=30 + lift<2x → 未 validated（不阻断接入跑通，60日后复验）。"""
        for day in range(35):  # 35 天，每天 1 pick → s_settled=35>=30（非探索性）
            date = f"2026-08-{day:02d}" if day < 31 else f"2026-09-{day-30:02d}"
            recs = [DailyRecommendation(date, f"00{day:03d}", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            # picks 80% 胜率（day%5==0 输）
            r = 2.0 if day % 5 != 0 else -1.0
            record_actual_returns(date, {
                f"00{day:03d}": {"return_open2close": r, "return_close2close": r, "next_pctChg": r},
            })
            # universe 也 80%（4/5 赢）→ lift 1.0x 未 validated
            uni = {}
            for i in range(5):
                win = i != 0
                rr = 2.0 if win else -1.0
                uni[f"1{day}{i}"] = {"return_open2close": rr, "return_close2close": rr, "next_pctChg": rr}
            record_universe_returns(date, uni)

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.settled_count >= 30  # 非探索性
        assert result.is_exploratory is False
        assert result.lift < 2.0  # lift 1.0x
        assert result.passed is False  # passed 逻辑不变（lift<2 仍 False）
        assert result.validation_status == "未 validated"  # n>=30 + lift<2 → 未 validated（非探索性）
        assert "噪声" in result.note or "重叠" in result.note

    def test_lift_below_1_hard_floor(self, fresh_db):
        """§44 硬底线：n>=30 + lift<1 → 劣于随机（移除/权重0，不保留跑通）。"""
        for day in range(35):  # 35 天，每天 1 pick → s_settled=35>=30（非探索性）
            date = f"2026-08-{day:02d}" if day < 31 else f"2026-09-{day-30:02d}"
            recs = [DailyRecommendation(date, f"00{day:03d}", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            # picks 40% 胜率（day%5 ∈ {0,1} 赢 → 2/5=40%）
            r = 2.0 if day % 5 < 2 else -1.0
            record_actual_returns(date, {
                f"00{day:03d}": {"return_open2close": r, "return_close2close": r, "next_pctChg": r},
            })
            # universe 60% 胜率（3/5 赢）→ lift = 40/60 = 0.667 <1（劣于随机）
            uni = {}
            for i in range(5):
                win = i < 3
                rr = 2.0 if win else -1.0
                uni[f"1{day}{i}"] = {"return_open2close": rr, "return_close2close": rr, "next_pctChg": rr}
            record_universe_returns(date, uni)

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.settled_count >= 30  # 非探索性
        assert result.is_exploratory is False
        assert result.lift < 1.0  # lift=40/60=0.667<1（劣于随机）
        assert result.passed is False
        assert result.validation_status == "劣于随机"  # lift<1 硬底线
        assert "硬底线" in result.note or "劣于随机" in result.note

    def test_lift_below_1_but_exploratory_still_wins(self, fresh_db):
        """§44 优先级：n<30 + lift<1 → 探索性（非劣于随机，样本不足无法定论）。"""
        for day in range(25):  # 25 天，每天 1 pick → s_settled=25<30（探索性）
            date = f"2026-08-{day:02d}"
            recs = [DailyRecommendation(date, f"00{day:03d}", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            # picks 40% 胜率（day%5 ∈ {0,1} 赢 → 2/5=40%）
            r = 2.0 if day % 5 < 2 else -1.0
            record_actual_returns(date, {
                f"00{day:03d}": {"return_open2close": r, "return_close2close": r, "next_pctChg": r},
            })
            # universe 60% 胜率（3/5 赢）→ lift=40/60=0.667<1
            uni = {}
            for i in range(5):
                win = i < 3
                rr = 2.0 if win else -1.0
                uni[f"1{day}{i}"] = {"return_open2close": rr, "return_close2close": rr, "next_pctChg": rr}
            record_universe_returns(date, uni)

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        assert result.settled_count < 30  # 探索性
        assert result.is_exploratory is True
        assert result.lift < 1.0  # lift<1 但 n<30
        assert result.validation_status == "探索性"  # 探索性优先，非劣于随机
