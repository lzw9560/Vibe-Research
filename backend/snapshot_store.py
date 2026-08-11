# -*- coding: utf-8 -*-
"""S050 W0：盘前快照读取共享模块（settlement_recorder 与 routers/workflow 共用）。

抽离自 routers/workflow.py 的 _load_snapshot/_list_snapshot_dates——
settlement_recorder 需读快照 final_candidates 做票根关联，但直接 import
routers.* 会形成反向依赖（routers → settlement_recorder 已存在）。
抽出共享模块后双方共用，行为零变化（纯重构）。

快照文件位置：<VR_DATA_DIR>/workflow/pre-market/<date>.json（私有，gitignored）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from vr_paths import resolve_data_dir

logger = logging.getLogger(__name__)


def _snapshot_dir() -> Path:
    """快照目录：<私有数据根>/workflow/pre-market/（VR_DATA_DIR 可覆盖，conftest 已隔离）。"""
    return resolve_data_dir() / "workflow" / "pre-market"


def _snapshot_path(date: str) -> Path:
    """快照文件路径：<快照目录>/<date>.json。"""
    return _snapshot_dir() / f"{date}.json"


def _is_valid_date(d: str) -> bool:
    try:
        from datetime import datetime
        datetime.strptime(d, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def load_snapshot(date: str) -> Optional[dict]:
    """读快照；不存在/损坏返 None（只读语义，不自愈删除）。

    settlement_recorder 票根关联调用此函数查 final_candidates。
    """
    try:
        p = _snapshot_path(date)
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("快照读取失败 %s: %s", date, exc)
        return None


def list_snapshot_dates() -> list[str]:
    """有快照的日期降序列表；忽略非日期文件名。"""
    d = _snapshot_dir()
    if not d.is_dir():
        return []
    return sorted((p.stem for p in d.glob("*.json") if _is_valid_date(p.stem)), reverse=True)
