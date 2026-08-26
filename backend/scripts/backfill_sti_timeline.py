"""STI timeline 历史回填脚本（2026-08-26，见 .scratch/sti-fix-timeline/issues/03）。

遍历 start→end 交易日，调 STIEngine.precompute_daily(d) 重算并落库 sti_timeline。
- dimension_*（limit_up_count/seal_rate/...）：push2ex 能查~1 个月历史 → 有值。
- zt_real：akshare legu 无历史 → 历史日 NULL（诚实，不臆造）；save_result 已改
  ON CONFLICT+COALESCE，重跑不覆盖当天跑的 zt_real 真值。
- 非交易日 / _emotion 返空日 → precompute_daily 返空 result 不 save → 无行（诚实）。

限流防封：每日间 sleep 1.2s（参考 backfill_raw_break_rate 范式）。
幂等：依赖 save_result 的 ON CONFLICT，重跑只补缺失行、不覆盖 zt_real。

手动触发：
    cd backend && .venv/bin/python -m scripts.backfill_sti_timeline
    cd backend && .venv/bin/python -m scripts.backfill_sti_timeline --start 2026-07-28 --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vr_paths import is_trading_day, last_trading_date_str  # noqa: E402
from limitup_sti.service import get_sti_engine  # noqa: E402


def _trading_days(start: str, end: str) -> list[str]:
    """枚举 start→end 间交易日（含端点），升序。"""
    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    end_d = datetime.strptime(end, "%Y-%m-%d").date()
    days: list[str] = []
    cur = start_d
    while cur <= end_d:
        if is_trading_day(cur):
            days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return days


def main() -> None:
    parser = argparse.ArgumentParser(
        description="回填 sti_timeline 历史交易日（precompute_daily，幂等不覆盖 zt_real）"
    )
    parser.add_argument(
        "--start", default="2026-07-28",
        help="起始日期 YYYY-MM-DD（默认 2026-07-28，migrations 应用日）",
    )
    parser.add_argument(
        "--end", default=None,
        help="结束日期 YYYY-MM-DD（默认最近交易日）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只打印将回填的交易日列表，不实际写库",
    )
    args = parser.parse_args()

    end = args.end or last_trading_date_str()
    days = _trading_days(args.start, end)
    total = len(days)
    print(f"sti_timeline 回填区间 {args.start} -> {end}：{total} 个交易日")

    if args.dry_run:
        print("[dry-run] 交易日列表（升序）：")
        for d in days:
            print(f"  {d}")
        print(f"\n[dry-run] 未写库，共列出 {total} 日")
        return

    engine = get_sti_engine()
    written = 0
    skipped = 0
    failed: list[str] = []

    for i, d in enumerate(days, start=1):
        try:
            result = engine.precompute_daily(d)
        except Exception as exc:
            print(f"  [WARN] {d}: precompute_daily 抛异常 -> {exc}")
            failed.append(d)
            skipped += 1
            time.sleep(1.2)
            continue

        # source_ok=False / score None：非交易日或 _emotion 返空（compute 返空 result 不 save）
        if not result.source_ok or result.score is None:
            print(f"  {d}: skip（无 emotion 数据 / 非交易日，未落库）")
            skipped += 1
            time.sleep(1.2)
            continue

        print(
            f"  {d}: score={result.score} "
            f"phase={result.phase.value if result.phase else None} "
            f"zt_real={result.zt_real}"
        )
        written += 1

        if i % 10 == 0:
            print(f"  [进度] {i}/{total}（写入 {written} / 跳过 {skipped}）")
        time.sleep(1.2)

    print(f"\n完成：写入 {written} / 跳过 {skipped} / 总 {total}")
    if failed:
        print(f"失败日期（{len(failed)}）：{', '.join(failed)}")


if __name__ == "__main__":
    main()
