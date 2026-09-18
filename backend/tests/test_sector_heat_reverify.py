# -*- coding: utf-8 -*-
"""S218 #12 sector_heat 非-arm 重验 cron test（deep-review 2026-09-18 w1d19k2hl #12）。

sector_heat（evaluation.py:175，无 arm 映射）→ r3_enforce skip_non_arm 永远冻 ×0.5。
本 cron 补洞：每 30 天重跑 sector_heat_validation.compute()，days≥60 跨阈调 write_override。

决策门（§44v2 规约④ 一致）：
- days<60 → skip（underpowered，保持 ×0.5，write_override 不调）
- days≥60 + lift≥2.0 → write_override 升 ×1.0（phase=r3_reverify）
- days≥60 + lift<1.0 → write_override 降 ×0.1
- else（1≤lift<2）→ skip（保持 ×0.5，write_override 不调——无意义 write）
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _compute_result(lift: float, days: int, ci_overlap: bool = False) -> dict:
    """构造 compute() 返回值——zt>=3 canonical arm 受控 lift/days。"""
    return {
        "days": days,
        "heat_defs": [
            {
                "name": "zt>=3",
                "lift": lift,
                "hot_n": 233,
                "hot_wins": 5,
                "cold_n": 233,
                "cold_wins": 2,
                "hot_lo": 0.01, "hot_hi": 0.04,
                "cold_lo": 0.005, "cold_hi": 0.02,
                "ci_overlap": ci_overlap,
                "verdict": "≥2x validated" if lift >= 2.0 else "<2x 未 validated",
            },
        ],
    }


def _patch_pair(lift: float, days: int, ci_overlap: bool = False):
    """patch compute + write_override（track 调用）。返回 (write_calls, ctx_manager)。"""
    write_calls: list[tuple] = []

    def _track(*args, **kwargs):
        write_calls.append((args, kwargs))
        return {"dimension_id": "sector_heat", "lift": lift, "n": 466,
                "days_robust": days, "validation_status": "stub",
                "weight_multiplier": 1.0 if lift >= 2.0 else 0.1, "phase": "r3_reverify"}

    ctx = patch("tools.sector_heat_validation.compute",
                return_value=_compute_result(lift, days, ci_overlap)), \
          patch("candidate_funnel.lift_override.write_override", side_effect=_track)
    return write_calls, ctx


def test_upgrades_when_lift_ge_2_and_days_ge_60():
    """lift≥2.0 + days≥60 → write_override 调用一次，status=upgraded，phase=r3_reverify。"""
    from scheduler.executors.sector_heat_reverify import sector_heat_reverify
    write_calls, (c1, c2) = _patch_pair(lift=2.5, days=70)
    with c1, c2:
        result = sector_heat_reverify({})

    assert result["status"] == "upgraded", f"lift≥2 days≥60 该 upgraded，得 {result['status']}"
    assert result["days_robust"] == 70
    assert result["lift"] == 2.5
    assert result["n_updated"] == 1
    assert len(write_calls) == 1, "lift≥2 days≥60 → write_override 该被调一次"
    args, kwargs = write_calls[0]
    assert args[0] == "sector_heat", "write_override 第一参数该是 sector_heat"
    assert args[1] == 2.5, "lift 该透传"
    assert kwargs.get("phase") == "r3_reverify", "phase 该是 r3_reverify"
    assert kwargs.get("source_script", "").endswith("sector_heat_reverify.py")


def test_downgrades_when_lift_lt_1_and_days_ge_60():
    """lift<1.0 + days≥60 → write_override 调用一次，status=downgraded。"""
    from scheduler.executors.sector_heat_reverify import sector_heat_reverify
    write_calls, (c1, c2) = _patch_pair(lift=0.8, days=65)
    with c1, c2:
        result = sector_heat_reverify({})

    assert result["status"] == "downgraded", f"lift<1 days≥60 该 downgraded，得 {result['status']}"
    assert result["lift"] == 0.8
    assert result["n_updated"] == 1
    assert len(write_calls) == 1, "lift<1 days≥60 → write_override 该被调一次"
    args, kwargs = write_calls[0]
    assert args[0] == "sector_heat"
    assert args[1] == 0.8
    assert kwargs.get("phase") == "r3_reverify"


def test_skips_when_lift_between_1_and_2_days_ge_60():
    """1≤lift<2 + days≥60 → skip_no_change（保持 ×0.5，write_override 不调）。"""
    from scheduler.executors.sector_heat_reverify import sector_heat_reverify
    write_calls, (c1, c2) = _patch_pair(lift=1.5, days=80)
    with c1, c2:
        result = sector_heat_reverify({})

    assert result["status"] == "skip_no_change", f"1≤lift<2 该 skip_no_change，得 {result['status']}"
    assert result["lift"] == 1.5
    assert result["n_updated"] == 0
    assert len(write_calls) == 0, "1≤lift<2 → write_override 不该被调（无意义 write）"


def test_skips_underpowered_when_days_lt_60():
    """days<60 → skip_underpowered（§44v2 规约④ 不判，保持 ×0.5，write_override 不调）。"""
    from scheduler.executors.sector_heat_reverify import sector_heat_reverify
    # 即使 lift≥2.0，days<60 仍 skip（不臆造 enforce）——与 lift_to_multiplier days<60 cap 一致
    write_calls, (c1, c2) = _patch_pair(lift=2.5, days=40)
    with c1, c2:
        result = sector_heat_reverify({})

    assert result["status"] == "skip_underpowered", f"days<60 该 skip_underpowered，得 {result['status']}"
    assert result["days_robust"] == 40
    assert result["lift"] == 2.5
    assert result["n_updated"] == 0
    assert len(write_calls) == 0, "days<60 → write_override 不该被调（underpowered 不判）"


def test_boundary_lift_eq_2_days_eq_60_upgrades():
    """边界：lift=2.0 + days=60 → upgraded（lift≥2.0 闭区间，days≥60 闭区间）。"""
    from scheduler.executors.sector_heat_reverify import sector_heat_reverify
    write_calls, (c1, c2) = _patch_pair(lift=2.0, days=60)
    with c1, c2:
        result = sector_heat_reverify({})

    assert result["status"] == "upgraded"
    assert len(write_calls) == 1


def test_boundary_lift_eq_1_days_eq_60_skips():
    """边界：lift=1.0 + days=60 → skip_no_change（lift<1.0 严格 <，1.0 不降级）。"""
    from scheduler.executors.sector_heat_reverify import sector_heat_reverify
    write_calls, (c1, c2) = _patch_pair(lift=1.0, days=60)
    with c1, c2:
        result = sector_heat_reverify({})

    assert result["status"] == "skip_no_change", "lift=1.0 不满足 lift<1.0，该 skip_no_change"
    assert len(write_calls) == 0


def test_threshold_days_payload_override():
    """payload.threshold_days 可调（默认 60，传 50 → days=55 仍 underpowered，days=55<50? 不）。

    days=55, threshold=50 → 55≥50 → 走 decision gate（lift=2.5 → upgraded）。
    验证 threshold_days payload 真生效（不硬编码 60）。
    """
    from scheduler.executors.sector_heat_reverify import sector_heat_reverify
    write_calls, (c1, c2) = _patch_pair(lift=2.5, days=55)
    with c1, c2:
        result = sector_heat_reverify({"threshold_days": 50})

    assert result["status"] == "upgraded", "threshold=50 + days=55≥50 + lift=2.5 → upgraded"
    assert len(write_calls) == 1


def test_error_when_compute_raises():
    """compute() 异常 → status=error（不 crash scheduled task，降级 error run）。"""
    from scheduler.executors.sector_heat_reverify import sector_heat_reverify
    with patch("tools.sector_heat_validation.compute",
               side_effect=RuntimeError("db locked")), \
         patch("candidate_funnel.lift_override.write_override") as mock_wo:
        result = sector_heat_reverify({})

    assert result["status"] == "error"
    assert "db locked" in result.get("error", "")
    mock_wo.assert_not_called()


def test_error_when_canonical_heat_def_missing():
    """compute() 返结果无 zt>=3 → status=error（heat_def 缺失，不臆造 lift）。"""
    from scheduler.executors.sector_heat_reverify import sector_heat_reverify
    with patch("tools.sector_heat_validation.compute",
               return_value={"days": 70, "heat_defs": [
                   {"name": "top1", "lift": 1.0, "hot_n": 1, "cold_n": 1, "hot_wins": 0,
                    "cold_wins": 0, "hot_lo": 0.0, "hot_hi": 0.0, "cold_lo": 0.0,
                    "cold_hi": 0.0, "ci_overlap": True, "verdict": "<2x 未 validated"}]}), \
         patch("candidate_funnel.lift_override.write_override") as mock_wo:
        result = sector_heat_reverify({})

    assert result["status"] == "error"
    assert "zt>=3" in result.get("error", "")
    mock_wo.assert_not_called()
