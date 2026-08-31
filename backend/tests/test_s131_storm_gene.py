# -*- coding: utf-8 -*-
"""S131 R1：storm_internal_factor gene data_source 诚实化。

闭合 scan #3 confirmed_lying：_collect_internal_factor 读
``g.factors.get("炸板后溢价", 0) or 0``——gene data_source='kline_rebuild' 时
该因子 NULL→0（data.py load 时 ``or 0``），rebound_score=50 中性 fabricated，
StormFactor data_status 默认 ok → _worst_factor_status 返 ok → StormPrediction
顶层 ok 当权威。probability 偏差 ~5.8pt 可跨 50/70 阈值改 suggested_position。

修：检测 gene data_source/missing_factors → 标 degraded；读因子 without ``or 0``
（None→degraded，不 fabricated 0→50）。
"""
from __future__ import annotations

import limitup_screener.data as ls_data
from limitup_screener.models import GeneScore
from strategies import storm_predictor


def _gene(
    *,
    data_source: str = "eastmoney_live",
    missing_factors: list[str] | None = None,
    rebound: float | None = 0.0,
    seal: float | None = 80.0,
) -> GeneScore:
    """构造测试用 GeneScore。

    rebound/seal 可 None（模拟 kline_rebuild compute 路径诚实 None）或 0.0
    （模拟 data.py load 时 NULL→0 的 or 0 强转）。
    """
    return GeneScore(
        code="000001",
        name="测试",
        total_score=50.0,
        factors={
            "次日溢价率": 50.0,
            "红盘率": 50.0,
            "封板率": seal,
            "炸板后溢价": rebound,
            "涨停频次": 50.0,
        },
        wilson_adjusted=50.0,
        qualify=True,
        high_gene=False,
        last_zt_dates=["2026-08-19"],
        zt_count_250d=5,
        data_source=data_source,
        missing_factors=missing_factors or [],
        date="2026-08-19",
    )


def _patch_internal_deps(monkeypatch, genes, sti_signals=(5.0, 0.15)):
    """替身 _collect_internal_factor 的外部依赖。

    - load_gene_scores → 返回指定 genes（避免触真实 DB）
    - _load_sti_internal_signals → 返回 (max_boards, break_rate) 元组（避免触 STI DB）
    - _prev_trading_day → 固定 "2026-08-19"（避免日历依赖）
    """
    monkeypatch.setattr(ls_data, "load_gene_scores", lambda d: genes)
    monkeypatch.setattr(storm_predictor, "_load_sti_internal_signals",
                        lambda d: sti_signals)
    monkeypatch.setattr(storm_predictor, "_prev_trading_day", lambda d: "2026-08-19")


# ============================================================================
# R1.4①：gene data_source='kline_rebuild' → internal StormFactor data_status="degraded"
# ============================================================================

def test_kline_rebuild_gene_marks_internal_degraded(monkeypatch):
    """kline_rebuild gene 的炸板后溢价 NULL→0（data.py load 时 or 0），
    原代码或 0 → rebound_score=50 fabricated + data_status 默认 ok 当权威。
    现：检测 data_source/missing_factors → StormFactor data_status="degraded"。
    """
    gene = _gene(
        data_source="kline_rebuild",
        missing_factors=["封板率", "炸板后溢价"],
        rebound=0.0,  # data.py load 时 NULL→0
        seal=0.0,
    )
    _patch_internal_deps(monkeypatch, [gene])
    f = storm_predictor._collect_internal_factor("2026-08-20")
    assert f.data_status == "degraded"


def test_missing_factor_in_list_marks_degraded(monkeypatch):
    """炸板后溢价 in missing_factors（但 data_source 非 kline_rebuild）→ degraded。

    覆盖 R1.1 的 missing_factors 检测路径（不依赖 data_source）。
    """
    gene = _gene(
        data_source="eastmoney_live",
        missing_factors=["炸板后溢价"],
        rebound=0.0,
        seal=80.0,
    )
    _patch_internal_deps(monkeypatch, [gene])
    f = storm_predictor._collect_internal_factor("2026-08-20")
    assert f.data_status == "degraded"


