"""R3 bug fix test（deep-review 2026-09-18 w1d19k2hl）：consecutive_relay event-edge 守卫。

6 专家发现 R3 category-error bug：r3_enforce（backtest.py:210）调
lift_to_multiplier(dim.lift=None, dim.n=1283, days_robust=current_days>=60)
→ ('探索性', 1.0) → write_override ×1.0 静默绕过 regime_caps bull×0.75 +
34%衰减门 + bear_days≥120 + lbc3_days≥60，最该门控时刻自动升满仓。

consecutive_relay 在 DIM_ARM_MAP（evaluation.py:298）+ lift=None（event edge）+
regime_caps={bull:0.75,...}（evaluation.py:102）→ r3_enforce 会处理它。

修复：r3_enforce 遇 dim.lift is None 或 dim.regime_caps is not None 时 skip
（event-edge → weekly_review cap gate 管，非 r3_enforce selection-lift 逻辑）。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_r3_enforce_skips_consecutive_relay_event_edge():
    """consecutive_relay lift=None + regime_caps → skip lift_to_multiplier（不炸 ×1.0）。

    修复前（bug）：consecutive_relay 在 enforced + write_override ×1.0（绕过 regime_caps）。
    修复后：consecutive_relay 在 skipped_event_edge，write_override 不为它被调。
    """
    from scheduler.executors.backtest import r3_enforce

    # mock trade_journal 返 60 distinct exit_date（current_days>=60 触发 lift_to_multiplier 路径）
    mock_journal = MagicMock()
    mock_records = [MagicMock(exit_date=f"2026-09-{i:02d}") for i in range(1, 61)]
    mock_journal.query_records.return_value = mock_records

    # 追踪 write_override 调用（consecutive_relay 不该被调）
    write_override_calls: list[tuple] = []

    def _track_write_override(*args, **kwargs):
        write_override_calls.append((args, kwargs))
        return None

    with patch("engine.trade_journal.TradeJournal", return_value=mock_journal), \
         patch("candidate_funnel.lift_override.write_override", side_effect=_track_write_override):
        result = r3_enforce({"threshold_days": 60})

    # consecutive_relay 应在 skipped_event_edge（event-edge 守卫），不在 enforced
    enforced_ids = [e["dimension_id"] for e in result.get("enforced", [])]
    skipped_event = result.get("skipped_event_edge", [])
    skipped_event_ids = [e.get("dimension_id") for e in skipped_event if isinstance(e, dict)]

    assert "consecutive_relay" not in enforced_ids, (
        "R3 bug 未修：consecutive_relay 不该被 r3_enforce enforce（应 skip event-edge → weekly_review cap gate 管）。"
        "当前 enforced 含 consecutive_relay = lift_to_multiplier(None→×1.0) 静默绕过 regime_caps bull×0.75。"
    )
    assert "consecutive_relay" in skipped_event_ids, (
        "R3 bug 未修：consecutive_relay 应在 skipped_event_edge（event-edge 守卫）。"
    )

    # write_override 不该为 consecutive_relay 被调
    cr_calls = [c for c in write_override_calls if c[0] and c[0][0] == "consecutive_relay"]
    assert len(cr_calls) == 0, (
        f"R3 bug 未修：write_override 不该为 consecutive_relay 被调（会静默写 ×1.0 绕过 regime_caps），"
        f"实测 {len(cr_calls)} 次调用。"
    )


def test_r3_enforce_still_processes_selection_lift_arms():
    """breakout/trend/post_first_board（lift!=None 非 event-edge）仍走 lift_to_multiplier 路径。

    修复不能误伤 selection-lift arm——它们 lift!=None 非 event-edge，仍该 enforce。
    """
    from scheduler.executors.backtest import r3_enforce

    mock_journal = MagicMock()
    mock_records = [MagicMock(exit_date=f"2026-09-{i:02d}") for i in range(1, 61)]
    mock_journal.query_records.return_value = mock_records

    write_override_calls: list[tuple] = []

    def _track(*args, **kwargs):
        write_override_calls.append((args, kwargs))
        return None

    with patch("engine.trade_journal.TradeJournal", return_value=mock_journal), \
         patch("candidate_funnel.lift_override.write_override", side_effect=_track):
        result = r3_enforce({"threshold_days": 60})

    # breakout（lift=1.363 非 None 无 regime_caps）是 selection-lift，不该被 event-edge 守卫 skip
    skipped_event_ids = [e.get("dimension_id") for e in result.get("skipped_event_edge", []) if isinstance(e, dict)]
    assert "breakout" not in skipped_event_ids, (
        "修复误伤：breakout（selection-lift lift!=None）不该被 event-edge 守卫 skip，"
        "应仍走 lift_to_multiplier enforce 路径。"
    )
    # post_first_board（lift=None 探索性 PAPER 臂）是 event-edge，应被守卫 skip
    # （lift=None→lift_to_multiplier 返×1.0 bug 同样适用，须 skip 路由 weekly_review）
    assert "post_first_board" in skipped_event_ids, (
        "post_first_board（lift=None event-edge）应在 skipped_event_edge——"
        "event-edge 守卫须 skip 所有 lift=None dim（防 lift_to_multiplier(None→×1.0) bug）。"
    )
