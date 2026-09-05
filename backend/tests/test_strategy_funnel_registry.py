# -*- coding: utf-8 -*-
"""S066 §3-4 策略注册表 + 天气硬开关 + 3 套权重策略分测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.strategy_funnel_registry import (
    STRATEGY_FUNNEL_REGISTRY,
    WEATHER_STRATEGY_MAP,
    WEATHER_RECOMMENDATION,
    FALLBACK_STRATEGIES,
    StrategyFunnelConfig,
    get_strategies_for_weather,
    get_weather_recommendation,
    get_strategy_config,
    compute_strategy_score,
    score_candidates,
    check_quality_standards,
    passes_hard_standards,
)


class TestWeatherHardSwitch:
    """天气-策略推荐（spec §3.3，grill Q7 降级为软标注）。

    grill Q7：暴风雨仍硬约束（仓位=0）；其他天气所有战法可用，
    天气匹配的战法用 get_weather_recommendation() 返回推荐集合。
    """

    def test_sunny_day_strategies(self):
        """grill Q7：晴天 → 所有战法可用（不强过滤），fallback 恒空。

        旧：primary=[连板/龙头/平台]，fallback=[low_absorption]
        新：primary=所有战法，fallback=[]；推荐集合={连板/龙头/平台}
        """
        primary, fallback = get_strategies_for_weather("晴天")
        assert "consecutive_relay" in primary  # 推荐的在
        assert "dragon_head" in primary
        assert "platform_breakout" in primary
        assert "first_plate" in primary  # 不推荐的也在（不强过滤）
        assert fallback == []
        rec = get_weather_recommendation("晴天")
        assert rec == {"consecutive_relay", "dragon_head", "platform_breakout"}

    def test_storm_no_longer_hard_restricted(self):
        """S086 R3：暴风雨不再硬约束——全 allowed（含 storm_reversal），无 fallback。

        旧：暴风雨 → primary=["storm_reversal"]（硬约束其余 forbidden）；
        新：暴风雨 → 全部战法 allowed（primary=所有已注册），fallback 恒空。
        """
        primary, fallback = get_strategies_for_weather("暴风雨")
        assert "storm_reversal" in primary  # 推荐的在
        assert "first_plate" in primary  # 非推荐也 allowed（不强过滤）
        assert len(primary) == len(STRATEGY_FUNNEL_REGISTRY)  # 全 allowed
        assert fallback == []

    def test_unknown_returns_all_strategies(self):
        """grill Q7：未知/None → 所有战法可用，推荐集合为空。

        旧：保守降级到首板+连板；新：不强过滤，推荐集合空。
        """
        primary, fallback = get_strategies_for_weather(None)
        assert "first_plate" in primary
        assert "consecutive_relay" in primary
        assert "reverse_package" in primary  # 所有战法都在
        assert len(primary) == len(STRATEGY_FUNNEL_REGISTRY)
        assert fallback == []
        assert get_weather_recommendation(None) == set()

        primary_u, _ = get_strategies_for_weather("未知")
        assert "first_plate" in primary_u
        assert get_weather_recommendation("未知") == set()

    def test_extreme_rebound_strategies(self):
        """grill Q7：极端反弹不再硬过滤——所有战法可用，推荐集合只有 reverse_package。"""
        primary, fallback = get_strategies_for_weather("极端反弹")
        assert "reverse_package" in primary  # 推荐的在里面
        assert "consecutive_relay" in primary  # 不推荐的也在（不强过滤）
        rec = get_weather_recommendation("极端反弹")
        assert rec == {"reverse_package"}
        assert fallback == []


class TestStrategyRegistry:
    """策略注册表完整性。"""

    def test_registry_has_12_strategies(self):
        """S086 合并后 12 个策略（9 常规 + low_absorption + S081 PRD 2 + storm_reversal）。

        旧 STRATEGY_FUNNEL_REGISTRY（10）+ 旧 STRATEGY_REGISTRY（11）合并为单一
        STRATEGY_REGISTRY（12），STRATEGY_FUNNEL_REGISTRY 为别名同源。
        """
        assert len(STRATEGY_FUNNEL_REGISTRY) == 12
        from strategies.strategy_funnel_registry import STRATEGY_REGISTRY
        assert STRATEGY_REGISTRY is STRATEGY_FUNNEL_REGISTRY

    def test_all_codes_unique(self):
        codes = [s.code for s in STRATEGY_FUNNEL_REGISTRY]
        assert len(codes) == len(set(codes))

    def test_storm_reversal_has_position_scale(self):
        """storm_reversal 仓位 x0.3。"""
        cfg = get_strategy_config("storm_reversal")
        assert cfg is not None
        assert cfg.position_params.position_scale == 0.3

    def test_storm_reversal_only_in_storm(self):
        """storm_reversal 只在暴风雨天主跑。"""
        cfg = get_strategy_config("storm_reversal")
        assert cfg.weather_regimes == ["暴风雨"]
        assert cfg.is_primary is True

    def test_limitup_strategies_use_limitup_weights(self):
        """涨停类策略 weight_set=limitup。"""
        limitup_codes = {"first_plate", "consecutive_relay", "break_reseal",
                         "end_of_day_sneak", "n_shape_counterattack"}
        for code in limitup_codes:
            cfg = get_strategy_config(code)
            assert cfg.weight_set == "limitup", f"{code} should use limitup weights"

    def test_non_limitup_strategies_use_non_limitup_weights(self):
        """非涨停类策略 weight_set=non_limitup。"""
        non_limitup_codes = {"low_absorption", "reverse_package",
                             "platform_breakout", "dragon_head"}
        for code in non_limitup_codes:
            cfg = get_strategy_config(code)
            assert cfg.weight_set == "non_limitup", f"{code} should use non_limitup weights"

    def test_all_weather_regimes_valid(self):
        """所有 weather_regimes 必须在 WEATHER_RECOMMENDATION keys 中。"""
        valid_regimes = set(WEATHER_RECOMMENDATION.keys())
        for s in STRATEGY_FUNNEL_REGISTRY:
            for r in s.weather_regimes:
                assert r in valid_regimes, f"{s.code} has invalid regime {r}"


class TestComputeStrategyScore:
    """3 套权重策略分计算。

    注意：conftest 把 VR_DATA_DIR 指向临时目录，strategy_weights.json 不存在 → 等权兜底。
    需要真实权重的测试用 monkeypatch 注入。
    """

    def test_limitup_score_uses_3_significant_factors(self, monkeypatch):
        """涨停类用 seal/rebound/red 三因子（Phase 0d 显著因子）。"""
        from strategies import strategy_funnel_registry as sfr
        monkeypatch.setattr(sfr, "_WEIGHTS_CACHE", None)
        monkeypatch.setattr(sfr, "_WEIGHTS_PATH", Path(__file__).resolve().parent.parent.parent / ".vibe-research" / "strategy_weights.json")
        # factors 来自 gene_scores 用中文键名（见 compute_strategy_score docstring）；
        # 英文权重键经 _FACTOR_NAME_MAP 映射到中文键查值，故测试须传中文键。
        factors = {"封板率": 90, "炸板后溢价": 80, "红盘率": 70}
        score, breakdown = compute_strategy_score(factors, "limitup")
        assert score > 0
        assert "factor_seal_rate" in breakdown
        assert "factor_rebound_rate" in breakdown
        assert "factor_red_rate" in breakdown

    def test_storm_reversal_uses_seal_and_freq(self, monkeypatch):
        """暴风暴固定 seal 0.60 + (100-freq) 0.40。"""
        from strategies import strategy_funnel_registry as sfr
        # 指向真实 weights 文件
        real_weights = Path(__file__).resolve().parent.parent.parent / ".vibe-research" / "strategy_weights.json"
        monkeypatch.setattr(sfr, "_WEIGHTS_CACHE", None)
        monkeypatch.setattr(sfr, "_WEIGHTS_PATH", real_weights)
        # 中文键名（gene_scores 口径）；英文权重键经 _FACTOR_NAME_MAP 映射查值。
        factors = {"封板率": 90, "涨停频次": 20}
        score, breakdown = compute_strategy_score(factors, "storm_reversal")
        # seal 90×0.6=54, (100-20)×0.4=32, total=86; S151 R2 gene-based ×0.1: seal 5.4 + freq 3.2 = 8.6
        assert score == 8.6
        assert breakdown["factor_seal_rate"] == 5.4

    def test_reverse_factor_uses_100_minus_value(self, monkeypatch):
        """反向因子（freq）用 (100-value) 反转。"""
        from strategies import strategy_funnel_registry as sfr
        real_weights = Path(__file__).resolve().parent.parent.parent / ".vibe-research" / "strategy_weights.json"
        monkeypatch.setattr(sfr, "_WEIGHTS_CACHE", None)
        monkeypatch.setattr(sfr, "_WEIGHTS_PATH", real_weights)
        # 中文键名（gene_scores 口径）
        factors = {"封板率": 90, "涨停频次": 20}
        _, breakdown = compute_strategy_score(factors, "storm_reversal")
        # freq 反向：100-20=80, 80×0.4=32, S151 R2 gene-based ×0.1 = 3.2
        assert breakdown["factor_freq_score"] == 3.2

    def test_missing_weights_fallback_equal(self):
        """权重加载失败 → 等权兜底（不崩）。"""
        factors = {"a": 60, "b": 40}
        score, breakdown = compute_strategy_score(factors, "nonexistent_weight_set")
        # 等权：(60+40)/2=50
        assert score == 50.0

    def test_empty_factors_returns_zero(self):
        score, breakdown = compute_strategy_score({}, "limitup")
        assert score == 0.0
        assert breakdown == {}


class TestScoreCandidates:
    """候选评分排序。"""

    def test_sunny_day_scores_and_sorts(self):
        """晴天 limitup 候选按策略分降序排序。

        S094 T11：funnel_type 必填——limitup 路径只跑 7 涨停战法（dragon_head 等
        market_scan 战法不再在 limitup 路径命中，R9 行为变化）。给候选配 limitup 因子
        （total_score/zt_count/封板率/涨停频次）使 first_plate/n_shape 等命中。
        """
        cands = [
            {"code": "A", "name": "A", "factors": {"封板率": 90, "涨停频次": 40, "次日溢价率": 50},
             "total_score": 70, "zt_count_250d": 3},
            {"code": "B", "name": "B", "factors": {"封板率": 60, "涨停频次": 25, "次日溢价率": 30},
             "total_score": 55, "zt_count_250d": 2},
        ]
        scored = score_candidates(cands, "晴天", "limitup")
        assert len(scored) > 0
        # 第一个应该是高分候选
        assert scored[0]["code"] == "A"
        assert scored[0]["strategy_score"] > scored[-1]["strategy_score"]
        # S094 R12/T15: scored 复用 dispatch_match 产的 confidence（不派生 strategy_score/100）
        assert all(s.get("confidence") is not None for s in scored)

    def test_storm_reversal_scores_by_fbt_any_weather(self):
        """S086 R3/A9：storm_reversal 评分由 fbt（封板≤10:30）决定，不限天气。

        旧：storm_reversal 在暴风雨日无条件评分（_MATCHED 白名单豁免）；
        新：storm_reversal 有 match 条件（pool_item["fbt"]≤103000），任意天气命中即评分。
        无 pool_item_map → 不命中；fbt≤10:30 → 命中（晴天/暴风雨均评分）；fbt>10:30 → 不命中。
        """
        cands = [{"code": "A", "name": "A", "factors": {"factor_seal_rate": 90, "factor_freq_score": 20}}]

        # 无 pool_item_map → storm_reversal 无 fbt 不命中（晴天/暴风雨均不出现）
        assert all(s["strategy_code"] != "storm_reversal" for s in score_candidates(cands, "晴天", "limitup"))
        assert all(s["strategy_code"] != "storm_reversal" for s in score_candidates(cands, "暴风雨", "limitup"))

        # 提供 fbt≤10:30 的 pool_item_map → storm_reversal 命中（暴风雨/晴天均评分）
        pool_early = {"A": {"c": "A", "fbt": 93000, "p": 10.0}}
        assert any(s["strategy_code"] == "storm_reversal" for s in score_candidates(cands, "暴风雨", "limitup", pool_item_map=pool_early))
        assert any(s["strategy_code"] == "storm_reversal" for s in score_candidates(cands, "晴天", "limitup", pool_item_map=pool_early))

        # fbt>10:30 → 不命中
        pool_late = {"A": {"c": "A", "fbt": 140000, "p": 10.0}}
        assert all(s["strategy_code"] != "storm_reversal" for s in score_candidates(cands, "暴风雨", "limitup", pool_item_map=pool_late))

    def test_unknown_weather_uses_conservative(self):
        """未知天气 → 保守降级（首板+连板）。

        grill Q6：score_candidates 现加 match 过滤，候选必须满足入场条件才返回。
        给一个满足 first_plate（total_score>=60 且 涨停频次>20）的候选，验证降级
        路径仍能产出结果。
        """
        cands = [{
            "code": "A", "name": "A",
            "factors": {"涨停频次": 40, "封板率": 90},
            "total_score": 70,
            "zt_count_250d": 3,
        }]
        scored = score_candidates(cands, None, "limitup")
        strategy_codes = {s["strategy_code"] for s in scored}
        assert "first_plate" in strategy_codes or "consecutive_relay" in strategy_codes

    def test_grill_q6_match_filter_rejects_unqualified_candidate(self):
        """grill Q6：候选不满足入场条件 → 该策略不打分、不返回。

        break_reseal match 条件（limitup_strategy:683）：3<=zt_count_250d<=5
        且 封板率>=80。给 zt_count=3 但封板率=10 的候选 → break_reseal 应被
        过滤掉。

        grill Q7 注：阴天不再硬过滤 primary_codes（所有战法可用）。
        S094 T11 注：funnel_type="limitup" 后 dragon_head（market_scan 战法）不再在
        limitup 路径跑（R9 行为变化）——本测断言 grill Q6 核心验收点 break_reseal 被过滤，
        与 dragon_head 是否命中无关（dragon_head 已移出 limitup 路径）。
        """
        cands = [{
            "code": "000001", "name": "X",
            "factors": {"封板率": 10, "涨停频次": 5, "次日溢价率": 10},
            "total_score": 30,
            "zt_count_250d": 3,
        }]
        scored = score_candidates(cands, "阴天", "limitup")
        strategy_codes = {s["strategy_code"] for s in scored}
        # grill Q6 核心验收点：break_reseal 因封板率不满足被过滤
        assert "break_reseal" not in strategy_codes


class TestScoreCandidatesMarketScan:
    """S094 T10+T13：market_scan 分支构造 market_scan_ctx，dragon_head 条件化命中（R9）。"""

    def _cand(self, code, sector_rank, pattern=None):
        return {"code": code, "name": code, "sector": "电子",
                "sector_rank": sector_rank, "close": 10.0, "pattern": pattern}

    def _pattern(self):
        from strategies.pattern_scan import PatternScan
        return PatternScan(
            code="000001", relative_strength=5.0, ma_bullish=True, ma5_proximity=2.0,
            consolidation_days=0, consolidation_amplitude=None,
            volume_breakout_ratio=2.5, amount_yi=20.0,
            shadow_length_pct=5.0, ma5_slope=0.01,
        )

    def test_dragon_head_matches_when_sector_rank_le3(self):
        cands = [self._cand("000001", 2, self._pattern())]
        scored = score_candidates(cands, "晴天", "market_scan")
        assert any(s["strategy_code"] == "dragon_head" for s in scored)
        # S094 R12/T15: scored 复用 dispatch_match confidence（dragon_head 固定 0.5）
        assert any(s["strategy_code"] == "dragon_head" and s.get("confidence") == 0.5 for s in scored)
        # S094 audit fix: market_scan score 非零（_build_market_scan_factors 从 PatternScan 建 factors，原 cand 无 factors dict→0.0 bug）
        assert any(s["strategy_code"] == "dragon_head" and s.get("strategy_score", 0) > 0 for s in scored), \
            f"strategy_score 应 >0（非涨停 factors 已建），got: {[(s.get('strategy_code'), s.get('strategy_score')) for s in scored]}"

    def test_dragon_head_no_match_when_sector_rank_gt3(self):
        cands = [self._cand("000001", 5, self._pattern())]
        scored = score_candidates(cands, "晴天", "market_scan")
        assert all(s["strategy_code"] != "dragon_head" for s in scored)

    def test_dragon_head_no_match_without_pattern(self):
        # 无 pattern → market_scan_ctx.pattern=None → dragon_head 不命中（R9 诚实降级）
        cands = [self._cand("000001", 2, None)]
        scored = score_candidates(cands, "晴天", "market_scan")
        assert all(s["strategy_code"] != "dragon_head" for s in scored)

    def test_check_quality_drops_failing_hard_standard(self):
        # S094 R27: market_scan check_quality 闸前移——dragon_head matches(sector_rank=2)
        # 但 turnover_rate=3<5 → "换手>5%" 硬标准 fail → 丢弃（match sector_rank 与 quality turnover 维度分歧）
        cands = [{**self._cand("000001", 2, self._pattern()), "turnover_rate": 3.0}]
        scored = score_candidates(cands, "晴天", "market_scan")
        assert all(s["strategy_code"] != "dragon_head" for s in scored)

    def test_check_quality_keeps_passing_candidate(self):
        # dragon_head matches + turnover_rate=10>5 → "换手>5%" pass → 保留
        cands = [{**self._cand("000001", 2, self._pattern()), "turnover_rate": 10.0}]
        scored = score_candidates(cands, "晴天", "market_scan")
        assert any(s["strategy_code"] == "dragon_head" for s in scored)


class TestQualityStandards:
    """策略特定质量标准（spec §7）。"""

    def test_consecutive_relay_passes_with_2plus_boards(self):
        """连板接力：连板≥2 + 封板率≥80 → 通过。"""
        md = {"consecutive_boards": 3, "seal_rate": 85}
        results = check_quality_standards({}, "consecutive_relay", md)
        assert passes_hard_standards(results) is True

    def test_consecutive_relay_fails_with_1_board(self):
        """连板接力：连板=1 → 不通过硬标准。"""
        md = {"consecutive_boards": 1, "seal_rate": 85}
        results = check_quality_standards({}, "consecutive_relay", md)
        assert passes_hard_standards(results) is False

    def test_missing_data_does_not_block(self):
        """missing 数据不作为硬标准（spec §7.1）。"""
        md = {}  # 无任何数据
        results = check_quality_standards({}, "consecutive_relay", md)
        # 所有标准 missing → 不阻断
        assert passes_hard_standards(results) is True

    def test_break_reseal_needs_open_count(self):
        """炸板回封需要开板次数≥1。

        注：封板率门槛已统一为 ≥80%（S053），seal_rate 用 85 让封板率标准
        通过，聚焦验证 open_count 这条硬标准。
        """
        md = {"open_count": 2, "seal_rate": 85}
        results = check_quality_standards({}, "break_reseal", md)
        assert passes_hard_standards(results) is True

        md_fail = {"open_count": 0, "seal_rate": 85}
        results_fail = check_quality_standards({}, "break_reseal", md_fail)
        assert passes_hard_standards(results_fail) is False

    def test_reverse_package_needs_no_t1_limit_up(self):
        """反包战法需要 T-1 未涨停。"""
        md = {"t1_limit_up": False, "amount_yi": 20, "ma5": 10, "ma10": 9, "ma20": 8}
        results = check_quality_standards({}, "reverse_package", md)
        assert passes_hard_standards(results) is True

        md_fail = {"t1_limit_up": True, "amount_yi": 20, "ma5": 10, "ma10": 9, "ma20": 8}
        results_fail = check_quality_standards({}, "reverse_package", md_fail)
        assert passes_hard_standards(results_fail) is False
