# -*- coding: utf-8 -*-
"""S194 R6 · F3 融合整体 §44 event edge verdict 解读 + multifactor null 对账。

F3（spec §3 R6 + §5 A6）：用 s44_verifier event edge（不用 selection——spec grill CRITICAL#2
survivors 不可复现，AI 推理+用户决策非确定）。survivors=FS2 权重触发的融合 event（确定可复现），
测群体收益 lift（event edge 回答不了"融合能否选股"但可复现+诚实，spec §6 R6 option a）。

event edge 的 pass 门 = status=='robust_edge'（**非** selection_lift>=2.0——event edge 无 lift，
selection_lift 恒 None，dep map s44-verifier 视角确认 spec §5 A6「过 §44 2x lift」与 event edge 矛盾）。
days_robust<60 → status='underpowered'（§44v2 假阴性护栏，不判 robust/falsified）。

multifactor null 对账（spec §1.1）：backend/tools/multifactor_combo_validation.py 已证否 ML 多因子融合
（any_multifactor_edge=无，高置信）。S194 F3 融合若跑出 robust_edge = 用更弱方法（FS2 贝叶斯 < ML 组合严）
推翻高置信 null → 须非凡证据（spec §1.1「非凡证据」+ memory rigorous-methodology）。其余 status 与 null 一致
（无 validated 融合 edge），诚实降级（spec §6「不过=重发现 multifactor null，诚实标融合无 validated edge」）。
"""
from __future__ import annotations


def interpret_f3_verdict(
    status: str,
    event_status: str | None,
    day_mean: float | None,
    days_robust: int,
    p_bh: float | None,
) -> dict:
    """解读 F3 §44 event edge verdict + multifactor null 对账（spec §1.1 + §6 R6）。

    Args:
        status: s44_verifier.verify().status ∈ {robust_edge, underpowered, falsified, not_validated, exploratory}。
        event_status: verify().event_status（event_robust/thin_positive/falsified/not_tested 或 None）。
        day_mean: verify().event_metrics.day_mean（群体日均收益，net of cost floor）。
        days_robust: verify().days_robust（day-clustered 有效 n；<60 → underpowered）。
        p_bh: verify().p_bh（event path 的 BH 校正 p）。

    Returns:
        {status, event_status, day_mean, days_robust, p_bh, fusion_conclusion, null_engagement}。
        fusion_conclusion: fusion_has_event_edge / _underpowered / _falsified / _exploratory。
        null_engagement: 与 multifactor null 的对账结论（一致/矛盾须非凡证据）。
    """
    if status == "robust_edge":
        fusion_conclusion = "fusion_has_event_edge"
        null_engagement = (
            "CONTRADICTS multifactor null（any_multifactor_edge=无 高置信）——"
            "用更弱方法（FS2 贝叶斯权重 < multifactor ML 组合严）推翻高置信 null，"
            "须非凡证据 re-examine（spec §1.1 + memory rigorous-methodology）"
        )
    elif status == "underpowered":
        fusion_conclusion = "fusion_underpowered"
        null_engagement = (
            "consistent with multifactor null —— days_robust<60 不判，"
            "无 validated 融合 edge（诚实降级，spec §6）"
        )
    elif status == "falsified":
        fusion_conclusion = "fusion_falsified"
        null_engagement = (
            "consistent with multifactor null —— 融合 event 群体均收益≤0，"
            "重发现 null（spec §6 预期路径）"
        )
    else:  # exploratory / not_validated
        fusion_conclusion = "fusion_exploratory"
        null_engagement = (
            "consistent with multifactor null —— 无 validated 融合 edge，"
            "诚实标探索性不判（spec §6）"
        )

    return {
        "status": status,
        "event_status": event_status,
        "day_mean": day_mean,
        "days_robust": days_robust,
        "p_bh": p_bh,
        "fusion_conclusion": fusion_conclusion,
        "null_engagement": null_engagement,
    }
