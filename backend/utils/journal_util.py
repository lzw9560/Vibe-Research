# -*- coding: utf-8 -*-
"""journal/risk 家族共享的底层 I/O 与时间助手。

S166 fresh-impl（design-agnostic，非 vibe-astock 移植）：
- ``atomic_write_json``：原子写 JSON——tmp + os.replace + fsync，断电/崩溃不留空壳。
- ``china_now`` / ``china_today``：上海时区时间（无 zoneinfo 退回本机时间）。
- ``validate_trade_date``：严格解析 YYYY-MM-DD，拒绝非法/未来日期——所有日期入口的闸门，
  杜绝目录穿越。

这三个函数被 journal / excursion / at_risk / risk_rules 共享（DRY），故提取到此。
"""
from __future__ import annotations

import datetime
import json
import os
import uuid

try:
    from zoneinfo import ZoneInfo

    _CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001  无时区库退回本机时间（聊胜于无）
    _CN_TZ = None


def china_now() -> datetime.datetime:
    """上海时区当前时间（无 zoneinfo 时退回本机时间）。"""
    return datetime.datetime.now(_CN_TZ) if _CN_TZ else datetime.datetime.now()


def china_today() -> str:
    """上海时区今日 YYYY-MM-DD。"""
    return china_now().strftime("%Y-%m-%d")


def validate_trade_date(date: str) -> str:
    """严格解析 YYYY-MM-DD，拒绝非法/未来日期，返回规范化字符串。

    所有入口（API/CLI）的日期闸门：只有通过校验的规范日期才进入文件名和数据查询，
    杜绝 ``../../`` 目录穿越。
    """
    if not isinstance(date, str):
        raise ValueError(f"日期需为字符串，得到 {type(date).__name__}")
    try:
        d = datetime.datetime.strptime(date.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"非法日期 {date!r}，需 YYYY-MM-DD 格式")
    if d.strftime("%Y-%m-%d") > china_today():
        raise ValueError(f"拒绝未来日期 {date}")
    return d.strftime("%Y-%m-%d")


def atomic_write_json(path: str, payload: object) -> bool:
    """原子写 JSON 缓存。

    tmp + os.replace + fsync：断电/崩溃时不留"存在但内容为空"的缓存。
    写成功 True，失败 False（缓存失败从不影响调用方返回值）。
    """
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


__all__ = ["china_now", "china_today", "validate_trade_date", "atomic_write_json"]
