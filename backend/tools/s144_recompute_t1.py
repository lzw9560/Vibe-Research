# -*- coding: utf-8 -*-
"""S144 Tier 1 R6 重算：对已存 forward_test_records/universe_returns 回填 o2nc + is_unbuyable。

非破坏性（UPDATE 现有 picks 的 return 列，不删 picks）。
对每个 signal_date：compute_returns_for_codes → record_actual_returns + record_universe_returns
→ 回填 return_open2next_close（T+1 可实现口径）+ is_unbuyable（一字板排除）+ is_win（buyable-only）。

用法：
  python tools/s144_recompute_t1.py [--limit N]   # N=处理的 signal_date 数（默认全部）
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from config import GENE_SCORES_DB_PATH
from strategies.forward_test import (
    _ensure_table, get_forward_test_summary,
    record_actual_returns, record_universe_returns,
)
from strategies.kline_returns import compute_returns_for_codes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("s144_recompute")


def main(limit: int | None = None) -> int:
    # 1. 迁移 schema（_ensure_table → _ensure_column ALTER 加列到 existing DB）
    _ensure_table()
    logger.info("schema 迁移完成（_ensure_table 加列）")

    import sqlite3
    conn = sqlite3.connect(GENE_SCORES_DB_PATH)
    try:
        # 取有 picks 但 o2nc 未回填的 signal_date（按日降序，优先近期）
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT signal_date FROM forward_test_records "
            "WHERE return_open2next_close IS NULL "
            "AND return_open2close IS NOT NULL "  # 已 settled（o2c 有），需补 o2nc
            "ORDER BY signal_date DESC"
        ).fetchall()]
    finally:
        conn.close()
    if limit:
        dates = dates[:limit]
    logger.info("待重算 signal_date 数=%d%s", len(dates), f"（limit={limit}）" if limit else "")

    if not dates:
        logger.info("无待重算日期（o2nc 已全回填或无 settled picks）")
    else:
        # baostock 可用性检查
        try:
            import baostock as bs  # noqa: F401
        except ImportError:
            logger.warning("baostock 未安装 → 无法重算（operational follow-up）")
            return 1

    for i, signal_date in enumerate(dates, 1):
        conn = sqlite3.connect(GENE_SCORES_DB_PATH)
        try:
            pick_codes = [r[0] for r in conn.execute(
                "SELECT DISTINCT code FROM forward_test_records WHERE signal_date=?", (signal_date,)).fetchall()]
            uni_codes = [r[0] for r in conn.execute(
                "SELECT DISTINCT code FROM universe_returns WHERE signal_date=?", (signal_date,)).fetchall()]
        finally:
            conn.close()
        all_codes = list(dict.fromkeys(pick_codes + uni_codes))
        if not all_codes:
            continue
        returns_map = compute_returns_for_codes(signal_date, all_codes)
        if not returns_map:
            logger.warning("[%d/%d] %s baostock 不可用，中断", i, len(dates), signal_date)
            break
        picks_returns = {c: returns_map[c] for c in pick_codes
                         if c in returns_map and returns_map[c]["return_open2close"] is not None}
        uni_returns = {c: returns_map[c] for c in uni_codes
                       if c in returns_map and returns_map[c]["return_open2close"] is not None}
        n_picks = record_actual_returns(signal_date, picks_returns)
        n_uni = record_universe_returns(signal_date, uni_returns)
        n_unbuyable_pick = sum(1 for c in pick_codes if c in returns_map and returns_map[c].get("is_unbuyable"))
        n_unbuyable_uni = sum(1 for c in uni_codes if c in returns_map and returns_map[c].get("is_unbuyable"))
        logger.info("[%d/%d] %s settled picks=%s/%s universe=%s/%s unbuyable(pick=%s uni=%s)",
                    i, len(dates), signal_date, n_picks, len(pick_codes), n_uni, len(uni_codes),
                    n_unbuyable_pick, n_unbuyable_uni)

    # 2. 打印 §44 verdict 双报
    print("\n" + "=" * 70)
    print("§44 forward_test 汇总（S144 Tier 1 后：buyable-only + o2nc 双报）")
    print("=" * 70)
    result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
    print(f"total_days={result.total_days} settled={result.settled_count}/{result.total_recommendations}")
    print(f"win_rate(o2c 基线)={result.win_rate}% avg_return={result.avg_return}%")
    print(f"random_baseline={result.random_baseline_win_rate}% (settled={result.random_settled})")
    print(f"lift(buyable-only o2c)={result.lift}x | lift_unfiltered(原口径含污染)={result.lift_unfiltered}x")
    print(f"win_rate_open2next_close(T+1 可实现)={result.win_rate_open2next_close}% (o2nc_settled={result.o2nc_settled})")
    print(f"unbuyable_count(一字板排除)={result.unbuyable_count}")
    print(f"validation_status={result.validation_status} passed={result.passed}")
    print(f"consecutive_loss={result.consecutive_loss}")
    print(f"note: {result.note}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None, help="处理 signal_date 数（默认全部）")
    args = p.parse_args()
    sys.exit(main(args.limit))
