# -*- coding: utf-8 -*-
"""S218 Component 1: 每日信号报告测试（TDD - RED → GREEN）。

测试目标：
- get_consecutive_relay_signals 返回结构化 dict（含 regime/cap/filter/signals）
- render_daily_report 返回人话报告（非术语堆）
- 数字来自 verified §44 / deep_dive，不臆造
- 3-bucket 分类（可做/探索性/别碰）
- 参考价非 N/A
- 免责声明用 spec §44 reframe 字符串
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── test: get_consecutive_relay_signals ─────────────────────────────────

class TestGetConsecutiveRelaySignals:
    """测试核心纯函数 get_consecutive_relay_signals。"""

    @pytest.fixture(autouse=True)
    def _patch_deps(self, monkeypatch):
        """Mock 所有外部依赖。"""
        self.mock_scan = MagicMock(return_value=[
            {"code": "000001", "lbc": 2},
            {"code": "000002", "lbc": 3},
        ])
        self.mock_regime_labels = MagicMock(return_value={
            "2026-09-18": "bear",
        })
        self.mock_lift = MagicMock(return_value=(0.5, "consecutive_relay regime=bear 最保守"))
        self.mock_quote = MagicMock(return_value={
            "000001": {"name": "平安银行", "close": 12.34},
            "000002": {"name": "万科A", "close": 15.67},
        })
        self.mock_bars = MagicMock(return_value=[
            {"date": "2026-09-18", "open": 12.30, "close": 12.34, "high": 12.40, "low": 12.20, "pctChg": 0.32},
        ])
        self.mock_unbuyable = MagicMock(return_value=False)

        monkeypatch.setattr("pre_limitup_scanner.scan_consecutive_relay", self.mock_scan)
        monkeypatch.setattr("tools.gap_regime_stratified.compute_regime_labels", self.mock_regime_labels)
        monkeypatch.setattr("candidate_funnel.evaluation.lift_for_arm", self.mock_lift)
        monkeypatch.setattr("ai.tools.stock_tools.query_quote", self.mock_quote)
        monkeypatch.setattr("engine.bars_provider.KlineCacheBarsProvider", lambda: self.mock_bars)
        monkeypatch.setattr("engine.bar_utils.is_unbuyable_next_bar", self.mock_unbuyable)

    def test_returns_structured_dict(self):
        from tools.signal_report import get_consecutive_relay_signals
        result = get_consecutive_relay_signals("2026-09-18")
        assert isinstance(result, dict)
        assert "date" in result
        assert "arm" in result
        assert "regime" in result
        assert "cap" in result
        assert "signals" in result

    def test_regime_freshness_flag(self):
        from tools.signal_report import get_consecutive_relay_signals
        result = get_consecutive_relay_signals("2026-09-18")
        # freshness reads actual filesystem cache; just verify the key exists
        assert "freshness" in result["regime"]
        assert "last_cache_date" in result["regime"]["freshness"]
        assert "stale" in result["regime"]["freshness"]

    def test_effective_cap_reflects_current_regime(self):
        from tools.signal_report import get_consecutive_relay_signals
        result = get_consecutive_relay_signals("2026-09-18")
        assert result["regime"]["current"] == "bear"
        assert result["cap"]["effective"] == 0.5
        assert result["cap"]["base"] == 1.0

    def test_get_signals_returns_name_and_price(self):
        from tools.signal_report import get_consecutive_relay_signals
        result = get_consecutive_relay_signals("2026-09-18")
        signals = result["signals"]
        assert len(signals) == 2
        assert signals[0]["code"] == "000001"
        assert signals[0]["name"] == "平安银行"
        assert signals[0]["entry_price"] == 12.34
        assert signals[1]["code"] == "000002"
        assert signals[1]["name"] == "万科A"

    def test_filters_unbuyable(self):
        from tools.signal_report import get_consecutive_relay_signals
        result = get_consecutive_relay_signals("2026-09-18")
        assert result["filters"]["total_scanned"] == 2
        assert result["filters"]["tradable"] == 0
        assert result["filters"]["exploratory"] == 2

    def test_verified_numbers_present(self):
        from tools.signal_report import get_consecutive_relay_signals
        result = get_consecutive_relay_signals("2026-09-18")
        vn = result["verified_numbers"]
        assert vn["chrono_train"] == 1.57
        assert vn["chrono_test"] == 1.04
        assert vn["chrono_decay_pct"] == 34
        assert vn["chrono_p"] == 0.0054
        assert vn["chrono_wr"] == 52.7
        assert vn["deep_dive_lbc2"] == 0.90
        assert vn["deep_dive_lbc3"] == 2.05


class TestThreeBucketClassification:
    """测试 3-bucket 分类（可做/探索性/别碰）。"""

    def test_bull_regime_tradable(self, monkeypatch):
        from tools.signal_report import _classify_signal
        assert _classify_signal(False, "bull") == "tradable"

    def test_bear_regime_exploratory(self, monkeypatch):
        from tools.signal_report import _classify_signal
        assert _classify_signal(False, "bear") == "exploratory"

    def test_range_regime_exploratory(self, monkeypatch):
        from tools.signal_report import _classify_signal
        assert _classify_signal(False, "range") == "exploratory"

    def test_unbuyable_avoid(self, monkeypatch):
        from tools.signal_report import _classify_signal
        assert _classify_signal(True, "bull") == "avoid"
        assert _classify_signal(True, "bear") == "avoid"


class TestRenderDailyReport:
    """测试 render_daily_report 人话渲染。"""

    def test_daily_report_header_marks_validation_not_realized(self):
        from tools.signal_report import render_daily_report
        report = render_daily_report({
            "date": "2026-09-18",
            "arm": "consecutive_relay",
            "regime": {"current": "bear", "edge_status": "bear underpowered"},
            "cap": {"effective": 0.5},
            "signals": [],
            "verified_numbers": {"chrono_test": 1.04, "chrono_p": 0.0054},
            "disclaimers": [
                "统计验证（非已实现收益）—— edge 衰减中（train 1.57%→test 1.04% 跌 34%）",
                "paper-only 无券商（零真交易）—— 接券商前所有战绩 paper，要真获益须手动在券商下单",
                "照做有风险 —— cap（75%/50%）是统计信心不是保本，真钱仓位/止损由你手动定",
                "非自动交易 —— 本系统不自动下单，须手动在券商下单",
            ],
        })
        # spec §44 reframe 字符串
        assert "统计验证" in report
        assert "非已实现收益" in report
        assert "paper-only" in report
        assert "零真交易" in report
        assert "照做有风险" in report
        assert "非自动交易" in report

    def test_daily_report_edge_carries_decay(self):
        from tools.signal_report import render_daily_report
        report = render_daily_report({
            "date": "2026-09-18",
            "arm": "consecutive_relay",
            "regime": {"current": "bear", "edge_status": "bear underpowered"},
            "cap": {"effective": 0.5, "decay": 0.75},
            "signals": [],
            "verified_numbers": {"chrono_train": 1.57, "chrono_test": 1.04, "chrono_decay_pct": 34},
            "disclaimers": [],
        })
        assert "34%" in report or "衰减" in report or "1.04" in report or "1.57" in report

    def test_report_uses_ev_not_price_target(self):
        from tools.signal_report import render_daily_report
        report = render_daily_report({
            "date": "2026-09-18",
            "arm": "consecutive_relay",
            "regime": {"current": "bear", "edge_status": "bear underpowered"},
            "cap": {"effective": 0.5},
            "signals": [
                {"code": "000001", "name": "平安银行", "lbc": 2, "entry_price": 12.34, "verdict": "可做", "bucket": "tradable"},
            ],
            "verified_numbers": {"chrono_test": 1.04},
            "disclaimers": [],
        })
        assert "目标价" not in report
        assert "止盈" not in report
        assert "止损" not in report

    def test_report_says_not_auto_trading(self):
        from tools.signal_report import render_daily_report
        report = render_daily_report({
            "date": "2026-09-18",
            "arm": "consecutive_relay",
            "regime": {"current": "bear", "edge_status": "bear underpowered"},
            "cap": {"effective": 0.5},
            "signals": [],
            "verified_numbers": {},
            "disclaimers": ["非自动交易 —— 本系统不自动下单，须手动在券商下单"],
        })
        assert "非自动交易" in report or "不自动下单" in report or "手动" in report

    def test_lbc_numbers_labeled_deep_dive_not_chrono(self):
        from tools.signal_report import render_daily_report
        report = render_daily_report({
            "date": "2026-09-18",
            "arm": "consecutive_relay",
            "regime": {"current": "bear", "edge_status": "bear underpowered"},
            "cap": {"effective": 0.5},
            "signals": [
                {"code": "000001", "name": "平安银行", "lbc": 2, "entry_price": 12.34, "verdict": "可做", "bucket": "tradable"},
                {"code": "000002", "name": "万科A", "lbc": 3, "entry_price": 15.67, "verdict": "可做", "bucket": "exploratory"},
            ],
            "verified_numbers": {
                "deep_dive_lbc2": 0.90,
                "deep_dive_lbc3": 2.05,
            },
            "disclaimers": [],
        })
        assert "2.05" in report or "0.90" in report
        # deep_dive 数字应有标注，不与 chrono 混
        assert "deep" in report.lower() or "探索" in report or "参考" in report

    def test_empty_signals_says_no_picks(self):
        from tools.signal_report import render_daily_report
        report = render_daily_report({
            "date": "2026-09-18",
            "arm": "consecutive_relay",
            "regime": {"current": "bear", "edge_status": "bear underpowered"},
            "cap": {"effective": 0.5},
            "signals": [],
            "verified_numbers": {},
            "disclaimers": [],
        })
        assert "无" in report or "没有" in report or "空" in report

    def test_three_bucket_sections_present(self):
        from tools.signal_report import render_daily_report
        report = render_daily_report({
            "date": "2026-09-18",
            "arm": "consecutive_relay",
            "regime": {"current": "bear", "edge_status": "bear underpowered"},
            "cap": {"effective": 0.5},
            "signals": [
                {"code": "000001", "name": "平安银行", "lbc": 2, "entry_price": 12.34, "bucket": "exploratory"},
            ],
            "verified_numbers": {},
            "disclaimers": [],
        })
        assert "【可做】" in report
        assert "【探索性】" in report
        assert "【别碰】" in report
        # bear regime 的信号应进探索性而非可做
        assert "探索性" in report

    def test_reference_price_shown_not_na(self):
        from tools.signal_report import render_daily_report
        report = render_daily_report({
            "date": "2026-09-18",
            "arm": "consecutive_relay",
            "regime": {"current": "bear", "edge_status": "bear underpowered"},
            "cap": {"effective": 0.5},
            "signals": [
                {"code": "000001", "name": "平安银行", "lbc": 2, "entry_price": 12.34, "bucket": "exploratory", "price_source": "2026-09-15"},
            ],
            "verified_numbers": {},
            "disclaimers": [],
        })
        # 应显示参考价而非 N/A
        assert "12.34" in report or "参考价" in report
        # 不应 bare N/A
        assert "收盘价 N/A" not in report


class TestSignalReportRouter:
    """测试 routers/signals.py API 端点。"""

    def test_api_signals_daily_returns_dict(self):
        from routers.signals import _signals_daily
        with patch("routers.signals.get_consecutive_relay_signals") as mock_get:
            mock_get.return_value = {
                "date": "2026-09-18",
                "signals": [{"code": "000001", "name": "平安银行"}],
            }
            result = _signals_daily()
            assert isinstance(result, dict)
            assert result["date"] == "2026-09-18"

    def test_api_signals_status_returns_regime_and_arm(self):
        from routers.signals import _signals_status
        with patch("routers.signals.TradeJournal") as MockTJ:
            mock_tj = MagicMock()
            mock_tj.query_arm_status.return_value = {
                "is_active": True,
                "weight_override": None,
            }
            MockTJ.return_value = mock_tj
            with patch("routers.signals.compute_regime_labels") as mock_regime:
                mock_regime.return_value = {"2026-09-18": "bear"}
                result = _signals_status()
                assert "regime" in result
                assert "arms" in result
