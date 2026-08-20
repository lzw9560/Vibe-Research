# -*- coding: utf-8 -*-
"""S070：intraday 因子计算层。

R1：封单 trajectory（从 seal_intraday_snapshots 时序派生）
R7：战法因子派生（last_lock_time / broken_duration_min / max_drop_pct，纯函数）

模块提供两套接口（向后兼容 + plan §2 设计）：
- 纯函数（plan C3/C7 设计，executor/外部传入 snapshots 列表）：
  - ``compute_trajectory(snapshots) -> dict``：R1 trajectory 纯函数
  - ``compute_derived_features(snapshots) -> dict``：R7 派生纯函数
  - ``persist_trajectory(date, code, name, traj, conn)``：写 intraday_features
  - ``persist_derived_features(date, code, name, derived, conn)``：写 seal_derived_features
- DB 便利函数（遗留，内部委托纯函数，向后兼容）：
  - ``compute_seal_trajectory(date, code, db_path) -> SealTrajectory | None``
  - ``compute_all_trajectories(date, db_path) -> list[SealTrajectory]``

工程底线：
- 派生是纯函数，输入是 get_snapshots_by_code 返回的时序列表，不依赖网络
- 缺数据标 None，不臆造（data_status=missing/degraded）
- 60s 粒度近似标注（broken_duration_min 可能漏 <60s 短时炸板，AC7）
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# 60s 粒度近似标注（AC7：broken_duration_min 可能漏 <60s 短时炸板）
_GRANULARITY_NOTE = "60s粒度近似"


# ---------------------------------------------------------------------------
# R1 / R7 纯函数（plan §2 设计，输入 snapshots 列表，不依赖网络/DB）
# ---------------------------------------------------------------------------

def _linear_regression_slope(ys: list[float]) -> float:
    """简单线性回归 slope（y = a + b*x，返 b）。n<2 返 0.0。

    x 用快照序号 0..n-1（等间隔，等价于分钟数回归，避免 ts 解析依赖）。
    """
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    return numerator / denominator if denominator else 0.0


def compute_trajectory(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """R1：从封单时序派生 trajectory 因子（纯函数）。

    输入：get_snapshots_by_code(code, date) 返回的时序列表（按 ts 升序）。
    输出：{seal_delta, seal_max, seal_min, seal_slope, snapshot_count, data_status}

    算法：
    - seal_delta = seal_amount[末] - seal_amount[首]（日内封单变化）
    - seal_max / seal_min = 全时序 seal_amount 的 max / min
    - seal_slope = 线性回归 slope（x=快照序号, y=seal_amount），正=增强，负=衰减
    - snapshot_count = len(snapshots)（数据完整性参考，<10 标 degraded）
    - 空/全缺 seal_amount → data_status=missing，各因子 None
    """
    if not snapshots:
        return {"seal_delta": None, "seal_max": None, "seal_min": None,
                "seal_slope": None, "snapshot_count": 0, "data_status": "missing"}

    amounts = [s.get("seal_amount") for s in snapshots if s.get("seal_amount") is not None]
    if not amounts:
        return {"seal_delta": None, "seal_max": None, "seal_min": None,
                "seal_slope": None, "snapshot_count": len(snapshots), "data_status": "missing"}

    seal_delta = amounts[-1] - amounts[0] if len(amounts) >= 2 else 0.0
    seal_max = max(amounts)
    seal_min = min(amounts)
    seal_slope = _linear_regression_slope(amounts)
    # <10 快照标 degraded（数据不充分）
    data_status = "ok" if len(snapshots) >= 10 else "degraded"

    return {"seal_delta": seal_delta, "seal_max": seal_max, "seal_min": seal_min,
            "seal_slope": seal_slope, "snapshot_count": len(snapshots),
            "data_status": data_status}


def compute_derived_features(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """R7：从封单时序派生战法硬阈值因子（纯函数，不依赖网络）。

    输入：get_snapshots_by_code(code, date) 返回的时序列表（按 ts 升序）。
    输出：{last_lock_time, broken_duration_min, max_drop_pct, limit_price,
           granularity_note, data_status}

    算法（AC6，可被 financial_rigor.py 复算）：
    - last_lock_time：最后一个 open_count==0 的 ts（最后封死时刻）
      open_count=0 表示当前未开板；全程开板（无 open_count==0）→ None
    - broken_duration_min：count(open_count>0) × 1 分钟
      60s 粒度近似（每个快照间隔 60s），可能漏 <60s 短时炸板（AC7 标注）
    - limit_price：优先 limit_pct 反推（price/(1+limit_pct/100)），
      缺 limit_pct → 退回首快照 price 近似（标 degraded）
    - max_drop_pct：(limit_price - min(low_price)) / limit_price * 100
      缺 low_price → None（不臆造）
    """
    if not snapshots:
        return _empty_derived()

    # last_lock_time：最后一个 open_count==0 的 ts
    last_lock_time = None
    for s in snapshots:
        oc = s.get("open_count")
        if oc is not None and oc == 0:
            last_lock_time = s.get("ts")  # 不断覆盖，取最后一个

    # broken_duration_min：open_count>0 的快照数 × 1 分钟（60s 粒度）
    broken_count = sum(
        1 for s in snapshots
        if s.get("open_count") is not None and s["open_count"] > 0
    )
    broken_duration_min = float(broken_count)  # 每快照 60s = 1 分钟

    # limit_price：优先 limit_pct 反推，缺则退回首快照 price 近似
    limit_pct = snapshots[0].get("limit_pct")
    first_price = snapshots[0].get("price")
    limit_price = None
    limit_price_degraded = False
    if limit_pct is not None and first_price:
        limit_price = first_price / (1 + limit_pct / 100)
    elif first_price:
        limit_price = first_price  # 退回首价近似
        limit_price_degraded = True

    # max_drop_pct：(涨停价 - min(low_price)) / 涨停价 * 100
    low_prices = [
        s.get("low_price") for s in snapshots
        if s.get("low_price") is not None
    ]
    max_drop_pct = None
    if low_prices and limit_price and limit_price > 0:
        min_low = min(low_prices)
        max_drop_pct = (limit_price - min_low) / limit_price * 100

    # data_status
    data_status = "ok"
    if not low_prices:
        data_status = "degraded"  # 缺 low_price
    if limit_price_degraded:
        data_status = "degraded"

    return {
        "last_lock_time": last_lock_time,
        "broken_duration_min": broken_duration_min,
        "max_drop_pct": max_drop_pct,
        "limit_price": limit_price,
        "granularity_note": _GRANULARITY_NOTE,  # AC7 标注
        "data_status": data_status,
    }


def _empty_derived() -> dict[str, Any]:
    """空时序的派生结果（全 None，data_status=missing）。"""
    return {
        "last_lock_time": None,
        "broken_duration_min": None,
        "max_drop_pct": None,
        "limit_price": None,
        "granularity_note": _GRANULARITY_NOTE,
        "data_status": "missing",
    }


def persist_trajectory(date: str, code: str, name: str | None,
                       traj: dict[str, Any], conn: sqlite3.Connection) -> None:
    """R1：trajectory 写入 intraday_features 表（UPSERT）。

    conn 由调用方管理（executor 批量写时复用连接，避免逐只开闭）。
    """
    conn.execute(
        """INSERT OR REPLACE INTO intraday_features
        (date, code, name, seal_delta, seal_max, seal_min, seal_slope,
         snapshot_count, computed_at, data_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (date, code, name, traj["seal_delta"], traj["seal_max"], traj["seal_min"],
         traj["seal_slope"], traj["snapshot_count"], datetime.now().isoformat(),
         traj["data_status"]),
    )


