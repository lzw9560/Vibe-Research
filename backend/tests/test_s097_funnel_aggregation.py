# -*- coding: utf-8 -*-
"""S097 批次聚合 StrategyFunnelSummary 测试（R10/R11/R17）。

验证 score_candidates 产出 scored[].strategy_funnel：每战法跨候选
input_count/passed_count/data_unavailable_count/pass_rate 统计 +
候选命中标记（hit/miss/data_unavailable 三态）+ 并联语义（input_count=评估候选数，
非顺序串联）+ data_ok=False 战法的 data_unavailable 独立统计（不算逻辑过滤）。
"""
from __future__ import annotations

import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.strategy_funnel_registry import score_candidates


def _cand(code, total=70, freq=40, seal=90, zt=3):
    """构造 limitup 候选 dict（factors + total_score + zt_count_250d）。"""
    return {
        "code": code, "name": code,
        "factors": {"涨停频次": freq, "封板率": seal, "次日溢价率": 50},
        "total_score": total, "zt_count_250d": zt,
    }


class TestFunnelAggregation:
    def test_limitup_first_plate_funnel_summary(self):
        """3 cand（A 全 hit / B C1 miss / C C2 miss）→ first_plate 漏斗统计。

        并联语义：input_count=3（所有 cand 评估 first_plate，非顺序串联）；
        C1 passed=2（A,C score≥60），C2 passed=2（A,B freq>20），fired=1（仅 A 全 hit）。
        """
        cands = [
            _cand("A", total=70, freq=40),  # C1 hit C2 hit → fired
            _cand("B", total=55, freq=40),  # C1 miss(<60) C2 hit → not fired
            _cand("C", total=70, freq=10),  # C1 hit C2 miss(≤20) → not fired
        ]
        scored = score_candidates(cands, "晴天", "limitup")
        fp = [s for s in scored if s["strategy_code"] == "first_plate" and s["code"] == "A"]
        assert fp, "A 的 first_plate 应 fired"
        funnel = fp[0]["strategy_funnel"]
        assert funnel is not None
        assert funnel["strategy_code"] == "first_plate"
        assert funnel["total_count"] == 3
        assert funnel["fired_count"] == 1  # 仅 A

        c1 = next(c for c in funnel["conditions"] if c["condition_id"] == "first_plate.c1")
        c2 = next(c for c in funnel["conditions"] if c["condition_id"] == "first_plate.c2")
        assert c1["input_count"] == 3  # 并联：所有 cand 评估
        assert c1["passed_count"] == 2  # A, C
        assert c1["data_unavailable_count"] == 0
        assert c1["pass_rate"] == round(2 / 3, 4)
        assert c2["passed_count"] == 2  # A, B
        assert c2["data_unavailable_count"] == 0

        # 候选命中标记（三态）
        mark_a = next(c for c in funnel["candidates"] if c["code"] == "A")
        assert mark_a["fired"] is True
        assert next(c for c in mark_a["conditions"]
                    if c["condition_id"] == "first_plate.c1")["state"] == "hit"
        mark_b = next(c for c in funnel["candidates"] if c["code"] == "B")
        assert mark_b["fired"] is False
        assert next(c for c in mark_b["conditions"]
                    if c["condition_id"] == "first_plate.c1")["state"] == "miss"
        mark_c = next(c for c in funnel["candidates"] if c["code"] == "C")
        assert mark_c["fired"] is False
        assert next(c for c in mark_c["conditions"]
                    if c["condition_id"] == "first_plate.c2")["state"] == "miss"

    def test_storm_reversal_data_unavailable_count(self):
        """storm_reversal：A 有 pool_item fbt 早→hit；B 无 pool_item→data_unavailable。

        data_ok=False 的 B 独立统计 data_unavailable_count（不算逻辑 miss/过滤）。
        """
        cands = [_cand("A"), _cand("B")]
        pool_map = {"A": {"c": "A", "fbt": 93000, "p": 10.0}}  # B 无 pool_item
        scored = score_candidates(cands, "晴天", "limitup", pool_item_map=pool_map)
        sr = [s for s in scored if s["strategy_code"] == "storm_reversal" and s["code"] == "A"]
        assert sr, "A 的 storm_reversal 应 fired（fbt=93000≤103000）"
        funnel = sr[0]["strategy_funnel"]
        assert funnel["total_count"] == 2
        assert funnel["fired_count"] == 1  # A
        c1 = funnel["conditions"][0]
        assert c1["passed_count"] == 1  # A hit
        assert c1["data_unavailable_count"] == 1  # B 无 pool_item
        # B 标 data_unavailable（非 miss）
        mark_b = next(c for c in funnel["candidates"] if c["code"] == "B")
        assert mark_b["fired"] is False
        assert mark_b["conditions"][0]["state"] == "data_unavailable"

    def test_all_scored_items_have_strategy_funnel(self):
        """每个 scored 项都回填 strategy_funnel 字段（非 None）。"""
        cands = [_cand("A")]
        scored = score_candidates(cands, "晴天", "limitup")
        assert len(scored) > 0
        assert all("strategy_funnel" in s for s in scored)
        assert all(s["strategy_funnel"] is not None for s in scored)
        # strategy_funnel 的 strategy_code 与 scored 项一致
        assert all(s["strategy_funnel"]["strategy_code"] == s["strategy_code"] for s in scored)

    def test_zero_candidates_no_crash(self):
        """无候选 → scored 空，不崩（聚合 total=0）。"""
        scored = score_candidates([], "晴天", "limitup")
        # 空候选 → 返回 none 标注项（grill Q5）
        assert len(scored) >= 1
        # none 项无 strategy_funnel（非战法）
        assert all(s.get("strategy_funnel") is None or s["strategy_code"] == "none"
                   for s in scored)
