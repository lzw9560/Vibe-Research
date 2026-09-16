# -*- coding: utf-8 -*-
"""S175 T8 — PaperPortfolio thin read-only wrapper 测试（R10，R9 消费非空转 SH1）。

委托 trade_journal.get_drawdown_status + drawdown_breaker.full_status/final_size，
不存独立 state（S088 重算范式）。R9 recommendation_engine 读 equity() 作 floor sizing。
"""
import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from engine.trade_journal import TradeJournal, JournalRecord, DEFAULT_INITIAL_CAPITAL  # noqa: E402


class TestPaperPortfolio:
    def test_equity_returns_initial_when_empty(self, tmp_path):
        from engine.paper_portfolio import PaperPortfolio
        journal = TradeJournal(db_path=tmp_path / "pp.db")
        pp = PaperPortfolio(journal=journal)
        assert pp.equity() == DEFAULT_INITIAL_CAPITAL

    def test_equity_includes_realized_pnl(self, tmp_path):
        """有 breakout realized net_pnl=100 → equity = initial + 100（重算）。"""
        from engine.paper_portfolio import PaperPortfolio
        journal = TradeJournal(db_path=tmp_path / "pp.db")
        journal.insert(JournalRecord.create(
            arm="breakout", stock_code="000001", entry_price=10.0, entry_date="2026-01-15",
            exit_price=11.0, exit_date="2026-01-19", exit_reason="max_hold",
            net_pnl=100.0, is_realized=1,
        ))
        pp = PaperPortfolio(journal=journal)
        assert pp.equity() == pytest.approx(DEFAULT_INITIAL_CAPITAL + 100.0, abs=0.01)

    def test_no_independent_state_recompute(self, tmp_path):
        """不存独立 state——插记录后 equity 重算反映（S088 非缓存）。"""
        from engine.paper_portfolio import PaperPortfolio
        journal = TradeJournal(db_path=tmp_path / "pp.db")
        pp = PaperPortfolio(journal=journal)
        e1 = pp.equity()
        journal.insert(JournalRecord.create(
            arm="breakout", stock_code="000001", entry_price=10.0, entry_date="2026-01-15",
            net_pnl=50.0, is_realized=1,
        ))
        e2 = pp.equity()
        assert e2 == pytest.approx(e1 + 50.0, abs=0.01)  # 重算反映新记录

    def test_drawdown_status_delegates_to_breaker(self, tmp_path):
        from engine.paper_portfolio import PaperPortfolio
        journal = TradeJournal(db_path=tmp_path / "pp.db")
        pp = PaperPortfolio(journal=journal)
        status = pp.drawdown_status()
        assert isinstance(status, dict)

    def test_final_size_delegates_to_breaker(self, tmp_path):
        from engine.paper_portfolio import PaperPortfolio
        journal = TradeJournal(db_path=tmp_path / "pp.db")
        pp = PaperPortfolio(journal=journal)
        # final_size(arm, arm_size, lift_multiplier=1.0) 委托 drawdown_breaker.final_size
        fs = pp.final_size("breakout", 10000.0, lift_multiplier=1.0)
        assert isinstance(fs, float)

    def test_equity_per_arm(self, tmp_path):
        """equity(arm='breakout') → per-arm 权益（只 cum breakout realized）。"""
        from engine.paper_portfolio import PaperPortfolio
        journal = TradeJournal(db_path=tmp_path / "pp.db")
        journal.insert(JournalRecord.create(
            arm="breakout", stock_code="000001", entry_price=10.0, entry_date="2026-01-15",
            net_pnl=100.0, is_realized=1,
        ))
        journal.insert(JournalRecord.create(
            arm="floor", stock_code="512890", entry_price=1.0, entry_date="2026-01-15",
            net_pnl=30.0, is_realized=1,  # floor 通常 is_realized=0，但测试 per-arm 隔离
        ))
        pp = PaperPortfolio(journal=journal)
        # portfolio 级含两臂
        assert pp.equity() == pytest.approx(DEFAULT_INITIAL_CAPITAL + 130.0, abs=0.01)
        # breakout per-arm 只含 breakout
        assert pp.equity(arm="breakout") == pytest.approx(DEFAULT_INITIAL_CAPITAL + 100.0, abs=0.01)


class TestT5BayesianFloor:
    """T5（S209 §4）：bayesian_arm_size <30 decided trades → EXPLORATORY_ARM_FLOOR=0.05 不归零。

    原返 0.0 = 死臂，与 exploratory PAPER 定位矛盾（探索性臂保留最小仓位）。
    """

    def test_no_trades_returns_floor(self, tmp_path):
        """空 journal（0 trades <30）→ 0.05 floor（非 0.0 死臂）。"""
        from engine.paper_portfolio import PaperPortfolio, EXPLORATORY_ARM_FLOOR
        journal = TradeJournal(db_path=tmp_path / "t5.db")
        pp = PaperPortfolio(journal=journal)
        assert pp.bayesian_arm_size("breakout") == EXPLORATORY_ARM_FLOOR

    def test_few_trades_returns_floor(self, tmp_path, monkeypatch):
        """10 decided trades（<30）→ 0.05 floor。"""
        from engine.paper_portfolio import PaperPortfolio, EXPLORATORY_ARM_FLOOR
        journal = TradeJournal(db_path=tmp_path / "t5.db")
        pp = PaperPortfolio(journal=journal)
        monkeypatch.setattr(journal, "query_winrate_trends", lambda arm=None: [{
            "n_decided": 10, "win_rate": 0.5,
        }])
        assert pp.bayesian_arm_size("breakout") == EXPLORATORY_ARM_FLOOR

    def test_many_trades_uses_posterior(self, tmp_path, monkeypatch):
        """≥30 decided trades → Beta 后验下 5% 分位（非 floor，数据累积仓位增长）。"""
        from engine.paper_portfolio import PaperPortfolio, EXPLORATORY_ARM_FLOOR
        journal = TradeJournal(db_path=tmp_path / "t5.db")
        pp = PaperPortfolio(journal=journal)
        # 100 decided, 60% winrate → 后验 lower > 0.05（数据足够，跳出 floor）
        monkeypatch.setattr(journal, "query_winrate_trends", lambda arm=None: [{
            "n_decided": 100, "win_rate": 0.6,
        }])
        size = pp.bayesian_arm_size("breakout")
        assert size > EXPLORATORY_ARM_FLOOR, f"100 trades 60% win 应 > floor，got {size}"
        assert size < 1.0, f"下 5% 分位应保守 <1.0，got {size}"
