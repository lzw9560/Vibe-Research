# -*- coding: utf-8 -*-
"""天气-策略推荐（spec §3.3，grill Q7 降级为软标注；S086 R3 暴风雨不再硬约束）。

所有战法对所有天气可用，天气匹配的标注"推荐"（weather_recommended）。
理由：(1) T-1 天气不代表 T 日天气；(2) §13.0 验证天气路由无统计显著提升；
      (3) 强约束导致 0 候选比无约束更有害。
"""
from __future__ import annotations


# grill Q7 + S086 R3：天气硬开关降级为软标注（含暴风雨例外移除）
WEATHER_RECOMMENDATION: dict[str, set[str]] = {
    "晴天":   {"consecutive_relay", "dragon_head", "platform_breakout"},
    "阴天":   {"first_plate", "break_reseal", "end_of_day_sneak"},
    "极端反弹": {"reverse_package"},
    "暴风雨": {"storm_reversal"},  # 软标注推荐（不再硬约束仓位=0）
    "未知":   set(),
}

# 向后兼容 alias（grill Q7 后应改用 WEATHER_RECOMMENDATION）
WEATHER_STRATEGY_MAP = {k: list(v) for k, v in WEATHER_RECOMMENDATION.items()}

FALLBACK_STRATEGIES: dict[str, list[str]] = {
    "晴天":   ["low_absorption"],
    "阴天":   ["low_absorption"],
    "极端反弹": [],
    "暴风雨": [],   # 暴风雨无 fallback——空仓也是策略
    "未知":   [],
}


def get_weather_recommendation(weather_state: str | None) -> set[str]:
    """天气推荐战法集合（软标注，不用于过滤候选）。"""
    if not weather_state:
        return set()
    return WEATHER_RECOMMENDATION.get(weather_state, set())


def get_strategies_for_weather(weather_state: str | None) -> tuple[list[str], list[str]]:
    """天气 → (主跑策略 codes, fallback 策略 codes)。

    S086 R3：暴风雨不再硬约束（全 allowed）；所有天气返回所有已注册战法（非空），
    fallback 恒为 []。天气推荐集合用 get_weather_recommendation() 查。
    """
    from strategies.funnel.registry import STRATEGY_REGISTRY
    all_codes = [s.code for s in STRATEGY_REGISTRY]
    return (all_codes, [])
