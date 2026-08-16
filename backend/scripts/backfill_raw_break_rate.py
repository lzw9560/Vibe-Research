"""S063 T4 补齐回填脚本：遍历 sti_timeline 存量日期，幂等回填 raw_break_rate 列。

历史行（2026-08-17 迁移前）raw_break_rate IS NULL，盘前简报 T-1 炸板率显 "--"。
本脚本对每个缺失行调 market._emotion(d) 重算原始 0-1 比率（zb/(zt+zb)）并落库。

限流防封：每日间 sleep 1.2s（参考 limitup_sti/service.py:291 backfill 范式）。
幂等：raw_break_rate IS NULL 过滤确保只回填缺失行，重复运行不重复写、不覆盖已有值。

手动触发：
    cd backend && .venv/bin/python -m scripts.backfill_raw_break_rate
    cd backend && .venv/bin/python -m scripts.backfill_raw_break_rate --dry-run
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import STI_TIMELINE_DB_PATH  # noqa: E402
from market import _emotion  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="幂等回填 sti_timeline.raw_break_rate（仅写 NULL 行）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将回填的日期列表，不实际写库",
    )
    args = parser.parse_args()

    try:
        conn = sqlite3.connect(STI_TIMELINE_DB_PATH)
    except Exception as exc:
        print(f"[FATAL] 连接 DB 失败：{STI_TIMELINE_DB_PATH} -> {exc}")
        sys.exit(1)

    try:
        rows = conn.execute(
            "SELECT date FROM sti_timeline "
            "WHERE raw_break_rate IS NULL AND score IS NOT NULL "
            "ORDER BY date ASC"
        ).fetchall()
    except Exception as exc:
        print(f"[FATAL] 查询 raw_break_rate 缺失行失败：{exc}")
        conn.close()
        sys.exit(1)
    finally:
        conn.close()

    dates = [r[0] for r in rows]
    total = len(dates)
    print(f"sti_timeline 待回填 raw_break_rate：{total} 日")

    if args.dry_run:
        print("[dry-run] 日期列表（升序）：")
        for d in dates:
            print(f"  {d}")
        print(f"\n[dry-run] 未写库，共列出 {total} 日")
        return

    written = 0
    skipped = 0
    failed: list[str] = []

    for i, d in enumerate(dates, start=1):
        try:
            emotion = _emotion(d)
        except Exception as exc:
            print(f"  [WARN] {d}: market._emotion 抛异常 -> {exc}")
            failed.append(d)
            skipped += 1
            time.sleep(1.2)
            continue

        if not emotion:
            print(f"  {d}: skip（emotion 为空：非交易日/数据缺失）")
            skipped += 1
            time.sleep(1.2)
            continue

        br = emotion.get("break_rate")
        if br is None:
            # 同花顺降级源会返 break_rate=None；不臆造，跳过
            src = emotion.get("data_source")
            print(f"  {d}: skip（break_rate=None，source={src}）")
            skipped += 1
            time.sleep(1.2)
            continue

        try:
            br_val = float(br)
        except (TypeError, ValueError) as exc:
            print(f"  [WARN] {d}: break_rate 非数值 {br!r} -> {exc}")
            failed.append(d)
            skipped += 1
            time.sleep(1.2)
            continue

        try:
            conn = sqlite3.connect(STI_TIMELINE_DB_PATH)
            try:
                cur = conn.execute(
                    "UPDATE sti_timeline SET raw_break_rate=? WHERE date=? "
                    "AND raw_break_rate IS NULL",
                    (br_val, d),
                )
                conn.commit()
                affected = cur.rowcount
            finally:
                conn.close()
        except Exception as exc:
            print(f"  [WARN] {d}: UPDATE 失败 -> {exc}")
            failed.append(d)
            skipped += 1
            time.sleep(1.2)
            continue

        if affected > 0:
            written += 1
            print(f"  {d}: raw_break_rate={br_val} (zb/zt 聚合)")
        else:
            # affected=0：并发或已被其他进程写入；不计为失败
            skipped += 1
            print(f"  {d}: skip（UPDATE affected=0：行已非 NULL）")

        if i % 10 == 0:
            print(f"  [进度] {i}/{total}（写入 {written} / 跳过 {skipped}）")

        time.sleep(1.2)

    print(f"\n完成：写入 {written} / 跳过 {skipped} / 总 {total}")
    if failed:
        print(f"失败日期（{len(failed)}）：{', '.join(failed)}")


if __name__ == "__main__":
    main()
