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
