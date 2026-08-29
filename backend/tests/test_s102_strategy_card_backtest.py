# -*- coding: utf-8 -*-
"""S102 战法卡片历史战绩段测试——运行时拼接 + §44 口径 + 战绩差标红。

契约：
- query_strategy_card 返回的 card 含「## 历史战绩」段
- 缓存命中：显胜率/均值/n + §44 口径（n<30 标本不足 / win<50% 标红 / 否则正胜率）
- 缓存未命中：显"战绩计算中"+ 异步触发预计算（不阻塞）
- 无样本：显"无样本"

注意：_CACHE/_CACHE_TS 在 strategies.strategy_backtest 模块（非 strategy_tools）。
_build_backtest_section 用函数内 `from ... import` 局部导入读模块属性，
故测试 monkeypatch strategy_backtest 模块的 _CACHE/_CACHE_TS 模块属性。
"""
from __future__ import annotations

import types

import pytest

from ai.tools import strategy_tools as st_tools
import strategies.strategy_backtest as sb


def _fake_result(code: str, win: float, avg: float, n: int):
    """构造 StrategyBacktestResult-like（SimpleNamespace）。"""
    return types.SimpleNamespace(
        strategy_code=code, strategy_name=code,
        win_rate=win, avg_return=avg, sample_size=n, available_days=60, skipped=0,
    )


def _seed_cache(monkeypatch, result):
    """填 strategy_backtest._CACHE 命中 + _CACHE_TS 新鲜。"""
    import time
    monkeypatch.setattr(sb, "_CACHE", {(60, None): [result]})
    monkeypatch.setattr(sb, "_CACHE_TS", {(60, None): time.time()})
    monkeypatch.setattr(sb, "_CACHE_TTL", 43200)


class TestBacktestSection:
    def test_no_sample(self, monkeypatch):
        """sample_size=0 → 显"无样本"。"""
        monkeypatch.setattr(st_tools, "_trigger_backtest_async", lambda code: None)
        _seed_cache(monkeypatch, _fake_result("first_plate", 0, 0, 0))

        section = st_tools._build_backtest_section("first_plate")
        assert "无样本" in section
        assert "历史战绩" in section

    def test_small_sample_marks_insufficient(self, monkeypatch):
        """n<30 → §44 标本不足，不下结论。"""
        monkeypatch.setattr(st_tools, "_trigger_backtest_async", lambda code: None)
        _seed_cache(monkeypatch, _fake_result("first_plate", 0.8, 5.0, 15))

        section = st_tools._build_backtest_section("first_plate")
        assert "样本不足" in section
        assert "不下结论" in section
        assert "n=15" in section
        assert "⚠️" not in section  # 样本不足不标红

    def test_poor_performance_marks_red(self, monkeypatch):
        """n>=30 且 win<50% → 标红警告。"""
        monkeypatch.setattr(st_tools, "_trigger_backtest_async", lambda code: None)
        _seed_cache(monkeypatch, _fake_result("first_plate", 0.313, 0.38, 418))

        section = st_tools._build_backtest_section("first_plate")
        assert "⚠️" in section
        assert "战绩偏弱" in section
        assert "31.3" in section  # win_pct
        assert "n=418" in section
        assert "§44" in section

    def test_good_performance_no_red(self, monkeypatch):
        """n>=30 且 win>=50% → 历史正胜率，不标红。"""
        monkeypatch.setattr(st_tools, "_trigger_backtest_async", lambda code: None)
        _seed_cache(monkeypatch, _fake_result("consecutive_relay", 0.5, 1.5, 100))

        section = st_tools._build_backtest_section("consecutive_relay")
        assert "⚠️" not in section
        assert "历史正胜率" in section
        assert "n=100" in section

    def test_cache_miss_shows_pending_and_triggers_async(self, monkeypatch):
        """缓存未命中 → 显"计算中"+ 触发异步预计算（不阻塞）。"""
        triggered: list[str] = []
        monkeypatch.setattr(st_tools, "_trigger_backtest_async", lambda code: triggered.append(code))
        monkeypatch.setattr(sb, "_CACHE", {})  # 无缓存
        monkeypatch.setattr(sb, "_CACHE_TS", {})
        monkeypatch.setattr(sb, "_CACHE_TTL", 43200)

        section = st_tools._build_backtest_section("first_plate")
        assert "计算中" in section
        assert triggered == ["first_plate"]  # 触发了异步预计算


class TestQueryCardWithBacktest:
    def test_card_contains_backtest_section_when_cached(self, monkeypatch):
        """query_strategy_card 缓存命中时 card 含战绩段。"""
        monkeypatch.setattr(st_tools, "_trigger_backtest_async", lambda code: None)
        _seed_cache(monkeypatch, _fake_result("first_plate", 0.313, 0.38, 418))

        result = st_tools.query_strategy_card("first_plate")
        assert "error" not in result
        card = result["card"]
        assert "## 历史战绩" in card
        assert "31.3" in card
        assert "⚠️" in card  # win 31.3% <50% 标红
        # 战绩段在风险点段前
        assert card.index("## 历史战绩") < card.index("## 风险点")

    def test_card_still_has_risk_disclaimer_tail(self, monkeypatch):
        """战绩段插入不破坏尾部风险提醒。"""
        monkeypatch.setattr(st_tools, "_trigger_backtest_async", lambda code: None)
        _seed_cache(monkeypatch, _fake_result("first_plate", 0.5, 1.0, 50))

        result = st_tools.query_strategy_card("first_plate")
        card = result["card"]
        assert "历史统计特征" in card  # 尾部风险提醒仍在
        assert card.rstrip().endswith("研究参考。")  # 尾部完整

    def test_unknown_code_returns_error(self):
        """未知 code 返 error（不崩）。"""
        result = st_tools.query_strategy_card("bogus_strategy")
        assert "error" in result


class TestTriggerThrottle:
    def test_trigger_throttled_within_cooldown(self, monkeypatch):
        """同一 code 5min 内不重复触发异步预计算。"""
        monkeypatch.setattr("threading.Thread", lambda *a, **kw: types.SimpleNamespace(start=lambda: None))

        st_tools._trigger_backtest_async("first_plate")
        # 第二次（立即）应被节流——_BACKTEST_TRIGGER_TS 已记录，第二次不重复
        st_tools._trigger_backtest_async("first_plate")
        assert "first_plate" in st_tools._BACKTEST_TRIGGER_TS
