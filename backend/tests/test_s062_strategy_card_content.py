# -*- coding: utf-8 -*-
"""S062：战法卡内容填充测试。

覆盖：
- A1 注册表 schema：dragon_head 新条目 + reverse_package 参数精化
- A2 卡片存在且含来源与样本期段落
- A3 S053 对照结论有文字记录（reverse_package 卡片）
"""
from __future__ import annotations

import pytest

from limitup_strategy import STRATEGY_REGISTRY


def _get(code: str) -> dict:
    return next(s for s in STRATEGY_REGISTRY if s["code"] == code)


class TestRegistrySchema:
    """A1：注册表 schema 测试。"""

    def test_dragon_head_entry_exists(self):
        codes = [s["code"] for s in STRATEGY_REGISTRY]
        assert "dragon_head" in codes, "STRATEGY_REGISTRY 缺 dragon_head 条目"

    def test_dragon_head_has_required_fields(self):
        s = _get("dragon_head")
        assert s["name"] == "龙头战法"
        assert "晴天" in s["weather_regimes"]
        assert "阴天" in s["weather_regimes"]
        assert "龙头" in s["aliases"]

    def test_dragon_head_entry_conditions(self):
        s = _get("dragon_head")
        # 关键条件字段含板块领涨 + 相对强度 + 换手 + 量比 + 催化
        ec = s["entry_condition"]
        assert "板块领涨" in ec
        assert "相对强度" in ec
        assert "换手" in ec
        assert "量比" in ec
        assert "催化" in ec

    def test_dragon_head_exit_params(self):
        s = _get("dragon_head")
        assert s["max_hold_days"] == 5
        assert s["stop_loss_pct"] == -5.0
        assert s["take_profit_pct"] == 15.0

    def test_reverse_package_max_hold_days_is_t_plus_1(self):
        """S062 T1：reverse_package max_hold_days 2→1（严格 T+1 纪律）。"""
        s = _get("reverse_package")
        assert s["max_hold_days"] == 1

    def test_reverse_package_entry_condition_absorbs_fanbao_five(self):
        """S062 T1：entry_condition 吸收 fanbao 五条件关键字。"""
        ec = _get("reverse_package")["entry_condition"]
        # fanbao 五条件关键字
        assert "T-2" in ec and "T-3" in ec  # T-2/T-3 涨停（加分）
        assert "T-1" in ec  # T-1 未涨停 + T-1 成交额
        assert "15亿" in ec  # T-1 成交额>15亿
        assert "M7/M14" in ec or "均线多头" in ec  # 均线多头
        assert "实体" in ec  # 实体涨跌幅

    def test_reverse_package_retains_weather_regimes(self):
        s = _get("reverse_package")
        assert "极端反弹" in s["weather_regimes"]


class TestCardContent:
    """A2/A3：卡片内容测试。"""

    def test_dragon_head_card_exists_with_source_section(self):
        from ai.tools.strategy_tools import query_strategy_card

        result = query_strategy_card("dragon_head")
        assert "error" not in result, result.get("error")
        card = result["card"]
        assert "适用天气" in card
        assert "来源与样本期" in card, "dragon_head 卡片缺来源与样本期段落"
        assert "历史统计" in card  # 风险提醒

    def test_dragon_head_card_sources_attribution(self):
        from ai.tools.strategy_tools import query_strategy_card

        card = query_strategy_card("dragon_head")["card"]
        # 两个源项目都应出现
        assert "ZhuLinsen" in card or "daily_stock_analysis" in card
        assert "attrib2004" in card or "a-share-dragon-strategy" in card

    def test_reverse_package_card_has_source_section(self):
        from ai.tools.strategy_tools import query_strategy_card

        card = query_strategy_card("reverse_package")["card"]
        assert "来源与样本期" in card, "reverse_package 卡片缺来源与样本期段落"
        # fanbao 数字原文引用
        assert "47.62%" in card  # 实盘胜率
        assert "50.9%" in card  # 回测胜率
        assert "629" in card  # 回测交易笔数
        assert "357" in card  # 实盘交易笔数
        assert "历史统计" in card  # 风险提醒

    def test_reverse_package_card_has_s053_conclusion(self):
        """A3：S053 对照结论有文字记录。"""
        from ai.tools.strategy_tools import query_strategy_card

        card = query_strategy_card("reverse_package")["card"]
        assert "S053" in card, "reverse_package 卡片缺 S053 对照结论"
        assert "炸板后溢价" in card or "因子缺供" in card


class TestRegistryCompleteness:
    """所有注册表条目都有卡片 + 风险提醒（回归 S058）。"""

    def test_all_cards_exist_for_registry(self):
        from ai.tools.strategy_tools import query_strategy_card

        for s in STRATEGY_REGISTRY:
            result = query_strategy_card(s["code"])
            assert "error" not in result, f"{s['code']} 卡片缺失：{result.get('error')}"
            assert "适用天气" in result["card"]
            assert "历史统计" in result["card"]
