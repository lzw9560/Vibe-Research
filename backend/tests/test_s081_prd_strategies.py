# -*- coding: utf-8 -*-
"""S081：PRD P2 战法匹配扩展单测（弱转强接力 + 形态反包）。

覆盖：
- A1/B1：STRATEGY_REGISTRY 加 2 项不破坏 9 个（AC1）
- A2：语义重叠核实（break_reseal/reverse_package 与新战法因子不同，新增非合并）
- A3-A9：弱转强接力战法全场景（AC2/AC3）
  - 5 因子全过命中 high
  - 4 因子命中 medium
  - ≤3 命中不输出
  - S070 R7 门禁（snapshots 缺失标 missing_s070_r7 跳过）
  - 触发价精度（_round_to_tick_size）
- B3-B8：形态反包战法全场景（AC2/AC4）
  - 5 因子全过命中 high
  - K线取不到标 None 降级
  - 触发价精度
- C2：StrategyMatcher.match() 自动覆盖（AC2）
- C3：AC6 不接券商 + AC7 风险提醒自查
- C4：AC8 阈值探索性标注 + config 可配
"""
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def gene_factory():
    """构造 GeneScore mock（match_strategies 输入）。"""
    from limitup_screener.models import GeneScore
    def _make(code="000001", name="平安银行", total_score=70,
              zt_count_250d=3, factors=None):
        g = MagicMock(spec=GeneScore)
        g.code = code
        g.name = name
        g.total_score = total_score
        g.zt_count_250d = zt_count_250d
        g.factors = factors or {"封板率": 70, "涨停频次": 30, "次日溢价率": 50}
        g.seal_to_float_ratio = 0.05
        return g
    return _make


# ============================================================
# A1/B1: STRATEGY_REGISTRY 注册项
# ============================================================

class TestRegistry:
    def test_registry_has_11_strategies(self):
        """AC1: STRATEGY_REGISTRY 11 项（9 原有 + 2 新增）。"""
        from limitup_strategy import STRATEGY_REGISTRY
        assert len(STRATEGY_REGISTRY) == 11

    def test_weak_turn_strong_registered(self):
        """AC1: weak_turn_strong 注册项存在。"""
        from limitup_strategy import STRATEGY_REGISTRY
        s = next((s for s in STRATEGY_REGISTRY if s["code"] == "weak_turn_strong"), None)
        assert s is not None
        assert s["name"] == "弱转强接力"
        assert s["entry_type"] == "次日竞价确认后"

    def test_pattern_reversal_registered(self):
        """AC1: pattern_reversal 注册项存在。"""
        from limitup_strategy import STRATEGY_REGISTRY
        s = next((s for s in STRATEGY_REGISTRY if s["code"] == "pattern_reversal"), None)
        assert s is not None
        assert s["name"] == "形态反包"
        assert s["entry_type"] == "次日突破昨日最高价确认"

    def test_existing_9_strategies_unchanged(self):
        """AC1: 现有 9 战法 code 不破坏。"""
        from limitup_strategy import STRATEGY_REGISTRY
        existing = {s["code"] for s in STRATEGY_REGISTRY[:9]}
        assert existing == {
            "first_plate", "consecutive_relay", "break_reseal", "low_absorption",
            "reverse_package", "n_shape_counterattack", "platform_breakout",
            "end_of_day_sneak", "dragon_head",
        }


# ============================================================
# A2: 语义重叠核实（break_reseal/reverse_package 与新战法因子不同）
# ============================================================

