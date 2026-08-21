"""Project-local path helpers for Vibe-Research private data.

约束（用户 2026-07-30 指令，覆盖 CLAUDE.md §1 旧"~/.vibe-research/"约定）：
所有项目相关信息只存项目目录内，不落到 home 目录。私有数据（API key /
持仓 / 研报）放入项目根的 ``.vibe-research/``（gitignored，绝不进 git）。

仍可用 ``VR_DATA_DIR`` / ``VR_REPORTS_DIR`` 环境变量覆盖（测试时 conftest
会指到临时目录隔离）。
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/vr_paths.py → 上一级即仓库根
_REPO_ROOT: Path = Path(__file__).resolve().parents[1]

#: 项目内私有数据根目录（gitignored，绝不进 git）
DEFAULT_DATA_DIR: Path = _REPO_ROOT / ".vibe-research"


def resolve_data_dir() -> Path:
    """返回生效的私有数据根目录：优先 ``$VR_DATA_DIR``，否则项目内默认。"""
    env = os.environ.get("VR_DATA_DIR")
    if env:  # 空串视同未设置
        return Path(env)
    return DEFAULT_DATA_DIR


def resolve_reports_dir() -> Path:
    """返回研报目录：优先 ``$VR_REPORTS_DIR``，否则 data_dir/myreports。"""
    env = os.environ.get("VR_REPORTS_DIR")
    if env:
        return Path(env)
    return resolve_data_dir() / "myreports"


# ---------- 交易日判断（S023 C1）----------

from datetime import date, datetime as _dt, timedelta as _td, timezone as _tz

#: 北京时区 UTC+8——所有"当前时刻"判断统一用此，杜绝 naive datetime 时区 bug
BEIJING_TZ = _tz(_td(hours=8))

# A 股法定节假日（YYYY-MM-DD）。仅列固定日期节假日，调休补班日单独标。
# 此列表保守列举已知节假日，后续可接交易日历库扩展（留扩展位）。
_A_SHARE_HOLIDAYS: set[str] = {
    # 元旦
    "2026-01-01",
    # 春节
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    # 清明
    "2026-04-06",
    # 劳动节
    "2026-05-04", "2026-05-05", "2026-05-06",
    # 端午
    "2026-06-19",
    # 中秋
    "2026-09-25",
    # 国庆
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",
}


def is_trading_day(d: date | None = None) -> bool:
    """判断是否 A 股交易日（周一至周五且非法定节假日）。

    保守实现：仅排除周末 + 已知节假日。调休补班日（周末补班）未纳入，
    量级极小且偶发，非交易日时因子会用上一交易日，影响可忽略。
    扩展位：后续接交易日历库时替换此实现。
    """
    d = d or date.today()
    if d.weekday() >= 5:  # 周六 5 / 周日 6
        return False
    return d.isoformat() not in _A_SHARE_HOLIDAYS


def last_trading_date(d: date | None = None) -> date:
    """返回 d 当日或之前的最近 A 股交易日。

    - 非交易时段（周末/节假日/盘后）回退到最近交易日。
    - d 为交易日则返回 d 本身；否则向前回溯直到交易日。
    """
    d = d or date.today()
    while not is_trading_day(d):
        d = d - _td(days=1)
    return d


def prev_trading_date(d: date | None = None) -> date:
    """返回 d 之前（不含 d）的最近交易日——严格前一交易日。

    last_trading_date(d) 在 d 为交易日时返回 d 本身，故"前一交易日"须先退一日
    再回退过周末/节假日，否则取到当日。S088 grill Q1：predict_storm 预测交易日
    时须读前一交易日的夜间快照，而非当日快照。
    """
    d = d or date.today()
    return last_trading_date(d - _td(days=1))


def last_trading_date_str(d: date | None = None) -> str:
    """返回 last_trading_date 的 YYYY-MM-DD 字符串。"""
    return last_trading_date(d).isoformat()
