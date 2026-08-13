"""S065 回填脚本：遍历 sti_timeline 存量日期，幂等回填 weather_history。

零 em_get（只读 sti_timeline dimensions，复用 compute_weather_snapshot）。
手动触发：cd backend && .venv/bin/python -m scripts.backfill_weather_history
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3

from config import STI_TIMELINE_DB_PATH
from routers.sentiment_weather import compute_weather_snapshot
from weather_history import save_weather_snapshot, get_weather_history


def main() -> None:
    conn = sqlite3.connect(STI_TIMELINE_DB_PATH)
    try:
        rows = conn.execute(
            "SELECT date FROM sti_timeline WHERE score IS NOT NULL ORDER BY date ASC"
        ).fetchall()
    finally:
        conn.close()

    dates = [r[0] for r in rows]
    print(f"sti_timeline 存量 {len(dates)} 日，开始回填 weather_history…")
    written = 0
    skipped = 0
    for d in dates:
        snapshot = compute_weather_snapshot(d)
        if snapshot.get("data_status") != "ok":
            print(f"  {d}: skip（{snapshot.get('data_status')}）")
            skipped += 1
            continue
        save_weather_snapshot(snapshot)
        print(f"  {d}: {snapshot['weather_state']} (composite={snapshot['composite_score']})")
        written += 1

    print(f"\n完成：写入 {written} / 跳过 {skipped}")
    # 幂等验证：再读一次
    hist = get_weather_history(365)
    print(f"weather_history 表现有 {len(hist)} 行")


if __name__ == "__main__":
    main()
