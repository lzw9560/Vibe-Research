#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S070 R7 trajectory + 派生历史回填——0813-0817 月表 16647 行批量 compute + persist。

根因：0817 采集时后端跑旧 scheduled_tasks（无派生段）+ 0818+ 后端没启没采集 →
intraday_features 0 行（trajectory 死）。代码已修（scheduled_tasks:877-916 派生段），
本脚本回填历史 0813-0817 trajectory + derived（填 intraday_features/seal_derived_features）。

用法：cd backend && .venv/bin/python tools/backfill_intraday_features.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from risk.seal_intraday_collector import _get_conn, get_latest_snapshots, get_snapshots_by_code  # noqa: E402
from strategies.intraday_features import (  # noqa: E402
    compute_trajectory, persist_trajectory,
    compute_derived_features, persist_derived_features,
)


def backfill(dates: list[str]) -> dict:
    """逐日批量回填 trajectory + derived。"""
    conn = _get_conn()
    stats = {"dates": [], "traj_written": 0, "derived_written": 0, "skipped": 0, "errors": []}
    try:
        for date in dates:
            latest = get_latest_snapshots(date)
            if not latest:
                stats["skipped"] += 1
                continue
            t, d = 0, 0
            for snap in latest:
                code = snap.get("code")
                name = snap.get("name") or code
                if not code:
                    continue
                snaps = get_snapshots_by_code(code, date)
                if not snaps:
                    continue
                try:
                    traj = compute_trajectory(snaps)
                    persist_trajectory(date, code, name, traj, conn)
                    t += 1
                    derived = compute_derived_features(snaps)
                    persist_derived_features(date, code, name, derived, conn)
                    d += 1
                except Exception as exc:  # noqa: BLE001
                    stats["errors"].append(f"{date} {code}: {exc}")
            stats["dates"].append({"date": date, "stocks": len(latest), "traj": t, "derived": d})
            stats["traj_written"] += t
            stats["derived_written"] += d
            print(f"[backfill] {date}: {len(latest)}只 traj={t} derived={d}", flush=True)
        conn.commit()
    finally:
        conn.close()
    return stats


if __name__ == "__main__":
    # 0813-0817（月表有数据的交易日）
    dates = ["2026-08-13", "2026-08-14", "2026-08-15", "2026-08-16", "2026-08-17"]
    t0 = datetime.now()
    stats = backfill(dates)
    elapsed = (datetime.now() - t0).total_seconds()
    print(f"\n[backfill] done: {stats['traj_written']} traj + {stats['derived_written']} derived, "
          f"{stats['skipped']} skipped, {len(stats['errors'])} errors, {elapsed:.0f}s")
    if stats["errors"]:
        print("errors:", stats["errors"][:3])
