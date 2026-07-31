"""S005 models 单测：字段完整性 + 合规（无主观评分/方向词）。"""

from datetime import datetime

from value_funnel import models


def test_quality_metric_fields():
    m = models.QualityMetric(index=1, name="ROE", value=15.0, threshold=8.0, passed=True,
                             evidence="10年平均ROE=15%, 阈值8%")
    assert m.passed is True
    assert m.inapplicable is False
    assert m.evidence


def test_moat_no_score():
    moat = models.MoatSignals()
    assert "系统不输出主观评分" in moat.note
    # 无任何评分字段（只有代理信号）
    assert not hasattr(moat, "score")
    assert not hasattr(moat, "rating")


def test_quality_assessment_dual_rate():
    a = models.QualityAssessment(
        metrics=[], moat=models.MoatSignals(),
        pass_count=5, inapplicable_count=1,
        pass_rate_absolute=round(5 / 7, 4), pass_rate_adjusted=round(5 / 6, 4),
    )
    assert a.pass_rate_absolute == round(5 / 7, 4)
    assert a.pass_rate_adjusted == round(5 / 6, 4)


def test_company_analysis_has_counter_arguments():
    c = models.CompanyAnalysis(code="000001", name="测试",
                               counter_arguments=["需求下行", "竞品分流"])
    assert len(c.counter_arguments) == 2  # 反面论据占位


def test_deep_skeleton_ai_pending():
    d = models.DeepAnalysisSkeleton(code="000001", name="测试",
                                    perspectives=[models.MasterPerspective(
                                        master="巴菲特", framework="护城河")])
    assert d.ai_pending is True
    assert d.perspectives[0].ai_text is None  # 文字待 AI


def test_funnel_result_structure():
    r = models.ValueFunnelResult(run_id="r1", direction="AI算力")
    assert r.layers == []
    assert r.l2_assessments == {}
    assert r.l4_finals == []
