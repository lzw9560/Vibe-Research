# -*- coding: utf-8 -*-
"""s234_bridge —— S234 排雷过滤器接线（S235 T18，spec §plan S234 filter 映射）。

S235 三战法 → S234 战法映射，过排雷 filter，Block 则信号压制不推送（仍落库标 suppressed）。

设计：filter_fn 依赖注入（调用方传 filter_stock+to_json 包装）。tactics 包不直接
import tools/short_term_tactics_filter（避免 path 耦合），便于纯逻辑测试。
"""
from __future__ import annotations
from typing import Callable

# S235 战法 → S234 战法映射（spec §plan）
# ice_rebound 无 S234 对应（冰点反抽只过第一层财务硬过滤）
TACTIC_TO_S234: dict[str, str | None] = {
    "reversal": "战法1_弱转强",
    "tail_breakout": "战法2_尾盘锁定",
    "ice_rebound": None,
}


def apply_s234_filter(
    code: str,
    tactic_name: str,
    filter_fn: Callable[[str, str], dict],
) -> dict:
    """过 S234 排雷 filter，返回 verdict dict。

    Args:
        code: 标的代码（6 位纯数字或 sh./sz. 前缀，filter 内部 _normalize_code）。
        tactic_name: S235 战法名（reversal / tail_breakout / ice_rebound）。
        filter_fn: 调用方注入，签名 (code, s234_tactic) -> dict（含 safe_action/verdict 等）。
                   调用方包装：`lambda c, t: to_json(filter_stock(c, t))`。

    Returns:
        S234 verdict dict（safe_action: Pass/Block/Refuse + verdict + ...）。
        ice_rebound → 直接 Pass（仅过第一层财务过滤，S234 无对应战法）。
        filter_fn 异常 → 降级 Pass（不阻断信号，但 verdict 标异常）。
    """
    s234_tactic = TACTIC_TO_S234.get(tactic_name)
    if s234_tactic is None:
        # 冰点反抽：S234 无对应战法，只过第一层财务硬过滤（由调用方另行调 first_layer_filter）
        return {
            "safe_action": "Pass",
            "verdict": "冰点反抽：S234 无对应战法，仅过第一层财务硬过滤",
            "tactic": tactic_name,
            "code": code,
        }
    try:
        result = filter_fn(code, s234_tactic)
    except Exception as e:
        # filter 异常不阻断信号（降级 Pass），但 verdict 标异常供审计
        return {
            "safe_action": "Pass",
            "verdict": f"S234 filter 异常（降级 Pass）: {e}",
            "tactic": tactic_name,
            "s235_tactic": tactic_name,
            "code": code,
        }
    # 透传 filter 结果 + 标 S235 战法名（飞书卡片展示）
    if isinstance(result, dict):
        result = {**result, "s235_tactic": tactic_name}
    return result


def should_suppress(s234_result: dict) -> bool:
    """safe_action=Block → 信号压制不推送（仍落库标 suppressed）。

    Refuse（黑名单）也压制。Pass（观察池）不压制。
    """
    action = str(s234_result.get("safe_action", "")).lower()
    return action in ("block", "refuse")
