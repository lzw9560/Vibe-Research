# -*- coding: utf-8 -*-
"""S145 Tier 3 敏感性分析：path_lift 在不同 SL/TP/max_hold params 下是否 robust <1？

当前 path_lift=0.978x（picks 各战法 params + universe 默认 -3/+8/3）——方法论依赖。
此脚本：picks + universe 用**相同 params**（隔离 selection edge），多组 params 对比。
fetch bars 一次/（code,date），多 params 复用 simulate_holding（快，无网络）。

用法：python tools/s145_sensitivity.py [--sample N]   # N=采样 signal_date 数（默认 12）
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
from strategies.kline_returns import fetch_klines, _bs_code, _match_next_bar, simulate_holding
from strategies.forward_test import _ensure_table

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("s145_sensitivity")

# 多组 params（覆盖紧/松止损、短/长持仓、战法实际值）——picks+universe 同用，隔离 selection
PARAM_SETS = [
    {"name": "first_plate(-3/+8/3)", "stop_pct": -3.0, "take_profit_pct": 8.0, "max_hold_days": 3},
    {"name": "consecutive_relay(-5/+12/2)", "stop_pct": -5.0, "take_profit_pct": 12.0, "max_hold_days": 2},
    {"name": "break_reseal(-3/+6/1)", "stop_pct": -3.0, "take_profit_pct": 6.0, "max_hold_days": 1},
    {"name": "looser(-7/+15/5)", "stop_pct": -7.0, "take_profit_pct": 15.0, "max_hold_days": 5},
    {"name": "low_absorption(-5/+10/5)", "stop_pct": -5.0, "take_profit_pct": 10.0, "max_hold_days": 5},
]


def main(sample: int = 12) -> int:
    _ensure_table()
    try:
        import baostock as bs
    except ImportError:
        logger.warning("baostock 未安装"); return 1

    import sqlite3
    conn = sqlite3.connect(GENE_SCORES_DB_PATH)
    try:
        # 采样有 path 数据的 signal_date（近期）
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT signal_date FROM forward_test_records "
            "WHERE return_path IS NOT NULL ORDER BY signal_date DESC LIMIT ?", (sample,)).fetchall()]
        # 每 date 的 pick codes + universe codes
        date_codes: dict[str, tuple[list, list]] = {}
        for d in dates:
            picks = [r[0] for r in conn.execute(
                "SELECT DISTINCT code FROM forward_test_records WHERE signal_date=? AND return_path IS NOT NULL",
                (d,)).fetchall()]
            unis = [r[0] for r in conn.execute(
                "SELECT DISTINCT code FROM universe_returns WHERE signal_date=? AND return_open2close IS NOT NULL",
                (d,)).fetchall()]
            date_codes[d] = (picks, unis)
    finally:
        conn.close()
    logger.info("采样 %d dates", len(dates))

    lg = bs.login()
    if getattr(lg, "error_code", "0") != "0":
        logger.warning("baostock login 失败"); return 1

    from datetime import datetime, timedelta
    # 收集所有 (date, code) 的 bars（fetch 一次，多 params 复用）
    bars_cache: dict[tuple, list] = {}
    try:
        for d in dates:
            dt = datetime.strptime(d, "%Y-%m-%d")
            start = (dt - timedelta(days=5)).strftime("%Y-%m-%d")
            end = datetime.now().strftime("%Y-%m-%d")
            picks, unis = date_codes[d]
            for code in set(picks + unis):
                bsc = _bs_code(code)
                if not bsc:
                    continue
                bars_cache[(d, code)] = fetch_klines(bsc, start, end)
    finally:
        bs.logout()
    logger.info("bars 缓存完成（%d 条），开始多 params 模拟", len(bars_cache))

    # 每 params 下算 picks + universe path-winrate + path_lift
    print("\n" + "=" * 80)
    print(f"敏感性分析：path_lift 在不同 params 下（picks+universe 同 params，隔离 selection）")
    print(f"采样 {len(dates)} dates；当前 DB path_lift=0.978x（picks 战法 params + universe -3/+8/3）")
    print("=" * 80)
    print(f"{'params':<32} {'pick_wr':<10} {'uni_wr':<10} {'path_lift':<10} {'<1?':<6}")
    print("-" * 80)
    for P in PARAM_SETS:
        pick_wins = pick_settled = uni_wins = uni_settled = 0
        for d in dates:
            picks, unis = date_codes[d]
            for code in picks:
                bars = bars_cache.get((d, code))
                if not bars:
                    continue
                sim = simulate_holding(bars, d, P["stop_pct"], P["take_profit_pct"], P["max_hold_days"])
                if sim is not None:
                    pick_settled += 1
                    if sim["won"]:
                        pick_wins += 1
            for code in unis:
                bars = bars_cache.get((d, code))
                if not bars:
                    continue
                sim = simulate_holding(bars, d, P["stop_pct"], P["take_profit_pct"], P["max_hold_days"])
                if sim is not None:
                    uni_settled += 1
                    if sim["won"]:
                        uni_wins += 1
        pick_wr = round(pick_wins / pick_settled * 100, 2) if pick_settled else 0.0
        uni_wr = round(uni_wins / uni_settled * 100, 2) if uni_settled else 0.0
        pl = round(pick_wr / uni_wr, 3) if uni_wr else 0.0
        print(f"{P['name']:<32} {pick_wr:<10} {uni_wr:<10} {pl:<10} {'Y' if pl < 1 else 'N':<6}")
    print("-" * 80)
    print("若所有 params path_lift<1 → selection 劣于随机 robust（不依赖出场规则）")
    print("若部分 >1 → path_lift 方法论依赖（出场规则影响结论）")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--sample", type=int, default=12)
    args = p.parse_args()
    sys.exit(main(args.sample))
