# -*- coding: utf-8 -*-
"""S094 席位画像迁移：seat_profiles.json (A 链路) → seat_profiles.db 宽表。

读取 backend/seat_profiles.json 的 205 个席位存量数据，写入
.vibe-research/seat_profiles.db 的 seat_profiles 表（A 字段，B 字段全 NULL）。

跑：.venv/bin/python scripts/migrate_seat_profiles_to_db.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# backend 目录入 sys.path
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from seat_engine.data import save_profiles_to_db  # noqa: E402
from config import SEAT_PROFILES_DB_PATH  # noqa: E402

_JSON_PATH = _BACKEND / "seat_profiles.json"


def main() -> None:
    print("=== 席位画像迁移：seat_profiles.json → seat_profiles.db ===")
    if not _JSON_PATH.exists():
        print(f"❌ 源文件不存在：{_JSON_PATH}")
        sys.exit(1)

    with open(_JSON_PATH, "r", encoding="utf-8") as f:
        profiles = json.load(f)
    print(f"读取 {len(profiles)} 个席位画像 from {_JSON_PATH}")

    # save_profiles_to_db 已处理建表 + UPSERT
    save_profiles_to_db(profiles)
    print(f"写入 seat_profiles 表（A 字段，B 字段全 NULL）")

    # 验证
    conn = sqlite3.connect(SEAT_PROFILES_DB_PATH)
    try:
        count = conn.execute("SELECT COUNT(*) FROM seat_profiles").fetchone()[0]
        a_nonempty = conn.execute(
            "SELECT COUNT(*) FROM seat_profiles WHERE total_appearances IS NOT NULL"
        ).fetchone()[0]
        b_null = conn.execute(
            "SELECT COUNT(*) FROM seat_profiles WHERE next_day_sell_rate IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()

    print(f"\n验证：")
    print(f"  SELECT COUNT(*) = {count}")
    print(f"  A 字段非空行数 = {a_nonempty}")
    print(f"  B 字段全 NULL 行数 = {b_null}")
    if count == len(profiles) == 205:
        print(f"✅ 迁移成功：{count} 行（= 205）")
    else:
        print(f"⚠️ 行数不符：期望 205，实际 {count}")
        sys.exit(1)


if __name__ == "__main__":
    main()