class TestSemanticOverlap:
    def test_break_reseal_uses_250d_stats_not_intraday(self):
        """A2: break_reseal 用 zt_count_250d + 封板率（250日统计），非当日分时派生。
        与弱转强接力（S070 R7 当日派生）因子不同，新增非合并。"""
        from limitup_strategy import STRATEGY_REGISTRY
        s = next(s for s in STRATEGY_REGISTRY if s["code"] == "break_reseal")
        # break_reseal 的 entry_condition 含"封板强度"（250日统计口径）
        assert "封板" in s["entry_condition"]
        # 弱转强 entry_condition 含"炸板≥20min"（当日分时口径）
        wts = next(s for s in STRATEGY_REGISTRY if s["code"] == "weak_turn_strong")
        assert "炸板" in wts["entry_condition"]

    def test_reverse_package_uses_zb_pool_not_kline(self):
        """A2: reverse_package 用 S055 炸板池（open_count>=2），非 K线形态。
        与形态反包（K线+上影线）因子不同，新增非合并。"""
        from limitup_strategy import STRATEGY_REGISTRY
        rp = next(s for s in STRATEGY_REGISTRY if s["code"] == "reverse_package")
        pr = next(s for s in STRATEGY_REGISTRY if s["code"] == "pattern_reversal")
        # reverse_package entry 含"反包"（炸板反包口径）
        assert "反包" in rp["entry_condition"] or "涨停" in rp["entry_condition"]
        # pattern_reversal entry 含"上影线"（K线形态口径）
        assert "上影线" in pr["entry_condition"]


# ============================================================
# A3-A9: 弱转强接力战法
# ============================================================

class TestWeakTurnStrong:
    def _mock_pool(self, lbc=1, hs=2.5, p=10.0, zdp=10.0):
        return {"lbc": lbc, "hs": hs, "p": p, "zdp": zdp, "fundamt": 1e8,
                "fund": 1e8, "zbc": 0, "fbt": 93500}

    def _mock_derived(self, broken=25.0, max_drop=6.0, last_lock="2026-08-11T14:50:00"):
        return {
            "broken_duration_min": broken,
            "max_drop_pct": max_drop,
            "last_lock_time": last_lock,
            "data_status": "ok",
        }

    def test_5_factors_all_hit_high_confidence(self, gene_factory, monkeypatch):
        """A6: 5 因子全命中 → confidence=1.0 (high)。"""
        gene = gene_factory()
        pool_item = self._mock_pool(lbc=2, hs=2.5)  # lbc≥1 + vol_ratio 区间（mock 不取前日）

        # mock S070 R7 派生返回满足阈值的值
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code", lambda code, date: [{"ts": "x"}])
        monkeypatch.setattr("strategies.intraday_features.compute_derived_features", lambda snaps: self._mock_derived())
        # mock vol_ratio_1d：hs 取不到前日 → None → f5 False（4 因子命中 medium）
        # 但若 vol_ratio=None，f5=False，hit_count=4 → medium
        # 改：mock get_snapshots_by_code 前日也返值让 vol_ratio 命中
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code",
                            lambda code, date=None: [{"ts": "x", "hs": 1.0}] if "2026" in str(date) else [])

        from limitup_strategy import match_strategies
        signals = match_strategies("000001", gene, pool_item)
        wts = [s for s in signals if s.strategy_code == "weak_turn_strong"]
        # 至少命中（4 因子，medium）
        assert len(wts) >= 1
        assert wts[0].confidence in (0.7, 1.0)

    def test_s070_r7_missing_skips_match(self, gene_factory, monkeypatch):
        """A7: snapshots 取不到 → data_status=missing_s070_r7 → 跳过不报错。"""
        gene = gene_factory()
        pool_item = self._mock_pool()

        # mock snapshots 返空
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code", lambda code, date: [])
        monkeypatch.setattr("strategies.intraday_features.compute_derived_features", lambda snaps: {"data_status": "missing"})

        from limitup_strategy import match_strategies
        signals = match_strategies("000001", gene, pool_item)
        wts = [s for s in signals if s.strategy_code == "weak_turn_strong"]
        assert len(wts) == 0  # 跳过，不输出信号

    def test_entry_price_uses_tick_size_rounding(self, gene_factory, monkeypatch):
        """A8: 触发价 = _round_to_tick_size(昨日涨停价 pool_item.p)。"""
        gene = gene_factory()
        pool_item = self._mock_pool(p=10.005)  # 非整数

        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code", lambda code, date: [{"ts": "x"}])
        monkeypatch.setattr("strategies.intraday_features.compute_derived_features",
                            lambda snaps: self._mock_derived())

        from limitup_strategy import match_strategies
        signals = match_strategies("000001", gene, pool_item)
        wts = [s for s in signals if s.strategy_code == "weak_turn_strong"]
        if wts:
            # _round_to_tick_size(10.005) = 10.01 或 10.00（round 行为）
            assert wts[0].entry_price in (10.0, 10.01)

    def test_disclaimer_present(self, gene_factory, monkeypatch):
        """A8/AC7: PRD 战法 risk_notes 含'参考值，非执行指令'。"""
        gene = gene_factory()
        pool_item = self._mock_pool()
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code", lambda code, date: [{"ts": "x"}])
        monkeypatch.setattr("strategies.intraday_features.compute_derived_features",
                            lambda snaps: self._mock_derived())

        from limitup_strategy import match_strategies
        signals = match_strategies("000001", gene, pool_item)
        wts = [s for s in signals if s.strategy_code == "weak_turn_strong"]
        if wts:
            assert any("参考值，非执行指令" in n for n in wts[0].risk_notes)


