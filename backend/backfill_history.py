# -*- coding: utf-8 -*-
"""S040 · 历史回填脚本 —— 逐日补齐涨停池基因得分（gene_scores DB）。

用法：
    python backfill_history.py --days 10 --dry-run          # 只探测，不写 DB
    python backfill_history.py --days 10                    # 回填 DB 最早日期之前 10 个交易日
    python backfill_history.py --start 2026-05-10 --end 2026-05-20
    python backfill_history.py --days 90 --batch-size 10 --no-confirm

流程（正式模式）：逐日调 limitup_screener.get_screener_result(date)，
内部走 data/transport.py 限流层写 gene_scores DB（PK(date,code) + INSERT OR REPLACE 幂等）。
空池日（非交易日/节假日）跳过计数，不污染覆盖统计。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import GENE_SCORES_DB_PATH  # noqa: E402  (S037 路径)


# ── 交易日枚举 ────────────────────────────────────────────────

def _load_holidays() -> set[str]:
    """从 data/trading_calendar.json 加载节假日；缺失返空（降级为仅跳周末）。"""
    try:
        cal_file = Path(__file__).resolve().parent / "data" / "trading_calendar.json"
        if cal_file.exists():
            return set(json.loads(cal_file.read_text(encoding="utf-8")).get("holidays", []))
    except Exception:
        pass
    return set()


def trading_days_back(end_date: str, n: int) -> list[str]:
    """从 end_date（含）往前枚举 n 个交易日，返回按时间升序的日期列表（YYYY-MM-DD）。"""
    holidays = _load_holidays()
    out: list[str] = []
    d = datetime.strptime(end_date, "%Y-%m-%d")
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() >= 5:  # 周末
            continue
        ds = d.strftime("%Y-%m-%d")
        if ds in holidays:
            continue
        out.append(ds)
    return list(reversed(out))


def trading_days_between(start_date: str, end_date: str) -> list[str]:
    """枚举 [start_date, end_date] 区间内的交易日（升序）。"""
    holidays = _load_holidays()
    out: list[str] = []
    d = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while d <= end:
        if d.weekday() < 5 and d.strftime("%Y-%m-%d") not in holidays:
            out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


# ── DB 查询（只读统计）────────────────────────────────────────

def db_stats(db_path: str | None = None) -> tuple[int, str | None, str | None]:
    """返回 (总行数, 最早日期, 最晚日期)。DB 不存在/空表返 (0, None, None)。"""
    path = db_path or GENE_SCORES_DB_PATH
    try:
        conn = sqlite3.connect(path, timeout=10)
        row = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM gene_scores").fetchone()
        conn.close()
        return int(row[0]), row[1], row[2]
    except Exception:
        return 0, None, None


def existing_dates(db_path: str | None = None) -> set[str]:
    """返回 DB 中已有数据的日期集合（用于幂等跳过）。"""
    path = db_path or GENE_SCORES_DB_PATH
    try:
        conn = sqlite3.connect(path, timeout=10)
        rows = conn.execute("SELECT DISTINCT date FROM gene_scores").fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


def db_earliest_date(db_path: str | None = None) -> str | None:
    """DB 最早日期（YYYY-MM-DD），空库返 None。"""
    _, earliest, _ = db_stats(db_path)
    return earliest


# ── 熔断器感知 ────────────────────────────────────────────────

def breaker_state() -> str:
    """读取东财熔断器当前状态（peek 不消耗试探名额）。"""
    try:
        from circuit_breaker import get_breaker
        return get_breaker("eastmoney").peek_state().value
    except Exception as exc:  # noqa: BLE001
        return f"unknown({exc})"


# ── 核心回填 ──────────────────────────────────────────────────

async def backfill_dates(
    dates: list[str],
    dry_run: bool = False,
    force: bool = False,
    batch_size: int = 10,
    no_confirm: bool = False,
    db_path: str | None = None,
    source: str = "eastmoney",
) -> dict[str, int]:
    """逐日回填。返回统计 dict：success/skipped_existing/empty_pool/failed。

    source:
        "eastmoney"（默认）：调 get_screener_result（完整5因子，窗口约4周）
        "kline"：调 kline_rebuild.rebuild_date（K线重建3因子降级，可回溯数年）
    --dry-run 只探测（eastmoney 模式探测涨停池，kline 模式跳过写DB）。
    """
    import astock
    import limitup_screener as ls
    from limitup_screener.kline_rebuild import rebuild_date as _rebuild
    from limitup_screener.data import save_gene_scores as _save_kline

    already = existing_dates(db_path) if not force else set()
    stats = {"success": 0, "skipped_existing": 0, "empty_pool": 0, "failed": 0}
    consecutive_failures = 0

    # kline 模式：获取 codes 列表（从 DB 取或全市场扫）
    kline_codes = None
    if source == "kline" and not dry_run:
        from limitup_screener.data import get_db as _get_db
        try:
            conn = _get_db()
            rows = conn.execute("SELECT DISTINCT code FROM gene_scores").fetchall()
            conn.close()
            kline_codes = [r[0] for r in rows]
        except Exception:
            kline_codes = []

    for i, date in enumerate(dates):
        if date in already and not force:
            stats["skipped_existing"] += 1
            print(f"[{i + 1}/{len(dates)}] {date} 已有数据，跳过（--force 强制重算）")
            continue

        # 交易日守卫（P0-3）：东财涨停池对非交易日请求静默回退返回最近交易日数据，
        # 不报错不返空，会误判"该日有数据"并把错位数据入库。这里独立校验，
        # 即便上游 trading_days_* 节假日表与 vr_paths 不同步也能拦住。非交易日直接跳过，不打东财。
        try:
            from vr_paths import is_trading_day as _is_trading_day
            d_obj = datetime.strptime(date, "%Y-%m-%d").date()
            if not _is_trading_day(d_obj):
                stats["empty_pool"] += 1
                print(f"[{i + 1}/{len(dates)}] {date} 非交易日（周末/节假日），跳过")
                continue
        except Exception:
            # vr_paths 不可用时不阻断回填（保守：仅日志），交由上游预过滤兜底
            pass

        start_ts = time.time()
        try:
            if dry_run:
                if source == "kline":
                    # kline 模式 dry-run：跳过（重建逻辑不探测，直接标 skip）
                    stats["empty_pool"] += 1
                    print(f"[{i + 1}/{len(dates)}] {date} kline dry-run 跳过")
                else:
                    pool = await asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZTPool", date.replace("-", ""))
                    elapsed = time.time() - start_ts
                    if pool:
                        stats["success"] += 1
                        consecutive_failures = 0
                        print(f"[{i + 1}/{len(dates)}] {date} 探测成功 池={len(pool)} 只 耗时={elapsed:.1f}s")
                    else:
                        stats["empty_pool"] += 1
                        print(f"[{i + 1}/{len(dates)}] {date} 空池（非交易日或无数据）")
            elif source == "kline":
                scores = await _rebuild(date, codes=kline_codes)
                elapsed = time.time() - start_ts
                if scores:
                    _save_kline(date, scores)
                    stats["success"] += 1
                    consecutive_failures = 0
                    print(f"[{i + 1}/{len(dates)}] {date} K线重建成功 {len(scores)} 条 耗时={elapsed:.1f}s")
                else:
                    stats["empty_pool"] += 1
                    print(f"[{i + 1}/{len(dates)}] {date} K线重建空（无涨停股或无K线）")
            else:
                result = await ls.get_screener_result(date)
                elapsed = time.time() - start_ts
                count = len(result.gene_scores)
                if count > 0:
                    stats["success"] += 1
                    consecutive_failures = 0
                    print(f"[{i + 1}/{len(dates)}] {date} 回填成功 {count} 条基因 耗时={elapsed:.1f}s")
                else:
                    stats["empty_pool"] += 1
                    print(f"[{i + 1}/{len(dates)}] {date} 空池（非交易日或无数据）")
        except Exception as exc:  # noqa: BLE001
            stats["failed"] += 1
            consecutive_failures += 1
            state = breaker_state()
            print(f"[{i + 1}/{len(dates)}] {date} 失败: {exc} 熔断器={state}")
            if consecutive_failures >= batch_size:
                print(f"连续 {batch_size} 次失败，熔断器={breaker_state()}，中止回填")
                break

        # 批间暂停（仅正式模式、交互确认）
        if (
            not dry_run
            and not no_confirm
            and i > 0
            and (i + 1) % batch_size == 0
            and i + 1 < len(dates)
        ):
            state = breaker_state()
            if state == "open":
                print(f"熔断器 OPEN，等待 65s 恢复后继续……")
                await asyncio.sleep(65)
            answer = input(f"批次 {i + 1}/{len(dates)} 完成，继续下一批？[y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                print("用户中止")
                break

    return stats


def _print_summary(stats: dict[str, int], db_path: str | None) -> None:
    total, earliest, latest = db_stats(db_path)
    print()
    print("=" * 60)
    print(f"回填完成：成功 {stats['success']} | 已有跳过 {stats['skipped_existing']}"
          f" | 空池 {stats['empty_pool']} | 失败 {stats['failed']}")
    print(f"DB 覆盖：{earliest or '?'} ~ {latest or '?'} · 共 {total} 行 · {len(existing_dates(db_path))} 个交易日")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="S040 基因得分历史回填")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--days", type=int, help="从 DB 最早日期往前补 N 个交易日")
    group.add_argument("--range", nargs=2, metavar=("START", "END"),
                       help="显式日期范围 YYYY-MM-DD YYYY-MM-DD（含端点）")
    parser.add_argument("--dry-run", action="store_true", help="只探测涨停池，不写 DB")
    parser.add_argument("--force", action="store_true", help="强制重算已有日期")
    parser.add_argument("--batch-size", type=int, default=10, help="批大小（连续失败达此数中止，默认 10）")
    parser.add_argument("--no-confirm", action="store_true", help="跳过批间交互确认")
    parser.add_argument("--db", default=None, help="DB 路径（默认 config.GENE_SCORES_DB_PATH，测试用）")
    parser.add_argument("--source", choices=["eastmoney", "kline"], default="eastmoney",
                        help="数据源：eastmoney（默认，完整5因子，窗口约4周）/ kline（K线重建3因子降级，可回溯数年）")
    args = parser.parse_args()

    if args.range:
        dates = trading_days_between(args.range[0], args.range[1])
    else:
        earliest = db_earliest_date(args.db)
        if earliest is None:
            today = datetime.now().strftime("%Y-%m-%d")
            dates = trading_days_back(today, args.days)
        else:
            # 从最早日期前一天开始往前补 N 个交易日
            prev = (datetime.strptime(earliest, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
            dates = trading_days_back(prev, args.days)

    print(f"目标日期：{dates[0]} ~ {dates[-1]}（{len(dates)} 个交易日，dry_run={args.dry_run}，source={args.source}）")
    total_before, earliest, latest = db_stats(args.db)
    print(f"回填前 DB：{earliest or '?'} ~ {latest or '?'} · {total_before} 行")

    stats = asyncio.run(backfill_dates(
        dates,
        dry_run=args.dry_run,
        force=args.force,
        batch_size=args.batch_size,
        no_confirm=args.no_confirm,
        db_path=args.db,
        source=args.source,
    ))
    _print_summary(stats, args.db)


if __name__ == "__main__":
    main()
