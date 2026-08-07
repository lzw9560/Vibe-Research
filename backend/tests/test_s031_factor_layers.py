# -*- coding: utf-8 -*-
"""S031 T12：limitup_screener_factor.fetch 输出三层 FunnelLayer（打分→战法→仓位）。

mock PreMarketWorkflow.run 返回受控 PreMarketReport，断言 3 层 input/output/
passed/filtered 正确 + 0 qualified / 无战法 边界。不联网（纯内存）。
"""

from unittest.mock import AsyncMock, patch

import pytest

from factors.limitup_screener_factor import LimitupScreenerFactor
from limitup_screener.models import GeneScore
from limitup_strategy import StrategySignal
from pre_market_workflow import PositionSuggestion, PreMarketReport, StrategyMatch


def _gene(code="000001", name="平安银行", total=85.0, zt=5):
    return GeneScore(
        code=code, name=name, total_score=total,
        factors={"次日溢价率": 80, "红盘率": 70, "封板率": 60, "炸板后溢价": 50, "涨停频次": 40},
        wilson_adjusted=80.0, qualify=True, high_gene=True, last_zt_dates=[], zt_count_250d=zt,
    )


def _signal(strategy_code="first_plate", strategy_name="首板挖掘", confidence=0.85):
    return StrategySignal(
        code="000001", name="平安银行", strategy_code=strategy_code,
        strategy_name=strategy_name, confidence=confidence, max_hold_days=3,
    )


def _report(qualified=True, with_strategy=True, with_position=True):
    report = PreMarketReport(date="2026-08-03", generated_at="2026-08-03T09:00:00")
    if not qualified:
        return report
    g = _gene()
    report.candidates = [g]
    report.strong_candidates = [g]
    report.filtered_out = [{"code": "000002", "name": "万科A", "reason": "基因得分未达标"}]
    if with_strategy:
        report.strategy_matches = [StrategyMatch(
            code="000001", name="平安银行", matched_strategies=[_signal()],
            best_strategy="首板挖掘", confidence="高", entry_price=0.0,
            stop_loss=0.0, take_profit=0.0, position_pct=0.0, reasons=["基因合格"],
        )]
    if with_position:
        report.position_suggestions = [PositionSuggestion(
            code="000001", name="平安银行", suggested_pct=0.3, confidence="高",
            entry_price_range=(10.0, 11.0), stop_loss=0.0, take_profit=0.0,
            matched_strategy="首板挖掘", reasons=[],
        )]
    return report


@patch("pre_market_workflow.PreMarketWorkflow")
def test_fetch_returns_three_layers(mock_pmw):
    """fetch 返 3 层（LS-1/LS-2/LS-3），各层 input/output/passed 齐。"""
    mock_pmw.return_value.run = AsyncMock(return_value=_report())
    fr = LimitupScreenerFactor().fetch("2026-08-03")

    assert len(fr.layers) == 3
    l1, l2, l3 = fr.layers
    assert (l1.layer_id, l2.layer_id, l3.layer_id) == ("LS-1", "LS-2", "LS-3")
    assert (l1.name, l2.name, l3.name) == ("涨停基因打分", "战法匹配", "仓位建议")

    # L1 打分：input=scanned(filtered1+qualified1=2) → output=1，filtered_out=1
    assert l1.input_count == 2
    assert l1.output_count == 1
    assert [f.code for f in l1.filtered_out] == ["000002"]
    assert l1.output_codes == ["000001"]
    assert l1.passed[0]["code"] == "000001"

    # L2 战法：input=1(qualified) → output=1(matched)，passed 携 best_strategy + confidence_value
    assert l2.input_count == 1
    assert l2.output_count == 1
    assert l2.passed[0]["best_strategy"] == "首板挖掘"
    assert l2.passed[0]["confidence"] == "高"
    assert l2.passed[0]["confidence_value"] == pytest.approx(0.85)

    # L3 仓位：input=1(L2 output) → output=1(positioned)
    assert l3.input_count == 1
    assert l3.output_count == 1
    assert l3.passed[0]["suggested_pct"] == pytest.approx(0.3)
    assert l3.passed[0]["matched_strategy"] == "首板挖掘"


@patch("pre_market_workflow.PreMarketWorkflow")
def test_fetch_zero_qualified_layers_empty(mock_pmw):
    """qualified=0 日：L1 output=0，L2/L3 空（不做降级，用户自行切日）。"""
    mock_pmw.return_value.run = AsyncMock(return_value=_report(qualified=False))
    fr = LimitupScreenerFactor().fetch("2026-08-03")

    l1, l2, l3 = fr.layers
    assert l1.output_count == 0
    assert l1.data_status == "未取得"  # 无涨停数据
    assert l2.output_count == 0
    assert l3.output_count == 0


@patch("pre_market_workflow.PreMarketWorkflow")
def test_fetch_qualified_but_no_strategy(mock_pmw):
    """qualified 有但无战法匹配：L2 output=0、filtered_out 含该 qualified。"""
    mock_pmw.return_value.run = AsyncMock(return_value=_report(with_strategy=False, with_position=False))
    fr = LimitupScreenerFactor().fetch("2026-08-03")

    l1, l2, l3 = fr.layers
    assert l1.output_count == 1  # qualified 通过打分
    assert l2.output_count == 0  # 无战法匹配
    assert [f.code for f in l2.filtered_out] == ["000001"]
    assert l3.output_count == 0  # L2 output 空 → L3 空
