# -*- coding: utf-8 -*-
"""情绪温度指数（STI）引擎 —— 兼容 facade（实际实现已拆分到 data/service/models）。"""

from __future__ import annotations

import threading
from limitup_sti.models import (
    STIPhase,
    STIDimension,
    STIResult,
    DISCLAIMER,
    STI_WEIGHTS,
    STI_DIRECTIONS,
    TOTAL_WEIGHT,
    PHASE_EXPLANATIONS,
    percentile_rank,
    _safe_float,
    _ema_3day,
)
from limitup_sti.service import STIEngine, get_sti_engine, _BEIJING_TZ

# 公开别名：routers/sti.py 等以 ``limitup_sti.BEIJING_TZ`` 引用（service 内定义为私有 _BEIJING_TZ）
BEIJING_TZ = _BEIJING_TZ

import logging
_logger = logging.getLogger(__name__)

# 模块导入时自动运行迁移（幂等）——镜像 limitup_screener/__init__.py；
# 否则 fresh DB（测试/新部署）未实例化 STIEngine 时不建 sti_timeline → /api/health "no such table"。
try:
    from limitup_sti.data import run_initial_migrations
    run_initial_migrations()
    # S063 T1：sti_intraday 盘中采样表迁移（幂等，已应用则跳过）
    try:
        from pathlib import Path as _Path
        from migrations import MigrationManager as _MM
        from config import STI_TIMELINE_DB_PATH as _STI_DB
        _intraday_sql = (
            _Path(__file__).resolve().parent.parent
            / "migrations" / "sti" / "20260813-001_create_sti_intraday.sql"
        ).read_text(encoding="utf-8")
        _intraday_zone_sql = (
            _Path(__file__).resolve().parent.parent
            / "migrations" / "sti" / "20260813-002_add_sti_intraday_zone.sql"
        ).read_text(encoding="utf-8")
        _MM(db_path=_STI_DB).upgrade([
            {"version": "20260813-001", "name": "create_sti_intraday", "sql": _intraday_sql},
            {"version": "20260813-002", "name": "add_sti_intraday_zone", "sql": _intraday_zone_sql},
        ])
        # S065：weather_history 持久化（幂等，W1 证据层前置）
        try:
            _weather_sql = (
                _Path(__file__).resolve().parent.parent
                / "migrations" / "sti" / "20260813-003_create_weather_history.sql"
            ).read_text(encoding="utf-8")
            _MM(db_path=_STI_DB).upgrade([
                {"version": "20260813-003", "name": "create_weather_history", "sql": _weather_sql},
            ])
        except Exception as _we:
            _logger.warning("[limitup_sti] weather_history 迁移失败（不影响主流程）: %s", _we)
        # S063 T4 补齐：sti_timeline 加 raw_break_rate 列（盘前简报 T-1 炸板率直读）
        try:
            _raw_br_sql = (
                _Path(__file__).resolve().parent.parent
                / "migrations" / "sti" / "20260817-001_add_raw_break_rate.sql"
            ).read_text(encoding="utf-8")
            _MM(db_path=_STI_DB).upgrade([
                {"version": "20260817-001", "name": "add_raw_break_rate", "sql": _raw_br_sql},
            ])
        except Exception as _re:
            _logger.warning("[limitup_sti] raw_break_rate 迁移失败（不影响主流程）: %s", _re)
    except Exception as _e:
        _logger.warning("[limitup_sti] sti_intraday 迁移失败（不影响主流程）: %s", _e)
except Exception as e:
    _logger.warning("[limitup_sti] 自动迁移失败（不影响主流程）: %s", e)

# 兼容旧接口的模块级变量
_sti_lock = threading.Lock()
_sti_scores: list[float] = []

__all__ = [
    "STIEngine",
    "get_sti_engine",
    "BEIJING_TZ",
    "STIPhase",
    "STIDimension",
    "STIResult",
    "DISCLAIMER",
    "STI_WEIGHTS",
    "STI_DIRECTIONS",
    "TOTAL_WEIGHT",
    "PHASE_EXPLANATIONS",
    "percentile_rank",
    "_safe_float",
    "_ema_3day",
    "_sti_lock",
    "_sti_scores",
]
