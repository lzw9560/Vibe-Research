# -*- coding: utf-8 -*-
"""S218 #10 cron-fire audit executor——cron_audit(payload) 数 missed cron。

跨日 audit（每晚 20:00 cron 触发）：扫 cron_fire.log receipt + scheduled_tasks
.last_run_at，数哪些 delivery cron 该 fire 没 fire（last_run_at 旧或 null 且今日无
receipt），返 {n_expected, n_fired, n_missed, missed:[...]}。

reality-check verdict NEEDS WORK 核心："built 但没验证 fire"——本 executor 把
"wired" 变可观测：receipt = fire 正证（executor 真跑写产出），last_run_at =
scheduler 触发正证，二者皆空 = missed（cron 从未触发，last_run_at=null 的根因）。

工程底线：不臆造（读真实 last_run_at + 真实 receipt，不猜不补）；私有数据隔离
（cron_fire.log 在 .vibe-research/，VR_DATA_DIR）；零网络（只读本地 SQLite + jsonl）。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from scheduler.cron_fire_audit import (
    DEFAULT_AUDITED_TASK_TYPES,
    _fired_task_types_today,
    _read_receipts,
)
from scheduler.db import _manager
from vr_paths import BEIJING_TZ

logger = logging.getLogger("vibe-research")

#: 默认 staleness 阈值——daily cron >36h 未跑 = missed（>1.5 天容忍 cron 漂移/节假日）。
DEFAULT_STALE_HOURS = 36


def _parse_last_run_at(s: str | None) -> datetime | None:
    """解析 last_run_at（naive 视为北京时间，tz-aware 转 Beijing）。失败返 None。

    scheduler 写 ``datetime.now().isoformat()``（naive，服务器本地时区）——本项目跑 A 股
    场景，naive 视为北京；若已是 tz-aware（带 +08:00）则转 Beijing（no-op 若同偏移）。
    """
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BEIJING_TZ)  # naive → 视为北京
    return dt


def cron_audit(payload: dict[str, Any]) -> dict[str, Any]:
    """扫 cron_fire.log + scheduled_tasks.last_run_at，数 missed cron。

    判定（per seeded enabled task whose task_type ∈ audited set）：
    - 今日有 receipt（cron_fire.log）→ fired（executor 真跑了，写产出）。
    - 否则 last_run_at recent（≤ stale_hours）→ fired（scheduler 触发了；executor 可能
      raise 前未写 receipt，但 cron 系统通了——不误判 missed）。
    - 否则（last_run_at null 或 > stale_hours）→ missed（cron 从未触发或太久没跑）。

    Args:
        payload: {
            "task_types": [str]  # 可选，默认 DEFAULT_AUDITED_TASK_TYPES，
            "stale_hours": int|float  # 可选，默认 36，
        }

    Returns:
        {"status": "ok", "as_of": iso, "n_expected": int, "n_fired": int,
         "n_missed": int, "missed": [task_name], "audited_task_types": [str],
         "stale_hours": float, "fired_today": [task_type]}
    """
    audited_types = set(payload.get("task_types") or DEFAULT_AUDITED_TASK_TYPES)
    stale_hours = payload.get("stale_hours", DEFAULT_STALE_HOURS)
    try:
        stale_hours = float(stale_hours)
    except (ValueError, TypeError):
        stale_hours = float(DEFAULT_STALE_HOURS)

    receipts = _read_receipts()
    fired_today_by_type = _fired_task_types_today(receipts)
    now = datetime.now(BEIJING_TZ)

    tasks = [t for t in _manager.list_tasks() if t.enabled and t.task_type in audited_types]
    missed: list[str] = []
    for t in tasks:
        if t.task_type in fired_today_by_type:
            continue  # 今日有 receipt → fired（executor 真跑了）
        dt = _parse_last_run_at(t.last_run_at)
        if dt is None:
            missed.append(t.name)  # last_run_at null/不可解析 → missed
            continue
        hours_since = (now - dt).total_seconds() / 3600.0
        if hours_since > stale_hours:
            missed.append(t.name)  # 太久没跑 → missed
            continue
        # last_run_at recent → fired（scheduler 触发了，无 receipt 但系统通）

    n_expected = len(tasks)
    n_missed = len(missed)
    return {
        "status": "ok",
        "as_of": now.isoformat(),
        "n_expected": n_expected,
        "n_fired": n_expected - n_missed,
        "n_missed": n_missed,
        "missed": missed,
        "audited_task_types": sorted(audited_types),
        "stale_hours": stale_hours,
        "fired_today": sorted(fired_today_by_type),
    }
