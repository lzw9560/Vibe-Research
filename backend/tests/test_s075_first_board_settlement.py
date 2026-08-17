# -*- coding: utf-8 -*-
"""S075 首板流 Phase 4 结算+验证单测（tasks.md 060-062）。

覆盖：
- 060 盈亏归因：settle_pnl / calc_target_return / calc_position_return
    - 盈利归因（exit>entry）
    - 亏损归因（exit<entry）
    - 交易成本 0.4% 扣除
    - entry/exit 为 0 或缺失 → 返 0.0 防除零
    - 标的收益口径（T+1 close vs T open）
    - 持仓收益口径（entry→exit）
- 061 成本模型：apply_transaction_cost
    - 扣 0.4% 成本
    - 亏损时成本加重亏损
    - 零收益扣成本后为负
- 062 lift 四态 + 端到端：judge_lift_four_states / run_first_board_settlement
    - validated（lift≥2.0 AND n≥30）
    - 未 validated（1.0≤lift<2.0 AND n≥30）
    - 探索性（n<30 优先于 lift）
    - 劣于随机（lift<1.0）
    - 边界 lift=2.0 / lift=1.0
    - 端到端返回结构完整
    - t1_data=None 降级

mock 模式（参考 test_forward_test.py / test_s075_first_board_market_env.py）：
- forward_test DB 用 tmp_path 隔离：monkeypatch forward_test._DB + 调 _ensure_table()
- 纯 mock 无网络。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


# =========================================================================
# DB 隔离 fixture（参考 test_forward_test.py:28-34）
# =========================================================================

@pytest.fixture
def fresh_ft_db(tmp_path, monkeypatch):
    """每个测试用临时 forward_test DB 隔离。

    monkeypatch strategies.forward_test._DB 到 tmp_path，再调 _ensure_table 建表。
    """
    from strategies import forward_test as ft
    db_path = tmp_path / "test_first_board_settlement.db"
    monkeypatch.setattr("strategies.forward_test._DB", str(db_path))
    ft._ensure_table()
    return str(db_path)


# =========================================================================
# 060 盈亏归因
# =========================================================================

class TestSettlePnl:
    """060：测试 settle_pnl（T+1 盘后盈亏归因）。"""

    def test_positive_return(self):
        """盈利归因：exit>entry → return_pct 正。

        entry=10.0, exit=10.50 → return_pct=5.0, net=4.6（扣 0.4%）
        """
        from strategies.first_board_settlement import settle_pnl
        s = settle_pnl({"code": "001358", "total": 63.4}, 10.50, 10.0)
        assert s["code"] == "001358"
        assert s["return_pct"] == 5.0
        assert s["net_return_pct"] == 4.6  # 5.0 - 0.4
        assert s["cost_pct"] == 0.4
        assert s["total_score"] == 63.4
        assert s["hold_days"] == 1  # T+1 必卖

    def test_negative_return(self):
        """亏损归因：exit<entry → return_pct 负，成本加重亏损。

        entry=10.0, exit=9.70 → return_pct=-3.0, net=-3.4
        """
        from strategies.first_board_settlement import settle_pnl
        s = settle_pnl({"code": "001358", "total": 63.4}, 9.70, 10.0)
        assert s["return_pct"] == -3.0
        assert s["net_return_pct"] == -3.4  # -3.0 - 0.4

    def test_transaction_cost_deducted(self):
        """交易成本 0.4% 扣除：return_pct=2.0 → net=1.6。"""
        from strategies.first_board_settlement import settle_pnl
        # entry=10.0, exit=10.20 → return_pct=2.0
        s = settle_pnl({"code": "X", "total": 50.0}, 10.20, 10.0)
        assert s["return_pct"] == 2.0
        assert s["net_return_pct"] == 1.6  # 2.0 - 0.4
        assert s["cost_pct"] == 0.4

    def test_zero_prices_returns_zero(self):
        """entry/exit 为 0 或缺失 → 返 0.0 防除零。"""
        from strategies.first_board_settlement import settle_pnl
        # entry=0 → 防除零
        s = settle_pnl({"code": "X", "total": 0.0}, 10.50, 0.0)
        assert s["return_pct"] == 0.0
        assert s["net_return_pct"] == -0.4  # 0.0 - 0.4
        # entry_price 为 0 → 结果 entry_price 字段为 0.0
        assert s["entry_price"] == 0.0

    def test_name_passthrough(self):
        """holding.name 透传到结果。"""
        from strategies.first_board_settlement import settle_pnl
        s = settle_pnl({"code": "001358", "name": "测试股", "total": 70.0}, 10.50, 10.0)
        assert s["name"] == "测试股"

    def test_rounded_4_decimals(self):
        """收益 4 位小数（非整除场景）。"""
        from strategies.first_board_settlement import settle_pnl
        # entry=10.0, exit=10.333 → (0.333/10)*100 = 3.33
        s = settle_pnl({"code": "X", "total": 50.0}, 10.333, 10.0)
        # round(3.33, 4) = 3.33
        assert s["return_pct"] == 3.33


class TestCalcTargetReturn:
    """060：测试 calc_target_return（标的收益，排名用口径）。"""

    def test_target_return_calc(self):
        """标的收益 = (T+1 close - T open) / T open * 100。

        t_open=10.0, t1_close=10.30 → 3.0
        """
        from strategies.first_board_settlement import calc_target_return
        assert calc_target_return(10.0, 10.30) == 3.0

    def test_zero_open_returns_zero(self):
        """t_open=0 → 防除零返 0.0。"""
        from strategies.first_board_settlement import calc_target_return
        assert calc_target_return(0.0, 10.30) == 0.0
        assert calc_target_return(0, 10.30) == 0.0

    def test_negative_open_returns_zero(self):
        """t_open<0 → 防除零返 0.0。"""
        from strategies.first_board_settlement import calc_target_return
        assert calc_target_return(-1.0, 10.30) == 0.0

    def test_negative_return(self):
        """T+1 close < T open → 负收益。

        t_open=10.0, t1_close=9.80 → -2.0
        """
        from strategies.first_board_settlement import calc_target_return
        assert calc_target_return(10.0, 9.80) == -2.0


class TestCalcPositionReturn:
    """060：测试 calc_position_return（持仓收益，执行用口径）。"""

    def test_position_return_calc(self):
        """持仓收益 = (exit - entry) / entry * 100。

        entry=10.0, exit=10.50 → 5.0
        """
        from strategies.first_board_settlement import calc_position_return
        assert calc_position_return(10.0, 10.50) == 5.0

    def test_zero_entry_returns_zero(self):
        """entry=0 → 防除零返 0.0。"""
        from strategies.first_board_settlement import calc_position_return
        assert calc_position_return(0.0, 10.50) == 0.0
        assert calc_position_return(0, 10.50) == 0.0

    def test_negative_return(self):
        """exit<entry → 负收益。

        entry=10.0, exit=9.50 → -5.0
        """
        from strategies.first_board_settlement import calc_position_return
        assert calc_position_return(10.0, 9.50) == -5.0


# =========================================================================
# 061 成本模型
# =========================================================================

class TestApplyTransactionCost:
    """061：测试 apply_transaction_cost（扣 0.4% 固定成本）。"""

    def test_cost_deducted(self):
        """扣 0.4% 成本：gross=2.5 → net=2.1。"""
        from strategies.first_board_settlement import apply_transaction_cost
        assert apply_transaction_cost(2.5) == 2.1

    def test_negative_return_double_cost(self):
        """亏损时成本加重亏损：gross=-2.0 → net=-2.4。"""
        from strategies.first_board_settlement import apply_transaction_cost
        assert apply_transaction_cost(-2.0) == -2.4

    def test_zero_return(self):
        """零收益扣成本后为负：gross=0.0 → net=-0.4。"""
        from strategies.first_board_settlement import apply_transaction_cost
        assert apply_transaction_cost(0.0) == -0.4

    def test_large_positive_return(self):
        """大盈利扣成本：gross=10.0 → net=9.6。"""
        from strategies.first_board_settlement import apply_transaction_cost
        assert apply_transaction_cost(10.0) == 9.6

    def test_large_negative_return(self):
        """大亏损扣成本：gross=-10.0 → net=-10.4。"""
        from strategies.first_board_settlement import apply_transaction_cost
        assert apply_transaction_cost(-10.0) == -10.4

    def test_transaction_cost_pct_constant(self):
        """TRANSACTION_COST_PCT 常量为 0.004（0.4%）。"""
        from strategies.first_board_settlement import TRANSACTION_COST_PCT
        assert TRANSACTION_COST_PCT == 0.004


# =========================================================================
# 062 lift 四态 + 端到端
# =========================================================================

class TestJudgeLiftFourStates:
    """062：测试 judge_lift_four_states（§44 60 日复验窗口四态）。"""

    def test_validated(self):
        """lift≥2.0 AND n≥30 → validated。"""
        from strategies.first_board_settlement import judge_lift_four_states
        assert judge_lift_four_states(2.5, 35) == "validated"

    def test_not_validated(self):
        """1.0≤lift<2.0 AND n≥30 → 未 validated。"""
        from strategies.first_board_settlement import judge_lift_four_states
        assert judge_lift_four_states(1.5, 35) == "未 validated"

    def test_exploratory(self):
        """n<30 → 探索性（优先于 lift）。"""
        from strategies.first_board_settlement import judge_lift_four_states
        # lift=2.5 但 n=25 → 探索性（n<30 优先）
        assert judge_lift_four_states(2.5, 25) == "探索性"

    def test_worse_than_random(self):
        """lift<1.0 → 劣于随机（n≥30 时）。"""
        from strategies.first_board_settlement import judge_lift_four_states
        assert judge_lift_four_states(0.8, 35) == "劣于随机"

    def test_boundary_lift_2_0(self):
        """lift=2.0 边界 → validated（>=2.0）。"""
        from strategies.first_board_settlement import judge_lift_four_states
        assert judge_lift_four_states(2.0, 30) == "validated"

    def test_boundary_lift_1_0(self):
        """lift=1.0 边界 → 未 validated（1.0<=lift<2.0）。"""
        from strategies.first_board_settlement import judge_lift_four_states
        assert judge_lift_four_states(1.0, 30) == "未 validated"

    def test_exploratory_takes_priority_over_worse_than_random(self):
        """n<30 + lift<1.0 → 探索性（优先于劣于随机）。"""
        from strategies.first_board_settlement import judge_lift_four_states
        # lift=0.5（劣于随机）但 n=10（探索性）→ 探索性优先
        assert judge_lift_four_states(0.5, 10) == "探索性"

    def test_exploratory_n_zero(self):
        """n=0 → 探索性（无样本，非定论）。"""
        from strategies.first_board_settlement import judge_lift_four_states
        assert judge_lift_four_states(0.0, 0) == "探索性"

    def test_boundary_n_30_validated(self):
        """n=30 边界（==30，非<30）→ 不算探索性。"""
        from strategies.first_board_settlement import judge_lift_four_states
        # n=30, lift=2.0 → validated（n=30 不算探索性，n<30 才算）
        assert judge_lift_four_states(2.0, 30) == "validated"

    def test_boundary_n_29_exploratory(self):
        """n=29 边界（<30）→ 探索性。"""
        from strategies.first_board_settlement import judge_lift_four_states
        assert judge_lift_four_states(3.0, 29) == "探索性"


class TestRunFirstBoardSettlement:
    """062：端到端测试 run_first_board_settlement。"""

    def test_end_to_end_structure(self, fresh_ft_db):
        """端到端：mock holdings+candidates+t1_data，验证返回结构完整。

        holdings: 1 只已建仓（001358，entry=10.0）
        candidates: 2 只（001358 已建仓 + 002001 漏单）
        t1_data: 001358 t1_close=10.50，002001 t1_open=10.0/t1_close=10.30
        预期：
        - settled: 1 条（001358 盈亏归因）
        - missed: 1 条（002001 漏单对账）
        - forward_test_recorded: 2（picks 写入）
        - forward_test_summary: dict 含 validation_status 等
        - verdict: str
        """
        from strategies.first_board_settlement import run_first_board_settlement

        signal_date = "20260818"
        holdings = [
            {"code": "001358", "name": "测试股A", "total": 63.4, "entry_price": 10.0},
        ]
        candidates = [
            {"code": "001358", "name": "测试股A", "total": 63.4},
            {"code": "002001", "name": "测试股B", "total": 55.0},
        ]
        t1_data = {
            "001358": {
                "return_open2close": 5.0,
                "t1_close": 10.50,
                "entry_price": 10.0,
            },
            "002001": {
                "return_open2close": 3.0,
                "t1_open": 10.0,
                "t1_close": 10.30,
            },
        }

        result = run_first_board_settlement(signal_date, holdings, candidates, t1_data)

        # 结构完整
        assert set(result.keys()) == {
            "settled", "missed", "forward_test_recorded",
            "forward_test_summary", "verdict",
        }

        # settled: 1 条（001358）
        assert len(result["settled"]) == 1
        s = result["settled"][0]
        assert s["code"] == "001358"
        assert s["return_pct"] == 5.0  # (10.50-10.0)/10.0*100
        assert s["net_return_pct"] == 4.6  # 5.0 - 0.4
        assert s["hold_days"] == 1

        # missed: 1 条（002001）
        assert len(result["missed"]) == 1
        m = result["missed"][0]
        assert m["code"] == "002001"
        assert m["missed"] is True
        assert m["return_pct"] == 3.0  # (10.30-10.0)/10.0*100

        # forward_test_recorded: 2（picks 写入）
        assert result["forward_test_recorded"] == 2

        # forward_test_summary: dict 含 validation_status
        summary = result["forward_test_summary"]
        assert "validation_status" in summary
        assert "lift" in summary
        assert "note" in summary
        assert "首板流" in summary["note"]

        # verdict: str
        assert isinstance(result["verdict"], str)
        assert len(result["verdict"]) > 0

    def test_t1_data_none_degraded(self, fresh_ft_db):
        """t1_data=None 降级：settled/missed 空，picks 仍写入。

        t1_data=None →
        - settled=[] （无 T+1 数据无法归因）
        - missed=[] （无 t1_open/t1_close 无法算漏单收益）
        - forward_test_recorded>0 （picks 仍写入，次日再回填）
        - verdict 含"降级"
        """
        from strategies.first_board_settlement import run_first_board_settlement

        signal_date = "20260818"
        holdings = [
            {"code": "001358", "name": "测试股A", "total": 63.4, "entry_price": 10.0},
        ]
        candidates = [
            {"code": "001358", "name": "测试股A", "total": 63.4},
            {"code": "002001", "name": "测试股B", "total": 55.0},
        ]

        result = run_first_board_settlement(signal_date, holdings, candidates, None)

        # 降级：settled/missed 空
        assert result["settled"] == []
        assert result["missed"] == []
        # picks 仍写入（forward_test 不依赖 t1_data）
        assert result["forward_test_recorded"] == 2
        # verdict 含"降级"
        assert "降级" in result["verdict"]

    def test_holdings_use_exit_price_override(self, fresh_ft_db):
        """holding.exit_price 优先于 t1_data.t1_close。

        holding.exit_price=10.80, t1_data.t1_close=10.50 → exit=10.80（用 holding）
        """
        from strategies.first_board_settlement import run_first_board_settlement

        holdings = [
            {
                "code": "001358", "name": "X", "total": 60.0,
                "entry_price": 10.0, "exit_price": 10.80,
            },
        ]
        candidates = [{"code": "001358", "name": "X", "total": 60.0}]
        t1_data = {
            "001358": {"t1_close": 10.50, "entry_price": 10.0},
        }

        result = run_first_board_settlement("20260818", holdings, candidates, t1_data)
        # exit_price 用 holding 的 10.80，不是 t1_close 10.50
        s = result["settled"][0]
        assert s["exit_price"] == 10.80
        # return_pct = (10.80-10.0)/10.0*100 = 8.0
        assert s["return_pct"] == 8.0

    def test_missing_t1_data_for_holding_skipped(self, fresh_ft_db):
        """holding 的 code 在 t1_data 中缺失 → 跳过该持仓归因（不崩）。"""
        from strategies.first_board_settlement import run_first_board_settlement

        holdings = [
            {"code": "001358", "name": "X", "total": 60.0, "entry_price": 10.0},
            {"code": "002001", "name": "Y", "total": 55.0, "entry_price": 10.0},
        ]
        candidates = [
            {"code": "001358", "name": "X", "total": 60.0},
            {"code": "002001", "name": "Y", "total": 55.0},
        ]
        # 只给 001358 的 t1_data，002001 缺失
        t1_data = {
            "001358": {"t1_close": 10.50, "entry_price": 10.0},
        }

        result = run_first_board_settlement("20260818", holdings, candidates, t1_data)
        # 只 001358 归因，002001 跳过
        assert len(result["settled"]) == 1
        assert result["settled"][0]["code"] == "001358"

    def test_forward_test_db_isolation(self, fresh_ft_db, tmp_path):
        """forward_test DB 隔离：写入的 picks 在临时 DB，不影响生产库。"""
        import sqlite3
        from strategies.first_board_settlement import run_first_board_settlement
        from strategies import forward_test as ft

        signal_date = "20260818"
        candidates = [{"code": "001358", "name": "X", "total": 60.0}]
        result = run_first_board_settlement(signal_date, [], candidates, None)

        # 验证写入临时 DB（fresh_ft_db），不在生产 GENE_SCORES_DB_PATH
        conn = sqlite3.connect(fresh_ft_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM forward_test_records WHERE signal_date = ?",
            (signal_date,),
        ).fetchone()[0]
        conn.close()
        assert count == 1  # 1 只 pick 写入
        assert result["forward_test_recorded"] == 1

    def test_record_first_board_signals_strategy_code(self, fresh_ft_db):
        """record_first_board_signals 写入 strategy_code='first_board'。"""
        import sqlite3
        from strategies.first_board_settlement import record_first_board_signals

        candidates = [
            {"code": "001358", "name": "X", "total": 63.4},
            {"code": "002001", "name": "Y", "total": 55.0},
        ]
        n = record_first_board_signals("20260818", candidates, weather_state="green")
        assert n == 2

        # 验证 strategy_code / strategy_score 字段
        conn = sqlite3.connect(fresh_ft_db)
        rows = conn.execute(
            "SELECT code, strategy_code, strategy_score, weather_state "
            "FROM forward_test_records WHERE signal_date = '20260818'"
        ).fetchall()
        conn.close()
        assert len(rows) == 2
        for code, sc, ss, ws in rows:
            assert sc == "first_board"
            assert ws == "green"
            if code == "001358":
                assert ss == 63.4
            elif code == "002001":
                assert ss == 55.0

    def test_settle_first_board_t1_backfills(self, fresh_ft_db):
        """settle_first_board_t1 回填 T+1 收益到 forward_test_records。"""
        import sqlite3
        from strategies.first_board_settlement import (
            record_first_board_signals,
            settle_first_board_t1,
        )

        # 先写 picks
        candidates = [{"code": "001358", "name": "X", "total": 60.0}]
        record_first_board_signals("20260818", candidates)

        # 回填 T+1 收益
        t1_data = {
            "001358": {
                "return_open2close": 5.0,
                "return_close2close": 4.8,
                "next_pctChg": 5.0,
            },
        }
        n = settle_first_board_t1("20260818", t1_data)
        assert n == 1

        # 验证回填
        conn = sqlite3.connect(fresh_ft_db)
        row = conn.execute(
            "SELECT return_open2close, is_win FROM forward_test_records "
            "WHERE signal_date = '20260818' AND code = '001358'"
        ).fetchone()
        conn.close()
        assert row[0] == 5.0
        assert row[1] == 1  # 5.0>0 → is_win=1

    def test_empty_candidates_returns_zeros(self, fresh_ft_db):
        """空 candidates → forward_test_recorded=0, settled=[], missed=[]。"""
        from strategies.first_board_settlement import run_first_board_settlement

        result = run_first_board_settlement("20260818", [], [], None)
        assert result["forward_test_recorded"] == 0
        assert result["settled"] == []
        assert result["missed"] == []
        assert "降级" in result["verdict"]

    def test_verdict_worse_than_random(self, fresh_ft_db):
        """verdict: lift<1.0 + n≥30 → "§44 硬底线触发"。

        构造：写入 30+ 条 picks，胜率<随机基准 → lift<1.0。
        但 random_settled=0 时 lift=0（无法算），validation_status=探索性（n<30）或
        劣于随机（n≥30 但 lift<1）。
        实际 forward_test 在 random_settled=0 时 lift=0.0 → lift<1.0 → 劣于随机
        （n≥30 时），或探索性（n<30 时）。
        本测试用 monkeypatch get_forward_test_summary 直接构造 lift<1.0 + n≥35 场景。
        """
        from unittest.mock import patch
        from strategies.forward_test import ForwardTestResult
        from strategies import first_board_settlement as m

        # 构造 lift=0.8, settled_count=35 → 劣于随机
        fake_result = ForwardTestResult(
            total_days=35,
            total_recommendations=35,
            settled_count=35,
            win_count=10,
            win_rate=28.57,
            avg_return=1.0,
            random_settled=35,
            random_win_count=35,
            random_baseline_win_rate=35.71,
            lift=0.8,
            is_exploratory=False,
            passed=False,
            consecutive_loss=0,
            note="",
            validation_status="劣于随机",
        )
        with patch.object(
            m, "get_forward_test_summary", return_value=fake_result
        ):
            result = m.run_first_board_settlement(
                "20260818",
                [{"code": "001358", "total": 60.0, "entry_price": 10.0}],
                [{"code": "001358", "total": 60.0}],
                {"001358": {"t1_close": 10.50, "entry_price": 10.0}},
            )
        assert "硬底线" in result["verdict"]
        assert result["forward_test_summary"]["validation_status"] == "劣于随机"

    def test_verdict_validated(self, fresh_ft_db):
        """verdict: lift≥2.0 + n≥30 → "§44 validated"。

        用 monkeypatch get_forward_test_summary 构造 validated 场景。
        """
        from unittest.mock import patch
        from strategies.forward_test import ForwardTestResult
        from strategies import first_board_settlement as m

        fake_result = ForwardTestResult(
            total_days=35,
            total_recommendations=35,
            settled_count=35,
            win_count=25,
            win_rate=71.43,
            avg_return=3.0,
            random_settled=35,
            random_win_count=10,
            random_baseline_win_rate=28.57,
            lift=2.5,
            is_exploratory=False,
            passed=True,
            consecutive_loss=0,
            note="",
            validation_status="validated",
        )
        with patch.object(
            m, "get_forward_test_summary", return_value=fake_result
        ):
            result = m.run_first_board_settlement(
                "20260818",
                [{"code": "001358", "total": 60.0, "entry_price": 10.0}],
                [{"code": "001358", "total": 60.0}],
                {"001358": {"t1_close": 10.50, "entry_price": 10.0}},
            )
        assert "validated" in result["verdict"]
        assert result["forward_test_summary"]["validation_status"] == "validated"

    def test_verdict_exploratory(self, fresh_ft_db):
        """verdict: n<30 → "探索性"。

        用 monkeypatch get_forward_test_summary 构造探索性场景。
        """
        from unittest.mock import patch
        from strategies.forward_test import ForwardTestResult
        from strategies import first_board_settlement as m

        fake_result = ForwardTestResult(
            total_days=5,
            total_recommendations=5,
            settled_count=5,
            win_count=4,
            win_rate=80.0,
            avg_return=3.0,
            random_settled=5,
            random_win_count=1,
            random_baseline_win_rate=20.0,
            lift=4.0,
            is_exploratory=True,
            passed=False,
            consecutive_loss=0,
            note="",
            validation_status="探索性",
        )
        with patch.object(
            m, "get_forward_test_summary", return_value=fake_result
        ):
            result = m.run_first_board_settlement(
                "20260818",
                [{"code": "001358", "total": 60.0, "entry_price": 10.0}],
                [{"code": "001358", "total": 60.0}],
                {"001358": {"t1_close": 10.50, "entry_price": 10.0}},
            )
        assert "探索性" in result["verdict"]
        assert result["forward_test_summary"]["validation_status"] == "探索性"

    def test_verdict_not_validated(self, fresh_ft_db):
        """verdict: 1.0≤lift<2.0 + n≥30 → "未 validated"。

        用 monkeypatch get_forward_test_summary 构造未 validated 场景。
        """
        from unittest.mock import patch
        from strategies.forward_test import ForwardTestResult
        from strategies import first_board_settlement as m

        fake_result = ForwardTestResult(
            total_days=35,
            total_recommendations=35,
            settled_count=35,
            win_count=18,
            win_rate=51.43,
            avg_return=1.0,
            random_settled=35,
            random_win_count=24,
            random_baseline_win_rate=34.29,
            lift=1.5,
            is_exploratory=False,
            passed=False,
            consecutive_loss=0,
            note="",
            validation_status="未 validated",
        )
        with patch.object(
            m, "get_forward_test_summary", return_value=fake_result
        ):
            result = m.run_first_board_settlement(
                "20260818",
                [{"code": "001358", "total": 60.0, "entry_price": 10.0}],
                [{"code": "001358", "total": 60.0}],
                {"001358": {"t1_close": 10.50, "entry_price": 10.0}},
            )
        assert "未 validated" in result["verdict"]
        assert result["forward_test_summary"]["validation_status"] == "未 validated"


# =========================================================================
# settle_missed 补充测试
# =========================================================================

class TestSettleMissed:
    """settle_missed 漏单对账补充测试。"""

    def test_missed_basic(self):
        """漏单对账基本场景。"""
        from strategies.first_board_settlement import settle_missed
        candidates = [
            {"code": "001358", "name": "X", "total": 60.0},
            {"code": "002001", "name": "Y", "total": 55.0},
        ]
        t1_open = {"001358": 10.0, "002001": 10.0}
        t1_close = {"001358": 10.30, "002001": 9.80}
        out = settle_missed(candidates, t1_open, t1_close)
        assert len(out) == 2
        assert out[0]["code"] == "001358"
        assert out[0]["return_pct"] == 3.0  # (10.30-10.0)/10.0*100
        assert out[0]["missed"] is True
        assert out[1]["code"] == "002001"
        assert out[1]["return_pct"] == -2.0  # (9.80-10.0)/10.0*100

    def test_missing_t1_data_skipped(self):
        """T+1 数据缺失的 code 跳过（不臆造）。"""
        from strategies.first_board_settlement import settle_missed
        candidates = [
            {"code": "001358", "name": "X", "total": 60.0},
            {"code": "002001", "name": "Y", "total": 55.0},  # t1 数据缺失
        ]
        t1_open = {"001358": 10.0}
        t1_close = {"001358": 10.30}
        out = settle_missed(candidates, t1_open, t1_close)
        assert len(out) == 1
        assert out[0]["code"] == "001358"

    def test_zero_t1_open_skipped(self):
        """t1_open=0 的 code 跳过（防除零）。"""
        from strategies.first_board_settlement import settle_missed
        candidates = [{"code": "001358", "name": "X", "total": 60.0}]
        t1_open = {"001358": 0.0}
        t1_close = {"001358": 10.30}
        out = settle_missed(candidates, t1_open, t1_close)
        assert out == []

    def test_empty_candidates_returns_empty(self):
        """空 candidates 返空 list。"""
        from strategies.first_board_settlement import settle_missed
        out = settle_missed([], {}, {})
        assert out == []