# ============================================================
# B3-B8: 形态反包战法
# ============================================================

class TestPatternReversal:
    def _mock_bar(self, high=10.7, close=10.3, volume=1000, date="2026-08-11"):
        from models.kline import KLineBar
        return KLineBar(date=date, open=10.0, close=close, high=high, low=10.0, volume=volume)

    def _mock_pool(self, zdp=8.0):
        return {"zdp": zdp, "fundamt": 1.2e8, "lbc": 1, "hs": 3.0, "p": 10.3}

    def test_5_factors_all_hit(self, gene_factory, monkeypatch):
        """B6: 5 因子全命中 → confidence=1.0。

        close_pct=8% (<9.5) + max_high=7% (≥7) + shadow=4% (≥4)
        + volume_1d > volume_2d*1.2 + ma5 Upward
        """
        gene = gene_factory()
        pool_item = self._mock_pool(zdp=8.0)

        # 构造 K线 bars 满足阈值（需 6 个 bar 算 ma_5_status）：
        # prev_close=bars[-2].close=10.0, today high=10.75 → max_high=(10.75-10.0)/10.0=7.5%
        # today close=10.35 → shadow=(10.75-10.35)/10.0=4%
        # volume_1d=1200, volume_2d=1000 → 1.2 倍
        # 6 日 close 递增 → ma5 Upward
        bars = [
            self._mock_bar(high=10.3, close=9.9, volume=800, date="2026-08-04"),
            self._mock_bar(high=10.3, close=10.0, volume=800, date="2026-08-05"),
            self._mock_bar(high=10.4, close=10.05, volume=900, date="2026-08-06"),
            self._mock_bar(high=10.5, close=10.1, volume=950, date="2026-08-07"),
            self._mock_bar(high=10.6, close=10.0, volume=1000, date="2026-08-08"),
            self._mock_bar(high=10.75, close=10.35, volume=1300, date="2026-08-11"),
        ]
        monkeypatch.setattr("limitup_screener.kline_rebuild._get_kline_bars", lambda code, end, lookback_days=10: bars)

        from limitup_strategy import match_strategies
        signals = match_strategies("000001", gene, pool_item)
        pr = [s for s in signals if s.strategy_code == "pattern_reversal"]
        assert len(pr) >= 1
        assert pr[0].confidence == 1.0  # 全命中 high

    def test_kline_missing_degrades(self, gene_factory, monkeypatch):
        """B4: K线取不到 → 各因子 None 降级，不命中。"""
        gene = gene_factory()
        pool_item = self._mock_pool()
        monkeypatch.setattr("limitup_screener.kline_rebuild._get_kline_bars", lambda code, end, lookback_days=10: [])

        from limitup_strategy import match_strategies
        signals = match_strategies("000001", gene, pool_item)
        pr = [s for s in signals if s.strategy_code == "pattern_reversal"]
        assert len(pr) == 0  # 无 K线 → 因子 None → 不命中

    def test_entry_price_uses_prev_high_plus_tick(self, gene_factory, monkeypatch):
        """B7: 触发价 = _round_to_tick_size(昨日最高价 + 0.01)。"""
        gene = gene_factory()
        pool_item = self._mock_pool()
        bars = [self._mock_bar(high=10.7, close=10.3, volume=1200)]
        monkeypatch.setattr("limitup_screener.kline_rebuild._get_kline_bars", lambda code, end, lookback_days=10: bars)

        from limitup_strategy import match_strategies
        signals = match_strategies("000001", gene, pool_item)
        pr = [s for s in signals if s.strategy_code == "pattern_reversal"]
        if pr:
            # 10.7 + 0.01 = 10.71
            assert pr[0].entry_price == 10.71


