# -*- coding: utf-8 -*-
"""ice_point_detector —— 冰点检测 + 落库（S235 T05，spec §5.5）。

冰点 = 连续 2 日跌停 > 50 家（市场恐慌底区域）。
- count_limit_down()：用 hithink-finance special limit-down-pool（board-aware，
  不用 -9.5% 近似——创业板/科创板 20% 板会被百分比漏判）。
- 落库每日跌停计数 → is_ice_point() 读最近 2 日判连续。
- 首日无历史 → False（不臆造历史）。

CLI runner 可注入（测试 fake，Phase B 用真实 CLI；T14 实测字段）。
"""

from __future__ import annotations
import json
import sqlite3
import subprocess
from datetime import date
from pathlib import Path
from typing import Callable

from vr_paths import resolve_data_dir  # 复用现有私有数据目录解析

# 冰点阈值：连续 2 日跌停 > 50 家（spec §2.3 社区经验参数）
ICE_THRESHOLD = 50
# CLI 调用超时（防 hang）
_CLI_TIMEOUT = 30


def _default_limit_down_runner() -> dict:
    """调 hithink-finance CLI 取跌停池。失败/无数据返 {}。

    ⚠️ 字段口径待 Phase B T14 实测确认；当前按 spec §5.5 的 pagination.total 解析。
    """
    try:
        out = subprocess.run(
            [
                "hithink-finance",
                "special",
                "limit-down-pool",
                "--size",
                "200",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    if out.returncode != 0:
        return {}
    try:
        return json.loads(out.stdout or "{}")
    except json.JSONDecodeError:
        return {}


class IcePointDetector:
    """冰点检测器。CLI runner 可注入便于测试。"""

    def __init__(
        self,
        db_path: str | Path | None = None,
        runner: Callable[[], dict] | None = None,
    ):
        if db_path is None:
            db_path = resolve_data_dir() / "tactics_icepoint.db"
        self.db_path = str(db_path)
        self._runner = runner or _default_limit_down_runner
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS ice_point_history (date TEXT PRIMARY KEY, limit_down_count INTEGER)")

    def count_limit_down(self) -> int:
        """今日跌停家数（board-aware，CLI 跌停池 pagination.total）。失败返 0。"""
        d = self._runner()
        if not isinstance(d, dict) or not d.get("ok"):
            return 0
        return int(d.get("data", {}).get("pagination", {}).get("total", 0) or 0)

    def record_today(self, today: str | None = None) -> int:
        """统计今日跌停数并落库，返回 count。"""
        count = self.count_limit_down()
        date_str = today or date.today().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ice_point_history (date, limit_down_count) VALUES (?, ?)",
                (date_str, count),
            )
        return count

    def is_ice_point(self) -> bool:
        """连续 2 日跌停 > 50 家。首日无历史 → False。"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT limit_down_count FROM ice_point_history ORDER BY date DESC LIMIT 2").fetchall()
        if len(rows) < 2:
            return False  # 首日无历史，不臆造
        return all(r[0] is not None and r[0] > ICE_THRESHOLD for r in rows)

    def is_ice_point_today(self, today: str | None = None) -> bool:
        """记录今日 + 判冰点（需今日 + 前日共 2 日历史）。"""
        self.record_today(today)
        return self.is_ice_point()
