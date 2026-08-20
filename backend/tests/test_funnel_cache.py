# -*- coding: utf-8 -*-
"""S087 R10：funnel_cache 单测（save/load round-trip + 缺失返 None + 日期列表）。

conftest 设 VR_DATA_DIR 临时目录 → funnel_cache.db 落临时，隔离不污染生产。
"""
from __future__ import annotations

import json
from datetime import datetime

from candidate_funnel.funnel_cache import (
    list_cached_dates,
    load_funnel_result,
    save_funnel_result,
)
from candidate_funnel.models import FunnelResult, ThresholdConfig


def _mock_result(date: str = "2026-01-01") -> FunnelResult:
    """构造最小 FunnelResult（空 layers/final，避免构造 DiagnosisCard 联网）。"""
    return FunnelResult(
        run_id="test",
        date=date,
        layers=[],
        final_candidates=[],
        threshold_config=ThresholdConfig(),
        as_of=datetime(2026, 1, 1, 12, 0, 0),
        sentiment_phase="冰点",
        market_context={"zt_count": 79},
    )


def test_save_load_round_trip():
    r = _mock_result("2026-01-01")
    save_funnel_result("2026-01-01", "all", r)
    loaded = load_funnel_result("2026-01-01", "all")
    assert loaded is not None
    assert loaded.run_id == "test"
    assert loaded.date == "2026-01-01"
    assert loaded.sentiment_phase == "冰点"
    assert loaded.market_context == {"zt_count": 79}
    # dump 完全一致（序列化 round-trip）
    a = json.dumps(r.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    b = json.dumps(loaded.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    assert a == b


def test_load_missing_returns_none():
    assert load_funnel_result("2099-12-31", "all") is None


def test_list_cached_dates_contains_saved():
    save_funnel_result("2026-02-02", "all", _mock_result("2026-02-02"))
    dates = list_cached_dates()
    assert "2026-02-02" in dates


def test_stage_isolation():
    """同 date 不同 stage 不覆盖（PRIMARY KEY date+stage）。"""
    r_all = _mock_result("2026-03-03")
    r_r1 = FunnelResult(**{**r_all.model_dump(), "run_id": "r1_run"})
    save_funnel_result("2026-03-03", "all", r_all)
    save_funnel_result("2026-03-03", "r1", r_r1)
    assert load_funnel_result("2026-03-03", "all").run_id == "test"
    assert load_funnel_result("2026-03-03", "r1").run_id == "r1_run"
