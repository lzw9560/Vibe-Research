# -*- coding: utf-8 -*-
"""S093 S2a：bomb_alert 规则引擎扩展 C7-C9 + dispatcher 飞书通知测试。

覆盖：
- C7（涨停 INFO）/ C8（情绪恶化 MEDIUM）/ C9（连板断裂 MEDIUM）触发 + 不触发 + 缺数据
- dispatcher 接 NotificationService.send() 推飞书卡片（mock）
- 冷却 10min 内同信号同标的不重复
- 北向规则已删（Oracle 阻断 #2）
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

_NOW = datetime(2026, 8, 20, 10, 30)


# ─── C7 前瞻标的涨停 ───────────────────────────────────────────

class TestC7ForwardLimitUp:
    def test_triggered_when_in_forward_and_zt_pool(self):
        from risk.bomb_alert_rules import check_c7_forward_limit_up
        snaps = [{"ts": _NOW.isoformat()}]
        r = check_c7_forward_limit_up(
            snaps, "000001", "测试",
            forward_candidates={"000001"}, zt_pool_codes={"000001"}, now=_NOW,
        )
        assert r.triggered is True
        assert r.alert is not None
        assert r.alert.alert_level == "info"
        assert r.alert.recommendation == "建议关注"

    def test_triggered_when_in_forward_and_high_gain(self):
        from risk.bomb_alert_rules import check_c7_forward_limit_up
        snaps = [{"ts": _NOW.isoformat(), "gain_pct": 10.0}]
        r = check_c7_forward_limit_up(
            snaps, "000001", "测试",
            forward_candidates={"000001"}, zt_pool_codes=set(), now=_NOW,
        )
        assert r.triggered is True
        assert r.alert.alert_level == "info"

    def test_triggered_with_pct_chg_field(self):
        """快照用 pct_chg 字段也能识别涨停。"""
        from risk.bomb_alert_rules import check_c7_forward_limit_up
        snaps = [{"ts": _NOW.isoformat(), "pct_chg": 9.9}]
        r = check_c7_forward_limit_up(
            snaps, "000001", "测试",
            forward_candidates={"000001"}, zt_pool_codes=set(), now=_NOW,
        )
        assert r.triggered is True

    def test_not_triggered_when_not_forward_candidate(self):
        from risk.bomb_alert_rules import check_c7_forward_limit_up
        snaps = [{"ts": _NOW.isoformat(), "gain_pct": 10.0}]
        r = check_c7_forward_limit_up(
            snaps, "000001", "测试",
            forward_candidates={"600519"}, zt_pool_codes={"000001"}, now=_NOW,
        )
        assert r.triggered is False
        assert "不在前瞻候选" in r.reason

    def test_not_triggered_when_zt_pool_provided_but_not_in_it(self):
        """zt_pool 明确提供但不含该 code → 不触发（非 missing）。"""
        from risk.bomb_alert_rules import check_c7_forward_limit_up
        snaps = [{"ts": _NOW.isoformat(), "gain_pct": 5.0}]
        r = check_c7_forward_limit_up(
            snaps, "000001", "测试",
            forward_candidates={"000001"}, zt_pool_codes={"600519"}, now=_NOW,
        )
        assert r.triggered is False
        assert r.data_status == "ok"

    def test_missing_when_no_zt_pool_and_no_snapshot(self):
        from risk.bomb_alert_rules import check_c7_forward_limit_up
        r = check_c7_forward_limit_up(
            [], "000001", "测试",
            forward_candidates={"000001"}, zt_pool_codes=None, now=_NOW,
        )
        assert r.triggered is False
        assert r.data_status == "missing"

    def test_missing_when_no_zt_pool_and_no_gain_field(self):
        """zt_pool 未传入 + 快照无涨幅字段 → missing。"""
        from risk.bomb_alert_rules import check_c7_forward_limit_up
        snaps = [{"ts": _NOW.isoformat(), "seal_amount": 1e8}]
        r = check_c7_forward_limit_up(
            snaps, "000001", "测试",
            forward_candidates={"000001"}, zt_pool_codes=None, now=_NOW,
        )
        assert r.triggered is False
        assert r.data_status == "missing"


# ─── C8 情绪恶化 ──────────────────────────────────────────────

class TestC8SentimentDeterioration:
    def test_triggered_when_zt_low_and_zb_high(self):
        from risk.bomb_alert_rules import check_c8_sentiment_deterioration
        snap = {"zt_count": 3, "zb_count": 5}
        r = check_c8_sentiment_deterioration(snap, _NOW)
        assert r.triggered is True
        assert r.alert is not None
        assert r.alert.alert_level == "medium"
        assert r.alert.recommendation == "建议谨慎"
        assert r.alert.code == "MARKET"

    def test_not_triggered_when_zt_sufficient(self):
        from risk.bomb_alert_rules import check_c8_sentiment_deterioration
        snap = {"zt_count": 10, "zb_count": 5}
        r = check_c8_sentiment_deterioration(snap, _NOW)
        assert r.triggered is False

    def test_not_triggered_when_zb_not_exceeding_zt(self):
        """zb_count < zt_count → 不触发。"""
        from risk.bomb_alert_rules import check_c8_sentiment_deterioration
        snap = {"zt_count": 3, "zb_count": 2}
        r = check_c8_sentiment_deterioration(snap, _NOW)
        assert r.triggered is False

    def test_not_triggered_when_zt_high_but_zb_also_high(self):
        """zt_count≥5 → 不触发（即使 zb>zt）。"""
        from risk.bomb_alert_rules import check_c8_sentiment_deterioration
        snap = {"zt_count": 6, "zb_count": 8}
        r = check_c8_sentiment_deterioration(snap, _NOW)
        assert r.triggered is False

    def test_missing_when_no_snapshot(self):
        from risk.bomb_alert_rules import check_c8_sentiment_deterioration
        r = check_c8_sentiment_deterioration(None, _NOW)
        assert r.triggered is False
        assert r.data_status == "missing"

    def test_missing_when_zb_count_absent(self):
        """S1 未落 zb_count 字段 → None → missing 不触发。"""
        from risk.bomb_alert_rules import check_c8_sentiment_deterioration
        snap = {"zt_count": 3}
        r = check_c8_sentiment_deterioration(snap, _NOW)
        assert r.triggered is False
        assert r.data_status == "missing"


# ─── C9 连板断裂 ───────────────────────────────────────────────

class TestC9LadderBreak:
    def test_triggered_when_max_boards_high_and_no_2board(self):
        from risk.bomb_alert_rules import check_c9_ladder_break
        snap = {"max_boards": 5, "ladder": {1: 30, 2: 0, 3: 5, 4: 1}}
        r = check_c9_ladder_break(snap, _NOW)
        assert r.triggered is True
        assert r.alert is not None
        assert r.alert.alert_level == "medium"
        assert r.alert.recommendation == "建议回避高位"
        assert r.alert.code == "MARKET"

    def test_not_triggered_when_max_boards_low(self):
        from risk.bomb_alert_rules import check_c9_ladder_break
        snap = {"max_boards": 2, "ladder": {1: 30, 2: 0}}
        r = check_c9_ladder_break(snap, _NOW)
        assert r.triggered is False

    def test_not_triggered_when_2board_exists(self):
        from risk.bomb_alert_rules import check_c9_ladder_break
        snap = {"max_boards": 5, "ladder": {1: 30, 2: 5, 3: 2}}
        r = check_c9_ladder_break(snap, _NOW)
        assert r.triggered is False

    def test_missing_when_no_ladder(self):
        from risk.bomb_alert_rules import check_c9_ladder_break
        snap = {"max_boards": 5}
        r = check_c9_ladder_break(snap, _NOW)
        assert r.triggered is False
        assert r.data_status == "missing"

    def test_missing_when_no_snapshot(self):
        from risk.bomb_alert_rules import check_c9_ladder_break
        r = check_c9_ladder_break(None, _NOW)
        assert r.triggered is False
        assert r.data_status == "missing"

    def test_list_ladder_format(self):
        """ladder 为 list 格式也能处理（index 1 = 2板家数）。"""
        from risk.bomb_alert_rules import check_c9_ladder_break
        snap = {"max_boards": 4, "ladder": [10, 0, 3, 1]}  # 1板=10, 2板=0, 3板=3, 4板=1
        r = check_c9_ladder_break(snap, _NOW)
        assert r.triggered is True


# ─── check_market_rules 集成 ──────────────────────────────────

class TestCheckMarketRules:
    def test_returns_two_rules(self):
        from risk.bomb_alert_rules import check_market_rules
        snap = {"zt_count": 10, "zb_count": 5, "max_boards": 2, "ladder": {1: 30, 2: 0}}
        results = check_market_rules(snap, _NOW)
        assert len(results) == 2
        assert [r.rule_id for r in results] == ["C8", "C9"]

    def test_both_triggered(self):
        from risk.bomb_alert_rules import check_market_rules
        snap = {"zt_count": 3, "zb_count": 5, "max_boards": 5, "ladder": {1: 30, 2: 0, 3: 5}}
        results = check_market_rules(snap, _NOW)
        assert all(r.triggered for r in results)

    def test_missing_when_snapshot_none(self):
        from risk.bomb_alert_rules import check_market_rules
        results = check_market_rules(None, _NOW)
        assert all(r.data_status == "missing" for r in results)


# ─── check_all_rules 含 C7 ────────────────────────────────────

class TestCheckAllRulesWithC7:
    def test_returns_seven_rules(self):
        from risk.bomb_alert_rules import check_all_rules
        snaps = [{"ts": _NOW.isoformat(), "seal_amount": 1e8, "float_market_cap": 1e9}]
        results = check_all_rules(snaps, "000001", "测试", set(), _NOW)
        assert len(results) == 7
        assert [r.rule_id for r in results] == ["C1", "C2", "C3", "C4", "C5", "C6", "C7"]

    def test_c7_not_triggered_without_forward_candidates(self):
        """无 forward_candidates → C7 不触发（不在候选集合）。"""
        from risk.bomb_alert_rules import check_all_rules
        snaps = [{"ts": _NOW.isoformat(), "seal_amount": 1e8}]
        results = check_all_rules(snaps, "000001", "测试", set(), _NOW)
        c7 = [r for r in results if r.rule_id == "C7"][0]
        assert c7.triggered is False


# ─── 北向规则已删 ─────────────────────────────────────────────

class TestNorthboundRuleDeleted:
    """Oracle 阻断 #2：北向个股日级数据 2024-08-19 停更，无真实数据源，违反不臆造底线。"""

    def test_no_northbound_function_in_rules(self):
        import risk.bomb_alert_rules as rules
        rule_funcs = [
            name for name in dir(rules)
            if name.startswith("check_") and name not in ("check_all_rules", "check_market_rules")
        ]
        assert not any("north" in f.lower() for f in rule_funcs)

    def test_no_northbound_rule_id_in_check_all(self):
        from risk.bomb_alert_rules import check_all_rules
        snaps = [{"ts": _NOW.isoformat()}]
        results = check_all_rules(snaps, "000001", "测试", set(), _NOW)
        for r in results:
            assert "north" not in r.rule_id.lower()

    def test_no_northbound_constant(self):
        import risk.bomb_alert_rules as rules
        constants = [name for name in dir(rules) if name.isupper()]
        assert not any("north" in c.lower() for c in constants)


