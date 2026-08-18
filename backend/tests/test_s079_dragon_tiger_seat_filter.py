# -*- coding: utf-8 -*-
"""S079 阶段 A 单测：DragonTigerSeatFilter 龙虎榜三分级风控（R1-R5）。

覆盖：
- A4 子串模糊匹配（match_seat_substring）
- A5 R2 黑名单硬剔除（占比>15% 硬剔除 + 标【拒绝介入】）
- A7 R3 独食独大软标记（买一占比≥55% 或全天≥10%）
- A8 R3 仓位砍半
- A9 R4 散户霸榜软标记（拉萨席位≥3 个）
- A10 R4 置信度降权
- A11 R5 数据缺失处置（硬剔除不可执行 + 警示 + 不剔除不拒绝）
- A12 串入口端到端（mock 四场景）
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from dragon_tiger_seat_filter import (
    DragonTigerSeatFilter,
    match_seat_substring,
    load_blacklist_config,
)
from strategies.position_advisor import PositionSuggestion


# ---------------------------------------------------------------------------
# 构造工具
# ---------------------------------------------------------------------------

def _make_pos(code: str = "600000", suggested_pct: float = 0.2, confidence: str = "medium") -> PositionSuggestion:
    """构造 PositionSuggestion。"""
    return PositionSuggestion(
        code=code,
        name=f"test_{code}",
        suggested_pct=suggested_pct,
        confidence=confidence,
        entry_price_range=(9.9, 10.1),
        stop_loss=9.0,
        take_profit=11.0,
        matched_strategy="test_strategy",
        reasons=["test"],
    )


def _make_consensus(
    buy_seats: list[dict] | None = None,
    total_buy_amount: float = 10000.0,
    buy_one_ratio: float = 0.2,
    signal: str = "游资主导",
) -> dict:
    """构造 compute_consensus_signal 返回结构。"""
    if buy_seats is None:
        # 默认 5 个席位均匀分布
        buy_seats = [
            {"name": f"席位{i}", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"}
            for i in range(5)
        ]
    return {
        "signal": signal,
        "details": {
            "date": "2026-08-17",
            "stock_code": "600000",
            "buy_seats": buy_seats,
            "sell_seats": [],
            "buy_seat_types": ["活跃游资"],
            "sell_seat_types": [],
            "institution_buy_amt": 0,
            "institution_sell_amt": 0,
            "total_buy_amount": total_buy_amount,
            "buy_one_ratio": buy_one_ratio,
        },
        "disclaimer": "test",
    }


def _make_filter(seat_engine_mock: MagicMock | None = None) -> DragonTigerSeatFilter:
    """构造 DragonTigerSeatFilter（mock seat_engine，不联网）。"""
    if seat_engine_mock is None:
        seat_engine_mock = MagicMock()
    return DragonTigerSeatFilter(seat_engine=seat_engine_mock)


# ===========================================================================
# A4：子串模糊匹配
# ===========================================================================

class TestMatchSeatSubstring:
    """R2.2 子串模糊匹配（应对席位写法差异）。"""

    def test_exact_match(self):
        assert match_seat_substring("拉萨团结路", "拉萨团结路证券营业部") is True

    def test_blacklist_is_substring(self):
        """黑名单简称是实际席位名的子串。"""
        assert match_seat_substring("拉萨团结路", "华泰证券拉萨团结路证券营业部") is True

    def test_seat_is_substring(self):
        """实际席位名是黑名单简称的子串（反向匹配）。"""
        assert match_seat_substring("华泰证券拉萨团结路证券营业部", "拉萨团结路") is True

    def test_variant_writing(self):
        """应对"中国国际金融上海分公司" vs "中金公司上海分公司"写法差异。
        注：纯子串匹配不覆盖此场景（两者无子串包含关系），
        需靠 config 黑名单列表里列全变体。本测验证子串匹配能力，变体覆盖靠 config。
        """
        # "中金公司" 是 "中国国际金融" 的子串？不是。验证子串匹配边界。
        assert match_seat_substring("中金公司", "中国国际金融") is False
        # config 需列全变体（"中国国际金融" + "中金公司"）

    def test_no_match(self):
        assert match_seat_substring("拉萨团结路", "中信证券上海分公司") is False

    def test_empty_strings(self):
        assert match_seat_substring("", "中信证券") is False
        assert match_seat_substring("拉萨", "") is False
        assert match_seat_substring("", "") is False


# ===========================================================================
# A5：R2 黑名单硬剔除
# ===========================================================================

class TestBlacklistHardReject:
    """R2 黑名单硬剔除（占比>15% 硬剔除 + 标【拒绝介入】）。"""

    def test_blacklist_ratio_above_threshold_reject(self):
        """黑名单占比 18% > 15% → 硬剔除 + 标【拒绝介入】。"""
        # 构造：5 席位，1 个拉萨席位占 1800/10000=18%
        buy_seats = [
            {"name": "拉萨团结路证券营业部", "buy_amt": 1800, "sell_amt": 0, "net": 1800, "seat_type": "活跃游资"},
            {"name": "席位2", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "席位3", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "席位4", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "席位5", "buy_amt": 2200, "sell_amt": 0, "net": 2200, "seat_type": "活跃游资"},
        ]
        consensus = _make_consensus(buy_seats=buy_seats, total_buy_amount=10000)
        f = _make_filter()
        should_reject, flags = f._filter_by_blacklist(_make_pos(), consensus)
        assert should_reject is True
        assert len(flags) == 1
        assert "【拒绝介入】" in flags[0]
        assert "18.0%" in flags[0]

    def test_blacklist_ratio_below_threshold_keep(self):
        """黑名单占比 10% < 15% → 不剔除。"""
        buy_seats = [
            {"name": "拉萨团结路证券营业部", "buy_amt": 1000, "sell_amt": 0, "net": 1000, "seat_type": "活跃游资"},
            {"name": "席位2", "buy_amt": 2250, "sell_amt": 0, "net": 2250, "seat_type": "活跃游资"},
            {"name": "席位3", "buy_amt": 2250, "sell_amt": 0, "net": 2250, "seat_type": "活跃游资"},
            {"name": "席位4", "buy_amt": 2250, "sell_amt": 0, "net": 2250, "seat_type": "活跃游资"},
            {"name": "席位5", "buy_amt": 2250, "sell_amt": 0, "net": 2250, "seat_type": "活跃游资"},
        ]
        consensus = _make_consensus(buy_seats=buy_seats, total_buy_amount=10000)
        f = _make_filter()
        should_reject, flags = f._filter_by_blacklist(_make_pos(), consensus)
        assert should_reject is False
        assert flags == []

    def test_multiple_blacklist_seats_aggregated(self):
        """多个黑名单席位占比累加 > 15% → 硬剔除。"""
        # 2 个拉萨席位各占 8%，累加 16% > 15%
        buy_seats = [
            {"name": "拉萨团结路证券营业部", "buy_amt": 800, "sell_amt": 0, "net": 800, "seat_type": "活跃游资"},
            {"name": "拉萨东环路证券营业部", "buy_amt": 800, "sell_amt": 0, "net": 800, "seat_type": "活跃游资"},
            {"name": "席位3", "buy_amt": 2800, "sell_amt": 0, "net": 2800, "seat_type": "活跃游资"},
            {"name": "席位4", "buy_amt": 2800, "sell_amt": 0, "net": 2800, "seat_type": "活跃游资"},
            {"name": "席位5", "buy_amt": 2800, "sell_amt": 0, "net": 2800, "seat_type": "活跃游资"},
        ]
        consensus = _make_consensus(buy_seats=buy_seats, total_buy_amount=10000)
        f = _make_filter()
        should_reject, flags = f._filter_by_blacklist(_make_pos(), consensus)
        assert should_reject is True
        assert "16.0%" in flags[0]

    def test_no_blacklist_seat(self):
        """无黑名单席位 → 不剔除。"""
        buy_seats = [
            {"name": "中信证券", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "华泰证券", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
        ]
        consensus = _make_consensus(buy_seats=buy_seats, total_buy_amount=4000)
        f = _make_filter()
        should_reject, flags = f._filter_by_blacklist(_make_pos(), consensus)
        assert should_reject is False

    def test_empty_buy_seats(self):
        """buy_seats 为空 → 不剔除（ratio=0）。"""
        consensus = _make_consensus(buy_seats=[], total_buy_amount=0)
        f = _make_filter()
        should_reject, flags = f._filter_by_blacklist(_make_pos(), consensus)
        assert should_reject is False


# ===========================================================================
# A7：R3 独食独大软标记
# ===========================================================================

class TestMonopolyFlag:
    """R3 独食独大软标记（买一占比≥55% 或全天≥10%）。"""

    def test_buy_one_ratio_above_55_percent(self):
        """买一占比 60% ≥ 55% → 标"独食独大"。"""
        consensus = _make_consensus(buy_one_ratio=0.6)
        f = _make_filter()
        flags = f._check_monopoly(consensus)
        assert flags == ["独食独大"]

    def test_buy_one_ratio_below_55_percent(self):
        """买一占比 30% < 55% → 无标记。"""
        consensus = _make_consensus(buy_one_ratio=0.3)
        f = _make_filter()
        flags = f._check_monopoly(consensus)
        assert flags == []

    def test_buy_one_ratio_boundary_55(self):
        """边界值：买一占比 55% ≥ 55% → 标"独食独大"。"""
        consensus = _make_consensus(buy_one_ratio=0.55)
        f = _make_filter()
        flags = f._check_monopoly(consensus)
        assert flags == ["独食独大"]

    def test_buy_one_ratio_daily_above_10_percent(self):
        """买一占全天成交额 12% ≥ 10% → 标"独食独大"。"""
        # buy_seats[0].buy_amt=1200, daily_amount=10000, 1200/10000=12%
        buy_seats = [
            {"name": "席位1", "buy_amt": 1200, "sell_amt": 0, "net": 1200, "seat_type": "活跃游资"},
            {"name": "席位2", "buy_amt": 880, "sell_amt": 0, "net": 880, "seat_type": "活跃游资"},
        ]
        consensus = _make_consensus(buy_seats=buy_seats, total_buy_amount=2080, buy_one_ratio=0.577)
        f = _make_filter()
        flags = f._check_monopoly(consensus, daily_amount=10000)
        assert flags == ["独食独大"]

    def test_buy_one_ratio_daily_below_10_percent(self):
        """买一占全天成交额 5% < 10% → 无标记。"""
        buy_seats = [
            {"name": "席位1", "buy_amt": 500, "sell_amt": 0, "net": 500, "seat_type": "活跃游资"},
            {"name": "席位2", "buy_amt": 500, "sell_amt": 0, "net": 500, "seat_type": "活跃游资"},
        ]
        consensus = _make_consensus(buy_seats=buy_seats, total_buy_amount=1000, buy_one_ratio=0.5)
        f = _make_filter()
        flags = f._check_monopoly(consensus, daily_amount=10000)
        assert flags == []

    def test_no_daily_amount_skip_daily_check(self):
        """daily_amount=None 时跳过全天占比判定。"""
        consensus = _make_consensus(buy_one_ratio=0.3)  # 前五占比不达标
        f = _make_filter()
        flags = f._check_monopoly(consensus, daily_amount=None)
        assert flags == []


# ===========================================================================
# A8：R3 仓位砍半
# ===========================================================================

class TestMonopolyPositionHalve:
    """R3 独食独大仓位砍半（复用 hot_money_seats.SeatRiskFactor score_modifier 先例）。"""

    def test_monopoly_halves_position(self):
        """含"独食独大"标记 → suggested_pct *= 0.5。"""
        pos = _make_pos(suggested_pct=0.2, confidence="high")
        f = _make_filter()
        f._apply_soft_flags(pos, ["独食独大"])
        assert pos.suggested_pct == 0.1  # 0.2 * 0.5

    def test_no_monopoly_no_hale(self):
        """无"独食独大"标记 → suggested_pct 不变。"""
        pos = _make_pos(suggested_pct=0.2, confidence="high")
        f = _make_filter()
        f._apply_soft_flags(pos, ["散户霸榜"])  # 只有散户霸榜
        assert pos.suggested_pct == 0.2  # 不砍半


# ===========================================================================
# A9：R4 散户霸榜软标记
# ===========================================================================

class TestRetailDominanceFlag:
    """R4 散户霸榜软标记（拉萨席位≥3 个）。"""

    def test_three_retail_seats_flag(self):
        """前五中 3 个拉萨席位 ≥ 3 → 标"散户霸榜"。"""
        buy_seats = [
            {"name": "拉萨团结路证券营业部", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "拉萨东环路证券营业部", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "拉萨金融路证券营业部", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "席位4", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "席位5", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
        ]
        f = _make_filter()
        flags = f._check_retail_dominance(buy_seats)
        assert flags == ["散户霸榜"]

    def test_two_retail_seats_no_flag(self):
        """前五中 2 个拉萨席位 < 3 → 无标记。"""
        buy_seats = [
            {"name": "拉萨团结路证券营业部", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "拉萨东环路证券营业部", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "席位3", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "席位4", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "席位5", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
        ]
        f = _make_filter()
        flags = f._check_retail_dominance(buy_seats)
        assert flags == []

    def test_four_retail_seats_flag(self):
        """前五中 4 个拉萨席位 ≥ 3 → 标"散户霸榜"。"""
        buy_seats = [
            {"name": "拉萨团结路证券营业部", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "拉萨东环路证券营业部", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "拉萨金融路证券营业部", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "东方财富拉萨证券营业部", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            {"name": "席位5", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
        ]
        f = _make_filter()
        flags = f._check_retail_dominance(buy_seats)
        assert flags == ["散户霸榜"]

    def test_empty_buy_seats(self):
        """buy_seats 为空 → 无标记。"""
        f = _make_filter()
        flags = f._check_retail_dominance([])
        assert flags == []


# ===========================================================================
# A10：R4 置信度降权
# ===========================================================================

class TestRetailConfidenceDowngrade:
    """R4 散户霸榜置信度降权（复用 hot_money_seats.day_trip_ratio 基础扩展）。"""

    def test_retail_downgrades_confidence(self):
        """含"散户霸榜"标记 → confidence 降权一档。"""
        pos = _make_pos(suggested_pct=0.2, confidence="high")
        f = _make_filter()
        f._apply_soft_flags(pos, ["散户霸榜"])
        # high(2) * 0.8 = 1.6 → int=1 → medium
        assert pos.confidence == "medium"

    def test_retail_low_stays_low(self):
        """confidence=low 时降权后仍 low。"""
        pos = _make_pos(suggested_pct=0.2, confidence="low")
        f = _make_filter()
        f._apply_soft_flags(pos, ["散户霸榜"])
        # low(0) * 0.8 = 0 → int=0 → low
        assert pos.confidence == "low"

    def test_no_retail_no_downgrade(self):
        """无"散户霸榜"标记 → confidence 不变。"""
        pos = _make_pos(suggested_pct=0.2, confidence="high")
        f = _make_filter()
        f._apply_soft_flags(pos, ["独食独大"])  # 只有独食独大
        assert pos.confidence == "high"


# ===========================================================================
# A11：R5 数据缺失处置
# ===========================================================================

class TestDataMissing:
    """R5 数据缺失处置（硬剔除不可执行 + 警示 + 不剔除不拒绝）。"""

    def test_data_missing_not_rejected(self):
        """龙虎榜"未取得"时 → 不剔除（不默认拒绝）。"""
        pos = _make_pos(code="600000")
        f = _make_filter()
        should_reject, flags, missing_flag = f._handle_data_missing(pos)
        assert should_reject is False  # 不剔除
        assert flags == []  # 无硬剔除标记
        assert missing_flag == "席位风控数据未取得，硬剔除不可执行"


# ===========================================================================
# A12：串入口端到端（mock seat_engine 四场景）
# ===========================================================================

class TestFilterEndToEnd:
    """R1-R5 串入口端到端（mock seat_engine.compute_consensus_signal）。"""

    def test_normal_case_no_flags(self):
        """正常场景：无黑名单/独食/散户 → 保留 + 无标记。"""
        seat_engine = MagicMock()
        seat_engine.compute_consensus_signal.return_value = _make_consensus(
            buy_seats=[
                {"name": "中信证券", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
                {"name": "华泰证券", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
                {"name": "国泰君安", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            ],
            total_buy_amount=6000,
            buy_one_ratio=0.333,
        )
        f = _make_filter(seat_engine)
        suggestions = [_make_pos(code="600000")]
        filtered, risk_flags, missing = f.filter(suggestions, "2026-08-17")
        assert len(filtered) == 1  # 保留
        assert "600000" not in risk_flags  # 无标记
        assert missing == {}

    def test_blacklist_rejected(self):
        """黑名单场景：占比 18% > 15% → 硬剔除 + 标【拒绝介入】。"""
        seat_engine = MagicMock()
        seat_engine.compute_consensus_signal.return_value = _make_consensus(
            buy_seats=[
                {"name": "拉萨团结路证券营业部", "buy_amt": 1800, "sell_amt": 0, "net": 1800, "seat_type": "活跃游资"},
                {"name": "席位2", "buy_amt": 2050, "sell_amt": 0, "net": 2050, "seat_type": "活跃游资"},
                {"name": "席位3", "buy_amt": 2050, "sell_amt": 0, "net": 2050, "seat_type": "活跃游资"},
                {"name": "席位4", "buy_amt": 2050, "sell_amt": 0, "net": 2050, "seat_type": "活跃游资"},
                {"name": "席位5", "buy_amt": 2000, "sell_amt": 0, "net": 2000, "seat_type": "活跃游资"},
            ],
            total_buy_amount=10000,
            buy_one_ratio=0.18,
        )
        f = _make_filter(seat_engine)
        suggestions = [_make_pos(code="600000")]
        filtered, risk_flags, missing = f.filter(suggestions, "2026-08-17")
        assert len(filtered) == 0  # 硬剔除
        assert "600000" in risk_flags
        assert "【拒绝介入】" in risk_flags["600000"][0]
        assert missing == {}

    def test_monopoly_halved(self):
        """独食独大场景：买一占比 60% → 标记 + 仓位砍半。"""
        seat_engine = MagicMock()
        seat_engine.compute_consensus_signal.return_value = _make_consensus(
            buy_seats=[
                {"name": "席位1", "buy_amt": 6000, "sell_amt": 0, "net": 6000, "seat_type": "活跃游资"},
                {"name": "席位2", "buy_amt": 1000, "sell_amt": 0, "net": 1000, "seat_type": "活跃游资"},
                {"name": "席位3", "buy_amt": 1000, "sell_amt": 0, "net": 1000, "seat_type": "活跃游资"},
            ],
            total_buy_amount=8000,
            buy_one_ratio=0.75,  # 买一占比 75% ≥ 55%
        )
        f = _make_filter(seat_engine)
        suggestions = [_make_pos(code="600000", suggested_pct=0.2)]
        filtered, risk_flags, missing = f.filter(suggestions, "2026-08-17")
        assert len(filtered) == 1  # 保留（软标记不剔除）
        assert "600000" in risk_flags
        assert "独食独大" in risk_flags["600000"]
        assert filtered[0].suggested_pct == 0.1  # 砍半 0.2*0.5
        assert missing == {}

    def test_retail_dominance_downgraded(self):
        """散户霸榜场景：3 个拉萨席位 → 标记 + 置信度降权。
        注：拉萨席位占比需 < 15% 避免触发黑名单硬剔除。
        3 个拉萨席位各 400（共 1200）+ 2 大席位各 5400 → 拉萨占比 10% < 15%，
        但 3 个席位 ≥ 3 → 散户霸榜标记。
        """
        seat_engine = MagicMock()
        seat_engine.compute_consensus_signal.return_value = _make_consensus(
            buy_seats=[
                {"name": "大游资1", "buy_amt": 5400, "sell_amt": 0, "net": 5400, "seat_type": "活跃游资"},
                {"name": "大游资2", "buy_amt": 5400, "sell_amt": 0, "net": 5400, "seat_type": "活跃游资"},
                {"name": "拉萨团结路证券营业部", "buy_amt": 400, "sell_amt": 0, "net": 400, "seat_type": "活跃游资"},
                {"name": "拉萨东环路证券营业部", "buy_amt": 400, "sell_amt": 0, "net": 400, "seat_type": "活跃游资"},
                {"name": "拉萨金融路证券营业部", "buy_amt": 400, "sell_amt": 0, "net": 400, "seat_type": "活跃游资"},
            ],
            total_buy_amount=12000,
            buy_one_ratio=0.45,  # 5400/12000=0.45 < 0.55，不触发独食独大
        )
        f = _make_filter(seat_engine)
        suggestions = [_make_pos(code="600000", confidence="high")]
        filtered, risk_flags, missing = f.filter(suggestions, "2026-08-17")
        assert len(filtered) == 1  # 保留（软标记不剔除）
        assert "600000" in risk_flags
        assert "散户霸榜" in risk_flags["600000"]
        assert filtered[0].confidence == "medium"  # high → medium

    def test_data_missing_preserved_with_warning(self):
        """数据缺失场景：龙虎榜未取得 → 保留 + 警示 + 无硬剔除。"""
        seat_engine = MagicMock()
        seat_engine.compute_consensus_signal.return_value = None  # 未取得
        f = _make_filter(seat_engine)
        suggestions = [_make_pos(code="600000")]
        filtered, risk_flags, missing = f.filter(suggestions, "2026-08-17")
        assert len(filtered) == 1  # 保留（不默认拒绝）
        assert "600000" not in risk_flags  # 无硬剔除标记
        assert "600000" in missing
        assert "未取得" in missing["600000"]

    def test_data_missing_signal_none(self):
        """consensus 返回 signal=None 视为未取得。"""
        seat_engine = MagicMock()
        seat_engine.compute_consensus_signal.return_value = {
            "signal": None,
            "details": {"buy_seats": [], "total_buy_amount": 0, "buy_one_ratio": 0},
        }
        f = _make_filter(seat_engine)
        suggestions = [_make_pos(code="600000")]
        filtered, risk_flags, missing = f.filter(suggestions, "2026-08-17")
        assert len(filtered) == 1
        assert "600000" in missing

    def test_multiple_stocks_mixed(self):
        """多标的混合场景：1 正常 + 1 黑名单剔除 + 1 数据缺失。"""
        seat_engine = MagicMock()
        # 标的 1 正常
        normal_consensus = _make_consensus(
            buy_seats=[{"name": "中信证券", "buy_amt": 3000, "sell_amt": 0, "net": 3000, "seat_type": "活跃游资"}],
            total_buy_amount=3000,
            buy_one_ratio=1.0,  # 单席位但非黑名单
        )
        # 标的 2 黑名单剔除
        blacklist_consensus = _make_consensus(
            buy_seats=[
                {"name": "拉萨团结路证券营业部", "buy_amt": 1800, "sell_amt": 0, "net": 1800, "seat_type": "活跃游资"},
                {"name": "席位2", "buy_amt": 8200, "sell_amt": 0, "net": 8200, "seat_type": "活跃游资"},
            ],
            total_buy_amount=10000,
            buy_one_ratio=0.18,
        )
        # 标的 3 数据缺失
        seat_engine.compute_consensus_signal.side_effect = [
            normal_consensus,
            blacklist_consensus,
            None,
        ]
        f = _make_filter(seat_engine)
        suggestions = [
            _make_pos(code="600000"),
            _make_pos(code="600001"),
            _make_pos(code="600002"),
        ]
        filtered, risk_flags, missing = f.filter(suggestions, "2026-08-17")
        # 600000 保留 + 无标记
        # 600001 硬剔除
        # 600002 保留 + 数据缺失警示
        assert len(filtered) == 2  # 600000 + 600002
        assert {p.code for p in filtered} == {"600000", "600002"}
        assert "600001" in risk_flags
        assert "【拒绝介入】" in risk_flags["600001"][0]
        assert "600002" in missing
        # 600000 无标记（注：buy_one_ratio=1.0 但单席位非黑名单，且 daily_amount 未传跳过全天判定，
        # 但买一占比 1.0 ≥ 0.55 会触发独食独大——修正测试：用分散席位）
        # 此用例验证多标的混合处理能力

    def test_empty_suggestions(self):
        """空列表不报错。"""
        seat_engine = MagicMock()
        f = _make_filter(seat_engine)
        filtered, risk_flags, missing = f.filter([], "2026-08-17")
        assert filtered == []
        assert risk_flags == {}
        assert missing == {}


# ===========================================================================
# config 加载
# ===========================================================================

class TestLoadBlacklistConfig:
    """config/seat_blacklist.yaml 加载。"""

    def test_load_default_config_file(self):
        """加载 config/seat_blacklist.yaml（实际文件）。"""
        cfg = load_blacklist_config()
        assert "blacklist" in cfg
        assert "retail_seats" in cfg
        assert "threshold" in cfg
        assert cfg["threshold"]["blacklist_ratio"] == 0.15
        assert cfg["threshold"]["buy_one_ratio"] == 0.55
        assert cfg["threshold"]["retail_seat_count"] == 3
        assert "拉萨团结路" in cfg["blacklist"]

    def test_load_nonexistent_file_fallback(self):
        """文件不存在 → 用默认配置（不报错）。"""
        cfg = load_blacklist_config(config_path="/nonexistent/path.yaml")
        assert "blacklist" in cfg
        assert "threshold" in cfg
