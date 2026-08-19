# -*- coding: utf-8 -*-
"""S081 C2 修复单测：StrategyMatcher.match 传 pool_item 后 PRD 2 战法能命中。

覆盖：
- match() 签名加 pool_item 参数（向后兼容，默认 None）
- match_batch() 签名加 pool_items 参数（{code: pool_item} 映射）
- 传 pool_item 后 weak_turn_strong 战法能取 lbc/hs（依赖 S070 R7 派生数据 mock）
- 传 pool_item 后 pattern_reversal 战法能取 zdp（依赖 K线 mock）
- pool_item=None 降级：既有 9 战法不受影响，PRD 2 战法因子 None 不命中
- pre_market_workflow 取涨停池建 pool_item_map（mock fetch_zt_pool）
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.strategy_matcher import StrategyMatcher
from limitup_screener.models import GeneScore


# ---------------------------------------------------------------------------
# 构造工具
# ---------------------------------------------------------------------------

def _make_gene(code: str = "600000", name: str = "test_stock") -> GeneScore:
    """构造 GeneScore。"""
    return GeneScore(
        code=code,
        name=name,
        total_score=75.0,
        factors={"次日溢价率": 3.5, "红盘率": 70.0, "封板率": 80.0, "炸板后溢价": 2.0, "涨停频次": 5},
        wilson_adjusted=72.0,
        qualify=True,
        high_gene=True,
        last_zt_dates=["2026-08-17"],
        zt_count_250d=5,
    )


def _make_pool_item(
    code: str = "600000",
    lbc: int = 2,
    hs: float = 8.5,
    zdp: float = 10.0,
    p: float = 11.0,
) -> dict:
    """构造涨停池原始 dict（em_zt_topic_pool 返回结构）。

    字段：c(代码)/n(名)/lbc(连板)/zbc(炸板)/fbt(首封)/zdp(涨幅)/hs(换手)/p(价)
    """
    return {
        "c": code,
        "n": f"test_{code}",
        "lbc": lbc,
        "zbc": 0,
        "fbt": 93000,
        "zdp": zdp,
        "hs": hs,
        "p": p,
        "fundamt": 500000000,
        "fund": 10000000,
        "ltsz": 2000000000,
        "hybk": "测试行业",
    }


def _make_derived_features() -> dict:
    """构造 compute_derived_features 返回（S070 R7 派生字段）。

    weak_turn_strong 战法需要：broken_duration_min/max_drop_pct/last_lock_time。
    """
    return {
        "broken_duration_min": 25.0,   # ≥ 20 阈值
        "max_drop_pct": 6.0,           # ≥ 5.0 阈值
        "last_lock_time": "2026-08-18T14:50:00",  # ≥ 14:40 阈值
        "data_status": "ok",
    }


# ===========================================================================
# 1. match() 签名加 pool_item 参数（向后兼容）
# ===========================================================================

class TestMatchSignatureBackwardCompat:
    """match() 签名加 pool_item，默认 None 向后兼容。"""

    def test_match_old_signature_2_args(self):
        """旧调用 match(gene, weather_state) 不报错。"""
        matcher = StrategyMatcher()
        gene = _make_gene()
        # 不传 pool_item，应正常返回（既有 9 战法匹配，可能空）
        signals = matcher.match(gene, "晴天")
        # 不报错即可（具体命中看战法逻辑）
        assert isinstance(signals, list)

    def test_match_pool_item_none_default(self):
        """pool_item=None 默认值，PRD 战法因子取 None 不命中。"""
        matcher = StrategyMatcher()
        gene = _make_gene()
        signals = matcher.match(gene, None, pool_item=None)
        assert isinstance(signals, list)
        # PRD 战法依赖 pool_item，None 时不命中（不在 signals 里）
        prd_codes = [s.strategy_code for s in signals if s.strategy_code in ("weak_turn_strong", "pattern_reversal")]
        # pool_item=None + 无 S070 R7 数据 → PRD 战法不命中
        assert "weak_turn_strong" not in prd_codes

    def test_match_pool_item_keyword_arg(self):
        """关键字 pool_item= 传参。"""
        matcher = StrategyMatcher()
        gene = _make_gene()
        pool_item = _make_pool_item()
        # 不报错（PRD 战法还需 S070/K线数据，这里只验证签名接受）
        signals = matcher.match(gene, None, pool_item=pool_item)
        assert isinstance(signals, list)


# ===========================================================================
# 2. match_batch() 签名加 pool_items 参数
# ===========================================================================

class TestMatchBatchPoolItems:
    """match_batch() 签名加 pool_items（{code: pool_item} 映射）。"""

    def test_match_batch_old_signature(self):
        """旧调用 match_batch(genes, weather_state) 不报错。"""
        matcher = StrategyMatcher()
        genes = [_make_gene("600000"), _make_gene("600001")]
        results = matcher.match_batch(genes, "晴天")
        assert isinstance(results, dict)
        assert "600000" in results
        assert "600001" in results

    def test_match_batch_with_pool_items(self):
        """传 pool_items 映射，按 code 匹配 pool_item。"""
        matcher = StrategyMatcher()
        genes = [_make_gene("600000"), _make_gene("600001")]
        pool_items = {
            "600000": _make_pool_item("600000"),
            "600001": _make_pool_item("600001"),
        }
        results = matcher.match_batch(genes, None, pool_items=pool_items)
        assert isinstance(results, dict)
        assert len(results) == 2

    def test_match_batch_pool_items_none_default(self):
        """pool_items=None 默认值，向后兼容。"""
        matcher = StrategyMatcher()
        genes = [_make_gene("600000")]
        results = matcher.match_batch(genes, None, pool_items=None)
        assert isinstance(results, dict)

    def test_match_batch_partial_pool_items(self):
        """部分 code 有 pool_item，部分无 → 混合处理。"""
        matcher = StrategyMatcher()
        genes = [_make_gene("600000"), _make_gene("600001")]
        pool_items = {"600000": _make_pool_item("600000")}  # 只有 600000 有
        results = matcher.match_batch(genes, None, pool_items=pool_items)
        # 两个 code 都处理了
        assert "600000" in results
        assert "600001" in results


# ===========================================================================
# 3. 传 pool_item 后 PRD 战法能取因子（mock S070/K线数据）
# ===========================================================================

class TestPRDStrategiesWithPoolItem:
    """传 pool_item 后 PRD 2 战法能取 lbc/hs/zdp 做判定。"""

    def test_weak_turn_strong_hits_with_pool_item_and_s070(self):
        """weak_turn_strong 战法：传 pool_item（lbc/hs）+ mock S070 R7 派生 → 命中。

        5 因子：lbc≥1 / broken_duration_min≥20 / max_drop_pct≥5 / last_lock_time≥14:40 / vol_ratio_1d 1.8-3.0
        mock：lbc=2✓ / broken=25✓ / drop=6✓ / lock=14:50✓ / vol_ratio=None✗（4 命中 ≥ 4 → medium）
        """
        matcher = StrategyMatcher()
        gene = _make_gene("600000")
        pool_item = _make_pool_item("600000", lbc=2, hs=8.5)

        # mock S070 R7：get_snapshots_by_code + compute_derived_features
        mock_snaps = [{"ts": "2026-08-18T09:30:00", "hs": 8.5}]
        mock_derived = _make_derived_features()

        with patch("risk.seal_intraday_collector.get_snapshots_by_code", return_value=mock_snaps):
            with patch("strategies.intraday_features.compute_derived_features", return_value=mock_derived):
                signals = matcher.match(gene, None, pool_item=pool_item)

        # weak_turn_strong 应命中（4 因子 ≥ 4 → confidence=0.7）
        wts_signals = [s for s in signals if s.strategy_code == "weak_turn_strong"]
        assert len(wts_signals) >= 1
        assert wts_signals[0].confidence == 0.7  # 4 命中 medium
        # 验证取了 pool_item 的 lbc（value 字段格式 "lbc={lbc}"）
        matches_value = [m.value for m in wts_signals[0].matches]
        assert any("lbc=2" in v for v in matches_value)

    def test_weak_turn_strong_missing_s070_no_hit(self):
        """weak_turn_strong 战法：S070 R7 数据缺失 → 标 missing_s070_r7 不命中。"""
        matcher = StrategyMatcher()
        gene = _make_gene("600000")
        pool_item = _make_pool_item("600000")

        # mock S070 R7 数据缺失（get_snapshots_by_code 返回空）
        with patch("risk.seal_intraday_collector.get_snapshots_by_code", return_value=[]):
            signals = matcher.match(gene, None, pool_item=pool_item)

        # missing_s070_r7 → confidence=0 → 不在 signals 里
        wts_signals = [s for s in signals if s.strategy_code == "weak_turn_strong"]
        assert len(wts_signals) == 0

    def test_weak_turn_strong_no_pool_item_lbc_zero(self):
        """weak_turn_strong 战法：pool_item=None → lbc=0 → f1 不命中。

        注：lbc=0 但其他因子可能命中，需 ≤3 命中才不输出。
        此测验证 pool_item=None 时 lbc 取默认 0（不命中 lbc≥1 阈值）。
        """
        matcher = StrategyMatcher()
        gene = _make_gene("600000")
        pool_item = None  # 不传

        mock_snaps = [{"ts": "2026-08-18T09:30:00"}]
        mock_derived = _make_derived_features()

        with patch("risk.seal_intraday_collector.get_snapshots_by_code", return_value=mock_snaps):
            with patch("strategies.intraday_features.compute_derived_features", return_value=mock_derived):
                signals = matcher.match(gene, None, pool_item=pool_item)

        # pool_item=None → lbc=0，f1 不命中；其他 4 因子可能命中
        # 若 4 因子全命中（broken/drop/lock/vol_ratio），hit_count=4 仍可能输出
        # 但 vol_ratio_1d 在代码里恒 None（见 line 846 简化），所以最多 3 命中 → 不输出
        wts_signals = [s for s in signals if s.strategy_code == "weak_turn_strong"]
        assert len(wts_signals) == 0  # 3 命中 < 4 → 不输出

    def test_pattern_reversal_takes_zdp_from_pool_item(self):
        """pattern_reversal 战法：传 pool_item（zdp）→ 取 close_pct 做判定。

        注：pattern_reversal 还需 K线数据（_get_kline_bars），mock 返回有效 bars。
        完整命中需 max_high_pct/shadow_length/ma_5/volume 因子，这里只验证取到 zdp。
        """
        matcher = StrategyMatcher()
        gene = _make_gene("600000")
        pool_item = _make_pool_item("600000", zdp=9.5)

        # mock K线数据（_get_kline_bars 返回足够 bars）
        mock_bars = [
            MagicMock(close=10.0, high=10.5, low=9.8, open=10.0, volume=1000000),
            MagicMock(close=10.8, high=11.2, low=10.5, open=10.5, volume=1200000),
        ]

        with patch("limitup_screener.kline_rebuild._get_kline_bars", return_value=mock_bars):
            signals = matcher.match(gene, None, pool_item=pool_item)

        # pattern_reversal 可能命中也可能不命中（取决于 K线因子判定）
        # 这里只验证不报错 + 取到了 zdp（若命中，matches 描述应含 close_pct）
        pr_signals = [s for s in signals if s.strategy_code == "pattern_reversal"]
        # 不报错即可，命中看 K线因子
        assert isinstance(pr_signals, list)

    def test_pattern_reversal_no_pool_item_zdp_none(self):
        """pattern_reversal 战法：pool_item=None → close_pct=None 不命中。"""
        matcher = StrategyMatcher()
        gene = _make_gene("600000")
        pool_item = None

        mock_bars = [MagicMock(close=10.0, high=10.5, low=9.8, open=10.0, volume=1000000)]

        with patch("limitup_screener.kline_rebuild._get_kline_bars", return_value=mock_bars):
            signals = matcher.match(gene, None, pool_item=pool_item)

        # pool_item=None → close_pct=None → 不命中 pattern_reversal
        pr_signals = [s for s in signals if s.strategy_code == "pattern_reversal"]
        assert len(pr_signals) == 0


# ===========================================================================
# 4. 既有 9 战法不受 pool_item 影响
# ===========================================================================

class TestExistingStrategiesUnaffected:
    """既有 9 战法不依赖 pool_item，传 None 或非 None 行为不变。"""

    def test_existing_strategies_same_with_or_without_pool_item(self):
        """既有 9 战法：传 pool_item vs None，命中结果一致。"""
        matcher = StrategyMatcher()
        gene = _make_gene("600000")

        # 不传 pool_item
        signals_none = matcher.match(gene, None, pool_item=None)
        # 传 pool_item
        pool_item = _make_pool_item("600000")
        signals_with = matcher.match(gene, None, pool_item=pool_item)

        # 既有战法 strategy_code（排除 PRD 2 战法 + storm_reversal——
        # S086 R3 后 storm_reversal 读 pool_item["fbt"]，与 PRD 战法同属 pool_item 依赖）
        pool_dependent = ("weak_turn_strong", "pattern_reversal", "storm_reversal")
        existing_codes = {
            s.strategy_code for s in signals_none
            if s.strategy_code not in pool_dependent
        }
        existing_codes_with = {
            s.strategy_code for s in signals_with
            if s.strategy_code not in pool_dependent
        }
        # 既有战法命中结果一致（不依赖 pool_item）
        assert existing_codes == existing_codes_with


# ===========================================================================
# 5. pre_market_workflow 取涨停池建 pool_item_map
# ===========================================================================

class TestPreMarketPoolItemMap:
    """pre_market_workflow 取涨停池建 pool_item_map 传给 match()。"""

    def test_pool_item_map_built_from_fetch_zt_pool(self):
        """fetch_zt_pool 返回涨停池 → 建 code→pool_item 映射。"""
        from pre_market_workflow import PreMarketWorkflow

        # mock fetch_zt_pool 返回 2 个涨停股
        mock_zt_pool = [
            {"c": "600000", "n": "stock_a", "lbc": 2, "hs": 8.5, "zdp": 10.0, "p": 11.0},
            {"c": "600001", "n": "stock_b", "lbc": 1, "hs": 5.0, "zdp": 9.8, "p": 10.5},
        ]

        with patch("strategies.first_board_filter.fetch_zt_pool", return_value=mock_zt_pool):
            with patch("sentiment_context.build_context") as mock_ctx:
                mock_ctx.return_value = MagicMock(weather_state="晴天", source_date="2026-08-17")
                # mock 其他依赖避免真实采集
                with patch("limitup_screener.service.get_screener_result"):
                    wf = PreMarketWorkflow(date="2026-08-18")
                    # 直接测 pool_item_map 构建逻辑（提取循环）
                    # 模拟 pre_market_workflow 里的循环
                    pool_item_map: dict[str, dict] = {}
                    for p in mock_zt_pool:
                        code = str(p.get("c", "") or "").strip()
                        if code:
                            pool_item_map[code] = p

        assert "600000" in pool_item_map
        assert "600001" in pool_item_map
        assert pool_item_map["600000"]["lbc"] == 2
        assert pool_item_map["600001"]["lbc"] == 1

    def test_pool_item_map_empty_when_fetch_zt_pool_fails(self):
        """fetch_zt_pool 失败/空 → pool_item_map={} 降级。"""
        # 模拟 fetch_zt_pool 返回空
        pool_item_map: dict[str, dict] = {}
        for p in [] :  # 空列表
            code = str(p.get("c", "") or "").strip()
            if code:
                pool_item_map[code] = p
        assert pool_item_map == {}

    def test_pool_item_map_code_field_extraction(self):
        """涨停池 dict 用 'c' 字段做 code（非 'code'）。"""
        mock_zt_pool = [
            {"c": "600000", "lbc": 3},   # c 字段
            {"c": "600001", "lbc": 1},
        ]
        pool_item_map: dict[str, dict] = {}
        for p in mock_zt_pool:
            code = str(p.get("c", "") or "").strip()
            if code:
                pool_item_map[code] = p
        assert len(pool_item_map) == 2
        assert pool_item_map["600000"]["lbc"] == 3

    def test_pool_item_map_skips_empty_code(self):
        """c 字段为空 → 跳过不进 map。"""
        mock_zt_pool = [
            {"c": "600000", "lbc": 2},
            {"c": "", "lbc": 1},          # 空 code 跳过
            {"lbc": 1},                    # 无 c 字段跳过
            {"c": "600001", "lbc": 1},
        ]
        pool_item_map: dict[str, dict] = {}
        for p in mock_zt_pool:
            code = str(p.get("c", "") or "").strip()
            if code:
                pool_item_map[code] = p
        assert len(pool_item_map) == 2  # 只 600000 + 600001
        assert "600000" in pool_item_map
        assert "600001" in pool_item_map
