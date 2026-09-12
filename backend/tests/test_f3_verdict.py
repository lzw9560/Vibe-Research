# -*- coding: utf-8 -*-
"""S194 R6 · F3 verdict 解读单测——融合整体 §44 event edge + multifactor null 对账。

纯函数 interpret_f3_verdict：把 s44_verifier.verify(edge_type='event') 的 verdict 解读成
融合 edge 结论 + multifactor null 对账（spec §1.1 engage 高置信 null）。

event edge 无 selection_lift（spec grill CRITICAL#2 改设计）；pass 门 = status=='robust_edge'
（非 selection_lift>=2.0）；days_robust<60 → underpowered 不判（§44v2）。
"""
from __future__ import annotations

from tools.f3_verdict import interpret_f3_verdict


class TestInterpretF3Verdict:
    def test_robust_edge_contradicts_null(self):
        """status=robust_edge → 融合有 event edge，但矛盾于 multifactor null → 须非凡证据。"""
        v = interpret_f3_verdict(
            status="robust_edge", event_status="event_robust",
            day_mean=0.0042, days_robust=64, p_bh=0.0008,
        )
        assert v["fusion_conclusion"] == "fusion_has_event_edge"
        assert "CONTRADICTS" in v["null_engagement"] or "矛盾" in v["null_engagement"]
        assert "非凡证据" in v["null_engagement"]

    def test_underpowered_consistent_with_null(self):
        """status=underpowered → 样本不够不判，与 null 一致（无 validated edge）。"""
        v = interpret_f3_verdict(
            status="underpowered", event_status="event_thin_positive",
            day_mean=0.003, days_robust=49, p_bh=0.15,
        )
        assert v["fusion_conclusion"] == "fusion_underpowered"
        assert "consistent" in v["null_engagement"] or "一致" in v["null_engagement"]

    def test_falsified_consistent_with_null(self):
        """status=falsified → 均收益≤0，与 null 一致。"""
        v = interpret_f3_verdict(
            status="falsified", event_status="event_falsified",
            day_mean=-0.002, days_robust=64, p_bh=0.6,
        )
        assert v["fusion_conclusion"] == "fusion_falsified"
        assert "consistent" in v["null_engagement"] or "一致" in v["null_engagement"]

    def test_exploratory_consistent_with_null(self):
        """status=exploratory/not_validated → 无 validated edge，与 null 一致。"""
        v = interpret_f3_verdict(
            status="exploratory", event_status=None,
            day_mean=None, days_robust=10, p_bh=None,
        )
        assert v["fusion_conclusion"] == "fusion_exploratory"
        assert "consistent" in v["null_engagement"] or "一致" in v["null_engagement"]

    def test_preserves_verifier_metrics(self):
        """解读保留原 verdict 指标（day_mean/days_robust/p_bh）供下游展示。"""
        v = interpret_f3_verdict(
            status="underpowered", event_status="event_thin_positive",
            day_mean=0.003, days_robust=49, p_bh=0.15,
        )
        assert v["day_mean"] == 0.003
        assert v["days_robust"] == 49
        assert v["p_bh"] == 0.15
