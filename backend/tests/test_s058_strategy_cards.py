# -*- coding: utf-8 -*-
"""S058：战法双层卡片 + 天气适配软过滤测试。

覆盖：注册表 schema（weather_regimes/aliases）、适配度三态逻辑、
query_strategy_card 命中/别名/缺失、卡片完整性。
"""

import pytest

from limitup_strategy import (
    STRATEGY_REGISTRY,
    calc_weather_fit,
    get_strategy_registry,
)


class TestRegistrySchema:
    def test_every_strategy_has_weather_regimes(self):
        for s in STRATEGY_REGISTRY:
            assert "weather_regimes" in s, f"{s['code']} 缺 weather_regimes"
            assert isinstance(s["weather_regimes"], list)

    def test_every_strategy_has_aliases(self):
        for s in STRATEGY_REGISTRY:
            assert "aliases" in s, f"{s['code']} 缺 aliases"
            assert isinstance(s["aliases"], list)

    def test_get_strategy_registry_includes_new_fields(self):
        regs = get_strategy_registry()
        for r in regs:
            assert "weather_regimes" in r
            assert "aliases" in r

    def test_first_plate_maps_to_yintian(self):
        s = next(s for s in STRATEGY_REGISTRY if s["code"] == "first_plate")
        assert "阴天" in s["weather_regimes"]

    def test_consecutive_relay_maps_to_qingtian(self):
        s = next(s for s in STRATEGY_REGISTRY if s["code"] == "consecutive_relay")
        assert "晴天" in s["weather_regimes"]

    def test_reverse_package_maps_to_extreme_rebound(self):
        s = next(s for s in STRATEGY_REGISTRY if s["code"] == "reverse_package")
        assert "极端反弹" in s["weather_regimes"]


class TestWeatherFit:
    def test_fit_when_weather_in_regimes(self):
        assert calc_weather_fit("consecutive_relay", "晴天") == "适配"

    def test_unfit_when_weather_not_in_regimes(self):
        assert calc_weather_fit("consecutive_relay", "阴天") == "不适配"

    def test_neutral_when_weather_none(self):
        assert calc_weather_fit("consecutive_relay", None) == "中性"

    def test_neutral_when_weather_unknown(self):
        # 未知天气（regimes 非空但不含）应返不适配，而非中性
        # 但 None 或空字符串返中性
        assert calc_weather_fit("consecutive_relay", "") == "中性"

    def test_neutral_when_strategy_code_unknown(self):
        assert calc_weather_fit("bogus_code", "晴天") == "中性"

    def test_low_absorption_fits_both_qingtian_and_yintian(self):
        assert calc_weather_fit("low_absorption", "晴天") == "适配"
        assert calc_weather_fit("low_absorption", "阴天") == "适配"


class TestQueryStrategyCard:
    def test_query_by_code_returns_card_text(self):
        from ai.tools.strategy_tools import query_strategy_card

        result = query_strategy_card("first_plate")
        assert "error" not in result
        assert result["code"] == "first_plate"
        assert "首板挖掘" in result["card"]
        assert "适用天气" in result["card"]

    def test_query_by_alias_resolves_code(self):
        from ai.tools.strategy_tools import query_strategy_card

        result = query_strategy_card("首板")
        assert "error" not in result
        assert result["code"] == "first_plate"

    def test_query_unknown_code_returns_error(self):
        from ai.tools.strategy_tools import query_strategy_card

        result = query_strategy_card("bogus_strategy")
        assert "error" in result
        assert "bogus_strategy" in result["error"]

    def test_all_cards_exist_for_registry(self):
        """卡片完整性：cards/ 目录与注册表 code 一一对应。"""
        from ai.tools.strategy_tools import query_strategy_card

        for s in STRATEGY_REGISTRY:
            result = query_strategy_card(s["code"])
            assert "error" not in result, f"{s['code']} 卡片缺失：{result.get('error')}"
            assert "适用天气" in result["card"], f"{s['code']} 卡片缺适用天气段"


class TestCardContent:
    def test_card_has_risk_disclaimer(self):
        """战法卡尾挂轻量风险提醒。"""
        from ai.tools.strategy_tools import query_strategy_card

        for s in STRATEGY_REGISTRY:
            result = query_strategy_card(s["code"])
            assert "历史统计特征" in result["card"], f"{s['code']} 卡片缺风险提醒"


class TestCardConditionAlignment:
    """S100：卡片入场条件与 match() 对齐（条件数 + 阈值数值双断言，防 S058 停滞漂移）。

    基准 = 实际 match() 代码（fa4514e 2026-08-27 后），非 S097 §5.2（已知 first_plate/
    end_of_day_sneak 两处被 fa4514e 改写，§5.2 旧值 60/20、>40 已过期）。卡片经
    strategy_tools 喂 chat/MCP/CLI 三出口，条件与 match 不一致 = AI 基于错误条件给判断。
    """

    # code -> (入场条件 bullet 数 = match total_count, 卡片须含的非通用阈值数值 list)
    CARD_ALIGN: dict[str, tuple[int, list[str]]] = {
        "first_plate": (2, ["40", "6"]),            # total_score≥40 / 涨停频次≥6
        "consecutive_relay": (2, ["60"]),           # 封板率≥60（旧卡片 80% 漂移）
        "break_reseal": (2, ["80"]),                # 封板率≥80
        "low_absorption": (2, []),                  # ma5_proximity≤3 / ma_bullish（阈值通用，靠 count）
        "n_shape_counterattack": (1, []),           # zt∈[2,10] 单条件
        "platform_breakout": (2, []),              # consolidation≥5 / vol_ratio>2
        "end_of_day_sneak": (2, ["15"]),           # 封板率≥40 / 次日溢价率>15（旧 >40 漂移）
        "dragon_head": (1, []),                     # sector_rank≤3 单条件（旧 5 条漂移）
        "weak_turn_strong": (5, ["14:40", "1.8", "3.0"]),  # C1-C5
        "pattern_reversal": (3, ["1.2"]),          # shadow≥4 / vol≥1.2 / ma5>0
        "reverse_package": (1, []),                # open_count≥2 单条件（旧 6 条漂移）
        "storm_reversal": (1, ["10:30"]),          # fbt≤10:30 单条件
    }

    def _entry_bullets(self, card: str) -> list[str]:
        """解析卡片「## 入场条件」段的 bullet 行（行首 - 或 *）。"""
        in_section = False
        bullets: list[str] = []
        for line in card.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                in_section = "入场条件" in stripped
                continue
            if in_section and (stripped.startswith("- ") or stripped.startswith("* ")):
                bullets.append(stripped[2:])
        return bullets

    def test_entry_condition_count_matches_match_total(self):
        """卡片入场条件 bullet 数 == match StrategyMatchResult.total_count。"""
        from ai.tools.strategy_tools import query_strategy_card

        for code, (expected_count, _) in self.CARD_ALIGN.items():
            card = query_strategy_card(code)["card"]
            actual = len(self._entry_bullets(card))
            assert actual == expected_count, (
                f"{code}: 卡片入场条件 {actual} 条 vs match total_count {expected_count}"
            )

    def test_card_contains_match_threshold_values(self):
        """卡片含 match 真实阈值数值（防 first_plate 60→40 / end_of_day_sneak >40→>15 漂移）。"""
        from ai.tools.strategy_tools import query_strategy_card

        for code, (_, thresholds) in self.CARD_ALIGN.items():
            card = query_strategy_card(code)["card"]
            for t in thresholds:
                assert t in card, f"{code}: 卡片缺阈值 {t}（应含 match 真实阈值）"
