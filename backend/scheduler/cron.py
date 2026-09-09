# -*- coding: utf-8 -*-
"""cron 表达式匹配——纯函数无状态。"""
from __future__ import annotations

from datetime import datetime


# 各字段合法值域：[分, 时, 日, 月, 周]，weekday 0=周一..6=周日
_CRON_FIELD_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


def _cron_token_match(token: str, value: int, lo: int, hi: int) -> bool:
    """单个逗号子项匹配：支持 单值 / */n / a-b / a-b/n。非法子项返回 False。"""
    step = 1
    range_part = token
    if "/" in token:
        range_part, step_str = token.split("/", 1)
        if not step_str.isdigit() or int(step_str) <= 0:
            return False
        step = int(step_str)

    if range_part == "*":
        return value % step == 0

    if "-" in range_part:
        a_str, b_str = range_part.split("-", 1)
        if not a_str.isdigit() or not b_str.isdigit():
            return False
        a, b = int(a_str), int(b_str)
        if a < lo or b > hi or a > b:
            return False
        return a <= value <= b and (value - a) % step == 0

    if not range_part.isdigit():
        return False
    n = int(range_part)
    if n < lo or n > hi:
        return False
    if step == 1:
        return value == n
    return value >= n and (value - n) % step == 0


def _cron_field_match(field: str, value: int, lo: int, hi: int) -> bool:
    """单字段匹配：``*`` 恒 True；逗号分隔的任意一个子项命中即命中。"""
    if field == "*":
        return True
    for token in field.split(","):
        if _cron_token_match(token, value, lo, hi):
            return True
    return False


def cron_match(cron_expr: str, dt: datetime) -> bool:
    """cron 5 段表达式匹配（分 时 日 月 周）。纯函数，非法输入一律 False、不抛异常。

    - ``*`` → 恒 True
    - 单值数字 → 相等
    - ``*/n`` → value % n == 0（``*/0`` / ``*/x`` 非法 → False；``*/1`` 等价 ``*``）
    - ``a-b`` → 含边界的范围
    - ``a-b/n`` → 范围内且 (value - a) % n == 0
    - 逗号 OR（可混合 range，如 ``0-30,45``）
    - weekday 用 ``dt.weekday()``（0=周一..6=周日）
    """
    try:
        parts = cron_expr.split()
        if len(parts) != 5:
            return False
        values = (dt.minute, dt.hour, dt.day, dt.month, dt.weekday())
        for field, value, (lo, hi) in zip(parts, values, _CRON_FIELD_BOUNDS):
            if not _cron_field_match(field, value, lo, hi):
                return False
        return True
    except Exception:
        return False