# ─── Dispatcher 飞书通知 ───────────────────────────────────────

@pytest.fixture
def isolated_seal_db(tmp_path, monkeypatch):
    """隔离 seal DB + 冷却 cache（复用 test_s055 模式）。"""
    db_path = tmp_path / "seal_intraday.db"
    monkeypatch.setattr("risk.seal_intraday_collector._DB_PATH", str(db_path))
    monkeypatch.setattr("risk.seal_intraday_collector.SEAL_INTRADAY_DB_PATH", str(db_path))
    monkeypatch.setattr("risk.bomb_alert_dispatcher._DB_PATH", str(db_path))
    monkeypatch.setattr("risk.bomb_alert_dispatcher.SEAL_INTRADAY_DB_PATH", str(db_path))
    import risk.bomb_alert_dispatcher as bad
    bad._cooldown_cache.clear()
    from risk.seal_intraday_collector import run_migrations
    run_migrations()
    yield str(db_path)
    bad._cooldown_cache.clear()


def _make_alert_result(rule_id="C5", level="red", condition="开板未回封",
                       recommendation="建议止损"):
    """构造一个 triggered RuleCheckResult。"""
    from realtime_workflow import BombAlert
    from risk.bomb_alert_rules import RuleCheckResult
    return RuleCheckResult(
        rule_id=rule_id, triggered=True,
        alert=BombAlert(
            timestamp=_NOW.isoformat(), code="000001", name="测试",
            alert_level=level, condition=condition,
            current_seal_amount=0, seal_amount_change_5min=0,
            recommendation=recommendation,
        ),
        data_status="ok", reason=condition,
    )