def test_none_rebound_marks_degraded(monkeypatch):
    """炸板后溢价=None（kline_rebuild compute 路径诚实 None）→ 标 degraded，
    不 or 0→50 假中性。覆盖 R1.2 的 None 检测路径。
    """
    gene = _gene(
        data_source="kline_rebuild",
        missing_factors=["炸板后溢价"],
        rebound=None,  # 诚实 None（非 0）
        seal=None,
    )
    _patch_internal_deps(monkeypatch, [gene])
    f = storm_predictor._collect_internal_factor("2026-08-20")
    assert f.data_status == "degraded"
    # None 不 fabricated 为 0→rebound_score=50；degraded 标记使概率不当权威
    assert f.score is not None  # 仍算分供展示，但 degraded 标非权威


# ============================================================================
# R1.4②：internal degraded + 其他 3 factor ok → StormPrediction.data_status="degraded"
# ============================================================================

def test_predict_storm_propagates_internal_degraded_to_top(monkeypatch):
    """internal_f degraded + 其他 3 factor ok → _worst_factor_status 传播 →
    StormPrediction.data_status="degraded"（probability/suggested_position 不当权威）。
    """
    gene = _gene(
        data_source="kline_rebuild",
        missing_factors=["炸板后溢价"],
        rebound=0.0,
        seal=80.0,
    )
    _patch_internal_deps(monkeypatch, [gene])

    def _ok_factor(name: str) -> storm_predictor.StormFactor:
        return storm_predictor.StormFactor(name, 50.0, "detail", "ok")

    monkeypatch.setattr(storm_predictor, "_collect_global_factor",
                        lambda d: _ok_factor("外围"))
    monkeypatch.setattr(storm_predictor, "_collect_news_factor",
                        lambda d: _ok_factor("新闻"))
    monkeypatch.setattr(storm_predictor, "_collect_calendar_factor",
                        lambda d: _ok_factor("日历"))

    p = storm_predictor.predict_storm("2026-08-20")
    assert p.data_status == "degraded"
    # 确认是 internal factor 拖低了顶层（非其他因子）
    internal = next(f for f in p.factors if f.name == "前日内部先行")
    assert internal.data_status == "degraded"
    others = [f for f in p.factors if f.name != "前日内部先行"]
    assert all(f.data_status == "ok" for f in others)


# ============================================================================
# R1.4③：正常 gene → ok 原行为不破
# ============================================================================

def test_normal_gene_stays_ok(monkeypatch):
    """eastmoney_live gene（无 missing_factors，因子有值）→ data_status="ok"（原行为不破）。
    """
    gene = _gene(
        data_source="eastmoney_live",
        missing_factors=[],
        rebound=5.0,
        seal=80.0,
    )
    _patch_internal_deps(monkeypatch, [gene])
    f = storm_predictor._collect_internal_factor("2026-08-20")
    assert f.data_status == "ok"
    # rebound=5 → rebound_score = 50-10 = 40（非 50 fabricated 中性）
    # height=5→75, break=0.15→30, rebound=40 → (75+30+40)/3 ≈ 48.3
    assert f.score != 50.0


def test_mixed_genes_one_degraded_marks_degraded(monkeypatch):
    """混合 genes：1 个 kline_rebuild + 1 个正常 → 任一 degraded → 整体 degraded。
    """
    normal = _gene(
        data_source="eastmoney_live",
        missing_factors=[],
        rebound=5.0,
        seal=80.0,
    )
    degraded = _gene(
        data_source="kline_rebuild",
        missing_factors=["炸板后溢价"],
        rebound=0.0,
        seal=0.0,
    )
    _patch_internal_deps(monkeypatch, [normal, degraded])
    f = storm_predictor._collect_internal_factor("2026-08-20")
    assert f.data_status == "degraded"
