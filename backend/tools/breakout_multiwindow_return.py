# -*- coding: utf-8 -*-
"""S188 A · breakout 多窗口 holding-return harness。

用户决策（2026-09-12）：breakout 不看涨停 selection lift（§44 已证否 1.36x<2x），
改测**短期持有净收益**——breakout 信号建仓后 D+1/D+2/D+3/D+5 close-to-close 净 return
（扣 accounting._cost_pct round-trip 成本）。回答"breakout 建仓持有 N 日扣成本赚不赚钱"+ 哪窗口最优。

§44 v2「前置窗口 sanity」落地：多窗口多 outcome 测了再下结论，非"D+1 涨停率<2x 就否"。

数据：trade_journal breakout 1040 笔（07-01~09-10）entry_date/code/entry_price + baostock 日 K（有历史，非 seal_time 墙）+ accounting._cost_pct。

用法：
  python tools/breakout_multiwindow_return.py                  # 全量跑
  python tools/breakout_multiwindow_return.py --sample 50      # 50 笔抽样
  python tools/breakout_multiwindow_return.py --dry-run        # 不落盘只 print
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vr_paths import resolve_data_dir  # noqa: E402
from engine.accounting import _cost_pct  # noqa: E402

WINDOWS = [1, 2, 3, 5]  # D+N close-to-close
SAMPLE_BATCH = 20  # baostock 并发（_BAOSTOCK_LOCK 串行，故实际顺序）
BAOSTOCK_LOCK = None  # lazy


def _load_breakout_trades(limit: int | None = None) -> list[dict]:
    """从 trade_journal 读 breakout 全部 trades。"""
    db = resolve_data_dir() / "trade_journal.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT signal_id, stock_code, entry_price, entry_date "
            "FROM trade_journal WHERE arm='breakout' ORDER BY entry_date",
        ).fetchall()
        if limit:
            rows = rows[:limit]
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _baostock_bars(code: str) -> list[dict]:
    """baostock 日 K（sh.6/sz.0/sz.3）。返 [{date,open,high,low,close,...}]。"""
    try:
        from engine.bars_provider import _baostock_a_share_hist  # noqa: PLC0415
    except ImportError:
        return []
    raw = _baostock_a_share_hist(code)
    if not raw:
        return []
    # _baostock_a_share_hist 返最近 400 天；过滤 entry 前后够用
    return [{**d, "date": str(d.get("date", ""))[:10]} for d in raw]


def _window_return(entry_price: float, entry_date: str, bars: list[dict], n: int) -> tuple[float, float | None]:
    """D+N close-to-close gross return%（用 entry_price 当 D 日 close 参照，找 D+N 的 close）。

    返 (gross_return_pct, d_plus_n_close)。无 D+N bar → (0.0, None)。
    """
    # 找 entry_date 在 bars 的 idx
    idx = next((i for i, b in enumerate(bars) if b.get("date") == entry_date), None)
    if idx is None:
        # entry_date 不在 baostock bars（可能停牌/新股/日期边界）→ 用最近 <= entry 的 bar
        idx = next((i for i, b in enumerate(bars) if b.get("date", "") <= entry_date), None)
        if idx is None:
            return 0.0, None
    target_idx = idx + n
    if target_idx >= len(bars):
        return 0.0, None  # D+N 超出 bars 范围（近期 entry 还没到 D+N）
    d_plus_n_close = float(bars[target_idx].get("close", 0) or 0)
    if d_plus_n_close <= 0 or entry_price <= 0:
        return 0.0, None
    gross = (d_plus_n_close - entry_price) / entry_price * 100
    return gross, d_plus_n_close


def wilson_lower_bound(wins: int, n: int, z: float = 1.96) -> float:
    """Wilson 下界（胜率诚实，小 n 不通胀）。"""
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return max(0.0, center - margin)


async def _run(trades: list[dict], dry_run: bool = False) -> dict:
    """逐 trade 拉 baostock bars → 各窗口 net return → 聚合。"""
    # 窗口聚合
    agg: dict[int, dict] = {n: {"returns": [], "net_returns": [], "wins": 0, "n": 0, "missing": 0} for n in WINDOWS}

    for i, t in enumerate(trades):
        code = t["stock_code"]
        ep = t["entry_price"]
        if ep is None:
            for n in WINDOWS:
                agg[n]["missing"] += 1
            continue
        entry_price = float(ep)
        entry_date = t["entry_date"]
        bars = await asyncio.to_thread(_baostock_bars, code)
        if not bars:
            for n in WINDOWS:
                agg[n]["missing"] += 1
            continue
        cost = _cost_pct(entry_price, 100.0, entry_date)  # size=100（1 手，触发最低佣金）
        for n in WINDOWS:
            gross, d_plus_n_close = _window_return(entry_price, entry_date, bars, n)
            if d_plus_n_close is None:
                agg[n]["missing"] += 1
                continue
            net = gross - cost
            agg[n]["returns"].append(gross)
            agg[n]["net_returns"].append(net)
            agg[n]["n"] += 1
            if net > 0:
                agg[n]["wins"] += 1
        if (i + 1) % 100 == 0:
            print(f"[{i+1}/{len(trades)}] 处理中...", file=sys.stderr)

    # 聚合统计
    results = {}
    for n in WINDOWS:
        a = agg[n]
        nets = a["net_returns"]
        if not nets:
            results[f"D+{n}"] = {"n": 0, "missing": a["missing"], "note": "无数据"}
            continue
        mean_net = sum(nets) / len(nets)
        win_rate = a["wins"] / len(nets)
        wilson_lb = wilson_lower_bound(a["wins"], len(nets))
        results[f"D+{n}"] = {
            "n": len(nets),
            "missing": a["missing"],
            "mean_gross_return_pct": round(sum(a["returns"]) / len(nets), 3),
            "mean_net_return_pct": round(mean_net, 3),
            "cost_pct": round(_cost_pct(50.0, 100.0, ""), 3),  # 参考成本（entry=50 估算）
            "win_rate": round(win_rate * 100, 2),
            "wilson_lower_bound_winrate": round(wilson_lb * 100, 2),
            "t_stat": round(mean_net / ((sum((x - mean_net) ** 2 for x in nets) / len(nets)) ** 0.5 / (len(nets) ** 0.5)), 3) if len(nets) > 1 else None,
        }

    out = {
        "total_trades": len(trades),
        "windows": results,
        "summary": "breakout 建仓持有 N 日扣成本净收益（多窗口 holding-return，非涨停 selection lift）",
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))

    if not dry_run:
        out_path = resolve_data_dir() / "breakout_multiwindow_return.json"
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n落盘: {out_path}", file=sys.stderr)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="S188 A · breakout 多窗口 holding-return")
    p.add_argument("--sample", type=int, default=None, help="抽样 N 笔（默认全量 1040）")
    p.add_argument("--dry-run", action="store_true", help="不落盘")
    args = p.parse_args()

    trades = _load_breakout_trades(limit=args.sample)
    print(f"加载 breakout trades: {len(trades)} 笔", file=sys.stderr)
    asyncio.run(_run(trades, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
