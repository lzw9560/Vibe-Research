# -*- coding: utf-8 -*-
"""S070 §44 60日复验窗口验证 —— intraday 因子 lift 验证占位。

⚠️ 日历阻塞：当前 intraday 数据积累不足 30 日（seal_intraday_snapshots 自 2026-08-11 起采）。
本模块为占位实现，30 日数据积累后补完验证逻辑。

验证目标（spec R4/AC3）：
  - intraday 因子（封单 trajectory + 战法因子派生：last_lock_time/broken_duration_min/max_drop_pct）
    对"次日涨停/溢价"的 lift（实际值 vs 随机期望）
  - 复用 sector_heat_validation 口径（热/冷分位 + Wilson CI + lift）
  - 破 2x → validated 接选股权重升级；<2x → 标未 validated 保留接入 + 考虑 pivot

诚实标注（spec R5/AC4）：
  - 未满 30 日标"探索性/未 validated"
  - 不臆造，缺数据标 None
  - 派生字段（seal_derived_features）data_status 在缺数据场景标 degraded/missing 非 ok

TODO（30 日后补）：
  - implement validate_intraday_factors(window_days=60) -> ValidationReport
  - 复用 tools/sector_heat_validation.py 的 Wilson CI + lift 计算
  - 输出报告：因子命中率/空池率/lift/validated 判定

关联：
  - spec: specs/S070-intraday采集管道/spec.md §3.1 R4 + §6.2 A3
  - 派生数据源: backend/strategies/intraday_features.py::compute_derived_features
  - 持久化: seal_derived_features 表（intraday_features R3 迁移已建）
"""
from __future__ import annotations


def validate_intraday_factors(window_days: int = 60) -> dict:
    """占位：intraday 因子 lift 验证。

    当前状态：日历阻塞（数据积累 < 30 日）。
    30 日后实现：对 window_days 内的派生因子做 lift 验证。

    Returns:
        dict: 占位返回，标"探索性/未 validated"
    """
    return {
        "status": "calendar_blocked",
        "reason": "intraday 数据积累不足 30 日（seal_intraday_snapshots 自 2026-08-11 起采）",
        "validated": False,
        "exploratory": True,
        "window_days": window_days,
        "todo": "30 日后补完 validate_intraday_factors 逻辑（复用 sector_heat_validation 口径）",
    }