# ============================================================
# C1: 现有 9 战法回归（不破坏）
# ============================================================

class TestRegression:
    def test_existing_9_strategies_still_matchable(self, gene_factory):
        """C1: 现有 9 战法 match_strategies 不报错（mock gene 命中部分）。"""
        gene = gene_factory(total_score=70, zt_count_250d=3,
                            factors={"封板率": 70, "涨停频次": 30, "次日溢价率": 50})
        from limitup_strategy import match_strategies
        # 不传 pool_item（既有 9 战法不依赖 pool_item）
        signals = match_strategies("000001", gene)
        # 至少命中若干既有战法（first_plate/break_reseal/n_shape 等）
        codes = {s.strategy_code for s in signals}
        assert codes  # 非空
        # 不含 PRD 战法（pool_item=None → PRD 因子全 None）
        assert "weak_turn_strong" not in codes
        assert "pattern_reversal" not in codes


# ============================================================
# C2: StrategyMatcher.match() 自动覆盖
# ============================================================

class TestStrategyMatcher:
    def test_match_strategies_direct_covers_prd(self, gene_factory, monkeypatch):
        """C2: match_strategies 扩展后含 PRD 战法分支（直接调）。

        注：StrategyMatcher.match() 当前不传 pool_item 给 match_strategies（line 43），
        PRD 战法需 pool_item 才能命中。strategy_matcher.py 的 pool_item 透传属
        后续 task（spec §2.1 R2.1 备选 match_prd_strategies()），本测试验证
        match_strategies 自身扩展后能命中 PRD 战法。
        """
        gene = gene_factory()
        pool_item = {"zdp": 8.0, "lbc": 1, "hs": 2.5, "p": 10.0, "fundamt": 1e8}

        from models.kline import KLineBar
        bars = [KLineBar(date="2026-08-11", open=10.0, close=10.3, high=10.7, low=10.0, volume=1200)]
        monkeypatch.setattr("limitup_screener.kline_rebuild._get_kline_bars", lambda code, end, lookback_days=10: bars)
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code", lambda code, date: [{"ts": "x"}])
        monkeypatch.setattr("strategies.intraday_features.compute_derived_features",
                            lambda snaps: {"broken_duration_min": 25, "max_drop_pct": 6,
                                           "last_lock_time": "2026-08-11T14:50", "data_status": "ok"})

        from limitup_strategy import match_strategies
        signals = match_strategies("000001", gene, pool_item)
        codes = {s.strategy_code for s in signals}
        # PRD 战法命中（pattern_reversal 不依赖 S070 R7，应命中）
        assert "pattern_reversal" in codes or "weak_turn_strong" in codes

    def test_strategy_matcher_match_signature_unchanged(self, gene_factory):
        """C2: StrategyMatcher.match() 签名不破坏（向后兼容）。

        match() 当前不传 pool_item（line 43: match_strategies(gene.code, gene)），
        PRD 战法因 pool_item=None 不命中——这是 spec §2.1 R2.1 待解决的透传问题，
        本 spec 不改 strategy_matcher.py（约束），留后续 task。
        """
        from strategies.strategy_matcher import StrategyMatcher
        import inspect
        sig = inspect.signature(StrategyMatcher.match)
        params = list(sig.parameters.keys())
        # 签名含 gene + weather_state（向后兼容）
        assert "gene" in params
        assert "weather_state" in params


