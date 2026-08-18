# -*- coding: utf-8 -*-
"""S075 首板流筛选单测（tasks.md 023-026）。

覆盖：
- 023 首板过滤（lbc=1）
- 024 三层剔除（封板质量/筹码结构/市场环境）
- 025 9 维度评分（权重和/范围/排序/数据缺失降级）
- 026 数据缺失降级（不崩不误剔）

mock 模式：monkeypatch.setattr("strategies.first_board_filter.<name>", mock)
- 顶部 from astock import ... 绑定到本模块属性，patch 本模块属性即可
- 评分函数内懒导入 from astock import xxx → patch astock.xxx
- 落盘隔离：monkeypatch 改 _SCORES_DIR 到 tmp_path
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ── 公共 mock 数据工厂 ───────────────────────────────────────────────────

def _make_pool_item(
    code: str = "000001", name: str = "测试股", lbc=1, zbc=0, fbt=93000,
    fund=1e7, ltsz=20e8, fundamt=5e8, hybk="半导体", p=10.0, zje=11.0,
) -> dict:
    """构造东财涨停池 raw dict（真实字段名）。"""
    return {
        "c": code, "n": name, "lbc": lbc, "zbc": zbc, "fbt": fbt,
        "fund": fund, "ltsz": ltsz, "fundamt": fundamt, "hybk": hybk,
        "p": p, "zje": zje,
    }


def _make_first_board(
    code: str = "000001", name: str = "测试股", price=10.0, lbc=1,
    break_times=0, first_seal=93000, seal_amount=1e7,
    float_cap=20e8, amount=5e8, industry="半导体",
) -> dict:
    """构造 filter_first_board 产出格式的首板 dict。"""
    from strategies.first_board_filter import _fbt_to_hhmm
    return {
        "code": code, "name": name, "price": price, "lbc": lbc,
        "break_times": break_times, "first_seal": first_seal,
        "first_seal_hhmm": _fbt_to_hhmm(first_seal),
        "seal_amount": seal_amount, "float_cap": float_cap,
        "amount": amount, "industry": industry,
    }


def _make_tencent_quote(
    turnover_pct=8.0, vol_ratio=1.0, amount_wan=50000.0,
) -> dict:
    """构造 tencent_quote 单股返回结构（dict[code, dict]）。"""
    return {
        "turnover_pct": turnover_pct, "vol_ratio": vol_ratio,
        "amount_wan": amount_wan,
    }


# =========================================================================
# 023 首板过滤
# =========================================================================

class TestFilterFirstBoard:
    """023：测试 filter_first_board（lbc=1）。"""

    def test_only_first_board_kept(self):
        """mock 涨停池含首板(lbc=1)+连板(lbc=2,3)，只返首板。"""
        from strategies.first_board_filter import filter_first_board
        pool = [
            _make_pool_item(code="000001", lbc=1),
            _make_pool_item(code="000002", lbc=2),
            _make_pool_item(code="000003", lbc=1),
            _make_pool_item(code="000004", lbc=3),
        ]
        out = filter_first_board(pool)
        codes = [c["code"] for c in out]
        assert codes == ["000001", "000003"]
        assert all(c["lbc"] == 1 for c in out)

    def test_lbc_missing_treated_as_first(self):
        """lbc 缺失/0/None 也视为首板（东财口径 1=首板，兼容 0/None）。

        代码逻辑：lbc_raw is None → lbc=1；lbc=0 → 保留原值 0（视为首板，不剔）。
        本用例验证全部 4 只都被保留（视为首板），不验证 lbc 字段值（0/1 都可）。
        """
        from strategies.first_board_filter import filter_first_board
        pool = [
            {"c": "000001", "n": "A", "lbc": None},  # None → 视为首板(lbc=1)
            {"c": "000002", "n": "B", "lbc": 0},     # 0 → 视为首板(lbc=0 保留)
            {"c": "000003", "n": "C", "lbc": "0"},   # "0" → 视为首板(lbc=0 保留)
            {"c": "000004", "n": "D"},               # 缺字段 → 视为首板(lbc=1)
        ]
        out = filter_first_board(pool)
        assert len(out) == 4  # 全部保留（视为首板）
        codes = [c["code"] for c in out]
        assert codes == ["000001", "000002", "000003", "000004"]
        # lbc=None/缺字段 → 默认 1；lbc=0/"0" → 保留原值 0
        lbc_map = {c["code"]: c["lbc"] for c in out}
        assert lbc_map["000001"] == 1  # None → 1
        assert lbc_map["000002"] == 0  # 0 → 0(保留)
        assert lbc_map["000003"] == 0  # "0" → 0(保留)
        assert lbc_map["000004"] == 1  # 缺字段 → 1

    def test_empty_pool(self):
        """空池返回空 list。"""
        from strategies.first_board_filter import filter_first_board
        assert filter_first_board([]) == []
        assert filter_first_board(None) == []  # type: ignore[arg-type]

    def test_field_mapping(self):
        """字段映射：c→code, n→name, zbc→break_times, fbt→first_seal,
        fund→seal_amount(非 zje), ltsz→float_cap, fundamt→amount, hybk→industry。"""
        from strategies.first_board_filter import filter_first_board
        pool = [_make_pool_item(
            code="600000", name="浦发银行", lbc=1, zbc=1, fbt=92500,
            fund=2e7, ltsz=30e8, fundamt=8e8, hybk="银行", p=10.5, zje=11.0,
        )]
        out = filter_first_board(pool)
        assert len(out) == 1
        c = out[0]
        assert c["code"] == "600000"
        assert c["name"] == "浦发银行"
        assert c["break_times"] == 1
        assert c["first_seal"] == 92500
        assert c["first_seal_hhmm"] == "09:25"
        assert c["seal_amount"] == 2e7      # fund，非 zje
        assert c["float_cap"] == 30e8      # ltsz
        assert c["amount"] == 8e8           # fundamt
        assert c["industry"] == "银行"


# =========================================================================
# 024 三层剔除
# =========================================================================

class TestExcludeLayers:
    """024：测试三层剔除。"""

    # ── 层1：封板质量 ──────────────────────────────────────────────────

    def test_layer1_break_times_excluded(self):
        """break_times≥2 剔除。"""
        from strategies.first_board_filter import exclude_layer1_seal_quality
        fbs = [
            _make_first_board(code="001", break_times=2),   # 剔除
            _make_first_board(code="002", break_times=1),   # 保留
            _make_first_board(code="003", break_times=0),   # 保留
        ]
        kept, filtered = exclude_layer1_seal_quality(fbs)
        kept_codes = [c["code"] for c in kept]
        assert "002" in kept_codes and "003" in kept_codes
        assert "001" not in kept_codes
        rec = next(r for r in filtered if r["code"] == "001")
        assert rec["layer"] == 1
        assert "炸板2次" in rec["reason"]

    def test_layer1_late_seal_excluded(self):
        """首封时间不再硬剔除（改为 score_dim_seal_time 评分体现）。

        grill 决策：首封时间从硬剔除改为评分，层1只保留炸板+封单比硬剔除。
        """
        from strategies.first_board_filter import exclude_layer1_seal_quality
        fbs = [
            _make_first_board(code="001", first_seal=140000),   # 保留（首封时间改评分）
            _make_first_board(code="002", first_seal=135900),   # 保留
            _make_first_board(code="003", first_seal=93000),    # 保留
            _make_first_board(code="004", first_seal=145000),   # 保留（首封时间改评分）
        ]
        kept, filtered = exclude_layer1_seal_quality(fbs)
        # 全部保留（首封时间不再硬剔除）
        assert len(kept) == 4
        assert filtered == []

    def test_layer1_low_seal_ratio_excluded(self):
        """封单/流通市值<0.1% 剔除（grill 固定底线 0.1%）。"""
        from strategies.first_board_filter import exclude_layer1_seal_quality
        # seal/float_cap: 1e5/20e8=0.00005%(<0.1% 剔除) vs 2e7/20e8=1%(保留)
        fbs = [
            _make_first_board(code="001", seal_amount=1e5, float_cap=20e8),   # 0.005% 剔除
            _make_first_board(code="002", seal_amount=2e7, float_cap=20e8),    # 1% 保留
        ]
        kept, filtered = exclude_layer1_seal_quality(fbs)
        assert [c["code"] for c in kept] == ["002"]
        assert filtered[0]["code"] == "001"
        assert "封单/流通市值" in filtered[0]["reason"]

    def test_layer1_data_missing_no_crash(self):
        """层1 数据缺失（break_times/first_seal 等 None）跳过对应条件，不误剔。"""
        from strategies.first_board_filter import exclude_layer1_seal_quality
        fb = _make_first_board(code="001")
        fb["break_times"] = None
        fb["first_seal"] = None
        fb["seal_amount"] = None
        fb["float_cap"] = None
        kept, filtered = exclude_layer1_seal_quality([fb])
        assert len(kept) == 1
        assert filtered == []

    # ── 层2：筹码结构 ──────────────────────────────────────────────────

    def test_layer2_high_turnover_excluded(self, monkeypatch):
        """换手>30% 剔除（grill 固定底线 30%）。"""
        from strategies.first_board_filter import exclude_layer2_chip_structure
        # mock extract_chip_structure 返历史筹码（turnover_pct 字段名）
        monkeypatch.setattr(
            "strategies.first_board_filter.extract_chip_structure",
            lambda code, date: {"turnover_pct": 35.0, "vol_ratio": 1.0, "amount": 5e8}
        )

        fbs = [
            _make_first_board(code="001"),  # 35% 换手 → 剔除
            _make_first_board(code="002"),  # 同 mock，35% → 剔除
        ]
        kept, filtered = exclude_layer2_chip_structure(fbs, "20260818")
        # 两个都 35% 换手 → 都剔除
        assert len(kept) == 0
        assert len(filtered) == 2
        assert "换手" in filtered[0]["reason"]

    def test_layer2_high_amount_excluded(self, monkeypatch):
        """成交额不再硬剔除（改为 chip 评分体现，grill 决策）。

        grill 锁定：层2只保留换手>30% 硬剔除，成交额/量比改为评分。
        """
        from strategies.first_board_filter import exclude_layer2_chip_structure
        # 001: 20亿(>15亿旧阈值) ; 002: 5亿
        def mock_chip(code, date):
            return {"amount": 20e8 if code == "001" else 5e8, "turnover_pct": 8.0, "vol_ratio": 1.0}
        monkeypatch.setattr("strategies.first_board_filter.extract_chip_structure", mock_chip)

        fbs = [
            _make_first_board(code="001", amount=20e8),  # 20亿 → 保留（不再硬剔）
            _make_first_board(code="002", amount=5e8),   # 5亿 → 保留
        ]
        kept, filtered = exclude_layer2_chip_structure(fbs, "20260818")
        # 成交额不再硬剔除 → 全部保留
        assert len(kept) == 2
        assert filtered == []

    def test_layer2_high_vol_ratio_excluded(self, monkeypatch):
        """量比不再硬剔除（改为 chip 评分体现，grill 决策）。"""
        from strategies.first_board_filter import exclude_layer2_chip_structure
        def mock_chip(code, date):
            return {"vol_ratio": 2.5 if code == "001" else 1.0,
                    "turnover_pct": 8.0, "amount": 5e8}
        monkeypatch.setattr("strategies.first_board_filter.extract_chip_structure", mock_chip)

        fbs = [
            _make_first_board(code="001"),
            _make_first_board(code="002"),
        ]
        kept, filtered = exclude_layer2_chip_structure(fbs, "20260818")
        # 量比不再硬剔除 → 全部保留
        assert len(kept) == 2
        assert filtered == []

    def test_layer2_tencent_missing_no_crash(self, monkeypatch):
        """extract_chip_structure 取不到（返空 dict）时不误剔（宁可放过不冤杀）。"""
        from strategies.first_board_filter import exclude_layer2_chip_structure
        # mock extract_chip_structure 返空（历史数据缺失）
        monkeypatch.setattr("strategies.first_board_filter.extract_chip_structure",
                            lambda code, date: {})

        fbs = [_make_first_board(code="001", amount=1e8)]  # pool amount 1亿，正常
        kept, filtered = exclude_layer2_chip_structure(fbs, "20260818")
        # 筹码缺失 → 跳过换手/量比/amount(降级用 pool 的 1亿)，1亿<15亿不剔
        assert len(kept) == 1
        assert filtered == []

    # ── 层3：市场环境 ──────────────────────────────────────────────────

    def test_layer3_market_drop_flagged(self, monkeypatch):
        """大盘跌>1.5% 标记 high_risk（不剔除，仅标记 env_flags）。"""
        from strategies.first_board_filter import exclude_layer3_market_env
        # mock _emotion 返正常情绪（max_boards=3, ladder 非空）
        monkeypatch.setattr(
            "strategies.first_board_filter._emotion",
            lambda d: {"max_boards": 3, "ladder": [{"boards": 2, "count": 5}]}
        )
        # mock _market_drop_pct 返沪深300 跌 2%（历史数据，无未来函数）
        monkeypatch.setattr("strategies.first_board_filter._market_drop_pct",
                            lambda d: -2.0)

        fb = _make_first_board(code="001", industry="半导体")
        kept, filtered, env = exclude_layer3_market_env([fb], "20260818", first_boards=[fb])
        # 大盘跌 2% → high_risk=True，但不剔除（层3 仅板块孤板剔除）
        assert env["high_risk"] is True
        assert env["market_drop_pct"] == -2.0
        # 单股 + 单板块（sector_count=1<2），但需 concept_tags 空才剔
        # mock concept_blocks 返空 → concept_tags 空 → 剔除（孤板无题材）
        # 这里不验证剔除（下一用例验），只验 high_risk 标记

    def test_layer3_isolated_sector_excluded(self, monkeypatch):
        """同板块涨停<2 且无题材 → 剔除（孤板无板块效应）。"""
        from strategies.first_board_filter import exclude_layer3_market_env
        monkeypatch.setattr(
            "strategies.first_board_filter._emotion",
            lambda d: {"max_boards": 3, "ladder": [{"boards": 2, "count": 5}]}
        )
        # mock _market_drop_pct 返涨（非高风险）
        monkeypatch.setattr("strategies.first_board_filter._market_drop_pct", lambda d: 0.5)
        # mock concept_blocks 返空 → 无题材
        monkeypatch.setattr("strategies.first_board_filter.concept_blocks", lambda c: {})

        # 只 1 只半导体，sector_count=1<2，无题材 → 剔除
        fb = _make_first_board(code="001", industry="半导体")
        kept, filtered, env = exclude_layer3_market_env([fb], "20260818", first_boards=[fb])
        assert len(kept) == 0
        assert len(filtered) == 1
        assert filtered[0]["layer"] == 3
        assert "同板块" in filtered[0]["reason"]

    def test_layer3_sector_with_theme_kept(self, monkeypatch):
        """同板块涨停<2 但有题材 → 保留（有题材支撑不剔）。"""
        from strategies.first_board_filter import exclude_layer3_market_env
        monkeypatch.setattr(
            "strategies.first_board_filter._emotion",
            lambda d: {"max_boards": 3, "ladder": [{"boards": 2, "count": 5}]}
        )
        monkeypatch.setattr("strategies.first_board_filter._market_drop_pct", lambda d: 0.5)
        # mock concept_blocks 返有题材
        monkeypatch.setattr(
            "strategies.first_board_filter.concept_blocks",
            lambda c: {"boards": [{"name": "芯片"}], "concept_tags": ["芯片"]}
        )

        fb = _make_first_board(code="001", industry="半导体")
        kept, filtered, env = exclude_layer3_market_env([fb], "20260818", first_boards=[fb])
        assert len(kept) == 1
        assert filtered == []

    def test_excluded_records_have_reason(self, monkeypatch):
        """剔除记录含 code/layer/reason 字段，reason 写人话。

        grill 决策：层1只保留炸板+封单比硬剔除，首封时间不再剔除。
        """
        from strategies.first_board_filter import exclude_layer1_seal_quality
        fb = _make_first_board(code="001", break_times=3, first_seal=143000,
                               seal_amount=1e5, float_cap=20e8)
        _, filtered = exclude_layer1_seal_quality([fb])
        rec = filtered[0]
        assert set(rec.keys()) >= {"code", "layer", "reason"}
        assert rec["code"] == "001"
        assert rec["layer"] == 1
        # reason 含中文人话：炸板3次 + 封单/流通市值（首封时间不再剔除）
        assert "炸板3次" in rec["reason"]
        assert "封单/流通市值" in rec["reason"]


# =========================================================================
# 025 9 维度评分
# =========================================================================

class TestScoreCandidate:
    """025：测试 9 维度评分。"""

    def test_weights_sum_to_one(self):
        """MARKET_PHASE_WEIGHTS 每档权重和=1.0。"""
        from strategies.first_board_filter import MARKET_PHASE_WEIGHTS
        for phase, weights in MARKET_PHASE_WEIGHTS.items():
            assert abs(sum(weights.values()) - 1.0) < 1e-9, f"{phase} 权重和={sum(weights.values())}"

    def test_weights_count(self):
        """4 档市场档位权重。"""
        from strategies.first_board_filter import MARKET_PHASE_WEIGHTS
        assert len(MARKET_PHASE_WEIGHTS) == 4  # 冰点/普通/活跃/亢奋
        for phase in ("冰点", "普通", "活跃", "亢奋"):
            assert phase in MARKET_PHASE_WEIGHTS

    def test_score_range_0_to_100(self, monkeypatch):
        """总分在 0-100 范围（新评分体系：11 维度，权重分层）。"""
        from strategies.first_board_filter import score_candidate
        # mock 所有维度数据源为缺失 → 核心维度 -1（不参与加权），保留维度 50
        monkeypatch.setattr("strategies.first_board_filter.extract_chip_structure",
                            lambda code, date: {})
        monkeypatch.setattr("strategies.first_board_filter.concept_blocks", lambda c: {})
        monkeypatch.setattr("astock.ths_limit_up_pool", lambda d: [])
        monkeypatch.setattr("astock.dragon_tiger_board", lambda c: {})
        monkeypatch.setattr("astock.announcements", lambda c, limit=10: [])
        monkeypatch.setattr("predict.features.fund_flow.fetch_northbound", lambda c, d=None: None)
        monkeypatch.setattr("strategies.first_board_filter.em_zt_topic_pool",
                            lambda *a, **kw: [])

        # candidate 无 first_seal/seal_amount/float_cap → 核心 4 维度 -1
        cand = {"code": "001", "name": "A", "industry": None}
        result = score_candidate(cand, "20260818", "普通")
        assert 0.0 <= result["total"] <= 100.0
        assert "scores" in result
        assert len(result["scores"]) == 11  # 11 维度

    def test_rank_descending(self):
        """rank_candidates 按总分降序（新签名 score_candidate 加 phase 参数）。"""
        from strategies.first_board_filter import rank_candidates
        # 用 mock candidate + patch score_candidate 避免网络
        cands = [
            {"code": "001", "name": "A"},
            {"code": "002", "name": "B"},
            {"code": "003", "name": "C"},
        ]
        scores_map = {"001": 80.0, "002": 60.0, "003": 70.0}
        # 新签名 score_candidate(c, date, phase) → patch 匹配 3 参数
        with patch("strategies.first_board_filter.score_candidate",
                   lambda c, d, p="普通": {"code": c["code"], "name": c["name"],
                                           "scores": {}, "raw_values": {},
                                           "total": scores_map[c["code"]], "rank": 0,
                                           "market_phase": p}):
            out = rank_candidates(cands, "20260818")
        assert out[0]["code"] == "001" and out[0]["rank"] == 1
        assert out[1]["code"] == "003" and out[1]["rank"] == 2
        assert out[2]["code"] == "002" and out[2]["rank"] == 3
        assert out[0]["total"] >= out[1]["total"] >= out[2]["total"]

    def test_dim_data_missing_returns_50(self, monkeypatch):
        """数据缺失：北向停更返-1/无龙虎榜返50/无公告返50（新签名返 tuple）。"""
        from strategies.first_board_filter import (
            score_dim6_northbound, score_dim7_institution, score_dim9_event,
        )
        cand = _make_first_board(code="001")
        # 北向 fetch_northbound 返 None → -1（数据缺失，不参与加权）
        monkeypatch.setattr("predict.features.fund_flow.fetch_northbound", lambda c, d=None: None)
        s6, raw6 = score_dim6_northbound(cand, "20260818")
        assert s6 == -1.0  # 北向停更→数据缺失→-1
        assert raw6["northbound_net"] is None

        # 龙虎榜 dragon_tiger_board 返空 → institution_net=None → 50（保留维度降级50）
        monkeypatch.setattr("astock.dragon_tiger_board", lambda c: {})
        s7, raw7 = score_dim7_institution(cand, "20260818")
        assert s7 == 50.0
        assert raw7["inst_net"] is None

        # 公告 announcements 返空 → 50
        monkeypatch.setattr("astock.announcements", lambda c, limit=10: [])
        s9, raw9 = score_dim9_event(cand, "20260818")
        assert s9 == 50.0
        assert raw9["event_type"] == "无公告"

    def test_dim5_auction_returns_neg1(self):
        """竞价确认 T-1 盘后返 -1（数据缺失，不参与加权）。"""
        from strategies.first_board_filter import score_dim5_auction
        cand = _make_first_board(code="001")
        s, raw = score_dim5_auction(cand, "20260818")
        assert s == -1.0  # 数据缺失，不参与加权
        assert raw["auction_open_pct"] is None
        assert raw["auction_vol_ratio"] is None

    def test_dim3_seal_strength_scoring(self):
        """封板强度：开盘秒板+大封单+不炸=高分；尾盘+小封单+炸=低分。新签名返 (score, raw)。"""
        from strategies.first_board_filter import score_dim3_seal_strength
        # 高分：9:25 封板(100) + 封单2%(100) + 0炸板(100)
        strong = _make_first_board(code="001", first_seal=92500,
                                   seal_amount=4e7, float_cap=20e8, break_times=0)
        s_strong, raw_strong = score_dim3_seal_strength(strong, "20260818")
        assert s_strong >= 90.0
        # raw 字段落盘校验
        assert raw_strong["first_seal"] == 92500
        assert raw_strong["seal_amount"] == 4e7
        assert raw_strong["float_cap"] == 20e8
        assert raw_strong["seal_ratio"] == round(4e7 / 20e8, 4)
        assert raw_strong["break_times"] == 0

        # 低分：14:30 封板(20) + 封单0.1%(10) + 2炸板(0)
        weak = _make_first_board(code="002", first_seal=143000,
                                 seal_amount=2e5, float_cap=20e8, break_times=2)
        s_weak, raw_weak = score_dim3_seal_strength(weak, "20260818")
        assert s_weak <= 30.0
        assert raw_weak["first_seal"] == 143000

    def test_dim4_chip_scoring(self, monkeypatch):
        """筹码结构：健康换手+正常量比+适中成交=高分。新签名返 (score, raw)。"""
        from strategies.first_board_filter import score_dim4_chip
        # 健康：换手8% + 量比1.0 + 成交5亿（mock 历史筹码）
        def mock_chip(code, date):
            return {"turnover_pct": 8.0, "vol_ratio": 1.0, "amount": 5e8}
        monkeypatch.setattr("strategies.first_board_filter.extract_chip_structure", mock_chip)

        healthy = _make_first_board(code="001", amount=5e8)
        s_healthy, raw_healthy = score_dim4_chip(healthy, "20260818")
        assert s_healthy >= 80.0
        # raw 字段落盘校验
        assert raw_healthy["turnover"] == 8.0
        assert raw_healthy["vol_ratio"] == 1.0
        assert raw_healthy["amount"] == 5e8

        # 松动：换手30% + 量比2.5 + 成交20亿
        def mock_chip2(code, date):
            return {"turnover_pct": 30.0, "vol_ratio": 2.5, "amount": 20e8}
        monkeypatch.setattr("strategies.first_board_filter.extract_chip_structure", mock_chip2)

        loose = _make_first_board(code="002", amount=20e8)
        s_loose, raw_loose = score_dim4_chip(loose, "20260818")
        assert s_loose <= 30.0
        assert raw_loose["turnover"] == 30.0
        assert raw_loose["vol_ratio"] == 2.5


# =========================================================================
# 026 数据缺失降级
# =========================================================================

class TestDataMissingDegradation:
    """026：测试数据缺失降级不崩不误剔。"""

    def test_chip_data_missing_no_crash(self, monkeypatch):
        """extract_chip_structure 取不到（返空 dict）时不误剔（宁可放过不冤杀）。"""
        from strategies.first_board_filter import exclude_layer2_chip_structure
        # mock extract_chip_structure 返空（历史 baostock 缓存缺失）
        monkeypatch.setattr("strategies.first_board_filter.extract_chip_structure",
                            lambda code, date: {})

        # pool amount 1亿（<15亿不剔），筹码缺失 → 跳过换手/量比
        fb = _make_first_board(code="001", amount=1e8)
        kept, filtered = exclude_layer2_chip_structure([fb], "20260818")
        assert len(kept) == 1
        assert filtered == []

    def test_market_emotion_missing_no_crash(self, monkeypatch):
        """market._emotion 失败时 env_flags 降级，不崩。"""
        from strategies.first_board_filter import exclude_layer3_market_env
        # _emotion 抛异常 → emotion={} → max_boards=None, ladder_broken=True
        def boom(d):
            raise RuntimeError("情绪数据故障")
        monkeypatch.setattr("strategies.first_board_filter._emotion", boom)
        # _market_drop_pct 返 None（baostock 失败内部 try/except 降级返 None，不抛）
        monkeypatch.setattr("strategies.first_board_filter._market_drop_pct",
                            lambda d: None)
        # concept_blocks 返有题材 → 避免孤板剔除，确保走完流程
        monkeypatch.setattr(
            "strategies.first_board_filter.concept_blocks",
            lambda c: {"boards": [{"name": "芯片"}], "concept_tags": ["芯片"]}
        )

        fb = _make_first_board(code="001", industry="半导体")
        kept, filtered, env = exclude_layer3_market_env([fb], "20260818", first_boards=[fb])
        # 不崩 + env_flags 降级字段
        assert env["max_boards"] is None
        assert env["market_drop_pct"] is None
        assert env["high_risk"] is False  # None ≤ -1.5 → False
        assert env["ladder_broken"] is True
        # 有题材 → 保留
        assert len(kept) == 1

    def test_all_dims_missing_no_crash(self, monkeypatch, tmp_path):
        """所有维度数据源都取不到时，候选仍能跑完，各维返 50 中性（auction=0）。

        新 score_dim1 用 em_zt_topic_pool hybk 聚合，score_dim2 用 dragon_tiger_board
        最近龙虎榜——测试 mock 这两个数据源缺失，验证降级 50。
        """
        from strategies.first_board_filter import rank_candidates
        # mock 所有数据源缺失
        monkeypatch.setattr("strategies.first_board_filter.extract_chip_structure",
                            lambda code, date: {})
        monkeypatch.setattr("strategies.first_board_filter.concept_blocks", lambda c: {})
        monkeypatch.setattr("astock.ths_limit_up_pool", lambda d: [])
        # dragon_tiger_board 返空（无龙虎榜记录）→ score_dim2 降级 50
        monkeypatch.setattr("astock.dragon_tiger_board", lambda c: {})
        monkeypatch.setattr("astock.announcements", lambda c, limit=10: [])
        monkeypatch.setattr("predict.features.fund_flow.fetch_northbound", lambda c, d=None: None)
        # em_zt_topic_pool 返空 → score_dim1 涨停池空，same_industry_count=0
        # 但 candidate.industry="半导体"存在 → score_dim1 返 40（非 50）
        # 用 industry=None 的 candidate 让 score_dim1 返 50（无 industry→中性）
        monkeypatch.setattr("strategies.first_board_filter.em_zt_topic_pool",
                            lambda *a, **kw: [])

        cands = [_make_first_board(code="001", industry=None),
                 _make_first_board(code="002", industry=None)]
        out = rank_candidates(cands, "20260818")
        assert len(out) == 2
        for s in out:
            # auction/northbound 数据缺失返 -1（不参与加权）
            assert s["scores"]["auction"] == -1.0
            assert s["scores"]["northbound"] == -1.0
            # 保留维度（hot_money/institution/theme/event）降级 50
            # chip 可能用 candidate.amount 降级 → 非 50（允许）
            for dim in ("hot_money", "institution", "theme", "event"):
                assert s["scores"][dim] == 50.0, f"{dim}={s['scores'][dim]} 应=50"
            # total 在 0-100 范围
            assert 0 <= s["total"] <= 100

    def test_run_first_board_filter_end_to_end(self, monkeypatch, tmp_path):
        """端到端：mock 全部数据源，验证 run_first_board_filter 返回结构完整。"""
        from strategies import first_board_filter as fbf

        # 隔离落盘
        monkeypatch.setattr(fbf, "_SCORES_DIR", tmp_path)

        # mock 涨停池：2 只首板 + 1 只连板
        pool = [
            _make_pool_item(code="000001", lbc=1, hybk="半导体"),
            _make_pool_item(code="000002", lbc=1, hybk="半导体"),
            _make_pool_item(code="000003", lbc=2, hybk="半导体"),
        ]
        monkeypatch.setattr(fbf, "em_zt_topic_pool", lambda *a, **kw: pool)

        # mock extract_chip_structure 返历史筹码（不触发层2剔除）
        def mock_chip(code, date):
            return {"turnover_pct": 8.0, "vol_ratio": 1.0, "amount": 5e8}
        monkeypatch.setattr(fbf, "extract_chip_structure", mock_chip)

        # mock _emotion 正常
        monkeypatch.setattr(
            fbf, "_emotion",
            lambda d: {"max_boards": 3, "ladder": [{"boards": 2, "count": 5}]}
        )
        # mock _market_drop_pct 涨（非高风险，历史数据无未来函数）
        monkeypatch.setattr(fbf, "_market_drop_pct", lambda d: 0.5)

        # mock concept_blocks 有题材（避免孤板剔除）
        monkeypatch.setattr(
            fbf, "concept_blocks",
            lambda c: {"boards": [{"name": "芯片"}], "concept_tags": ["芯片"]}
        )

        # mock 评分维度数据源（全部降级 50，避免网络）
        monkeypatch.setattr("astock.ths_limit_up_pool", lambda d: [])
        monkeypatch.setattr("astock.dragon_tiger_board", lambda c: {})
        monkeypatch.setattr("astock.announcements", lambda c, limit=10: [])
        monkeypatch.setattr("predict.features.fund_flow.fetch_northbound", lambda c, d=None: None)
        monkeypatch.setattr("strategies.sector_cycle.aggregate_sectors", lambda d: [])
        monkeypatch.setattr(
            "strategies.hot_money_seats.compute_seat_risk_factor",
            lambda *a, **kw: type("F", (), {"risk_label": "无数据", "score_modifier": 1.0})()
        )

        result = fbf.run_first_board_filter("20260818")

        # 结构完整
        assert set(result.keys()) >= {
            "date", "zt_pool_count", "first_board_count", "candidates",
            "scored_candidates", "excluded", "env_flags",
        }
        assert result["date"] == "20260818"
        assert result["zt_pool_count"] == 3       # pool 3 只
        assert result["first_board_count"] == 2    # 首板 2 只（lbc=1）
        # 2 只首板，板块涨停 sector_count=2>=2 → 不孤板剔除 → 候选 2
        assert len(result["candidates"]) == 2
        assert len(result["scored_candidates"]) == 2
        # env_flags 完整
        assert "market_drop_pct" in result["env_flags"]
        assert "high_risk" in result["env_flags"]
        assert "max_boards" in result["env_flags"]
        assert "ladder_broken" in result["env_flags"]
        # 落盘文件存在
        score_file = tmp_path / "first_board_scores_20260818.json"
        assert score_file.exists()
        data = json.loads(score_file.read_text(encoding="utf-8"))
        assert data["_meta"]["date"] == "20260818"
        assert data["_meta"]["count"] == 2
        # scored_candidates 有 rank + total + scores
        sc = result["scored_candidates"][0]
        assert set(sc.keys()) >= {"code", "name", "scores", "total", "rank"}
        assert sc["rank"] == 1
        assert 0 <= sc["total"] <= 100
