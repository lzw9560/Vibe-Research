# -*- coding: utf-8 -*-
"""S145 R6 path-dependent 重算：回填 forward_test_records/universe_returns 的 path 列。

继承 s144_recompute_t1（o2nc/is_unbuyable 回填）+ 加 path（SL/TP/max_hold 模拟）。
- picks：用其 strategy_code 对应 STRATEGY_REGISTRY params 算 path（每 code 取首个战法）。
- universe：用 DEFAULT_PATH_PARAMS（-3%/+8%/3）算 path（path-lift 基准分母）。

非破坏性（UPDATE existing picks 的 return 列，不删 picks）。
用法：python tools/s145_recompute_path.py [--limit N]
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
from strategies.kline_returns import compute_returns_for_codes, strategy_params_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("s145_recompute")


def main(limit: int | None = None) -> int:
    _ensure_table()
    logger.info("schema 迁移完成（path 列已加）")

    import sqlite3
    conn = sqlite3.connect(GENE_SCORES_DB_PATH)
    try:
        # path 未回填的 signal_date（return_path IS NULL 且 o2c 已 settled）
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT signal_date FROM forward_test_records "
            "WHERE return_path IS NULL AND return_open2close IS NOT NULL "
            "ORDER BY signal_date DESC"
        ).fetchall()]
    finally:
        conn.close()
    if limit:
        dates = dates[:limit]
    logger.info("待重算 signal_date 数=%d%s", len(dates), f"（limit={limit}）" if limit else "")

    if not dates:
        logger.info("无待重算日期")
    else:
        try:
            import baostock as bs  # noqa: F401
        except ImportError:
            logger.warning("baostock 未安装 → 无法重算")
            return 1

    for i, signal_date in enumerate(dates, 1):
        conn = sqlite3.connect(GENE_SCORES_DB_PATH)
        try:
            # picks: code + strategy_code（取首个战法 params）；build strategy_params_map
            pick_rows = conn.execute(
                "SELECT code, strategy_code FROM forward_test_records WHERE signal_date=?",
                (signal_date,)).fetchall()
            uni_codes = [r[0] for r in conn.execute(
                "SELECT DISTINCT code FROM universe_returns WHERE signal_date=?", (signal_date,)).fetchall()]
        finally:
            conn.close()
        # 每 code 取首个战法 params（多战法同 code 时 record_actual_returns 按 code UPDATE 全行同 path）
        strategy_params_map: dict[str, dict] = {}
        pick_codes: list[str] = []
        for code, sc in pick_rows:
            pick_codes.append(code)
            if code not in strategy_params_map and sc:
                strategy_params_map[code] = strategy_params_for(sc)
        all_codes = list(dict.fromkeys(pick_codes + uni_codes))
        if not all_codes:
            continue
        returns_map = compute_returns_for_codes(signal_date, all_codes, strategy_params_map=strategy_params_map)
        if not returns_map:
            logger.warning("[%d/%d] %s baostock 不可用，中断", i, len(dates), signal_date)
            break
        picks_returns = {c: returns_map[c] for c in pick_codes
                         if c in returns_map and returns_map[c]["return_open2close"] is not None}
        uni_returns = {c: returns_map[c] for c in uni_codes
                       if c in returns_map and returns_map[c]["return_open2close"] is not None}
        n_picks = record_actual_returns(signal_date, picks_returns)
        n_uni = record_universe_returns(signal_date, uni_returns)
        n_path_pick = sum(1 for c in pick_codes if c in returns_map and returns_map[c].get("return_path") is not None)
        n_path_uni = sum(1 for c in uni_codes if c in returns_map and returns_map[c].get("return_path") is not None)
        logger.info("[%d/%d] %s picks=%s/%s uni=%s/%s path_settled(pick=%s uni=%s)",
                    i, len(dates), signal_date, n_picks, len(pick_codes), n_uni, len(uni_codes),
                    n_path_pick, n_path_uni)

    print("\n" + "=" * 70)
    print("§44 forward_test 汇总（S145 Tier 2 后：三口径 + path-dependent gate）")
    print("=" * 70)
    result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
    print(f"total_days={result.total_days} settled(o2c)={result.settled_count}/{result.total_recommendations}")
    print(f"[o2c endpoint] win_rate={result.win_rate}% lift(buyable-only)={result.lift}x | lift_unfiltered={result.lift_unfiltered}x")
    print(f"[o2nc T+1] win_rate_open2next_close={result.win_rate_open2next_close}% (o2nc_settled={result.o2nc_settled})")
    print(f"[path-dependent] win_rate_path={result.win_rate_path}% (path_settled={result.path_settled}) "
          f"| random_path={result.random_win_rate_path}% (settled={result.random_path_settled}) "
          f"| path_lift={result.path_lift}x  ← §44 真·gate")
    print(f"unbuyable_count={result.unbuyable_count} validation_status={result.validation_status} passed={result.passed}")
    print(f"note: {result.note}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    sys.exit(main(args.limit))
