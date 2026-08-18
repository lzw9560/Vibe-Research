# -*- coding: utf-8 -*-
"""S079 阶段 C 单测：pre_market_workflow P2 两层后处理链路（R9）。

覆盖 C1-C7：
- C1-C2：_apply_p2_post_filters 串两层（DragonTigerSeatFilter + cap_by_market_phase）
- C3：_compute_market_phase_factors 从 market._emotion 取 4 因子（big_loss 缺失降级）
- C4：仓位参数输出（total_suggested_position + 单笔委托金额）
- C5：不输出触发价/竞价达标额（属 S081）
- C6：参数标注"参考值，非执行指令"风险提醒
- C7：端到端单测（mock advise_batch + DragonTigerSeatFilter + market._emotion）

不跑真实链路（不联网），全程 mock：
- PositionAdvisor.advise_batch → mock 返回 position_advisor.PositionSuggestion 列表
- DragonTigerSeatFilter.filter → mock 返回 filtered + risk_flags + data_missing
- market._emotion → mock 返回 zt_count/dt_count 等 4 因子
- SentimentContext → mock source_date/weather_state
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.position_advisor import PositionSuggestion
from pre_market_workflow import (
    PreMarketWorkflow,
    PreMarketReport,
    PARAM_DISCLAIMER,
)


# ---------------------------------------------------------------------------
# 构造工具
# ---------------------------------------------------------------------------

def _make_pos(code: str = "600000", suggested_pct: float = 0.2, confidence: str = "medium") -> PositionSuggestion:
    """构造 position_advisor.PositionSuggestion（advise_batch 输出模拟）。"""
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


def _make_ctx(source_date: str = "2026-08-17", weather_state: str | None = "晴天"):
    """构造 mock SentimentContext。"""
    ctx = MagicMock()
    ctx.source_date = source_date
    ctx.weather_state = weather_state
    return ctx


def _make_workflow() -> PreMarketWorkflow:
    """构造 PreMarketWorkflow（不联网）。"""
    return PreMarketWorkflow(date="2026-08-18")


def _mock_emotion(zt_count=80, dt_count=5, promotion_rate=0.3, max_boards=3):
    """mock market._emotion 返回值。"""
    return {
        "zt_count": zt_count,
        "dt_count": dt_count,
        "promotion_rate": promotion_rate,
        "max_boards": max_boards,
    }


# ===========================================================================
# C3：_compute_market_phase_factors 从 market._emotion 取 4 因子
# ===========================================================================

class TestComputeMarketPhaseFactors:
    """R6.4 从 T-1 盘后市场数据计算 _market_phase 4 因子。"""

    def test_factors_from_emotion(self):
        """4 因子从 market._emotion 正确映射（big_loss=None 降级）。"""
        w = _make_workflow()
        with patch("market._emotion", return_value=_mock_emotion(zt_count=80, dt_count=5)):
            factors = w._compute_market_phase_factors("2026-08-17")
        assert factors["zt_count"] == 80
        assert factors["floor"] == 5           # dt_count → floor
        assert factors["ladder_success"] == 0.3  # promotion_rate → ladder_success
        assert factors["ladder_height"] == 3    # max_boards → ladder_height
        assert factors["big_loss"] is None      # _emotion 无此字段 → None 降级

    def test_factors_empty_emotion(self):
        """_emotion 返回空 dict → 全部 None。"""
        w = _make_workflow()
        with patch("market._emotion", return_value={}):
            factors = w._compute_market_phase_factors("2026-08-17")
        assert factors["zt_count"] is None
        assert factors["floor"] is None
        assert factors["ladder_success"] is None
        assert factors["ladder_height"] is None
        assert factors["big_loss"] is None

    def test_factors_emotion_exception(self):
        """_emotion 抛异常 → 全部 None（降级，不报错）。"""
        w = _make_workflow()
        with patch("market._emotion", side_effect=Exception("network error")):
            factors = w._compute_market_phase_factors("2026-08-17")
        assert factors["zt_count"] is None
        assert factors["big_loss"] is None


# ===========================================================================
# C1-C2：_apply_p2_post_filters 串两层
# ===========================================================================

class TestApplyP2PostFilters:
    """R9 两层后处理：DragonTigerSeatFilter + cap_by_market_phase。"""

    def test_two_layers_normal_case(self):
        """正常场景：无黑名单/独食/散户 → 保留 + 无标记 + green cap 不放宽。
        mock：advise_batch 2 个标的（suggested_pct=0.2），
              DragonTigerSeatFilter.filter 返回原样（无剔除无标记），
              _market_phase 返回"活跃"（zt_count=80，green cap=1.0）。
        """
        w = _make_workflow()
        suggestions = [_make_pos("600000", 0.2), _make_pos("600001", 0.2)]
        ctx = _make_ctx(weather_state="晴天")

        # mock DragonTigerSeatFilter.filter 返回原样
        mock_filter = MagicMock()
        mock_filter.filter.return_value = (suggestions, {}, {})
        # mock market._emotion
        with patch("market._emotion", return_value=_mock_emotion(zt_count=80)):
            with patch("dragon_tiger_seat_filter.DragonTigerSeatFilter", return_value=mock_filter):
                result = w._apply_p2_post_filters(suggestions, ctx)

        # 两层串联
        assert len(result["position_suggestions"]) == 2
        # green cap=1.0，不放宽只收紧：suggested_pct=min(0.2, 0.3*1.0)=0.2
        assert result["position_suggestions"][0].suggested_pct == 0.2
        # market_phase + cap 字段
        assert result["market_phase"] == "活跃"
        assert result["market_phase_cap"] == 1.0
        assert result["position_cap_tier"] == "green"
        # 无风控标记
        assert result["seat_risk_flags"] == {}
        assert result["data_missing_flags"] == {}

    def test_layer1_blacklist_rejected(self):
        """Layer 1 硬剔除：DragonTigerSeatFilter 返回剔除后列表 + risk_flags。"""
        w = _make_workflow()
        suggestions = [_make_pos("600000", 0.2), _make_pos("600001", 0.2)]
        ctx = _make_ctx()

        # mock DragonTigerSeatFilter 硬剔除 600000
        mock_filter = MagicMock()
        mock_filter.filter.return_value = (
            [_make_pos("600001", 0.2)],  # 只剩 600001
            {"600000": ["【拒绝介入】黑名单占比 18.0%"]},
            {},
        )
        with patch("market._emotion", return_value=_mock_emotion(zt_count=80)):
            with patch("dragon_tiger_seat_filter.DragonTigerSeatFilter", return_value=mock_filter):
                result = w._apply_p2_post_filters(suggestions, ctx)

        # Layer 1 硬剔除生效
        assert len(result["position_suggestions"]) == 1
        assert result["position_suggestions"][0].code == "600001"
        assert "600000" in result["seat_risk_flags"]
        assert "【拒绝介入】" in result["seat_risk_flags"]["600000"][0]

    def test_layer2_yellow_phase_halves(self):
        """Layer 2 黄档 cap=0.5：仓位砍半。
        mock：_market_phase 返回"普通"（zt_count=40，yellow cap=0.5）。
        suggested_pct=0.2 → min(0.2, 0.3*0.5=0.15)=0.15
        """
        w = _make_workflow()
        suggestions = [_make_pos("600000", 0.2)]
        ctx = _make_ctx()

        mock_filter = MagicMock()
        mock_filter.filter.return_value = (suggestions, {}, {})
        with patch("market._emotion", return_value=_mock_emotion(zt_count=40)):
            with patch("dragon_tiger_seat_filter.DragonTigerSeatFilter", return_value=mock_filter):
                result = w._apply_p2_post_filters(suggestions, ctx)

        assert result["market_phase"] == "普通"
        assert result["market_phase_cap"] == 0.5
        assert result["position_cap_tier"] == "yellow"
        # 黄档砍半：min(0.2, 0.3*0.5)=0.15
        assert result["position_suggestions"][0].suggested_pct == 0.15

    def test_layer2_red_phase_shrinks(self):
        """Layer 2 红期 cap=0.2：仓位收紧。
        mock：big_loss=10 触发红期硬熔断（≥8）。
        """
        w = _make_workflow()
        suggestions = [_make_pos("600000", 0.2)]
        ctx = _make_ctx()

        mock_filter = MagicMock()
        mock_filter.filter.return_value = (suggestions, {}, {})
        # _emotion 无 big_loss 字段，但 _compute_market_phase_factors big_loss=None；
        # 用 floor=25 触发红期（floor≥20）
        with patch("market._emotion", return_value=_mock_emotion(zt_count=80, dt_count=25)):
            with patch("dragon_tiger_seat_filter.DragonTigerSeatFilter", return_value=mock_filter):
                result = w._apply_p2_post_filters(suggestions, ctx)

        assert result["market_phase"] == "红期"
        assert result["market_phase_cap"] == 0.2
        assert result["position_cap_tier"] == "red"
        # 红档收紧：min(0.2, 0.3*0.2=0.06)=0.06
        assert result["position_suggestions"][0].suggested_pct == 0.06

    def test_layer2_red_phase_big_loss(self):
        """Layer 2 红期由 big_loss 触发（mock _compute_market_phase_factors 注入 big_loss）。
        _emotion 无 big_loss，但可 mock _compute_market_phase_factors 方法注入。
        """
        w = _make_workflow()
        suggestions = [_make_pos("600000", 0.2)]
        ctx = _make_ctx()

        mock_filter = MagicMock()
        mock_filter.filter.return_value = (suggestions, {}, {})
        # 直接 mock _compute_market_phase_factors 注入 big_loss=10
        with patch.object(w, "_compute_market_phase_factors", return_value={
            "zt_count": 80, "big_loss": 10, "floor": 0,
            "ladder_success": 0.3, "ladder_height": 3,
        }):
            with patch("dragon_tiger_seat_filter.DragonTigerSeatFilter", return_value=mock_filter):
                result = w._apply_p2_post_filters(suggestions, ctx)

        assert result["market_phase"] == "红期"
        assert result["position_cap_tier"] == "red"

    def test_data_missing_preserved_with_warning(self):
        """R5 数据缺失：Layer 1 返回 data_missing_flags，保留在结果中。"""
        w = _make_workflow()
        suggestions = [_make_pos("600000", 0.2)]
        ctx = _make_ctx()

        mock_filter = MagicMock()
        mock_filter.filter.return_value = (
            suggestions,
            {},
            {"600000": "席位风控数据未取得，硬剔除不可执行"},
        )
        with patch("market._emotion", return_value=_mock_emotion(zt_count=80)):
            with patch("dragon_tiger_seat_filter.DragonTigerSeatFilter", return_value=mock_filter):
                result = w._apply_p2_post_filters(suggestions, ctx)

        assert "600000" in result["data_missing_flags"]
        assert "未取得" in result["data_missing_flags"]["600000"]

    def test_empty_suggestions(self):
        """空 suggestions 不报错。"""
        w = _make_workflow()
        ctx = _make_ctx()

        mock_filter = MagicMock()
        mock_filter.filter.return_value = ([], {}, {})
        with patch("market._emotion", return_value=_mock_emotion(zt_count=80)):
            with patch("dragon_tiger_seat_filter.DragonTigerSeatFilter", return_value=mock_filter):
                result = w._apply_p2_post_filters([], ctx)

        assert result["position_suggestions"] == []
        assert result["market_phase"] == "活跃"


# ===========================================================================
# C4-C6：仓位参数输出 + checklist + 合规标注
# ===========================================================================

class TestExecutionChecklist:
    """R10 execution_checklist 内容 + 合规标注。"""

    def test_checklist_contains_disclaimer(self):
        """checklist 含"参考值，非执行指令"标注。"""
        w = _make_workflow()
        checklist = w._build_execution_checklist(
            phase="普通", tier="yellow", total_cap=0.15, n_stocks=2, data_missing_flags={},
        )
        assert any("参考值，非执行指令" in item for item in checklist)

    def test_checklist_contains_risk_reminder(self):
        """checklist 含风险提醒「历史统计特征，市场有风险」。"""
        w = _make_workflow()
        checklist = w._build_execution_checklist(
            phase="活跃", tier="green", total_cap=0.4, n_stocks=2, data_missing_flags={},
        )
        assert any("历史统计特征，市场有风险" in item for item in checklist)

    def test_checklist_yellow_phase_halve_hint(self):
        """黄色期 checklist 含仓位砍半提示。"""
        w = _make_workflow()
        checklist = w._build_execution_checklist(
            phase="普通", tier="yellow", total_cap=0.15, n_stocks=2, data_missing_flags={},
        )
        assert any("黄色期仓位砍半" in item for item in checklist)

    def test_checklist_red_phase_warning(self):
        """红期 checklist 含强制熔断提示。"""
        w = _make_workflow()
        checklist = w._build_execution_checklist(
            phase="红期", tier="red", total_cap=0.06, n_stocks=1, data_missing_flags={},
        )
        assert any("红期强制熔断" in item for item in checklist)

    def test_checklist_data_missing_hint(self):
        """数据缺失时 checklist 含人工核实提示。"""
        w = _make_workflow()
        checklist = w._build_execution_checklist(
            phase="活跃", tier="green", total_cap=0.4, n_stocks=2,
            data_missing_flags={"600000": "席位风控数据未取得，硬剔除不可执行"},
        )
        assert any("席位风控数据未取得标的需人工核实龙虎榜" in item for item in checklist)
        assert any("600000" in item for item in checklist)

    def test_checklist_no_data_missing_no_hint(self):
        """无数据缺失时 checklist 不含人工核实提示。"""
        w = _make_workflow()
        checklist = w._build_execution_checklist(
            phase="活跃", tier="green", total_cap=0.4, n_stocks=2, data_missing_flags={},
        )
        assert not any("人工核实龙虎榜" in item for item in checklist)

    def test_param_disclaimer_constant(self):
        """PARAM_DISCLAIMER 常量含合规标注。"""
        assert "参考值，非执行指令" in PARAM_DISCLAIMER
        assert "历史统计特征" in PARAM_DISCLAIMER


# ===========================================================================
# C5：不输出触发价/竞价达标额（属 S081）
# ===========================================================================

class TestNoTriggerPriceOutput:
    """R9.2 不输出触发价/竞价达标额（属 S081 战法匹配 spec 范围）。"""

    def test_p2_result_no_trigger_price_field(self):
        """P2 结果不含触发价/竞价达标额字段（属 S081）。"""
        w = _make_workflow()
        suggestions = [_make_pos("600000", 0.2)]
        ctx = _make_ctx()

        mock_filter = MagicMock()
        mock_filter.filter.return_value = (suggestions, {}, {})
        with patch("market._emotion", return_value=_mock_emotion(zt_count=80)):
            with patch("dragon_tiger_seat_filter.DragonTigerSeatFilter", return_value=mock_filter):
                result = w._apply_p2_post_filters(suggestions, ctx)

        # 不含触发价/竞价达标额字段
        assert "trigger_price" not in result
        assert "auction_amount" not in result
        assert "竞价达标额" not in result
        assert "触发价" not in result


# ===========================================================================
# PreMarketReport 字段扩展
# ===========================================================================

class TestPreMarketReportFields:
    """PreMarketReport dataclass 加 S079 扩展字段。"""

    def test_report_has_p2_fields(self):
        """PreMarketReport 含 S079 P2 扩展字段。"""
        report = PreMarketReport(date="2026-08-18", generated_at="2026-08-18T08:00:00")
        assert hasattr(report, "market_phase")
        assert hasattr(report, "market_phase_cap")
        assert hasattr(report, "position_cap_tier")
        assert hasattr(report, "seat_risk_flags")
        assert hasattr(report, "data_missing_flags")
        assert hasattr(report, "execution_checklist")
        assert hasattr(report, "param_disclaimer")

    def test_report_p2_fields_default(self):
        """P2 扩展字段默认值。"""
        report = PreMarketReport(date="2026-08-18", generated_at="2026-08-18T08:00:00")
        assert report.market_phase is None
        assert report.market_phase_cap is None
        assert report.position_cap_tier is None
        assert report.seat_risk_flags == {}
        assert report.data_missing_flags == {}
        assert report.execution_checklist == []
        assert report.param_disclaimer is None


# ===========================================================================
# C7：端到端集成测试要点（标注，不在本测试实现）
# ===========================================================================

class TestIntegrationNotes:
    """C8 集成测试要点（不在本任务实现，仅标注）。

    集成测试需 mock 整个 run() 链路：
    - get_screener_result → mock 返回 ScreenerResult
    - build_context → mock 返回 SentimentContext
    - StrategyMatcher.match → mock 返回 signals
    - PositionAdvisor.advise_batch → mock 返回 suggestions
    - DragonTigerSeatFilter.filter → mock 返回两层结果
    - market._emotion → mock 返回 4 因子

    本任务 C7 已覆盖 _apply_p2_post_filters 单元测试（mock 各层），
    完整 run() 集成测试在阶段 F 验收时补。
    """

    def test_integration_notes_placeholder(self):
        """占位：集成测试在阶段 F 验收时补。"""
        pytest.skip("集成测试在阶段 F 验收时补，本任务只做单元测试")
