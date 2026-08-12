# -*- coding: utf-8 -*-
"""S053 炸板后溢价因子修复测试。

覆盖：
- R2 _compute_rebound_rate：zb 空/zt_next 缺/正常/全回封 四态
- R2 _fetch_zt_next_pool：mock em_zt_topic_pool
- R3 break_reseal match：zt_count_250d 黄金区 [3,5] + 封板率>=80
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from limitup_screener.service import _compute_rebound_rate, _fetch_zt_next_pool
from models.market_snapshot import ZTPoolItem
from limitup_screener.models import GeneScore


class TestR2ComputeReboundRate:
    """R2：zb 次日回封率计算。"""

    def test_zb_empty_returns_zero_no_missing(self):
        """4a：zb 空 → (0.0, [])，非 missing。"""
        rate, missing = _compute_rebound_rate([], [])
        assert rate == 0.0
        assert missing == []

    def test_zb_empty_with_zt_next_still_zero(self):
        """zb 空时 zt_next 有数据也返 0（无炸板何来回封）。"""
        rate, missing = _compute_rebound_rate([], [ZTPoolItem(code="001")])
        assert rate == 0.0
        assert missing == []

    def test_zt_next_none_returns_zero_with_missing(self):
        """4b：zt_next None → (0.0, ['炸板后溢价'])。"""
        zb = [ZTPoolItem(code="001"), ZTPoolItem(code="002")]
        rate, missing = _compute_rebound_rate(zb, None)
        assert rate == 0.0
        assert "炸板后溢价" in missing

    def test_zt_next_empty_returns_zero_with_missing(self):
        """zt_next 空列表 → missing。"""
        zb = [ZTPoolItem(code="001")]
        rate, missing = _compute_rebound_rate(zb, [])
        assert rate == 0.0
        assert "炸板后溢价" in missing

    def test_normal_partial_reseal(self):
        """正常：zb 2 只，zt_next 含 1 只回封 → wilson 下界 > 0。"""
        zb = [ZTPoolItem(code="001"), ZTPoolItem(code="002")]
        zt_next = [ZTPoolItem(code="001"), ZTPoolItem(code="999")]
        rate, missing = _compute_rebound_rate(zb, zt_next)
        assert missing == []
        assert rate > 0
        assert rate <= 50  # 1/2 回封，wilson 下界应 < 50

    def test_full_reseal_higher_than_partial(self):
        """全回封率 > 部分回封。"""
        zb = [ZTPoolItem(code="001"), ZTPoolItem(code="002")]
        partial = _compute_rebound_rate(zb, [ZTPoolItem(code="001")])[0]
        full = _compute_rebound_rate(zb, [ZTPoolItem(code="001"), ZTPoolItem(code="002")])[0]
        assert full > partial


class TestR2FetchZtNextPool:
    """R2：_fetch_zt_next_pool 拉 T+1 zt 池。"""

    def test_returns_pool_when_next_day_has_data(self):
        """T+1 有数据 → 返回非空列表。"""
        with patch("limitup_screener.service.astock") as mock_astock:
            mock_astock.em_zt_topic_pool.return_value = [{"c": "001"}, {"c": "002"}]
            result = _fetch_zt_next_pool("20260811")
            assert len(result) == 2

    def test_returns_empty_when_all_next_days_empty(self):
        """T+1 ~ T+7 全空 → 返空。"""
        with patch("limitup_screener.service.astock") as mock_astock:
            mock_astock.em_zt_topic_pool.return_value = []
            result = _fetch_zt_next_pool("20260811")
            assert result == []

    def test_skips_empty_days_finds_next_trading_day(self):
        """跳过空日（周末/节假日）找到下一交易日。"""
        call_count = [0]
        def mock_pool(*args):
            call_count[0] += 1
            return [] if call_count[0] < 3 else [{"c": "001"}]
        with patch("limitup_screener.service.astock") as mock_astock:
            mock_astock.em_zt_topic_pool.side_effect = mock_pool
            result = _fetch_zt_next_pool("20260811")
            assert len(result) == 1
            assert call_count[0] == 3  # 前 2 日空，第 3 日有

    def test_invalid_date_returns_empty(self):
        """非法日期 → 返空。"""
        result = _fetch_zt_next_pool("invalid")
        assert result == []


class TestR3BreakResealMatch:
    """R3：break_reseal match 改 zt_count 黄金区。"""

    def _make_gene(self, zt_count: int, seal_rate: float) -> GeneScore:
        return GeneScore(
            code="001",
            name="测试",
            total_score=55.0,
            factors={"次日溢价率": 30, "红盘率": 50, "封板率": seal_rate,
                     "炸板后溢价": 0, "涨停频次": 10},
            wilson_adjusted=50.0,
            qualify=True,
            high_gene=False,
            last_zt_dates=[],
            zt_count_250d=zt_count,
        )

    def test_break_reseal_hits_golden_zone(self):
        """zt_count=4 且 封板率>=80 → 命中。"""
        from limitup_strategy import match_strategies
        gene = self._make_gene(zt_count=4, seal_rate=85)
        signals = match_strategies("001", gene)
        br = next((s for s in signals if s.strategy_code == "break_reseal"), None)
        assert br is not None
        assert "黄金区" in br.matches[0].condition or "封板能力" in br.matches[0].condition

    def test_break_reseal_misses_low_zt_count(self):
        """zt_count=2（低于黄金区）→ 不命中。"""
        from limitup_strategy import match_strategies
        gene = self._make_gene(zt_count=2, seal_rate=85)
        signals = match_strategies("001", gene)
        br = next((s for s in signals if s.strategy_code == "break_reseal"), None)
        assert br is None

    def test_break_reseal_misses_high_zt_count(self):
        """zt_count=8（高于黄金区，过劳）→ 不命中。"""
        from limitup_strategy import match_strategies
        gene = self._make_gene(zt_count=8, seal_rate=85)
        signals = match_strategies("001", gene)
        br = next((s for s in signals if s.strategy_code == "break_reseal"), None)
        assert br is None

    def test_break_reseal_misses_low_seal_rate(self):
        """封板率 < 80 → 不命中。"""
        from limitup_strategy import match_strategies
        gene = self._make_gene(zt_count=4, seal_rate=70)
        signals = match_strategies("001", gene)
        br = next((s for s in signals if s.strategy_code == "break_reseal"), None)
        assert br is None

    def test_break_reseal_boundary_zt_3_and_5(self):
        """黄金区边界 zt=3 和 zt=5 都命中。"""
        from limitup_strategy import match_strategies
        for zc in [3, 5]:
            gene = self._make_gene(zt_count=zc, seal_rate=80)
            signals = match_strategies("001", gene)
            br = next((s for s in signals if s.strategy_code == "break_reseal"), None)
            assert br is not None, f"zt_count={zc} 应命中"
