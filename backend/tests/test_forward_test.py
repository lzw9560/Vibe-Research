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


# ===========================================================================
# S144 Tier 1：unbuyable 排除（R2/R3）+ open2next_close 双报（R5）
# ===========================================================================

class TestS144UnbuyableExclusion:
    """R2/R3：一字板（unbuyable）pick/universe 排除出 settled/wins 分母。"""

    def test_unbuyable_pick_excluded_from_buyable_only(self, fresh_db):
        """R2：unbuyable=True 的 pick → is_win=NULL + is_unbuyable=1，排除出 s_settled/s_wins（buyable-only）。"""
        date = "2026-08-13"
        recs = [
            DailyRecommendation(date, "000001", "可买A", "first_plate", 70.0),
            DailyRecommendation(date, "000002", "一字板B", "first_plate", 75.0),  # unbuyable
        ]
        record_daily_recommendations(date, recs)
        record_actual_returns(date, {
            "000001": {"return_open2close": 2.0, "return_close2close": 2.0, "next_pctChg": 2.0,
                       "is_unbuyable": False},
            "000002": {"return_open2close": 0.0, "return_close2close": 0.0, "next_pctChg": 10.0,
                       "is_unbuyable": True},  # 一字板涨停
        })

        daily = get_daily_recommendations(date)
        by_code = {r["code"]: r for r in daily}
        # 可买 pick：is_win=1
        assert by_code["000001"]["is_win"] == 1
        assert by_code["000001"]["is_unbuyable"] == 0
        # 一字板 pick：is_win=NULL（排除非 0）+ is_unbuyable=1
        assert by_code["000002"]["is_win"] is None
        assert by_code["000002"]["is_unbuyable"] == 1

        # summary：buyable-only s_settled=1（排除 unbuyable），s_wins=1
        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=5)
        assert result.settled_count == 1  # 排除 unbuyable
        assert result.win_count == 1

    def test_unbuyable_universe_excluded(self, fresh_db):
        """R3：universe 的 unbuyable 同样排除——分母不抬高。"""
        date = "2026-08-13"
        recs = [DailyRecommendation(date, "000001", "可买", "first_plate", 70.0)]
        record_daily_recommendations(date, recs)
        record_actual_returns(date, {
            "000001": {"return_open2close": 2.0, "return_close2close": 2.0, "next_pctChg": 2.0,
                       "is_unbuyable": False},
        })
        record_universe_returns(date, {
            "100001": {"return_open2close": 2.0, "return_close2close": 2.0, "next_pctChg": 2.0,
                       "is_unbuyable": False},
            "100002": {"return_open2close": 0.0, "return_close2close": 0.0, "next_pctChg": 10.0,
                       "is_unbuyable": True},  # universe 一字板
        })

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=5)
        # universe buyable-only：settled=1（排除 unbuyable 100002）
        assert result.random_settled == 1

    def test_consecutive_loss_excludes_unbuyable(self, fresh_db):
        """R2：consecutive_loss 查询的 is_unbuyable=0 filter 是承重的——
        unbuyable(is_win=NULL) 被 filter 排除；无 filter 则 NULL 错误中断连亏计数。

        构造 4 records（DESC by date: D4 loss, D3 loss, D2 unbuyable(NULL), D1 loss）：
        - with filter: recent=[D4,D3,D1] 全 loss → cl=3（D2 排除）
        - without filter: recent=[D4,D3,D2(NULL),D1] → NULL 错误中断 → cl=2
        """
        for day, unbuyable in [(1, False), (2, True), (3, False), (4, False)]:
            date = f"2026-08-{day:02d}"
            rec = DailyRecommendation(date, f"0000{day}", "X", "first_plate", 70.0)
            record_daily_recommendations(date, [rec])
            o2c = 0.0 if unbuyable else -1.0  # unbuyable o2c=0（一字板），buyable loss o2c=-1
            record_actual_returns(date, {
                f"0000{day}": {"return_open2close": o2c, "return_close2close": o2c,
                               "next_pctChg": 10.0 if unbuyable else -1.0,
                               "is_unbuyable": unbuyable},
            })
        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=3)
        # filter 排除 unbuyable(D2) → recent=[D4,D3,D1] 全 loss → cl=3（无 filter 会 cl=2）
        assert result.consecutive_loss == 3

    def test_buyable_only_lift_not_polluted_by_unbuyable(self, fresh_db):
        """R2/R3 合：一字板污染消除后 lift 不被分子压低/分母抬高。"""
        for day in range(25):
            date = f"2026-08-{day+1:02d}"
            recs = [DailyRecommendation(date, f"00{day}01", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            # pick：可买，80% 胜率
            r = 2.0 if day % 5 != 0 else -1.0
            record_actual_returns(date, {
                f"00{day}01": {"return_open2close": r, "return_close2close": r, "next_pctChg": r,
                               "is_unbuyable": False},
            })
            # universe：1 可买 + 1 一字板（一字板 o2c=0 不算 win，原口径会抬高基准 winrate）
            uni = {
                f"1{day}0a": {"return_open2close": 2.0, "return_close2close": 2.0, "next_pctChg": 2.0,
                              "is_unbuyable": False},
                f"1{day}0b": {"return_open2close": 0.0, "return_close2close": 0.0, "next_pctChg": 10.0,
                              "is_unbuyable": True},
            }
            record_universe_returns(date, uni)

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        # 一字板排除后：universe settled=25（非 50），buyable-only
        assert result.random_settled == 25
        # buyable-only picks settled=25（全可买），is_win=o2c fallback（未传 o2nc）→ 80% 胜率
        assert result.settled_count == 25
        # S144 A3：lift 双报——buyable-only 0.8x vs 原口径（含 unbuyable 污染）1.6x
        # 原口径：universe 含 25 一字板（o2c=0 不算 win）压低基准 winrate→50%→lift 虚高 1.6x
        # buyable-only：剔一字板→基准 100%→lift 0.8x（诚实更低，污染消除）
        assert result.lift == 0.8
        assert result.lift_unfiltered == 1.6
        # unbuyable 计数（picks 侧）= 0（本 fixture 只 universe 有 unbuyable；picks 全可买）
        assert result.unbuyable_count == 0


class TestS144Open2NextClose:
    """R5：return_open2next_close（T-open→T+1-close 可实现口径）双报。"""

    def test_is_win_uses_o2c_baseline_escape_hatch(self, fresh_db):
        """R5 escape hatch：is_win 仍用 o2c（T+0 基线，一致口径），不用 open2next_close 改 verdict。

        避免 mixed caliber（o2nc 对 settled + o2c 对 recent 混在一个 winrate）= §44 不可复现风险。
        o2nc（T+1 可实现）单独双报（win_rate_open2next_close），不改 is_win。
        """
        date = "2026-08-13"
        rec = DailyRecommendation(date, "000001", "测试", "first_plate", 70.0)
        record_daily_recommendations(date, [rec])
        # o2c<0 但 open2next_close>0 → is_win=0（用 o2c，不切 T+1）——escape hatch 保 verdict 一致
        record_actual_returns(date, {
            "000001": {
                "return_open2close": -1.0,       # T+0 intraday 亏
                "return_open2next_close": 3.0,   # T+1 可实现 赢
                "return_close2close": 2.0, "next_pctChg": 2.0,
                "is_unbuyable": False,
            },
        })
        daily = get_daily_recommendations(date)
        assert daily[0]["is_win"] == 0  # escape hatch：用 o2c（-1<0），不切 o2nc
        assert daily[0]["return_open2next_close"] == 3.0  # o2nc 仍记录供双报

    def test_is_win_falls_back_to_o2c_without_open2next_close(self, fresh_db):
        """R5：未提供 return_open2next_close（旧数据/first_board 路径）→ is_win 用 o2c 兼容。"""
        date = "2026-08-13"
        rec = DailyRecommendation(date, "000001", "测试", "first_plate", 70.0)
        record_daily_recommendations(date, [rec])
        record_actual_returns(date, {
            "000001": {"return_open2close": 2.5, "return_close2close": 3.0, "next_pctChg": 3.0},
            # 不传 open2next_close / is_unbuyable（向后兼容）
        })
        daily = get_daily_recommendations(date)
        assert daily[0]["is_win"] == 1  # o2c>0 fallback

    def test_dual_report_o2c_verdict_and_open2next_close_dual(self, fresh_db):
        """R5 escape hatch：verdict=win_rate 用 o2c（T+0 一致口径）；open2next_close（T+1 可实现）单独双报。

        o2c 全赢（T+0 100%），open2next_close 52%（T+1 更低）——双报可见 T+1 胜率降（用户预期），
        但 verdict 保 o2c 一致口径（切纯 T+1=Tier 2，避 mixed caliber §44 风险）。
        """
        for day in range(25):
            date = f"2026-08-{day+1:02d}"
            recs = [DailyRecommendation(date, f"00{day}01", "A", "first_plate", 70.0)]
            record_daily_recommendations(date, recs)
            # o2c 全赢（T+0 intraday），open2next_close 只在 day%2==0 赢（T+1 口径更差）
            o2c = 2.0
            o2nc = 2.0 if day % 2 == 0 else -1.0
            record_actual_returns(date, {
                f"00{day}01": {
                    "return_open2close": o2c, "return_open2next_close": o2nc,
                    "return_close2close": o2c, "next_pctChg": o2c, "is_unbuyable": False,
                },
            })
            uni = {f"1{day}0{i}": {"return_open2close": 1.0, "return_close2close": 1.0,
                                   "next_pctChg": 1.0, "is_unbuyable": False}
                   for i in range(5)}
            record_universe_returns(date, uni)

        result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
        # verdict = o2c 口径（escape hatch，一致）= 100%（25/25 全赢）
        assert result.win_rate == 100.0
        # open2next_close 双报（T+1 可实现）= 52%（13/25）——T+1 胜率降，可见但不改 verdict
        assert result.win_rate_open2next_close == 52.0
        assert result.o2nc_settled == 25


# ===========================================================================
# S086 R7：run_daily_forward_test 接 pool_item_map（涨停池→score_candidates）
# ===========================================================================

def test_run_daily_forward_test_passes_pool_item_map(monkeypatch):
    """S086 R7：run_daily_forward_test 取涨停池建 pool_item_map 传给 score_candidates。

    验证：fetch_zt_pool 的原始池（按 "c" 字段）建 {code: pool_item} 映射，
    作为第 5 个位置参传给 score_candidates（funnel_type 第 3，S094 T11 必填；供 storm_reversal fbt / R2 真实入场价）。
    fetch_zt_pool 失败 → 空 map 降级（A7 fallback），不阻断。
    """
    from strategies import forward_test as ft
    from limitup_screener.models import GeneScore

    gene = GeneScore(
        code="000001", name="X", total_score=70.0,
        factors={"封板率": 80, "涨停频次": 30, "次日溢价率": 50, "红盘率": 60, "炸板后溢价": 0},
        wilson_adjusted=70.0, qualify=True, high_gene=False,
        last_zt_dates=[], zt_count_250d=3, date="2026-08-18",
    )
    monkeypatch.setattr("limitup_screener.data.load_gene_scores", lambda d: [gene])

    # fetch_zt_pool 返回含 fbt 的涨停池（"c" 字段做 code）
    monkeypatch.setattr(
        "strategies.first_board_filter.fetch_zt_pool",
        lambda d: [{"c": "000001", "fbt": 93000, "p": 10.0, "lbc": 2, "n": "X"}],
    )

    captured: dict = {}

    def _fake_score(cands, weather, funnel_type, trade_date=None, pool_item_map=None):
        captured["pool_item_map"] = pool_item_map
        captured["n_cands"] = len(cands)
        return [{"code": "000001", "name": "X", "strategy_code": "first_plate",
                 "strategy_name": "首板", "strategy_score": 70, "score_breakdown": {}}]

    monkeypatch.setattr("strategies.strategy_funnel_registry.score_candidates", _fake_score)
    monkeypatch.setattr("strategies.calendar_factor.calendar_factor", lambda d: (1.0, ""))
    monkeypatch.setattr("strategies.forward_test.record_daily_recommendations", lambda d, recs: len(recs))
    monkeypatch.setattr("strategies.forward_test._record_universe_codes", lambda d, genes: None)

    r = ft.run_daily_forward_test("2026-08-18", "晴天")

    # pool_item_map 按 "c" 建，含完整 raw 池停池 dict（fbt/p/lbc 供战法取因子）
    assert captured["pool_item_map"] == {
        "000001": {"c": "000001", "fbt": 93000, "p": 10.0, "lbc": 2, "n": "X"},
    }
    assert captured["n_cands"] == 1
    assert r["recommendations"] == 1


def test_run_daily_forward_test_degrades_when_fetch_zt_pool_fails(monkeypatch):
    """S086 R7/A7：fetch_zt_pool 异常 → 空 pool_item_map 降级，score_candidates 仍被调用（A7 价格代理 fallback）。"""
    from strategies import forward_test as ft
    from limitup_screener.models import GeneScore

    gene = GeneScore(
        code="000001", name="X", total_score=70.0,
        factors={"封板率": 80, "涨停频次": 30, "次日溢价率": 50, "红盘率": 60, "炸板后溢价": 0},
        wilson_adjusted=70.0, qualify=True, high_gene=False,
        last_zt_dates=[], zt_count_250d=3, date="2026-08-18",
    )
    monkeypatch.setattr("limitup_screener.data.load_gene_scores", lambda d: [gene])

    def _boom(_d):
        raise RuntimeError("em_get 限流触发")
    monkeypatch.setattr("strategies.first_board_filter.fetch_zt_pool", _boom)

    captured: dict = {}

    def _fake_score(cands, weather, funnel_type, trade_date=None, pool_item_map=None):
        captured["pool_item_map"] = pool_item_map
        return []
    monkeypatch.setattr("strategies.strategy_funnel_registry.score_candidates", _fake_score)
    monkeypatch.setattr("strategies.calendar_factor.calendar_factor", lambda d: (1.0, ""))
    monkeypatch.setattr("strategies.forward_test.record_daily_recommendations", lambda d, recs: 0)
    monkeypatch.setattr("strategies.forward_test._record_universe_codes", lambda d, genes: None)

    ft.run_daily_forward_test("2026-08-18", "晴天")
    # 失败降级为空 map（不抛、不阻断；entry_price 走 A7 gene.total_score 代理）
    assert captured["pool_item_map"] == {}
