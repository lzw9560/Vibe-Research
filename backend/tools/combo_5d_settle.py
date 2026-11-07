# -*- coding: utf-8 -*-
"""settle combo_5d paper 记录：T+5 到了的填 entry/exit/net_pnl + is_realized=1。

entry = bars[idx+1].open（T+1 开盘买，spec §5 次日集合竞价限价）
exit  = bars[idx+5].close（T+5 收盘卖，5 日持有 nostop）
net_pnl = (exit-entry)/entry*100 - 0.4（双边成本 0.4%）

bars[idx+5] 不存在 = T+5 未到，跳过（仍 pending，等下次 settle）。
基准对比注意：replay_check BACKTEST_MEANS=2.06 是 close-to-close 回测；
settle 用 T+1-open→T+5-close（实盘口径），高 gap 票 T+1 open 常高于 T close
→ 实盘 net 略低于 close-to-close 基准（spec §5 已注口径微调，alpha +1.8% 容错）。

用法：cd backend && .venv/bin/python tools/combo_5d_settle.py
"""

from __future__ import annotations
import json
import sqlite3
import sys
from pathlib import Path

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
KLINE_DB = resolve_data_dir() / "baostock_kline_cache.db"
COST_PCT = 0.4  # 双边成本 %


def settle_combo_5d() -> int:
    """settle 成熟的 combo_5d pending 记录（T+5 到了的）。返 settle 数。"""
    from engine.trade_journal import TradeJournal  # noqa: PLC0415

    tj = TradeJournal()
    conn = tj._conn()
    pending = conn.execute(
        "SELECT signal_id, stock_code, entry_date FROM trade_journal "
        "WHERE arm='combo_5d' AND (is_realized=0 OR is_realized IS NULL)"
    ).fetchall()
    if not pending:
        print("[settle] 无 combo_5d pending 记录")
        conn.close()
        return 0

    kconn = sqlite3.connect(str(KLINE_DB))
    settled = 0
    skipped = 0
    for row in pending:
        sig_id = row["signal_id"]
        code = row["stock_code"]
        entry_date = row["entry_date"]
        bj = kconn.execute("SELECT bars_json FROM kline WHERE code=?", (code,)).fetchone()
        if not bj:
            skipped += 1
            continue
        try:
            bars = json.loads(bj[0])
        except Exception:
            skipped += 1
            continue
        # 找 entry_date（信号日）的 bar idx
        idx = None
        for i, b in enumerate(bars):
            if b.get("date") == entry_date:
                idx = i
                break
        # 需 idx+5 < len（T+5 到了）+ idx+1 < len（T+1 有 bar）
        if idx is None or idx + 5 >= len(bars):
            skipped += 1  # T+5 未到 或 信号日无 bar
            continue
        entry_price = float(bars[idx + 1].get("open", 0) or 0)
        exit_bar = bars[idx + 5]
        exit_price = float(exit_bar.get("close", 0) or 0)
        exit_date = exit_bar.get("date", "")
        if not entry_price or not exit_price:
            skipped += 1
            continue
        net_pnl = (exit_price - entry_price) / entry_price * 100 - COST_PCT
        conn.execute(
            "UPDATE trade_journal SET entry_price=?, exit_price=?, exit_date=?, "
            "net_pnl=?, is_realized=1, exit_reason='nostop_t5_settled' "
            "WHERE signal_id=?",
            (entry_price, exit_price, exit_date, round(net_pnl, 4), sig_id),
        )
        settled += 1
    conn.commit()
    conn.close()
    kconn.close()
    print(f"[settle] {settled} settled, {skipped} skipped（T+5 未到/无数据）, {len(pending)} total pending")
    return settled


if __name__ == "__main__":
    settle_combo_5d()
