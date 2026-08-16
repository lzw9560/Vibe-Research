# -*- coding: utf-8 -*-
"""S070 R1：封单 trajectory（日内动态）从 seal_intraday_snapshots 导出。

封单 trajectory = 某日某股的 seal_amount 时序（per-minute snapshots）→ 动态特征：
first/last/delta/max/min/mean/slope/n_snapshots/break_count（炸板次数，seal→0 跳变）。
区别于 EOD 快照（seal_rate=首次封板时间，post-hoc）——trajectory 是日内动态（封住/衰减/炸板形态），
intraday-class 未测因子（§44 public EOD 全死，trajectory 是不同类，untested）。

§44 验证（R4，~30 日 S055 积累后）：trajectory 特征 → 次日涨停/溢价 lift>=2x。
零新 fetch（导出现有 seal_intraday_snapshots）。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from vr_paths import resolve_data_dir

_SEAL_DB = Path(resolve_data_dir()) / "seal_intraday.db"


@dataclass(frozen=True)
class SealTrajectory:
    """某日某股的封单 trajectory 特征。"""
    code: str
    date: str
    n_snapshots: int
    first_seal: float       # 开盘附近首值
    last_seal: float        # 收盘附近末值
    delta: float            # last - first（衰减为负）
    max_seal: float
    min_seal: float
    mean_seal: float
    slope: float            # 线性回归斜率（seal_amount over ts-minutes，负=衰减）
    break_count: int       # seal→0 跳变次数（炸板）


def _parse_ts_minute(ts: str) -> float:
    """ISO8601 ts → 当日分钟数（09:25:40 → 565）。解析失败返 0。"""
    try:
        # "2026-08-14T09:25:40.049833"
        tpart = ts.split("T")[1] if "T" in ts else ts
        h, m, s = tpart.split(":")[:3]
        return int(h) * 60 + int(m) + int(float(s)) / 60
    except Exception:
        return 0.0


def compute_seal_trajectory(date: str, code: str, db_path: Path | str | None = None) -> SealTrajectory | None:
    """从 seal_intraday_snapshots 算 (date,code) 的封单 trajectory。无数据返 None。"""
    db = Path(db_path) if db_path else _SEAL_DB
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db), timeout=10)
    try:
        rows = conn.execute(
            "SELECT ts, seal_amount FROM seal_intraday_snapshots WHERE date=? AND code=? ORDER BY ts",
            (date, code),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None
    seals = [r[1] or 0.0 for r in rows]
    minutes = [_parse_ts_minute(r[0]) for r in rows]
    n = len(seals)
    first_seal = seals[0]
    last_seal = seals[-1]
    delta = last_seal - first_seal
    max_seal = max(seals)
    min_seal = min(seals)
    mean_seal = sum(seals) / n
    # 线性回归 slope = seal over minute（负=衰减）
    if n >= 2:
        xbar = sum(minutes) / n
        ybar = mean_seal
        num = sum((x - xbar) * (y - ybar) for x, y in zip(minutes, seals))
        den = sum((x - xbar) ** 2 for x in minutes)
        slope = num / den if den else 0.0
    else:
        slope = 0.0
    # 炸板次数：seal→0 跳变（从 >0 到 0）
    break_count = sum(1 for i in range(1, n) if seals[i - 1] > 0 and seals[i] == 0)
    return SealTrajectory(
        code=code, date=date, n_snapshots=n,
        first_seal=round(first_seal, 2), last_seal=round(last_seal, 2),
        delta=round(delta, 2), max_seal=round(max_seal, 2),
        min_seal=round(min_seal, 2), mean_seal=round(mean_seal, 2),
        slope=round(slope, 2), break_count=break_count,
    )


def compute_all_trajectories(date: str, db_path: Path | str | None = None) -> list[SealTrajectory]:
    """某日全部 code 的 trajectory（从 snapshots distinct code）。"""
    db = Path(db_path) if db_path else _SEAL_DB
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db), timeout=10)
    try:
        codes = [r[0] for r in conn.execute(
            "SELECT DISTINCT code FROM seal_intraday_snapshots WHERE date=?", (date,)).fetchall()]
    finally:
        conn.close()
    return [t for c in codes if (t := compute_seal_trajectory(date, c, db)) is not None]


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "2026-08-14"
    ts = compute_all_trajectories(d)
    print(f"=== {d} 封单 trajectory（{len(ts)} 股）===")
    for t in ts[:5]:
        print(f"  {t.code}: n={t.n_snapshots} first={t.first_seal} last={t.last_seal} "
              f"delta={t.delta} max={t.max_seal} slope={t.slope} break={t.break_count}")
    if len(ts) > 5:
        print(f"  ... ({len(ts) - 5} more)")