class TestDispatcherFeishuNotification:
    def test_notify_calls_notification_service_when_enabled(self, isolated_seal_db, monkeypatch):
        from config import default_config
        monkeypatch.setattr(default_config, "BOMB_ALERT_NOTIFY_ENABLE", True)

        with patch("notification.notification_service.NotificationService") as mock_svc:
            mock_svc.return_value.send.return_value = True
            from risk.bomb_alert_dispatcher import notify_if_enabled
            result = _make_alert_result()
            ok = notify_if_enabled("000001", "测试", result)
            assert ok is True
            mock_svc.return_value.send.assert_called_once()

    def test_notify_card_contains_recommendation_and_disclaimer(self, isolated_seal_db, monkeypatch):
        from config import default_config
        monkeypatch.setattr(default_config, "BOMB_ALERT_NOTIFY_ENABLE", True)

        with patch("notification.notification_service.NotificationService") as mock_svc:
            mock_svc.return_value.send.return_value = True
            from risk.bomb_alert_dispatcher import notify_if_enabled
            result = _make_alert_result(recommendation="建议止损")
            notify_if_enabled("000001", "测试", result)
            content = mock_svc.return_value.send.call_args[0][0]
            assert "建议止损" in content
            assert "历史统计特征" in content
            assert "市场有风险" in content

    def test_notify_skipped_when_disabled(self, isolated_seal_db, monkeypatch):
        from config import default_config
        monkeypatch.setattr(default_config, "BOMB_ALERT_NOTIFY_ENABLE", False)

        with patch("notification.notification_service.NotificationService") as mock_svc:
            from risk.bomb_alert_dispatcher import notify_if_enabled
            result = _make_alert_result()
            ok = notify_if_enabled("000001", "测试", result)
            assert ok is False
            mock_svc.return_value.send.assert_not_called()

    def test_notify_failure_does_not_raise(self, isolated_seal_db, monkeypatch):
        """NotificationService.send() 抛异常 → catch 不阻塞落库主流程。"""
        from config import default_config
        monkeypatch.setattr(default_config, "BOMB_ALERT_NOTIFY_ENABLE", True)

        with patch("notification.notification_service.NotificationService") as mock_svc:
            mock_svc.return_value.send.side_effect = RuntimeError("网络错误")
            from risk.bomb_alert_dispatcher import notify_if_enabled
            result = _make_alert_result()
            ok = notify_if_enabled("000001", "测试", result)
            assert ok is False  # 失败返 False

    def test_cooldown_prevents_repeat_within_10min(self, isolated_seal_db, monkeypatch):
        """同股同规则 10 分钟内不重复触发（冷却去重）。"""
        from config import default_config
        monkeypatch.setattr(default_config, "BOMB_ALERT_NOTIFY_ENABLE", True)

        with patch("notification.notification_service.NotificationService") as mock_svc:
            mock_svc.return_value.send.return_value = True
            from risk.bomb_alert_dispatcher import process_alerts
            now = datetime(2026, 8, 20, 10, 0)
            result = _make_alert_result()

            # 第一次触发 → 落库 + 通知
            active1 = process_alerts("000001", "测试", [result], now)
            assert len(active1) == 1
            assert mock_svc.return_value.send.call_count == 1

            # 5 分钟后同信号 → 冷却跳过
            later = now + timedelta(minutes=5)
            active2 = process_alerts("000001", "测试", [result], later)
            assert len(active2) == 0
            assert mock_svc.return_value.send.call_count == 1  # 未再发送

    def test_cooldown_expires_after_10min(self, isolated_seal_db, monkeypatch):
        """冷却 10 分钟后可再次触发。"""
        from config import default_config
        monkeypatch.setattr(default_config, "BOMB_ALERT_NOTIFY_ENABLE", True)

        with patch("notification.notification_service.NotificationService") as mock_svc:
            mock_svc.return_value.send.return_value = True
            from risk.bomb_alert_dispatcher import process_alerts
            now = datetime(2026, 8, 20, 10, 0)
            result = _make_alert_result()

            process_alerts("000001", "测试", [result], now)
            after = now + timedelta(minutes=11)
            active2 = process_alerts("000001", "测试", [result], after)
            assert len(active2) == 1
            assert mock_svc.return_value.send.call_count == 2

    def test_process_market_alerts_triggers_c8(self, isolated_seal_db, monkeypatch):
        """市场级规则 C8 触发 → 落库 + 通知。"""
        from config import default_config
        monkeypatch.setattr(default_config, "BOMB_ALERT_NOTIFY_ENABLE", True)

        with patch("notification.notification_service.NotificationService") as mock_svc:
            mock_svc.return_value.send.return_value = True
            from risk.bomb_alert_dispatcher import process_market_alerts
            snap = {"zt_count": 3, "zb_count": 5, "max_boards": 2, "ladder": {1: 30, 2: 0}}
            active = process_market_alerts(snap, _NOW)
            assert len(active) == 1
            assert active[0]["rule_id"] == "C8"
            assert active[0]["alert_level"] == "medium"
            assert active[0]["code"] == "MARKET"
            assert mock_svc.return_value.send.call_count == 1

    def test_process_market_alerts_triggers_c9(self, isolated_seal_db, monkeypatch):
        """市场级规则 C9 触发 → 落库 + 通知。"""
        from config import default_config
        monkeypatch.setattr(default_config, "BOMB_ALERT_NOTIFY_ENABLE", True)

        with patch("notification.notification_service.NotificationService") as mock_svc:
            mock_svc.return_value.send.return_value = True
            from risk.bomb_alert_dispatcher import process_market_alerts
            snap = {"zt_count": 10, "zb_count": 2, "max_boards": 5, "ladder": {1: 30, 2: 0, 3: 5}}
            active = process_market_alerts(snap, _NOW)
            assert len(active) == 1
            assert active[0]["rule_id"] == "C9"
            assert mock_svc.return_value.send.call_count == 1

    def test_market_alert_cooldown_prevents_repeat(self, isolated_seal_db, monkeypatch):
        """市场级 C8 10min 内不重复。"""
        from config import default_config
        monkeypatch.setattr(default_config, "BOMB_ALERT_NOTIFY_ENABLE", True)

        with patch("notification.notification_service.NotificationService") as mock_svc:
            mock_svc.return_value.send.return_value = True
            from risk.bomb_alert_dispatcher import process_market_alerts
            snap = {"zt_count": 3, "zb_count": 5, "max_boards": 2, "ladder": {1: 30, 2: 0}}
            now = datetime(2026, 8, 20, 10, 0)

            active1 = process_market_alerts(snap, now)
            assert len(active1) == 1

            later = now + timedelta(minutes=3)
            active2 = process_market_alerts(snap, later)
            assert len(active2) == 0  # 冷却期内
            assert mock_svc.return_value.send.call_count == 1