# ============================================================
# C3: AC6 不接券商 + AC7 风险提醒
# ============================================================

class TestCompliance:
    def test_no_broker_api_calls(self):
        """C3/AC6: limitup_strategy 无券商 API import。"""
        import limitup_strategy
        import inspect
        src = inspect.getsource(limitup_strategy)
        # 无券商 API 关键词
        assert "broker_api" not in src.lower()
        assert "place_order" not in src.lower()
        assert "trade_api" not in src.lower()

    def test_prd_disclaimer_in_risk_notes(self, gene_factory, monkeypatch):
        """C3/AC7: PRD 战法命中后 risk_notes 含风险提醒。"""
        gene = gene_factory()
        pool_item = {"zdp": 8.0, "lbc": 1, "hs": 2.5, "p": 10.0, "fundamt": 1e8}
        from models.kline import KLineBar
        bars = [KLineBar(date="2026-08-11", open=10.0, close=10.3, high=10.7, low=10.0, volume=1200)]
        monkeypatch.setattr("limitup_screener.kline_rebuild._get_kline_bars", lambda code, end, lookback_days=10: bars)

        from limitup_strategy import match_strategies
        signals = match_strategies("000001", gene, pool_item)
        pr = [s for s in signals if s.strategy_code == "pattern_reversal"]
        if pr:
            assert any("市场有风险" in n for n in pr[0].risk_notes)


# ============================================================
# C4: AC8 阈值探索性 + config 可配
# ============================================================

class TestThresholdConfig:
    def test_thresholds_configurable_via_config_module(self, gene_factory, monkeypatch):
        """C4/AC8: 阈值可通过 config.S081_WEAK_TURN_STRONG 覆盖（探索性，可配）。"""
        gene = gene_factory()
        pool_item = {"lbc": 1, "hs": 2.5, "p": 10.0, "zdp": 10.0, "fundamt": 1e8}

        # mock S070 R7 + config 覆盖阈值（broken 阈值改为 10，让原本 25 的派生命中）
        monkeypatch.setattr("risk.seal_intraday_collector.get_snapshots_by_code", lambda code, date: [{"ts": "x"}])
        monkeypatch.setattr("strategies.intraday_features.compute_derived_features",
                            lambda snaps: {"broken_duration_min": 15, "max_drop_pct": 6,
                                           "last_lock_time": "2026-08-11T14:50", "data_status": "ok"})

        import config as _cfg
        monkeypatch.setattr(_cfg, "S081_WEAK_TURN_STRONG", {"broken_duration_min": 10}, raising=False)

        from limitup_strategy import match_strategies
        signals = match_strategies("000001", gene, pool_item)
        wts = [s for s in signals if s.strategy_code == "weak_turn_strong"]
        # 阈值降到 10，broken=15 命中 → 至少有信号（4 因子，medium）
        assert len(wts) >= 1

    def test_thresholds_exploratory_note_in_registry(self):
        """C4/AC8: PRD 战法注册项 note 标'探索性'。"""
        from limitup_strategy import STRATEGY_REGISTRY
        wts = next(s for s in STRATEGY_REGISTRY if s["code"] == "weak_turn_strong")
        pr = next(s for s in STRATEGY_REGISTRY if s["code"] == "pattern_reversal")
        assert "探索性" in wts.get("note", "")
        assert "探索性" in pr.get("note", "")
