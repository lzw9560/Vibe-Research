"""涨停基因选股器 & 策略逻辑分析引擎 单测（无网络、快、确定）。"""

import math

from limitup_screener import (
    DISCLAIMER,
    GENE_HIGH_THRESHOLD,
    GENE_QUALIFY_THRESHOLD,
    LOOKBACK_DAYS,
    GeneScore,
    ScreenerResult,
    _calc_total_score,
    _compute_factors,
    wilson_lower_bound,
)
from limitup_strategy import (
    ConditionMatch,
    LimitUpAnalysis,
    RiskRuleKnowledge,
    StrategyLogicMatch,
    RISK_RULES_KNOWLEDGE,
    _build_condition_matches,
)


# ===========================================================================
# wilson_lower_bound 单测
# ===========================================================================

def test_wilson_lower_bound_zero_trials():
    assert wilson_lower_bound(0, 0) == 0.0


def test_wilson_lower_bound_perfect():
    # 100 次全中 → 下界应接近 1.0
    lb = wilson_lower_bound(100, 100)
    assert lb > 0.95


def test_wilson_lower_bound_half():
    # 50/100 → 下界应 < 0.5
    lb = wilson_lower_bound(50, 100)
    assert 0.39 < lb < 0.42


def test_wilson_lower_bound_small_sample():
    # 1/2 → Wilson 校正应显著压低
    lb = wilson_lower_bound(1, 2)
    # 正常比例是 0.5，Wilson 下界应明显更低
    assert lb < 0.5


def test_wilson_lower_bound_negative_blocked():
    assert wilson_lower_bound(0, 10) >= 0.0


# ===========================================================================
# _compute_factors 单测
# ===========================================================================

def test_compute_factors_empty():
    factors = _compute_factors([], [], [])
    assert factors["次日溢价率"] == 0.0
    assert factors["红盘率"] == 0.0
    assert factors["封板率"] == 0.0
    assert factors["炸板后溢价"] == 0.0
    assert factors["涨停频次"] == 0.0


def test_compute_factors_with_history():
    history = [
        {"c": "600519", "lbc": 1, "zdp": 10.0},
        {"c": "600519", "lbc": 2, "zdp": 10.0},
        {"c": "600519", "lbc": 1, "zdp": 10.0},
    ]
    factors = _compute_factors(history, [], [])
    # 有数据时不应全零
    assert factors["涨停频次"] > 0
    assert factors["次日溢价率"] >= 0


# ===========================================================================
# _calc_total_score 单测
# ===========================================================================

def test_calc_total_score_zero():
    assert _calc_total_score({
        "次日溢价率": 0, "红盘率": 0, "封板率": 0,
        "炸板后溢价": 0, "涨停频次": 0,
    }) == 0.0


def test_calc_total_score_max():
    total = _calc_total_score({
        "次日溢价率": 100, "红盘率": 100, "封板率": 100,
        "炸板后溢价": 100, "涨停频次": 100,
    })
    assert total == 100.0


def test_calc_total_score_partial():
    total = _calc_total_score({
        "次日溢价率": 60, "红盘率": 60, "封板率": 60,
        "炸板后溢价": 60, "涨停频次": 20,
    })
    expected = 60 * 0.25 + 60 * 0.25 + 60 * 0.25 + 60 * 0.15 + 20 * 0.10
    assert abs(total - expected) < 0.01


# ===========================================================================
# Pydantic 模型单测
# ===========================================================================

def test_gene_score_model():
    gs = GeneScore(
        code="600519",
        name="贵州茅台",
        total_score=75.5,
        factors={"次日溢价率": 60.0, "红盘率": 70.0, "封板率": 80.0, "炸板后溢价": 50.0, "涨停频次": 30.0},
        wilson_adjusted=70.2,
        qualify=True,
        high_gene=True,
        last_zt_dates=["20260715", "20260710"],
        zt_count_250d=5,
        backtest_points=[],
    )
    assert gs.code == "600519"
    assert gs.qualify is True
    assert gs.high_gene is True
    assert gs.zt_count_250d == 5


def test_screener_result_model():
    sr = ScreenerResult(
        date="2026-07-19",
        gene_scores=[],
        qualified=[],
        high_gene=[],
        updated="2026-07-19 15:00",
        disclaimer=DISCLAIMER,
    )
    assert sr.disclaimer == DISCLAIMER
    assert sr.date == "2026-07-19"


# ===========================================================================
# 配置常量单测
# ===========================================================================

def test_config_defaults():
    assert GENE_QUALIFY_THRESHOLD == 60.0
    assert GENE_HIGH_THRESHOLD == 75.0
    assert LOOKBACK_DAYS == 60


# ===========================================================================
# 策略逻辑分析引擎单测
# ===========================================================================

def test_build_condition_matches_no_gene():
    gene = GeneScore(
        code="600519",
        name="贵州茅台",
        total_score=0.0,
        factors={"次日溢价率": 0, "红盘率": 0, "封板率": 0, "炸板后溢价": 0, "涨停频次": 0},
        wilson_adjusted=0.0,
        qualify=False,
        high_gene=False,
        last_zt_dates=[],
        zt_count_250d=0,
        backtest_points=[],
    )
    result = _build_condition_matches("600519", "贵州茅台", gene)
    assert result.code == "600519"
    assert result.name == "贵州茅台"
    assert isinstance(result.matches, list)
    assert "策略逻辑上" in result.logic_description
    assert result.disclaimer == DISCLAIMER


def test_build_condition_matches_high_gene():
    gene = GeneScore(
        code="600519",
        name="贵州茅台",
        total_score=85.0,
        factors={"次日溢价率": 70, "红盘率": 80, "封板率": 85, "炸板后溢价": 60, "涨停频次": 50},
        wilson_adjusted=80.0,
        qualify=True,
        high_gene=True,
        last_zt_dates=["20260715"],
        zt_count_250d=10,
        backtest_points=[],
    )
    result = _build_condition_matches("600519", "贵州茅台", gene)
    conditions = {m.condition for m in result.matches}
    assert "基因高分" in conditions


def test_build_condition_matches_low_seal_rate():
    gene = GeneScore(
        code="000001",
        name="平安银行",
        total_score=40.0,
        factors={"次日溢价率": 20, "红盘率": 30, "封板率": 35, "炸板后溢价": 10, "涨停频次": 5},
        wilson_adjusted=35.0,
        qualify=False,
        high_gene=False,
        last_zt_dates=[],
        zt_count_250d=1,
        backtest_points=[],
    )
    result = _build_condition_matches("000001", "平安银行", gene)
    conditions = {m.condition for m in result.matches}
    assert "低封板率" in conditions
    assert "基因偏低" in conditions


def test_risk_rules_knowledge_not_empty():
    assert len(RISK_RULES_KNOWLEDGE) >= 6


def test_risk_rule_models():
    rule = RiskRuleKnowledge(
        rule_name="硬性止损",
        description="策略逻辑上，亏损达到阈值时止损退出",
        default_value="-7%",
        configurable=True,
        example="持仓亏损达到 7% 时，策略逻辑上应止损退出",
    )
    assert rule.rule_name == "硬性止损"
    assert rule.configurable is True


def test_condition_match_model():
    cm = ConditionMatch(
        condition="高封单比",
        value="封单比 0.15",
        description="策略逻辑上，封单比较高",
    )
    assert cm.condition == "高封单比"


def test_disclaimer_contains_required_text():
    assert "历史统计特征" in DISCLAIMER
    assert "不构成投资建议" in DISCLAIMER
    assert "股市有风险" in DISCLAIMER