def persist_derived_features(date: str, code: str, name: str | None,
                             derived: dict[str, Any],
                             conn: sqlite3.Connection) -> None:
    """R7：派生结果写入 seal_derived_features 表（INSERT OR REPLACE）。

    conn 由调用方管理（executor 批量写时复用连接）。
    """
    conn.execute(
        """INSERT OR REPLACE INTO seal_derived_features
        (date, code, name, last_lock_time, broken_duration_min, max_drop_pct,
         limit_price, granularity_note, computed_at, data_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (date, code, name, derived["last_lock_time"], derived["broken_duration_min"],
         derived["max_drop_pct"], derived["limit_price"], derived["granularity_note"],
         datetime.now().isoformat(), derived["data_status"]),
    )


# ---------------------------------------------------------------------------
# 遗留 DB 便利函数（向后兼容，内部委托纯函数）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SealTrajectory:
    """某日某股的封单 trajectory 特征（遗留 dataclass，向后兼容）。"""
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


def compute_seal_trajectory(date: str, code: str,
                            db_path: Path | str | None = None) -> SealTrajectory | None:
    """从 seal_intraday_snapshots 分表算 (date,code) 的封单 trajectory（DB 便利函数）。

    遗留接口，内部委托纯函数 compute_trajectory 计算 core 特征，
    额外保留 first/last/mean/break_count（遗留 dataclass 字段）。
    无数据返 None。

    S089 C7：调 ``resolve_partition(date)`` 路由到对应月分表。``db_path`` 入参
    仅在分库存在时覆盖（遗留调用方传单库路径场景）；分表不存在返 None。
    """
    from db_partition_router import resolve_partition
    resolved_db, table = resolve_partition(date)
    # 调用方显式传 db_path 时优先用之（遗留兼容），否则用路由结果
    db = Path(db_path) if db_path else Path(resolved_db)
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db), timeout=10)
    try:
        rows = conn.execute(
            f"SELECT ts, seal_amount FROM {table} WHERE date=? AND code=? ORDER BY ts",
            (date, code),
        ).fetchall()
    except sqlite3.OperationalError:
        # 分表不存在 → None（不臆造）
        return None
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


def compute_all_trajectories(date: str,
                             db_path: Path | str | None = None) -> list[SealTrajectory]:
    """某日全部 code 的 trajectory（从 snapshots distinct code）。遗留便利函数。

    S089 C7：调 ``resolve_partition(date)`` 路由到对应月分表。``db_path`` 入参
    仅在分库存在时覆盖（遗留兼容）；分表不存在返 []。
    """
    from db_partition_router import resolve_partition
    resolved_db, table = resolve_partition(date)
    db = Path(db_path) if db_path else Path(resolved_db)
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db), timeout=10)
    try:
        codes = [r[0] for r in conn.execute(
            f"SELECT DISTINCT code FROM {table} WHERE date=?", (date,)).fetchall()]
    except sqlite3.OperationalError:
        # 分表不存在 → 空集（不臆造）
        return []
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
