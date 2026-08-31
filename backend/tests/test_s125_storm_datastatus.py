# -*- coding: utf-8 -*-
"""S125 R3：StormPrediction 顶层 data_status 钉死。

闭合 S124 scan HIGH confirmed_lying #3：storm_predictor.py StormPrediction 无
data_status，predict_storm probability 从含 degraded 因子加权和算出当权威呈现。
修：dataclass 加 data_status 字段 + predict_storm 算最差因子态传顶层。

对齐 risk_models._merge_data_status 范式（missing > degraded/fallback_current > ok），
避免 import risk_models 循环依赖，inline severity map。
"""
from __future__ import annotations

from strategies import storm_predictor


def _factor(name: str, status: str) -> storm_predictor.StormFactor:
    """构造指定 data_status 的因子（score 中性 50，不影响 status 聚合断言）。"""
    return storm_predictor.StormFactor(name, 50.0, "detail", status)


def _patch_factors(monkeypatch, global_s, internal_s, news_s, calendar_s) -> None:
    """替身四因子采集器返指定 data_status 的因子。"""
    monkeypatch.setattr(storm_predictor, "_collect_global_factor",
                       lambda d: _factor("外围", global_s))
    monkeypatch.setattr(storm_predictor, "_collect_internal_factor",
                       lambda d: _factor("内部", internal_s))
    monkeypatch.setattr(storm_predictor, "_collect_news_factor",
                       lambda d: _factor("新闻", news_s))
    monkeypatch.setattr(storm_predictor, "_collect_calendar_factor",
                       lambda d: _factor("日历", calendar_s))


# ============================================================================
# R3.4：predict_storm 顶层 data_status = 最差因子态
# ============================================================================

def test_storm_data_status_all_ok(monkeypatch):
    """R3.4①：全因子 ok→StormPrediction.data_status=ok。"""
    _patch_factors(monkeypatch, "ok", "ok", "ok", "ok")
    p = storm_predictor.predict_storm("2026-08-20")
    assert p.data_status == "ok"


def test_storm_data_status_any_missing(monkeypatch):
    """R3.4②：任一因子 missing→data_status=missing（最差态透传顶层）。"""
    _patch_factors(monkeypatch, "ok", "missing", "ok", "ok")
    p = storm_predictor.predict_storm("2026-08-20")
    assert p.data_status == "missing"


def test_storm_data_status_degraded_plus_fallback(monkeypatch):
    """R3.4③：degraded + fallback_current 同级→data_status=degraded（不降 ok 不升 missing）。

    闭合 lying：含 degraded 因子时顶层须显非 ok，否则概率当权威呈现。
    degraded 优先于 fallback_current（更通用语义标签）。
    """
    _patch_factors(monkeypatch, "degraded", "fallback_current", "ok", "ok")
    p = storm_predictor.predict_storm("2026-08-20")
    assert p.data_status == "degraded"


# ============================================================================
# R3.3：_worst_factor_status helper 直接断言（tiebreak + 保留态）
# ============================================================================

def test_worst_factor_status_empty_returns_ok():
    """R3.3：空因子列表→ok（对齐 _merge_data_status 空入参兜底）。"""
    assert storm_predictor._worst_factor_status([]) == "ok"


def test_worst_factor_status_pure_fallback_preserved():
    """R3.3：仅 fallback_current（无 degraded/missing）→保留 fallback_current 态。

    纯 fallback 语义比 blanket 降为 degraded 更具体诚实——顶层应显真实最差态。
    """
    only_fallback = [_factor("外围", "fallback_current"), _factor("内部", "ok")]
    assert storm_predictor._worst_factor_status(only_fallback) == "fallback_current"


def test_worst_factor_status_missing_beats_all():
    """R3.3：missing + degraded + fallback_current → missing（最高严重度）。"""
    mixed = [
        _factor("外围", "degraded"),
        _factor("内部", "fallback_current"),
        _factor("新闻", "missing"),
        _factor("日历", "ok"),
    ]
    assert storm_predictor._worst_factor_status(mixed) == "missing"
