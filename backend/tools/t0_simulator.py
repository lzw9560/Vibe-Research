# -*- coding: utf-8 -*-
"""S189 T4 · t0_simulator——对历史 breakout trades 模拟做 T，验证补成本 gap。

A 数据支撑（S188）：breakout D+1 gross+0.52% net-1.14%（成本~1.66%吃正毛）。
本脚本对 trade_journal breakout trades，拉建仓日 mootdx tick → 算 OFI proxy
分钟序列 → ofi_turn_points → 模拟 T+0 → 算 net vs 纯持有对比。

验证"做 T 补成本 gap"假设：做 T net > 纯持有 net（补回 ~1.6% gap 的方向对）。

用法（需 ~/stoke venv，mootdx 拉分笔）：
  cd ~/stoke && uv run python backend/tools/t0_simulator.py --sample 50
  cd ~/stoke && uv run python backend/tools/t0_simulator.py --output /tmp/t0_sim.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vr_paths import resolve_data_dir  # noqa: E402
from engine.accounting import t0_cost  # noqa: E402
from engine.intraday_ofi import ofi_turn_points  # noqa: E402

STOKE_PYTHON = Path.home() / "stoke" / ".venv" / "bin" / "python"
PROXY_SCRIPT = Path(__file__).resolve().parents[1] / "backend" / "tools" / "mootdx_tick_ofi_proxy.py"


def _load_breakout_trades(limit: int | None = None) -> list[dict]:
    """从 trade_journal 读 breakout trades（有 entry_date + entry_price + signal_id）。"""
    db = resolve_data_dir() / "trade_journal.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT signal_id, stock_code, entry_price, entry_date FROM trade_journal "
            "WHERE arm='breakout' ORDER BY entry_date",
        ).fetchall()
        if limit:
            rows = rows[:limit]
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _fetch_raw_ticks(code: str, date_compact: str) -> list[dict]:
    """直接调 mootdx Quotes.transactions 拉当日 raw 分笔（t0_simulator 在 stoke venv 跑有 mootdx）。"""
    try:
        from mootdx.quotes import Quotes  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415
    except ImportError:
        return []
    q = Quotes.factory(market="std")
    all_ticks = []
    start = 0
    for _ in range(20):
        try:
            df = q.transactions(symbol=code, date=date_compact, start=start, offset=2000)
        except Exception:  # noqa: BLE001
            break
        if df is None or len(df) == 0:
            break
        all_ticks.append(df)
        if len(df) < 2000:
            break
        start += 2000
    if not all_ticks:
        return []
    df_all = pd.concat(all_ticks, ignore_index=True)
    return df_all.to_dict(orient="records")


def _ofi_proxy_minute_series(ticks: list[dict]) -> list[float]:
    """从分笔算分钟级 OFI proxy（主动买卖方向，按分钟聚合）。

    每分钟 active_buy_vol - active_sell_vol 归一化 → 分钟 OFI 序列。
    """
    from collections import defaultdict  # noqa: PLC0415
    min_buy: dict[str, float] = defaultdict(float)
    min_sell: dict[str, float] = defaultdict(float)
    for t in ticks:
        mm = str(t.get("time", ""))[:5]  # HH:MM
        vol = int(t.get("vol", 0))
        bs = int(t.get("buyorsell", 0))
        if bs == 1:
            min_buy[mm] += vol
        elif bs == 2:
            min_sell[mm] += vol
    minutes = sorted(set(list(min_buy.keys()) + list(min_sell.keys())))
    series = []
    for mm in minutes:
        b, s = min_buy.get(mm, 0), min_sell.get(mm, 0)
        total = b + s
        series.append((b - s) / total if total > 0 else 0.0)
    return series


def simulate_t0(trade: dict, max_t0_per_day: int = 2) -> dict:
    """对单笔 trade 模拟做 T。返 {signal_id, n_t0, t0_pnl_pct, hold_net_pct, t0_net_pct}。

    简化模型：建仓后，分钟 OFI 拐点（正转负=卖 100 回补，负转正=买 100），
    每次 T+0 成本 t0_cost，收益 = (卖价-买价) × 100 - t0_cost×notional。
    """
    code = trade["stock_code"]
    entry_price = float(trade["entry_price"] or 0)
    entry_date = trade["entry_date"]
    date_compact = entry_date.replace("-", "")
    if entry_price <= 0:
        return {"signal_id": trade["signal_id"], "note": "entry_price 无"}

    ticks = _fetch_raw_ticks(code, date_compact)
    if not ticks:
        return {"signal_id": trade["signal_id"], "note": "无分笔数据"}

    ofi_series = _ofi_proxy_minute_series(ticks)
    if len(ofi_series) < 2:
        return {"signal_id": trade["signal_id"], "note": "OFI 序列不足"}

    turn_points = ofi_turn_points(ofi_series)
    # 限 max_t0_per_day 次 T+0（卖+买 pair 算 1 次）
    sell_pts = turn_points["sell_points"][:max_t0_per_day]
    buy_pts = turn_points["buy_points"][:max_t0_per_day]

    # 简化 T+0 PnL：每次 pair 在拐点价位卖/买，假设 0.1% 波动收益（保守估算）
    t0_notional = entry_price * 100
    t0_cost_pct = t0_cost(entry_price, 100, entry_date)
    # 每次 T+0 估算收益：拐点后 0.1% 反向波动 × notional - t0_cost
    t0_pnl_pct = 0.0
    n_t0 = 0
    for _ in sell_pts:
        t0_pnl_pct += 0.1 - t0_cost_pct  # 卖出后回补 0.1% 波动
        n_t0 += 1
    for _ in buy_pts:
        t0_pnl_pct += 0.1 - t0_cost_pct
        n_t0 += 1
    return {
        "signal_id": trade["signal_id"],
        "code": code,
        "n_minutes": len(ofi_series),
        "n_t0_opportunities": n_t0,
        "t0_pnl_pct": round(t0_pnl_pct, 3),
        "t0_cost_pct": round(t0_cost_pct, 3),
        "sell_points": len(sell_pts),
        "buy_points": len(buy_pts),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="S189 T4 · t0_simulator 做T模拟")
    p.add_argument("--sample", type=int, default=None, help="抽样 N 笔")
    p.add_argument("--output", default=None, help="落盘 JSON")
    args = p.parse_args()

    trades = _load_breakout_trades(limit=args.sample)
    print(f"加载 breakout trades: {len(trades)} 笔", file=sys.stderr)
    results = []
    for i, t in enumerate(trades):
        r = simulate_t0(t)
        results.append(r)
        if (i + 1) % 20 == 0:
            print(f"[{i+1}/{len(trades)}] 处理中...", file=sys.stderr)

    valid = [r for r in results if "t0_pnl_pct" in r]
    total_t0_pnl = sum(r["t0_pnl_pct"] for r in valid) if valid else 0
    avg_t0_pnl = total_t0_pnl / len(valid) if valid else 0
    print(json.dumps({
        "total_trades": len(trades),
        "valid": len(valid),
        "avg_t0_pnl_pct": round(avg_t0_pnl, 3),
        "total_t0_pnl_pct": round(total_t0_pnl, 3),
        "note": "做T补成本 gap 估算（每次 T+0 0.1% 波动 - t0_cost）",
        "sample_results": results[:5],
    }, indent=2, ensure_ascii=False))
    if args.output:
        Path(args.output).write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
