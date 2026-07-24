import unittest
from datetime import datetime

from risk.bomb_alert_system import BombAlertSystem, BombAlertRule, BombAlertResult
from risk.position_manager import PositionManager, PositionLimit, PositionSnapshot
from settlement.settlement_engine import SettlementEngine, SettlementInput


class TestBombAlertSystem(unittest.TestCase):
    def test_default_rule_exists(self):
        system = BombAlertSystem()
        assert len(system.rules) == 1
        assert system.rules[0].name == "default"

    def test_no_alert_when_drop_below_threshold(self):
        system = BombAlertSystem()
        # 150万 -> 200万，下跌 25%，未达 50% 阈值
        result = system.check("001", "测试", 1500000, 2000000)
        assert result.triggered is False
        assert result.alert is None

    def test_alert_when_drop_above_threshold(self):
        system = BombAlertSystem()
        # 100万 -> 200万，下跌 50%，达到阈值且封单额 >= 100万
        result = system.check("001", "测试", 1000000, 2000000)
        assert result.triggered is True
        assert result.alert is not None
        assert result.alert.code == "001"
        assert result.alert.name == "测试"
        assert result.alert.current_seal_amount == 1000000
        assert result.alert.seal_amount_change_5min == 1000000
        assert result.alert.alert_level == "yellow"

    def test_alert_severity_high(self):
        system = BombAlertSystem()
        # 100万 -> 400万，下跌 75%，触发 high/red
        result = system.check("001", "测试", 1000000, 4000000)
        assert result.alert.alert_level == "red"

    def test_alert_severity_medium(self):
        system = BombAlertSystem()
        # 100万 -> 200万，下跌 50%，触发 medium/yellow
        result = system.check("001", "测试", 1000000, 2000000)
        assert result.alert.alert_level == "yellow"

    def test_batch_check(self):
        system = BombAlertSystem()
        items = [
            {"code": "001", "name": "A", "seal_amount": 1000000, "prev_seal_amount": 2000000},
            {"code": "002", "name": "B", "seal_amount": 1800000, "prev_seal_amount": 2000000},
        ]
        results = system.batch_check(items)
        assert len(results) == 2
        assert results[0].triggered is True
        assert results[1].triggered is False

    def test_active_alerts(self):
        system = BombAlertSystem()
        system.check("001", "A", 1000000, 2000000)
        system.check("002", "B", 1800000, 2000000)
        alerts = system.active_alerts()
        assert len(alerts) == 1
        assert alerts[0].code == "001"


class TestPositionManager(unittest.TestCase):
    def test_default_limits(self):
        pm = PositionManager()
        assert pm.limits.max_single_position == 0.3
        assert pm.limits.max_sector_position == 0.6
        assert pm.limits.min_cash_reserve == 0.2

    def test_evaluate_increase_within_limit(self):
        pm = PositionManager()
        adj = pm.evaluate("001", "测试", 0.4)
        assert adj.action == "increase"
        assert adj.old_position_pct == 0.0
        assert adj.new_position_pct == 0.3

    def test_evaluate_decrease(self):
        pm = PositionManager()
        pm.upsert(PositionSnapshot(code="001", name="测试", weight=0.4))
        adj = pm.evaluate("001", "测试", 0.1)
        assert adj.action == "decrease"
        assert adj.old_position_pct == 0.4
        assert adj.new_position_pct == 0.1

    def test_evaluate_hold(self):
        pm = PositionManager()
        pm.upsert(PositionSnapshot(code="001", name="测试", weight=0.2))
        adj = pm.evaluate("001", "测试", 0.2)
        assert adj.action == "hold"

    def test_sector_exposure(self):
        pm = PositionManager()
        pm.upsert(PositionSnapshot(code="001", name="A", weight=0.2, sector="科技"))
        pm.upsert(PositionSnapshot(code="002", name="B", weight=0.3, sector="科技"))
        assert pm.sector_exposure("科技") == 0.5

    def test_current_weights(self):
        pm = PositionManager()
        pm.upsert(PositionSnapshot(code="001", name="A", weight=0.2))
        weights = pm.current_weights()
        assert weights["001"] == 0.2


class TestSettlementEngine(unittest.TestCase):
    def test_settle_win(self):
        engine = SettlementEngine()
        result = engine.settle(
            SettlementInput(code="001", name="测试", strategy="打板", entry_price=10, exit_price=11)
        )
        assert result.won is True
        assert result.return_pct == 10.0
        assert result.strategy_used == "打板"

    def test_settle_loss(self):
        engine = SettlementEngine()
        result = engine.settle(
            SettlementInput(code="001", name="测试", strategy="打板", entry_price=10, exit_price=9)
        )
        assert result.won is False
        assert result.return_pct == -10.0

    def test_batch_settle(self):
        engine = SettlementEngine()
        items = [
            SettlementInput(code="001", name="A", strategy="打板", entry_price=10, exit_price=11),
            SettlementInput(code="002", name="B", strategy="打板", entry_price=10, exit_price=9),
        ]
        results = engine.batch_settle(items)
        assert len(results) == 2
        assert results[0].won is True
        assert results[1].won is False

    def test_win_rate(self):
        engine = SettlementEngine()
        engine.settle(SettlementInput(code="001", name="A", strategy="打板", entry_price=10, exit_price=11))
        engine.settle(SettlementInput(code="002", name="B", strategy="打板", entry_price=10, exit_price=9))
        assert engine.win_rate() == 0.5

    def test_win_rate_by_strategy(self):
        engine = SettlementEngine()
        engine.settle(SettlementInput(code="001", name="A", strategy="二板定龙", entry_price=10, exit_price=11))
        engine.settle(SettlementInput(code="002", name="B", strategy="首板突破", entry_price=10, exit_price=9))
        assert engine.win_rate(strategy="二板定龙") == 1.0
        assert engine.win_rate(strategy="首板突破") == 0.0

    def test_summary(self):
        engine = SettlementEngine()
        engine.settle(SettlementInput(code="001", name="A", strategy="打板", entry_price=10, exit_price=11))
        summary = engine.summary()
        assert summary["count"] == 1
        assert summary["win_rate"] == 1.0
        assert summary["avg_return"] == 10.0


if __name__ == "__main__":
    unittest.main()
